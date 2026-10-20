from __future__ import annotations

import argparse
import json
import os
import logging
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional

import requests
from sqlalchemy import select, func

import models
from qaqc import discovery
from services.device_locations import set_device_location, validate_coordinate_pair
from db import SessionLocal
from sources.measurement_metadata import (
    MeasurementMetadataManager,
    MeasurementMetadataStatus,
    MeasurementTimestampSemantics,
)
from services.provider_safety import (
    assert_paid_provider_http_authorized,
    paid_provider_request_scope,
    require_purpleair_import_authorization,
)
from services.import_summaries import (
    merge_qc_counts,
    new_import_summary,
    write_import_summary,
)
                                                                              
try:
    from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed
except Exception:                                                           
    upsert_measurement_with_policy_detailed = None

try:
    from timezonefinder import TimezoneFinder
except ImportError:                                                                               
    TimezoneFinder = None

                                                              
DEFAULT_BASE_URL = "https://api.purpleair.com/v1/sensors"

               
logger = logging.getLogger(__name__)

                                     
DEVICE_FIELDS = [
                                   
    "name",
    "latitude",
    "longitude",
]

                                                                                                  
SENSOR_FIELDS: list[str] = []

MEASUREMENT_FIELDS = [
    "pm2.5_atm",
    "pm10.0_atm",
]
PURPLEAIR_SENSOR_FIELD_BY_PARAMETER = {
    "pm25": "pm2.5_atm",
    "pm10": "pm10.0_atm",
}

# PurpleAir documents average=0 history values as two-minute "real-time"
# averages. The unsuffixed PM fields are provider-combined channel values.
# History time_stamp is the time the provider received the channel data, not
# a documented interval boundary.
PURPLEAIR_METADATA_REFRESH_SECONDS = 24 * 60 * 60
PURPLEAIR_MINIMUM_POLL_SECONDS = 120
PURPLEAIR_EXPECTED_FREQUENCY_SECONDS = 120
PURPLEAIR_MEASUREMENT_DURATION_SECONDS = 120
PURPLEAIR_SOURCE_AGGREGATION_DURATION_SECONDS = 120
PURPLEAIR_TIMESTAMP_SEMANTICS = (
    MeasurementTimestampSemantics.PROVIDER_RECEIVED_AT.value
)
PURPLEAIR_METADATA_STATUS = MeasurementMetadataStatus.PROVIDER_DOCUMENTED.value
PURPLEAIR_METADATA_MANAGER = MeasurementMetadataManager.PURPLEAIR_IMPORTER.value


class PurpleAirImporterError(Exception):
    """Raised for recoverable importer issues."""


def _load_purpleair_config(session) -> tuple[models.ExternalAPI, str, list[str], Optional[str]]:
    """Load PurpleAir config row and resolve sensor indexes from PurpleAir devices."""
    record = session.scalars(
        select(models.ExternalAPI).where(
            models.ExternalAPI.provider_code == "purpleair"
        )
    ).one_or_none()
    if not record:
        raise PurpleAirImporterError("ExternalAPI configuration for PurpleAir not found")

    base_url = record.base_url.rstrip("/") if record.base_url else DEFAULT_BASE_URL
    # Only configured devices are import targets. Never infer a sensor index
    # from arbitrary digits in a URL (the /v1/ API version is not a sensor).
    statement = select(models.Device.external_id).where(
        models.Device.external_api_id == record.external_api_id,
        models.Device.external_id.is_not(None),
    )
    env_target = os.getenv("PURPLEAIR_TARGET_SENSOR_ID")
    if env_target:
        statement = statement.where(models.Device.external_id == env_target.strip())
    sensor_indices = list(dict.fromkeys(
        str(sid).strip()
        for sid in session.scalars(statement).all()
        if str(sid).strip()
    ))

    api_key = record.api_key or os.getenv("PURPLEAIR_API_KEY")
    logger.info("Resolved %s PurpleAir device(s) for import", len(sensor_indices))
    return record, base_url, list(sensor_indices), api_key


def _ensure_aggregation_period(session, code: str = "2m", display_name: str = "2 Minutes") -> Optional[int]:
    ap = session.scalars(
        select(models.AggregationPeriod).where(func.lower(models.AggregationPeriod.code) == code.lower())
    ).one_or_none()
    if ap:
        ap.duration_minutes = 2
        ap.expected_interval = "00:02:00"
        return ap.aggregation_period_id
    ap = models.AggregationPeriod(
        code=code,
        display_name=display_name,
        duration_minutes=2,
        is_rolling=False,
        expected_interval="00:02:00",
    )
    session.add(ap)
    session.flush()
    return ap.aggregation_period_id


def _lookup_unit_id(session, code: str) -> Optional[int]:
    unit = session.scalars(select(models.Unit).where(func.lower(models.Unit.code) == code.lower())).one_or_none()
    return unit.unit_id if unit else None


def _lookup_timezone(lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    """Return IANA timezone for coordinates, or None when unavailable."""
    if TimezoneFinder is None or lat is None or lon is None:
        return None
    try:
        return TimezoneFinder().timezone_at(lat=lat, lng=lon)
    except Exception:
        return None


def _latest_observed_at_for_sensors(session, sensors: Iterable[models.Sensor]) -> Optional[datetime]:
    """Return the latest observed_at across the provided sensors, normalized to UTC."""
    sensor_ids = [s.sensor_id for s in sensors if s and getattr(s, "sensor_id", None)]
    if not sensor_ids:
        return None
    last_obs = session.scalar(
        select(func.max(models.Measurement.observed_at)).where(models.Measurement.sensor_id.in_(sensor_ids))
    )
    if isinstance(last_obs, datetime) and last_obs.tzinfo is None:
        last_obs = last_obs.replace(tzinfo=timezone.utc)
    return last_obs


def _api_get(base_url: str, sensor_index: str, fields: Iterable[str], api_key: Optional[str] = None) -> dict:
    """Call PurpleAir sensor endpoint with the requested fields."""
    assert_paid_provider_http_authorized("PurpleAir")
    url = f"{base_url.rstrip('/')}/{sensor_index}"
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    params = {"fields": ",".join(fields)}
    logger.info(
        "PurpleAir metadata request sensor_index=%s fields=%s retries=0",
        sensor_index,
        params["fields"],
    )
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        body_snippet = resp.text[:200] if resp is not None else ""
        logger.error("PurpleAir GET failed (%s): %s", exc, body_snippet)
        raise PurpleAirImporterError(f"PurpleAir GET failed: {exc}") from exc
    except Exception as exc:
        logger.error("PurpleAir GET encountered error: %s", exc)
        raise

    payload = resp.json()
    if not isinstance(payload, dict) or payload.get("error"):
        raise PurpleAirImporterError("PurpleAir returned an invalid or error response")
    return payload

def _api_get_history(
    base_url: str,
    sensor_index: str,
    fields: Iterable[str],
    start_timestamp: int,
    end_timestamp: int,
    api_key: Optional[str] = None,
) -> dict:
    """Call PurpleAir history endpoint for a sensor."""
    assert_paid_provider_http_authorized("PurpleAir")
    url = f"{base_url.rstrip('/')}/{sensor_index}/history"
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    params = {
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "fields": ",".join(fields),
                                                                                           
        "average": 0,
    }

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        body_snippet = resp.text[:200] if resp is not None else ""
        logger.error("PurpleAir history GET failed (%s): %s", exc, body_snippet)
        raise PurpleAirImporterError(f"PurpleAir history GET failed: {exc}") from exc
    except Exception as exc:
        logger.error("PurpleAir history GET encountered error: %s", exc)
        raise

    payload = resp.json()
    if not isinstance(payload, dict) or payload.get("error"):
        raise PurpleAirImporterError("PurpleAir returned an invalid or error response")
    return payload


def _ensure_device(
    session,
    base_url: str,
    sensor_index: str,
    external_api_id: Optional[int],
    api_key: Optional[str],
    *,
    refresh_metadata: bool = True,
) -> models.Device:
    existing = session.scalars(
        select(models.Device).where(
            models.Device.external_api_id == external_api_id,
            models.Device.external_id == str(sensor_index),
        )
    ).one_or_none()
    if existing and not refresh_metadata:
        return existing
    if existing:
                                             
        if external_api_id and existing.external_api_id is None:
            existing.external_api_id = external_api_id
                                                         
        payload = _api_get(base_url, sensor_index, DEVICE_FIELDS, api_key=api_key)
        sensor_obj = payload.get("sensor", {}) if isinstance(payload, dict) else {}
        provider_name = sensor_obj.get("name")
        if isinstance(provider_name, str) and provider_name.strip():
            normalized_provider_name = provider_name.strip()
            if existing.name != normalized_provider_name:
                # `name` is provider-owned metadata. `friendly_name` remains the
                # separate administrator-owned display customization.
                existing.name = normalized_provider_name
        lat = sensor_obj.get("latitude")
        lon = sensor_obj.get("longitude")
        if lat is not None or lon is not None:
            set_device_location(
                session,
                existing,
                latitude=lat,
                longitude=lon,
            )
        if existing.timezone is None and existing.latitude is not None and existing.longitude is not None:
            tz = _lookup_timezone(existing.latitude, existing.longitude)
            if tz:
                existing.timezone = tz
        session.add(existing)
        session.flush()
        return existing

    payload = _api_get(base_url, sensor_index, DEVICE_FIELDS, api_key=api_key)
    sensor_obj = payload.get("sensor", {}) if isinstance(payload, dict) else {}
    coordinate_pair = validate_coordinate_pair(
        sensor_obj.get("latitude"), sensor_obj.get("longitude")
    )
    lat_val, lon_val = coordinate_pair if coordinate_pair is not None else (None, None)
    tz_guess = _lookup_timezone(lat_val, lon_val)
    if tz_guess is None and lat_val is not None and lon_val is not None:
        logger.info("Could not resolve timezone for PurpleAir device %s at (%s,%s)", sensor_index, lat_val, lon_val)
    device = models.Device(
        name=sensor_obj.get("name") or f"purpleair-{sensor_index}",
        external_id=str(sensor_index),
        external_api_id=external_api_id,
        timezone=tz_guess,
    )
    session.add(device)
    set_device_location(
        session,
        device,
        latitude=lat_val,
        longitude=lon_val,
    )
    return device


def _lookup_parameter_id(session, code: str) -> Optional[int]:
    param = session.scalars(select(models.Parameter).where(func.lower(models.Parameter.code) == code.lower())).one_or_none()
    return param.parameter_id if param else None


def _ensure_sensor(
    session,
    base_url: str,
    sensor_index: str,
    device: models.Device,
    code: str,
    api_key: Optional[str],
    agg_period_id: Optional[int],
    unit_id: Optional[int],
) -> models.Sensor:
    parameter_id = _lookup_parameter_id(session, code)

    provider_field = PURPLEAIR_SENSOR_FIELD_BY_PARAMETER[code]
    canonical_external_sensor_id = f"{sensor_index}:{provider_field}"
    existing_query = select(models.Sensor).where(
        models.Sensor.device_id == device.device_id,
        models.Sensor.external_sensor_id == canonical_external_sensor_id,
    )

    sensor = session.scalars(existing_query).one_or_none()
    if sensor:
        # PurpleAir owns these source semantics. Reconcile every run so older
        # one-minute labels and stale metadata cannot silently persist.
        if agg_period_id:
            sensor.aggregation_period_id = agg_period_id
        if unit_id and sensor.unit_id is None:
            sensor.unit_id = unit_id
        _apply_purpleair_measurement_metadata(sensor)
        return sensor

                                                                                             
    if SENSOR_FIELDS:
        _api_get(base_url, sensor_index, SENSOR_FIELDS, api_key=api_key)

    sensor = models.Sensor(
        device_id=device.device_id,
        parameter_id=parameter_id,
        external_sensor_id=canonical_external_sensor_id,
        aggregation_period_id=agg_period_id,
        unit_id=unit_id or (None if parameter_id is None else _lookup_unit_id(session, "ug_m3")),
    )
    _apply_purpleair_measurement_metadata(sensor)
    session.add(sensor)
    session.flush()
    return sensor


def _apply_purpleair_measurement_metadata(sensor: models.Sensor) -> None:
    """Apply the provider-documented semantics for average=0 PM history."""
    sensor.expected_frequency_seconds = PURPLEAIR_EXPECTED_FREQUENCY_SECONDS
    sensor.measurement_duration_seconds = PURPLEAIR_MEASUREMENT_DURATION_SECONDS
    sensor.source_aggregation_duration_seconds = (
        PURPLEAIR_SOURCE_AGGREGATION_DURATION_SECONDS
    )
    sensor.measurement_timestamp_semantics = PURPLEAIR_TIMESTAMP_SEMANTICS
    sensor.measurement_metadata_status = PURPLEAIR_METADATA_STATUS
    sensor.measurement_metadata_managed_by = PURPLEAIR_METADATA_MANAGER


def _store_measurements(
    session,
    base_url: str,
    sensor_index: str,
    sensor_map: dict[str, models.Sensor],
    api_key: Optional[str],
    max_lookback_hours: Optional[int] = None,
    *,
    usage: Optional[dict] = None,
) -> tuple[dict[str, dict[str, int]], dict[str, int], dict | None]:
    """Fetch missing measurements via the PurpleAir history endpoint and insert Measurement rows."""
    per_param = defaultdict(lambda: {"insert": 0, "update": 0, "skip": 0})
    overall = {"insert": 0, "update": 0, "skip": 0}
    qc_summary: dict = {}

    usage = usage if usage is not None else {}
    end_dt = _utcnow()
                                                                                       
    try:
        lookback_hours = int(max_lookback_hours) if max_lookback_hours is not None else 24
    except Exception:
        lookback_hours = 24

    end_ts = int(end_dt.timestamp())
    earliest_allowed_ts = int((end_dt - timedelta(hours=lookback_hours)).timestamp())

    latest_observed = _latest_observed_at_for_sensors(session, sensor_map.values())
    if latest_observed is None:
                                                                                               
        start_ts = earliest_allowed_ts
    else:
        start_ts = int(latest_observed.timestamp())

    if start_ts < earliest_allowed_ts:
        logger.info(
            "Clamping PurpleAir history start_timestamp for sensor_index=%s from %s to %s (max %sh lookback)",
            sensor_index,
            start_ts,
            earliest_allowed_ts,
            lookback_hours,
        )
        start_ts = earliest_allowed_ts
    if start_ts >= end_ts:
        logger.info(
            "Skipping PurpleAir history fetch for sensor_index=%s (start_timestamp=%s >= end_timestamp=%s)",
            sensor_index,
            start_ts,
            end_ts,
        )
        return per_param, overall, None

    usage.update({
        "history_requests": 1,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "fields": list(MEASUREMENT_FIELDS),
        "average": 0,
        "retries": 0,
    })
    logger.info("PurpleAir history request sensor_index=%s usage=%s", sensor_index, usage)
    payload = _api_get_history(base_url, sensor_index, MEASUREMENT_FIELDS, start_ts, end_ts, api_key=api_key)
    if not isinstance(payload, dict) or payload.get("error"):
        raise PurpleAirImporterError("PurpleAir history returned an invalid or error response")
    fields = payload.get("fields")
    data_rows = payload.get("data")
    if (
        not isinstance(fields, list)
        or not all(isinstance(field, str) for field in fields)
        or not isinstance(data_rows, list)
    ):
        raise PurpleAirImporterError("PurpleAir history requires fields and data arrays")
    # Current responses include time_stamp in fields; older captured responses
    # omit that name but still put its value first. Preserve both layouts.
    columns = fields if "time_stamp" in fields else ["time_stamp", *fields]
    if len(set(columns)) != len(columns) or not set(MEASUREMENT_FIELDS).issubset(columns):
        raise PurpleAirImporterError("PurpleAir history is missing or repeats required columns")
    field_positions = {field: idx for idx, field in enumerate(columns)}
    usage["rows_returned"] = len(data_rows)
    usage["missing_values"] = 0
    field_code_map = {"pm2.5_atm": "pm25", "pm10.0_atm": "pm10"}

    for row in data_rows:
        if not isinstance(row, (list, tuple)) or len(row) != len(columns):
            raise PurpleAirImporterError("PurpleAir history row does not match its columns")
        ts_val = row[field_positions["time_stamp"]]
        try:
            observed_at = datetime.fromtimestamp(int(ts_val), tz=timezone.utc)
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            raise PurpleAirImporterError("PurpleAir history row has an invalid timestamp") from exc
        for field_name, code in field_code_map.items():
            sensor = sensor_map.get(code)
            if not sensor:
                continue
            idx = field_positions.get(field_name)
            if idx is None or idx >= len(row):
                continue
            value = row[idx]
            if value is None:
                usage["missing_values"] += 1
                continue
            try:
                value = float(value)
            except (ValueError, TypeError) as exc:
                raise PurpleAirImporterError("PurpleAir history contains a nonnumeric measurement") from exc
            if not math.isfinite(value):
                raise PurpleAirImporterError("PurpleAir history contains a nonfinite measurement")
            m = models.Measurement(sensor_id=sensor.sensor_id, value=float(value), observed_at=observed_at)
                                                                                          
            device = getattr(sensor, "device", None)
            if device is None:
                device = session.scalars(
                    select(models.Device).where(models.Device.device_id == sensor.device_id)
                ).one_or_none()
            if upsert_measurement_with_policy_detailed:
                upsert_result = upsert_measurement_with_policy_detailed(
                    session,
                    m,
                    device=device,
                    sensor=sensor,
                )
                decision = upsert_result.action
                merge_qc_counts(qc_summary, upsert_result.qc)
                if decision == "insert":
                    per_param[code]["insert"] += 1
                    overall["insert"] += 1
                elif decision == "update":
                    per_param[code]["update"] += 1
                    overall["update"] += 1
                else:
                    per_param[code]["skip"] += 1
                    overall["skip"] += 1
            else:
                                                             
                existing = session.scalar(
                    select(models.Measurement.measurement_id).where(
                        models.Measurement.sensor_id == sensor.sensor_id,
                        models.Measurement.observed_at == observed_at,
                    )
                )
                if existing:
                    per_param[code]["skip"] += 1
                    overall["skip"] += 1
                    continue
                session.add(m)
                per_param[code]["insert"] += 1
                overall["insert"] += 1
    usage.update({
        "measurements_inserted": overall["insert"],
        "measurements_updated": overall["update"],
        "measurements_skipped": overall["skip"],
    })
    return per_param, overall, qc_summary.get("qc")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _recent(previous: Optional[datetime], now: datetime, seconds: int) -> bool:
    if previous is None:
        return False
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    # A future cache time must not prevent imports after a clock correction.
    return 0 <= (now - previous).total_seconds() < seconds


def _run_authorized_import(summary_json: Optional[str] = None) -> dict:
    """Entrypoint: ensure device/sensors exist and store latest PurpleAir readings for all PurpleAir devices."""
    with SessionLocal() as session:
        record, base_url, sensor_indices, api_key = _load_purpleair_config(session)
        logger.info("Starting PurpleAir import for %s devices", len(sensor_indices))

        import_summary = new_import_summary()
        if not sensor_indices:
            logger.warning("No PurpleAir devices are configured; no measurements requested")
            write_import_summary(import_summary, summary_json)
            return import_summary

        agg_period_id = _ensure_aggregation_period(session, code="2m", display_name="2 Minutes")
        ug_unit_id = _lookup_unit_id(session, "ug_m3")

        summaries: list[dict] = []

        for sensor_index in sensor_indices:
            existing_device = session.scalar(
                select(models.Device).where(
                    models.Device.external_api_id == record.external_api_id,
                    models.Device.external_id == sensor_index,
                ).with_for_update()
            )
            # Lock the configured device before reading poll state. PostgreSQL
            # serializes concurrent manual/scheduled imports of this device.
            if existing_device is None:
                continue  # Deleted since the target list was read.
            state = session.get(models.PurpleAirImportState, existing_device.device_id)
            if state is None:
                state = models.PurpleAirImportState(device_id=existing_device.device_id)
                session.add(state)
            now = _utcnow()
            if _recent(state.history_polled_at, now, PURPLEAIR_MINIMUM_POLL_SECONDS):
                summary = {
                    "sensor_index": sensor_index,
                    "device_id": existing_device.device_id,
                    "api_usage": {"metadata_requests": 0, "history_requests": 0, "retries": 0},
                    "skip_reason": "polled_within_two_minutes",
                }
                summaries.append(summary)
                logger.info("PurpleAir import skipped: %s", summary)
                session.commit()
                continue
            refresh_metadata = not _recent(
                state.metadata_refreshed_at, now, PURPLEAIR_METADATA_REFRESH_SECONDS
            )
            usage = {
                "metadata_requests": int(refresh_metadata),
                "history_requests": 0,
                "metadata_fields": list(DEVICE_FIELDS) if refresh_metadata else [],
                "retries": 0,
            }
            device = _ensure_device(
                session, base_url, sensor_index, record.external_api_id, api_key,
                refresh_metadata=refresh_metadata,
            )
            if refresh_metadata:
                state.metadata_refreshed_at = now
            existing_sensor_count = session.scalar(
                select(func.count(models.Sensor.sensor_id)).where(
                    models.Sensor.device_id == device.device_id
                )
            ) or 0
            sensors = {
                "pm25": _ensure_sensor(
                    session, base_url, sensor_index, device, "pm25", api_key, agg_period_id, ug_unit_id
                ),
                "pm10": _ensure_sensor(
                    session, base_url, sensor_index, device, "pm10", api_key, agg_period_id, ug_unit_id
                ),
            }
            current_sensor_count = session.scalar(
                select(func.count(models.Sensor.sensor_id)).where(
                    models.Sensor.device_id == device.device_id
                )
            ) or 0
            import_summary["devices_processed"] += 1
            import_summary["sensors_processed"] += len(sensors)
            import_summary["sensors_created"] += max(
                current_sensor_count - existing_sensor_count, 0
            )

                                                                                          
            max_lookback_hours: Optional[int] = None
            try:
                params = getattr(record, "params", None)
                if isinstance(params, dict):
                    v = params.get("max_lookback_hours")
                    if v is not None:
                        max_lookback_hours = int(v)
            except Exception:
                max_lookback_hours = None

            per_param, overall, qc_counts = _store_measurements(
                session, base_url, sensor_index, sensors, api_key, max_lookback_hours, usage=usage
            )
            if usage["history_requests"]:
                state.history_polled_at = now
            session.commit()

            import_summary["measurements_received"] += sum(overall.values())
            import_summary["measurements_inserted"] += overall.get("insert", 0)
            import_summary["measurements_updated"] += overall.get("update", 0)
            import_summary["measurements_skipped"] += overall.get("skip", 0)
            merge_qc_counts(import_summary, qc_counts)

                                                                                          
                                                                                 
            summary = {
                "per_parameter": {k: v for k, v in per_param.items()},
                "overall": overall,
                "sensor_index": sensor_index,
                "device_id": device.device_id,
                "api_usage": usage,
            }
            summaries.append(summary)
            logger.info(
                "PurpleAir import completed for sensor_index=%s device_id=%s summary=%s",
                sensor_index,
                device.device_id,
                summary,
            )

                                                                                              
            try:
                per_param_json = json.dumps({k: v for k, v in per_param.items()}, ensure_ascii=False)
                overall_json = json.dumps(overall, ensure_ascii=False)
            except Exception:
                per_param_json = str({k: v for k, v in per_param.items()})
                overall_json = str(overall)
            print(
                f"PurpleAir import ok: sensor_index={sensor_index} device_id={device.device_id} "
                f"per_parameter={per_param_json} overall={overall_json}"
            )

        import_summary["provider_results"] = summaries
        print("PurpleAir API usage: " + json.dumps(summaries, ensure_ascii=False))
        if summary_json:
            try:
                write_import_summary(import_summary, summary_json)
                logger.info("Wrote summary JSON to %s", summary_json)
            except Exception as exc:
                logger.error("Failed to write summary JSON to %s: %s", summary_json, exc)

        return import_summary


def run_import(summary_json: Optional[str] = None) -> dict:
    """Run only after the process context passes the paid-provider safety gate."""
    with SessionLocal() as safety_session:
        authorization = require_purpleair_import_authorization(safety_session)
    with paid_provider_request_scope(authorization):
        return _run_authorized_import(summary_json=summary_json)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PurpleAir importer")
    parser.add_argument("--summary-json", dest="summary_json", help="Write summary JSON to this path", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    discovery.load_plugins()
    run_import(summary_json=args.summary_json)


if __name__ == "__main__":
    main()
