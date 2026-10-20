from __future__ import annotations

from datetime import datetime, timezone
import os

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

import models
from postgresql_test_support import (
    POSTGRES_TEST_URL_ENV,
    temporary_postgres_database,
    upgrade,
)
from services.administrator_summary_collector import build_administrator_summary
from services.administrator_summary_domain import (
    AdministratorSummaryCadence,
    QcDigestOutcome,
    calculate_completed_reporting_window,
)


UTC = timezone.utc


def test_postgresql_collectors_execute_grouped_json_and_distinct_aggregations() -> None:
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL summary tests")

    with temporary_postgres_database("administrator_summary") as (database_url, engine):
        upgrade(database_url, "head")
        with Session(engine) as session:
            purpleair_source = session.scalar(
                select(models.ExternalAPI).where(
                    models.ExternalAPI.provider_code == "purpleair"
                )
            )
            purpleair_schedule = session.scalar(
                select(models.JobSchedule).where(
                    models.JobSchedule.task == "purpleair_import"
                )
            )
            parameter = session.scalar(
                select(models.Parameter).where(models.Parameter.code == "pm25")
            )
            unit = session.scalar(
                select(models.Unit).where(models.Unit.code == "ug_m3")
            )
            assert purpleair_source is not None
            assert purpleair_schedule is not None
            assert parameter is not None
            assert unit is not None

            device = models.Device(
                name="PostgreSQL summary device",
                external_api_id=purpleair_source.external_api_id,
                timezone="UTC",
            )
            session.add(device)
            session.flush()
            sensor = models.Sensor(
                device_id=device.device_id,
                parameter_id=parameter.parameter_id,
                unit_id=unit.unit_id,
                external_sensor_id="summary-postgresql-sensor",
            )
            session.add(sensor)
            session.flush()

            period_time = datetime(2026, 8, 21, 4, tzinfo=UTC)
            session.add_all(
                [
                    models.JobRun(
                        job_schedule_id=purpleair_schedule.job_schedule_id,
                        status="success",
                        started_at=period_time,
                        finished_at=period_time,
                        summary={
                            "measurements_received": 8,
                            "measurements_inserted": 5,
                            "measurements_updated": 1,
                            "measurements_skipped": 2,
                        },
                    ),
                    models.JobRun(
                        job_schedule_id=purpleair_schedule.job_schedule_id,
                        status="failed",
                        started_at=period_time,
                        finished_at=period_time,
                        summary=None,
                        error_message="raw provider exception",
                    ),
                ]
            )
            for value in (1.0, 2.0):
                measurement = models.Measurement(
                    sensor_id=sensor.sensor_id,
                    value=value,
                    observed_at=None,
                    is_valid=False,
                    created_at=period_time,
                )
                session.add(measurement)
                session.flush()
                session.add(
                    models.MeasurementQCResult(
                        measurement_id=measurement.measurement_id,
                        parameter_id=parameter.parameter_id,
                        aggregate_code="1h",
                        check_code="max_value",
                        passed=False,
                        severity="error",
                        evaluation_status="failed",
                        failure_action="mark_invalid",
                        created_at=period_time,
                    )
                )
            session.add(
                models.Event(
                    event_type="unmapped_postgresql_error",
                    source="system.worker",
                    severity="error",
                    message="raw message must not be selected",
                    raw_snippet="raw body must not be selected",
                    created_at=period_time,
                )
            )
            session.commit()

        window = calculate_completed_reporting_window(
            datetime(2026, 8, 22, 12, tzinfo=UTC),
            AdministratorSummaryCadence.DAILY,
            "UTC",
        )
        statements: list[str] = []

        @event.listens_for(engine, "before_cursor_execute")
        def capture_statement(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement.lower())

        try:
            with Session(engine) as session:
                summary = build_administrator_summary(
                    session,
                    window,
                    generated_at_utc=datetime(2026, 8, 22, 12, tzinfo=UTC),
                )
        finally:
            event.remove(engine, "before_cursor_execute", capture_statement)

        assert len(statements) == 4
        assert sum("group by" in statement for statement in statements) == 3
        assert sum("job_schedule.cron_expr" in statement for statement in statements) == 1
        assert any("count(distinct" in statement for statement in statements)
        assert any("->>" in statement for statement in statements)
        assert len(summary.import_sources) == 1
        purpleair = summary.import_sources[0]
        assert purpleair.job_count == 2
        assert purpleair.successful_job_count == 1
        assert purpleair.failed_job_count == 1
        assert purpleair.measurements_received == 8
        assert purpleair.measurements_inserted == 5
        assert purpleair.measurements_updated == 1
        assert purpleair.measurements_skipped == 2
        assert len(summary.qc_activity) == 1
        assert summary.qc_activity[0].outcome is QcDigestOutcome.MARKED_INVALID
        assert summary.qc_activity[0].measurement_count == 2
        assert [group.digest_code for group in summary.system_events] == [
            "system_error"
        ]
