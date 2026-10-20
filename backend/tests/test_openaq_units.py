from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select

from db import SessionLocal
from models import Device, ExternalAPI, Measurement, Parameter, Sensor, Unit
from sources.openaq.openaq_upserts import (
    _upsert_sensor_for_device,
    normalize_and_upsert_from_parameter_latest,
    upsert_measurement_with_policy,
)
from sources.openaq.importer import (
    _apply_new_openaq_gas_period_metadata,
    _apply_new_openaq_ozone_period_metadata,
)


def _ensure_external_api(session) -> ExternalAPI:
    existing = session.scalar(select(ExternalAPI).where(ExternalAPI.name == "unit-test-api"))
    if existing:
        return existing
    api = ExternalAPI(name="unit-test-api", base_url="http://example.com", params={})
    session.add(api)
    session.flush()
    return api


def test_normalize_preserves_reported_o3_mass_unit_without_conversion():
    session = SessionLocal()
    try:
        param_map = dict(session.execute(select(Parameter.code, Parameter.parameter_id)).all())
        param_default_unit = dict(session.execute(select(Parameter.code, Parameter.default_unit_id)).all())
        unit_code_map = dict(session.execute(select(Unit.code, Unit.unit_id)).all())
        unit_symbol_map = dict(session.execute(select(Unit.symbol, Unit.unit_id)).all())
        unit_id_code_map = {uid: code for code, uid in unit_code_map.items()}

        items = [
            {
                "parameter": "o3",
                "value": 1963.0,
                "unit": "µg/m³",
                "datetime": {"utc": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat()},
                "locationId": "loc-x",
                "sensorId": "sens-x",
                "id": "m-1",
            }
        ]
        rows = normalize_and_upsert_from_parameter_latest(
            items,
            parameter_name="o3",
            param_map=param_map,
            unit_code_map=unit_code_map,
            unit_symbol_map=unit_symbol_map,
            param_default_unit=param_default_unit,
            unit_id_code_map=unit_id_code_map,
        )
        assert rows
        assert rows[0].value == 1963.0
        assert getattr(rows[0], "_unit_id") == unit_code_map.get("ug_m3")
    finally:
        session.rollback()
        session.close()


def test_normalize_preserves_reported_o3_ppb_for_exact_aqi_conversion():
    session = SessionLocal()
    try:
        param_map = dict(session.execute(select(Parameter.code, Parameter.parameter_id)).all())
        param_default_unit = dict(session.execute(select(Parameter.code, Parameter.default_unit_id)).all())
        unit_code_map = dict(session.execute(select(Unit.code, Unit.unit_id)).all())
        unit_symbol_map = dict(session.execute(select(Unit.symbol, Unit.unit_id)).all())
        rows = normalize_and_upsert_from_parameter_latest(
            [{
                "parameter": "o3",
                "value": 78.0,
                "unit": "ppb",
                "datetime": {"utc": "2025-01-01T00:00:00Z"},
            }],
            parameter_name="o3",
            param_map=param_map,
            unit_code_map=unit_code_map,
            unit_symbol_map=unit_symbol_map,
            param_default_unit=param_default_unit,
            unit_id_code_map={uid: code for code, uid in unit_code_map.items()},
        )
        assert rows[0].value == 78.0
        assert getattr(rows[0], "_unit_id") == unit_code_map["ppb"]
    finally:
        session.rollback()
        session.close()


def test_upsert_sensor_does_not_rewrite_existing_ozone_measurements_or_unit():
    session = SessionLocal()
    try:
        o3 = session.scalar(select(Parameter).where(Parameter.code == "o3"))
        ug = session.scalar(select(Unit).where(Unit.code == "ug_m3"))
        ppm = session.scalar(select(Unit).where(Unit.code == "ppm"))
        ext = _ensure_external_api(session)
        device = Device(name="unit-fix-device", external_api_id=ext.external_api_id)
        session.add(device)
        session.flush()
        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=o3.parameter_id if o3 else None,
            unit_id=ug.unit_id if ug else None,
            external_sensor_id="ext-test",
        )
        session.add(sensor)
        session.flush()

        obs = datetime(2025, 1, 1, tzinfo=timezone.utc)
        session.add(Measurement(sensor_id=sensor.sensor_id, value=1963.0, observed_at=obs, is_valid=True))
        session.flush()

        unit_lookup = {ug.unit_id: "ug_m3", ppm.unit_id: "ppm"} if ug and ppm else {}
        sensor_out = _upsert_sensor_for_device(
            session,
            device,
            "o3",
            "ext-test",
            parameter_id=o3.parameter_id if o3 else None,
            unit_id=ppm.unit_id if ppm else None,
            unit_id_code_map=unit_lookup,
            convert_unit=True,
        )
        session.flush()
        session.refresh(sensor_out)

        converted = session.scalar(select(Measurement.value).where(Measurement.sensor_id == sensor.sensor_id))
        if ug:
            assert sensor_out.unit_id == ug.unit_id
        assert converted == 1963.0
    finally:
        session.rollback()
        session.close()


def test_openaq_period_metadata_qualifies_only_new_ozone_streams():
    session = SessionLocal()
    try:
        o3 = session.scalar(select(Parameter).where(Parameter.code == "o3"))
        ppm = session.scalar(select(Unit).where(Unit.code == "ppm"))
        ext = _ensure_external_api(session)
        device = Device(name="period-metadata-device", external_api_id=ext.external_api_id)
        session.add(device)
        session.flush()
        new_sensor = Sensor(
            device_id=device.device_id,
            parameter_id=o3.parameter_id,
            unit_id=ppm.unit_id,
            external_sensor_id="new-period-stream",
        )
        legacy_sensor = Sensor(
            device_id=device.device_id,
            parameter_id=o3.parameter_id,
            unit_id=ppm.unit_id,
            external_sensor_id="legacy-period-stream",
        )
        session.add_all((new_sensor, legacy_sensor))
        session.flush()
        session.add(Measurement(
            sensor_id=legacy_sensor.sensor_id,
            value=0.078,
            observed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            is_valid=True,
        ))
        session.flush()
        period = {
            "interval": "PT1H",
            "datetimeFrom": {"utc": "2025-01-01T00:00:00Z"},
            "datetimeTo": {"utc": "2025-01-01T01:00:00Z"},
        }

        _apply_new_openaq_ozone_period_metadata(
            session, new_sensor, parameter_code="o3", period=period
        )
        _apply_new_openaq_ozone_period_metadata(
            session, legacy_sensor, parameter_code="o3", period=period
        )

        assert new_sensor.hourly_concentration_provenance == "provider_reported_hourly_average"
        assert new_sensor.hourly_timestamp_semantics == "hour_end"
        assert new_sensor.measurement_metadata_status == "provider_documented"
        assert legacy_sensor.hourly_concentration_provenance is None
        assert legacy_sensor.measurement_metadata_status is None
    finally:
        session.rollback()
        session.close()


def test_normalize_preserves_reported_units_for_remaining_aqi_gases():
    session = SessionLocal()
    try:
        param_map = dict(session.execute(select(Parameter.code, Parameter.parameter_id)).all())
        param_default_unit = dict(session.execute(select(Parameter.code, Parameter.default_unit_id)).all())
        unit_code_map = dict(session.execute(select(Unit.code, Unit.unit_id)).all())
        unit_symbol_map = dict(session.execute(select(Unit.symbol, Unit.unit_id)).all())
        rows = normalize_and_upsert_from_parameter_latest(
            [
                {"parameter": "co", "value": 4400.0, "unit": "ppb", "datetime": {"utc": "2025-01-01T00:00:00Z"}},
                {"parameter": "no2", "value": 0.053, "unit": "ppm", "datetime": {"utc": "2025-01-01T00:00:00Z"}},
                {"parameter": "so2", "value": 262.0, "unit": "µg/m³", "datetime": {"utc": "2025-01-01T00:00:00Z"}},
            ],
            parameter_name="",
            param_map=param_map,
            unit_code_map=unit_code_map,
            unit_symbol_map=unit_symbol_map,
            param_default_unit=param_default_unit,
            unit_id_code_map={uid: code for code, uid in unit_code_map.items()},
        )

        assert [row.value for row in rows] == [4400.0, 0.053, 262.0]
        assert getattr(rows[0], "_unit_id") == unit_code_map["ppb"]
        assert getattr(rows[1], "_unit_id") == unit_code_map["ppm"]
        assert getattr(rows[2], "_unit_id") == unit_code_map["ug_m3"]
    finally:
        session.rollback()
        session.close()


def test_new_openaq_period_metadata_qualifies_each_supported_aqi_gas():
    session = SessionLocal()
    try:
        ext = _ensure_external_api(session)
        device = Device(name="gas-period-device", external_api_id=ext.external_api_id)
        session.add(device)
        session.flush()
        period = {
            "interval": "PT1H",
            "datetimeFrom": {"utc": "2025-01-01T00:00:00Z"},
            "datetimeTo": {"utc": "2025-01-01T01:00:00Z"},
        }

        for parameter_code in ("co", "no2", "so2"):
            parameter = session.scalar(
                select(Parameter).where(Parameter.code == parameter_code)
            )
            sensor = Sensor(
                device_id=device.device_id,
                parameter_id=parameter.parameter_id,
                external_sensor_id=f"new-{parameter_code}-period-stream",
            )
            session.add(sensor)
            session.flush()
            _apply_new_openaq_gas_period_metadata(
                session,
                sensor,
                parameter_code=parameter_code,
                period=period,
            )
            assert sensor.hourly_concentration_provenance == (
                "provider_reported_hourly_average"
            )
            assert sensor.hourly_timestamp_semantics == "hour_end"
            assert sensor.measurement_metadata_status == "provider_documented"
            assert sensor.measurement_metadata_managed_by == "openaq_importer"
    finally:
        session.rollback()
        session.close()


def test_openaq_skips_gas_measurement_when_reported_unit_changes():
    session = SessionLocal()
    try:
        co = session.scalar(select(Parameter).where(Parameter.code == "co"))
        ppm = session.scalar(select(Unit).where(Unit.code == "ppm"))
        ppb = session.scalar(select(Unit).where(Unit.code == "ppb"))
        ext = _ensure_external_api(session)
        device = Device(name="gas-unit-change-device", external_api_id=ext.external_api_id)
        session.add(device)
        session.flush()
        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=co.parameter_id,
            unit_id=ppm.unit_id,
            external_sensor_id="co-unit-change",
        )
        session.add(sensor)
        session.flush()
        measurement = Measurement(
            sensor_id=sensor.sensor_id,
            value=4400.0,
            observed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            is_valid=True,
        )
        setattr(measurement, "_parameter_code", "co")
        setattr(measurement, "_unit_id", ppb.unit_id)

        action = upsert_measurement_with_policy(
            session, measurement, device=device, sensor=sensor
        )

        assert action == "skip"
        assert measurement not in session.new
        assert sensor.unit_id == ppm.unit_id
    finally:
        session.rollback()
        session.close()
