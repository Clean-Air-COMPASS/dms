from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime, timezone
from sqlalchemy import text, select, func
from sqlalchemy.orm import Session, aliased

from db import engine, get_session
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    ParameterAggregationRollup,
    ParameterAggregationRule,
    Sensor,
    Unit,
)
from sqlalchemy import exists as sa_exists, and_
from services import aqi as aqi_service
from utils.parameter_aggregation_rule_formatting import (
    apply_parameter_aggregation_rule,
    load_parameter_aggregation_rules,
    resolve_parameter_aggregation_rule,
)

router = APIRouter()
MANUAL_SOURCE_LABEL = "Other"


def _resolve_public_source_name(manual_data_source_name: Optional[str], external_api_name: Optional[str]) -> Optional[str]:
    if manual_data_source_name:
        return MANUAL_SOURCE_LABEL
    return external_api_name


def _is_other_source_filter(external_api_name: Optional[str]) -> bool:
    return (external_api_name or "").strip().lower() == MANUAL_SOURCE_LABEL.lower()


@router.get("/data-sources")
def list_public_data_sources(session: Session = Depends(get_session)):
    rows = session.execute(
        select(ExternalAPI.name)
        .where(ExternalAPI.is_active == True)              
        .order_by(ExternalAPI.name.asc())
    ).all()

    options = [
        {"name": name, "filter_value": name.lower()}
        for (name,) in rows
        if name
    ]
    options.append({"name": MANUAL_SOURCE_LABEL, "filter_value": MANUAL_SOURCE_LABEL.lower()})

    deduped: list[dict[str, str]] = []
    seen_filter_values: set[str] = set()
    for option in options:
        filter_value = option["filter_value"]
        if filter_value in seen_filter_values:
            continue
        seen_filter_values.add(filter_value)
        deduped.append(option)

    deduped.sort(key=lambda option: option["name"].lower())
    return deduped


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/version")
def db_version():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            row = result.fetchone()
            return {"postgres_version": row[0] if row else "unknown"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


@router.get("/devices")
def list_devices(
    aggregation: Optional[str] = Query(
        None,
        description=(
            "Aggregation period code to restrict devices to those with at least one sensor that supports the "
            "aggregation (directly or via rollup from a finer period)."
        ),
    ),
    external_api_name: Optional[str] = Query(
        None,
        description="Optional filter by ExternalAPI.name (e.g., 'openaq', 'purpleair', 'airgradient').",
    ),
    session: Session = Depends(get_session),
):
    """Return a list of devices with current coordinates.

    Phase 2+: Device.latitude/longitude are authoritative; no history fallback.
    """
    try:
        from sqlalchemy import select as sa_select
        from sqlalchemy import distinct

                                 
        sens_counts = (
            sa_select(Sensor.device_id, func.count(Sensor.sensor_id).label("sensor_count"))
            .group_by(Sensor.device_id)
            .subquery("sens_counts")
        )

        agg_code = (aggregation or "").lower()
        normalized_external_api_name = (external_api_name or "").strip().lower() if external_api_name else None
        qualified_devices = None
        if aggregation:
            if agg_code in aqi_service.AQI_TIME_RESOLUTIONS:
                allowed_params = [
                    p for p, tres in aqi_service.POLLUTANT_TIME_RESOLUTIONS.items() if agg_code in tres
                ]
                if allowed_params:
                    qualified_devices = (
                        sa_select(distinct(Sensor.device_id).label("device_id"))
                        .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
                        .where(Parameter.code.in_(allowed_params))
                    ).subquery("agg_devices")
            else:
                                                                                              
                                                                                                                       
                ap_sensor = aliased(AggregationPeriod, name="ap_sensor_devices")
                ap_to = aliased(AggregationPeriod, name="ap_to_devices")

                rollup_exists = (
                    sa_select(ParameterAggregationRollup.parameter_aggregation_rollup_id)
                    .join(ap_to, ap_to.aggregation_period_id == ParameterAggregationRollup.to_aggregation_period_id)
                    .where(ParameterAggregationRollup.parameter_id == Sensor.parameter_id)
                    .where(ParameterAggregationRollup.from_aggregation_period_id == Sensor.aggregation_period_id)
                    .where(ap_to.code == agg_code)
                    .limit(1)
                    .exists()
                )

                rule_exists = (
                    sa_select(ParameterAggregationRule.parameter_aggregation_rule_id)
                    .join(
                        AggregationPeriod,
                        ParameterAggregationRule.aggregation_period_id == AggregationPeriod.aggregation_period_id,
                    )
                    .where(ParameterAggregationRule.parameter_id == Sensor.parameter_id)
                    .where(AggregationPeriod.code == agg_code)
                    .limit(1)
                    .exists()
                )

                qualified_devices = (
                    sa_select(distinct(Sensor.device_id).label("device_id"))
                    .join(ap_sensor, ap_sensor.aggregation_period_id == Sensor.aggregation_period_id, isouter=True)
                    .where(
                        (
                            (ap_sensor.code == agg_code)
                            | rollup_exists
                            | ((Sensor.aggregation_period_id == None) & rule_exists)
                        )
                    )
                ).subquery("agg_devices")

        stmt = (
            sa_select(
                Device,
                Device.latitude.label("latitude"),
                Device.longitude.label("longitude"),
                Device.timezone.label("timezone"),
                func.coalesce(sens_counts.c.sensor_count, 0).label("sensor_count"),
                Device.manual_data_source_name.label("manual_data_source_name"),
                ExternalAPI.name.label("network"),
            )
            .join(sens_counts, sens_counts.c.device_id == Device.device_id, isouter=True)
            .join(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
            .order_by(Device.created_at.desc())
        )
        if normalized_external_api_name:
            if _is_other_source_filter(normalized_external_api_name):
                stmt = stmt.where(Device.manual_data_source_name.is_not(None))
            else:
                stmt = stmt.where(func.lower(ExternalAPI.name) == normalized_external_api_name)
        if qualified_devices is not None:
            stmt = stmt.join(qualified_devices, qualified_devices.c.device_id == Device.device_id)

        rows = session.execute(stmt).all()
        return [
            {
                "device_id": row[0].device_id,
                "name": row[0].name,
                "friendly_name": getattr(row[0], "friendly_name", None),
                "created_at": row[0].created_at.isoformat() if row[0].created_at else None,
                "latitude": row[1],
                "longitude": row[2],
                "timezone": row[3],
                "external_id": getattr(row[0], "external_id", None),
                "sensor_count": row[4],
                "network": _resolve_public_source_name(row[5], row[6]),
            }
            for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{device_id}/sensors")
def list_device_sensors(
    device_id: int,
    since: datetime | None = Query(
        None,
        description="ISO8601 UTC. If provided, latest values are computed only from measurements with observed_at >= since.",
    ),
    aggregation: Optional[str] = Query(
        None,
        description="Aggregation period code to restrict sensors to those that support the aggregation (e.g., '1h','8h','24h').",
    ),
    session: Session = Depends(get_session),
):
    """Return all sensors for a device along with basic metadata and latest measurement.

    For each sensor: sensor_id, external_sensor_id, parameter code/name, unit symbol,
    latest value and observed_at (from valid measurements only).
    """
    try:
        from sqlalchemy import select as sa_select
        from sqlalchemy import or_

                                
        exists = session.execute(sa_select(Device.device_id).where(Device.device_id == device_id)).first()
        if not exists:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

                                                                                                                
        def build_latest_with_valid():
            rn_local = func.row_number().over(
                partition_by=Measurement.sensor_id,
                order_by=[Measurement.observed_at.desc(), Measurement.measurement_id.desc()],
            )
            sel = sa_select(
                Measurement.sensor_id.label("sensor_id"),
                Measurement.value.label("value"),
                Measurement.observed_at.label("observed_at"),
                getattr(Measurement, "is_valid").label("is_valid"),
                rn_local.label("rn"),
            )
            if since:
                cutoff = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
                sel = sel.where(Measurement.observed_at >= cutoff)
            return sel.subquery("latest")

        def build_latest_without_valid():
            rn_local = func.row_number().over(
                partition_by=Measurement.sensor_id,
                order_by=[Measurement.observed_at.desc(), Measurement.measurement_id.desc()],
            )
            sel = sa_select(
                Measurement.sensor_id.label("sensor_id"),
                Measurement.value.label("value"),
                Measurement.observed_at.label("observed_at"),
                rn_local.label("rn"),
            )
            if since:
                cutoff = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
                sel = sel.where(Measurement.observed_at >= cutoff)
            return sel.subquery("latest")

                                                                                 
        def build_stmt(latest_subq, has_valid: bool):
            return (
            sa_select(
                Sensor.sensor_id,
                Sensor.external_sensor_id,
                AggregationPeriod.code.label("aggregation_code"),
                Parameter.code.label("parameter_code"),
                Parameter.display_name.label("parameter_name"),
                Unit.symbol.label("unit_symbol"),
                latest_subq.c.value,
                latest_subq.c.observed_at,
                (latest_subq.c.is_valid if has_valid else func.null()).label("is_valid"),
            )
            .select_from(Sensor)
            .outerjoin(AggregationPeriod, Sensor.aggregation_period_id == AggregationPeriod.aggregation_period_id)
            .outerjoin(Parameter, Sensor.parameter_id == Parameter.parameter_id)
            .outerjoin(Unit, Sensor.unit_id == Unit.unit_id)
            .outerjoin(latest_subq, (latest_subq.c.sensor_id == Sensor.sensor_id) & (latest_subq.c.rn == 1))
            .where(Sensor.device_id == device_id)
            .order_by(Parameter.display_name.asc().nulls_last())
        )
                                                                 
        latest = build_latest_with_valid()
        stmt = build_stmt(latest, has_valid=True)
                                                                                   
                                                                                     
                                                                                          
        if aggregation:
            agg_code = (aggregation or "").lower()
            if agg_code in aqi_service.AQI_TIME_RESOLUTIONS:
                allowed_params = [
                    p for p, tres in aqi_service.POLLUTANT_TIME_RESOLUTIONS.items() if agg_code in tres
                ]
                if allowed_params:
                    stmt = stmt.where(Parameter.code.in_(allowed_params))
            else:
                exists_subq = (
                    sa_select(ParameterAggregationRule.parameter_aggregation_rule_id)
                    .join(
                        AggregationPeriod,
                        ParameterAggregationRule.aggregation_period_id == AggregationPeriod.aggregation_period_id,
                    )
                    .where(ParameterAggregationRule.parameter_id == Sensor.parameter_id)
                    .where(AggregationPeriod.code == agg_code)
                    .limit(1)
                    .exists()
                )
                stmt = (
                    stmt.join(
                        AggregationPeriod,
                        AggregationPeriod.aggregation_period_id == Sensor.aggregation_period_id,
                        isouter=True,
                    )
                    .where(
                        or_(
                            AggregationPeriod.code == agg_code,
                                                                                                                       
                            and_(Sensor.aggregation_period_id == None, exists_subq),
                        )
                    )
                )
        try:
            rows = session.execute(stmt).all()
        except Exception as e:
            msg = str(e).lower()
                                                                             
            if "is_valid" in msg or "undefined column" in msg or "does not exist" in msg:
                rows = session.execute(build_stmt(build_latest_without_valid(), has_valid=False)).all()
            else:
                raise

        parameter_codes = {
            (getattr(row, "parameter_code", None) or "").lower()
            for row in rows
            if getattr(row, "parameter_code", None)
        }
        aggregation_codes = {
            (getattr(row, "aggregation_code", None) or "").lower()
            for row in rows
            if getattr(row, "aggregation_code", None)
        }
        rules_by_parameter_and_aggregation: dict[str, dict] = {}
        for parameter_code in parameter_codes:
            rules_by_parameter_and_aggregation[parameter_code] = load_parameter_aggregation_rules(
                session,
                parameter_code,
                aggregation_codes,
            )

        def format_latest_value(
            parameter_code: Optional[str],
            aggregation_code: Optional[str],
            raw_value: Optional[float],
        ) -> Optional[float]:
            normalized_parameter_code = (parameter_code or "").lower()
            if not normalized_parameter_code:
                return raw_value

            rules_for_parameter = rules_by_parameter_and_aggregation.get(normalized_parameter_code, {})
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

        out = []
        for r in rows:
            out.append(
                {
                    "sensor_id": r[0],
                    "external_sensor_id": r[1],
                    "aggregation_code": r[2],
                    "parameter": r[3],
                    "parameter_name": r[4],
                    "unit": r[5],
                    "latest_value": format_latest_value(r[3], r[2], r[6]),
                    "latest_observed_at": r[7].isoformat() if r[7] else None,
                    "latest_is_valid": r[8] if len(r) > 8 else None,
                }
            )
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
