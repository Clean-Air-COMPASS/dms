from __future__ import annotations

from datetime import datetime, timezone
import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from postgresql_test_support import (
    POSTGRES_TEST_URL_ENV,
    downgrade,
    temporary_postgres_database,
    upgrade,
)


UTC = timezone.utc


def test_administrator_summary_migration_upgrade_and_downgrade() -> None:
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL migration tests")

    with temporary_postgres_database("administrator_summary_migration") as (
        database_url,
        engine,
    ):
        upgrade(database_url, "20260820_0010")
        with engine.begin() as connection:
            schedule_id = connection.scalar(
                text(
                    "SELECT job_schedule_id FROM job_schedule "
                    "ORDER BY job_schedule_id LIMIT 1"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO job_run (job_schedule_id, status, started_at) "
                    "VALUES (:schedule_id, 'success', :started_at)"
                ),
                {
                    "schedule_id": schedule_id,
                    "started_at": datetime(2026, 8, 21, tzinfo=UTC),
                },
            )

        # Round-trip the summary schema and timezone adjustment before later
        # migrations introduce intentional downgrade safety barriers.
        upgrade(database_url, "20260822_0012")
        inspector = inspect(engine)
        email_columns = {
            column["name"]: column
            for column in inspector.get_columns("email_settings")
        }
        assert {
            "administrator_summary_enabled",
            "administrator_summary_cadence",
            "administrator_summary_daily_send_time",
            "administrator_summary_reporting_timezone_override",
            "administrator_summary_effective_at",
        } <= set(email_columns)
        system_columns = {
            column["name"] for column in inspector.get_columns("system_settings")
        }
        assert "system_timezone" in system_columns
        job_run_columns = {
            column["name"] for column in inspector.get_columns("job_run")
        }
        assert "execution_trigger" in job_run_columns
        delivery_columns = {
            column["name"]
            for column in inspector.get_columns("administrator_summary_delivery")
        }
        assert delivery_columns == {
            "administrator_summary_delivery_id",
            "period_start",
            "period_end",
            "cadence",
            "reporting_timezone",
            "status",
            "attempt_count",
            "last_attempted_at",
            "sent_at",
            "error_code",
            "created_at",
            "updated_at",
        }
        assert not {
            "recipients",
            "html_body",
            "text_body",
            "smtp_password",
        } & delivery_columns

        job_indexes = {
            index["name"] for index in inspector.get_indexes("job_run")
        }
        qc_indexes = {
            index["name"]
            for index in inspector.get_indexes("measurement_qc_result")
        }
        assert "ix_job_run_started_at" in job_indexes
        assert "ix_measurement_qc_result_created_at" in qc_indexes
        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "administrator_summary_delivery"
            )
        }
        assert "uq_administrator_summary_delivery_period" in unique_constraints

        with engine.connect() as connection:
            defaults = connection.execute(
                text(
                    "SELECT administrator_summary_enabled, "
                    "administrator_summary_cadence, "
                    "administrator_summary_daily_send_time, "
                    "administrator_summary_reporting_timezone_override, "
                    "administrator_summary_effective_at FROM email_settings"
                )
            ).mappings().one()
            execution_trigger = connection.scalar(
                text("SELECT execution_trigger FROM job_run LIMIT 1")
            )
            system_timezone = connection.scalar(
                text("SELECT system_timezone FROM system_settings")
            )
        assert defaults["administrator_summary_enabled"] is False
        assert defaults["administrator_summary_cadence"] == "daily"
        assert str(defaults["administrator_summary_daily_send_time"]) == "07:00:00"
        assert defaults["administrator_summary_reporting_timezone_override"] is None
        assert defaults["administrator_summary_effective_at"] is None
        assert system_timezone == "UTC"
        # Historical manual origin was not persisted before this migration and
        # therefore cannot be reconstructed safely.
        assert execution_trigger == "scheduled"

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE email_settings SET "
                        "administrator_summary_cadence = 'weekly'"
                    )
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE job_run SET execution_trigger = 'unknown'")
                )

        period_values = {
            "period_start": datetime(2026, 8, 21, 10, tzinfo=UTC),
            "period_end": datetime(2026, 8, 21, 11, tzinfo=UTC),
        }
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO administrator_summary_delivery "
                    "(period_start, period_end, cadence, reporting_timezone, "
                    "status, attempt_count, last_attempted_at) VALUES "
                    "(:period_start, :period_end, 'hourly', 'UTC', "
                    "'sending', 1, :period_end)"
                ),
                period_values,
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO administrator_summary_delivery "
                        "(period_start, period_end, cadence, reporting_timezone, "
                        "status, attempt_count) VALUES "
                        "(:period_start, :period_end, 'daily', 'UTC', 'failed', 1)"
                    ),
                    period_values,
                )

        downgrade(database_url, "20260820_0010")
        downgraded_inspector = inspect(engine)
        assert "administrator_summary_delivery" not in (
            downgraded_inspector.get_table_names()
        )
        assert "execution_trigger" not in {
            column["name"]
            for column in downgraded_inspector.get_columns("job_run")
        }
        assert "administrator_summary_enabled" not in {
            column["name"]
            for column in downgraded_inspector.get_columns("email_settings")
        }
        assert "ix_job_run_started_at" not in {
            index["name"] for index in downgraded_inspector.get_indexes("job_run")
        }

        upgrade(database_url, "head")
        assert "administrator_summary_delivery" in inspect(engine).get_table_names()


def test_existing_summary_timezone_is_preserved_as_an_explicit_override() -> None:
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL migration tests")

    with temporary_postgres_database("administrator_summary_timezone_preservation") as (
        database_url,
        engine,
    ):
        upgrade(database_url, "20260821_0011")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE email_settings SET "
                    "administrator_summary_enabled = true, "
                    "administrator_summary_reporting_timezone = 'America/Sao_Paulo'"
                )
            )

        upgrade(database_url, "head")

        with engine.connect() as connection:
            values = connection.execute(
                text(
                    "SELECT administrator_summary_reporting_timezone_override "
                    "FROM email_settings"
                )
            ).scalar_one()
            system_timezone = connection.scalar(
                text("SELECT system_timezone FROM system_settings")
            )

        assert values == "America/Sao_Paulo"
        assert system_timezone == "UTC"
