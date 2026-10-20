from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from api.main import app
from db import SessionLocal
from models import SystemSettings, User
from services import auth


client = TestClient(app)


def _authenticated_user() -> tuple[dict[str, str], uuid.UUID]:
    auth_settings = auth.get_auth_settings()
    with SessionLocal() as session:
        user = User(
            user_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            email=f"language-{uuid.uuid4()}@example.com",
            password_hash=auth.hash_password("strong-password-123"),
            is_active=True,
        )
        session.add(user)
        session.commit()
        token, _ = auth.create_access_token(
            settings=auth_settings,
            user_id=user.user_id,
            org_id=user.org_id,
            roles=["viewer"],
            scopes=auth.scopes_from_roles(["viewer"]),
        )
        return {"Authorization": f"Bearer {token}"}, user.user_id


def test_me_exposes_and_persists_nullable_language_override():
    headers, user_id = _authenticated_user()
    with SessionLocal() as session:
        session.execute(delete(SystemSettings))
        session.add(SystemSettings(default_language_code="en"))
        session.commit()

    initial_response = client.get("/auth/me", headers=headers)
    assert initial_response.status_code == 200, initial_response.text
    assert initial_response.json()["preferred_language_code"] is None
    assert initial_response.json()["system_default_language_code"] == "en"

    spanish_response = client.patch(
        "/auth/me/preferences",
        json={"preferred_language_code": "es"},
        headers=headers,
    )
    assert spanish_response.status_code == 200, spanish_response.text
    assert spanish_response.json()["preferred_language_code"] == "es"

    reset_response = client.patch(
        "/auth/me/preferences",
        json={"preferred_language_code": None},
        headers=headers,
    )
    assert reset_response.status_code == 200, reset_response.text
    assert reset_response.json()["preferred_language_code"] is None

    with SessionLocal() as session:
        assert session.get(User, user_id).preferred_language_code is None


def test_user_language_override_rejects_unsupported_code():
    headers, _ = _authenticated_user()
    response = client.patch(
        "/auth/me/preferences",
        json={"preferred_language_code": "fr"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


def test_setup_requires_and_persists_explicit_default_language():
    with SessionLocal() as session:
        session.execute(delete(SystemSettings))
        user = User(
            user_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            email=f"setup-language-{uuid.uuid4()}@example.com",
            password_hash=auth.hash_password("strong-password-123"),
            is_active=True,
        )
        session.add(user)
        session.add(SystemSettings(is_system_setup_complete=False))
        session.commit()
        user_id = user.user_id

    missing_response = client.post("/setup/complete", json={})
    assert missing_response.status_code == 422, missing_response.text

    response = client.post(
        "/setup/complete",
        json={
            "default_language_code": "es",
            "system_timezone": "America/Los_Angeles",
        },
    )
    assert response.status_code == 200, response.text

    status_response = client.get("/setup/status")
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["default_language_code"] == "es"
    assert status_response.json()["is_setup_required"] is False

    with SessionLocal() as session:
        settings = session.execute(select(SystemSettings)).scalar_one()
        assert settings.default_language_code == "es"
        assert settings.system_timezone == "America/Los_Angeles"
        session.delete(session.get(User, user_id))
        session.delete(settings)
        session.commit()


def test_setup_invalid_browser_timezone_falls_back_to_utc():
    with SessionLocal() as session:
        session.execute(delete(SystemSettings))
        user = User(
            user_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            email=f"setup-timezone-{uuid.uuid4()}@example.com",
            password_hash=auth.hash_password("strong-password-123"),
            is_active=True,
        )
        session.add(user)
        session.add(SystemSettings(is_system_setup_complete=False))
        session.commit()
        user_id = user.user_id

    response = client.post(
        "/setup/complete",
        json={
            "default_language_code": "en",
            "system_timezone": "Not/A_Zone",
        },
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as session:
        settings = session.execute(select(SystemSettings)).scalar_one()
        assert settings.system_timezone == "UTC"
        session.delete(session.get(User, user_id))
        session.delete(settings)
        session.commit()
