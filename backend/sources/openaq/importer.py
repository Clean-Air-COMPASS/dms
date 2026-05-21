"""OpenAQ import orchestrator.

Provides focused dev path (single sensor) and bulk import paths.
Uses Pydantic schemas for response validation when available.
"""

from __future__ import annotations

import os
from typing import List, Union, Optional
from collections import Counter, defaultdict
import argparse
import json
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import sys

from sqlalchemy import select, text, func

from db import SessionLocal
import models
from qaqc import discovery
from .openaq_client import get_api_client, fetch_json
from .openaq_schemas import LocationLatestResponse, SensorModel, SensorResponse, OpenAQMeasurementsResponse
from pydantic import TypeAdapter
from .openaq_upserts import (
    normalize_and_upsert_from_parameter_latest,
    _upsert_device_for_sensor,
    _upsert_sensor_for_device,
    _upsert_device_for_external_location,
    upsert_measurement_with_policy,
    _canonical_unit_id,
)

OPENAQ_LOCATIONS_URL = "https://api.openaq.org/v3/locations"
OPENAQ_SENSORS_URL = "https://api.openaq.org/v3/sensors"
OPENAQ_MEASUREMENTS_URL = "https://api.openaq.org/v3/measurements"

                                                                          
DEFAULT_OUT_DIR = (Path(__file__).resolve().parents[3] / "tmp")


def _iso_duration_to_hhmmss(v: Optional[str]) -> Optional[str]:
    """Convert ISO-8601 duration like 'PT1H' or 'PT15M' to 'HH:MM:SS'.

    Returns None if parsing fails or the input is falsy.
    """
    if not v or not isinstance(v, str):
        return None
    s = v.strip().upper()
                         
    if ":" in s and all(part.isdigit() for part in s.split(":") if part):
        parts = s.split(":")
        if len(parts) == 3 and all(len(p) in (1, 2) for p in parts):
                                  
            h, m, sec = (p.zfill(2) for p in parts)
            return f"{h}:{m}:{sec}"
        return None
                                                           
    if not s.startswith("PT"):
        return None
    s2 = s[2:]
    hours = 0
    minutes = 0
    seconds = 0
    num = ""
    for ch in s2:
        if ch.isdigit():
            num += ch
            continue
        if ch == "H":
            hours = int(num or "0")
            num = ""
        elif ch == "M":
            minutes = int(num or "0")
            num = ""
        elif ch == "S":
            seconds = int(num or "0")
            num = ""
        else:
                           
            return None
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _lookup_aggregation_period_id_by_interval(session, hhmmss: Optional[str]) -> Optional[int]:
    if not hhmmss:
        return None
    try:
        return session.scalar(
            select(models.AggregationPeriod.aggregation_period_id).where(
                models.AggregationPeriod.expected_interval == hhmmss
            ).limit(1)
        )
    except Exception:
        return None


def _get_api_key_for_external_api(name: str) -> Optional[str]:
    """Return the stored API key for an ExternalAPI by name (case-insensitive).

    Returns None if no row or no api_key present.
    """
    try:
        with SessionLocal() as session:
            row = session.scalars(
                select(models.ExternalAPI.api_key).where(func.lower(models.ExternalAPI.name) == (name or "").lower()).limit(1)
            ).one_or_none()
            return row
    except Exception:
        return None


def _get_openaq_external_api_id(session) -> Optional[int]:
    """Resolve the external_api_id for OpenAQ (case-insensitive)."""
    try:
        return session.scalar(
            select(models.ExternalAPI.external_api_id).where(func.lower(models.ExternalAPI.name) == "openaq").limit(1)
        )
    except Exception:
        return None


def emit_event(event_type: str, severity: str = "warning", sensor_id: str | None = None, endpoint: str | None = None, params: dict | None = None, message: str | None = None, raw_snippet: str | None = None) -> None:
    """Emit a structured event to stdout for later ingestion into an events table.

    Output is a single line prefixed with `EVENT:` followed by JSON. This keeps
    logs machine-parseable while remaining human-readable.
    """
    try:
        payload = {
            "event_type": event_type,
            "source": "openaq_importer",
            "severity": severity,
            "sensor_id": sensor_id,
            "endpoint": endpoint,
            "params": params,
            "message": message,
            "raw_snippet": raw_snippet,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print("EVENT:" + json.dumps(payload, ensure_ascii=False), flush=True)
                                                   
        try:
            from db import SessionLocal as _SessionLocal
            import models as _models
            with _SessionLocal() as _s:
                                                                                          
                sensor_fk = None
                device_fk = None
                if sensor_id:
                    try:
                        _sensor = _s.scalars(select(_models.Sensor).where(_models.Sensor.external_sensor_id == str(sensor_id))).one_or_none()
                        if _sensor:
                            sensor_fk = _sensor.sensor_id
                            device_fk = _sensor.device_id
                    except Exception:
                        pass
                evt = _models.Event(
                    event_type=event_type,
                    source="openaq_importer",
                    severity=severity,
                    device_id=device_fk,
                    sensor_id=sensor_fk,
                    external_sensor_id=str(sensor_id) if sensor_id else None,
                    endpoint=endpoint,
                    params=params,
                    message=message,
                    raw_snippet=raw_snippet,
                )
                _s.add(evt)
                _s.commit()
        except Exception:
                                                                      
            pass
    except Exception:
                                                       
        try:
            print(f"EVENT:{{'event_type': '{event_type}', 'message': 'failed to emit structured event'}}", flush=True)
        except Exception:
            pass


def _sanitize_unit_code(raw: str) -> str:
    s = (raw or "").strip().lower()
                                              
    s = s.replace("µ", "u").replace("μ", "u")
    s = s.replace("/", "_").replace("\\", "_")
    s = s.replace("³", "3").replace("^3", "3").replace("^2", "2")
    s = s.replace(" per ", "_").replace(" ", "_")
                         
    import re
    s = re.sub(r"[^a-z0-9_]", "", s)
    if not s:
        s = "unit"
    return s[:32]


def sync_catalogs_from_sensors() -> None:
    """Ensure Unit and Parameter catalogs contain entries referenced by Sensor records.

    - For each Sensor.unit, ensure a Unit row exists (by code or symbol); create if missing.
    - For each Sensor.parameter, ensure a Parameter row exists; create with default_unit_id from the sensor's unit.
    - Backfill Sensor.parameter_id and Measurement.parameter_id for the newly inserted parameters.
    """
                                                                          
    if not hasattr(models.Sensor, 'unit') or not hasattr(models.Sensor, 'parameter'):
        print("Catalog sync skipped: legacy Sensor.unit/parameter columns not available after migration.")
        return
    created_units = 0
    created_params = 0
    with SessionLocal() as session:
                                              
        unit_rows = session.execute(select(models.Unit.unit_id, models.Unit.code, models.Unit.symbol)).all()
        code_to_unitid = {code: uid for (uid, code, _sym) in unit_rows}
        symbol_to_unitid = {sym: uid for (uid, _code, sym) in unit_rows}

                             
        existing_params = set(session.scalars(select(models.Parameter.code)).all())

                         
        sensors = session.scalars(select(models.Sensor)).all()
        for s in sensors:
            raw_unit = (s.unit or "").strip()
            unit_id = None
            if raw_unit:
                unit_id = code_to_unitid.get(raw_unit) or symbol_to_unitid.get(raw_unit)
                if unit_id is None:
                                       
                    code = _sanitize_unit_code(raw_unit)
                                          
                    base_code = code
                    i = 1
                    while code in code_to_unitid and symbol_to_unitid.get(raw_unit) is None:
                        i += 1
                        code = f"{base_code}_{i}"[:32]
                    new_u = models.Unit(code=code, symbol=raw_unit, name=raw_unit)
                    session.add(new_u)
                    session.flush()
                    unit_id = new_u.unit_id
                    code_to_unitid[code] = unit_id
                    symbol_to_unitid[raw_unit] = unit_id
                    created_units += 1

                                     
            pcode = (s.parameter or "").strip().lower()
            if not pcode:
                continue
            if pcode not in existing_params:
                                                                                                  
                if unit_id is None:
                    continue
                disp = pcode.upper()
                new_p = models.Parameter(code=pcode, display_name=disp, default_unit_id=unit_id)
                session.add(new_p)
                session.flush()
                existing_params.add(pcode)
                created_params += 1

        session.commit()

                                                                                  
        session.execute(text(
            """
            UPDATE sensor AS s
            SET parameter_id = p.parameter_id
            FROM parameter AS p
            WHERE s.parameter_id IS NULL
              AND s.parameter IS NOT NULL
              AND lower(s.parameter) = p.code
            """
        ))
        session.execute(text(
            """
            UPDATE measurement AS m
            SET parameter_id = p.parameter_id
            FROM parameter AS p
            WHERE m.parameter_id IS NULL
              AND m.parameter IS NOT NULL
              AND lower(m.parameter) = p.code
            """
        ))
        session.commit()

    print(f"Catalog sync complete: created {created_units} unit(s), {created_params} parameter(s).")


def import_single_sensor(sensor_id: str) -> None:
    """Fetch a single sensor by id and insert its latest PM2.5 measurement if present."""

    api_key = _get_api_key_for_external_api("OpenAQ") or os.getenv("OPENAQ_API_KEY")
    headers = {"X-API-Key": api_key} if api_key else {}
    url = f"{OPENAQ_SENSORS_URL}/{sensor_id}"

    with get_api_client("OpenAQ") as client, SessionLocal() as session:
                                                                          
        try:
            known_params = set(session.scalars(select(models.Parameter.code)).all())
            param_map = dict(session.execute(select(models.Parameter.code, models.Parameter.parameter_id)).all())
                                               
            unit_code_map = dict(session.execute(select(models.Unit.code, models.Unit.unit_id)).all())
            unit_symbol_map = dict(session.execute(select(models.Unit.symbol, models.Unit.unit_id)).all())
                                           
            param_default_unit = dict(session.execute(select(models.Parameter.code, models.Parameter.default_unit_id)).all())
            unit_id_code_map = {uid: code for code, uid in unit_code_map.items()}
        except Exception:
            known_params = set()
            param_map = {}
            unit_code_map = {}
            unit_symbol_map = {}
            param_default_unit = {}
            unit_id_code_map = {}
        raw = fetch_json(client, url, headers=headers)
        if not raw:
            print(f"Failed to fetch sensor {sensor_id}")
            return

        parsed = None
        try:
            parsed = TypeAdapter(Union[SensorResponse, SensorModel]).validate_python(raw)
        except Exception:
            parsed = None

        sensor_obj = None
        if parsed and hasattr(parsed, "results"):
            sensor_obj = parsed.results[0] if parsed.results else None
        elif isinstance(parsed, SensorModel):
            sensor_obj = parsed
        elif isinstance(raw, dict) and raw.get("results"):
            lst = raw.get("results")
            if lst:
                sensor_obj = lst[0]
        elif isinstance(raw, dict):
            sensor_obj = raw

        if not sensor_obj:
            print(f"No sensor object found for id {sensor_id}")
            return

        if isinstance(sensor_obj, SensorModel):
            param = sensor_obj.parameter or None
            param_name = (param.name or str(param.id or "")).lower() if param else ""
            unit = param.units if param and param.units else ""
            latest = sensor_obj.latest or None
            lv = latest.value if latest else None
        else:
            param = sensor_obj.get("parameter") or {}
            param_name = (param.get("name") or str(param.get("id") or "")).lower()
            unit = param.get("units") or ""
            latest = sensor_obj.get("latest") or {}
            lv = latest.get("value")

                                                        
        if param_name:
            pn = (param_name or "").lower()
            param_name = pn if pn in known_params else pn
        pid = param_map.get(param_name) if param_name else None

        value = None
        if lv is not None:
            try:
                value = float(lv)
            except Exception:
                value = None

        loc_ext = None
        if isinstance(sensor_obj, SensorModel):
            if sensor_obj.locationId:
                loc_ext = str(sensor_obj.locationId)
            elif sensor_obj.locationsId and len(sensor_obj.locationsId) > 0:
                loc_ext = str(sensor_obj.locationsId[0])
        else:
            if sensor_obj.get("locationId"):
                loc_ext = str(sensor_obj.get("locationId"))
            elif sensor_obj.get("locationsId"):
                v = sensor_obj.get("locationsId")
                if isinstance(v, (list, tuple)) and v:
                    loc_ext = str(v[0])
                else:
                    loc_ext = str(v)

        device = None
        if loc_ext:
            try:
                device = session.scalars(select(models.Device).where(models.Device.external_id == str(loc_ext))).one_or_none()
            except Exception:
                device = None
        if not device:
                                                                                                              
            if loc_ext:
                                                                                                         
                device = _upsert_device_for_external_location(session, str(loc_ext), name=None, latitude=None, longitude=None, timezone=None)
            else:
                device = _upsert_device_for_sensor(session, sensor_obj, sensor_id, db_loc=None)

        sensor = None
                         
        uid = None
        if unit:
            uid = unit_code_map.get(unit) or unit_symbol_map.get(unit)
                                                      
        canonical_uid = _canonical_unit_id(param_name or "", param_default_unit, unit_code_map, unit_symbol_map)
        uid = canonical_uid or uid

                                                                                    
        agg_pid: Optional[int] = None
        try:
            exp = None
            if isinstance(sensor_obj, SensorModel):
                cov = getattr(sensor_obj, "coverage", None)
                exp = getattr(cov, "expectedInterval", None) if cov is not None else None
            elif isinstance(sensor_obj, dict):
                cov = sensor_obj.get("coverage") or {}
                exp = cov.get("expectedInterval")
            hhmmss = _iso_duration_to_hhmmss(exp) if exp else None
            agg_pid = _lookup_aggregation_period_id_by_interval(session, hhmmss) if hhmmss else None
        except Exception:
            agg_pid = None

        if device:
            sensor = _upsert_sensor_for_device(
                session,
                device,
                param_name,
                str(sensor_id),
                parameter_id=pid,
                unit_id=uid,
                aggregation_period_id=agg_pid,
                unit_id_code_map=unit_id_code_map,
                convert_unit=True,
            )

        if value is None:
            value = 0.0

        observed_at = None
        if isinstance(latest, dict):
            observed_at = (latest.get("datetime") or {}).get("utc")
        else:
            observed_at = (
                latest.datetime.utc
                if latest and latest.datetime
                else (latest.date.utc if latest and latest.date else None)
            ) if latest else None

        openaq_id = (
            str(sensor_obj.id)
            if isinstance(sensor_obj, SensorModel) and sensor_obj.id is not None
            else str(sensor_obj.get("id") or "")
        )

                                                                               
        if device and observed_at:
            try:
                from .openaq_upserts import _update_device_location
                _update_device_location(session, device, getattr(device, "latitude", None), getattr(device, "longitude", None), effective_from=observed_at)
            except Exception:
                pass

                                                              
        norm_items = [
            {
                "location": getattr(device, "name", None) if device else None,
                "parameter": param_name,
                "value": value,
                "unit": unit,
                "datetime": {"utc": observed_at},
                "coordinates": {
                    "latitude": getattr(device, "latitude", None) if device else None,
                    "longitude": getattr(device, "longitude", None) if device else None,
                },
                "id": openaq_id,
                "locationId": loc_ext,
                "sensorId": str(sensor_id),
            }
        ]
        measurements = normalize_and_upsert_from_parameter_latest(
            norm_items,
            parameter_name=param_name or "",
            param_map=param_map,
            unit_code_map=unit_code_map,
            unit_symbol_map=unit_symbol_map,
            param_default_unit=param_default_unit,
            unit_id_code_map=unit_id_code_map,
        )
        if measurements:
            m = measurements[0]
            if sensor:
                m.sensor_id = sensor.sensor_id
            action = upsert_measurement_with_policy(session, m, device=device, sensor=sensor)
            session.commit()
            verb_map = {"insert": "Inserted", "update": "Updated", "skip": "Skipped"}
            print(f"{verb_map.get(action, action)} 1 measurement for sensor {sensor_id}")
        else:
            session.commit()
            print(f"Skipped measurement for sensor {sensor_id}: no numeric value")


def import_measurements_from_locations(
    limit_per_location: int = 100,
    summary_json: Optional[str] = None,
    summary_csv: Optional[str] = None,
) -> dict:
    """Import measurements for OpenAQ devices using location-scoped endpoints."""

    api_key = _get_api_key_for_external_api("OpenAQ") or os.getenv("OPENAQ_API_KEY")
    headers = {"X-API-Key": api_key} if api_key else {}

    with SessionLocal() as session:
        openaq_api_id = _get_openaq_external_api_id(session)
                                                                      
        stmt = (
            select(models.Device)
            .join(models.ExternalAPI, models.ExternalAPI.external_api_id == models.Device.external_api_id, isouter=True)
            .where(models.Device.external_id != None)              
        )
        if openaq_api_id:
            stmt = stmt.where(models.Device.external_api_id == openaq_api_id)
        else:
            stmt = stmt.where(func.lower(models.ExternalAPI.name) == "openaq")
        stmt = stmt.order_by(models.Device.device_id)
        devices_with_ext = session.scalars(stmt).all()

    if not devices_with_ext:
        print("No OpenAQ devices with external_id found in DB; skipping measurement import.")
        return

    batch_size = 100
    inserted_total = 0
    processed_locations = 0

    with get_api_client("OpenAQ") as client, SessionLocal() as session:
                                                                                   
        try:
            known_params = set(session.scalars(select(models.Parameter.code)).all())
            param_rows = session.execute(select(models.Parameter.code, models.Parameter.parameter_id, models.Parameter.default_unit_id)).all()
            param_map = {code: pid for (code, pid, _du) in param_rows}
            param_default_unit = {code: du for (code, _pid, du) in param_rows}
            unit_code_map = dict(session.execute(select(models.Unit.code, models.Unit.unit_id)).all())
            unit_symbol_map = dict(session.execute(select(models.Unit.symbol, models.Unit.unit_id)).all())
            unit_id_code_map = {uid: code for code, uid in unit_code_map.items()}
        except Exception:
            known_params = set()
            param_map = {}
            param_default_unit = {}
            unit_code_map = {}
            unit_symbol_map = {}
            unit_id_code_map = {}
                                             
        action_totals = Counter()
        per_param_actions: dict[str, Counter] = defaultdict(Counter)
        for dev in devices_with_ext:

            ext_id = getattr(dev, "external_id", None)
            if not ext_id:
                continue

                                                                             

            url = f"{OPENAQ_LOCATIONS_URL}/{ext_id}/latest"
            data = fetch_json(client, url, headers=headers, schema=LocationLatestResponse)
            if not data:
                print(f"Warning: failed to fetch data for location {ext_id}")
                continue

            sensors_url = f"{OPENAQ_LOCATIONS_URL}/{ext_id}/sensors"
            sdata = fetch_json(client, sensors_url, headers=headers, schema=SensorResponse)
            sresults = sdata.results if hasattr(sdata, "results") else (sdata.get("results", []) if sdata else [])

            items: List[dict] = []

            if sresults:
                device = session.scalars(select(models.Device).where(models.Device.external_id == str(ext_id))).one_or_none()
                if device and openaq_api_id and getattr(device, "external_api_id", None) != openaq_api_id:
                    print(f"Skipping non-OpenAQ device {ext_id}")
                    continue
                if not device:
                                                                        
                                                                                                    
                    tz = None
                    try:
                        if isinstance(data, dict):
                            if data.get("results") and isinstance(data.get("results"), (list, tuple)) and data.get("results"):
                                first = data.get("results")[0]
                                if isinstance(first, dict):
                                    tz = first.get("timezone") or data.get("timezone")
                        else:
                            tz = getattr(data, "timezone", None)
                    except Exception:
                        tz = None
                    device = _upsert_device_for_external_location(session, str(ext_id), name=None, latitude=None, longitude=None, timezone=tz)

                for s in sresults:
                    if isinstance(s, SensorModel):
                        s_ext_id = str(s.id or s.sensorId or "")
                        param_obj = s.parameter or None
                        param_name = (
                            param_obj.name if param_obj and param_obj.name else str(param_obj.id if param_obj and param_obj.id else "")
                        ).lower() if param_obj else ""
                        unit = param_obj.units if param_obj and param_obj.units else ""
                        latest = s.latest
                        lv = latest.value if latest else None
                    else:
                        s_ext_id = str(s.get("id") or s.get("sensorId") or "")
                        param_obj = s.get("parameter") or {}
                        param_name = (param_obj.get("name") or param_obj.get("displayName") or str(param_obj.get("id"))).lower()
                        unit = param_obj.get("units") or ""
                        latest = s.get("latest") or {}
                        lv = latest.get("value")

                                                          
                    if param_name:
                        pn = (param_name or "").lower()
                        param_name = pn if pn in known_params else pn

                    pid = param_map.get(param_name) if param_name else None
                    uid = unit_code_map.get(unit) or unit_symbol_map.get(unit) if unit else None
                    canonical_uid = _canonical_unit_id(param_name or "", param_default_unit, unit_code_map, unit_symbol_map)
                    uid = canonical_uid or uid
                                                                                 
                    agg_pid: Optional[int] = None
                    try:
                        details = fetch_json(client, f"{OPENAQ_SENSORS_URL}/{s_ext_id}", headers=headers)
                        exp = None
                        if isinstance(details, dict):
                            if details.get("results") and isinstance(details.get("results"), (list, tuple)) and details["results"]:
                                first = details["results"][0]
                                cov = first.get("coverage") if isinstance(first, dict) else None
                                exp = (cov or {}).get("expectedInterval") if isinstance(cov, dict) else None
                            else:
                                cov = details.get("coverage") if isinstance(details, dict) else None
                                exp = (cov or {}).get("expectedInterval") if isinstance(cov, dict) else None
                        hhmmss = _iso_duration_to_hhmmss(exp) if exp else None
                        agg_pid = _lookup_aggregation_period_id_by_interval(session, hhmmss) if hhmmss else None
                    except Exception:
                        agg_pid = None
                    sensor = _upsert_sensor_for_device(
                        session,
                        device,
                        param_name,
                        s_ext_id,
                        parameter_id=pid,
                        unit_id=uid,
                        aggregation_period_id=agg_pid,
                        unit_id_code_map=unit_id_code_map,
                        convert_unit=True,
                    ) if device else None

                    latest_val = None
                    if lv is not None:
                        try:
                            latest_val = float(lv)
                        except Exception:
                            latest_val = None

                    if latest_val is not None:
                        if isinstance(latest, dict):
                            utc = (latest.get("datetime") or latest.get("date") or {}).get("utc")
                        else:
                            utc = (
                                latest.datetime.utc
                                if latest and latest.datetime
                                else (latest.date.utc if latest and latest.date else None)
                            )

                        raw_sensor = s.model_dump() if hasattr(s, "model_dump") else s
                        items.append(
                            {
                                "location": dev.name if dev else None,
                                "parameter": (param_name or "").lower(),
                                "value": latest_val,
                                "unit": unit,
                                "datetime": {"utc": utc},
                                "coordinates": {
                                    "latitude": getattr(dev, "latitude", None),
                                    "longitude": getattr(dev, "longitude", None),
                                },
                                "id": s_ext_id,
                                "locationId": ext_id,
                                "raw": {"sensor": raw_sensor},
                            }
                        )

                                                                                                              
                    try:
                                                                                                          
                        last_dt_val = None
                        if sensor:
                            last_dt_val = session.scalar(
                                select(func.max(models.Measurement.observed_at)).where(models.Measurement.sensor_id == sensor.sensor_id)
                            )
                                                                  
                        last_dt_dt: datetime | None = None
                        if isinstance(last_dt_val, datetime):
                            last_dt_dt = last_dt_val
                        elif isinstance(last_dt_val, str):
                            try:
                                s = last_dt_val.replace('Z', '+00:00')
                                last_dt_dt = datetime.fromisoformat(s)
                            except Exception:
                                last_dt_dt = None
                        if last_dt_dt is not None and last_dt_dt.tzinfo is None:
                            last_dt_dt = last_dt_dt.replace(tzinfo=timezone.utc)

                        min_from = datetime.now(timezone.utc) - timedelta(hours=24)
                        effective_from = last_dt_dt if last_dt_dt and last_dt_dt > min_from else min_from

                                                                                  
                        hist_url = f"{OPENAQ_SENSORS_URL}/{s_ext_id}/measurements"
                        iso = effective_from.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
                        meas_params = {"datetime_from": iso, "limit": limit_per_location}
                                                                                                 
                        mraw = fetch_json(client, hist_url, params=meas_params, headers=headers, schema=OpenAQMeasurementsResponse)
                        if not mraw:
                                                                                           
                                                                                            
                            try:
                                emit_event(
                                    event_type="openaq_measurements_validation_failed",
                                    severity="warning",
                                    sensor_id=s_ext_id,
                                    endpoint=hist_url,
                                    params=meas_params,
                                    message="measurements schema validation or fetch failed",
                                )
                            except Exception:
                                pass
                            mresults = []
                        else:
                                                                               
                            try:
                                mresults = mraw.results if hasattr(mraw, "results") else (mraw.get("results", []) if isinstance(mraw, dict) else [])
                            except Exception:
                                mresults = []
                        for mr in mresults:
                                                                 
                            m_param = (mr.get("parameter") or "").lower()
                            m_val = mr.get("value")
                            m_unit = mr.get("unit") or mr.get("units")
                            m_dt = None
                            if isinstance(mr.get("date"), dict):
                                m_dt = (mr.get("date") or {}).get("utc")
                            elif isinstance(mr.get("datetime"), dict):
                                m_dt = (mr.get("datetime") or {}).get("utc")
                                                      
                            try:
                                m_val = float(m_val)
                            except Exception:
                                m_val = None
                            if m_val is None:
                                continue
                            items.append(
                                {
                                    "location": dev.name if dev else None,
                                    "parameter": m_param,
                                    "value": m_val,
                                    "unit": m_unit,
                                    "datetime": {"utc": m_dt},
                                    "coordinates": {
                                        "latitude": getattr(dev, "latitude", None),
                                        "longitude": getattr(dev, "longitude", None),
                                    },
                                    "id": s_ext_id,
                                    "locationId": ext_id,
                                    "raw": {"measurement": mr},
                                }
                            )
                    except Exception:
                                                                                                      
                        pass

                session.commit()

            if not items:
                if hasattr(data, "results") and getattr(data, "results") is not None:
                    results = getattr(data, "results")
                elif isinstance(data, dict) and data.get("results"):
                    results = data.get("results")
                elif isinstance(data, dict) and data.get("measurements"):
                    results = [data]
                else:
                    results = [data]
            else:
                results = []

            for item in results:
                                                                                  
                if hasattr(item, "model_dump"):
                    try:
                        item = item.model_dump()
                    except Exception:
                        pass
                loc_name = (item.get("name") if isinstance(item, dict) else None) or (item.get("location") if isinstance(item, dict) else None) or getattr(item, "name", None) or getattr(item, "location", None) or dev.name
                coords_obj = (item.get("coordinates") if isinstance(item, dict) else getattr(item, "coordinates", None))
                if isinstance(coords_obj, dict):
                    coords = {"latitude": coords_obj.get("latitude"), "longitude": coords_obj.get("longitude")}
                else:
                    lat = getattr(coords_obj, "latitude", None) if coords_obj is not None else None
                    lon = getattr(coords_obj, "longitude", None) if coords_obj is not None else None
                    coords = {"latitude": lat if lat is not None else getattr(dev, "latitude", None), "longitude": lon if lon is not None else getattr(dev, "longitude", None)}
                source_measurements = (item.get("parameters") if isinstance(item, dict) else getattr(item, "parameters", None)) or (item.get("measurements") if isinstance(item, dict) else getattr(item, "measurements", None)) or []
                for m in source_measurements:
                    if hasattr(m, "model_dump"):
                        try:
                            m = m.model_dump()
                        except Exception:
                            pass
                    nd = {
                        "location": loc_name,
                        "parameter": ((m.get("parameter") if isinstance(m, dict) else getattr(m, "parameter", "")) or "").lower(),
                        "value": (m.get("value") if isinstance(m, dict) else getattr(m, "value", None)) or (m.get("lastValue") if isinstance(m, dict) else getattr(m, "lastValue", None)) or None,
                        "unit": (m.get("unit") if isinstance(m, dict) else getattr(m, "unit", None)),
                        "datetime": {
                            "utc": (m.get("lastUpdated") if isinstance(m, dict) else getattr(m, "lastUpdated", None))
                            or (m.get("lastUpdatedUtc") if isinstance(m, dict) else getattr(m, "lastUpdatedUtc", None))
                            or ((m.get("date") or {}).get("utc") if isinstance(m, dict) else (getattr(getattr(m, "date", None), "utc", None) if getattr(m, "date", None) is not None else None))
                        },
                        "coordinates": coords,
                        "id": (m.get("id") if isinstance(m, dict) else getattr(m, "id", None)) or None,
                        "locationId": ext_id,
                        "raw": {"location_item": item, "measurement": m},
                    }
                                                          
                    if nd["parameter"]:
                        pn = nd["parameter"].lower()
                        nd["parameter"] = pn if pn in known_params else pn
                    items.append(nd)

            if not items:
                print(f"No measurements returned for location {ext_id}; skipping.")
                continue

            if limit_per_location > 0:
                items = items[:limit_per_location]

            measurements = normalize_and_upsert_from_parameter_latest(
                items,
                parameter_name="",
                param_map=param_map,
                unit_code_map=unit_code_map,
                unit_symbol_map=unit_symbol_map,
                param_default_unit=param_default_unit,
                unit_id_code_map=unit_id_code_map,
            )
            if not measurements:
                print(f"Location {ext_id} returned measurements but none contained numeric values; skipping.")
                continue

            for idx, mobj in enumerate(measurements, start=1):
                dev_for_row = session.scalars(select(models.Device).where(models.Device.external_id == getattr(mobj, "_openaq_location_id", None))).one_or_none()
                if not dev_for_row:
                    dev_for_row = _upsert_device_for_external_location(session, getattr(mobj, "_openaq_location_id", None), name=None, latitude=None, longitude=None, timezone=None)
                code = getattr(mobj, "_parameter_code", None)
                pid = getattr(mobj, "_parameter_id", None)
                uid = getattr(mobj, "_unit_id", None)
                sensor = _upsert_sensor_for_device(
                    session,
                    dev_for_row,
                    (code or ""),
                    getattr(mobj, "_openaq_sensor_id", None),
                    parameter_id=pid,
                    unit_id=uid,
                    unit_id_code_map=unit_id_code_map,
                    convert_unit=True,
                ) if dev_for_row else None

                if sensor:
                    mobj.sensor_id = sensor.sensor_id
                                                                                       
                if dev_for_row:
                    try:
                        from .openaq_upserts import _update_device_location
                        _update_device_location(session, dev_for_row, getattr(dev_for_row, "latitude", None), getattr(dev_for_row, "longitude", None), effective_from=mobj.observed_at)
                    except Exception:
                        pass
                                                                                    

                action = upsert_measurement_with_policy(session, mobj, device=dev_for_row, sensor=sensor)
                                 
                p = (code or "unknown")
                action_totals[action] += 1
                per_param_actions[p][action] += 1
                if idx % batch_size == 0:
                    session.commit()
                    inserted_total += batch_size

            session.commit()
            inserted_total += len(measurements)
            processed_locations += 1
            print(
                f"Inserted {len(measurements)} measurements for location {ext_id} "
                f"(processed {processed_locations})"
            )

                                                                  
    try:
        throttling_metrics = client.get_metrics()
    except Exception:
        throttling_metrics = None

    print(f"Total inserted measurements (raw count of prepared rows): {inserted_total}")
                                                     
    print("Summary by parameter:")
    for param, ctr in sorted(per_param_actions.items()):
        ins = ctr.get('insert', 0)
        upd = ctr.get('update', 0)
        skp = ctr.get('skip', 0)
        total = ins + upd + skp
        print(f"  {param}: total={total}, inserted={ins}, updated={upd}, skipped={skp}")
    print("Overall actions:")
    print(f"  inserted={action_totals.get('insert', 0)}, updated={action_totals.get('update', 0)}, skipped={action_totals.get('skip', 0)}")

                                    
    payload = {
        "per_parameter": {
            p: {"insert": c.get("insert", 0), "update": c.get("update", 0), "skip": c.get("skip", 0)}
            for p, c in per_param_actions.items()
        },
        "overall": {
            "insert": action_totals.get("insert", 0),
            "update": action_totals.get("update", 0),
            "skip": action_totals.get("skip", 0),
        },
        "prepared_rows": inserted_total,
    }
    if throttling_metrics:
        payload["throttling"] = throttling_metrics

                                                         
    if summary_json:
        try:
            out_path = Path(summary_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, indent=2))
            print(f"Wrote summary JSON to {out_path}")
        except Exception as e:
            print(f"Failed to write summary JSON to {summary_json}: {e}")

    if summary_csv:
        try:
            out_path = Path(summary_csv)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["parameter", "inserted", "updated", "skipped", "total"]) 
                for p, c in sorted(per_param_actions.items()):
                    ins = c.get("insert", 0)
                    upd = c.get("update", 0)
                    skp = c.get("skip", 0)
                    total = ins + upd + skp
                    w.writerow([p, ins, upd, skp, total])
            print(f"Wrote summary CSV to {out_path}")
        except Exception as e:
            print(f"Failed to write summary CSV to {summary_csv}: {e}")

    return payload


def main() -> None:
    """Main entry point: focused single sensor run or bulk location import."""

    parser = argparse.ArgumentParser(description="OpenAQ Importer")
    parser.add_argument("--summary-json", dest="summary_json", default=str(DEFAULT_OUT_DIR / "import_summary.json"), help="Write per-parameter summary to this JSON file")
    parser.add_argument("--summary-csv", dest="summary_csv", default=str(DEFAULT_OUT_DIR / "import_summary.csv"), help="Write per-parameter summary to this CSV file")
    parser.add_argument("--sync-catalogs", dest="sync_catalogs", action="store_true", help="Sync Parameter/Unit catalogs from existing Sensor records and exit")
    args, _unknown = parser.parse_known_args()

    print("Starting OpenAQ import")
                                                                                                          
    try:
        discovery.load_plugins()
    except Exception:
        print("Plugin discovery in importer failed; continuing with built-in plugins")
    if args.sync_catalogs:
        print("Syncing Parameter and Unit catalogs from Sensor records...")
        sync_catalogs_from_sensors()
        return
    target_sensor = os.getenv("OPENAQ_TARGET_SENSOR_ID")
    api_key = _get_api_key_for_external_api("OpenAQ") or os.getenv("OPENAQ_API_KEY")
    if target_sensor:
        try:
            sid = str(int(target_sensor))
        except Exception:
            sid = target_sensor
        print(f"Focused run for sensor {sid}")
        if not api_key:
            print("Error: OpenAQ API key not configured; failing job.", flush=True)
            try:
                emit_event(event_type="openaq_missing_api_key", severity="error", message="OpenAQ API key not configured")
            except Exception:
                pass
            sys.exit(2)
        import_single_sensor(sid)
                                                                             
        if args.summary_json or args.summary_csv:
                                                                                                                             
            payload = {
                "per_parameter": {},
                "overall": {"insert": 0, "update": 0, "skip": 0},
                "prepared_rows": 1,
            }
            if args.summary_json:
                try:
                    p = Path(args.summary_json)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps(payload, indent=2))
                    print(f"Wrote (minimal) summary JSON to {args.summary_json}")
                except Exception as e:
                    print(f"Failed to write summary JSON: {e}")
            if args.summary_csv:
                try:
                    p = Path(args.summary_csv)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with p.open("w", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        w.writerow(["parameter", "inserted", "updated", "skipped", "total"]) 
                    print(f"Wrote (minimal) summary CSV to {args.summary_csv}")
                except Exception as e:
                    print(f"Failed to write summary CSV: {e}")
        return

    if not api_key:
        print("Error: OpenAQ API key not configured; failing job.", flush=True)
        try:
            emit_event(event_type="openaq_missing_api_key", severity="error", message="OpenAQ API key not configured")
        except Exception:
            pass
        sys.exit(2)

    print("Running bulk import for OpenAQ devices already in the database")
    import_measurements_from_locations(
        limit_per_location=100,
        summary_json=args.summary_json,
        summary_csv=args.summary_csv,
    )


if __name__ == "__main__":
    main()
