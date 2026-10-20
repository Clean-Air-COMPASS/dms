from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.orm import Session, aliased

from db import get_session
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Parameter,
    Sensor,
    Unit,
)
from sqlalchemy import or_
from services.measurement_aggregation import (
    MeasurementAggregationError,
    execute_latest_measurements,
    load_measurement_aggregation_capabilities,
)
from services.data_attribution import serialize_device_data_attribution

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
        .where(or_(
            ExternalAPI.enabled.is_(True),
            select(Device.device_id).where(
                Device.external_api_id == ExternalAPI.external_api_id,
                Device.manual_data_source_name.is_(None),
            ).exists(),
        ))
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


@router.get("/devices")
def list_devices(
    parameter: Optional[str] = Query(None, description="Restrict to devices with a sensor for this parameter, including sensors without measurements."),
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

    Device.location is authoritative; coordinates are derived with ST_Y/ST_X.
    Location history is not a fallback for a missing current point.
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
            capability_groups = load_measurement_aggregation_capabilities(
                session, source=normalized_external_api_name
            )
            supported_pairs = {
                (group["parameter_code"], group["native_aggregation_code"])
                for group in capability_groups
                if agg_code in {"raw", "latest"}
                or any(
                        option["result_aggregation_code"] == agg_code
                        and option["supports_latest"]
                        for option in group["supported_aggregations"]
                    )
            }
            ap_sensor = aliased(AggregationPeriod, name="ap_sensor_devices")
            pair_conditions = [
                (
                    (func.lower(Parameter.code) == parameter_code)
                    & (func.lower(ap_sensor.code) == native_code)
                )
                for parameter_code, native_code in sorted(supported_pairs)
                if native_code is not None
            ]
            if agg_code in {"raw", "latest"}:
                unknown_native_pairs = {
                    parameter_code
                    for parameter_code, native_code in supported_pairs
                    if native_code is None
                }
                pair_conditions.extend(
                    (func.lower(Parameter.code) == parameter_code)
                    & ap_sensor.code.is_(None)
                    for parameter_code in sorted(unknown_native_pairs)
                )
            qualified_devices = (
                sa_select(distinct(Sensor.device_id).label("device_id"))
                .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
                .join(ap_sensor, ap_sensor.aggregation_period_id == Sensor.aggregation_period_id, isouter=True)
                .where(or_(*pair_conditions) if pair_conditions else False)
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
                stmt = stmt.where(
                    Device.manual_data_source_name.is_(None),
                    func.lower(ExternalAPI.name) == normalized_external_api_name,
                )
        if parameter:
            parameter_devices = (
                sa_select(Sensor.device_id)
                .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
                .where(func.lower(Parameter.code) == parameter.strip().lower())
            )
            stmt = stmt.where(Device.device_id.in_(parameter_devices))
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
                "data_attribution": serialize_device_data_attribution(
                    row[0], _resolve_public_source_name(row[5], row[6])
                ),
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
    until: datetime | None = Query(None, description="ISO8601 UTC upper bound."),
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
                                
        exists = session.execute(sa_select(Device.device_id).where(Device.device_id == device_id)).first()
        if not exists:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

        try:
            latest_rows = execute_latest_measurements(
                session,
                result_aggregation_code=aggregation,
                since=since,
                until=until,
                device_id=device_id,
            )
        except MeasurementAggregationError as exc:
            raise HTTPException(
                status_code=400,
                detail={"reason": exc.reason, "message": str(exc)},
            ) from exc

        native_period = aliased(AggregationPeriod, name="device_sensor_native_period")
        metadata_rows = session.execute(
            sa_select(
                Sensor.sensor_id,
                Sensor.external_sensor_id,
                native_period.code.label("native_aggregation_code"),
                Parameter.code.label("parameter_code"),
                Parameter.display_name.label("parameter_name"),
                Unit.symbol.label("unit_symbol"),
                Sensor.expected_frequency_seconds,
                Sensor.measurement_duration_seconds,
                Sensor.source_aggregation_duration_seconds,
                Sensor.measurement_timestamp_semantics,
                Sensor.measurement_metadata_status,
                Sensor.measurement_metadata_managed_by,
                Sensor.acquisition_metadata,
            )
            .select_from(Sensor)
            .outerjoin(native_period, native_period.aggregation_period_id == Sensor.aggregation_period_id)
            .outerjoin(Parameter, Parameter.parameter_id == Sensor.parameter_id)
            .outerjoin(Unit, Unit.unit_id == Sensor.unit_id)
            .where(Sensor.device_id == device_id)
            .order_by(Parameter.display_name.asc().nulls_last())
        ).all()
        latest_by_sensor = {int(row["sensor_id"]): row for row in latest_rows}
        output = []
        for metadata in metadata_rows:
            latest = latest_by_sensor.get(int(metadata.sensor_id))
            if aggregation and latest is None:
                continue
            native_code = (metadata.native_aggregation_code or "").lower() or None
            output.append(
                {
                    "sensor_id": metadata.sensor_id,
                    "external_sensor_id": metadata.external_sensor_id,
                    "aggregation_code": native_code,
                    "native_aggregation_code": native_code,
                    "result_aggregation_code": (
                        latest["result_aggregation_code"] if latest else (native_code or "raw")
                    ),
                    "parameter": metadata.parameter_code,
                    "parameter_name": metadata.parameter_name,
                    "unit": metadata.unit_symbol,
                    "latest_value": latest["value"] if latest else None,
                    "latest_observed_at": latest["observed_at"] if latest else None,
                    "latest_is_valid": (
                        latest["invalid_sample_count"] == 0 if latest else None
                    ),
                    "formatting_status": latest["formatting_status"] if latest else None,
                    "display_precision": latest["display_precision"] if latest else None,
                    "interval_started_at": latest["interval_started_at"] if latest else None,
                    "interval_ended_at": latest["interval_ended_at"] if latest else None,
                    "latest_source_observed_at": latest["latest_source_observed_at"] if latest else None,
                    "query_since": latest["query_since"] if latest else None,
                    "result_is_rolling": latest["result_is_rolling"] if latest else False,
                    "sample_count": latest["sample_count"] if latest else 0,
                    "valid_sample_count": latest["valid_sample_count"] if latest else 0,
                    "invalid_sample_count": latest["invalid_sample_count"] if latest else 0,
                    "expected_frequency_seconds": metadata.expected_frequency_seconds,
                    "measurement_duration_seconds": metadata.measurement_duration_seconds,
                    "source_aggregation_duration_seconds": metadata.source_aggregation_duration_seconds,
                    "measurement_timestamp_semantics": metadata.measurement_timestamp_semantics,
                    "measurement_metadata_status": metadata.measurement_metadata_status,
                    "measurement_metadata_managed_by": metadata.measurement_metadata_managed_by,
                    "acquisition_metadata": metadata.acquisition_metadata,
                }
            )
        return output
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
