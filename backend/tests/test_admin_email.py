from __future__ import annotations

import json
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

import api.routes.admin.email as email_route
from api.main import app
from db import SessionLocal
from models import EmailSettings, Event, User
from services import auth
from services.email_delivery import EmailDeliveryError, EmailDeliveryErrorCode
from services.secret_encryption import (
    ENCRYPTION_KEY_ENVIRONMENT_VARIABLE,
    decrypt_secret,
)


client = TestClient(app)


def _create_user_headers(*, roles: list[str]) -> tuple[dict[str, str], uuid.UUID, str]:
    settings = auth.get_auth_settings()
    with SessionLocal() as session:
        user = User(
            user_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            email=f"{roles[0]}-{uuid.uuid4()}@example.com",
            password_hash=auth.hash_password("strong-password-123"),
            is_active=True,
        )
        session.add(user)
        session.commit()

        token, _ = auth.create_access_token(
            settings=settings,
            user_id=user.user_id,
            org_id=user.org_id,
            roles=roles,
            scopes=auth.scopes_from_roles(roles),
        )
        return {"Authorization": f"Bearer {token}"}, user.user_id, user.email


def _complete_payload(**overrides) -> dict:
    payload = {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_security_mode": "starttls",
        "smtp_username": "smtp-user",
        "smtp_password": "smtp-secret-value",
        "from_email": "sender@example.com",
        "from_display_name": "CompassAQ Alerts",
        "reply_to_email": "support@example.com",
        "administrator_recipients": ["primary@example.com", "backup@example.com"],
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def clean_email_configuration(monkeypatch):
    encryption_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv(ENCRYPTION_KEY_ENVIRONMENT_VARIABLE, encryption_key)
    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.email"))
        session.execute(delete(EmailSettings))
        session.commit()
    yield encryption_key
    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.email"))
        session.execute(delete(EmailSettings))
        session.commit()


def _email_events() -> list[Event]:
    with SessionLocal() as session:
        return list(
            session.execute(
                select(Event)
                .where(Event.source == "admin.email")
                .order_by(Event.event_id)
            )
            .scalars()
            .all()
        )


def test_get_configuration_creates_safe_singleton_response():
    admin_headers, _, _ = _create_user_headers(roles=["admin"])

    response = client.get("/admin/email/configuration", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "not_configured"
    assert response.json()["password_configured"] is False
    assert "smtp_password" not in response.json()
    assert "smtp_password_ciphertext" not in response.json()
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(EmailSettings)) == 1


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/admin/email/configuration", None),
        ("put", "/admin/email/configuration", _complete_payload()),
        ("post", "/admin/email/test", {}),
    ],
)
def test_email_endpoints_require_users_write_scope(method, path, json_body):
    viewer_headers, _, _ = _create_user_headers(roles=["viewer"])

    unauthenticated = client.request(method, path, json=json_body)
    forbidden = client.request(method, path, json=json_body, headers=viewer_headers)

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403


def test_update_encrypts_password_returns_only_configured_flag_and_logs_actor(
    clean_email_configuration,
):
    admin_headers, admin_user_id, admin_email = _create_user_headers(roles=["admin"])
    payload = _complete_payload()

    response = client.put(
        "/admin/email/configuration", json=payload, headers=admin_headers
    )

    assert response.status_code == 200, response.text
    response_text = response.text
    response_payload = response.json()
    assert response_payload["password_configured"] is True
    assert response_payload["status"] == "needs_attention"
    assert response_payload["status_reason_codes"] == ["test_required"]
    assert "smtp_password" not in response_payload
    assert "smtp_password_ciphertext" not in response_payload
    assert payload["smtp_password"] not in response_text

    with SessionLocal() as session:
        saved = session.get(EmailSettings, 1)
        assert saved is not None
        assert saved.smtp_password_ciphertext != payload["smtp_password"]
        assert decrypt_secret(saved.smtp_password_ciphertext) == payload["smtp_password"]
        event = session.execute(
            select(Event).where(Event.source == "admin.email")
        ).scalar_one()
        assert event.event_type == "email.configuration.updated"
        assert event.actor_user_id == admin_user_id
        assert event.actor_email == admin_email
        assert event.params["password_action"] == "configured"
        assert "smtp_password" in event.params["changed_fields"]
        serialized_event = json.dumps(event.params) + (event.message or "")
        assert payload["smtp_password"] not in serialized_event
        assert saved.smtp_password_ciphertext not in serialized_event


def test_omitted_password_preserves_ciphertext_without_decrypting_it(
    monkeypatch, clean_email_configuration
):
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    first_response = client.put(
        "/admin/email/configuration",
        json=_complete_payload(),
        headers=admin_headers,
    )
    assert first_response.status_code == 200
    with SessionLocal() as session:
        original_ciphertext = session.get(EmailSettings, 1).smtp_password_ciphertext

    monkeypatch.delenv(ENCRYPTION_KEY_ENVIRONMENT_VARIABLE)
    update_without_password = _complete_payload(from_display_name="Updated sender")
    update_without_password.pop("smtp_password")
    response = client.put(
        "/admin/email/configuration",
        json=update_without_password,
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["password_configured"] is True
    assert response.json()["status_reason_codes"] == ["smtp_secret_unavailable"]
    with SessionLocal() as session:
        assert session.get(EmailSettings, 1).smtp_password_ciphertext == original_ciphertext


def test_null_password_clears_it_and_invalid_password_errors_never_echo_value():
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    assert client.put(
        "/admin/email/configuration",
        json=_complete_payload(),
        headers=admin_headers,
    ).status_code == 200

    clear_payload = _complete_payload(smtp_username=None, smtp_password=None)
    clear_response = client.put(
        "/admin/email/configuration", json=clear_payload, headers=admin_headers
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["password_configured"] is False

    invalid_secret = "unsafe-secret-that-must-not-be-returned"
    invalid_payload = _complete_payload(smtp_password={"value": invalid_secret})
    invalid_response = client.put(
        "/admin/email/configuration", json=invalid_payload, headers=admin_headers
    )
    assert invalid_response.status_code == 422
    assert invalid_response.json()["detail"]["error_code"] == "invalid_smtp_password"
    assert invalid_secret not in invalid_response.text


def test_replacing_password_without_encryption_env_uses_persistent_runtime_key(
    monkeypatch, tmp_path
):
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    runtime_dir = tmp_path / "runtime-secrets"
    monkeypatch.delenv(ENCRYPTION_KEY_ENVIRONMENT_VARIABLE)
    monkeypatch.setenv("COMPASSAQ_DATA_DIR", str(runtime_dir))

    response = client.put(
        "/admin/email/configuration",
        json=_complete_payload(),
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["password_configured"] is True
    assert "smtp-secret-value" not in response.text
    assert (runtime_dir / "encryption_key").is_file()
    with SessionLocal() as session:
        ciphertext = session.get(EmailSettings, 1).smtp_password_ciphertext
    assert decrypt_secret(ciphertext) == "smtp-secret-value"


def test_no_op_update_does_not_create_an_event():
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    assert client.put(
        "/admin/email/configuration",
        json=_complete_payload(),
        headers=admin_headers,
    ).status_code == 200
    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.email"))
        session.commit()

    unchanged_payload = _complete_payload()
    unchanged_payload.pop("smtp_password")
    response = client.put(
        "/admin/email/configuration", json=unchanged_payload, headers=admin_headers
    )

    assert response.status_code == 200
    assert _email_events() == []


def test_test_delivery_uses_saved_secret_and_one_time_recipient(monkeypatch):
    admin_headers, admin_user_id, admin_email = _create_user_headers(roles=["admin"])
    assert client.put(
        "/admin/email/configuration",
        json=_complete_payload(),
        headers=admin_headers,
    ).status_code == 200
    captured: dict[str, object] = {}

    class SuccessfulEmailService:
        def __init__(self, configuration):
            captured["configuration"] = configuration

        def send(self, **message):
            captured["message"] = message

    monkeypatch.setattr(email_route, "EmailService", SuccessfulEmailService)
    response = client.post(
        "/admin/email/test",
        json={"recipient": "one-time@example.com"},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["delivery_status"] == "sent"
    assert response.json()["recipient"] == "one-time@example.com"
    configuration = captured["configuration"]
    assert configuration.smtp_password == "smtp-secret-value"
    assert captured["message"]["recipients"] == ("one-time@example.com",)

    with SessionLocal() as session:
        saved = session.get(EmailSettings, 1)
        assert saved.administrator_recipients == [
            "primary@example.com",
            "backup@example.com",
        ]
        assert saved.last_test_status == "success"
        assert saved.last_test_error_code is None
        assert saved.last_tested_at is not None
        event = session.execute(
            select(Event)
            .where(Event.event_type == "email.test.sent")
            .order_by(Event.event_id.desc())
        ).scalars().first()
        assert event.actor_user_id == admin_user_id
        assert event.actor_email == admin_email
        assert event.params == {"status": "success"}

    readiness = client.get(
        "/admin/email/configuration", headers=admin_headers
    ).json()
    assert readiness["status"] == "ready"
    assert readiness["status_reason_codes"] == []


def test_test_delivery_accepts_empty_body_and_uses_first_saved_recipient(monkeypatch):
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    assert client.put(
        "/admin/email/configuration",
        json=_complete_payload(smtp_username=None, smtp_password=None),
        headers=admin_headers,
    ).status_code == 200
    captured: dict[str, object] = {}

    class SuccessfulEmailService:
        def __init__(self, configuration):
            captured["configuration"] = configuration

        def send(self, **message):
            captured["message"] = message

    monkeypatch.setattr(email_route, "EmailService", SuccessfulEmailService)
    response = client.post("/admin/email/test", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert captured["configuration"].smtp_password is None
    assert captured["message"]["recipients"] == ("primary@example.com",)


def test_test_request_rejects_submitted_transport_credentials_without_echoing_them():
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    submitted_secret = "one-time-secret-must-not-be-returned"

    response = client.post(
        "/admin/email/test",
        json={"smtp_password": submitted_secret, "smtp_host": "other.example.com"},
        headers=admin_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "unexpected_request_fields"
    assert response.json()["detail"]["error_context"]["fields"] == [
        "smtp_host",
        "smtp_password",
    ]
    assert submitted_secret not in response.text


def test_disabled_test_is_rejected_and_preserves_last_success(monkeypatch):
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    assert client.put(
        "/admin/email/configuration",
        json=_complete_payload(),
        headers=admin_headers,
    ).status_code == 200

    class SuccessfulEmailService:
        def __init__(self, configuration):
            pass

        def send(self, **message):
            pass

    monkeypatch.setattr(email_route, "EmailService", SuccessfulEmailService)
    assert client.post("/admin/email/test", json={}, headers=admin_headers).status_code == 200

    disabled_payload = _complete_payload(enabled=False)
    disabled_payload.pop("smtp_password")
    assert client.put(
        "/admin/email/configuration", json=disabled_payload, headers=admin_headers
    ).status_code == 200

    response = client.post("/admin/email/test", json={}, headers=admin_headers)

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "email_configuration_disabled"
    with SessionLocal() as session:
        saved = session.get(EmailSettings, 1)
        assert saved.last_test_status == "success"
        assert saved.last_test_error_code is None
        failure_event = session.execute(
            select(Event)
            .where(Event.event_type == "email.test.failed")
            .order_by(Event.event_id.desc())
        ).scalars().first()
        assert failure_event.params == {"error_code": "email_configuration_disabled"}


def test_incomplete_configuration_is_rejected_and_records_explicit_reasons():
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    response = client.put(
        "/admin/email/configuration",
        json={"enabled": True},
        headers=admin_headers,
    )
    assert response.status_code == 200

    response = client.post("/admin/email/test", json={}, headers=admin_headers)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error_code"] == "email_configuration_incomplete"
    assert detail["error_context"]["reason_codes"] == [
        "smtp_host_missing",
        "smtp_port_missing",
        "smtp_security_mode_missing",
        "from_email_missing",
        "administrator_recipients_missing",
    ]
    with SessionLocal() as session:
        saved = session.get(EmailSettings, 1)
        assert saved.last_test_status == "failed"
        assert saved.last_test_error_code == "email_configuration_incomplete"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (EmailDeliveryError(EmailDeliveryErrorCode.CONNECTION_TIMEOUT), 504),
        (EmailDeliveryError(EmailDeliveryErrorCode.AUTHENTICATION_FAILED, smtp_code=535), 502),
        (EmailDeliveryError(EmailDeliveryErrorCode.RELAY_DENIED, smtp_code=530), 502),
    ],
)
def test_delivery_failures_update_state_log_safe_events_and_return_stable_errors(
    monkeypatch, error, expected_status
):
    admin_headers, admin_user_id, admin_email = _create_user_headers(roles=["admin"])
    assert client.put(
        "/admin/email/configuration",
        json=_complete_payload(),
        headers=admin_headers,
    ).status_code == 200

    class FailingEmailService:
        def __init__(self, configuration):
            pass

        def send(self, **message):
            raise error

    monkeypatch.setattr(email_route, "EmailService", FailingEmailService)
    response = client.post("/admin/email/test", json={}, headers=admin_headers)

    assert response.status_code == expected_status
    assert response.json()["detail"]["error_code"] == error.error_code.value
    assert "smtp-secret-value" not in response.text
    with SessionLocal() as session:
        saved = session.get(EmailSettings, 1)
        assert saved.last_test_status == "failed"
        assert saved.last_test_error_code == error.error_code.value
        event = session.execute(
            select(Event)
            .where(Event.event_type == "email.test.failed")
            .order_by(Event.event_id.desc())
        ).scalars().first()
        assert event.actor_user_id == admin_user_id
        assert event.actor_email == admin_email
        assert event.params["error_code"] == error.error_code.value
        assert "smtp-secret-value" not in json.dumps(event.params)


def test_unreadable_saved_secret_fails_without_exposing_ciphertext(
    monkeypatch, clean_email_configuration
):
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    assert client.put(
        "/admin/email/configuration",
        json=_complete_payload(),
        headers=admin_headers,
    ).status_code == 200
    with SessionLocal() as session:
        ciphertext = session.get(EmailSettings, 1).smtp_password_ciphertext
    monkeypatch.setenv(
        ENCRYPTION_KEY_ENVIRONMENT_VARIABLE,
        Fernet.generate_key().decode("ascii"),
    )

    response = client.post("/admin/email/test", json={}, headers=admin_headers)

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "smtp_secret_unavailable"
    assert ciphertext not in response.text
    assert "smtp-secret-value" not in response.text
    with SessionLocal() as session:
        saved = session.get(EmailSettings, 1)
        assert saved.last_test_status == "failed"
        assert saved.last_test_error_code == "smtp_secret_unavailable"
