from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterator
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session

from api.main import app
from db import get_session
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    MeasurementQCResult,
    Parameter,
    Sensor,
    Unit,
)
from services.aqi_engine import calculate_latest_us_epa_aqi
from services.measurement_aggregation import execute_measurement_aggregation


BACKEND_ROOT = Path(__file__).resolve().parents[1]
INTEGER_MAX = 2_147_483_647
POSTGRES_TEST_URL_ENV = "COMPASSAQ_POSTGRES_TEST_URL"


def _postgres_test_url() -> URL:
    raw_url = os.environ.get(POSTGRES_TEST_URL_ENV)
    if not raw_url:
        pytest.skip(
            f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL migration tests."
        )
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql":
        pytest.fail(f"{POSTGRES_TEST_URL_ENV} must be a PostgreSQL URL")
    return url


@contextmanager
def _temporary_postgres_database() -> Iterator[tuple[URL, Engine]]:
    base_url = _postgres_test_url()
    database_name = f"compassaq_bigint_{uuid4().hex}"
    admin_url = base_url.set(database="postgres")
    test_url = base_url.set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    test_engine: Engine | None = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        test_engine = create_engine(test_url)
        yield test_url, test_engine
    finally:
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def _upgrade(database_url: URL, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url.render_as_string(hide_password=False)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def _downgrade(database_url: URL, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url.render_as_string(hide_password=False)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def _column_metadata(connection) -> dict[tuple[str, str], dict]:
    rows = connection.execute(
        text(
            """
            SELECT table_name, column_name, data_type, udt_name,
                   column_default, is_identity
            FROM information_schema.columns
            WHERE (table_name = 'measurement' AND column_name = 'measurement_id')
               OR (table_name = 'measurement_qc_result'
                   AND column_name IN ('measurement_id', 'measurement_qc_result_id'))
            ORDER BY table_name, ordinal_position
            """
        )
    ).mappings()
    return {
        (row["table_name"], row["column_name"]): dict(row)
        for row in rows
    }


def _sequence_metadata(connection) -> dict[str, dict]:
    rows = connection.execute(
        text(
            """
            SELECT sequencename, data_type, start_value, min_value, max_value,
                   increment_by, cycle, cache_size, last_value
            FROM pg_sequences
            WHERE schemaname = 'public'
              AND sequencename IN (
                'measurement_measurement_id_seq',
                'measurement_qc_result_measurement_qc_result_id_seq'
              )
            ORDER BY sequencename
            """
        )
    ).mappings()
    return {row["sequencename"]: dict(row) for row in rows}


def _index_names(connection, table_name: str) -> set[str]:
    return set(
        connection.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = :table_name"
            ),
            {"table_name": table_name},
        ).scalars()
    )


def _assert_bigint_schema(connection) -> None:
    columns = _column_metadata(connection)
    assert set(columns) == {
        ("measurement", "measurement_id"),
        ("measurement_qc_result", "measurement_qc_result_id"),
        ("measurement_qc_result", "measurement_id"),
    }
    for column in columns.values():
        assert column["data_type"] == "bigint"
        assert column["udt_name"] == "int8"
        assert column["is_identity"] == "NO"
    assert columns[("measurement", "measurement_id")]["column_default"] == (
        "nextval('measurement_measurement_id_seq'::regclass)"
    )
    assert columns[("measurement_qc_result", "measurement_qc_result_id")][
        "column_default"
    ] == "nextval('measurement_qc_result_measurement_qc_result_id_seq'::regclass)"

    sequences = _sequence_metadata(connection)
    assert set(sequences) == {
        "measurement_measurement_id_seq",
        "measurement_qc_result_measurement_qc_result_id_seq",
    }
    for sequence in sequences.values():
        assert sequence["data_type"] == "bigint"
        assert sequence["max_value"] == 9_223_372_036_854_775_807
        assert sequence["increment_by"] == 1
        assert sequence["cycle"] is False

    assert connection.scalar(
        text("SELECT pg_get_serial_sequence('measurement', 'measurement_id')")
    ) == "public.measurement_measurement_id_seq"
    assert connection.scalar(
        text(
            "SELECT pg_get_serial_sequence(" 
            "'measurement_qc_result', 'measurement_qc_result_id')"
        )
    ) == "public.measurement_qc_result_measurement_qc_result_id_seq"
    assert connection.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'measurement_qc_result_measurement_id_fkey'"
        )
    ) == (
        "FOREIGN KEY (measurement_id) REFERENCES "
        "measurement(measurement_id) ON DELETE CASCADE"
    )

    measurement_indexes = _index_names(connection, "measurement")
    assert "ix_measurement_sensor_observed_at" not in measurement_indexes
    assert "measurement_pkey" in measurement_indexes
    assert "uq_measurement_sensor_observed" in measurement_indexes
    qc_indexes = _index_names(connection, "measurement_qc_result")
    assert "ix_measurement_qc_result_measurement_id" not in qc_indexes
    assert "measurement_qc_result_pkey" in qc_indexes
    assert "uq_mqc_result_measurement_check" in qc_indexes


def _create_measurement_dependencies(session: Session) -> tuple[object, Sensor, Parameter]:
    parameter = session.scalar(select(Parameter).where(Parameter.code == "pm25"))
    assert parameter is not None
    unit = session.scalar(select(Unit).where(Unit.unit_id == parameter.default_unit_id))
    aggregation_period = session.scalar(
        select(AggregationPeriod).where(AggregationPeriod.code == "1h")
    )
    assert unit is not None and aggregation_period is not None
    external_api = ExternalAPI(
        name=f"bigint-test-{uuid4().hex}",
        base_url="https://example.invalid",
        params={},
    )
    session.add(external_api)
    session.flush()
    device_columns = {
        column["name"] for column in inspect(session.get_bind()).get_columns("device")
    }
    if "location" in device_columns:
        device: object = Device(
            name="BIGINT regression device",
            external_api_id=external_api.external_api_id,
            timezone="UTC",
        )
        session.add(device)
        session.flush()
    else:
        # This regression intentionally exercises an intermediate historical
        # revision. The current ORM has a later spatial column, so insert only
        # fields that existed at that revision.
        device_id = session.scalar(
            text(
                "INSERT INTO device (name, external_api_id, timezone) "
                "VALUES (:name, :external_api_id, 'UTC') RETURNING device_id"
            ),
            {
                "name": "BIGINT regression device",
                "external_api_id": external_api.external_api_id,
            },
        )
        device = SimpleNamespace(device_id=device_id)
    sensor = Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=aggregation_period.aggregation_period_id,
        hourly_concentration_provenance="provider_reported_hourly_average",
        hourly_timestamp_semantics="hour_start",
        measurement_metadata_status="provider_documented",
        measurement_metadata_managed_by="bigint_regression_test",
    )
    session.add(sensor)
    session.flush()
    return device, sensor, parameter


def test_existing_install_upgrade_preserves_data_sequences_and_serial_semantics() -> None:
    with _temporary_postgres_database() as (database_url, engine):
        _upgrade(database_url, "20260810_0005")
        with engine.begin() as connection:
            before_columns = _column_metadata(connection)
            assert all(column["data_type"] == "integer" for column in before_columns.values())
            before_indexes = {
                *_index_names(connection, "measurement"),
                *_index_names(connection, "measurement_qc_result"),
            }
            assert "ix_measurement_sensor_observed_at" in before_indexes
            assert "ix_measurement_qc_result_measurement_id" in before_indexes

        # Seed the historical schema through SQL, independently of later ORM
        # columns (including AirGradient checkpoints and QC policy metadata).
        with engine.begin() as connection:
            source_id = connection.scalar(text(
                "INSERT INTO external_api (name, base_url, params) "
                "VALUES (:name, 'https://example.invalid', '{}') RETURNING external_api_id"
            ), {"name": f"bigint-test-{uuid4().hex}"})
            device_id = connection.scalar(text(
                "INSERT INTO device (name, external_api_id, timezone) "
                "VALUES ('BIGINT regression device', :source_id, 'UTC') RETURNING device_id"
            ), {"source_id": source_id})
            parameter_id = connection.scalar(text("SELECT parameter_id FROM parameter WHERE code = 'pm25'"))
            sensor_id = connection.scalar(text(
                "INSERT INTO sensor (device_id, parameter_id, unit_id, aggregation_period_id, "
                "hourly_concentration_provenance, hourly_timestamp_semantics, "
                "measurement_metadata_status, measurement_metadata_managed_by) "
                "SELECT :device_id, p.parameter_id, p.default_unit_id, a.aggregation_period_id, "
                "'provider_reported_hourly_average', 'hour_start', 'provider_documented', 'bigint_regression_test' "
                "FROM parameter p CROSS JOIN aggregation_period a WHERE p.code = 'pm25' AND a.code = '1h' "
                "RETURNING sensor_id"
            ), {"device_id": device_id})
            assert sensor_id is not None
            measurement_id = connection.scalar(text(
                "INSERT INTO measurement (sensor_id, value, observed_at, is_valid) "
                "VALUES (:sensor_id, 12.5, :observed_at, false) RETURNING measurement_id"
            ), {"sensor_id": sensor_id, "observed_at": datetime(2026, 8, 12, tzinfo=timezone.utc)})
            qc_result_id = connection.scalar(
                text(
                    "INSERT INTO measurement_qc_result "
                    "(measurement_id, parameter_id, aggregate_code, check_code, passed) "
                    "VALUES (:measurement_id, :parameter_id, '1h', "
                    "'bigint_upgrade_preservation', false) "
                    "RETURNING measurement_qc_result_id"
                ),
                {
                    "measurement_id": measurement_id,
                    "parameter_id": parameter_id,
                },
            )
            assert qc_result_id is not None

        with engine.begin() as connection:
            connection.execute(
                text("SELECT setval('measurement_measurement_id_seq', 5000, true)")
            )
            connection.execute(
                text(
                    "SELECT setval(" 
                    "'measurement_qc_result_measurement_qc_result_id_seq', 8000, true)"
                )
            )
            before_sequences = _sequence_metadata(connection)

        _upgrade(database_url, "head")

        with engine.connect() as connection:
            _assert_bigint_schema(connection)
            after_sequences = _sequence_metadata(connection)
            assert after_sequences["measurement_measurement_id_seq"]["last_value"] == (
                before_sequences["measurement_measurement_id_seq"]["last_value"]
            )
            assert after_sequences[
                "measurement_qc_result_measurement_qc_result_id_seq"
            ]["last_value"] == before_sequences[
                "measurement_qc_result_measurement_qc_result_id_seq"
            ]["last_value"]
            assert connection.scalar(
                text("SELECT measurement_id FROM measurement WHERE measurement_id = :id"),
                {"id": measurement_id},
            ) == measurement_id
            assert connection.scalar(
                text(
                    "SELECT measurement_qc_result_id FROM measurement_qc_result "
                    "WHERE measurement_qc_result_id = :id"
                ),
                {"id": qc_result_id},
            ) == qc_result_id


def test_fresh_install_has_expected_schema() -> None:
    with _temporary_postgres_database() as (database_url, engine):
        _upgrade(database_url, "head")
        with engine.connect() as connection:
            _assert_bigint_schema(connection)


def test_safe_downgrade_and_reupgrade_have_expected_schema() -> None:
    with _temporary_postgres_database() as (database_url, engine):
        # Test this revision's narrowing contract without crossing the later
        # Demo migration's independent activation-state protection.
        _upgrade(database_url, "20260812_0006")
        with engine.connect() as connection:
            _assert_bigint_schema(connection)
        _downgrade(database_url, "20260810_0005")
        with engine.connect() as connection:
            columns = _column_metadata(connection)
            assert all(column["data_type"] == "integer" for column in columns.values())
            assert all(
                sequence["data_type"] == "integer"
                for sequence in _sequence_metadata(connection).values()
            )
            assert "ix_measurement_sensor_observed_at" in _index_names(
                connection, "measurement"
            )
            assert "ix_measurement_qc_result_measurement_id" in _index_names(
                connection, "measurement_qc_result"
            )

        _upgrade(database_url, "head")
        with engine.connect() as connection:
            _assert_bigint_schema(connection)


def test_downgrade_refuses_to_narrow_an_allocated_bigint_identifier() -> None:
    with _temporary_postgres_database() as (database_url, engine):
        _upgrade(database_url, "20260812_0006")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT setval(" 
                    "'measurement_measurement_id_seq', 2147483648, true)"
                )
            )

        with pytest.raises(RuntimeError, match="exceeded 2,147,483,647"):
            _downgrade(database_url, "20260810_0005")

        with engine.connect() as connection:
            _assert_bigint_schema(connection)

        _upgrade(database_url, "head")
        with engine.connect() as connection:
            _assert_bigint_schema(connection)


def test_identifier_above_int32_survives_orm_qc_aggregation_aqi_and_api() -> None:
    with _temporary_postgres_database() as (database_url, engine):
        _upgrade(database_url, "head")
        completed_before = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)

        with Session(engine) as session:
            device, sensor, parameter = _create_measurement_dependencies(session)
            session.execute(
                text(
                    "SELECT setval(" 
                    "'measurement_measurement_id_seq', 2147483647, true)"
                )
            )
            measurements = [
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=value,
                    observed_at=completed_before - timedelta(hours=hours_ago),
                    is_valid=True,
                )
                for hours_ago, value in ((1, 10.0), (2, 12.0), (3, 14.0))
            ]
            session.add_all(measurements)
            session.flush()
            high_measurement = measurements[0]
            assert high_measurement.measurement_id == INTEGER_MAX + 1

            session.execute(
                text(
                    "SELECT setval(" 
                    "'measurement_qc_result_measurement_qc_result_id_seq', "
                    "2147483647, true)"
                )
            )
            qc_result = MeasurementQCResult(
                measurement_id=high_measurement.measurement_id,
                parameter_id=parameter.parameter_id,
                aggregate_code="1h",
                check_code="bigint_regression",
                passed=False,
                severity="warning",
                message="High identifier regression",
            )
            session.add(qc_result)
            session.commit()
            high_measurement_id = high_measurement.measurement_id
            device_id = device.device_id
            sensor_id = sensor.sensor_id
            assert qc_result.measurement_qc_result_id == INTEGER_MAX + 1

        with Session(engine) as session:
            loaded = session.get(Measurement, high_measurement_id)
            assert loaded is not None
            assert loaded.measurement_id == INTEGER_MAX + 1
            loaded_qc = session.scalar(
                select(MeasurementQCResult).where(
                    MeasurementQCResult.measurement_id == high_measurement_id
                )
            )
            assert loaded_qc is not None
            assert loaded_qc.measurement_id == high_measurement_id

            aggregation = execute_measurement_aggregation(
                session,
                sensor_ids=[sensor_id],
                parameter_code="pm25",
                native_aggregation_code="1h",
                result_aggregation_code="1h",
                since=completed_before - timedelta(hours=4),
                until=completed_before,
            )
            assert high_measurement_id in {
                point.measurement_id for point in aggregation
            }

            aqi_results = calculate_latest_us_epa_aqi(
                session,
                product_code="us_epa.pm25.nowcast",
                reference_time_utc=completed_before,
                current_time_utc=completed_before,
                device_id=device_id,
            )
            assert len(aqi_results) == 1
            assert high_measurement_id in aqi_results[0].measurement_ids

        def override_session():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        try:
            client = TestClient(app)
            response = client.get(
                "/measurements/pm25/latest",
                params={"aggregation": "1h", "device_id": device_id},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert len(payload) == 1
            assert payload[0]["measurement_id"] == high_measurement_id
        finally:
            app.dependency_overrides.pop(get_session, None)
