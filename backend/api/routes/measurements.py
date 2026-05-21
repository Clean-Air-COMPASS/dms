from __future__ import annotations

from typing import Optional, List, Tuple, Dict, Set
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, literal_column
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session, aliased

from db import get_session
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    ParameterAggregationRule,
    ParameterAggregationRollup,
    Sensor,
    Unit,
)
from sqlalchemy import exists
from utils.aggregations import get_pm25_rolling_24h_avg, get_pm25_daily_24h_avg
from services import aqi as aqi_service
from services import aqi_engine
from utils.parameter_aggregation_rule_formatting import (
    ParameterAggregationRuleFormatting,
    apply_parameter_aggregation_rule,
    load_parameter_aggregation_rules,
    resolve_parameter_aggregation_rule,
)

                       
                                                                             
                                                                               
                                                                 
                                                                            
                                                       

router = APIRouter()
                                                                                  
BUCKET_SECONDS = {
    "1m": 60,
    "1h": 3600,
    "8h": 8 * 3600,
    "24h": 24 * 3600,
}
MANUAL_SOURCE_LABEL = "Other"


def _normalize_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_bbox(bbox: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    if bbox is None:
        return None
    parts = (bbox or "").split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must be min_lon,min_lat,max_lon,max_lat")
    try:
        coords = tuple(float(p.strip()) for p in parts)
    except Exception:
        raise HTTPException(status_code=400, detail="bbox values must be numeric")
    min_lon, min_lat, max_lon, max_lat = coords
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="bbox bounds are invalid (min must be < max)")
    return min_lon, min_lat, max_lon, max_lat


def _seconds_from_interval(expected_interval: Optional[str], duration_minutes: Optional[int]) -> Optional[int]:
    """Return cadence in seconds from HH:MM:SS or duration_minutes; fallback to None."""
    if expected_interval:
        try:
            parts = expected_interval.split(":")
            if len(parts) == 3:
                h, m, s = [int(float(p)) for p in parts]
                return h * 3600 + m * 60 + s
        except Exception:
            pass
    if duration_minutes:
        try:
            return int(duration_minutes) * 60
        except Exception:
            return None
    return None


def _resolve_public_source_name(
    manual_data_source_name: Optional[str], external_api_name: Optional[str]
) -> Optional[str]:
    if manual_data_source_name:
        return MANUAL_SOURCE_LABEL
    return external_api_name


def _is_other_source_filter(external_api_name: Optional[str]) -> bool:
    return (external_api_name or "").strip().lower() == MANUAL_SOURCE_LABEL.lower()


def _apply_public_source_filter(stmt, normalized_external_api_name: Optional[str]):
    if not normalized_external_api_name:
        return stmt
    if _is_other_source_filter(normalized_external_api_name):
        return stmt.where(Device.manual_data_source_name.is_not(None))
    return stmt.where(func.lower(ExternalAPI.name) == normalized_external_api_name)

class DeviceOut(BaseModel):
    device_id: Optional[int]
    name: Optional[str]
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    network: Optional[str] = None
    timezone: Optional[str] = None
    external_api: Optional[dict] = None


class MeasurementOut(BaseModel):
    """Shared response shape for concentration and AQI values (unit may be 'AQI')."""

    measurement_id: int
    sensor_id: Optional[int]
    external_sensor_id: Optional[str] = None
    parameter: str
    value: float
    unit: Optional[str]
    observed_at: Optional[str]
    sensor_aggregation_period: Optional[str] = None
    device: Optional[DeviceOut]

                                                                    
    model_config = {"from_attributes": True}


class ParameterOut(BaseModel):
    code: str
    display_name: str
    unit_symbol: Optional[str] = None


class ParameterAggregationRuleOut(BaseModel):
    parameter_code: str
    aggregation_code: str
    rounding_method: Optional[str] = None
    rounding_precision: Optional[int] = None
    truncation_method: Optional[str] = None
    truncation_precision: Optional[int] = None


@router.get("/parameters", response_model=List[ParameterOut])
def list_parameters(session: Session = Depends(get_session)):
    """List known parameters and their default unit symbol.

    This powers the frontend selector for /measurements/{parameter}/latest.
    """
    try:
        stmt = (
            sa_select(Parameter.code, Parameter.display_name, Unit.symbol.label("unit_symbol"))
            .join(Unit, Parameter.default_unit_id == Unit.unit_id)
            .order_by(Parameter.display_name.asc())
        )
        rows = session.execute(stmt).all()
        return [
            ParameterOut(code=r[0], display_name=r[1], unit_symbol=r[2]) for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/parameter_aggregation_rules", response_model=List[ParameterAggregationRuleOut])
def list_parameter_aggregation_rules(session: Session = Depends(get_session)):
    """Expose active rounding/truncation rules per parameter & aggregation period."""

    try:
        stmt = (
            sa_select(
                Parameter.code.label("parameter_code"),
                AggregationPeriod.code.label("aggregation_code"),
                ParameterAggregationRule.rounding_method,
                ParameterAggregationRule.rounding_precision,
                ParameterAggregationRule.truncation_method,
                ParameterAggregationRule.truncation_precision,
            )
            .join(Parameter, Parameter.parameter_id == ParameterAggregationRule.parameter_id)
            .join(
                AggregationPeriod,
                AggregationPeriod.aggregation_period_id
                == ParameterAggregationRule.aggregation_period_id,
            )
            .where(ParameterAggregationRule.active == True)              
        )
        rows = session.execute(stmt).all()
        return [
            ParameterAggregationRuleOut(
                parameter_code=row[0],
                aggregation_code=row[1],
                rounding_method=row[2],
                rounding_precision=row[3],
                truncation_method=row[4],
                truncation_precision=row[5],
            )
            for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aggregation_periods")
def list_aggregation_periods(session: Session = Depends(get_session)):
    """List available aggregation/time resolution periods from the database."""
    try:
        stmt = sa_select(AggregationPeriod.code, AggregationPeriod.display_name).order_by(AggregationPeriod.duration_minutes.asc().nulls_last())
        rows = session.execute(stmt).all()
        return [{"code": r[0], "display_name": r[1]} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aggregation_rollups")
def list_aggregation_rollups(
    parameter: Optional[str] = Query(None, description="Filter by parameter code (e.g., 'pm25', 'o3'). If omitted, returns all rollup configurations."),
    from_period: Optional[str] = Query(None, description="Filter by source aggregation period code (e.g., '1h'). Useful to find valid target periods for a sensor's native resolution."),
    session: Session = Depends(get_session),
):
    """List valid aggregation rollup paths from parameter_aggregation_rollup table.
    
    Returns the allowed aggregation rollup configurations that define valid transitions
    from a sensor's native time resolution to a displayed aggregation period.
    
    For example, a sensor with native '1h' resolution may roll up to '24h' if a
    corresponding rollup entry exists for that parameter.
    
    Query parameters:
    - parameter: Filter by parameter code (e.g., 'pm25')
    - from_period: Filter by source aggregation period code (sensor's native resolution)
    
    Response shape:
    [
      {
        "parameter_code": "pm25",
        "from_period_code": "1h",
        "from_period_display": "Hourly",
        "to_period_code": "24h",
        "to_period_display": "Daily"
      },
      ...
    ]
    """
    try:
        from_ap = aliased(AggregationPeriod, name="from_ap")
        to_ap = aliased(AggregationPeriod, name="to_ap")
        
        stmt = (
            sa_select(
                Parameter.code.label("parameter_code"),
                from_ap.code.label("from_period_code"),
                from_ap.display_name.label("from_period_display"),
                to_ap.code.label("to_period_code"),
                to_ap.display_name.label("to_period_display"),
            )
            .select_from(ParameterAggregationRollup)
            .join(Parameter, Parameter.parameter_id == ParameterAggregationRollup.parameter_id)
            .join(from_ap, from_ap.aggregation_period_id == ParameterAggregationRollup.from_aggregation_period_id)
            .join(to_ap, to_ap.aggregation_period_id == ParameterAggregationRollup.to_aggregation_period_id)
            .order_by(Parameter.code, from_ap.duration_minutes.asc().nulls_last(), to_ap.duration_minutes.asc().nulls_last())
        )
        
        if parameter:
            stmt = stmt.where(func.lower(Parameter.code) == parameter.lower())
        if from_period:
            stmt = stmt.where(func.lower(from_ap.code) == from_period.lower())
        
        rows = session.execute(stmt).all()
        return [
            {
                "parameter_code": row.parameter_code,
                "from_period_code": row.from_period_code,
                "from_period_display": row.from_period_display,
                "to_period_code": row.to_period_code,
                "to_period_display": row.to_period_display,
            }
            for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{device_id}/pm25/rolling_24h")
def pm25_rolling_24h_average(
    device_id: int,
    end_time: Optional[datetime] = Query(
        None,
        description="End of the 24h window (UTC). If omitted, uses current time.",
    ),
    min_hours: Optional[int] = Query(None, description="Minimum per-sensor hours required to include sensor in the aggregate (overrides PM25_MIN_HOURS env)") ,
    session: Session = Depends(get_session),
):
    try:
        avg_val = get_pm25_rolling_24h_avg(session, device_id, end_time, min_hours=min_hours)
        return {"device_id": device_id, "pm25_rolling_24h": avg_val}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{device_id}/pm25/daily_24h")
def pm25_daily_24h_average(
    device_id: int,
    local_date: date = Query(
        ..., description="Local calendar date in the device timezone (YYYY-MM-DD)."
    ),
    min_hours: Optional[int] = Query(None, description="Minimum per-sensor hours required to include sensor in the aggregate (overrides PM25_MIN_HOURS env)"),
    session: Session = Depends(get_session),
):
    try:
        avg_val = get_pm25_daily_24h_avg(
            session, device_id, datetime.combine(local_date, datetime.min.time()), min_hours=min_hours
        )
        if avg_val is None:
            device = session.get(Device, device_id)
            if device is None:
                raise HTTPException(status_code=404, detail="Device not found")
            if not getattr(device, "timezone", None):
                raise HTTPException(
                    status_code=422,
                    detail="Device timezone not configured; cannot compute local daily average.",
                )
        return {
            "device_id": device_id,
            "local_date": local_date.isoformat(),
            "pm25_daily_24h": avg_val,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/measurements/{parameter}/latest", response_model=List[MeasurementOut])
def latest_by_parameter(
    parameter: str,
    limit: int = Query(100, ge=1, le=1000),
    since: Optional[datetime] = Query(
        None,
        description="ISO8601 UTC. If provided, returns all rows with observed_at >= since and ignores 'limit'.",
    ),
    until: Optional[datetime] = Query(
        None,
        description="ISO8601 UTC upper bound. If provided, limits values to observed_at <= until.",
    ),
    aggregation: Optional[str] = Query(
        None,
        description="Aggregation period code to restrict sensors to those that support the aggregation (e.g., '1h','8h','24h').",
    ),
    bbox: Optional[str] = Query(
        None,
        description="Optional bounding box filter (min_lon,min_lat,max_lon,max_lat) applied to device coordinates.",
    ),
    device_id: Optional[int] = Query(
        None,
        description="Optional device filter. When provided, limits results to the device.",
    ),
    external_api_name: Optional[str] = Query(
        None,
        description="Optional filter by ExternalAPI.name (e.g., 'openaq', 'purpleair', 'airgradient').",
    ),
    session: Session = Depends(get_session),
):
    """Return latest measurements for a given parameter code.

    Mirrors the pm25 endpoint but supports any canonical Parameter.code.
    Optional 'since' parameter filters by observed_at >= since (UTC) and disables the limit.
    """
    try:
        pcode = (parameter or "").lower()

                                                 
        cutoff: Optional[datetime] = _normalize_utc(since)
        until_cutoff: Optional[datetime] = _normalize_utc(until)

        bbox_tuple: Optional[Tuple[float, float, float, float]] = None
        if bbox:
            bbox_tuple = _parse_bbox(bbox)

                                                                 
        agg_code = (aggregation or "").lower() if aggregation else None
        normalized_external_api_name = (external_api_name or "").strip().lower() if external_api_name else None

        if agg_code in aqi_service.AQI_TIME_RESOLUTIONS:
            try:
                results = aqi_engine.compute_latest_aqi(
                    session,
                    pcode,
                    agg_code,
                    end_time=until_cutoff,
                    since=cutoff,
                    bbox=bbox_tuple,
                    device_id=device_id,
                    external_api_name=normalized_external_api_name,
                    limit=None if cutoff else limit,
                )
                                                                                            
                rules_by_aggregation_code = load_parameter_aggregation_rules(session, pcode, {"aqi"})
                rule = rules_by_aggregation_code.get("aqi")
                if rule:
                    for row in results:
                        row["value"] = apply_parameter_aggregation_rule(
                            row.get("value"),
                            rule.rounding_method,
                            rule.rounding_precision,
                            rule.truncation_method,
                            rule.truncation_precision,
                        )
                return results
            except HTTPException:
                raise
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        if pcode == "pm25" and agg_code in {"24h_rolling", "24h_daily"}:
                                        
            unit_symbol_row = (
                session.execute(
                    sa_select(Unit.symbol)
                    .join(Parameter, Parameter.default_unit_id == Unit.unit_id)
                    .where(Parameter.code == "pm25")
                ).first()
            )
            unit_symbol = unit_symbol_row[0] if unit_symbol_row else None

                                                          
            dev_stmt = (
                sa_select(
                    Device.device_id,
                    Device.name,
                    Device.latitude,
                    Device.longitude,
                    Device.timezone,
                    Device.manual_data_source_name,
                    ExternalAPI.name.label("network"),
                )
                .join(Sensor, Sensor.device_id == Device.device_id)
                .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
                .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
                .where(Parameter.code == "pm25")
                .distinct()
            )
            dev_stmt = _apply_public_source_filter(dev_stmt, normalized_external_api_name)
            dev_rows = session.execute(dev_stmt).all()

            out: List[dict] = []
            rules_for_pm25_24h: Dict[str, ParameterAggregationRuleFormatting] = load_parameter_aggregation_rules(
                session, pcode, {"24h"}
            )
            pm25_24h_rule = resolve_parameter_aggregation_rule(rules_for_pm25_24h, "24h")

            now_utc = datetime.now(timezone.utc)
            for d_id, d_name, d_lat, d_lon, d_tz, d_manual_source_name, d_network in dev_rows:
                resolved_source_name = _resolve_public_source_name(d_manual_source_name, d_network)
                avg_val: Optional[float] = None
                obs_at: Optional[str] = None
                if agg_code == "24h_rolling":
                    avg_val = get_pm25_rolling_24h_avg(session, d_id, now_utc)
                    obs_at = now_utc.isoformat()
                else:             
                    if not d_tz:
                        continue                                 
                    local_today = datetime.now(ZoneInfo(d_tz)).date()
                    avg_val = get_pm25_daily_24h_avg(session, d_id, datetime.combine(local_today, datetime.min.time()))
                                                                                           
                    obs_at = datetime.combine(local_today, datetime.min.time()).isoformat()

                if avg_val is None:
                    continue
                if pm25_24h_rule:
                    avg_val = apply_parameter_aggregation_rule(
                        avg_val,
                        pm25_24h_rule.rounding_method,
                        pm25_24h_rule.rounding_precision,
                        pm25_24h_rule.truncation_method,
                        pm25_24h_rule.truncation_precision,
                    )

                out.append(
                    {
                        "measurement_id": 0,
                        "sensor_id": None,
                        "external_sensor_id": None,
                        "parameter": "pm25",
                        "value": avg_val,
                        "unit": unit_symbol,
                        "observed_at": obs_at,
                        "device": {
                            "device_id": d_id,
                            "name": d_name,
                            "latitude": d_lat,
                            "longitude": d_lon,
                            "network": resolved_source_name,
                            "external_api": ({"name": resolved_source_name} if resolved_source_name is not None else None),
                        },
                    }
                )

            return out

                                                                                  
                                                                                      
                                                                                
        if agg_code and agg_code in BUCKET_SECONDS:
            bucket_seconds = BUCKET_SECONDS[agg_code]
            dialect_name = None
            try:
                if session.bind is not None:
                    dialect_name = session.bind.dialect.name
            except Exception:
                dialect_name = None
            bucket_expr = _bucket_start_expr(bucket_seconds, dialect=dialect_name)
            stmt = (
                sa_select(
                    Measurement.sensor_id,
                    func.avg(Measurement.value).label("value_avg"),
                    bucket_expr.label("bucket_start"),
                    Unit.symbol.label("unit_symbol"),
                    Device.device_id,
                    Device.name,
                    Device.latitude,
                    Device.longitude,
                    Sensor.external_sensor_id,
                    AggregationPeriod.expected_interval,
                    AggregationPeriod.duration_minutes,
                    AggregationPeriod.code.label("sensor_aggregation_code"),
                    func.count(Measurement.measurement_id).label("sample_count"),
                )
                .join(Sensor, Sensor.sensor_id == Measurement.sensor_id)
                .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
                .join(Unit, Unit.unit_id == Sensor.unit_id, isouter=True)
                .join(Device, Device.device_id == Sensor.device_id, isouter=True)
                .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
                .join(AggregationPeriod, AggregationPeriod.aggregation_period_id == Sensor.aggregation_period_id, isouter=True)
                .where(Parameter.code == pcode)
                .where(Measurement.is_valid == True)
            )

            if cutoff is not None:
                stmt = stmt.where(Measurement.observed_at >= cutoff)
            if until_cutoff is not None:
                stmt = stmt.where(Measurement.observed_at <= until_cutoff)
            if device_id is not None:
                stmt = stmt.where(Device.device_id == device_id)
            stmt = _apply_public_source_filter(stmt, normalized_external_api_name)
            if bbox_tuple:
                min_lon, min_lat, max_lon, max_lat = bbox_tuple
                stmt = stmt.where(Device.latitude != None, Device.longitude != None)              
                stmt = stmt.where(Device.latitude >= min_lat, Device.latitude <= max_lat)
                stmt = stmt.where(Device.longitude >= min_lon, Device.longitude <= max_lon)

            stmt = stmt.group_by(
                Measurement.sensor_id,
                bucket_expr,
                Unit.symbol,
                Device.device_id,
                Device.name,
                Device.latitude,
                Device.longitude,
                Sensor.external_sensor_id,
                AggregationPeriod.expected_interval,
                AggregationPeriod.duration_minutes,
                AggregationPeriod.code,
            )
            rows = session.execute(stmt).all()

            rules_by_aggregation_code: Dict[str, ParameterAggregationRuleFormatting] = load_parameter_aggregation_rules(
                session, pcode, {agg_code}
            )

            def _format_value_for_aggregation(raw_value: Optional[float]) -> Optional[float]:
                rule = resolve_parameter_aggregation_rule(rules_by_aggregation_code, agg_code)
                if not rule:
                    return raw_value
                return apply_parameter_aggregation_rule(
                    raw_value,
                    rule.rounding_method,
                    rule.rounding_precision,
                    rule.truncation_method,
                    rule.truncation_precision,
                )

            def _normalize_bucket_start(bucket_start_value: object) -> Optional[datetime]:
                normalized_value = bucket_start_value
                if isinstance(normalized_value, str):
                    try:
                        parsed = datetime.fromisoformat(normalized_value)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        normalized_value = parsed
                    except Exception:
                        normalized_value = None
                return normalized_value

                                                                             
                                                                                
            device_ids = {r.device_id for r in rows if getattr(r, 'device_id', None) is not None}
            device_info_map: dict = {}
            if device_ids:
                try:
                    net_rows = session.execute(
                        sa_select(
                            Device.device_id,
                            Device.manual_data_source_name,
                            ExternalAPI.name,
                            Device.timezone,
                        )
                        .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
                        .where(Device.device_id.in_(list(device_ids)))
                    ).all()
                    for did, manual_source_name, net, tz in net_rows:
                        device_info_map[did] = {
                            "network": _resolve_public_source_name(manual_source_name, net),
                            "timezone": tz,
                        }
                except Exception:
                    device_info_map = {}

            latest_by_sensor: dict[int, dict] = {}
            for row in rows:
                sid = row.sensor_id
                                                                                              
                bucket_start = _normalize_bucket_start(row.bucket_start)
                existing = latest_by_sensor.get(sid)
                if existing:
                    prev_ts = existing.get("_ts") or float("-inf")
                    cur_ts = bucket_start.timestamp() if bucket_start else float("-inf")
                    if cur_ts <= prev_ts:
                        continue
                                                                               
                device_info = device_info_map.get(row.device_id, {}) if row.device_id is not None else {}
                resolved_network = device_info.get("network") if device_info else None
                resolved_timezone = device_info.get("timezone") if device_info else None

                raw_value = float(row.value_avg) if row.value_avg is not None else None
                formatted_value = _format_value_for_aggregation(raw_value)

                latest_by_sensor[sid] = {
                    "_ts": bucket_start.timestamp() if bucket_start else None,
                    "measurement_id": 0,
                    "sensor_id": sid,
                    "external_sensor_id": row.external_sensor_id,
                    "parameter": pcode,
                    "value": formatted_value,
                    "unit": row.unit_symbol,
                    "observed_at": bucket_start.isoformat() if bucket_start else None,
                    "sensor_aggregation_period": getattr(row, "sensor_aggregation_code", None),
                    "device": (
                        {
                            "device_id": row.device_id,
                            "name": row.name,
                            "latitude": row.latitude,
                            "longitude": row.longitude,
                            "network": resolved_network,
                            "timezone": resolved_timezone,
                            "external_api": ({"name": resolved_network} if resolved_network is not None else None),
                        }
                        if row.device_id is not None
                        else None
                    ),
                }

            return list(latest_by_sensor.values())

        rn = func.row_number().over(
            partition_by=Measurement.sensor_id,
            order_by=(Measurement.observed_at.desc(), Measurement.measurement_id.desc()),
        )

        sensor_ap = aliased(AggregationPeriod, name="sensor_ap")

        base_select = (
            sa_select(
                Measurement.measurement_id.label("measurement_id"),
                Measurement.sensor_id.label("sensor_id"),
                Measurement.value.label("value"),
                Measurement.observed_at.label("observed_at"),
                Sensor.device_id.label("device_id"),
                Sensor.external_sensor_id.label("external_sensor_id"),
                Parameter.code.label("m_param_code"),
                Parameter.parameter_id.label("param_id"),
                Unit.symbol.label("m_unit_symbol"),
                rn.label("rn"),
                sensor_ap.code.label("sensor_aggregation_code"),
            )
            .join(Sensor, Measurement.sensor_id == Sensor.sensor_id)
            .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
            .outerjoin(Unit, Sensor.unit_id == Unit.unit_id)
            .outerjoin(sensor_ap, sensor_ap.aggregation_period_id == Sensor.aggregation_period_id)
            .where(Parameter.code == pcode)
            .where(Measurement.is_valid == True)
        )

        agg_code_normalized: Optional[str] = None
        if aggregation:
            agg_code_normalized = (aggregation or "").lower()
                                                                                                                          
            par_rule_exists = (
                sa_select(ParameterAggregationRule.parameter_aggregation_rule_id)
                .join(
                    AggregationPeriod,
                    ParameterAggregationRule.aggregation_period_id == AggregationPeriod.aggregation_period_id,
                )
                .where(ParameterAggregationRule.parameter_id == Parameter.parameter_id)
                .where(AggregationPeriod.code == agg_code_normalized)
                .limit(1)
                .exists()
            )
            base_select = base_select.where(or_(sensor_ap.code == agg_code_normalized, par_rule_exists))

        base = base_select.subquery("latest_per_sensor")

        stmt = (
            sa_select(
                base.c.measurement_id,
                base.c.sensor_id,
                base.c.m_param_code,
                base.c.value,
                base.c.m_unit_symbol,
                base.c.observed_at,
                Device.device_id,
                Device.name,
                Device.latitude,
                Device.longitude,
                base.c.external_sensor_id,
                base.c.sensor_aggregation_code,
                Device.manual_data_source_name,
                ExternalAPI.name.label("network"),
            )
            .join(Device, Device.device_id == base.c.device_id, isouter=True)
            .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
            .where(base.c.rn == 1)
        )

        if cutoff is not None:
            stmt = stmt.where(base.c.observed_at >= cutoff)
        if until_cutoff is not None:
            stmt = stmt.where(base.c.observed_at <= until_cutoff)
        if device_id is not None:
            stmt = stmt.where(Device.device_id == device_id)
        stmt = _apply_public_source_filter(stmt, normalized_external_api_name)
        if bbox_tuple:
            min_lon, min_lat, max_lon, max_lat = bbox_tuple
            stmt = stmt.where(Device.latitude != None, Device.longitude != None)              
            stmt = stmt.where(Device.latitude >= min_lat, Device.latitude <= max_lat)
            stmt = stmt.where(Device.longitude >= min_lon, Device.longitude <= max_lon)

                                                                                      
                                                                                       
                                                                  
                                                                                  

        stmt = stmt.order_by(base.c.observed_at.desc())

        if cutoff is None:
            stmt = stmt.limit(limit)

        rows = session.execute(stmt).all()
        out: List[dict] = []

        aggregation_codes_in_results: Set[str] = {
            (getattr(row, "sensor_aggregation_code", None) or "").lower()
            for row in rows
            if getattr(row, "sensor_aggregation_code", None)
        }
        rules_by_aggregation_code: Dict[str, ParameterAggregationRuleFormatting] = load_parameter_aggregation_rules(
            session, pcode, aggregation_codes_in_results
        )

        def _format_value_for_sensor(
            raw_value: Optional[float], aggregation_code_for_value: Optional[str]
        ) -> Optional[float]:
            rule = resolve_parameter_aggregation_rule(
                rules_by_aggregation_code, aggregation_code_for_value
            )
            if not rule:
                return raw_value
            return apply_parameter_aggregation_rule(
                raw_value,
                rule.rounding_method,
                rule.rounding_precision,
                rule.truncation_method,
                rule.truncation_precision,
            )

                                                                                       
        device_ids = {row.device_id for row in rows if row.device_id is not None}
        device_info_map: dict = {}
        if device_ids:
            try:
                net_rows = session.execute(
                    sa_select(
                        Device.device_id,
                        Device.manual_data_source_name,
                        ExternalAPI.name,
                        Device.timezone,
                    )
                    .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
                    .where(Device.device_id.in_(list(device_ids)))
                ).all()
                for did, manual_source_name, net, tz in net_rows:
                    device_info_map[did] = {
                        "network": _resolve_public_source_name(manual_source_name, net),
                        "timezone": tz,
                    }
            except Exception:
                device_info_map = {}

        for row in rows:
            device_info = device_info_map.get(row.device_id, {}) if row.device_id is not None else {}
            device_network = device_info.get("network") if device_info else None
            device_timezone = device_info.get("timezone") if device_info else None
            fallback_network = _resolve_public_source_name(
                row.manual_data_source_name,
                row.network,
            )
            formatted_value = _format_value_for_sensor(row.value, getattr(row, "sensor_aggregation_code", None))
            sensor_aggregation_code = getattr(row, "sensor_aggregation_code", None)
            out.append(
                {
                    "measurement_id": row.measurement_id,
                    "sensor_id": row.sensor_id,
                    "external_sensor_id": row.external_sensor_id,
                    "parameter": row.m_param_code or "",
                    "value": formatted_value,
                    "unit": row.m_unit_symbol,
                    "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                    "sensor_aggregation_period": sensor_aggregation_code,
                    "device": (
                        {
                            "device_id": row.device_id,
                            "name": row.name,
                            "latitude": row.latitude,
                            "longitude": row.longitude,
                            "network": device_network or fallback_network,
                            "timezone": device_timezone,
                            "external_api": (
                                {"name": (device_network or fallback_network)}
                                if (device_network or fallback_network) is not None
                                else None
                            ),
                        }
                        if row.device_id is not None
                        else None
                    ),
                }
            )

        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _bucket_start_expr(bucket_seconds: int, dialect: Optional[str] = None):
    """Return an expression to truncate observed_at to bucket start (UTC).

    Uses dialect-aware SQL so tests can run on SQLite while production uses Postgres.
    """
    if dialect and dialect.lower() == "sqlite":
        return func.datetime(
            func.floor(func.strftime("%s", Measurement.observed_at) / literal_column(str(bucket_seconds)))
            * literal_column(str(bucket_seconds)),
            literal_column("'unixepoch'"),
        )
                                                                                                          
    return func.to_timestamp(
        func.floor(func.extract("epoch", Measurement.observed_at) / literal_column(str(bucket_seconds)))
        * literal_column(str(bucket_seconds))
    )


@router.get("/measurements/{parameter}/aggregate")
def aggregate_measurements(
    parameter: str,
    source_agg: str = Query(..., alias="from"),
    target_agg: str = Query(..., alias="to"),
    since: Optional[datetime] = Query(None, description="ISO8601 UTC lower bound"),
    until: Optional[datetime] = Query(None, description="ISO8601 UTC upper bound"),
    external_api_name: Optional[str] = Query(
        None,
        description="Optional filter by ExternalAPI.name (e.g., 'openaq', 'purpleair', 'airgradient').",
    ),
    session: Session = Depends(get_session),
):
    """Aggregate measurements from a lower aggregation to a higher one (e.g., 1m -> 1h).

    Only allowed combinations are served (see ALLOWED_AGG_ROLLUPS).
    Aggregation is grouped per sensor_id per bucket start; returns average value and bucket start as observed_at.
    """
    pcode = (parameter or "").lower()
    src = (source_agg or "").lower()
    dst = (target_agg or "").lower()
    normalized_external_api_name = (external_api_name or "").strip().lower() if external_api_name else None

    try:
        ap_from = aliased(AggregationPeriod, name="ap_from")
        ap_to = aliased(AggregationPeriod, name="ap_to")
        rollup_stmt = (
            sa_select(
                ap_from.code.label("from_code"),
                ap_to.code.label("to_code"),
            )
            .select_from(ParameterAggregationRollup)
            .join(Parameter, Parameter.parameter_id == ParameterAggregationRollup.parameter_id)
            .join(ap_from, ap_from.aggregation_period_id == ParameterAggregationRollup.from_aggregation_period_id)
            .join(ap_to, ap_to.aggregation_period_id == ParameterAggregationRollup.to_aggregation_period_id)
            .where(Parameter.code == pcode)
        )
        allowed_pairs = {
            (row.from_code.lower(), row.to_code.lower()) for row in session.execute(rollup_stmt).all()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if (src, dst) not in allowed_pairs:
        raise HTTPException(status_code=400, detail=f"Aggregation from {src} to {dst} not allowed for {pcode}")

                                                                                  
    if dst == "rolling_24h":
        end_time = until if until else datetime.now(timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        start_time = end_time - timedelta(hours=24)
        if since:
            since_ts = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
            start_time = max(start_time, since_ts)

        src_seconds = BUCKET_SECONDS.get(src)
        if not src_seconds:
            raise HTTPException(status_code=400, detail=f"Unsupported source aggregation {src} for rolling_24h")
                                                                                        

        stmt = (
            sa_select(
                Measurement.sensor_id,
                func.avg(Measurement.value).label("value_avg"),
                literal_column("NULL").label("bucket_start"),
                Unit.symbol.label("unit_symbol"),
                Device.device_id,
                Device.name,
                Device.latitude,
                Device.longitude,
            )
            .join(Sensor, Sensor.sensor_id == Measurement.sensor_id)
            .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
            .join(Unit, Unit.unit_id == Sensor.unit_id, isouter=True)
            .join(Device, Device.device_id == Sensor.device_id, isouter=True)
            .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
            .where(Parameter.code == pcode)
            .where(Measurement.is_valid == True)
            .where(Measurement.observed_at >= start_time)
            .where(Measurement.observed_at <= end_time)
            .group_by(
                Measurement.sensor_id,
                Unit.symbol,
                Device.device_id,
                Device.name,
                Device.latitude,
                Device.longitude,
            )
            .order_by(Measurement.sensor_id)
        )
        stmt = _apply_public_source_filter(stmt, normalized_external_api_name)

        rows = session.execute(stmt).all()

                                                                  
        device_ids_in_rows = {r[4] for r in rows if r[4] is not None}                        
        device_network_map: dict[int, str | None] = {}
        if device_ids_in_rows:
            network_rows = session.execute(
                sa_select(Device.device_id, Device.manual_data_source_name, ExternalAPI.name)
                .outerjoin(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id)
                .where(Device.device_id.in_(device_ids_in_rows))
            ).all()
            for did, manual_source_name, net_name in network_rows:
                device_network_map[did] = _resolve_public_source_name(manual_source_name, net_name)

        out = []
        for sensor_id, avg_val, _, unit_symbol, dev_id, dev_name, dev_lat, dev_lon in rows:
            ext_api_obj = None
            if dev_id is not None:
                network_name = device_network_map.get(dev_id)
                if network_name is not None:
                    ext_api_obj = {"name": network_name}
            out.append(
                {
                    "sensor_id": sensor_id,
                    "parameter": pcode,
                    "value": float(avg_val) if avg_val is not None else None,
                    "unit": unit_symbol,
                    "observed_at": end_time.isoformat(),
                    "device": {
                        "device_id": dev_id,
                        "name": dev_name,
                        "latitude": dev_lat,
                        "longitude": dev_lon,
                        "external_api": ext_api_obj,
                    }
                    if dev_id is not None
                    else None,
                }
            )
        return out

                                                                      
    if dst not in BUCKET_SECONDS:
        raise HTTPException(status_code=400, detail=f"Aggregation target {dst} not supported")

    bucket_seconds = BUCKET_SECONDS[dst]
    src_seconds = BUCKET_SECONDS.get(src)
    if not src_seconds:
        raise HTTPException(status_code=400, detail=f"Aggregation source {src} not supported")
    expected_samples = bucket_seconds / src_seconds
    if expected_samples <= 0:
        raise HTTPException(status_code=400, detail="Invalid expected sample calculation for aggregation")
                                                                                 
    dialect_name = None
    try:
        if session.bind is not None:
            dialect_name = session.bind.dialect.name
    except Exception:
        dialect_name = None
    bucket_expr = _bucket_start_expr(bucket_seconds, dialect=dialect_name)

    stmt = (
        sa_select(
            Measurement.sensor_id,
            func.avg(Measurement.value).label("value_avg"),
            bucket_expr.label("bucket_start"),
            Unit.symbol.label("unit_symbol"),
            Device.device_id,
            Device.name,
            Device.latitude,
            Device.longitude,
            Device.manual_data_source_name,
            ExternalAPI.name.label("network"),
        )
        .join(Sensor, Sensor.sensor_id == Measurement.sensor_id)
        .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
        .join(Unit, Unit.unit_id == Sensor.unit_id, isouter=True)
        .join(Device, Device.device_id == Sensor.device_id, isouter=True)
        .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
        .where(Parameter.code == pcode)
        .where(Measurement.is_valid == True)
    )
    stmt = _apply_public_source_filter(stmt, normalized_external_api_name)

    if since:
        cutoff = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        stmt = stmt.where(Measurement.observed_at >= cutoff)
    if until:
        upper = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        stmt = stmt.where(Measurement.observed_at <= upper)

    stmt = stmt.group_by(
        Measurement.sensor_id,
        bucket_expr,
        Unit.symbol,
        Device.device_id,
        Device.name,
        Device.latitude,
        Device.longitude,
        Device.manual_data_source_name,
        ExternalAPI.name,
    ).order_by(bucket_expr.desc())

                                                                                         
                                                                                                 
    aggregated = stmt.subquery("aggregated")
    latest_ranked = sa_select(
        aggregated,
        func.row_number()
        .over(partition_by=aggregated.c.sensor_id, order_by=aggregated.c.bucket_start.desc())
        .label("rn"),
    ).subquery("latest_ranked")
    stmt = sa_select(
        latest_ranked.c.sensor_id,
        latest_ranked.c.value_avg,
        latest_ranked.c.bucket_start,
        latest_ranked.c.unit_symbol,
        latest_ranked.c.device_id,
        latest_ranked.c.name,
        latest_ranked.c.latitude,
        latest_ranked.c.longitude,
        latest_ranked.c.manual_data_source_name,
        latest_ranked.c.network,
    ).where(latest_ranked.c.rn == 1)

    rows = session.execute(stmt).all()
    out = []
    for sensor_id, avg_val, bucket_start, unit_symbol, dev_id, dev_name, dev_lat, dev_lon, manual_source_name, network in rows:
        resolved_source_name = _resolve_public_source_name(manual_source_name, network)
        bs = bucket_start
        if isinstance(bs, str):
            try:
                parsed = datetime.fromisoformat(bs)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                bs = parsed
            except Exception:
                bs = None
        out.append(
            {
                "sensor_id": sensor_id,
                "parameter": pcode,
                "value": float(avg_val) if avg_val is not None else None,
                "unit": unit_symbol,
                "observed_at": bs.isoformat() if bs else None,
                "device": {
                    "device_id": dev_id,
                    "name": dev_name,
                    "latitude": dev_lat,
                    "longitude": dev_lon,
                    "network": resolved_source_name,
                    "external_api": ({"name": resolved_source_name} if resolved_source_name is not None else None),
                }
                if dev_id is not None
                else None,
            }
        )
    return out


@router.get("/measurements/latest", response_model=List[MeasurementOut])
def latest_all_parameters(
    limit: int = Query(100, ge=1, le=1000),
    since: Optional[datetime] = Query(
        None,
        description="ISO8601 UTC. If provided, returns rows with observed_at >= since and ignores 'limit'.",
    ),
    until: Optional[datetime] = Query(
        None,
        description="ISO8601 UTC upper bound. If provided, returns rows with observed_at <= until.",
    ),
    aggregation: Optional[str] = Query(
        None,
        description="Aggregation period code to restrict sensors to those that support the aggregation (e.g., '1h','8h','24h').",
    ),
    external_api_name: Optional[str] = Query(
        None,
        description="Optional filter by ExternalAPI.name (e.g., 'openaq', 'purpleair', 'airgradient').",
    ),
    session: Session = Depends(get_session),
):
    """Return latest measurements per sensor for all parameters.

    Optional 'since'/'until' filters the window; optional 'aggregation' restricts sensors
    to those whose aggregation_period matches or whose parameter has an aggregation rule.
    """
    try:
                                                 
        since_cutoff: Optional[datetime] = None
        if since:
            since_cutoff = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        until_cutoff: Optional[datetime] = None
        if until:
            until_cutoff = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        normalized_external_api_name = (external_api_name or "").strip().lower() if external_api_name else None

        rn = func.row_number().over(
            partition_by=Measurement.sensor_id,
            order_by=(Measurement.observed_at.desc(), Measurement.measurement_id.desc()),
        )

        base_select = (
            sa_select(
                Measurement.measurement_id.label("measurement_id"),
                Measurement.sensor_id.label("sensor_id"),
                Measurement.value.label("value"),
                Measurement.observed_at.label("observed_at"),
                Sensor.device_id.label("device_id"),
                Sensor.external_sensor_id.label("external_sensor_id"),
                Parameter.code.label("m_param_code"),
                Parameter.parameter_id.label("param_id"),
                Unit.symbol.label("m_unit_symbol"),
                rn.label("rn"),
                Sensor.aggregation_period_id.label("sensor_agg_id"),
            )
            .join(Sensor, Measurement.sensor_id == Sensor.sensor_id)
            .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
            .outerjoin(Unit, Sensor.unit_id == Unit.unit_id)
            .where(Measurement.is_valid == True)
        )

        if since_cutoff:
            base_select = base_select.where(Measurement.observed_at >= since_cutoff)
        if until_cutoff:
            base_select = base_select.where(Measurement.observed_at <= until_cutoff)

        agg_code_normalized: Optional[str] = None
        if aggregation:
            agg_code_normalized = (aggregation or "").lower()
            ap_tbl = AggregationPeriod
            par_rule_exists = (
                sa_select(ParameterAggregationRule.parameter_aggregation_rule_id)
                .join(
                    ap_tbl,
                    ParameterAggregationRule.aggregation_period_id == ap_tbl.aggregation_period_id,
                )
                .where(ParameterAggregationRule.parameter_id == Parameter.parameter_id)
                .where(ap_tbl.code == agg_code_normalized)
                .limit(1)
                .exists()
            )
            base_select = base_select.join(
                ap_tbl, Sensor.aggregation_period_id == ap_tbl.aggregation_period_id, isouter=True
            ).where(or_(ap_tbl.code == agg_code_normalized, par_rule_exists))

        base = base_select.subquery("latest_per_sensor_all")
        sensor_ap_out = aliased(AggregationPeriod, name="sensor_ap_out")

        stmt = (
            sa_select(
                base.c.measurement_id,
                base.c.sensor_id,
                base.c.m_param_code,
                base.c.value,
                base.c.m_unit_symbol,
                base.c.observed_at,
                Device.device_id,
                Device.name,
                Device.latitude,
                Device.longitude,
                Device.manual_data_source_name,
                base.c.external_sensor_id,
                sensor_ap_out.code.label("sensor_aggregation_code"),
                ExternalAPI.name.label("network"),
            )
            .join(Device, Device.device_id == base.c.device_id, isouter=True)
            .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
            .outerjoin(sensor_ap_out, sensor_ap_out.aggregation_period_id == base.c.sensor_agg_id)
            .where(base.c.rn == 1)
            .order_by(base.c.observed_at.desc())
        )
        stmt = _apply_public_source_filter(stmt, normalized_external_api_name)

        if since_cutoff is None:
            stmt = stmt.limit(limit)

        rows = session.execute(stmt).all()
        out: List[dict] = []

        parameter_codes_in_results: Set[str] = {
            (row[2] or "").lower()
            for row in rows
            if row[2]
        }
        aggregation_codes_in_results: Set[str] = {
            (row[12] or "").lower()
            for row in rows
            if row[12]
        }
        parameter_rules_by_code: Dict[str, Dict[str, ParameterAggregationRuleFormatting]] = {}
        for parameter_code in parameter_codes_in_results:
            parameter_rules_by_code[parameter_code] = load_parameter_aggregation_rules(
                session,
                parameter_code,
                aggregation_codes_in_results,
            )

        def format_latest_value_for_all_parameters(
            parameter_code: Optional[str],
            aggregation_code: Optional[str],
            raw_value: Optional[float],
        ) -> Optional[float]:
            normalized_parameter_code = (parameter_code or "").lower()
            if not normalized_parameter_code:
                return raw_value

            rules_for_parameter = parameter_rules_by_code.get(normalized_parameter_code, {})
            rule = resolve_parameter_aggregation_rule(rules_for_parameter, aggregation_code)
            if not rule:
                return raw_value

            return apply_parameter_aggregation_rule(
                raw_value,
                rule.rounding_method,
                rule.rounding_precision,
                rule.truncation_method,
                rule.truncation_precision,
            )

                                                                                       
        device_ids = {row[6] for row in rows if row[6] is not None}
        device_info_map: dict = {}
        if device_ids:
            try:
                net_rows = session.execute(
                    sa_select(
                        Device.device_id,
                        Device.manual_data_source_name,
                        ExternalAPI.name,
                        Device.timezone,
                    )
                    .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
                    .where(Device.device_id.in_(list(device_ids)))
                ).all()
                for did, manual_source_name, net, tz in net_rows:
                    device_info_map[did] = {
                        "network": _resolve_public_source_name(manual_source_name, net),
                        "timezone": tz,
                    }
            except Exception:
                device_info_map = {}

        for row in rows:
            device_info = device_info_map.get(row[6], {}) if row[6] is not None else {}
            device_network = device_info.get("network") if device_info else None
            device_timezone = device_info.get("timezone") if device_info else None
            fallback_network = _resolve_public_source_name(row[10], row[13])
            out.append(
                {
                    "measurement_id": row[0],
                    "sensor_id": row[1],
                    "external_sensor_id": row[11],
                    "parameter": row[2] or "",
                    "value": format_latest_value_for_all_parameters(row[2], row[12], row[3]),
                    "unit": row[4],
                    "observed_at": row[5].isoformat() if row[5] else None,
                    "device": (
                        {
                            "device_id": row[6],
                            "name": row[7],
                            "latitude": row[8],
                            "longitude": row[9],
                            "network": device_network or fallback_network,
                            "timezone": device_timezone,
                            "external_api": (
                                {"name": (device_network or fallback_network)}
                                if (device_network or fallback_network) is not None
                                else None
                            ),
                        }
                        if row[6] is not None
                        else None
                    ),
                }
            )
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
