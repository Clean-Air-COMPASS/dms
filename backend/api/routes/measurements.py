from __future__ import annotations

from typing import Annotated, Optional, List, Tuple, Dict
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session, aliased

from db import get_session
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Parameter,
    ParameterAggregationRule,
    ParameterAggregationRollup,
    Sensor,
    Unit,
)
from utils.aggregations import get_pm25_rolling_24h_avg, get_pm25_daily_24h_avg
from utils.parameter_aggregation_rule_formatting import (
    ParameterAggregationRuleFormatting,
    apply_parameter_aggregation_rule,
    load_parameter_aggregation_rules,
    parameter_aggregation_display_precision,
    resolve_parameter_aggregation_rule,
)
from services.measurement_aggregation import (
    MeasurementAggregationError,
    execute_measurement_aggregation,
    execute_latest_measurements,
    load_measurement_aggregation_capabilities,
    resolve_measurement_aggregation,
)
from services.device_locations import (
    InvalidBoundingBox,
    device_bbox_predicate,
    parse_bounding_box,
)
from services.data_attribution import serialize_data_attribution

                       
                                                                             
                                                                               
                                                                 
                                                                            
                                                       

router = APIRouter()
                                                                                  
MANUAL_SOURCE_LABEL = "Other"


def _normalize_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_bbox(bbox: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    try:
        parsed = parse_bounding_box(bbox)
    except InvalidBoundingBox as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return parsed.as_tuple() if parsed is not None else None


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
    # Manual devices retain a provider association for storage, but their
    # public source identity is Other, matching the serialized provenance.
    return stmt.where(
        Device.manual_data_source_name.is_(None),
        func.lower(ExternalAPI.name) == normalized_external_api_name,
    )

class DeviceOut(BaseModel):
    device_id: Optional[int]
    name: Optional[str]
    friendly_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    network: Optional[str] = None
    timezone: Optional[str] = None
    external_api: Optional[dict] = None
    data_attribution: Optional[dict] = None


class MeasurementOut(BaseModel):
    """Public response shape for physical measurement values."""

    measurement_id: int
    sensor_id: Optional[int]
    external_sensor_id: Optional[str] = None
    parameter: str
    parameter_name: str
    value: float
    unit: Optional[str]
    observed_at: Optional[str]
    sensor_aggregation_period: Optional[str] = None
    native_aggregation_code: Optional[str] = None
    result_aggregation_code: Optional[str] = None
    formatting_status: Optional[str] = None
    display_precision: Optional[int] = None
    interval_started_at: Optional[str] = None
    interval_ended_at: Optional[str] = None
    latest_source_observed_at: Optional[str] = None
    query_since: Optional[str] = None
    result_is_rolling: bool = False
    sample_count: Optional[int] = None
    valid_sample_count: Optional[int] = None
    invalid_sample_count: Optional[int] = None
    acquisition_metadata: Optional[dict] = None
    device: Optional[DeviceOut]

                                                                    
    model_config = {"from_attributes": True}


class ParameterOut(BaseModel):
    code: str
    display_name: str
    unit_symbol: Optional[str] = None


def _latest_result_page(rows: list[dict], limit: int, offset: Optional[int]) -> list[dict]:
    # Export pages use sensor identity, rather than changing observation times,
    # so new observations cannot move a sensor between pages.
    if offset is None:
        return rows
    ordered = sorted(rows, key=lambda row: (row.get("sensor_id") or 0, row["measurement_id"]))
    return ordered[offset:offset + limit]


def _attach_acquisition_metadata(session: Session, rows: list[dict]) -> list[dict]:
    """Expose stream provenance without changing scientific aggregation."""
    sensor_ids = {row["sensor_id"] for row in rows if row.get("sensor_id") is not None}
    if not sensor_ids:
        return rows
    metadata = dict(session.execute(sa_select(
        Sensor.sensor_id, Sensor.acquisition_metadata,
    ).where(Sensor.sensor_id.in_(sensor_ids))).all())
    for row in rows:
        acquisition = metadata.get(row.get("sensor_id"))
        if acquisition is not None:
            row["acquisition_metadata"] = acquisition
    return rows


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
            .where(ParameterAggregationRule.active.is_(True))
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
        stmt = sa_select(
            AggregationPeriod.code,
            AggregationPeriod.display_name,
            AggregationPeriod.duration_minutes,
        ).order_by(AggregationPeriod.duration_minutes.asc().nulls_last())
        rows = session.execute(stmt).all()
        return [
            {
                "code": row.code,
                "display_name": row.display_name,
                "duration_minutes": row.duration_minutes,
            }
            for row in rows
        ]
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
    min_hours: Optional[int] = Query(None, description="Minimum per-sensor hours required to include sensor in the aggregate."),
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
    min_hours: Optional[int] = Query(None, description="Minimum per-sensor hours required to include sensor in the aggregate."),
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
    all_results: bool = False,
    offset: Annotated[Optional[int], Query(ge=0, description="Export page offset in stable sensor order. When set, limit applies even with since or all_results.")] = None,
    session: Session = Depends(get_session),
):
    """Return latest measurements for a given parameter code.

    Mirrors the pm25 endpoint but supports any canonical Parameter.code.
    Map callers may request all_results without imposing a time window.
    Optional 'since' parameter filters by observed_at >= since (UTC) and disables the limit.
    Explicit offset requests instead paginate in stable sensor order using limit.
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

        if agg_code == "aqi" or (agg_code and agg_code.startswith("aqi-")):
            raise HTTPException(
                status_code=400,
                detail=(
                    "U.S. EPA AQI is available only from "
                    "/air-quality-index/us_epa/latest."
                ),
            )

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
                    Device.friendly_name,
                    Parameter.display_name.label("parameter_name"),
                    Device.latitude,
                    Device.longitude,
                    Device.timezone,
                    Device.manual_data_source_name,
                    ExternalAPI.name.label("network"),
                    Device.acquisition_path,
                    Device.hardware_provider_name,
                    Device.provider_url,
                    Device.contributor_name,
                    Device.contributor_url,
                    Device.license_code,
                    Device.license_url,
                    Device.license_share_alike,
                )
                .join(Sensor, Sensor.device_id == Device.device_id)
                .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
                .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
                .where(Parameter.code == "pm25")
                .distinct()
            )
            dev_stmt = _apply_public_source_filter(dev_stmt, normalized_external_api_name)
            if bbox_tuple is not None:
                dev_stmt = dev_stmt.where(
                    device_bbox_predicate(Device.location, bbox_tuple)
                )
            dev_rows = session.execute(dev_stmt).all()

            out: List[dict] = []
            rules_for_pm25_24h: Dict[str, ParameterAggregationRuleFormatting] = load_parameter_aggregation_rules(
                session, pcode, {"24h"}
            )
            pm25_24h_rule = resolve_parameter_aggregation_rule(rules_for_pm25_24h, "24h")

            now_utc = datetime.now(timezone.utc)
            for (
                d_id,
                d_name,
                d_friendly_name,
                d_parameter_name,
                d_lat,
                d_lon,
                d_tz,
                d_manual_source_name,
                d_network,
                d_acquisition_path,
                d_hardware_provider_name,
                d_provider_url,
                d_contributor_name,
                d_contributor_url,
                d_license_code,
                d_license_url,
                d_license_share_alike,
            ) in dev_rows:
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
                                                                                           
                    obs_at = datetime.combine(
                        local_today,
                        datetime.min.time(),
                        tzinfo=ZoneInfo(d_tz),
                    ).astimezone(timezone.utc).isoformat()

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
                        "parameter_name": d_parameter_name,
                        "value": avg_val,
                        "unit": unit_symbol,
                        "observed_at": obs_at,
                        # These device-level PM2.5 products remain specialized
                        # adapters; they do not have one sensor-native period.
                        "native_aggregation_code": None,
                        "result_aggregation_code": agg_code,
                        "formatting_status": (
                            "configured" if pm25_24h_rule is not None else "not_configured"
                        ),
                        "display_precision": (
                            parameter_aggregation_display_precision(pm25_24h_rule)
                        ),
                        "device": {
                            "device_id": d_id,
                            "name": d_name,
                            "friendly_name": d_friendly_name,
                            "latitude": d_lat,
                            "longitude": d_lon,
                            "network": resolved_source_name,
                            "external_api": ({"name": resolved_source_name} if resolved_source_name is not None else None),
                            "data_attribution": serialize_data_attribution(
                                acquisition_path=d_acquisition_path,
                                data_provider_name=resolved_source_name,
                                hardware_provider_name=d_hardware_provider_name,
                                provider_url=d_provider_url,
                                contributor_name=d_contributor_name,
                                contributor_url=d_contributor_url,
                                license_code=d_license_code,
                                license_url=d_license_url,
                                license_share_alike=d_license_share_alike,
                            ),
                        },
                    }
                )

            return _latest_result_page(out, limit, offset)

                                                                                  
                                                                                      
                                                                                
        try:
            shared_results = execute_latest_measurements(
                session,
                result_aggregation_code=agg_code,
                parameter_code=pcode,
                since=cutoff,
                until=until_cutoff,
                source=normalized_external_api_name,
                device_id=device_id,
                bbox=bbox_tuple,
            )
        except MeasurementAggregationError as exc:
            raise HTTPException(
                status_code=400,
                detail={"reason": exc.reason, "message": str(exc)},
            ) from exc
        if offset is not None:
            return _attach_acquisition_metadata(session, _latest_result_page(shared_results, limit, offset))
        return _attach_acquisition_metadata(session, shared_results if all_results or since is not None else shared_results[:limit])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/measurement-aggregation-capabilities")
def measurement_aggregation_capabilities(
    parameter: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    native_aggregation_code: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Return backend-resolved ordinary measurement aggregation options."""

    try:
        return load_measurement_aggregation_capabilities(
            session,
            parameter_code=parameter,
            source=source,
            native_aggregation_code=native_aggregation_code,
        )
    except MeasurementAggregationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc


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

    native_period = aliased(AggregationPeriod, name="legacy_aggregate_native_period")
    sensor_query = (
        sa_select(
            Sensor.sensor_id,
            Sensor.external_sensor_id,
            Parameter.display_name.label("parameter_name"),
            Unit.symbol.label("unit_symbol"),
            Device.device_id,
            Device.name.label("device_name"),
            Device.latitude,
            Device.longitude,
            Device.manual_data_source_name,
            ExternalAPI.name.label("external_api_name"),
        )
        .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
        .join(native_period, native_period.aggregation_period_id == Sensor.aggregation_period_id)
        .outerjoin(Unit, Unit.unit_id == Sensor.unit_id)
        .join(Device, Device.device_id == Sensor.device_id)
        .outerjoin(ExternalAPI, ExternalAPI.external_api_id == Device.external_api_id)
        .where(func.lower(Parameter.code) == pcode)
        .where(func.lower(native_period.code) == src)
    )
    sensor_query = _apply_public_source_filter(sensor_query, normalized_external_api_name)
    sensor_rows = session.execute(sensor_query).all()
    metadata_by_sensor = {int(row.sensor_id): row for row in sensor_rows}
    try:
        resolve_measurement_aggregation(session, pcode, src, dst)
        points = execute_measurement_aggregation(
            session,
            sensor_ids=metadata_by_sensor,
            parameter_code=pcode,
            native_aggregation_code=src,
            result_aggregation_code=dst,
            since=since,
            until=until,
            # This legacy endpoint has always returned the latest bucket per sensor.
            latest_only=True,
        )
    except MeasurementAggregationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc

    output = []
    for point in points:
        metadata = metadata_by_sensor[point.sensor_id]
        source_name = _resolve_public_source_name(
            metadata.manual_data_source_name, metadata.external_api_name
        )
        output.append(
            {
                "measurement_id": point.measurement_id,
                "sensor_id": point.sensor_id,
                "external_sensor_id": metadata.external_sensor_id,
                "parameter": pcode,
                "parameter_name": metadata.parameter_name,
                "value": point.value,
                "unit": metadata.unit_symbol,
                "observed_at": point.observed_at.isoformat() if point.observed_at else None,
                "sensor_aggregation_period": src,
                "native_aggregation_code": src,
                "result_aggregation_code": point.result_aggregation_code,
                "formatting_status": point.formatting_status,
                "display_precision": point.display_precision,
                "interval_started_at": point.interval_started_at.isoformat() if point.interval_started_at else None,
                "interval_ended_at": point.interval_ended_at.isoformat() if point.interval_ended_at else None,
                "sample_count": point.sample_count,
                "valid_sample_count": point.valid_sample_count,
                "invalid_sample_count": point.invalid_sample_count,
                "device": {
                    "device_id": metadata.device_id,
                    "name": metadata.device_name,
                    "latitude": metadata.latitude,
                    "longitude": metadata.longitude,
                    "network": source_name,
                    "external_api": ({"name": source_name} if source_name is not None else None),
                },
            }
        )
    return output

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
    offset: Annotated[Optional[int], Query(ge=0, description="Export page offset in stable sensor order. When set, limit applies even with since.")] = None,
    session: Session = Depends(get_session),
):
    """Return latest measurements per sensor for all parameters.

    Optional 'since'/'until' filters the window; optional 'aggregation' restricts sensors
    to those whose aggregation_period matches or whose parameter has an aggregation rule.
    Explicit offset requests paginate in stable sensor order, including with since.
    """
    try:
                                                 
        since_cutoff: Optional[datetime] = None
        if since:
            since_cutoff = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        until_cutoff: Optional[datetime] = None
        if until:
            until_cutoff = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        normalized_external_api_name = (external_api_name or "").strip().lower() if external_api_name else None

        try:
            shared_results = execute_latest_measurements(
                session,
                result_aggregation_code=aggregation,
                since=since_cutoff,
                until=until_cutoff,
                source=normalized_external_api_name,
            )
        except MeasurementAggregationError as exc:
            raise HTTPException(
                status_code=400,
                detail={"reason": exc.reason, "message": str(exc)},
            ) from exc
        if offset is not None:
            return _attach_acquisition_metadata(session, _latest_result_page(shared_results, limit, offset))
        return _attach_acquisition_metadata(session, shared_results if since is not None else shared_results[:limit])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
