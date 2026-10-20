"""Transactional public-history persistence through the existing ingest/QC path."""
from __future__ import annotations

from datetime import datetime, timezone
import time

from sqlalchemy import select

import models
from services.import_summaries import merge_qc_counts
from sources.airgradient import map_history
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed


def ensure_history_sensor(session, device, parameter: str, metadata: dict):
    # Import locally to retain the existing canonical catalog and period helpers
    # without coupling the provider's HTTP adapter to ORM/importer code.
    from sources.airgradient.importer import _canonical_catalog

    parameters, units = _canonical_catalog(session)
    mapping = map_history.PARAMETERS[parameter]
    reference = map_history.REFERENCE_MAPPINGS[str(device.external_id)]
    external_id = f"map:{reference.map_id}:{parameter}:15m"
    sensor = session.scalar(select(models.Sensor).where(
        models.Sensor.device_id == device.device_id,
        models.Sensor.external_sensor_id == external_id,
    ))
    created = sensor is None
    if created:
        sensor = models.Sensor(device_id=device.device_id, external_sensor_id=external_id)
        session.add(sensor)
    period = session.scalar(select(models.AggregationPeriod).where(
        models.AggregationPeriod.code == "15m",
    ))
    if period is None:
        period = models.AggregationPeriod(code="15m", display_name="15 Minutes", duration_minutes=15, is_rolling=False)
        session.add(period)
        session.flush()
    if period.duration_minutes != 15 or period.is_rolling:
        raise map_history.MapHistoryError("15m aggregation catalog has incompatible metadata")
    sensor.parameter_id = parameters[mapping.parameter_code].parameter_id
    sensor.unit_id = units[mapping.unit_code].unit_id
    sensor.aggregation_period_id = period.aggregation_period_id
    sensor.expected_frequency_seconds = map_history.BUCKET_SECONDS
    # Nominal aggregate duration is known. Actual sampled duration is unknown;
    # leaving it NULL is essential to all three existing AQI eligibility gates.
    sensor.measurement_duration_seconds = None
    sensor.source_aggregation_duration_seconds = map_history.BUCKET_SECONDS
    sensor.measurement_timestamp_semantics = "interval_start"
    sensor.measurement_metadata_status = "provider_documented"
    sensor.measurement_metadata_managed_by = "airgradient_map_history_importer"
    sensor.hourly_concentration_provenance = None
    sensor.hourly_timestamp_semantics = None
    initial_start = (sensor.acquisition_metadata or {}).get("initial_interval_start")
    sensor.acquisition_metadata = map_history.provenance(
        str(device.external_id), reference.map_id, parameter, metadata,
    )
    if initial_start is not None:
        sensor.acquisition_metadata = {**sensor.acquisition_metadata, "initial_interval_start": initial_start}
    session.flush()
    return sensor, created


def _initial_window_start(sensor, until: datetime) -> datetime:
    """Retain the first lookback anchor across outages before any successful poll."""
    initial_start = sensor.acquisition_metadata.get("initial_interval_start")
    if initial_start is None:
        initial_start = (until - map_history.INITIAL_LOOKBACK).isoformat()
        sensor.acquisition_metadata = {**sensor.acquisition_metadata, "initial_interval_start": initial_start}
    try:
        parsed = datetime.fromisoformat(initial_start.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise map_history.MapHistoryError("Invalid initial AirGradient history anchor") from exc
    if parsed != map_history.floor_bucket(parsed) or parsed > until:
        raise map_history.MapHistoryError("Invalid initial AirGradient history anchor")
    return parsed.astimezone(timezone.utc)


def _utc_checkpoint(value: datetime) -> datetime:
    # SQLite returns naive UTC. PostgreSQL can return an offset representing
    # the connection timezone; preserve the instant instead of replacing it.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def import_location_history(session, device, dashboard: dict, summary: dict, *, deadline: float, now: datetime):
    """Caller holds the shared importer advisory lock across all commits.

    Every examined interval and its upserts use one transaction. Recovery uses
    the requested interval end, including an empty successful response, rather
    than a last observed timestamp. Counters are merged only after commit.
    """
    from sources.airgradient.importer import (
        AIRGRADIENT_PUBLIC_REFERENCE_PATH,
        _apply_public_reference_attribution,
    )
    if device.acquisition_path != AIRGRADIENT_PUBLIC_REFERENCE_PATH:
        raise map_history.MapHistoryError("Map history requires an approved public reference device")
    reference = map_history.REFERENCE_MAPPINGS.get(str(device.external_id))
    if reference is None:
        raise map_history.MapHistoryError("Unapproved public history device")
    metadata = map_history.public_get(f"locations/{reference.map_id}")
    map_history.validate_location(str(device.external_id), dashboard, metadata)
    # Existing installations may predate contributor fields. Reconcile the
    # verified public attribution used by established UI and CSV surfaces.
    _apply_public_reference_attribution(device, dashboard)
    until = map_history.closed_until(now)
    summary.setdefault("history_intervals_examined", 0)
    summary.setdefault("history_intervals_failed", 0)
    summary.setdefault("history_null_buckets", 0)
    summary.setdefault("history_progress", [])
    for parameter, definition in map_history.PARAMETERS.items():
        if time.monotonic() >= deadline:
            summary["history_work_remaining"] = True
            return
        created_pending = False
        stream_counted = False
        observations = None
        try:
            sensor, created_pending = ensure_history_sensor(session, device, parameter, metadata)
            checkpoint = sensor.acquisition_examined_until
            initial_start = _initial_window_start(sensor, until)
            # Configuration is durable before HTTP: a first-poll failure must
            # not shift the initial lookback forward and lose uncommitted data.
            # No examined checkpoint or measurement is advanced by this commit.
            session.commit()
            if created_pending:
                summary["sensors_created"] += 1
                created_pending = False
            for start, end in map_history.windows(checkpoint, until, initial_start):
                if time.monotonic() >= deadline:
                    session.rollback()
                    summary["history_work_remaining"] = True
                    return
                observations = None
                observations, missing = map_history.fetch_history(reference.map_id, parameter, start, end)
                actions = {"insert": 0, "update": 0, "skip": 0}
                interval_summary = {}
                for observation in observations:
                    if time.monotonic() >= deadline:
                        session.rollback()
                        summary["history_work_remaining"] = True
                        summary["history_intervals_deferred"] = summary.get("history_intervals_deferred", 0) + 1
                        return
                    result = upsert_measurement_with_policy_detailed(
                        session,
                        models.Measurement(sensor_id=sensor.sensor_id, observed_at=observation.bucket_start,
                                           value=observation.value, is_valid=True),
                        device=device, sensor=sensor,
                    )
                    actions[result.action] += 1
                    merge_qc_counts(interval_summary, result.qc)
                sensor.acquisition_examined_until = max(
                    end, _utc_checkpoint(sensor.acquisition_examined_until or end),
                )
                session.commit()
                if not stream_counted:
                    summary["sensors_processed"] += 1
                    stream_counted = True
                summary["history_intervals_examined"] += 1
                summary["history_null_buckets"] += missing
                summary["measurements_received"] += len(observations)
                for action, counter in (("insert", "measurements_inserted"), ("update", "measurements_updated"),
                                        ("skip", "measurements_skipped")):
                    summary[counter] += actions[action]
                counts = summary["per_parameter"].setdefault(definition.parameter_code, {"insert": 0, "update": 0, "skip": 0})
                for action, count in actions.items():
                    counts[action] += count
                merge_qc_counts(summary, interval_summary.get("qc"))
                summary["history_progress"].append({
                    "dashboard_location_id": str(device.external_id), "map_location_id": reference.map_id,
                    "parameter": parameter, "start": start.isoformat(), "end": end.isoformat(),
                    "examined_until": _utc_checkpoint(sensor.acquisition_examined_until).isoformat(),
                    "received": len(observations), **actions,
                })
            if sensor.acquisition_examined_until is not None:
                examined = _utc_checkpoint(sensor.acquisition_examined_until)
                if examined < until:
                    summary["history_work_remaining"] = True
        except map_history.MapHistoryRateLimit:
            session.rollback()
            summary["history_intervals_failed"] += 1
            summary["history_work_remaining"] = True
            raise
        except Exception as exc:
            session.rollback()
            summary["history_intervals_failed"] += 1
            summary["history_work_remaining"] = True
            if observations is not None:
                summary["measurements_received"] += len(observations)
                summary["measurements_failed"] = summary.get("measurements_failed", 0) + len(observations)
            # Do not expose arbitrary database/HTTP exception text in JobRuns.
            reason = str(exc) if isinstance(exc, map_history.MapHistoryError) else "AirGradient history transaction failed"
            summary.setdefault("errors", []).append(f"Map {reference.map_id} {parameter}: {reason}")
            summary.setdefault("history_failures", []).append({
                "map_location_id": reference.map_id, "parameter": parameter,
                "error_type": type(exc).__name__, "reason": reason,
                "failed_observations": len(observations) if observations is not None else None,
            })
