from __future__ import annotations

import argparse
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from sqlalchemy import func, select

import models
from db import SessionLocal

try:
    from sources.openaq.openaq_upserts import upsert_measurement_with_policy
except Exception:                    
    upsert_measurement_with_policy = None

logger = logging.getLogger("airgradient_importer")

DEFAULT_BASE_URL = "https://api.airgradient.com/public/api/v1"


class AirGradientImporterError(Exception):
    """Raised for recoverable importer issues."""


class AirGradientRateLimit(AirGradientImporterError):
    """Raised when API returns 429."""


PARAM_MAP: Dict[str, Tuple[str, str]] = {
    "pm01": ("pm1", "ug_m3"),
    "pm01_corrected": ("pm1", "ug_m3"),
    "pm02": ("pm25", "ug_m3"),
    "pm02_corrected": ("pm25", "ug_m3"),
    "pm2.5": ("pm25", "ug_m3"),
    "pm25": ("pm25", "ug_m3"),
    "pm10": ("pm10", "ug_m3"),
    "pm10_corrected": ("pm10", "ug_m3"),
    "co2": ("co2", "ppm"),
    "rco2": ("co2", "ppm"),
    "rco2_corrected": ("co2", "ppm"),
    "tvoc": ("tvoc", "ppb"),
    "tvocindex": ("tvoc_index", "index"),
    "voc": ("tvoc", "ppb"),
    "nox": ("nox", "ppb"),
    "noxindex": ("nox_index", "index"),
    "temperature": ("temp", "c"),
    "temp": ("temp", "c"),
    "atmp": ("temp", "c"),
    "atmp_corrected": ("temp", "c"),
    "humidity": ("rh", "%"),
    "rhum": ("rh", "%"),
    "pressure": ("pressure", "hpa"),
}


def _emit_event(
    event_type: str,
    severity: str = "info",
    device_id: Optional[int] = None,
    sensor_id: Optional[int] = None,
    message: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    """Emit structured Event row and stdout line."""
    data = {
        "event_type": event_type,
        "source": "airgradient_importer",
        "severity": severity,
        "device_id": device_id,
        "sensor_id": sensor_id,
        "message": message,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        print("EVENT:" + json.dumps(data, ensure_ascii=False), flush=True)
    except Exception:
        pass
    try:
        from db import SessionLocal as _SessionLocal
        with _SessionLocal() as s:
            evt = models.Event(
                event_type=event_type,
                source="airgradient_importer",
                severity=severity,
                device_id=device_id,
                sensor_id=sensor_id,
                message=message,
                raw_snippet=json.dumps(payload)[:2000] if payload else None,
            )
            s.add(evt)
            s.commit()
    except Exception:
        pass


def _get_api_key(session) -> Optional[str]:
    try:
        row = session.scalars(
            select(models.ExternalAPI.api_key).where(func.lower(models.ExternalAPI.name) == "airgradient").limit(1)
        ).one_or_none()
        if row:
            return row
    except Exception:
        pass
    return os.getenv("AIRGRADIENT_API_KEY")


def _api_get(path: str, api_key: str, params: Optional[dict] = None, include_token: bool = True) -> Any:
    url = path if path.startswith("http") else f"{DEFAULT_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    query = params.copy() if params else {}
                                                                              
    if include_token:
        query.setdefault("token", api_key)
    try:
        resp = requests.get(url, params=query, timeout=30)
    except requests.RequestException as exc:
        raise AirGradientImporterError(f"Request error: {exc}")
    if resp.status_code == 429:
        raise AirGradientRateLimit("AirGradient rate limit reached")
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        snippet = (resp.text or "")[:200]
        raise AirGradientImporterError(f"HTTP {resp.status_code}: {snippet}") from exc
    try:
        return resp.json()
    except Exception as exc:
        raise AirGradientImporterError(f"Failed to parse JSON: {exc}")


def _parse_ts(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(float(val), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(val, str):
        try:
            s = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


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


def _lookup_unit_id(session, code_or_symbol: Optional[str]) -> Optional[int]:
    if not code_or_symbol:
        return None
    val = code_or_symbol.lower()
    unit = session.scalars(select(models.Unit).where(func.lower(models.Unit.code) == val)).one_or_none()
    if unit:
        return unit.unit_id
    unit = session.scalars(select(models.Unit).where(func.lower(models.Unit.symbol) == val)).one_or_none()
    return unit.unit_id if unit else None


def _lookup_param_id(session, code: Optional[str]) -> Optional[int]:
    if not code:
        return None
    param = session.scalars(select(models.Parameter).where(func.lower(models.Parameter.code) == code.lower())).one_or_none()
    return param.parameter_id if param else None


def _normalize_param(key: str) -> Tuple[str, Optional[str]]:
    k = (key or "").strip().lower()
    mapped = PARAM_MAP.get(k)
    if mapped:
        return mapped[0], mapped[1]
    return k, None


def _ensure_device(session, api_device: dict, external_api_id: Optional[int]) -> models.Device:
    ext_id = str(api_device.get("id") or api_device.get("deviceId") or api_device.get("device_id") or api_device.get("locationId") or "")
    if not ext_id:
        raise AirGradientImporterError("Device missing id")
    name = api_device.get("name") or api_device.get("displayName") or api_device.get("locationName") or f"AirGradient-{ext_id}"
    friendly_name = api_device.get("friendlyName") or api_device.get("customName")
    lat = api_device.get("latitude")
    lon = api_device.get("longitude")
    tz = api_device.get("timezone")
    try:
        lat = float(lat) if lat is not None else None
    except Exception:
        lat = None
    try:
        lon = float(lon) if lon is not None else None
    except Exception:
        lon = None

    existing = session.scalars(select(models.Device).where(models.Device.external_id == ext_id).limit(1)).first()
    if existing:
        changed = False
        for attr, val in (
            ("name", name),
            ("friendly_name", friendly_name),
            ("latitude", lat),
            ("longitude", lon),
            ("timezone", tz),
        ):
            if val is not None and getattr(existing, attr, None) != val:
                setattr(existing, attr, val)
                changed = True
        if external_api_id and getattr(existing, "external_api_id", None) is None:
            existing.external_api_id = external_api_id
            changed = True
        if changed:
            session.add(existing)
            session.flush()
        return existing

    device = models.Device(
        name=name,
        friendly_name=friendly_name,
        external_id=ext_id,
        external_api_id=external_api_id,
        latitude=lat,
        longitude=lon,
        timezone=tz,
        allow_updates=models.UpdatePolicy.INHERIT,
    )
    session.add(device)
    session.flush()
    return device


def _extract_measurements(raw: Any) -> List[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        if "measurements" in raw and isinstance(raw["measurements"], list):
            return raw["measurements"]
        if "results" in raw and isinstance(raw["results"], list):
            return raw["results"]
                                   
        return [raw]
    if isinstance(raw, list):
        return raw
    return []


def _store_measurements(
    session,
    device: models.Device,
    measurements: List[dict],
    aggregation_period_id: Optional[int],
    sensor_lookup: Optional[dict] = None,
) -> Tuple[dict, dict]:
    per_param = defaultdict(lambda: {"insert": 0, "update": 0, "skip": 0})
    overall = {"insert": 0, "update": 0, "skip": 0}
    sensor_cache: Dict[str, models.Sensor] = {}

    for m in measurements:
        observed_at = None
        for ts_key in ("timestamp", "time", "datetime", "createdAt", "created_at", "at"):
            observed_at = _parse_ts(m.get(ts_key))
            if observed_at:
                break
        if observed_at is None:
            observed_at = datetime.now(timezone.utc)

        for key, value in list(m.items()):
            if key in ("timestamp", "time", "datetime", "createdAt", "created_at", "at"):
                continue
            if key in ("locationId", "locationName", "locationType", "serialno", "model", "firmwareVersion", "datapoints", "latitude", "longitude"):
                continue
            if value is None:
                continue
            try:
                valf = float(value)
            except Exception:
                continue

            param_code, unit_code = _normalize_param(key)
            unit_id = _lookup_unit_id(session, unit_code)
            sensor = None
            if sensor_lookup:
                sensor = sensor_lookup.get(param_code.lower())
            if not sensor:
                                                                         
                continue

            measurement = models.Measurement(
                sensor_id=sensor.sensor_id,
                value=valf,
                observed_at=observed_at,
            )
            if upsert_measurement_with_policy:
                action = upsert_measurement_with_policy(session, measurement, device=device, sensor=sensor)
            else:
                                                       
                existing = session.scalar(
                    select(models.Measurement.measurement_id).where(
                        models.Measurement.sensor_id == sensor.sensor_id,
                        models.Measurement.observed_at == observed_at,
                    )
                )
                if existing:
                    action = "skip"
                else:
                    session.add(measurement)
                    action = "insert"

            per_param[param_code][action] += 1
            overall[action] = overall.get(action, 0) + 1

    return per_param, overall


def _load_airgradient_config(session) -> Tuple[Optional[int], str]:
    row = session.scalars(
        select(models.ExternalAPI).where(func.lower(models.ExternalAPI.name) == "airgradient")
    ).one_or_none()
    if not row:
        raise AirGradientImporterError("ExternalAPI configuration for AirGradient not found")
    base_url = row.base_url if row and row.base_url else DEFAULT_BASE_URL
                                                                                                  
    if base_url.rstrip("/").endswith("/public/api"):
        base_url = base_url.rstrip("/") + "/v1"
    api_key = _get_api_key(session)
    if not api_key:
        raise AirGradientImporterError("AirGradient API key not configured in external_api or AIRGRADIENT_API_KEY env")
    return row.external_api_id, base_url


def run_import(summary_json: Optional[str] = None, location_ids: Optional[List[int]] = None) -> dict:
    summary: dict = {
        "devices_processed": 0,
        "measurements": {"insert": 0, "update": 0, "skip": 0},
        "per_param": {},
        "errors": [],
    }
    with SessionLocal() as session:
        try:
            external_api_id, _base = _load_airgradient_config(session)
        except AirGradientImporterError as exc:
            _emit_event("airgradient_config_error", "error", message=str(exc))
            raise

        try:
            api_key = _get_api_key(session)
                                                                                 
            device_query = select(models.Device).where(models.Device.external_api_id == external_api_id)
            if location_ids:
                ids_as_str = [str(i) for i in location_ids]
                device_query = device_query.where(models.Device.external_id.in_(ids_as_str))
            devices = session.scalars(device_query).all()
            if not devices:
                _emit_event("airgradient_fetch_error", "warning", message="No AirGradient devices found in database")
                return summary

                                                                            
            param_rows = session.execute(select(models.Parameter.parameter_id, models.Parameter.code)).all()
            param_code_by_id = {pid: (code or "").lower() for pid, code in param_rows}

            for device in devices:
                if not device.external_id:
                    _emit_event("airgradient_device_error", "error", device_id=device.device_id, message="Device missing external_id; skipping")
                    summary["errors"].append("Device missing external_id")
                    continue

                sensor_lookup: dict[str, models.Sensor] = {}
                sensors = session.scalars(select(models.Sensor).where(models.Sensor.device_id == device.device_id)).all()
                for s in sensors:
                    code = None
                    if s.parameter_id and s.parameter_id in param_code_by_id:
                        code = param_code_by_id[s.parameter_id]
                    if not code and s.external_sensor_id and ":" in s.external_sensor_id:
                        code = s.external_sensor_id.split(":")[-1].lower()
                    if code:
                        sensor_lookup[code.lower()] = s

                try:
                                                                                                    
                    mraw = _api_get(f"{_base}/world/locations/{device.external_id}/measures/current", api_key, include_token=False)
                    measurements = _extract_measurements(mraw)
                except AirGradientRateLimit as exc:
                    _emit_event("airgradient_rate_limit", "warning", device_id=device.device_id, message=str(exc))
                    summary["errors"].append(str(exc))
                    continue
                except AirGradientImporterError as exc:
                    _emit_event("airgradient_measurement_error", "error", device_id=device.device_id, message=str(exc))
                    summary["errors"].append(str(exc))
                    continue

                summary["devices_processed"] += 1
                per_param, overall = _store_measurements(session, device, measurements, aggregation_period_id=None, sensor_lookup=sensor_lookup)
                session.commit()

                summary["measurements"]["insert"] += overall.get("insert", 0)
                summary["measurements"]["update"] += overall.get("update", 0)
                summary["measurements"]["skip"] += overall.get("skip", 0)
                                 
                for p, ctr in per_param.items():
                    existing = summary["per_param"].get(p, {"insert": 0, "update": 0, "skip": 0})
                    for k in ("insert", "update", "skip"):
                        existing[k] = existing.get(k, 0) + ctr.get(k, 0)
                    summary["per_param"][p] = existing

        except AirGradientRateLimit as exc:
            _emit_event("airgradient_rate_limit", "warning", message=str(exc))
            raise
        except AirGradientImporterError as exc:
            _emit_event("airgradient_fetch_error", "error", message=str(exc))
            summary["errors"].append(str(exc))
            return summary

    if summary_json:
        try:
            out_path = Path(summary_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
        except Exception as exc:
            logger.error("Failed to write summary JSON: %s", exc)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AirGradient importer")
    parser.add_argument("--summary-json", dest="summary_json", default=None, help="Write summary JSON to this path")
    parser.add_argument("--location-id", dest="location_ids", action="append", type=int, default=None, help="Limit import to specific AirGradient location id (can be provided multiple times)")
    args = parser.parse_args()
    try:
        summary = run_import(summary_json=args.summary_json, location_ids=args.location_ids)
        print(json.dumps(summary, indent=2))
    except AirGradientRateLimit as exc:
        print(f"AirGradient importer rate limited: {exc}")
        raise SystemExit(1)
    except AirGradientImporterError as exc:
        print(f"AirGradient importer failed: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
