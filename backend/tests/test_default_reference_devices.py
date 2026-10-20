from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import models
from reference_data.default_devices import (
    DEFAULT_REFERENCE_DEVICES_VERSION,
    initialize_default_reference_devices,
    restore_missing_default_reference_devices,
)
from qaqc.policy import resolve_effective_qc_policy, resolve_parameter_qc_policy
from services.external_sources import ensure_builtin_external_apis


def _reference_session(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'references.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    ug_m3 = models.Unit(
        code="ug_m3", symbol="µg/m³", name="Micrograms per cubic meter"
    )
    ppm = models.Unit(code="ppm", symbol="ppm", name="Parts per million")
    session.add_all([ug_m3, ppm])
    session.flush()
    for code, display_name, unit in (
        ("pm25", "PM2.5", ug_m3),
        ("pm10", "PM10", ug_m3),
        ("o3", "O₃", ppm),
        ("no2", "NO₂", ppm),
        ("so2", "SO₂", ppm),
        ("co", "CO", ppm),
    ):
        session.add(
            models.Parameter(
                code=code,
                display_name=display_name,
                default_unit_id=unit.unit_id,
            )
        )
    session.add_all(
        [
            models.AggregationPeriod(
                code="1h",
                display_name="1-hour average",
                duration_minutes=60,
                expected_interval="01:00:00",
            ),
            models.AggregationPeriod(
                code="2m",
                display_name="2 Minutes",
                duration_minutes=2,
                expected_interval="00:02:00",
            ),
        ]
    )
    ensure_builtin_external_apis(session)
    session.commit()
    return session


def test_first_install_creates_exact_metadata_without_measurements(tmp_path):
    session = _reference_session(tmp_path)
    try:
        assert initialize_default_reference_devices(session) == (7, 19)
        session.commit()

        settings = session.scalar(select(models.SystemSettings))
        assert settings.default_reference_devices_version == DEFAULT_REFERENCE_DEVICES_VERSION
        assert session.scalar(select(func.count()).select_from(models.Device)) == 7
        assert session.scalar(select(func.count()).select_from(models.Sensor)) == 19
        assert session.scalar(select(func.count()).select_from(models.Measurement)) == 0

        airgradient = session.scalar(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == "airgradient"
            )
        )
        assert session.scalar(
            select(func.count())
            .select_from(models.Device)
            .where(models.Device.external_api_id == airgradient.external_api_id)
        ) == 0

        purpleair = session.scalar(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == "purpleair"
            )
        )
        devices = {
            device.external_id: device
            for device in session.scalars(
                select(models.Device).where(
                    models.Device.external_api_id == purpleair.external_api_id
                )
            ).all()
        }
        assert set(devices) == {"159361", "175407", "99177"}
        assert devices["159361"].name == "UAlbany - Queens College(DEC)"
        assert devices["159361"].latitude == 40.736748
        assert devices["159361"].longitude == -73.82209
        assert devices["99177"].name == "Calzada, Taguig"
        assert devices["99177"].latitude == 14.536089
        assert devices["99177"].longitude == 121.07563
        assert devices["175407"].name == "LQA PUC RIO"
        assert devices["175407"].latitude == -22.979204
        assert devices["175407"].longitude == -43.23326

        sensor_ids = set(
            session.scalars(select(models.Sensor.external_sensor_id)).all()
        )
        assert "159361:pm2.5_atm" in sensor_ids
        assert "159361:pm10.0_atm" in sensor_ids
        assert "99177:pm2.5_atm" in sensor_ids
        assert all("198733" not in sensor_id for sensor_id in sensor_ids)
        assert all("-pm25" not in sensor_id for sensor_id in sensor_ids)
        assert all("-pm10" not in sensor_id for sensor_id in sensor_ids)

        baseline_rules = list(
            session.scalars(
                select(models.QCRule).where(
                    models.QCRule.check_code == "baseline_drift"
                )
            ).all()
        )
        assert len(baseline_rules) == 1
        baseline_rule = baseline_rules[0]
        selected_sensor = session.scalar(
            select(models.Sensor)
            .join(models.Device, models.Device.device_id == models.Sensor.device_id)
            .join(
                models.ExternalAPI,
                models.ExternalAPI.external_api_id == models.Device.external_api_id,
            )
            .where(
                models.ExternalAPI.provider_code == "purpleair",
                models.Device.external_id == "159361",
                models.Sensor.external_sensor_id == "159361:pm2.5_atm",
            )
        )
        assert selected_sensor is not None
        assert baseline_rule.sensor_id == selected_sensor.sensor_id
        assert baseline_rule.parameter_id is None
        assert baseline_rule.external_api_id is None
        assert baseline_rule.aggregate_code is None
        assert baseline_rule.policy_unit_id == selected_sensor.unit_id
        assert baseline_rule.enabled_override is True
        assert baseline_rule.failure_action_override == "flag_for_review"
        assert baseline_rule.settings == {
            "lookback_hours": 168,
            "min_samples": 72,
            "baseline_quantile": 0.1,
            "max_drift_per_day": 5.0,
            "direction": "both",
        }

        sensor_policy = resolve_effective_qc_policy(
            session,
            selected_sensor.sensor_id,
            "baseline_drift",
        )
        assert sensor_policy.enabled is True
        assert sensor_policy.status == "ready"
        assert sensor_policy.failure_action == "flag_for_review"
        assert sensor_policy.most_specific_source.layer == "sensor_override"
        parameter_policy = resolve_parameter_qc_policy(
            session,
            selected_sensor.parameter_id,
            "baseline_drift",
            "ug_m3",
        )
        assert parameter_policy.enabled is False
        assert parameter_policy.status == "disabled"
    finally:
        session.close()


def test_normal_startup_preserves_edits_and_respects_deletions(tmp_path):
    session = _reference_session(tmp_path)
    try:
        initialize_default_reference_devices(session)
        session.commit()
        openaq = session.scalar(
            select(models.ExternalAPI).where(models.ExternalAPI.provider_code == "openaq")
        )
        edited = session.scalar(
            select(models.Device).where(
                models.Device.external_api_id == openaq.external_api_id,
                models.Device.external_id == "971",
            )
        )
        edited.name = "Administrator name"
        deleted_sensor = edited.sensors[0]
        session.delete(deleted_sensor)
        deleted_device = session.scalar(
            select(models.Device).where(
                models.Device.external_api_id == openaq.external_api_id,
                models.Device.external_id == "626",
            )
        )
        seeded_rule = session.scalar(
            select(models.QCRule).where(
                models.QCRule.check_code == "baseline_drift"
            )
        )
        seeded_rule.settings = {**seeded_rule.settings, "max_drift_per_day": 4.0}
        session.delete(deleted_device)
        session.commit()

        assert initialize_default_reference_devices(session) == (0, 0)
        session.commit()
        assert edited.name == "Administrator name"
        assert session.get(models.Sensor, deleted_sensor.sensor_id) is None
        assert session.get(models.Device, deleted_device.device_id) is None
        assert seeded_rule.settings["max_drift_per_day"] == 4.0

        session.delete(seeded_rule)
        session.commit()
        assert initialize_default_reference_devices(session) == (0, 0)
        session.commit()
        assert session.scalar(
            select(func.count())
            .select_from(models.QCRule)
            .where(models.QCRule.check_code == "baseline_drift")
        ) == 0
    finally:
        session.close()


def test_explicit_restore_creates_only_missing_records(tmp_path):
    session = _reference_session(tmp_path)
    try:
        initialize_default_reference_devices(session)
        session.commit()
        purpleair = session.scalar(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == "purpleair"
            )
        )
        existing = session.scalar(
            select(models.Device).where(
                models.Device.external_api_id == purpleair.external_api_id,
                models.Device.external_id == "175407",
            )
        )
        existing.name = "Administrator-edited Rio reference"
        deleted = session.scalar(
            select(models.Device).where(
                models.Device.external_api_id == purpleair.external_api_id,
                models.Device.external_id == "99177",
            )
        )
        session.delete(deleted)
        session.commit()

        assert restore_missing_default_reference_devices(session) == (1, 2)
        session.commit()
        restored = session.scalar(
            select(models.Device).where(
                models.Device.external_api_id == purpleair.external_api_id,
                models.Device.external_id == "99177",
            )
        )
        assert restored is not None
        assert restored.name == "Calzada, Taguig"
        assert restored.latitude == 14.536089
        assert restored.longitude == 121.07563
        assert existing.name == "Administrator-edited Rio reference"
    finally:
        session.close()
