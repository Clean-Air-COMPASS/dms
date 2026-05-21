from __future__ import annotations

import argparse
import json
import os
import re
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence

import requests
from sqlalchemy import select, func

import models
from db import SessionLocal
                                                                              
try:
    from sources.openaq.openaq_upserts import upsert_measurement_with_policy
except Exception:                                                           
    upsert_measurement_with_policy = None

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


class PurpleAirImporterError(Exception):
    """Raised for recoverable importer issues."""


def _extract_sensor_index(record: models.ExternalAPI) -> str:
    """Derive a sensor_index from the ExternalAPI record or environment variables."""

    params = getattr(record, "params", None)
    if params:
        try:
            parsed = json.loads(params) if isinstance(params, str) else params
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            val = parsed.get("sensor_index")
            if val is not None and str(val).strip():
                return str(val).strip()

    for candidate in (record.description, record.base_url):
        if not candidate:
            continue
        match = re.search(r"(?:sensor_index\s*[:=]\s*|/sensors/)(\d+)", candidate)
        if match:
            return match.group(1)
        loose = re.search(r"(\d+)", candidate)
        if loose:
            return loose.group(1)

    env_idx = os.getenv("PURPLEAIR_SENSOR_INDEX")
    if env_idx:
        return env_idx

    raise PurpleAirImporterError("sensor_index not found in external_api or environment")


def _load_purpleair_config(session) -> tuple[models.ExternalAPI, str, list[str], Optional[str]]:
    """Load PurpleAir config row and resolve sensor indexes from PurpleAir devices."""
    record = session.scalars(
        select(models.ExternalAPI).where(func.lower(models.ExternalAPI.name) == "purpleair")
    ).one_or_none()
    if not record:
        raise PurpleAirImporterError("ExternalAPI configuration for PurpleAir not found")

    base_url = record.base_url.rstrip("/") if record.base_url else DEFAULT_BASE_URL
                                                                             
    env_target = os.getenv("PURPLEAIR_TARGET_SENSOR_ID")
    if env_target:
        sensor_indices = [str(env_target).strip()]
    else:
                                                                           
        sensor_indices: Sequence[str] = session.scalars(
            select(models.Device.external_id)
            .where(models.Device.external_api_id == record.external_api_id)
            .where(models.Device.external_id.is_not(None))
        ).all()
    
                                                                               
    if not sensor_indices:
        sensor_indices = session.scalars(
            select(models.Device.external_id)
            .join(models.ExternalAPI, models.ExternalAPI.external_api_id == models.Device.external_api_id, isouter=True)
            .where(models.Device.external_id.is_not(None))
            .where(func.lower(models.ExternalAPI.name) == "purpleair")
        ).all()

    sensor_indices = [str(sid).strip() for sid in sensor_indices if sid is not None and str(sid).strip()]
                                                                            
    if not sensor_indices:
        try:
            fallback_idx = _extract_sensor_index(record)
            if fallback_idx:
                sensor_indices = [fallback_idx]
        except PurpleAirImporterError:
            sensor_indices = []

    if not sensor_indices:
        raise PurpleAirImporterError(
            "No PurpleAir devices with external_id found; add devices with sensor_index or set sensor_index in ExternalAPI params."
        )

    api_key = record.api_key or os.getenv("PURPLEAIR_API_KEY")
    logger.info("Resolved %s PurpleAir device(s) for import", len(sensor_indices))
    return record, base_url, list(sensor_indices), api_key


def _ensure_aggregation_period(session, code: str = "1m", display_name: str = "1 Minute") -> Optional[int]:
    ap = session.scalars(
        select(models.AggregationPeriod).where(func.lower(models.AggregationPeriod.code) == code.lower())
    ).one_or_none()
    if ap:
        return ap.aggregation_period_id
    ap = models.AggregationPeriod(code=code, display_name=display_name)
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
    url = f"{base_url.rstrip('/')}/{sensor_index}"
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    params = {"fields": ",".join(fields)}

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

    return resp.json()

def _api_get_history(
    base_url: str,
    sensor_index: str,
    fields: Iterable[str],
    start_timestamp: int,
    end_timestamp: int,
    api_key: Optional[str] = None,
) -> dict:
    """Call PurpleAir history endpoint for a sensor."""
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

    return resp.json()


def _ensure_device(
    session,
    base_url: str,
    sensor_index: str,
    external_api_id: Optional[int],
    api_key: Optional[str],
) -> models.Device:
    existing = session.scalars(select(models.Device).where(models.Device.external_id == str(sensor_index))).one_or_none()
    if existing:
                                             
        if external_api_id and existing.external_api_id is None:
            existing.external_api_id = external_api_id
                                                         
        payload = _api_get(base_url, sensor_index, DEVICE_FIELDS, api_key=api_key)
        sensor_obj = payload.get("sensor", {}) if isinstance(payload, dict) else {}
        lat = sensor_obj.get("latitude")
        lon = sensor_obj.get("longitude")
        if lat is not None and lon is not None:
            try:
                existing.latitude = float(lat)
                existing.longitude = float(lon)
            except Exception:
                pass
        if existing.timezone is None and existing.latitude is not None and existing.longitude is not None:
            tz = _lookup_timezone(existing.latitude, existing.longitude)
            if tz:
                existing.timezone = tz
        session.add(existing)
        session.flush()
        return existing

    payload = _api_get(base_url, sensor_index, DEVICE_FIELDS, api_key=api_key)
    sensor_obj = payload.get("sensor", {}) if isinstance(payload, dict) else {}
    lat_val = sensor_obj.get("latitude")
    lon_val = sensor_obj.get("longitude")
    try:
        lat_val = float(lat_val) if lat_val is not None else None
    except Exception:
        lat_val = None
    try:
        lon_val = float(lon_val) if lon_val is not None else None
    except Exception:
        lon_val = None
    tz_guess = _lookup_timezone(lat_val, lon_val)
    if tz_guess is None and lat_val is not None and lon_val is not None:
        logger.info("Could not resolve timezone for PurpleAir device %s at (%s,%s)", sensor_index, lat_val, lon_val)
    device = models.Device(
        name=sensor_obj.get("name") or f"purpleair-{sensor_index}",
        external_id=str(sensor_index),
        external_api_id=external_api_id,
        latitude=lat_val,
        longitude=lon_val,
        timezone=tz_guess,
    )
    session.add(device)
    session.flush()
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

    if parameter_id:
        existing_query = select(models.Sensor).where(
            models.Sensor.device_id == device.device_id,
            models.Sensor.parameter_id == parameter_id,
        )
    else:
        existing_query = select(models.Sensor).where(
            models.Sensor.device_id == device.device_id,
            models.Sensor.external_sensor_id == f"{sensor_index}-{code}",
        )

    sensor = session.scalars(existing_query).one_or_none()
    if sensor:
        if agg_period_id and sensor.aggregation_period_id is None:
            sensor.aggregation_period_id = agg_period_id
        if unit_id and sensor.unit_id is None:
            sensor.unit_id = unit_id
        return sensor

                                                                                             
    if SENSOR_FIELDS:
        _api_get(base_url, sensor_index, SENSOR_FIELDS, api_key=api_key)

    sensor = models.Sensor(
        device_id=device.device_id,
        parameter_id=parameter_id,
        external_sensor_id=f"{sensor_index}-{code}",
        aggregation_period_id=agg_period_id,
        unit_id=unit_id or (None if parameter_id is None else _lookup_unit_id(session, "ug_m3")),
    )
    session.add(sensor)
    session.flush()
    return sensor


def _store_measurements(
    session,
    base_url: str,
    sensor_index: str,
    sensor_map: dict[str, models.Sensor],
    api_key: Optional[str],
    max_lookback_hours: Optional[int] = None,
) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Fetch missing measurements via the PurpleAir history endpoint and insert Measurement rows."""
    per_param = defaultdict(lambda: {"insert": 0, "update": 0, "skip": 0})
    overall = {"insert": 0, "update": 0, "skip": 0}

    end_dt = datetime.now(timezone.utc)
                                                                                       
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
        return per_param, overall

    payload = _api_get_history(base_url, sensor_index, MEASUREMENT_FIELDS, start_ts, end_ts, api_key=api_key)
    if not isinstance(payload, dict):
        return per_param, overall

    fields = payload.get("fields") or []
    data_rows = payload.get("data") or []
    if not data_rows:
        logger.info(
            "No new PurpleAir history data for sensor_index=%s in window %s-%s", sensor_index, start_ts, end_ts
        )
        return per_param, overall

                                                                                               
    field_positions = {field: idx + 1 for idx, field in enumerate(fields)}
    field_code_map = {"pm2.5_atm": "pm25", "pm10.0_atm": "pm10"}

    for row in data_rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        ts_val = row[0]
        try:
            observed_at = datetime.fromtimestamp(int(ts_val), tz=timezone.utc)
        except Exception:
            continue
        for field_name, code in field_code_map.items():
            sensor = sensor_map.get(code)
            if not sensor:
                continue
            idx = field_positions.get(field_name)
            if idx is None or idx >= len(row):
                continue
            value = row[idx]
            if value is None:
                continue
            try:
                value = float(value)
            except Exception:
                continue
            m = models.Measurement(sensor_id=sensor.sensor_id, value=float(value), observed_at=observed_at)
                                                                                          
            device = getattr(sensor, "device", None)
            if device is None:
                device = session.scalars(
                    select(models.Device).where(models.Device.device_id == sensor.device_id)
                ).one_or_none()
            if upsert_measurement_with_policy:
                decision = upsert_measurement_with_policy(session, m, device=device, sensor=sensor)
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
    return per_param, overall

def run_import(summary_json: Optional[str] = None) -> dict:
    """Entrypoint: ensure device/sensors exist and store latest PurpleAir readings for all PurpleAir devices."""
    with SessionLocal() as session:
        record, base_url, sensor_indices, api_key = _load_purpleair_config(session)
        logger.info("Starting PurpleAir import for %s devices", len(sensor_indices))

        agg_period_id = _ensure_aggregation_period(session, code="1m", display_name="1 Minute")
        ug_unit_id = _lookup_unit_id(session, "ug_m3")

        summaries: list[dict] = []
        overall_totals = {"insert": 0, "update": 0, "skip": 0}

        for sensor_index in sensor_indices:
            device = _ensure_device(session, base_url, sensor_index, record.external_api_id, api_key)
            sensors = {
                "pm25": _ensure_sensor(
                    session, base_url, sensor_index, device, "pm25", api_key, agg_period_id, ug_unit_id
                ),
                "pm10": _ensure_sensor(
                    session, base_url, sensor_index, device, "pm10", api_key, agg_period_id, ug_unit_id
                ),
            }

                                                                                          
            max_lookback_hours: Optional[int] = None
            try:
                params = getattr(record, "params", None)
                if isinstance(params, dict):
                    v = params.get("max_lookback_hours")
                    if v is not None:
                        max_lookback_hours = int(v)
            except Exception:
                max_lookback_hours = None

            per_param, overall = _store_measurements(
                session, base_url, sensor_index, sensors, api_key, max_lookback_hours
            )
            session.commit()

            overall_totals["insert"] += overall.get("insert", 0)
            overall_totals["update"] += overall.get("update", 0)
            overall_totals["skip"] += overall.get("skip", 0)

                                                                                          
                                                                                 
            summary = {
                "per_parameter": {k: v for k, v in per_param.items()},
                "overall": overall,
                "sensor_index": sensor_index,
                "device_id": device.device_id,
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

        combined_summary = {"results": summaries, "overall_totals": overall_totals}
        if summary_json:
            try:
                out_path = Path(summary_json)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(combined_summary, f, indent=2)
                logger.info("Wrote summary JSON to %s", summary_json)
            except Exception as exc:
                logger.error("Failed to write summary JSON to %s: %s", summary_json, exc)

        return combined_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PurpleAir importer")
    parser.add_argument("--summary-json", dest="summary_json", help="Write summary JSON to this path", default=None)
    args = parser.parse_args()
    run_import(summary_json=args.summary_json)


if __name__ == "__main__":
    main()
