"""Helpers for normalizing OpenAQ payloads and upserting Device/Sensor records.

These helpers focus on DB-related concerns. They accept a SQLAlchemy
session and return model instances; callers are responsible for committing.
"""
from typing import List, Optional, Tuple, Dict
from datetime import datetime
from sqlalchemy import select, text

import models
from qaqc.pipeline import run_ingest, run_ingest_detailed
from qaqc.types import QCRecord
import qaqc.plugins                                                  
try:
    from timezonefinder import TimezoneFinder
except Exception:
                                                                     
    class TimezoneFinder:                
        def timezone_at(self, *args, **kwargs):
            return None

                                                                                    
                                             
PARAM_UNIT_FALLBACK: Dict[str, str] = {
    "pm25": "ug_m3",
    "pm10": "ug_m3",
    "pm1": "ug_m3",
    "o3": "ppm",
    "no2": "ppm",
    "nox": "ppm",
    "so2": "ppm",
    "co": "ppm",
    "no": "ppb",
    "relativehumidity": "percent",
    "temperature": "c",
}

                                                                 
UG_PER_PPM: Dict[str, float] = {
    "o3": 1963.0,          
    "no2": 1880.0,         
    "nox": 1880.0,                      
    "no": 1226.0,          
    "so2": 2620.0,         
    "co": 1145.0,          
}


def _normalize_unit_str(unit: Optional[str]) -> str:
    u = (unit or "").strip().lower()
    u = u.replace("µ", "u").replace(" ", "")
    u = u.replace("m³", "m3").replace("^3", "3")
    u = u.replace("/", "_")
    return u


def _unit_kind(unit: Optional[str]) -> Optional[str]:
    u = _normalize_unit_str(unit)
    if not u:
        return None
    if "ppm" in u:
        return "ppm"
    if "ppb" in u:
        return "ppb"
    if "mg_m3" in u:
        return "mg_m3"
    if "ug_m3" in u or "ugm3" in u or "æg_m3" in u:
        return "ug_m3"
    if "%" in u or "percent" in u:
        return "percent"
    if "c" == u:
        return "c"
    return u


def _canonical_unit_id(
    param_code: str,
    param_default_unit: Dict[str, int],
    unit_code_map: Dict[str, int],
    unit_symbol_map: Dict[str, int],
) -> Optional[int]:
    """Return preferred unit_id for the parameter using DB defaults with a fallback map."""
    code = (param_code or "").lower()
    if code in param_default_unit:
        return param_default_unit[code]
    fallback = PARAM_UNIT_FALLBACK.get(code)
    if fallback:
        return unit_code_map.get(fallback) or unit_symbol_map.get(fallback)
    return None


def _conversion_factor(param_code: str, from_unit: Optional[str], to_unit: Optional[str]) -> Optional[float]:
    """Return multiplicative factor to convert from -> to units (None if unknown)."""
    src = _unit_kind(from_unit)
    dst = _unit_kind(to_unit)
    if not src or not dst or src == dst:
        return 1.0 if src and dst and src == dst else None

                                        
    mw = UG_PER_PPM.get((param_code or "").lower())

    if dst == "ppm":
        if src == "ppb":
            return 1.0 / 1000.0
        if src == "ug_m3" and mw:
            return 1.0 / mw
        if src == "mg_m3" and mw:
            return 1000.0 / mw
    if dst == "ppb":
        if src == "ppm":
            return 1000.0
        if src == "ug_m3" and mw:
            return (1.0 / mw) * 1000.0
        if src == "mg_m3" and mw:
            return (1000.0 / mw) * 1000.0
    if dst == "ug_m3":
        if src == "ppm" and mw:
            return mw
        if src == "ppb" and mw:
            return mw / 1000.0
        if src == "mg_m3":
            return 1000.0

                                
    return None


def _convert_value_to_unit(
    param_code: str,
    value: float,
    src_unit: Optional[str],
    target_unit: Optional[str],
) -> float:
    """Convert numeric value into the target unit when possible."""
    factor = _conversion_factor(param_code, src_unit, target_unit)
    if factor is None or factor == 1.0:
        return value
    try:
        return value * factor
    except Exception:
        return value


def _get_external_api_id(session, name: str) -> int | None:
    """Return external_api_id for provider name, creating row if missing (minimal fields)."""
    try:
        row = session.scalars(select(models.ExternalAPI).where(models.ExternalAPI.name == name)).one_or_none()
        if row:
            return getattr(row, "external_api_id", None)
                                          
        api = models.ExternalAPI(name=name)
        session.add(api)
        session.flush()
        return getattr(api, "external_api_id", None)
    except Exception:
        return None


def _effective_aggregate_code(session, sensor: Optional[models.Sensor]) -> str:
    """Choose the aggregate code to use for QC.

    Preference: sensor.aggregation_period_id → corresponding AggregationPeriod.code; else '1h'.
    """
    try:
        if sensor and getattr(sensor, "aggregation_period_id", None):
            ap = session.scalars(
                select(models.AggregationPeriod.code).where(
                    models.AggregationPeriod.aggregation_period_id == sensor.aggregation_period_id
                )
            ).one_or_none()
            if ap:
                return ap
    except Exception:
        pass
    return "1h"


def _update_device_location(
    session,
    device: models.Device,
    latitude: Optional[float],
    longitude: Optional[float],
    effective_from: Optional[datetime] = None,
) -> None:
    """Ensure the device location history reflects the given lat/lon.

    If the latest open-ended row has the same lat/lon, do nothing.
    Otherwise, close the previous row (set effective_to) and insert a new one.
    """
    if latitude is None and longitude is None:
        return
    ef = effective_from or datetime.utcnow()
                                 
    latest = None
    try:
        latest = session.scalars(
            select(models.DeviceLocationHistory)
            .where(models.DeviceLocationHistory.device_id == device.device_id)
            .order_by(models.DeviceLocationHistory.effective_from.desc())
            .limit(1)
        ).one_or_none()
    except Exception:
        latest = None
    if latest and latest.effective_to is None:
                                              
        if (latest.latitude == latitude) and (latest.longitude == longitude):
            return
                                                                      
        if latest.effective_from <= ef:
            latest.effective_to = ef
            session.add(latest)
                    
    new_row = models.DeviceLocationHistory(
        device_id=device.device_id,
        latitude=latitude,
        longitude=longitude,
        effective_from=ef,
        effective_to=None,
    )
    session.add(new_row)


def _extract_provider_ids(it: dict) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    loc = None
    sens = None
    mid = None

    if "locationsId" in it:
        v = it.get("locationsId")
        if isinstance(v, (list, tuple)) and v:
            loc = str(v[0])
        elif v is not None:
            loc = str(v)
    if "locationId" in it:
        loc = str(it.get("locationId") or loc)
    if "locations" in it and not loc:
        loc = str(it.get("locations"))

    if "sensorsId" in it:
        v = it.get("sensorsId")
        if isinstance(v, (list, tuple)) and v:
            sens = str(v[0])
        elif v is not None:
            sens = str(v)
    if "sensorId" in it:
        sens = str(it.get("sensorId") or sens)

    if "id" in it:
        mid = str(it.get("id"))
    if "measurementId" in it:
        mid = str(it.get("measurementId") or mid)

    return loc, sens, mid


def normalize_and_upsert_from_parameter_latest(
    items: List[dict],
    parameter_name: str = "pm25",
    param_map: Optional[Dict[str, int]] = None,
    unit_code_map: Optional[Dict[str, int]] = None,
    unit_symbol_map: Optional[Dict[str, int]] = None,
    param_default_unit: Optional[Dict[str, int]] = None,
    unit_id_code_map: Optional[Dict[int, str]] = None,
) -> List[models.Measurement]:
    objs: List[models.Measurement] = []
    param_map = param_map or {}
    unit_code_map = unit_code_map or {}
    unit_symbol_map = unit_symbol_map or {}
    param_default_unit = param_default_unit or {}
    unit_id_code_map = unit_id_code_map or {uid: code for code, uid in unit_code_map.items()}
                                                                              
                                                                           
    for it in items:
        dt = None
        if isinstance(it.get("datetime"), dict):
            dt = it["datetime"].get("utc")

        raw = it
        unit = it.get("unit") or None

        value = it.get("value")
        try:
            valf = float(value) if value is not None else 0.0
        except Exception:
            continue

        loc_ext, sens_ext, mid = _extract_provider_ids(it)

                               
        p_code = it.get("parameter") or parameter_name or ""
        try:
            p_code = str(p_code).lower()
        except Exception:
            p_code = parameter_name
        pid = param_map.get(p_code)

                                                                                    
        canonical_uid = _canonical_unit_id(p_code, param_default_unit, unit_code_map, unit_symbol_map)
        incoming_uid = unit_code_map.get(unit) or unit_symbol_map.get(unit) if unit else None
        uid = canonical_uid or incoming_uid
        target_code = unit_id_code_map.get(uid) if uid is not None else None

                                                                
        valf = _convert_value_to_unit(p_code, valf, unit, target_code)

        m = models.Measurement(
            sensor_id=None,
            value=valf,
            observed_at=dt,
        )
                                                              
        setattr(m, "_parameter_code", p_code)
        setattr(m, "_parameter_id", pid)
        setattr(m, "_unit_id", uid)
                                                            
        setattr(m, "_openaq_location_id", loc_ext)
        setattr(m, "_openaq_sensor_id", sens_ext)
        setattr(m, "_openaq_id", mid)
        objs.append(m)

    return objs


                                                      


def _upsert_device_for_external_location(
    session,
    external_id: Optional[str],
    name: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    timezone: Optional[str] = None,
    external_api_name: str = "OpenAQ",
) -> models.Device:
    """Create or update a Device keyed by external_id (e.g., OpenAQ location id).

    - If a Device with the given external_id exists, update name if missing and
      coordinates if not set, and append to DeviceLocationHistory when coords differ.
    - If none exists, create a new Device with provided fields and seed location history.
    """
    ext = str(external_id) if external_id is not None else None
    dev: Optional[models.Device] = None
    if ext:
        dev = session.scalars(select(models.Device).where(models.Device.external_id == ext)).one_or_none()
    api_id = _get_external_api_id(session, external_api_name)
    if dev:
        changed = False
        if name and not getattr(dev, "name", None):
            dev.name = name
            changed = True
        if api_id is not None and getattr(dev, "external_api_id", None) is None:
            try:
                dev.external_api_id = api_id
                changed = True
            except Exception:
                pass
                                                          
        if timezone and not getattr(dev, "timezone", None):
            try:
                dev.timezone = timezone
                changed = True
            except Exception:
                pass
                                                                                
        if (getattr(dev, "latitude", None) is None and latitude is not None) or (
            getattr(dev, "longitude", None) is None and longitude is not None
        ):
            dev.latitude = latitude if latitude is not None else dev.latitude
            dev.longitude = longitude if longitude is not None else dev.longitude
            changed = True
            try:
                _update_device_location(session, dev, dev.latitude, dev.longitude, effective_from=None)
            except Exception:
                pass
        if changed:
            session.add(dev)
            session.flush()
        return dev
                       
    disp_name = name or (f"openaq-location-{ext}" if ext else "openaq-device")
    dev = models.Device(name=disp_name, external_api_id=api_id or 1)
    dev.external_id = ext
    dev.latitude = latitude
    dev.longitude = longitude
                                                                            
    try:
        if timezone:
            dev.timezone = timezone
        else:
                                                    
            if dev.latitude is not None and dev.longitude is not None:
                try:
                    tf = TimezoneFinder()
                    t = tf.timezone_at(lat=float(dev.latitude), lng=float(dev.longitude))
                    if t:
                        dev.timezone = t
                except Exception:
                    pass
    except Exception:
        pass
    session.add(dev)
    session.flush()
    try:
        _update_device_location(session, dev, latitude, longitude, effective_from=None)
    except Exception:
        pass
    return dev


def _upsert_device_for_sensor(session, sensor_obj: dict, sensor_id: str, db_loc: Optional[object] = None, external_api_name: str = "OpenAQ") -> models.Device:
                                                                       
                                                                        
                                                                           
    base_name = None
    if isinstance(sensor_obj, dict):
        base_name = sensor_obj.get("name")
    else:
                                              
        base_name = getattr(sensor_obj, "name", None)

    if not base_name:
        base_name = f"openaq-device-sensor-{sensor_id}"

    candidate_plain = base_name
    candidate_with_id = f"{base_name}-{sensor_id}"

    existing = session.scalars(
        select(models.Device).where((models.Device.name == candidate_plain) | (models.Device.name == candidate_with_id))
    ).one_or_none()

    api_id = _get_external_api_id(session, external_api_name)
    if existing:
        if api_id is not None and getattr(existing, "external_api_id", None) is None:
            try:
                existing.external_api_id = api_id
                session.add(existing)
                session.flush()
            except Exception:
                pass
                                                
        return existing

                                                                          
    dev = models.Device(name=candidate_with_id, external_api_id=api_id or 1)
    session.add(dev)
    try:
                                                                          
        session.commit()
        return dev
    except Exception:
                                                                                   
        session.rollback()
        existing = session.scalars(
            select(models.Device).where((models.Device.name == candidate_plain) | (models.Device.name == candidate_with_id))
        ).one_or_none()
        if existing:
            return existing
                                                                 
        raise


def _upsert_sensor_for_device(
    session,
    device: models.Device,
    param_name: str,
    external_sensor_id: Optional[str],
    parameter_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    aggregation_period_id: Optional[int] = None,
    unit_id_code_map: Optional[Dict[int, str]] = None,
    convert_unit: bool = False,
) -> models.Sensor:
                                                                                        
    cond = [models.Sensor.device_id == device.device_id]
    if parameter_id is not None:
        cond.append(models.Sensor.parameter_id == parameter_id)
    if external_sensor_id:
        cond.append(models.Sensor.external_sensor_id == external_sensor_id)
    res = session.execute(select(models.Sensor).where(*cond).limit(1))
    sensor = res.scalars().first()
    if not sensor:
        sensor = models.Sensor(
            device_id=device.device_id,
            external_sensor_id=external_sensor_id,
        )
        if parameter_id is not None:
            sensor.parameter_id = parameter_id
        if unit_id is not None:
            sensor.unit_id = unit_id
        if aggregation_period_id is not None:
            sensor.aggregation_period_id = aggregation_period_id
        session.add(sensor)
        session.flush()
    else:
                                                                    
        if parameter_id is not None and getattr(sensor, "parameter_id", None) is None:
            sensor.parameter_id = parameter_id
            session.add(sensor)
        if unit_id is not None:
            current_uid = getattr(sensor, "unit_id", None)
            if current_uid is None:
                sensor.unit_id = unit_id
                session.add(sensor)
            elif convert_unit and current_uid != unit_id:
                                                                                      
                unit_lookup = unit_id_code_map or {}
                src_code = unit_lookup.get(current_uid)
                dst_code = unit_lookup.get(unit_id)
                factor = _conversion_factor(param_name, src_code, dst_code)
                if factor and factor != 1.0:
                    try:
                        session.execute(
                            text("UPDATE measurement SET value = value * :factor WHERE sensor_id = :sid"),
                            {"factor": factor, "sid": sensor.sensor_id},
                        )
                    except Exception:
                                                                                                          
                        factor = None
                if factor:
                    sensor.unit_id = unit_id
                    session.add(sensor)
        if aggregation_period_id is not None and getattr(sensor, "aggregation_period_id", None) is None:
            sensor.aggregation_period_id = aggregation_period_id
            session.add(sensor)
    return sensor


def upsert_measurement_with_policy(
    session,
    measurement: models.Measurement,
    device: Optional[models.Device] = None,
    sensor: Optional[models.Sensor] = None,
) -> str:
    """Insert/update/skip a measurement based on allow_updates policy.

    Policy evaluation:
    - Sensor policy precedence: if Sensor.allow_updates is ALLOW -> update; DENY -> skip; INHERIT -> defer to device
    - Device policy: ALLOW -> update; DENY -> skip; INHERIT -> default skip

    Returns one of: 'insert', 'update', 'skip'
    """
    sid = measurement.sensor_id
    ts = measurement.observed_at
                                                                             
    if isinstance(ts, str):
        s = ts.strip()
        if s.endswith('Z'):
            s = s.replace('Z', '+00:00')
        try:
            ts_dt = datetime.fromisoformat(s)
            measurement.observed_at = ts_dt
            ts = ts_dt
        except Exception:
            ts = None
    if not sid or not ts:
                                                      
        session.add(measurement)
        return "insert"

    existing = session.scalars(
        select(models.Measurement).where(
            models.Measurement.sensor_id == sid,
            models.Measurement.observed_at == ts,
        )
    ).one_or_none()

    if not existing:
                                                                 
        pid = getattr(sensor, "parameter_id", None) if sensor else None
        uid = getattr(sensor, "unit_id", None) if sensor else None
        rec = QCRecord(
            sensor_id=measurement.sensor_id,
            parameter_id=pid,
            value=measurement.value,
            unit_id=uid,
            observed_at=measurement.observed_at,
            device_latitude=getattr(device, "latitude", None) if device else None,
            device_longitude=getattr(device, "longitude", None) if device else None,
            meta=None,
        )
        detailed = run_ingest_detailed([rec], {"session": session, "aggregate_code": _effective_aggregate_code(session, sensor)})
        overall = (detailed.get("overall") or [None])[0]
        per = detailed.get("per_plugin", {})
        if overall and overall.is_valid is not None:
            measurement.is_valid = bool(overall.is_valid)
                                                           
        failed_checks = [name for name, lst in per.items() if lst and lst[0] and lst[0].is_valid is False]
        if failed_checks:
            try:
                measurement.qc_flags = failed_checks
            except Exception:
                pass
        session.add(measurement)
        session.flush()
                                                                                
        try:
            from sqlalchemy import select as sa_select
            for name, lst in per.items():
                dec = lst[0] if lst else None
                if not dec:
                    continue
                                                              
                mqr = session.scalars(
                    sa_select(models.MeasurementQCResult).where(
                        models.MeasurementQCResult.measurement_id == measurement.measurement_id,
                        models.MeasurementQCResult.check_code == name,
                    )
                ).one_or_none()
                if dec.is_valid is False:
                    payload = models.MeasurementQCResult(
                        measurement_id=measurement.measurement_id,
                        parameter_id=pid,
                        aggregate_code=_effective_aggregate_code(session, sensor),
                        check_code=name,
                        passed=False,
                        details={"value": measurement.value, **(dec.patch or {})},
                        severity=dec.severity or "error",
                        message=dec.message or "",
                        rule_source=(dec.patch or {}).get("source"),
                        params_snapshot=(dec.patch or {}).get("params"),
                        plugin_version=None,
                        stage="ingest",
                        qc_version=None,
                    )
                    if mqr:
                                         
                        mqr.passed = False
                        mqr.details = payload.details
                        mqr.severity = payload.severity
                        mqr.message = payload.message
                        mqr.rule_source = payload.rule_source
                        mqr.params_snapshot = payload.params_snapshot
                        mqr.plugin_version = payload.plugin_version
                        mqr.stage = payload.stage
                        mqr.qc_version = payload.qc_version
                        session.add(mqr)
                    else:
                        session.add(payload)
                else:
                                                                                      
                    if mqr:
                        mqr.passed = True
                        mqr.details = {"value": measurement.value}
                        mqr.severity = "info"
                        mqr.message = ""
                        mqr.stage = "ingest"
                        session.add(mqr)
        except Exception:
            pass
        return "insert"

                                         
    decision: Optional[bool] = None
    if sensor:
        if sensor.allow_updates == models.UpdatePolicy.ALLOW:
            decision = True
        elif sensor.allow_updates == models.UpdatePolicy.DENY:
            decision = False
                                 
    if decision is None and device:
        if device.allow_updates == models.UpdatePolicy.ALLOW:
            decision = True
        elif device.allow_updates == models.UpdatePolicy.DENY:
            decision = False

    if decision is True:
                                                                                       
        existing.value = measurement.value
        pid = getattr(sensor, "parameter_id", None) if sensor else None
        uid = getattr(sensor, "unit_id", None) if sensor else None
        rec = QCRecord(
            sensor_id=existing.sensor_id,
            parameter_id=pid,
            value=existing.value,
            unit_id=uid,
            observed_at=existing.observed_at,
            device_latitude=getattr(device, "latitude", None) if device else None,
            device_longitude=getattr(device, "longitude", None) if device else None,
            meta=None,
        )
        detailed = run_ingest_detailed([rec], {"session": session, "aggregate_code": _effective_aggregate_code(session, sensor)})
        overall = (detailed.get("overall") or [None])[0]
        per = detailed.get("per_plugin", {})
        if overall and overall.is_valid is not None:
            existing.is_valid = bool(overall.is_valid)
                              
        failed_checks = [name for name, lst in per.items() if lst and lst[0] and lst[0].is_valid is False]
        try:
            existing.qc_flags = failed_checks or None
        except Exception:
            pass
        session.add(existing)
        session.flush()
                               
        try:
            from sqlalchemy import select as sa_select
            for name, lst in per.items():
                dec = lst[0] if lst else None
                if not dec:
                    continue
                mqr = session.scalars(
                    sa_select(models.MeasurementQCResult).where(
                        models.MeasurementQCResult.measurement_id == existing.measurement_id,
                        models.MeasurementQCResult.check_code == name,
                    )
                ).one_or_none()
                if dec.is_valid is False:
                    payload_details = {"value": existing.value, **(dec.patch or {})}
                    if mqr:
                        mqr.passed = False
                        mqr.details = payload_details
                        mqr.severity = dec.severity or "error"
                        mqr.message = dec.message or ""
                        mqr.rule_source = (dec.patch or {}).get("source")
                        mqr.params_snapshot = (dec.patch or {}).get("params")
                        mqr.stage = "ingest"
                        session.add(mqr)
                    else:
                        session.add(models.MeasurementQCResult(
                            measurement_id=existing.measurement_id,
                            parameter_id=pid,
                            aggregate_code=_effective_aggregate_code(session, sensor),
                            check_code=name,
                            passed=False,
                            details=payload_details,
                            severity=dec.severity or "error",
                            message=dec.message or "",
                            rule_source=(dec.patch or {}).get("source"),
                            params_snapshot=(dec.patch or {}).get("params"),
                            plugin_version=None,
                            stage="ingest",
                            qc_version=None,
                        ))
                else:
                    if mqr:
                        mqr.passed = True
                        mqr.details = {"value": existing.value}
                        mqr.severity = "info"
                        mqr.message = ""
                        mqr.stage = "ingest"
                        session.add(mqr)
        except Exception:
            pass
        return "update"

                                       
    return "skip"
