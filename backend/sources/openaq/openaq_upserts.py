"""Helpers for normalizing OpenAQ payloads and upserting Device/Sensor records.

These helpers focus on DB-related concerns. They accept a SQLAlchemy
session and return model instances; callers are responsible for committing.
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple
from datetime import datetime
from sqlalchemy import select, text

import models
from services.device_locations import set_device_location
from qaqc.pipeline import run_ingest_detailed
from qaqc.persistence import apply_ingest_qc_result
from qaqc.types import QCRecord
import qaqc.plugins                                                  


logger = logging.getLogger(__name__)
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

# OpenAQ gas measurements must retain the provider's reported unit and value.
# A molecular-weight factor alone cannot convert between mass concentration and
# mixing ratio without temperature and pressure.
AQI_GAS_PARAMETER_CODES = frozenset({"o3", "co", "no2", "so2"})


@dataclass(frozen=True)
class MeasurementUpsertResult:
    """Database action plus QC outcomes produced by that same upsert."""

    action: Literal["insert", "update", "skip"]
    qc: dict[str, int] | None = None


def _qc_counts_from_detailed_result(
    detailed_result: dict[str, Any],
) -> dict[str, int] | None:
    """Summarize the QC decisions already produced by the ingest pipeline."""
    per_plugin = detailed_result.get("per_plugin") or {}
    if not per_plugin:
        return None

    aligned_decisions = [
        decisions[0]
        for decisions in per_plugin.values()
        if decisions and decisions[0] is not None
    ]
    if not aligned_decisions:
        # A resolver-known not-applicable policy leaves no decision to count.
        # It is neither a pass nor an indeterminate evaluation.
        return None
    has_failed_check = any(
        decision.is_valid is False for decision in aligned_decisions
    )
    has_indeterminate_check = any(
        decision.is_valid is None for decision in aligned_decisions
    )
    return {
        "evaluated": 1,
        "passed": 1 if not has_failed_check and not has_indeterminate_check else 0,
        "flagged": 1 if has_failed_check else 0,
        "indeterminate": 1 if not has_failed_check and has_indeterminate_check else 0,
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


def _openaq_import_unit_id(
    param_code: str,
    reported_unit: Optional[str],
    param_default_unit: Dict[str, int],
    unit_code_map: Dict[str, int],
    unit_symbol_map: Dict[str, int],
) -> Optional[int]:
    """Preserve reported AQI-gas units; use existing defaults otherwise.

    A gaseous mass concentration cannot be converted to a mixing ratio without
    temperature and pressure. Keeping the reported unit lets the strict AQI
    path reject unsupported conversions explicitly.
    """
    incoming_unit_id = None
    if reported_unit:
        incoming_unit_id = (
            unit_code_map.get(reported_unit)
            or unit_symbol_map.get(reported_unit)
            or unit_code_map.get(_unit_kind(reported_unit) or "")
        )
    if (param_code or "").strip().lower() in AQI_GAS_PARAMETER_CODES:
        return incoming_unit_id
    return _canonical_unit_id(
        param_code,
        param_default_unit,
        unit_code_map,
        unit_symbol_map,
    ) or incoming_unit_id


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
        provider_code = name.strip().lower()
        row = session.scalars(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == provider_code
            )
        ).one_or_none()
        if row:
            return getattr(row, "external_api_id", None)
                                          
        provider_code = provider_code if provider_code in {
            "openaq",
            "purpleair",
            "airgradient",
        } else None
        api = models.ExternalAPI(
            provider_code=provider_code,
            name=name,
            enabled=False,
            params={},
        )
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
    """Compatibility wrapper for provider code using the shared writer."""
    set_device_location(
        session,
        device,
        latitude=latitude,
        longitude=longitude,
        effective_at=effective_from,
    )


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

                                                                                    
        uid = _openaq_import_unit_id(
            p_code,
            unit,
            param_default_unit,
            unit_code_map,
            unit_symbol_map,
        )
        target_code = unit_id_code_map.get(uid) if uid is not None else None

        # AQI gases retain the exact source unit. In particular, never infer a
        # gas mass-to-mixing-ratio conversion from molecular weight alone.
        if p_code not in AQI_GAS_PARAMETER_CODES:
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
    api_id = _get_external_api_id(session, external_api_name)
    if ext and api_id is not None:
        dev = session.scalars(
            select(models.Device).where(
                models.Device.external_api_id == api_id,
                models.Device.external_id == ext,
            )
        ).one_or_none()
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
                                                                                
        if dev.latitude is None and dev.longitude is None and (
            latitude is not None or longitude is not None
        ):
            set_device_location(
                session,
                dev,
                latitude=latitude,
                longitude=longitude,
            )
            changed = True
        if changed:
            session.add(dev)
            session.flush()
        return dev
                       
    disp_name = name or (f"openaq-location-{ext}" if ext else "openaq-device")
    dev = models.Device(name=disp_name, external_api_id=api_id or 1)
    dev.external_id = ext
                                                                            
    try:
        if timezone:
            dev.timezone = timezone
        else:
                                                    
            if latitude is not None and longitude is not None:
                try:
                    tf = TimezoneFinder()
                    t = tf.timezone_at(lat=float(latitude), lng=float(longitude))
                    if t:
                        dev.timezone = t
                except Exception:
                    pass
    except Exception:
        pass
    session.add(dev)
    set_device_location(
        session,
        dev,
        latitude=latitude,
        longitude=longitude,
    )
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
            elif (
                convert_unit
                and current_uid != unit_id
                and (param_name or "").strip().lower() not in AQI_GAS_PARAMETER_CODES
            ):
                                                                                      
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


def upsert_measurement_with_policy_detailed(
    session,
    measurement: models.Measurement,
    device: Optional[models.Device] = None,
    sensor: Optional[models.Sensor] = None,
) -> MeasurementUpsertResult:
    """Insert/update/skip a measurement and return its existing QC outcome.

    Policy evaluation:
    - Sensor policy precedence: if Sensor.allow_updates is ALLOW -> update; DENY -> skip; INHERIT -> defer to device
    - Device policy: ALLOW -> update; DENY -> skip; INHERIT -> default skip

    QC runs exactly once for inserted and allowed-updated measurements. Skips do
    not run QC because no measurement value is written.
    """
    incoming_parameter_code = str(
        getattr(measurement, "_parameter_code", "") or ""
    ).strip().lower()
    incoming_unit_id = getattr(measurement, "_unit_id", None)
    sensor_unit_id = getattr(sensor, "unit_id", None) if sensor else None
    if (
        incoming_parameter_code in AQI_GAS_PARAMETER_CODES
        and incoming_unit_id is not None
        and sensor_unit_id is not None
        and incoming_unit_id != sensor_unit_id
    ):
        logger.warning(
            "Skipping OpenAQ %s measurement for sensor %s because reported "
            "unit_id %s differs from stored unit_id %s",
            incoming_parameter_code,
            getattr(sensor, "sensor_id", None),
            incoming_unit_id,
            sensor_unit_id,
        )
        return MeasurementUpsertResult(action="skip")

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
        return MeasurementUpsertResult(action="insert")

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
        aggregate_code = _effective_aggregate_code(session, sensor)
        detailed = run_ingest_detailed(
            [rec], {"session": session, "aggregate_code": aggregate_code}
        )
        apply_ingest_qc_result(
            session,
            measurement,
            pid,
            aggregate_code,
            detailed,
            replace_existing=False,
        )
        return MeasurementUpsertResult(
            action="insert",
            qc=_qc_counts_from_detailed_result(detailed),
        )

                                         
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
        aggregate_code = _effective_aggregate_code(session, sensor)
        detailed = run_ingest_detailed(
            [rec], {"session": session, "aggregate_code": aggregate_code}
        )
        apply_ingest_qc_result(
            session,
            existing,
            pid,
            aggregate_code,
            detailed,
            replace_existing=True,
        )
        return MeasurementUpsertResult(
            action="update",
            qc=_qc_counts_from_detailed_result(detailed),
        )

                                       
    return MeasurementUpsertResult(action="skip")


def upsert_measurement_with_policy(
    session,
    measurement: models.Measurement,
    device: Optional[models.Device] = None,
    sensor: Optional[models.Sensor] = None,
) -> str:
    """Compatibility wrapper returning only ``insert``, ``update``, or ``skip``."""
    return upsert_measurement_with_policy_detailed(
        session,
        measurement,
        device=device,
        sensor=sensor,
    ).action
