from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import api.routes.admin.events as admin_events_route
import services.event_log as event_log_service
import services.system_settings as system_settings_service
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from api.main import app
from db import SessionLocal
from models import EmailSettings, Event, SystemSettings, User
from services import auth

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


def test_get_system_preferences_creates_singleton_row(monkeypatch):
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    monkeypatch.delenv("SYSTEM_TIMEZONE", raising=False)
    monkeypatch.setattr(system_settings_service, "get_localzone_name", lambda: "UTC")

    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.system_preferences"))
        session.execute(delete(SystemSettings))
        session.commit()

    response = client.get("/admin/system-preferences", headers=admin_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["geoapify_api_key"] is None
    assert payload["system_timezone"] == "UTC"
    assert payload["updated_at"] is not None
    assert payload["last_updated_by_email"] is None

    with SessionLocal() as session:
        rows = session.execute(select(SystemSettings)).scalars().all()
        assert len(rows) == 1


def test_update_system_preferences_persists_key_updates_timestamp_and_logs_event():
    admin_headers, admin_user_id, admin_email = _create_user_headers(roles=["admin"])

    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.system_preferences"))
        session.execute(delete(SystemSettings))
        session.commit()

        settings = SystemSettings(
            geoapify_api_key=None,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
            updated_at=datetime(2026, 4, 19, 8, 0, tzinfo=timezone.utc),
        )
        session.add(settings)
        session.commit()
        previous_updated_at = settings.updated_at

    response = client.put(
        "/admin/system-preferences",
        json={"geoapify_api_key": "new-geoapify-key", "default_language_code": "en"},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["geoapify_api_key"] == "new-geoapify-key"
    assert payload["updated_at"] is not None
    assert payload["last_updated_by_email"] == admin_email

    with SessionLocal() as session:
        settings = session.execute(select(SystemSettings)).scalar_one()
        assert settings.geoapify_api_key == "new-geoapify-key"
        assert settings.updated_at is not None
        assert settings.updated_at > previous_updated_at

        event = session.execute(
            select(Event)
            .where(Event.source == "admin.system_preferences")
            .order_by(Event.event_id.desc())
        ).scalar_one()
        assert event.event_type == "system_preferences.geoapify_api_key.changed"
        assert event.message == "Geoapify API key created"
        assert event.params == {"field": "geoapify_api_key", "action": "created"}
        assert event.actor_user_id == admin_user_id
        assert event.actor_email == admin_email
        assert "new-geoapify-key" not in (event.message or "")
        assert "new-geoapify-key" not in str(event.params or {})


def test_update_system_preferences_with_same_value_is_no_op():
    admin_headers, _, _ = _create_user_headers(roles=["admin"])

    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.system_preferences"))
        session.execute(delete(SystemSettings))
        session.commit()

        settings = SystemSettings(
            geoapify_api_key="same-key",
            default_language_code="en",
            updated_at=datetime(2026, 4, 19, 8, 0, tzinfo=timezone.utc),
        )
        session.add(settings)
        session.commit()
        previous_updated_at = settings.updated_at

    response = client.put(
        "/admin/system-preferences",
        json={"geoapify_api_key": "same-key", "default_language_code": "en"},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["geoapify_api_key"] == "same-key"

    with SessionLocal() as session:
        settings = session.execute(select(SystemSettings)).scalar_one()
        assert settings.updated_at == previous_updated_at
        events = session.execute(
            select(Event).where(Event.source == "admin.system_preferences")
        ).scalars().all()
        assert events == []


def test_next_admin_update_replaces_last_updated_by_email():
    first_admin_headers, _, first_admin_email = _create_user_headers(roles=["admin"])
    second_admin_headers, _, second_admin_email = _create_user_headers(roles=["admin"])

    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.system_preferences"))
        session.execute(delete(SystemSettings))
        session.commit()

    first_response = client.put(
        "/admin/system-preferences",
        json={"geoapify_api_key": "first-key", "default_language_code": "en"},
        headers=first_admin_headers,
    )
    assert first_response.json()["last_updated_by_email"] == first_admin_email

    second_response = client.put(
        "/admin/system-preferences",
        json={"geoapify_api_key": "second-key", "default_language_code": "en"},
        headers=second_admin_headers,
    )
    assert second_response.json()["last_updated_by_email"] == second_admin_email

    reloaded_response = client.get("/admin/system-preferences", headers=second_admin_headers)
    assert reloaded_response.json()["last_updated_by_email"] == second_admin_email


def test_update_system_preferences_allows_clearing_key():
    admin_headers, _, admin_email = _create_user_headers(roles=["admin"])

    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.system_preferences"))
        session.execute(delete(SystemSettings))
        session.commit()

        session.add(
            SystemSettings(
                geoapify_api_key="existing-key",
                default_language_code="en",
                updated_at=datetime(2026, 4, 19, 8, 0, tzinfo=timezone.utc),
            )
        )
        session.commit()

    response = client.put(
        "/admin/system-preferences",
        json={"geoapify_api_key": "   ", "default_language_code": "en"},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["geoapify_api_key"] is None

    with SessionLocal() as session:
        settings = session.execute(select(SystemSettings)).scalar_one()
        assert settings.geoapify_api_key is None

        event = session.execute(
            select(Event)
            .where(Event.source == "admin.system_preferences")
            .order_by(Event.event_id.desc())
        ).scalar_one()
        assert event.message == "Geoapify API key cleared"
        assert event.params == {"field": "geoapify_api_key", "action": "cleared"}
        assert event.actor_email == admin_email


def test_event_log_keeps_actor_email_after_user_is_deleted():
    actor_headers, actor_user_id, actor_email = _create_user_headers(roles=["admin"])
    deleter_headers, _, _ = _create_user_headers(roles=["admin"])

    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.system_preferences"))
        session.commit()

    save_response = client.put(
        "/admin/system-preferences",
        json={"geoapify_api_key": "retained-key", "default_language_code": "en"},
        headers=actor_headers,
    )
    assert save_response.status_code == 200, save_response.text

    delete_response = client.delete(f"/admin/users/{actor_user_id}", headers=deleter_headers)
    assert delete_response.status_code == 204, delete_response.text

    events_response = client.get(
        "/admin/events",
        params={"source": "admin.system_preferences"},
        headers=deleter_headers,
    )
    assert events_response.status_code == 200, events_response.text

    matching_event = events_response.json()[0]
    assert matching_event["actor_email"] == actor_email


def test_system_preferences_requires_admin_scope():
    viewer_headers, _, _ = _create_user_headers(roles=["viewer"])

    unauthenticated_response = client.get("/admin/system-preferences")
    assert unauthenticated_response.status_code == 401, unauthenticated_response.text

    forbidden_response = client.get("/admin/system-preferences", headers=viewer_headers)
    assert forbidden_response.status_code == 403, forbidden_response.text

    forbidden_update_response = client.put(
        "/admin/system-preferences",
        json={"geoapify_api_key": "blocked", "default_language_code": "en"},
        headers=viewer_headers,
    )
    assert forbidden_update_response.status_code == 403, forbidden_update_response.text


def test_update_system_preferences_persists_default_language_code():
    admin_headers, _, admin_email = _create_user_headers(roles=["admin"])

    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.system_preferences"))
        session.execute(delete(SystemSettings))
        session.add(SystemSettings(default_language_code="en"))
        session.commit()

    response = client.put(
        "/admin/system-preferences",
        json={"geoapify_api_key": None, "default_language_code": "es"},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["default_language_code"] == "es"
    assert response.json()["last_updated_by_email"] == admin_email

    with SessionLocal() as session:
        settings = session.execute(select(SystemSettings)).scalar_one()
        assert settings.default_language_code == "es"
        event = session.execute(
            select(Event)
            .where(Event.source == "admin.system_preferences")
            .order_by(Event.event_id.desc())
        ).scalar_one()
        assert event.event_type == "system_preferences.default_language_code.changed"
        assert event.params == {
            "field": "default_language_code",
            "action": "updated",
            "previous_language_code": "en",
            "language_code": "es",
        }


def test_system_timezone_accepts_valid_iana_and_rejects_invalid_timezone():
    admin_headers, _, _ = _create_user_headers(roles=["admin"])

    with SessionLocal() as session:
        session.execute(delete(Event).where(Event.source == "admin.system_preferences"))
        session.execute(delete(SystemSettings))
        session.add(SystemSettings(default_language_code="en", system_timezone="UTC"))
        session.commit()

    valid_response = client.put(
        "/admin/system-preferences",
        json={
            "geoapify_api_key": None,
            "default_language_code": "en",
            "system_timezone": "Asia/Manila",
        },
        headers=admin_headers,
    )
    assert valid_response.status_code == 200, valid_response.text
    assert valid_response.json()["system_timezone"] == "Asia/Manila"

    invalid_response = client.put(
        "/admin/system-preferences",
        json={
            "geoapify_api_key": None,
            "default_language_code": "en",
            "system_timezone": "Pacific Standard Time",
        },
        headers=admin_headers,
    )
    assert invalid_response.status_code == 422
    assert invalid_response.json()["detail"]["error_code"] == "invalid_system_timezone"

    with SessionLocal() as session:
        assert session.scalar(select(SystemSettings)).system_timezone == "Asia/Manila"


def test_system_timezone_change_resets_effective_at_only_for_inherited_summary():
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    original_effective_at = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)

    with SessionLocal() as session:
        session.execute(delete(EmailSettings))
        session.execute(delete(SystemSettings))
        session.add(SystemSettings(default_language_code="en", system_timezone="UTC"))
        session.add(
            EmailSettings(
                email_settings_id=1,
                administrator_summary_enabled=True,
                administrator_summary_cadence="daily",
                administrator_summary_daily_send_time=time(7),
                administrator_summary_reporting_timezone_override=None,
                administrator_summary_effective_at=original_effective_at,
            )
        )
        session.commit()

    response = client.put(
        "/admin/system-preferences",
        json={
            "geoapify_api_key": None,
            "default_language_code": "en",
            "system_timezone": "Asia/Manila",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as session:
        summary = session.get(EmailSettings, 1)
        assert summary is not None
        assert summary.administrator_summary_reporting_timezone_override is None
        assert summary.administrator_summary_effective_at is not None
        assert summary.administrator_summary_effective_at > original_effective_at.replace(tzinfo=None)


def test_system_timezone_change_does_not_reset_summary_override():
    admin_headers, _, _ = _create_user_headers(roles=["admin"])
    original_effective_at = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)

    with SessionLocal() as session:
        session.execute(delete(EmailSettings))
        session.execute(delete(SystemSettings))
        session.add(SystemSettings(default_language_code="en", system_timezone="UTC"))
        session.add(
            EmailSettings(
                email_settings_id=1,
                administrator_summary_enabled=True,
                administrator_summary_cadence="daily",
                administrator_summary_daily_send_time=time(7),
                administrator_summary_reporting_timezone_override="America/Los_Angeles",
                administrator_summary_effective_at=original_effective_at,
            )
        )
        session.commit()

    response = client.put(
        "/admin/system-preferences",
        json={
            "geoapify_api_key": None,
            "default_language_code": "en",
            "system_timezone": "Asia/Manila",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as session:
        summary = session.get(EmailSettings, 1)
        assert summary is not None
        assert summary.administrator_summary_reporting_timezone_override == "America/Los_Angeles"
        assert summary.administrator_summary_effective_at == original_effective_at.replace(tzinfo=None)


def test_event_log_list_falls_back_cleanly_when_actor_columns_are_missing(monkeypatch):
    admin_headers, _, _ = _create_user_headers(roles=["admin"])

    legacy_event_columns = {
        "event_id",
        "event_type",
        "source",
        "severity",
        "device_id",
        "sensor_id",
        "external_sensor_id",
        "endpoint",
        "params",
        "message",
        "raw_snippet",
        "created_at",
    }
    monkeypatch.setattr(admin_events_route, "get_event_table_column_names", lambda session: legacy_event_columns)

    with SessionLocal() as session:
        session.execute(
            text(
                """
                INSERT INTO event (event_type, source, severity, message)
                VALUES (:event_type, :source, :severity, :message)
                """
            ),
            {
                "event_type": "legacy.test",
                "source": "legacy-test",
                "severity": "info",
                "message": "Legacy event row",
            },
        )
        session.commit()

    response = client.get("/admin/events", params={"source": "legacy-test"}, headers=admin_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload[0]["event_type"] == "legacy.test"
    assert payload[0]["actor_user_id"] is None
    assert payload[0]["actor_email"] is None


def test_system_preferences_update_still_saves_when_actor_columns_are_missing(monkeypatch):
    admin_headers, _, _ = _create_user_headers(roles=["admin"])

    legacy_event_columns = {
        "event_id",
        "event_type",
        "source",
        "severity",
        "device_id",
        "sensor_id",
        "external_sensor_id",
        "endpoint",
        "params",
        "message",
        "raw_snippet",
        "created_at",
    }
    monkeypatch.setattr(event_log_service, "get_event_table_column_names", lambda session: legacy_event_columns)

    with SessionLocal() as session:
        session.execute(delete(SystemSettings))
        session.commit()

    response = client.put(
        "/admin/system-preferences",
        json={"geoapify_api_key": "legacy-compatible-key", "default_language_code": "en"},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["geoapify_api_key"] == "legacy-compatible-key"

    with SessionLocal() as session:
        saved_event = session.execute(
            text(
                """
                SELECT event_type, source, message
                FROM event
                WHERE source = :source
                ORDER BY event_id DESC
                LIMIT 1
                """
            ),
            {"source": "admin.system_preferences"},
        ).mappings().one()
        assert saved_event["event_type"] == "system_preferences.geoapify_api_key.changed"
        assert saved_event["message"] == "Geoapify API key created"
