from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

import db
import models
from api.main import app
from db import get_session
from services.system_settings import DEFAULT_LANGUAGE_CODE


def _install_session_override(session_factory: sessionmaker[Session]) -> None:
    def override_get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session


@pytest.fixture()
def isolated_setup_database(tmp_path: Path):
    database_path = tmp_path / "setup-state.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    models.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    _install_session_override(session_factory)
    try:
        yield database_path, engine, session_factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_general_test_suite_ignores_developer_database_configuration() -> None:
    expected_database = Path(__file__).resolve().parent / "testdata.sqlite3"
    assert db.DATABASE_URL == f"sqlite+pysqlite:///{expected_database}"


def test_fresh_install_reports_incomplete_with_english_default(
    isolated_setup_database,
) -> None:
    _, _, session_factory = isolated_setup_database

    response = TestClient(app).get("/setup/status")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "is_setup_required": True,
        "has_users": False,
        "default_language_code": DEFAULT_LANGUAGE_CODE,
    }
    with session_factory() as session:
        settings = session.scalar(select(models.SystemSettings))
        assert settings is not None
        assert settings.is_system_setup_complete is False
        assert settings.default_language_code == DEFAULT_LANGUAGE_CODE


@pytest.mark.parametrize(
    "payload",
    [
        {
            "password": "SetupValidationPassphrase123!",
            "confirm_password": "SetupValidationPassphrase123!",
        },
        {
            "email": "not-an-email",
            "password": "SetupValidationPassphrase123!",
            "confirm_password": "SetupValidationPassphrase123!",
        },
    ],
    ids=["missing-email", "invalid-email-format"],
)
def test_initial_admin_rejects_missing_or_invalid_email(isolated_setup_database, payload) -> None:
    _, _, session_factory = isolated_setup_database

    response = TestClient(app).post("/setup/admin", json=payload)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(models.User)) == 0


def test_initial_admin_trims_email_and_rejects_a_second_account(isolated_setup_database) -> None:
    client = TestClient(app)
    payload = {
        "email": "  Setup-Admin@Example.COM  ",
        "password": "SetupValidationPassphrase123!",
        "confirm_password": "SetupValidationPassphrase123!",
    }

    created = client.post("/setup/admin", json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["email"] == "setup-admin@example.com"

    conflict = client.post(
        "/setup/admin",
        json={**payload, "email": "another-admin@example.com"},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["error_code"] == "setup_admin_already_created"


def test_original_persona_email_has_structured_validation_and_allows_correction(
    isolated_setup_database,
) -> None:
    _, _, session_factory = isolated_setup_database
    client = TestClient(app)
    payload = {
        "email": "qa.jordan@example.invalid",
        "password": "SetupValidationPassphrase123!",
        "confirm_password": "SetupValidationPassphrase123!",
    }
    rejected = client.post("/setup/admin", json=payload)
    assert rejected.status_code == 422
    errors = rejected.json()["detail"]
    assert len(errors) == 1
    assert errors[0]["loc"] == ["body", "email"]
    assert errors[0]["type"] == "value_error"
    assert client.get("/setup/status").json()["has_users"] is False
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(models.User)) == 0

    corrected = client.post("/setup/admin", json={**payload, "email": "installer@example.org"})
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["email"] == "installer@example.org"


def test_password_validation_is_identified_separately_from_email(isolated_setup_database) -> None:
    response = TestClient(app).post("/setup/admin", json={
        "email": "installer@example.org", "password": "short", "confirm_password": "short",
    })
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "password"]


@pytest.mark.parametrize(
    ("password", "confirmation", "error_code"),
    [
        ("installer123456!", "installer123456!", "password_policy_not_met"),
        ("SetupValidationPassphrase123!", "DifferentPassphrase456!", "password_confirmation_mismatch"),
    ],
)
def test_initial_admin_keeps_password_policy_and_confirmation_checks(
    isolated_setup_database, password, confirmation, error_code,
) -> None:
    response = TestClient(app).post("/setup/admin", json={
        "email": "installer@example.org", "password": password, "confirm_password": confirmation,
    })
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == error_code


@pytest.mark.parametrize(
    ("setup_complete", "stored_language", "expected_setup_required"),
    [
        (True, None, False),
        (True, "invalid", False),
        (False, "es", True),
        (False, None, True),
    ],
)
def test_setup_status_depends_only_on_persisted_setup_marker(
    isolated_setup_database,
    setup_complete: bool,
    stored_language: str | None,
    expected_setup_required: bool,
) -> None:
    _, engine, _ = isolated_setup_database
    with engine.begin() as connection:
        # A malformed language is impossible under the current database check,
        # but this simulates a damaged/legacy row to verify the defensive read.
        connection.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            insert(models.SystemSettings).values(
                is_system_setup_complete=setup_complete,
                default_language_code=stored_language,
                system_timezone="UTC",
            )
        )

    response = TestClient(app).get("/setup/status")

    assert response.status_code == 200, response.text
    assert response.json()["is_setup_required"] is expected_setup_required
    assert response.json()["default_language_code"] == (
        stored_language if stored_language in {"en", "es"} else DEFAULT_LANGUAGE_CODE
    )


def test_completed_setup_and_initial_admin_survive_new_application_session(
    isolated_setup_database,
) -> None:
    database_path, engine, session_factory = isolated_setup_database
    client = TestClient(app)

    admin_response = client.post(
        "/setup/admin",
        json={
            "email": "setup-lifecycle@example.com",
            "password": "SetupLifecyclePassphrase123!",
            "confirm_password": "SetupLifecyclePassphrase123!",
        },
    )
    assert admin_response.status_code == 200, admin_response.text

    complete_response = client.post(
        "/setup/complete",
        json={"default_language_code": "en", "system_timezone": "UTC"},
    )
    assert complete_response.status_code == 200, complete_response.text

    with session_factory() as session:
        admin_id = uuid.UUID(admin_response.json()["user_id"])
        assert session.scalar(select(func.count()).select_from(models.User)) == 1

    app.dependency_overrides.clear()
    engine.dispose()
    restarted_engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    restarted_session_factory = sessionmaker(bind=restarted_engine)
    _install_session_override(restarted_session_factory)
    try:
        restarted_response = TestClient(app).get("/setup/status")
        assert restarted_response.status_code == 200, restarted_response.text
        assert restarted_response.json() == {
            "is_setup_required": False,
            "has_users": True,
            "default_language_code": "en",
        }
        with restarted_session_factory() as session:
            preserved_admin = session.get(models.User, admin_id)
            assert preserved_admin is not None
            assert preserved_admin.email == "setup-lifecycle@example.com"
    finally:
        app.dependency_overrides.clear()
        restarted_engine.dispose()
