from __future__ import annotations

from datetime import datetime, time, timezone
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import api.routes.admin.email as email_route
from api.main import app
from db import SessionLocal
from models import AdministratorSummaryDelivery, EmailSettings, Event, SystemSettings, User
from services import auth
from services.email_delivery import EmailDeliveryError, EmailDeliveryErrorCode


client = TestClient(app)
UTC = timezone.utc


def _create_user_headers(*, roles: list[str]) -> dict[str, str]:
    auth_settings = auth.get_auth_settings()
    with SessionLocal() as session:
        user = User(
            user_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            email=f"summary-{roles[0]}-{uuid.uuid4()}@example.com",
            password_hash=auth.hash_password("strong-password-123"),
            is_active=True,
        )
        session.add(user)
        session.commit()
        token, _ = auth.create_access_token(
            settings=auth_settings,
            user_id=user.user_id,
            org_id=user.org_id,
            roles=roles,
            scopes=auth.scopes_from_roles(roles),
        )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def clean_summary_configuration():
    with SessionLocal() as session:
        session.execute(delete(AdministratorSummaryDelivery))
        session.execute(delete(Event).where(Event.source == "admin.email"))
        session.execute(delete(EmailSettings))
        session.execute(delete(SystemSettings))
        session.add(SystemSettings(default_language_code="en", system_timezone="UTC"))
        session.commit()
    yield
    with SessionLocal() as session:
        session.execute(delete(AdministratorSummaryDelivery))
        session.execute(delete(Event).where(Event.source == "admin.email"))
        session.execute(delete(EmailSettings))
        session.execute(delete(SystemSettings))
        session.commit()


def _ready_email_settings(**overrides: object) -> EmailSettings:
    values: dict[str, object] = {
        "email_settings_id": 1,
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_security_mode": "starttls",
        "from_email": "sender@example.com",
        "administrator_recipients": ["saved@example.com"],
        "last_test_status": "success",
        "last_tested_at": datetime(2026, 8, 20, 12, tzinfo=UTC),
        "administrator_summary_enabled": True,
        "administrator_summary_cadence": "daily",
        "administrator_summary_daily_send_time": time(7, 0),
        "administrator_summary_reporting_timezone_override": "America/Los_Angeles",
        "administrator_summary_effective_at": datetime(2026, 8, 20, tzinfo=UTC),
    }
    values.update(overrides)
    return EmailSettings(**values)


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/admin/email/administrator-summary", None),
        ("put", "/admin/email/administrator-summary", {
            "enabled": False,
            "cadence": "daily",
            "daily_send_time": "07:00:00",
            "reporting_timezone_mode": "system",
            "reporting_timezone_override": None,
        }),
        ("post", "/admin/email/administrator-summary/preview", {}),
        ("post", "/admin/email/administrator-summary/test", {}),
    ],
)
def test_administrator_summary_endpoints_require_users_write_scope(
    method: str,
    path: str,
    json_body: dict | None,
):
    viewer_headers = _create_user_headers(roles=["viewer"])

    assert client.request(method, path, json=json_body).status_code == 401
    assert client.request(
        method,
        path,
        json=json_body,
        headers=viewer_headers,
    ).status_code == 403


def test_get_serializes_fresh_summary_off_and_email_readiness():
    headers = _create_user_headers(roles=["admin"])

    response = client.get("/admin/email/administrator-summary", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "enabled": False,
        "cadence": "daily",
        "daily_send_time": "07:00:00",
        "reporting_timezone": "UTC",
        "effective_at": None,
        "schedule_status": "summary_off",
        "blocker_codes": [],
        "email_delivery_ready": False,
        "next_due_at": None,
        "next_reporting_window": None,
        "last_scheduled_delivery": None,
        "reporting_timezone_source": "system_preferences",
        "reporting_timezone_override": None,
        "system_timezone": "UTC",
    }


def test_get_reports_blocked_email_and_safe_last_delivery():
    headers = _create_user_headers(roles=["admin"])
    with SessionLocal() as session:
        session.add(_ready_email_settings(last_test_status=None, last_tested_at=None))
        session.add(
            AdministratorSummaryDelivery(
                period_start=datetime(2026, 8, 19, 7, tzinfo=UTC),
                period_end=datetime(2026, 8, 20, 7, tzinfo=UTC),
                cadence="daily",
                reporting_timezone="America/Los_Angeles",
                status="failed",
                attempt_count=2,
                last_attempted_at=datetime(2026, 8, 20, 14, tzinfo=UTC),
                error_code="smtp_connection_timeout",
            )
        )
        session.commit()

    response = client.get("/admin/email/administrator-summary", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schedule_status"] == "blocked_email_delivery"
    assert payload["blocker_codes"] == ["test_required"]
    assert payload["email_delivery_ready"] is False
    assert payload["last_scheduled_delivery"]["status"] == "failed"
    assert payload["last_scheduled_delivery"]["error_code"] == "smtp_connection_timeout"
    assert "attempt_count" not in payload["last_scheduled_delivery"]


def test_summary_inherits_system_timezone_until_an_explicit_override_is_saved():
    headers = _create_user_headers(roles=["admin"])

    initial_response = client.get("/admin/email/administrator-summary", headers=headers)
    assert initial_response.status_code == 200, initial_response.text
    assert initial_response.json()["reporting_timezone"] == "UTC"
    assert initial_response.json()["reporting_timezone_source"] == "system_preferences"
    assert initial_response.json()["reporting_timezone_override"] is None

    system_response = client.put(
        "/admin/system-preferences",
        json={
            "geoapify_api_key": None,
            "default_language_code": "en",
            "system_timezone": "Asia/Manila",
        },
        headers=headers,
    )
    assert system_response.status_code == 200, system_response.text

    inherited_response = client.get("/admin/email/administrator-summary", headers=headers)
    assert inherited_response.status_code == 200, inherited_response.text
    assert inherited_response.json()["reporting_timezone"] == "Asia/Manila"
    assert inherited_response.json()["reporting_timezone_source"] == "system_preferences"
    assert inherited_response.json()["reporting_timezone_override"] is None

    override_response = client.put(
        "/admin/email/administrator-summary",
        json={
            "enabled": False,
            "cadence": "daily",
            "daily_send_time": "07:00:00",
            "reporting_timezone_mode": "override",
            "reporting_timezone_override": "America/Los_Angeles",
        },
        headers=headers,
    )
    assert override_response.status_code == 200, override_response.text
    assert override_response.json()["reporting_timezone"] == "America/Los_Angeles"
    assert override_response.json()["reporting_timezone_source"] == "summary_override"

    changed_system_response = client.put(
        "/admin/system-preferences",
        json={
            "geoapify_api_key": None,
            "default_language_code": "en",
            "system_timezone": "America/Sao_Paulo",
        },
        headers=headers,
    )
    assert changed_system_response.status_code == 200, changed_system_response.text

    overridden_response = client.get("/admin/email/administrator-summary", headers=headers)
    assert overridden_response.status_code == 200, overridden_response.text
    assert overridden_response.json()["reporting_timezone"] == "America/Los_Angeles"
    assert overridden_response.json()["system_timezone"] == "America/Sao_Paulo"
    assert overridden_response.json()["reporting_timezone_source"] == "summary_override"


def test_get_waits_for_first_period_when_delivery_predates_current_schedule():
    headers = _create_user_headers(roles=["admin"])
    with SessionLocal() as session:
        session.add(
            _ready_email_settings(
                administrator_summary_effective_at=datetime(
                    2026, 8, 21, 16, tzinfo=UTC
                )
            )
        )
        session.add(
            AdministratorSummaryDelivery(
                period_start=datetime(2026, 8, 19, 7, tzinfo=UTC),
                period_end=datetime(2026, 8, 20, 7, tzinfo=UTC),
                cadence="daily",
                reporting_timezone="America/Los_Angeles",
                status="sent",
                attempt_count=1,
                last_attempted_at=datetime(2026, 8, 20, 14, tzinfo=UTC),
                sent_at=datetime(2026, 8, 20, 14, tzinfo=UTC),
            )
        )
        session.commit()

    response = client.get("/admin/email/administrator-summary", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["schedule_status"] == "waiting_for_first_scheduled_period"
    assert response.json()["last_scheduled_delivery"]["status"] == "sent"


def test_put_no_op_preserves_effective_at_and_real_change_resets_it():
    headers = _create_user_headers(roles=["admin"])
    original_effective_at = datetime(2026, 8, 20, tzinfo=UTC)
    with SessionLocal() as session:
        session.add(_ready_email_settings(administrator_summary_effective_at=original_effective_at))
        session.commit()
    payload = {
        "enabled": True,
        "cadence": "daily",
        "daily_send_time": "07:00:00",
        "reporting_timezone_mode": "override",
        "reporting_timezone_override": "America/Los_Angeles",
    }

    no_op_response = client.put(
        "/admin/email/administrator-summary",
        json=payload,
        headers=headers,
    )
    changed_response = client.put(
        "/admin/email/administrator-summary",
        json={**payload, "cadence": "hourly"},
        headers=headers,
    )

    assert no_op_response.status_code == 200, no_op_response.text
    assert no_op_response.json()["effective_at"].startswith("2026-08-20T00:00:00")
    assert changed_response.status_code == 200, changed_response.text
    changed_effective_at = datetime.fromisoformat(changed_response.json()["effective_at"])
    assert changed_effective_at > original_effective_at
    with SessionLocal() as session:
        events = list(
            session.scalars(
                select(Event).where(
                    Event.event_type
                    == "email.administrator_summary.schedule.updated"
                )
            )
        )
    assert len(events) == 1
    assert events[0].params["changed_fields"] == ["cadence"]
    assert "hourly" not in str(events[0].params)


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("cadence", "weekly", "invalid_administrator_summary_cadence"),
        (
            "reporting_timezone_override",
            "Pacific Standard Time",
            "invalid_administrator_summary_reporting_timezone",
        ),
    ],
)
def test_put_rejects_invalid_schedule_values(field: str, value: str, error_code: str):
    headers = _create_user_headers(roles=["admin"])
    payload = {
        "enabled": True,
        "cadence": "daily",
        "daily_send_time": "07:00:00",
        "reporting_timezone_mode": "override",
        "reporting_timezone_override": "UTC",
        field: value,
    }

    response = client.put(
        "/admin/email/administrator-summary",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == error_code


def test_preview_uses_real_renderer_without_delivery_or_event_side_effects():
    headers = _create_user_headers(roles=["admin"])
    with SessionLocal() as session:
        session.add(_ready_email_settings())
        session.commit()

    response = client.post(
        "/admin/email/administrator-summary/preview",
        json={
            "cadence": "hourly",
            "reporting_timezone_mode": "override",
            "reporting_timezone_override": "UTC",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["overall_status"] in {"all_systems_normal", "needs_attention"}
    assert payload["subject"].startswith("[CompassAQ")
    assert "CompassAQ Administrator Summary" in payload["html_body"]
    assert "COMPASSAQ ADMINISTRATOR SUMMARY" in payload["text_body"]
    assert "Environment: Test" in payload["text_body"]
    assert "QC activity" not in payload["text_body"]
    assert "QC activity" not in payload["html_body"]
    with SessionLocal() as session:
        assert session.scalar(select(AdministratorSummaryDelivery)) is None
        assert session.scalar(
            select(Event).where(Event.source == "admin.email")
        ) is None


def test_summary_test_sends_real_rendered_content_without_mutating_canonical_state(
    monkeypatch,
):
    headers = _create_user_headers(roles=["admin"])
    sent_messages: list[dict[str, object]] = []

    class RecordingEmailService:
        def __init__(self, _transport):
            pass

        def send(self, **message):
            sent_messages.append(message)

    monkeypatch.setattr(email_route, "EmailService", RecordingEmailService)
    with SessionLocal() as session:
        session.add(_ready_email_settings())
        session.commit()

    response = client.post(
        "/admin/email/administrator-summary/test",
        json={
            "recipient": "one-time@example.com",
            "cadence": "every_15_minutes",
            "reporting_timezone_mode": "override",
            "reporting_timezone_override": "UTC",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["recipient"] == "one-time@example.com"
    assert sent_messages[0]["recipients"] == ("one-time@example.com",)
    assert str(sent_messages[0]["subject"]).startswith("[TEST] [CompassAQ")
    assert "CompassAQ Administrator Summary" in str(sent_messages[0]["html_body"])
    with SessionLocal() as session:
        saved = session.get(EmailSettings, 1)
        assert saved.administrator_recipients == ["saved@example.com"]
        assert saved.last_test_status == "success"
        assert saved.last_tested_at == datetime(2026, 8, 20, 12)
        assert session.scalar(select(AdministratorSummaryDelivery)) is None
        event = session.scalar(
            select(Event).where(
                Event.event_type == "email.administrator_summary.test.sent"
            )
        )
        assert event is not None
        assert "one-time@example.com" not in str(event.params)
        assert "html_body" not in str(event.params)


def test_summary_test_failure_records_safe_event_without_transport_readiness_change(
    monkeypatch,
):
    headers = _create_user_headers(roles=["admin"])

    class FailingEmailService:
        def __init__(self, _transport):
            pass

        def send(self, **_message):
            raise EmailDeliveryError(EmailDeliveryErrorCode.CONNECTION_TIMEOUT)

    monkeypatch.setattr(email_route, "EmailService", FailingEmailService)
    with SessionLocal() as session:
        session.add(_ready_email_settings())
        session.commit()

    response = client.post(
        "/admin/email/administrator-summary/test",
        json={},
        headers=headers,
    )

    assert response.status_code == 504
    with SessionLocal() as session:
        saved = session.get(EmailSettings, 1)
        assert saved.last_test_status == "success"
        assert session.scalar(select(AdministratorSummaryDelivery)) is None
        event = session.scalar(
            select(Event).where(
                Event.event_type == "email.administrator_summary.test.failed"
            )
        )
        assert event.params == {"error_code": "smtp_connection_timeout"}
