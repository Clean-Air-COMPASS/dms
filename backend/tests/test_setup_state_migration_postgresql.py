from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from postgresql_test_support import (
    POSTGRES_TEST_URL_ENV,
    temporary_postgres_database,
    upgrade,
)


def _require_postgresql_test_database() -> None:
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL migration tests")


OPERATIONAL_TIME = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _seed_active_admin(connection) -> str:
    user_id = str(uuid4())
    connection.execute(
        text(
            'INSERT INTO "user" '
            "(user_id, org_id, email, password_hash, is_active, created_at) "
            "VALUES (:user_id, :org_id, :email, 'not-a-real-hash', true, "
            ":created_at)"
        ),
        {
            "user_id": user_id,
            "org_id": str(uuid4()),
            "email": f"migration-admin-{uuid4().hex}@example.com",
            "created_at": OPERATIONAL_TIME,
        },
    )
    connection.execute(
        text(
            "INSERT INTO user_role (user_id, role_id) "
            "SELECT :user_id, role_id FROM role WHERE name = 'admin'"
        ),
        {"user_id": user_id},
    )
    return user_id


def _seed_imported_measurement(connection) -> None:
    external_api_id = connection.scalar(
        text("SELECT external_api_id FROM external_api ORDER BY external_api_id LIMIT 1")
    )
    parameter_id = connection.scalar(
        text("SELECT parameter_id FROM parameter ORDER BY parameter_id LIMIT 1")
    )
    unit_id = connection.scalar(
        text("SELECT unit_id FROM unit ORDER BY unit_id LIMIT 1")
    )
    device_id = connection.scalar(
        text(
            "INSERT INTO device (name, external_api_id) "
            "VALUES ('Migration evidence device', :external_api_id) "
            "RETURNING device_id"
        ),
        {"external_api_id": external_api_id},
    )
    sensor_id = connection.scalar(
        text(
            "INSERT INTO sensor (device_id, parameter_id, unit_id) "
            "VALUES (:device_id, :parameter_id, :unit_id) RETURNING sensor_id"
        ),
        {
            "device_id": device_id,
            "parameter_id": parameter_id,
            "unit_id": unit_id,
        },
    )
    connection.execute(
        text(
            "INSERT INTO measurement (sensor_id, value, observed_at, created_at) "
            "VALUES (:sensor_id, 12.5, :observed_at, :created_at)"
        ),
        {
            "sensor_id": sensor_id,
            "observed_at": OPERATIONAL_TIME,
            "created_at": OPERATIONAL_TIME,
        },
    )


def test_clean_postgresql_migration_keeps_setup_incomplete_and_defaults_language() -> None:
    _require_postgresql_test_database()
    with temporary_postgres_database("clean_setup_state") as (database_url, engine):
        upgrade(database_url, "head")

        with engine.connect() as connection:
            settings = connection.execute(
                text(
                    "SELECT is_system_setup_complete, default_language_code "
                    "FROM system_settings"
                )
            ).mappings().one()
            user_count = connection.scalar(text('SELECT count(*) FROM "user"'))

        assert settings == {
            "is_system_setup_complete": False,
            "default_language_code": "en",
        }
        assert user_count == 0


def test_migration_recreates_missing_setup_state_without_deleting_users() -> None:
    _require_postgresql_test_database()
    with temporary_postgres_database("configured_setup_state") as (
        database_url,
        engine,
    ):
        upgrade(database_url, "20260827_0016")
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM system_settings"))
            admin_user_id = _seed_active_admin(connection)
            _seed_imported_measurement(connection)

        upgrade(database_url, "head")

        with engine.connect() as connection:
            settings = connection.execute(
                text(
                    "SELECT is_system_setup_complete, default_language_code "
                    "FROM system_settings"
                )
            ).mappings().one()
            preserved_admin_count = connection.scalar(
                text('SELECT count(*) FROM "user" WHERE user_id = :user_id'),
                {"user_id": admin_user_id},
            )
            measurement_count = connection.scalar(
                text("SELECT count(*) FROM measurement")
            )

        assert settings == {
            "is_system_setup_complete": True,
            "default_language_code": "en",
        }
        assert preserved_admin_count == 1
        assert measurement_count == 1


def test_migration_repairs_existing_false_marker_for_configured_installation() -> None:
    _require_postgresql_test_database()
    with temporary_postgres_database("false_configured_setup_state") as (
        database_url,
        engine,
    ):
        upgrade(database_url, "20260827_0016")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE system_settings SET "
                    "is_system_setup_complete = false, default_language_code = NULL"
                )
            )
            _seed_active_admin(connection)
            _seed_imported_measurement(connection)

        upgrade(database_url, "head")

        with engine.connect() as connection:
            settings = connection.execute(
                text(
                    "SELECT is_system_setup_complete, default_language_code "
                    "FROM system_settings"
                )
            ).mappings().one()

        assert settings == {
            "is_system_setup_complete": True,
            "default_language_code": "en",
        }


def test_migration_does_not_complete_setup_from_admin_presence_alone() -> None:
    _require_postgresql_test_database()
    with temporary_postgres_database("incomplete_setup_state") as (
        database_url,
        engine,
    ):
        upgrade(database_url, "20260827_0016")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE system_settings SET "
                    "is_system_setup_complete = false, default_language_code = 'es'"
                )
            )
            _seed_active_admin(connection)

        upgrade(database_url, "head")

        with engine.connect() as connection:
            settings = connection.execute(
                text(
                    "SELECT is_system_setup_complete, default_language_code "
                    "FROM system_settings"
                )
            ).mappings().one()

        assert settings == {
            "is_system_setup_complete": False,
            "default_language_code": "es",
        }


def test_migration_repairs_language_without_changing_completed_setup() -> None:
    _require_postgresql_test_database()
    with temporary_postgres_database("complete_missing_language") as (
        database_url,
        engine,
    ):
        upgrade(database_url, "20260827_0016")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE system_settings SET "
                    "is_system_setup_complete = true, default_language_code = NULL"
                )
            )

        upgrade(database_url, "head")

        with engine.connect() as connection:
            settings = connection.execute(
                text(
                    "SELECT is_system_setup_complete, default_language_code "
                    "FROM system_settings"
                )
            ).mappings().one()

        assert settings == {
            "is_system_setup_complete": True,
            "default_language_code": "en",
        }
