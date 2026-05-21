from __future__ import annotations

"""Database-backed AQI helpers used by API routes."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    Sensor,
    Unit,
)
from services import aqi


@dataclass
class SensorMeta:
    sensor_id: int
    external_sensor_id: Optional[str]
    device_id: Optional[int]
    device_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    network: Optional[str]
    expected_interval_seconds: Optional[int]
    unit_symbol: Optional[str]


                                                                             
UG_PER_PPM = {
    "o3": 1963.0,                                                   
    "no2": 1880.0,         
    "so2": 2620.0,         
    "co": 1145.0,          
}


def _to_ppm(pollutant: str, value: float, unit_symbol: Optional[str]) -> float:
    p = pollutant.lower()
    unit = (unit_symbol or "").lower()
                                
    if p not in UG_PER_PPM:
        return value
    if "ppb" in unit:
        return value / 1000.0
    if "ppm" in unit:
        return value
    if "µg" in unit or "ug" in unit:
        factor = UG_PER_PPM.get(p)
        return value / factor if factor else value
    if "mg" in unit:
        factor = UG_PER_PPM.get(p)
        return (value * 1000.0) / factor if factor else value
                                                     
    return value


def _to_seconds(interval_str: Optional[str], fallback_minutes: Optional[int]) -> Optional[int]:
    """Convert HH:MM:SS to seconds; fall back to duration_minutes when present."""
    if interval_str:
        try:
            parts = interval_str.split(":")
            if len(parts) == 3:
                h, m, s = [int(float(p)) for p in parts]
                return h * 3600 + m * 60 + s
        except Exception:
            pass
    if fallback_minutes:
        try:
            return int(fallback_minutes) * 60
        except Exception:
            return None
    return None


def _normalize_dt(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fetch_candidate_sensors(
    session: Session,
    pollutant: str,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
) -> List[SensorMeta]:
    """Return sensors for the pollutant with device/network metadata."""
    stmt = (
        select(
            Sensor.sensor_id,
            Sensor.external_sensor_id,
            Device.device_id,
            Device.name,
            Device.latitude,
            Device.longitude,
            ExternalAPI.name.label("network"),
            AggregationPeriod.expected_interval,
            AggregationPeriod.duration_minutes,
            Unit.symbol.label("unit_symbol"),
        )
        .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
        .join(Device, Sensor.device_id == Device.device_id, isouter=True)
        .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
        .join(AggregationPeriod, AggregationPeriod.aggregation_period_id == Sensor.aggregation_period_id, isouter=True)
        .join(Unit, Unit.unit_id == Sensor.unit_id, isouter=True)
        .where(Parameter.code == pollutant)
    )
    normalized_external_api_name = (external_api_name or "").strip().lower() if external_api_name else None
    if device_id is not None:
        stmt = stmt.where(Device.device_id == device_id)
    if normalized_external_api_name:
        stmt = stmt.where(func.lower(ExternalAPI.name) == normalized_external_api_name)
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        stmt = stmt.where(Device.latitude != None, Device.longitude != None)              
        stmt = stmt.where(Device.latitude >= min_lat, Device.latitude <= max_lat)
        stmt = stmt.where(Device.longitude >= min_lon, Device.longitude <= max_lon)

    rows = session.execute(stmt).all()
    out: List[SensorMeta] = []
    for row in rows:
        expected_secs = _to_seconds(row.expected_interval, row.duration_minutes)
        out.append(
            SensorMeta(
                sensor_id=row.sensor_id,
                external_sensor_id=row.external_sensor_id,
                device_id=row.device_id,
                device_name=row.name,
                latitude=row.latitude,
                longitude=row.longitude,
                network=row.network,
                expected_interval_seconds=expected_secs,
                unit_symbol=row.unit_symbol,
            )
        )
    return out


def _fetch_hourly_buckets(
    session: Session,
    pollutant: str,
    sensor_ids: Sequence[int],
    start: datetime,
    end: datetime,
) -> Dict[int, List[Tuple[datetime, float, int]]]:
    """Return hourly bucket averages per sensor within [start, end]."""
    is_sqlite = False
    try:
        is_sqlite = session.bind and session.bind.dialect.name == "sqlite"
    except Exception:
        is_sqlite = False
    if is_sqlite:
                                                   
        stmt = (
            select(
                Measurement.sensor_id,
                Measurement.value,
                Measurement.observed_at,
            )
            .join(Sensor, Measurement.sensor_id == Sensor.sensor_id)
            .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
            .where(Parameter.code == pollutant)
            .where(Measurement.is_valid == True)              
            .where(Measurement.observed_at >= start)
            .where(Measurement.observed_at <= end)
        )
        if sensor_ids:
            stmt = stmt.where(Measurement.sensor_id.in_(list(sensor_ids)))

        rows = session.execute(stmt).all()
        tmp: Dict[Tuple[int, datetime], List[float]] = {}
        for sid, value, obs_at in rows:
            if obs_at is None:
                continue
            obs_norm = _normalize_dt(obs_at)
            bucket = obs_norm.replace(minute=0, second=0, microsecond=0)
            tmp.setdefault((sid, bucket), []).append(float(value))
        out: Dict[int, List[Tuple[datetime, float, int]]] = {}
        for (sid, bucket_dt), vals in tmp.items():
            avg_val = sum(vals) / len(vals) if vals else None
            out.setdefault(sid, []).append((bucket_dt, avg_val, len(vals)))
                                                        
        for sid in out:
            out[sid].sort(key=lambda it: it[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return out

    bucket_expr = func.date_trunc("hour", Measurement.observed_at).label("bucket")
    stmt = (
        select(
            Measurement.sensor_id,
            bucket_expr,
            func.avg(Measurement.value).label("avg_value"),
            func.count().label("count"),
        )
        .join(Sensor, Measurement.sensor_id == Sensor.sensor_id)
        .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
        .where(Parameter.code == pollutant)
        .where(Measurement.is_valid == True)              
        .where(Measurement.observed_at >= start)
        .where(Measurement.observed_at <= end)
        .group_by(Measurement.sensor_id, bucket_expr)
        .order_by(bucket_expr.desc())
    )
    if sensor_ids:
        stmt = stmt.where(Measurement.sensor_id.in_(list(sensor_ids)))

    rows = session.execute(stmt).all()
    out: Dict[int, List[Tuple[datetime, float, int]]] = {}
    for sid, bucket, avg_val, count in rows:
        bucket_dt = bucket
        if isinstance(bucket_dt, str):
            try:
                bucket_dt = datetime.fromisoformat(bucket_dt)
                if bucket_dt.tzinfo is None:
                    bucket_dt = bucket_dt.replace(tzinfo=timezone.utc)
            except Exception:
                bucket_dt = None
        out.setdefault(sid, []).append((bucket_dt, float(avg_val) if avg_val is not None else None, count))
    return out


def _min_samples_per_hour(expected_interval_seconds: Optional[int]) -> int:
                                                                                         
    return 0


def compute_latest_aqi(
    session: Session,
    pollutant: str,
    time_resolution: str,
    *,
    end_time: Optional[datetime] = None,
    since: Optional[datetime] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[dict]:
    """Compute AQI values per sensor for the requested pollutant/timeResolution."""
    p = aqi.normalize_pollutant(pollutant)
    tr = aqi.normalize_time_resolution(time_resolution)
    aqi.validate_combination(p, tr)

    meta = aqi.time_resolution_meta(tr)
    window_hours = int(meta.get("window_hours") or 0)
    if window_hours <= 0:
        raise ValueError(f"Invalid window hours for AQI {tr}")

    end_utc = _normalize_dt(end_time)
    start_utc = end_utc - timedelta(hours=window_hours)
    if since:
        since_utc = _normalize_dt(since)
        if since_utc > start_utc:
            start_utc = since_utc

    sensors = _fetch_candidate_sensors(
        session, p, bbox=bbox, device_id=device_id, external_api_name=external_api_name
    )
    if not sensors:
        return []

    sid_list = [s.sensor_id for s in sensors]
    hourly = _fetch_hourly_buckets(session, p, sid_list, start_utc, end_utc)

    results: List[dict] = []
    for s in sensors:
        buckets = hourly.get(s.sensor_id, [])
        if not buckets:
            continue

        min_samples = _min_samples_per_hour(s.expected_interval_seconds)
        hourly_values: List[float] = []
        for bucket_dt, avg_val, count in buckets:
            if avg_val is None:
                continue
            if count is not None and count < min_samples:
                continue
            hourly_values.append(_to_ppm(p, float(avg_val), s.unit_symbol))
        if not hourly_values:
            continue

        aqi_value: Optional[int] = None
        obs_time = end_utc
        if tr == "aqi-nowcast":
            aqi_value = aqi.compute_pm25_nowcast_aqi(hourly_values)
        elif tr in {"aqi-24h", "aqi-8h"}:
            aqi_value = aqi.compute_aqi_from_window(
                p,
                tr,
                hourly_values[:window_hours],
                expected_count=window_hours,
                min_fraction=0.75,
            )
        elif tr == "aqi-1h":
                                                          
            aqi_value = aqi.compute_aqi_for_concentration(p, tr, hourly_values[0])
                                                                                
            if buckets and buckets[0][0]:
                obs_time = _normalize_dt(buckets[0][0])
        else:
                                                     
            continue

        if aqi_value is None:
            continue

        device_payload = (
            {
                "device_id": s.device_id,
                "name": s.device_name,
                "latitude": s.latitude,
                "longitude": s.longitude,
                "network": s.network,
                "external_api": ({"name": s.network} if s.network is not None else None),
            }
            if s.device_id is not None
            else None
        )

        results.append(
            {
                "measurement_id": 0,
                "sensor_id": s.sensor_id,
                "external_sensor_id": s.external_sensor_id,
                "parameter": p,
                "value": aqi_value,
                "unit": "AQI",
                "observed_at": obs_time.isoformat(),
                "device": device_payload,
            }
        )

                                                        
    results.sort(key=lambda r: r.get("observed_at") or "", reverse=True)
    if limit:
        results = results[:limit]
    return results
