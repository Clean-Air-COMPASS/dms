"""Explicit development-only loader for validated offline fixtures."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import models
from services.device_locations import set_device_location
from db import SessionLocal
from reference_data.fixture_io import (
    ReferenceFixtureError,
    read_fixture_manifest,
    read_fixture_measurements,
)


@dataclass
class FixtureLoadSummary:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    external_api_ids: dict[str, int] | None = None
    device_ids: dict[str, int] | None = None
    sensor_ids: dict[str, int] | None = None


def _catalog_row(session: Session, model, code: str, label: str):
    row = session.scalar(select(model).where(func.lower(model.code) == code.lower()))
    if row is None:
        raise ReferenceFixtureError(f"Unknown {label} code '{code}'")
    return row


def _verified_provider_hourly_metadata(fixture_sensor) -> tuple[str | None, str | None]:
    """Map explicit one-hour fixture evidence to existing sensor provenance fields.

    Frozen OpenAQ measurements retain the provider interval, duration, and
    interval-end timestamp semantics.  The normal OpenAQ importer records that
    exact combination as a provider-reported hourly average with ``hour_end``
    semantics.  The reference loader must preserve the same meaning so loading
    a frozen provider record does not make an otherwise qualified stream
    ineligible for the provider-neutral hourly calculation path.

    Anything incomplete or inconsistent remains unqualified.  This helper
    deliberately does not infer hourly provenance from provider identity.
    """
    qualification = fixture_sensor.temporal_qualification or {}
    is_consistent_one_hour_interval = (
        fixture_sensor.aggregation_period_code == "1h"
        and fixture_sensor.expected_frequency_seconds == 3600
        and fixture_sensor.measurement_duration_seconds == 3600
        and fixture_sensor.source_aggregation_duration_seconds == 3600
        and fixture_sensor.measurement_timestamp_semantics == "interval_end"
        and fixture_sensor.measurement_metadata_status == "provider_documented"
        and qualification.get("status") == "provider_documented"
        and qualification.get("provider_duration_seconds") == 3600
        and qualification.get("provider_interval_seconds") == 3600
        and qualification.get("timestamp_semantics") == "interval_end"
    )
    if not is_consistent_one_hour_interval:
        return None, None
    return "provider_reported_hourly_average", "hour_end"


def load_reference_fixture(session: Session, fixture_root: Path) -> FixtureLoadSummary:
    manifest = read_fixture_manifest(fixture_root)
    fixture_measurements = read_fixture_measurements(fixture_root, manifest)
    summary = FixtureLoadSummary(external_api_ids={}, device_ids={}, sensor_ids={})

    external_api = session.scalar(
        select(models.ExternalAPI).where(func.lower(models.ExternalAPI.name) == manifest.provider.lower())
    )
    if external_api is None:
        external_api = models.ExternalAPI(
            provider_code=manifest.provider.strip().lower(),
            name=manifest.provider,
            description=f"Offline reference fixture: {manifest.dataset_id}",
            params={
                "fixture_dataset_id": manifest.dataset_id,
                "access_classification": manifest.access_classification,
                "provider_profile": manifest.provider_profile,
                "fixture_origin": manifest.origin.model_dump(mode="json"),
                "fixture_reference_area": manifest.reference_area.model_dump(mode="json"),
                "fixture_reference_areas": [
                    area.model_dump(mode="json") for area in manifest.reference_areas
                ],
                "fixture_license": manifest.license.model_dump(mode="json"),
                "fixture_provider_chain": [
                    entry.model_dump(mode="json") for entry in manifest.provider_chain
                ],
                "fixture_provenance": manifest.provenance.model_dump(mode="json"),
                "fixture_capture": (
                    manifest.capture.model_dump(mode="json") if manifest.capture else None
                ),
                "fixture_capture_history": manifest.capture_history,
                "fixture_coverage_matrix": manifest.coverage_matrix,
                "fixture_coverage_gaps": manifest.coverage_gaps,
                "fixture_known_limitations": manifest.known_limitations,
            },
            enabled=False,
        )
        session.add(external_api)
        session.flush()
        summary.inserted += 1
    else:
        summary.skipped += 1
    summary.external_api_ids[manifest.provider] = external_api.external_api_id

    device_by_ref = {}
    for fixture_device in manifest.devices:
        device = session.scalar(
            select(models.Device).where(
                models.Device.external_api_id == external_api.external_api_id,
                models.Device.external_id == fixture_device.external_id,
            )
        )
        if device is None:
            device = models.Device(
                name=fixture_device.name,
                friendly_name=fixture_device.friendly_name,
                external_id=fixture_device.external_id,
                external_api_id=external_api.external_api_id,
                timezone=fixture_device.timezone,
                allow_updates=models.UpdatePolicy.ALLOW,
            )
            session.add(device)
            set_device_location(
                session,
                device,
                latitude=fixture_device.latitude,
                longitude=fixture_device.longitude,
            )
            summary.inserted += 1
        else:
            summary.skipped += 1
        device_by_ref[fixture_device.fixture_ref] = device
        summary.device_ids[fixture_device.fixture_ref] = device.device_id

    sensor_by_ref = {}
    for fixture_sensor in manifest.sensors:
        device = device_by_ref[fixture_sensor.device_ref]
        parameter = _catalog_row(session, models.Parameter, fixture_sensor.parameter_code, "parameter")
        unit = _catalog_row(session, models.Unit, fixture_sensor.unit_code, "unit")
        aggregation = None
        if fixture_sensor.aggregation_period_code is not None:
            aggregation = _catalog_row(
                session,
                models.AggregationPeriod,
                fixture_sensor.aggregation_period_code,
                "aggregation period",
            )
        sensor = session.scalar(
            select(models.Sensor).where(
                models.Sensor.device_id == device.device_id,
                models.Sensor.external_sensor_id == fixture_sensor.external_sensor_id,
            )
        )
        if sensor is None:
            sensor = models.Sensor(
                device_id=device.device_id,
                parameter_id=parameter.parameter_id,
                unit_id=unit.unit_id,
                aggregation_period_id=(aggregation.aggregation_period_id if aggregation else None),
                external_sensor_id=fixture_sensor.external_sensor_id,
                allow_updates=models.UpdatePolicy.ALLOW,
            )
            session.add(sensor)
            session.flush()
            summary.inserted += 1
        else:
            summary.skipped += 1
        (
            sensor.hourly_concentration_provenance,
            sensor.hourly_timestamp_semantics,
        ) = _verified_provider_hourly_metadata(fixture_sensor)
        sensor.expected_frequency_seconds = fixture_sensor.expected_frequency_seconds
        sensor.measurement_duration_seconds = fixture_sensor.measurement_duration_seconds
        sensor.source_aggregation_duration_seconds = fixture_sensor.source_aggregation_duration_seconds
        sensor.measurement_timestamp_semantics = fixture_sensor.measurement_timestamp_semantics
        sensor.measurement_metadata_status = fixture_sensor.measurement_metadata_status
        sensor.measurement_metadata_managed_by = fixture_sensor.measurement_metadata_managed_by
        sensor_by_ref[fixture_sensor.fixture_ref] = sensor
        summary.sensor_ids[fixture_sensor.fixture_ref] = sensor.sensor_id

    for fixture_measurement in fixture_measurements:
        sensor = sensor_by_ref[fixture_measurement.sensor_ref]
        existing = session.scalar(
            select(models.Measurement).where(
                models.Measurement.sensor_id == sensor.sensor_id,
                models.Measurement.observed_at == fixture_measurement.observed_at,
            )
        )
        qc_flags = dict(fixture_measurement.qc_flags or {})
        provider_capture_metadata = {
            "provider_observation_ref": fixture_measurement.provider_observation_ref,
            "source_page": fixture_measurement.source_page,
            "source_result_index": fixture_measurement.source_result_index,
            "provider_parameter": fixture_measurement.provider_parameter,
            "provider_period": fixture_measurement.provider_period,
            "provider_field": fixture_measurement.provider_field,
            "provider_timestamp": fixture_measurement.provider_timestamp,
            "provider_flag_info": fixture_measurement.provider_flag_info,
            "provider_coordinates": fixture_measurement.provider_coordinates,
            "provider_summary": fixture_measurement.provider_summary,
            "provider_coverage": fixture_measurement.provider_coverage,
        }
        provider_capture_metadata = {
            name: value
            for name, value in provider_capture_metadata.items()
            if value is not None
        }
        if provider_capture_metadata:
            qc_flags["reference_fixture_provider_capture"] = provider_capture_metadata
        incoming_fields = {
            "value": fixture_measurement.value,
            "is_valid": fixture_measurement.is_valid,
            "qc_flags": qc_flags or None,
            "qc_version": fixture_measurement.qc_version,
        }
        if existing is None:
            session.add(
                models.Measurement(
                    sensor_id=sensor.sensor_id,
                    observed_at=fixture_measurement.observed_at,
                    **incoming_fields,
                )
            )
            summary.inserted += 1
        elif all(getattr(existing, name) == value for name, value in incoming_fields.items()):
            summary.skipped += 1
        else:
            for name, value in incoming_fields.items():
                setattr(existing, name, value)
            summary.updated += 1

    session.commit()
    return summary


def _assert_development_loader_enabled(confirm_development_only: bool) -> None:
    environment = os.getenv("COMPASSAQ_ENV", "").strip().lower()
    enabled = os.getenv("ENABLE_REFERENCE_DATA_DEV_LOADER", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if environment != "development" or not enabled or not confirm_development_only:
        raise ReferenceFixtureError(
            "Reference fixture loading requires COMPASSAQ_ENV=development, "
            "ENABLE_REFERENCE_DATA_DEV_LOADER=true, and --confirm-development-only"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Load a validated offline reference fixture")
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--confirm-development-only", action="store_true")
    args = parser.parse_args()
    _assert_development_loader_enabled(args.confirm_development_only)
    with SessionLocal() as session:
        summary = load_reference_fixture(session, args.fixture_root.resolve())
    print(json.dumps(asdict(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
