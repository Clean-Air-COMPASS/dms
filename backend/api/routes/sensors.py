from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_session
from models import AggregationPeriod, Measurement, Sensor, Parameter, Unit, MeasurementQCResult, Device, ExternalAPI
from services.measurement_aggregation import (
    MeasurementAggregationError,
    execute_measurement_aggregation,
)
from services.data_attribution import serialize_data_attribution
from services.measurement_qc import qc_summary, public_qc_detail

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
    hours: int = Query(24, ge=1, le=24 * 365 * 5, description="Window size in hours if start is not provided"),
    aggregate: str | None = Query(None, description="Legacy response shape: raw | hour | day"),
    aggregation: str | None = Query(None, description="Canonical aggregation period code"),
    start: datetime | None = Query(None, description="Start datetime (ISO8601 UTC); if provided, overrides 'hours'"),
    end: datetime | None = Query(None, description="End datetime (ISO8601 UTC); defaults to the current evaluation time"),
    include_invalid: bool = Query(False, description="Include invalid measurements that failed QC"),
    include_qc: bool = Query(False, description="Include recorded QC outcome summaries for native/raw points"),
    session: Session = Depends(get_session)
):
    """Return time series data for a specific sensor over the past N hours.
    
    Returns measurements ordered by observed_at ascending (oldest first).
    """
    try:
        from datetime import datetime as _dt, timedelta, timezone

                         
        now_utc = _dt.now(timezone.utc)
        if start and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        # Bound relative history at one evaluation instant, while honoring an
        # explicitly requested end (including future ranges for investigation).
        if not end:
            end = now_utc
        window_start = start if start else (now_utc - timedelta(hours=hours))

                                                           
        meta_row = session.execute(
            select(
                Sensor.sensor_id,
                Parameter.code.label("parameter_code"),
                Parameter.display_name.label("parameter_name"),
                Unit.symbol.label("unit_symbol"),
                Device.name.label("device_name"),
                Device.friendly_name.label("device_friendly_name"),
                Device.device_id.label("device_id"),
                Device.latitude.label("latitude"),
                Device.longitude.label("longitude"),
                Device.manual_data_source_name.label("manual_data_source_name"),
                ExternalAPI.name.label("external_api_name"),
                Sensor.external_sensor_id.label("external_sensor_id"),
                Device.timezone.label("device_timezone"),
                Device.acquisition_path,
                Device.hardware_provider_name,
                Device.provider_url,
                Device.contributor_name,
                Device.contributor_url,
                Device.license_code,
                Device.license_url,
                Device.license_share_alike,
                AggregationPeriod.code.label("native_aggregation_code"),
                Sensor.expected_frequency_seconds.label("expected_frequency_seconds"),
                Sensor.measurement_duration_seconds.label("measurement_duration_seconds"),
                Sensor.source_aggregation_duration_seconds.label("source_aggregation_duration_seconds"),
                Sensor.measurement_timestamp_semantics.label("measurement_timestamp_semantics"),
                Sensor.acquisition_metadata,
            )
            .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
            .outerjoin(Unit, Sensor.unit_id == Unit.unit_id)
            .join(Device, Sensor.device_id == Device.device_id)
            .outerjoin(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id)
            .outerjoin(AggregationPeriod, Sensor.aggregation_period_id == AggregationPeriod.aggregation_period_id)
            .where(Sensor.sensor_id == sensor_id)
        ).first()
        if not meta_row:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")
        public_source_name = _resolve_public_source_name(
            getattr(meta_row, "manual_data_source_name", None),
            getattr(meta_row, "external_api_name", None),
        )

                            
        time_filters = [
            Measurement.observed_at >= window_start,
            Measurement.observed_at <= end,
        ]

        normalized_aggregate = (aggregate or "").strip().lower()
        raw_aggregate_aliases = {"raw", "latest"}
        if normalized_aggregate and normalized_aggregate not in raw_aggregate_aliases | {"hour", "day"}:
            raise HTTPException(status_code=400, detail="Invalid aggregate; use raw|hour|day")

        legacy_to_canonical = {"raw": "raw", "latest": "raw", "hour": "1h", "day": "24h"}
        canonical_aggregation = (aggregation or "").strip().lower()
        legacy_canonical = legacy_to_canonical.get(normalized_aggregate) if normalized_aggregate else None
        if canonical_aggregation and legacy_canonical and canonical_aggregation != legacy_canonical:
            raise HTTPException(
                status_code=400,
                detail="Conflicting aggregate and aggregation query parameters",
            )
        requested_aggregation = canonical_aggregation or legacy_canonical or "1h"
        native_aggregation_code = getattr(meta_row, "native_aggregation_code", None)
        try:
            shared_points = execute_measurement_aggregation(
                session,
                sensor_ids=[sensor_id],
                parameter_code=meta_row.parameter_code,
                native_aggregation_code=native_aggregation_code,
                result_aggregation_code=requested_aggregation,
                since=window_start,
                until=end,
                include_invalid=include_invalid,
                latest_only=False,
            )
        except MeasurementAggregationError as exc:
            raise HTTPException(
                status_code=400,
                detail={"reason": exc.reason, "message": str(exc)},
            ) from exc

        uses_raw_measurements = requested_aggregation in {
            "raw",
            (native_aggregation_code or "").lower(),
        }
        qc_by_measurement: dict[int, list[dict]] = {}
        if include_qc and uses_raw_measurements:
            measurement_ids = [point.measurement_id for point in shared_points if point.measurement_id]
            if measurement_ids:
                qc_rows = session.execute(
                    select(
                        MeasurementQCResult.measurement_id,
                        MeasurementQCResult.check_code,
                        MeasurementQCResult.severity,
                        MeasurementQCResult.message,
                        MeasurementQCResult.evaluation_status,
                        MeasurementQCResult.passed,
                        MeasurementQCResult.failure_action,
                        MeasurementQCResult.reason_code,
                    ).join(Measurement, Measurement.measurement_id == MeasurementQCResult.measurement_id)
                    .where(Measurement.sensor_id == sensor_id, *time_filters,
                           *([] if include_invalid else [Measurement.is_valid.is_(True)]))
                    .order_by(MeasurementQCResult.measurement_id, MeasurementQCResult.check_code)
                ).all()
                for row in qc_rows:
                    qc_by_measurement.setdefault(row.measurement_id, []).append({**qc_summary(row), "message": row.message})

        response_aggregate = normalized_aggregate or requested_aggregation
        history_status = "available"
        if not shared_points:
            has_observations = session.scalar(
                select(Measurement.measurement_id)
                .where(Measurement.sensor_id == sensor_id, *time_filters)
                .limit(1)
            ) is not None
            history_status = "no_eligible_observations" if has_observations else "no_observations"
        return {
            "sensor_id": sensor_id,
            "parameter": meta_row.parameter_code,
            "parameter_name": meta_row.parameter_name,
            "unit": meta_row.unit_symbol,
            "aggregate": response_aggregate,
            "history_status": history_status,
            "includes_invalid": include_invalid,
            "qc_scope": "native" if uses_raw_measurements else "aggregate",
            "native_aggregation_code": native_aggregation_code,
            "result_aggregation_code": (
                shared_points[0].result_aggregation_code if shared_points else requested_aggregation
            ),
            "formatting_status": (
                shared_points[0].formatting_status if shared_points else "not_configured"
            ),
            "display_precision": shared_points[0].display_precision if shared_points else None,
            **({"hours": hours} if not start else {}),
            **({"start": start.isoformat(), "end": (end.isoformat() if end else None)} if start else {}),
            "device_name": meta_row.device_name,
            "device_friendly_name": meta_row.device_friendly_name,
            "device_id": meta_row.device_id,
            "latitude": meta_row.latitude,
            "longitude": meta_row.longitude,
            "device_timezone": meta_row.device_timezone,
            "external_sensor_id": meta_row.external_sensor_id,
            "external_api": ({"name": public_source_name} if public_source_name is not None else None),
            "data_attribution": serialize_data_attribution(
                acquisition_path=meta_row.acquisition_path,
                data_provider_name=public_source_name,
                hardware_provider_name=meta_row.hardware_provider_name,
                provider_url=meta_row.provider_url,
                contributor_name=meta_row.contributor_name,
                contributor_url=meta_row.contributor_url,
                license_code=meta_row.license_code,
                license_url=meta_row.license_url,
                license_share_alike=meta_row.license_share_alike,
            ),
            "expected_frequency_seconds": meta_row.expected_frequency_seconds,
            "measurement_duration_seconds": meta_row.measurement_duration_seconds,
            "source_aggregation_duration_seconds": meta_row.source_aggregation_duration_seconds,
            "measurement_timestamp_semantics": meta_row.measurement_timestamp_semantics,
            "acquisition_metadata": meta_row.acquisition_metadata,
            "data": [
                {
                    "measurement_id": point.measurement_id or None,
                    "timestamp": point.observed_at.isoformat() if point.observed_at else None,
                    "value": point.value,
                    "is_valid": point.invalid_sample_count == 0,
                    "qc_flags": point.qc_flags,
                    "interval_started_at": (
                        point.interval_started_at.isoformat() if point.interval_started_at else None
                    ),
                    "interval_ended_at": (
                        point.interval_ended_at.isoformat() if point.interval_ended_at else None
                    ),
                    "sample_count": point.sample_count,
                    "valid_sample_count": point.valid_sample_count,
                    "invalid_sample_count": point.invalid_sample_count,
                    **(
                        {
                            "qc_results": [{key: value for key, value in result.items() if key != "message"}
                                           for result in qc_by_measurement.get(point.measurement_id, [])],
                            "qc_provenance_status": (
                                "source_details_unavailable" if not uses_raw_measurements else
                                "recorded" if qc_by_measurement.get(point.measurement_id) else "not_recorded"
                            ),
                            # Retain the existing compact contract for older consumers.
                            "failed_checks": [{key: result[key] for key in ("check_code", "severity", "message")}
                                              for result in qc_by_measurement.get(point.measurement_id, [])
                                              if result["evaluation_status"] == "failed"],
                        }
                        if include_qc
                        else {}
                    ),
                }
                for point in shared_points
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get sensor history for sensor_id=%s", sensor_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sensors/{sensor_id}/measurements/{measurement_id}/qc")
def get_measurement_qc(sensor_id: int, measurement_id: int, session: Session = Depends(get_session)):
    """Same public visibility as history, with only safe recorded policy fields.

    Two indexed queries, independent of history length. The composite QC unique
    index starts with measurement_id. No current rule/plugin settings are read.
    """
    measurement = session.scalar(select(Measurement).where(
        Measurement.sensor_id == sensor_id, Measurement.measurement_id == measurement_id,
    ))
    if measurement is None:
        raise HTTPException(status_code=404, detail="Measurement not found for this sensor")
    results = session.scalars(select(MeasurementQCResult).where(
        MeasurementQCResult.measurement_id == measurement_id,
    ).order_by(MeasurementQCResult.check_code)).all()
    return {
        "measurement_id": measurement_id, "sensor_id": sensor_id,
        "timestamp": measurement.observed_at, "value": measurement.value,
        "is_valid": measurement.is_valid,
        "qc_provenance_status": "recorded" if results else "not_recorded",
        "qc_results": [public_qc_detail(result) for result in results],
    }
