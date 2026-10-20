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


def test_aggregate_endpoint_filters_by_external_api_name_and_returns_latest_bucket_per_sensor():
    session = SessionLocal()
    try:
        unit = _ensure(session, Unit, "code", "ug_m3", symbol="æg/m3", name="Micrograms per cubic meter")
        ap_1m = _ensure(session, AggregationPeriod, "code", "1m", display_name="1 Minute")
        ap_1h = _ensure(session, AggregationPeriod, "code", "1h", display_name="1 Hour")
        ap_1m.duration_minutes = 1
        ap_1h.duration_minutes = 60
        ap_1m.is_rolling = False
        ap_1h.is_rolling = False
        pm25 = _ensure(session, Parameter, "code", "pm25", display_name="PM2.5", default_unit_id=unit.unit_id)

        existing_roll = session.scalar(
            select(ParameterAggregationRollup).where(
                ParameterAggregationRollup.parameter_id == pm25.parameter_id,
                ParameterAggregationRollup.from_aggregation_period_id == ap_1m.aggregation_period_id,
                ParameterAggregationRollup.to_aggregation_period_id == ap_1h.aggregation_period_id,
            )
        )
        if not existing_roll:
            session.add(
                ParameterAggregationRollup(
                    parameter_id=pm25.parameter_id,
                    from_aggregation_period_id=ap_1m.aggregation_period_id,
                    to_aggregation_period_id=ap_1h.aggregation_period_id,
                )
            )

        purpleair_name = f"PurpleAirTest-{uuid.uuid4()}"
        openaq_name = f"OpenAQTest-{uuid.uuid4()}"
        purpleair_api = _ensure(session, ExternalAPI, "name", purpleair_name, base_url="http://example.com", params={})
        openaq_api = _ensure(session, ExternalAPI, "name", openaq_name, base_url="http://example.com", params={})

        purpleair_device = Device(name="pa-device", external_api_id=purpleair_api.external_api_id)
        openaq_device = Device(name="oa-device", external_api_id=openaq_api.external_api_id)
        session.add_all([purpleair_device, openaq_device])
        session.flush()

        purpleair_sensor = Sensor(
            device_id=purpleair_device.device_id,
            parameter_id=pm25.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=ap_1m.aggregation_period_id,
        )
        openaq_sensor = Sensor(
            device_id=openaq_device.device_id,
            parameter_id=pm25.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=ap_1m.aggregation_period_id,
        )
        session.add_all([purpleair_sensor, openaq_sensor])
        session.flush()

                                                                    
        bucket_0 = datetime(2025, 12, 13, 5, 0, tzinfo=timezone.utc)
        bucket_1 = bucket_0 + timedelta(hours=1)
        for i in range(60):
            session.add(
                Measurement(
                    sensor_id=purpleair_sensor.sensor_id,
                    value=10.0,
                    observed_at=bucket_0 + timedelta(minutes=i),
                    is_valid=True,
                )
            )
            session.add(
                Measurement(
                    sensor_id=purpleair_sensor.sensor_id,
                    value=20.0,
                    observed_at=bucket_1 + timedelta(minutes=i),
                    is_valid=True,
                )
            )
            session.add(
                Measurement(
                    sensor_id=openaq_sensor.sensor_id,
                    value=99.0,
                    observed_at=bucket_1 + timedelta(minutes=i),
                    is_valid=True,
                )
            )
        session.commit()

        client = TestClient(app)
        resp = client.get(
            "/measurements/pm25/aggregate",
            params={
                "from": "1m",
                "to": "1h",
                "since": bucket_0.isoformat(),
                "until": (bucket_1 + timedelta(hours=1)).isoformat(),
                "external_api_name": purpleair_name.lower(),
            },
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert isinstance(payload, list)

                                                                                                
        assert len(payload) == 1
        row = payload[0]
        assert row["sensor_id"] == purpleair_sensor.sensor_id
        assert row["device"]["external_api"]["name"].lower() == purpleair_name.lower()
        assert row["observed_at"].startswith(bucket_1.isoformat()[:13])               
        assert abs(row["value"] - 20.0) < 1e-6
    finally:
        session.rollback()
        session.close()
