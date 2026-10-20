"""Replay the offline fixture through the shared provider ingest/QC path."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from db import SessionLocal
from qaqc import discovery
from services.device_locations import set_device_location
from services.external_sources import require_task_source_runnable
from services.import_summaries import (
    merge_qc_counts,
    new_import_summary,
    write_import_summary,
)
from services.system_settings import is_system_setup_complete
from sources.demo.fixture import SAMPLES
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed

CADENCE_SECONDS = 300
INITIAL_SEED_SLOTS = 18  # 90 minutes of interval averages, ending at the current slot.
DEMO_LATITUDE = 52.0907
DEMO_LONGITUDE = 5.1214
SENSOR_DEFINITIONS = (
    ("pm25", "ug_m3", "DEMO PM2.5"),
    ("pm10", "ug_m3", "DEMO PM10"),
    ("o3", "ppm", "DEMO Ozone"),
)


def aligned_slot(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Demo clock must provide a timezone-aware instant")
    return datetime.fromtimestamp(
        int(now.timestamp()) // CADENCE_SECONDS * CADENCE_SECONDS, timezone.utc
    )


def values_for_slot(slot: datetime) -> tuple[float, float, float]:
    return SAMPLES[int(slot.timestamp()) // CADENCE_SECONDS % len(SAMPLES)]


def import_current_slot(session: Session, *, now: datetime) -> dict:
    """Caller commits observations and seed state together, or rolls both back.

    Lock the source for the whole bounded transaction, serializing manual and
    scheduled runs and source disable. After the first seed, only the current
    slot is considered: missed scheduling, downtime and disabled time are never
    backfilled. Durable state is independent of editable source params/history.
    """
    summary = new_import_summary()
    if not is_system_setup_complete(session):
        summary["skip_reason"] = "setup_incomplete"
        return summary
    source = require_task_source_runnable(session, "demo_import", for_update=True)
    slot = aligned_slot(now)
    state = session.get(models.DemoImportState, source.external_api_id)
    if state is None:
        # Lazily restored definitions and explicit upgrade activations never seed.
        state = models.DemoImportState(
            external_api_id=source.external_api_id, initial_seed_pending=False
        )
        session.add(state)
    seed = state.initial_seed_pending and state.activated_at is None
    slots = [
        slot - timedelta(seconds=CADENCE_SECONDS * i)
        for i in reversed(range(INITIAL_SEED_SLOTS if seed else 1))
    ]

    device = session.scalar(select(models.Device).where(
        models.Device.external_api_id == source.external_api_id,
        models.Device.external_id == "compassaq-sample-station",
        models.Device.acquisition_path == "demo_fixture",
    ))
    if device is None:
        device = models.Device(
            external_api_id=source.external_api_id,
            external_id="compassaq-sample-station",
            acquisition_path="demo_fixture",
            name="DEMO — CompassAQ Sample Station",
            friendly_name="Demonstration Site — Not a real monitoring location",
            hardware_provider_name="Demo Data — synthetic fixture",
            timezone="UTC",
            allow_updates=models.UpdatePolicy.DENY,
        )
        session.add(device)
        session.flush()
        set_device_location(
            session, device, latitude=DEMO_LATITUDE, longitude=DEMO_LONGITUDE,
            effective_at=slots[0] - timedelta(seconds=CADENCE_SECONDS),
        )
        summary["devices_created"] = 1
    summary["devices_processed"] = 1

    period = session.scalars(select(models.AggregationPeriod).where(
        models.AggregationPeriod.code == "5m")).one()
    sensors: list[models.Sensor] = []
    for parameter_code, unit_code, sensor_name in SENSOR_DEFINITIONS:
        parameter = session.scalars(select(models.Parameter).where(
            models.Parameter.code == parameter_code)).one()
        unit = session.scalars(select(models.Unit).where(models.Unit.code == unit_code)).one()
        sensor = session.scalar(select(models.Sensor).where(
            models.Sensor.device_id == device.device_id,
            models.Sensor.external_sensor_id == sensor_name,
        ))
        if sensor is None:
            sensor = models.Sensor(
                device_id=device.device_id,
                external_sensor_id=sensor_name,
                allow_updates=models.UpdatePolicy.DENY,
            )
            session.add(sensor)
            summary["sensors_created"] += 1
        # Provider-owned normalization metadata feeds normal completeness/AQI.
        sensor.parameter_id = parameter.parameter_id
        sensor.unit_id = unit.unit_id
        sensor.aggregation_period_id = period.aggregation_period_id
        sensor.expected_frequency_seconds = CADENCE_SECONDS
        sensor.measurement_duration_seconds = CADENCE_SECONDS
        sensor.source_aggregation_duration_seconds = CADENCE_SECONDS
        sensor.measurement_timestamp_semantics = "interval_end"
        sensor.measurement_metadata_status = "provider_documented"
        sensor.measurement_metadata_managed_by = "demo_importer"
        session.flush()
        sensors.append(sensor)
    summary["sensors_processed"] = len(sensors)
    for observed_at in slots:
        for sensor, value in zip(sensors, values_for_slot(observed_at)):
            measurement = models.Measurement(
                sensor_id=sensor.sensor_id, observed_at=observed_at, value=value
            )
            result = upsert_measurement_with_policy_detailed(
                session, measurement, device, sensor
            )
            summary["measurements_received"] += 1
            counter = {
                "insert": "measurements_inserted",
                "update": "measurements_updated",
                "skip": "measurements_skipped",
            }[result.action]
            summary[counter] += 1
            merge_qc_counts(summary, result.qc)
    state.initial_seed_pending = False
    if state.activated_at is None:
        state.activated_at = slot
    summary["initial_seed"] = bool(seed)
    session.flush()
    return summary


def run_import(*, now: datetime | None = None) -> dict:
    with SessionLocal() as session, session.begin():
        return import_current_slot(
            session, now=now if now is not None else datetime.now(timezone.utc)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-json")
    args = parser.parse_args()
    discovery.load_plugins()
    write_import_summary(run_import(), args.summary_json)


if __name__ == "__main__":
    main()
