from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime
from sqlalchemy import select, func, and_ as _and
from sqlalchemy.orm import Session

from db import get_session
from models import Measurement, Sensor, Parameter, Unit, MeasurementQCResult, Device, ExternalAPI

router = APIRouter()
logger = logging.getLogger(__name__)
MANUAL_SOURCE_LABEL = "Other"


def _resolve_public_source_name(manual_data_source_name: str | None, external_api_name: str | None) -> str | None:
    if manual_data_source_name:
        return MANUAL_SOURCE_LABEL
    return external_api_name


@router.get("/sensors/{sensor_id}/history")
def get_sensor_history(
    sensor_id: int,
    hours: int = Query(24, ge=1, le=24 * 365 * 5, description="Window size in hours if start/end not provided"),
    aggregate: str = Query("hour", description="Response shape: raw | hour | day"),
    start: datetime | None = Query(None, description="Start datetime (ISO8601 UTC); if provided, overrides 'hours'"),
    end: datetime | None = Query(None, description="End datetime (ISO8601 UTC); defaults to now if start provided"),
    include_invalid: bool = Query(False, description="Include invalid measurements that failed QC"),
    include_qc: bool = Query(False, description="Include QC details (failed checks) per point; not supported for aggregated series"),
    session: Session = Depends(get_session)
):
    """Return time series data for a specific sensor over the past N hours.
    
    Returns measurements ordered by observed_at ascending (oldest first).
    """
    try:
        from datetime import datetime as _dt, timedelta, timezone
        from sqlalchemy import literal_column

                         
        now_utc = _dt.now(timezone.utc)
        if start and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start and not end:
            end = now_utc
        cutoff = None if start else (now_utc - timedelta(hours=hours))

                                                           
        meta_row = session.execute(
            select(
                Sensor.sensor_id,
                Parameter.code.label("parameter_code"),
                Parameter.display_name.label("parameter_name"),
                Unit.symbol.label("unit_symbol"),
                Device.name.label("device_name"),
                Device.manual_data_source_name.label("manual_data_source_name"),
                ExternalAPI.name.label("external_api_name"),
                Sensor.external_sensor_id.label("external_sensor_id"),
                Device.timezone.label("device_timezone"),
            )
            .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
            .outerjoin(Unit, Sensor.unit_id == Unit.unit_id)
            .join(Device, Sensor.device_id == Device.device_id)
            .outerjoin(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id)
            .where(Sensor.sensor_id == sensor_id)
        ).first()
        if not meta_row:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")
        public_source_name = _resolve_public_source_name(
            getattr(meta_row, "manual_data_source_name", None),
            getattr(meta_row, "external_api_name", None),
        )

                            
        time_filters = []
        if start and end:
            time_filters.append(Measurement.observed_at >= start)
            time_filters.append(Measurement.observed_at <= end)
        elif cutoff is not None:
            time_filters.append(Measurement.observed_at >= cutoff)

        normalized_aggregate = (aggregate or "").strip().lower()
        raw_aggregate_aliases = {"raw", "latest"}
        if normalized_aggregate not in raw_aggregate_aliases | {"hour", "day"}:
            raise HTTPException(status_code=400, detail="Invalid aggregate; use raw|hour|day")

        uses_raw_measurements = normalized_aggregate in raw_aggregate_aliases

        def build_bucket_expression(bucket_name: str):
            dialect_name = None
            try:
                if session.bind is not None:
                    dialect_name = session.bind.dialect.name
            except Exception:
                dialect_name = None

            if dialect_name == "sqlite":
                sqlite_format_by_bucket = {
                    "hour": "%Y-%m-%d %H:00:00",
                    "day": "%Y-%m-%d 00:00:00",
                }
                sqlite_format = sqlite_format_by_bucket[bucket_name]
                return func.datetime(
                    func.strftime(sqlite_format, Measurement.observed_at),
                    literal_column("'utc'"),
                )

            return func.date_trunc(bucket_name, Measurement.observed_at)

        def normalize_timestamp(value):
            if value is None:
                return None
            if isinstance(value, str):
                try:
                    value = _dt.fromisoformat(value)
                except Exception:
                    return None
            if getattr(value, "tzinfo", None) is None:
                value = value.replace(tzinfo=timezone.utc)
            return value

        def to_iso_timestamp(value):
            normalized_value = normalize_timestamp(value)
            if normalized_value is None:
                return None
            return normalized_value.isoformat()

        rows = []
        if uses_raw_measurements:
                                                                 
            stmt = (
                select(
                    Measurement.measurement_id,
                    Measurement.value,
                    Measurement.observed_at,
                    Measurement.is_valid,
                    Measurement.qc_flags,
                )
                .where(Measurement.sensor_id == sensor_id)
            )
            for f in time_filters:
                stmt = stmt.where(f)
            if not include_invalid:
                stmt = stmt.where(Measurement.is_valid == True)              
            stmt = stmt.order_by(Measurement.observed_at.asc())
            result = session.execute(stmt)
            rows = result.fetchall()
        else:
            bucket = build_bucket_expression(normalized_aggregate).label("bucket")
            stmt = (
                select(
                    bucket,
                    func.avg(Measurement.value).label("avg_value"),
                    func.count().label("n"),
                )
                .where(Measurement.sensor_id == sensor_id)
            )
            for f in time_filters:
                stmt = stmt.where(f)
            if not include_invalid:
                stmt = stmt.where(Measurement.is_valid == True)              
            stmt = stmt.group_by(bucket).order_by(bucket.asc())
            result = session.execute(stmt)
            rows = result.fetchall()

        if not rows:
            return {
                "sensor_id": sensor_id,
                "parameter": meta_row.parameter_code if hasattr(meta_row, "parameter_code") else None,
                "parameter_name": getattr(meta_row, "parameter_name", None),
                "unit": getattr(meta_row, "unit_symbol", None),
                "aggregate": normalized_aggregate,
                **({"hours": hours} if not start else {}),
                **({"start": start.isoformat(), "end": (end.isoformat() if end else None)} if start else {}),
                "device_name": getattr(meta_row, "device_name", None),
                "device_timezone": getattr(meta_row, "device_timezone", None),
                "external_sensor_id": getattr(meta_row, "external_sensor_id", None),
                "external_api": ( {"name": public_source_name} if public_source_name is not None else None ),
                "data": []
            }

                                           
                                                                        
        qc_by_measurement: dict[int, list[dict]] = {}
        if uses_raw_measurements and include_qc:
            m_ids = [row[0] for row in rows]                             
            if m_ids:
                qc_rows = session.execute(
                    select(
                        MeasurementQCResult.measurement_id,
                        MeasurementQCResult.check_code,
                        MeasurementQCResult.severity,
                        MeasurementQCResult.message,
                    ).where(
                        MeasurementQCResult.measurement_id.in_(m_ids),
                        MeasurementQCResult.passed == False              
                    )
                ).fetchall()
                for mid, check_code, severity, message in qc_rows:
                    qc_by_measurement.setdefault(mid, []).append({
                        "check_code": check_code,
                        "severity": severity,
                        "message": message,
                    })

        if uses_raw_measurements:
            return {
                "sensor_id": sensor_id,
                "parameter": getattr(meta_row, "parameter_code", None),
                "parameter_name": getattr(meta_row, "parameter_name", None),
                "unit": getattr(meta_row, "unit_symbol", None),
                "aggregate": "raw",
                **({"hours": hours} if not start else {}),
                **({"start": start.isoformat(), "end": (end.isoformat() if end else None)} if start else {}),
                "device_name": getattr(meta_row, "device_name", None),
                "device_timezone": getattr(meta_row, "device_timezone", None),
                "external_sensor_id": getattr(meta_row, "external_sensor_id", None),
                "external_api": ( {"name": public_source_name} if public_source_name is not None else None ),
                "data": [
                    {
                        "timestamp": to_iso_timestamp(row[2]),
                        "value": row[1],
                        "is_valid": bool(row[3]),
                        "qc_flags": row[4],
                        **({"failed_checks": qc_by_measurement.get(row[0], [])} if include_qc else {}),
                    }
                    for row in rows
                ]
            }
        else:
                                 
            return {
                "sensor_id": sensor_id,
                "parameter": getattr(meta_row, "parameter_code", None),
                "parameter_name": getattr(meta_row, "parameter_name", None),
                "unit": getattr(meta_row, "unit_symbol", None),
                "aggregate": normalized_aggregate,
                **({"hours": hours} if not start else {}),
                **({"start": start.isoformat(), "end": (end.isoformat() if end else None)} if start else {}),
                "device_name": getattr(meta_row, "device_name", None),
                "device_timezone": getattr(meta_row, "device_timezone", None),
                "external_sensor_id": getattr(meta_row, "external_sensor_id", None),
                "external_api": ( {"name": public_source_name} if public_source_name is not None else None ),
                "data": [
                    {
                        "timestamp": to_iso_timestamp(row[0]),
                        "value": float(row[1]) if row[1] is not None else None,
                        "is_valid": True,
                    }
                    for row in rows
                ]
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get sensor history for sensor_id=%s", sensor_id)
        raise HTTPException(status_code=500, detail=str(e))
