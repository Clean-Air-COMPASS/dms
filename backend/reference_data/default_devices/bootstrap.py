"""Create the permanent default reference-device set without provider traffic."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

import models
from qaqc.policy_defaults import BASELINE_DRIFT_CHECK, get_default_qc_policy
from services.device_locations import set_device_location
from reference_data.regions import validate_reference_coordinates


_MANIFEST_PATH = Path(__file__).with_name("manifest.json")
_MANIFEST: dict[str, Any] = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
DEFAULT_REFERENCE_DEVICES_VERSION = str(_MANIFEST["version"])
_BOOTSTRAP_LOCK_ID = 483_201_771


def _lock_bootstrap_transaction(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": _BOOTSTRAP_LOCK_ID},
        )


def _system_settings_for_update(session: Session) -> models.SystemSettings:
    settings = session.scalar(select(models.SystemSettings).with_for_update())
    if settings is None:
        settings = models.SystemSettings()
        session.add(settings)
        session.flush()
    return settings


def _lookup_tables(session: Session) -> tuple[dict[str, models.Parameter], dict[str, models.Unit], dict[str, models.AggregationPeriod]]:
    parameters = {
        row.code: row for row in session.scalars(select(models.Parameter)).all()
    }
    units = {row.code: row for row in session.scalars(select(models.Unit)).all()}
    aggregation_periods = {
        row.code: row
        for row in session.scalars(select(models.AggregationPeriod)).all()
    }
    return parameters, units, aggregation_periods


def _create_missing_manifest_records(session: Session) -> tuple[int, int]:
    providers = {
        row.provider_code: row
        for row in session.scalars(
            select(models.ExternalAPI).where(models.ExternalAPI.provider_code.is_not(None))
        ).all()
    }
    parameters, units, aggregation_periods = _lookup_tables(session)
    devices_created = 0
    sensors_created = 0

    for device_definition in _MANIFEST["devices"]:
        # Validate even before looking up existing rows: a bad manifest must not
        # partially initialize a region or overwrite an administrator's device.
        validate_reference_coordinates(
            device_definition["region_code"],
            device_definition["latitude"],
            device_definition["longitude"],
        )
        provider_code = device_definition["provider_code"]
        provider = providers.get(provider_code)
        if provider is None:
            raise RuntimeError(
                f"Built-in external source '{provider_code}' must exist before reference bootstrap."
            )

        device = session.scalar(
            select(models.Device).where(
                models.Device.external_api_id == provider.external_api_id,
                models.Device.external_id == device_definition["external_id"],
            )
        )
        if device is None:
            device = models.Device(
                name=device_definition["name"],
                external_id=device_definition["external_id"],
                external_api_id=provider.external_api_id,
                timezone=device_definition["timezone"],
            )
            session.add(device)
            session.flush()
            set_device_location(
                session,
                device,
                latitude=device_definition["latitude"],
                longitude=device_definition["longitude"],
            )
            devices_created += 1

        for sensor_definition in device_definition["sensors"]:
            existing_sensor = session.scalar(
                select(models.Sensor).where(
                    models.Sensor.device_id == device.device_id,
                    models.Sensor.external_sensor_id
                    == sensor_definition["external_sensor_id"],
                )
            )
            if existing_sensor is not None:
                continue

            parameter = parameters[sensor_definition["parameter_code"]]
            unit = units[sensor_definition["unit_code"]]
            aggregation_code = sensor_definition["aggregation_period_code"]
            aggregation_period = (
                aggregation_periods[aggregation_code]
                if aggregation_code is not None
                else None
            )
            session.add(
                models.Sensor(
                    device_id=device.device_id,
                    parameter_id=parameter.parameter_id,
                    unit_id=unit.unit_id,
                    aggregation_period_id=(
                        aggregation_period.aggregation_period_id
                        if aggregation_period is not None
                        else None
                    ),
                    external_sensor_id=sensor_definition["external_sensor_id"],
                    expected_frequency_seconds=sensor_definition[
                        "expected_frequency_seconds"
                    ],
                    measurement_duration_seconds=sensor_definition[
                        "measurement_duration_seconds"
                    ],
                    source_aggregation_duration_seconds=sensor_definition[
                        "source_aggregation_duration_seconds"
                    ],
                    measurement_timestamp_semantics=sensor_definition[
                        "measurement_timestamp_semantics"
                    ],
                    measurement_metadata_status=sensor_definition[
                        "measurement_metadata_status"
                    ],
                    measurement_metadata_managed_by="default_reference_manifest",
                )
            )
            sensors_created += 1
    session.flush()
    return devices_created, sensors_created


def _create_initial_baseline_drift_rule(session: Session) -> None:
    """Create the one clean-install sensor example without enforcing it later."""
    selected_sensors = [
        (device_definition, sensor_definition)
        for device_definition in _MANIFEST["devices"]
        for sensor_definition in device_definition["sensors"]
        if sensor_definition.get("enable_baseline_drift_screening_preset") is True
    ]
    if len(selected_sensors) != 1:
        raise RuntimeError(
            "The default reference manifest must select exactly one "
            "Baseline Drift example sensor."
        )

    device_definition, sensor_definition = selected_sensors[0]
    provider = session.scalar(
        select(models.ExternalAPI).where(
            models.ExternalAPI.provider_code == device_definition["provider_code"]
        )
    )
    if provider is None:
        raise RuntimeError("The selected Baseline Drift provider is unavailable.")

    device = session.scalar(
        select(models.Device).where(
            models.Device.external_api_id == provider.external_api_id,
            models.Device.external_id == device_definition["external_id"],
        )
    )
    if device is None:
        raise RuntimeError("The selected Baseline Drift example device is unavailable.")

    sensor = session.scalar(
        select(models.Sensor).where(
            models.Sensor.device_id == device.device_id,
            models.Sensor.external_sensor_id == sensor_definition["external_sensor_id"],
        )
    )
    if sensor is None:
        raise RuntimeError("The selected Baseline Drift example sensor is unavailable.")

    parameter = session.get(models.Parameter, sensor.parameter_id)
    unit = session.get(models.Unit, sensor.unit_id)
    if parameter is None or unit is None:
        raise RuntimeError(
            "The selected Baseline Drift sensor must have an explicit "
            "parameter and unit."
        )
    if (
        parameter.code != sensor_definition["parameter_code"]
        or unit.code != sensor_definition["unit_code"]
    ):
        raise RuntimeError(
            "The selected Baseline Drift sensor does not match its stable "
            "manifest identity."
        )

    existing_rule = session.scalar(
        select(models.QCRule).where(
            models.QCRule.check_code == BASELINE_DRIFT_CHECK,
            models.QCRule.sensor_id == sensor.sensor_id,
            models.QCRule.policy_unit_id == unit.unit_id,
            models.QCRule.aggregate_code.is_(None),
        )
    )
    if existing_rule is not None:
        return

    screening_preset = get_default_qc_policy(
        parameter.code,
        unit.code,
        BASELINE_DRIFT_CHECK,
    )
    if screening_preset is None or screening_preset.enabled:
        raise RuntimeError(
            "The clean-install Baseline Drift example requires an "
            "Off-by-default screening preset."
        )

    # Copy every preset property into the sensor rule so its behavior remains
    # explicit and traceable even though the parameter default stays Off.
    session.add(
        models.QCRule(
            check_code=BASELINE_DRIFT_CHECK,
            sensor_id=sensor.sensor_id,
            enabled_override=True,
            failure_action_override=screening_preset.failure_action,
            settings=dict(screening_preset.settings),
            policy_unit_id=unit.unit_id,
            version=1,
            state="active",
        )
    )
    session.flush()


def initialize_default_reference_devices(session: Session) -> tuple[int, int]:
    """Initialize once; after the marker is set, deletions remain deleted."""
    _lock_bootstrap_transaction(session)
    settings = _system_settings_for_update(session)
    if settings.default_reference_devices_version is not None:
        return 0, 0

    result = _create_missing_manifest_records(session)
    _create_initial_baseline_drift_rule(session)
    settings.default_reference_devices_version = DEFAULT_REFERENCE_DEVICES_VERSION
    session.add(settings)
    session.flush()
    return result


def restore_missing_default_reference_devices(session: Session) -> tuple[int, int]:
    """Explicitly restore missing manifest devices/sensors without overwriting edits."""
    _lock_bootstrap_transaction(session)
    return _create_missing_manifest_records(session)
