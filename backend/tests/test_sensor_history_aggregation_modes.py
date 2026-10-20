from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    ParameterAggregationRollup,
    Sensor,
    Unit,
)


def _ensure(session, model, code_field: str, code: str, **fields):
    row = session.scalar(select(model).where(getattr(model, code_field) == code))
    if row:
        return row
    obj = model(**{code_field: code}, **fields)
    session.add(obj)
    session.flush()
    return obj


def test_sensor_history_returns_raw_measurements_without_instant():
    session = SessionLocal()
    try:
        unit = _ensure(session, Unit, "code", "ug_m3", symbol="ug/m3", name="Micrograms per cubic meter")
        parameter = _ensure(session, Parameter, "code", "pm25", display_name="PM2.5", default_unit_id=unit.unit_id)
        external_api = _ensure(
            session,
            ExternalAPI,
            "name",
            f"raw-history-api-{uuid.uuid4()}",
            base_url="https://example.com",
            params={},
        )

        device = Device(
            name=f"raw-history-device-{uuid.uuid4()}",
            external_api_id=external_api.external_api_id,
            timezone="America/Los_Angeles",
        )
        session.add(device)
        session.flush()

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=None,
            expected_frequency_seconds=300,
            measurement_duration_seconds=300,
            source_aggregation_duration_seconds=300,
            measurement_timestamp_semantics="interval_end",
        )
        session.add(sensor)
        session.flush()

        first_observed_at = datetime.now(timezone.utc) - timedelta(minutes=20)
        second_observed_at = first_observed_at + timedelta(minutes=5)
        session.add_all(
            [
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=10.1,
                    observed_at=first_observed_at,
                    is_valid=True,
                ),
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=10.9,
                    observed_at=second_observed_at,
                    is_valid=True,
                ),
            ]
        )
        session.commit()

        client = TestClient(app)
        response = client.get(
            f"/sensors/{sensor.sensor_id}/history",
            params={"aggregate": "raw", "include_qc": "true", "hours": 2},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["aggregate"] == "raw"
        assert [row["value"] for row in payload["data"]] == [10.1, 10.9]
        assert payload["data"][0]["timestamp"] == first_observed_at.isoformat()
        assert payload["data"][1]["timestamp"] == second_observed_at.isoformat()
        assert payload["expected_frequency_seconds"] == 300
        assert payload["measurement_duration_seconds"] == 300
        assert payload["source_aggregation_duration_seconds"] == 300
        assert payload["measurement_timestamp_semantics"] == "interval_end"
        assert payload["data"][0]["interval_started_at"] == (
            first_observed_at - timedelta(minutes=5)
        ).isoformat()
        assert payload["data"][0]["interval_ended_at"] == first_observed_at.isoformat()
    finally:
        session.rollback()
        session.close()


def test_sensor_history_supports_hourly_aggregation_without_instant():
    session = SessionLocal()
    try:
        unit = _ensure(session, Unit, "code", "ug_m3", symbol="ug/m3", name="Micrograms per cubic meter")
        parameter = _ensure(session, Parameter, "code", "pm25", display_name="PM2.5", default_unit_id=unit.unit_id)
        one_minute_period = _ensure(
            session, AggregationPeriod, "code", "1m", display_name="1 Minute", duration_minutes=1
        )
        one_hour_period = _ensure(
            session, AggregationPeriod, "code", "1h", display_name="1 Hour", duration_minutes=60
        )
        one_minute_period.duration_minutes = 1
        one_hour_period.duration_minutes = 60
        one_minute_period.is_rolling = False
        one_hour_period.is_rolling = False
        rollup = session.scalar(
            select(ParameterAggregationRollup).where(
                ParameterAggregationRollup.parameter_id == parameter.parameter_id,
                ParameterAggregationRollup.from_aggregation_period_id
                == one_minute_period.aggregation_period_id,
                ParameterAggregationRollup.to_aggregation_period_id
                == one_hour_period.aggregation_period_id,
            )
        )
        if rollup is None:
            session.add(
                ParameterAggregationRollup(
                    parameter_id=parameter.parameter_id,
                    from_aggregation_period_id=one_minute_period.aggregation_period_id,
                    to_aggregation_period_id=one_hour_period.aggregation_period_id,
                )
            )
        external_api = _ensure(
            session,
            ExternalAPI,
            "name",
            f"hour-history-api-{uuid.uuid4()}",
            base_url="https://example.com",
            params={},
        )

        device = Device(
            name=f"hour-history-device-{uuid.uuid4()}",
            external_api_id=external_api.external_api_id,
        )
        session.add(device)
        session.flush()

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=one_minute_period.aggregation_period_id,
        )
        session.add(sensor)
        session.flush()

        bucket_start = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
        session.add_all(
            [
                Measurement(sensor_id=sensor.sensor_id, value=10.0, observed_at=bucket_start, is_valid=True),
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=14.0,
                    observed_at=bucket_start + timedelta(minutes=20),
                    is_valid=True,
                ),
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=20.0,
                    observed_at=bucket_start + timedelta(hours=1),
                    is_valid=True,
                ),
            ]
        )
        session.commit()

        client = TestClient(app)
        response = client.get(
            f"/sensors/{sensor.sensor_id}/history",
            params={
                "aggregate": "hour",
                "start": bucket_start.isoformat(),
                "end": (bucket_start + timedelta(hours=2)).isoformat(),
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["aggregate"] == "hour"
        assert payload["native_aggregation_code"] == "1m"
        assert payload["result_aggregation_code"] == "1h"
        assert len(payload["data"]) == 2
        assert payload["data"][0]["value"] == 12.0
        assert payload["data"][1]["value"] == 20.0

        conflicting_response = client.get(
            f"/sensors/{sensor.sensor_id}/history",
            params={"aggregate": "hour", "aggregation": "24h"},
        )
        assert conflicting_response.status_code == 400
        assert "Conflicting aggregate and aggregation" in conflicting_response.text
    finally:
        session.rollback()
        session.close()


def test_sensor_history_rejects_legacy_instant_aggregate():
    session = SessionLocal()
    try:
        unit = _ensure(session, Unit, "code", "ug_m3", symbol="ug/m3", name="Micrograms per cubic meter")
        parameter = _ensure(session, Parameter, "code", "pm25", display_name="PM2.5", default_unit_id=unit.unit_id)
        external_api = _ensure(
            session,
            ExternalAPI,
            "name",
            f"invalid-history-api-{uuid.uuid4()}",
            base_url="https://example.com",
            params={},
        )

        device = Device(
            name=f"invalid-history-device-{uuid.uuid4()}",
            external_api_id=external_api.external_api_id,
        )
        session.add(device)
        session.flush()

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
        )
        session.add(sensor)
        session.commit()

        client = TestClient(app)
        response = client.get(f"/sensors/{sensor.sensor_id}/history", params={"aggregate": "instant"})

        assert response.status_code == 400, response.text
        assert "raw|hour|day" in response.text
    finally:
        session.rollback()
        session.close()
