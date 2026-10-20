from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def test_pm25_1m_to_1h_aggregate_endpoint_returns_bucket():
    """Regression: 1m sensors should aggregate to 1h buckets with completeness check."""
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

        ext = _ensure(session, ExternalAPI, "name", "agg-test", base_url="http://example.com", params={})
        device = Device(name="agg-device", external_api_id=ext.external_api_id)
        session.add(device)
        session.flush()
        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=pm25.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=ap_1m.aggregation_period_id,
        )
        session.add(sensor)
        session.flush()

                                                                            
        t0 = datetime(2025, 12, 8, 7, 0, tzinfo=timezone.utc)
        for i in range(60):
            session.add(
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=10.0 + i,
                    observed_at=t0 + timedelta(minutes=i),
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
                "since": (t0).isoformat(),
                "until": (t0 + timedelta(hours=1)).isoformat(),
            },
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert isinstance(payload, list)
        matching = [row for row in payload if row.get("sensor_id") == sensor.sensor_id]
        assert matching, f"Expected aggregated row for sensor {sensor.sensor_id}, got {payload}"
        first = matching[0]
                                  
        assert abs(first["value"] - 39.5) < 1e-6
        assert first["observed_at"].startswith("2025-12-08T07:00")
        assert first["native_aggregation_code"] == "1m"
        assert first["result_aggregation_code"] == "1h"
        assert first["interval_ended_at"].startswith("2025-12-08T08:00")
        assert first["sample_count"] == 60

        capabilities_response = client.get(
            "/measurement-aggregation-capabilities",
            params={"parameter": "pm25", "native_aggregation_code": "1m"},
        )
        assert capabilities_response.status_code == 200, capabilities_response.text
        capability = capabilities_response.json()[0]
        supported_codes = {
            option["result_aggregation_code"]
            for option in capability["supported_aggregations"]
        }
        assert {"1m", "1h"}.issubset(supported_codes)
    finally:
        session.rollback()
        session.close()
