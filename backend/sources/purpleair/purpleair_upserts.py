from __future__ import annotations

from typing import Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy import select

import models
from .purpleair_schemas import Sensor
from sources.openaq.openaq_upserts import (
    _upsert_device_for_sensor,
    _upsert_sensor_for_device,
    _update_device_location,
    upsert_measurement_with_policy,
)


def _resolve_param_and_unit_ids(session) -> Tuple[Optional[int], Optional[int]]:
    """Resolve ids for canonical PurpleAir PM2.5 and its unit.

    Parameter code: 'pm25'
    Unit preference: symbol 'µg/m³' then code 'ug_m3'.
    Returns (parameter_id, unit_id) which may be (None, None) if not found.
    """
    try:
        pid = session.scalar(select(models.Parameter.parameter_id).where(models.Parameter.code == "pm25"))
    except Exception:
        pid = None
    uid = None
    if pid is not None:
                                                        
        try:
            du = session.scalar(select(models.Parameter.default_unit_id).where(models.Parameter.parameter_id == pid))
            if du:
                uid = du
        except Exception:
            pass
    if uid is None:
        try:
            uid = session.scalar(select(models.Unit.unit_id).where(models.Unit.symbol == "µg/m³"))
        except Exception:
            uid = None
    if uid is None:
        try:
            uid = session.scalar(select(models.Unit.unit_id).where(models.Unit.code == "ug_m3"))
        except Exception:
            uid = None
    return pid, uid


def upsert_from_purpleair_sensor(session, sensor: Sensor | dict) -> Optional[models.Measurement]:
    """Upsert Device/Sensor from a PurpleAir sensor payload and insert/update a measurement.

    Uses pm2_5_atm when available, else pm2_5_cf_1. Observed time from last_seen.
    """
    if isinstance(sensor, dict):
        sid = sensor.get("sensor_index")
        name = sensor.get("name")
        lat = sensor.get("latitude") or sensor.get("lat")
        lon = sensor.get("longitude") or sensor.get("lon")
        last_seen = sensor.get("last_seen")
                                                                          
        v = sensor.get("pm2.5_atm") if sensor.get("pm2.5_atm") is not None else sensor.get("pm2_5_atm")
        if v is None:
            v = sensor.get("pm2.5_cf_1") if sensor.get("pm2.5_cf_1") is not None else sensor.get("pm2_5_cf_1")
    else:
        sid = sensor.sensor_index
        name = sensor.name
        lat = getattr(sensor, 'latitude', None) or getattr(sensor, 'lat', None)
        lon = getattr(sensor, 'longitude', None) or getattr(sensor, 'lon', None)
        last_seen = getattr(sensor, 'last_seen', None)
        v = getattr(sensor, 'pm2.5_atm', None) or getattr(sensor, 'pm2_5_atm', None) or getattr(sensor, 'pm2.5_cf_1', None) or getattr(sensor, 'pm2_5_cf_1', None)

    if sid is None:
        return None

                                                                        
    dev = _upsert_device_for_sensor(session, {"name": name} if name else {}, str(sid), external_api_name="PurpleAir")

                                                                                   
    obs_at = None
    try:
        if isinstance(last_seen, (int, float)):
            obs_at = datetime.fromtimestamp(float(last_seen), tz=timezone.utc)
        elif isinstance(last_seen, str):
                                                        
            s = last_seen.replace("Z", "+00:00")
            obs_at = datetime.fromisoformat(s)
            if obs_at.tzinfo is None:
                obs_at = obs_at.replace(tzinfo=timezone.utc)
    except Exception:
        obs_at = None

    try:
        if lat is not None or lon is not None:
            _update_device_location(session, dev, lat, lon, effective_from=obs_at)
    except Exception:
        pass

                                                
    pid, uid = _resolve_param_and_unit_ids(session)

    srec = _upsert_sensor_for_device(
        session,
        dev,
        "pm25",
        str(sid),
        parameter_id=pid,
        unit_id=uid,
        aggregation_period_id=None,
    )

                         
    value = None
    try:
        if v is not None:
            value = float(v)
    except Exception:
        value = None
    if value is None:
        return None

    m = models.Measurement(
        sensor_id=srec.sensor_id if srec else None,
        value=value,
        observed_at=obs_at,
    )
    upsert_measurement_with_policy(session, m, device=dev, sensor=srec)
    session.flush()
    return m
