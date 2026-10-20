from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select, delete as sa_delete

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


def ensure_unit(session, code: str, symbol: str, name: str) -> Unit:
    unit = session.scalar(select(Unit).where(Unit.code == code))
    if unit:
        return unit
    unit = Unit(code=code, symbol=symbol, name=name)
    session.add(unit)
    session.flush()
    return unit


def ensure_parameter(session, code: str, display_name: str, unit: Unit) -> Parameter:
    parameter = session.scalar(select(Parameter).where(Parameter.code == code))
    if parameter:
        return parameter
    parameter = Parameter(code=code, display_name=display_name, default_unit_id=unit.unit_id)
    session.add(parameter)
    session.flush()
    return parameter


def ensure_aggregation_period(
    session, code: str, display_name: str, duration_minutes: int | None = None
) -> AggregationPeriod:
    aggregation_period = session.scalar(select(AggregationPeriod).where(AggregationPeriod.code == code))
    if aggregation_period:
        if duration_minutes is not None:
            aggregation_period.duration_minutes = duration_minutes
        aggregation_period.is_rolling = False
        return aggregation_period
    aggregation_period = AggregationPeriod(
        code=code, display_name=display_name, duration_minutes=duration_minutes, is_rolling=False
    )
    session.add(aggregation_period)
    session.flush()
    return aggregation_period


def ensure_external_api(session, name: str = "formatting-api") -> ExternalAPI:
    external_api = session.scalar(select(ExternalAPI).where(ExternalAPI.name == name))
    if external_api:
        return external_api
    external_api = ExternalAPI(name=name, base_url="http://example.com", params={})
    session.add(external_api)
    session.flush()
    return external_api


def get_value_for_sensor(payload: list[dict], sensor_id: int) -> float | None:
    for row in payload:
        if row.get("sensor_id") == sensor_id:
            return row.get("value")
    return None


def test_native_latest_preserves_observation_with_truncation_metadata():
    session = SessionLocal()
    inserted_measurement_ids: list[int] = []
    inserted_sensor_ids: list[int] = []
    inserted_device_ids: list[int] = []
    try:
        unit = ensure_unit(session, "ug_m3", "æg/m3", "Micrograms per cubic meter")
        parameter = ensure_parameter(session, "pm25", "PM2.5", unit)
        aggregation_period = ensure_aggregation_period(session, "1h", "1 Hour", duration_minutes=60)
        external_api = ensure_external_api(session)

        device = Device(name="formatting-device-truncate", external_api_id=external_api.external_api_id)
        session.add(device)
        session.flush()
        inserted_device_ids.append(device.device_id)

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=aggregation_period.aggregation_period_id,
        )
        session.add(sensor)
        session.flush()
        inserted_sensor_ids.append(sensor.sensor_id)

        observed_at = datetime.now(timezone.utc)
        measurement = Measurement(
            sensor_id=sensor.sensor_id,
            value=12.39,
            observed_at=observed_at,
            is_valid=True,
        )
        session.add(measurement)
        session.commit()
        inserted_measurement_ids.append(measurement.measurement_id)

        client = TestClient(app)
        resp = client.get(f"/measurements/{parameter.code}/latest", params={"device_id": device.device_id})
        assert resp.status_code == 200, resp.text
        formatted_value = get_value_for_sensor(resp.json(), sensor.sensor_id)

        assert formatted_value is not None
        assert formatted_value == 12.39
        assert resp.json()[0]["display_precision"] == 1
    finally:
        try:
            if inserted_measurement_ids:
                session.execute(
                    sa_delete(Measurement).where(Measurement.measurement_id.in_(inserted_measurement_ids))
                )
            if inserted_sensor_ids:
                session.execute(sa_delete(Sensor).where(Sensor.sensor_id.in_(inserted_sensor_ids)))
            if inserted_device_ids:
                session.execute(sa_delete(Device).where(Device.device_id.in_(inserted_device_ids)))
            session.commit()
        finally:
            session.close()


def test_native_daily_latest_preserves_observation_with_rounding_metadata():
    session = SessionLocal()
    inserted_measurement_ids: list[int] = []
    inserted_sensor_ids: list[int] = []
    inserted_device_ids: list[int] = []
    try:
        unit = ensure_unit(session, "ug_m3", "æg/m3", "Micrograms per cubic meter")
        parameter = ensure_parameter(session, "pm25", "PM2.5", unit)
        aggregation_period = ensure_aggregation_period(session, "24h", "24 Hour", duration_minutes=24 * 60)
        external_api = ensure_external_api(session, name="formatting-api-rounding")

        device = Device(name="formatting-device-round", external_api_id=external_api.external_api_id)
        session.add(device)
        session.flush()
        inserted_device_ids.append(device.device_id)

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=aggregation_period.aggregation_period_id,
        )
        session.add(sensor)
        session.flush()
        inserted_sensor_ids.append(sensor.sensor_id)

        measurement = Measurement(
            sensor_id=sensor.sensor_id,
            value=10.45,
            observed_at=datetime.now(timezone.utc),
            is_valid=True,
        )
        session.add(measurement)
        session.commit()
        inserted_measurement_ids.append(measurement.measurement_id)

        client = TestClient(app)
        resp = client.get(f"/measurements/{parameter.code}/latest", params={"device_id": device.device_id})
        assert resp.status_code == 200, resp.text
        formatted_value = get_value_for_sensor(resp.json(), sensor.sensor_id)
        assert formatted_value is not None
        assert formatted_value == 10.45
        assert resp.json()[0]["display_precision"] == 1
    finally:
        try:
            if inserted_measurement_ids:
                session.execute(
                    sa_delete(Measurement).where(Measurement.measurement_id.in_(inserted_measurement_ids))
                )
            if inserted_sensor_ids:
                session.execute(sa_delete(Sensor).where(Sensor.sensor_id.in_(inserted_sensor_ids)))
            if inserted_device_ids:
                session.execute(sa_delete(Device).where(Device.device_id.in_(inserted_device_ids)))
            session.commit()
        finally:
            session.close()


def test_latest_measurements_does_not_fall_back_to_hour_rule_for_unknown_native_values():
    session = SessionLocal()
    inserted_measurement_ids: list[int] = []
    inserted_sensor_ids: list[int] = []
    inserted_device_ids: list[int] = []
    try:
        unit = ensure_unit(session, "ug_m3", "æg/m3", "Micrograms per cubic meter")
        parameter = ensure_parameter(session, "pm10", "PM10", unit)
        ensure_aggregation_period(session, "1h", "1 Hour", duration_minutes=60)
        external_api = ensure_external_api(session, name="formatting-api-fallback")

        device = Device(name="formatting-device-fallback", external_api_id=external_api.external_api_id)
        session.add(device)
        session.flush()
        inserted_device_ids.append(device.device_id)

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=None,
        )
        session.add(sensor)
        session.flush()
        inserted_sensor_ids.append(sensor.sensor_id)

        measurement = Measurement(
            sensor_id=sensor.sensor_id,
            value=2.9,
            observed_at=datetime.now(timezone.utc),
            is_valid=True,
        )
        session.add(measurement)
        session.commit()
        inserted_measurement_ids.append(measurement.measurement_id)

        client = TestClient(app)
        resp = client.get(f"/measurements/{parameter.code}/latest", params={"device_id": device.device_id})
        assert resp.status_code == 200, resp.text
        formatted_value = get_value_for_sensor(resp.json(), sensor.sensor_id)
        assert formatted_value is not None
        assert abs(formatted_value - 2.9) < 1e-6
        result = next(row for row in resp.json() if row["sensor_id"] == sensor.sensor_id)
        assert result["formatting_status"] == "not_configured"
    finally:
        try:
            if inserted_measurement_ids:
                session.execute(
                    sa_delete(Measurement).where(Measurement.measurement_id.in_(inserted_measurement_ids))
                )
            if inserted_sensor_ids:
                session.execute(sa_delete(Sensor).where(Sensor.sensor_id.in_(inserted_sensor_ids)))
            if inserted_device_ids:
                session.execute(sa_delete(Device).where(Device.device_id.in_(inserted_device_ids)))
            session.commit()
        finally:
            session.close()


def test_latest_measurements_bucketed_aggregation_formats_values():
    session = SessionLocal()
    inserted_measurement_ids: list[int] = []
    inserted_sensor_ids: list[int] = []
    inserted_device_ids: list[int] = []
    try:
        unit = ensure_unit(session, "ug_m3", "æg/m3", "Micrograms per cubic meter")
        parameter = ensure_parameter(session, "pm25", "PM2.5", unit)
        one_minute_period = ensure_aggregation_period(session, "1m", "1 Minute", duration_minutes=1)
        one_hour_period = ensure_aggregation_period(session, "1h", "1 Hour", duration_minutes=60)
        existing_rollup = session.scalar(
            select(ParameterAggregationRollup).where(
                ParameterAggregationRollup.parameter_id == parameter.parameter_id,
                ParameterAggregationRollup.from_aggregation_period_id
                == one_minute_period.aggregation_period_id,
                ParameterAggregationRollup.to_aggregation_period_id
                == one_hour_period.aggregation_period_id,
            )
        )
        if existing_rollup is None:
            session.add(
                ParameterAggregationRollup(
                    parameter_id=parameter.parameter_id,
                    from_aggregation_period_id=one_minute_period.aggregation_period_id,
                    to_aggregation_period_id=one_hour_period.aggregation_period_id,
                )
            )
        external_api = ensure_external_api(session, name="formatting-api-bucketed")

        device = Device(name="formatting-device-bucketed", external_api_id=external_api.external_api_id)
        session.add(device)
        session.flush()
        inserted_device_ids.append(device.device_id)

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=one_minute_period.aggregation_period_id,
        )
        session.add(sensor)
        session.flush()
        inserted_sensor_ids.append(sensor.sensor_id)

        bucket_start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        measurements = [
            Measurement(sensor_id=sensor.sensor_id, value=10.1, observed_at=bucket_start, is_valid=True),
            Measurement(
                sensor_id=sensor.sensor_id,
                value=10.2,
                observed_at=bucket_start + timedelta(minutes=10),
                is_valid=True,
            ),
        ]
        session.add_all(measurements)
        session.commit()
        inserted_measurement_ids.extend(m.measurement_id for m in measurements)

        client = TestClient(app)
        resp = client.get(
            f"/measurements/{parameter.code}/latest",
            params={"aggregation": "1h", "device_id": device.device_id},
        )
        assert resp.status_code == 200, resp.text
        formatted_value = get_value_for_sensor(resp.json(), sensor.sensor_id)

        assert formatted_value is not None
        assert abs(formatted_value - 10.1) < 1e-6
    finally:
        try:
            if inserted_measurement_ids:
                session.execute(
                    sa_delete(Measurement).where(Measurement.measurement_id.in_(inserted_measurement_ids))
                )
            if inserted_sensor_ids:
                session.execute(sa_delete(Sensor).where(Sensor.sensor_id.in_(inserted_sensor_ids)))
            if inserted_device_ids:
                session.execute(sa_delete(Device).where(Device.device_id.in_(inserted_device_ids)))
            session.commit()
        finally:
            session.close()


def test_latest_measurements_negative_zero_is_cleaned():
    session = SessionLocal()
    inserted_measurement_ids: list[int] = []
    inserted_sensor_ids: list[int] = []
    inserted_device_ids: list[int] = []
    try:
        unit = ensure_unit(session, "ug_m3", "æg/m3", "Micrograms per cubic meter")
        parameter = ensure_parameter(session, "pm25", "PM2.5", unit)
        aggregation_period = ensure_aggregation_period(session, "1h", "1 Hour", duration_minutes=60)
        external_api = ensure_external_api(session, name="formatting-api-negative-zero")

        device = Device(name="formatting-device-negative-zero", external_api_id=external_api.external_api_id)
        session.add(device)
        session.flush()
        inserted_device_ids.append(device.device_id)

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=aggregation_period.aggregation_period_id,
        )
        session.add(sensor)
        session.flush()
        inserted_sensor_ids.append(sensor.sensor_id)

        measurement = Measurement(
            sensor_id=sensor.sensor_id,
            value=-0.0,
            observed_at=datetime.now(timezone.utc),
            is_valid=True,
        )
        session.add(measurement)
        session.commit()
        inserted_measurement_ids.append(measurement.measurement_id)

        client = TestClient(app)
        resp = client.get(f"/measurements/{parameter.code}/latest", params={"device_id": device.device_id})
        assert resp.status_code == 200, resp.text
        formatted_value = get_value_for_sensor(resp.json(), sensor.sensor_id)
        assert formatted_value is not None
        assert formatted_value == 0.0
    finally:
        try:
            if inserted_measurement_ids:
                session.execute(
                    sa_delete(Measurement).where(Measurement.measurement_id.in_(inserted_measurement_ids))
                )
            if inserted_sensor_ids:
                session.execute(sa_delete(Sensor).where(Sensor.sensor_id.in_(inserted_sensor_ids)))
            if inserted_device_ids:
                session.execute(sa_delete(Device).where(Device.device_id.in_(inserted_device_ids)))
            session.commit()
        finally:
            session.close()
