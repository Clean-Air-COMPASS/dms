from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, literal, or_, select
from sqlalchemy.orm import Session

from api.routes.admin.history import HistoryPage, history_bounds
from db import get_session
from models import (
    Device,
    Event,
    ExternalAPI,
    Measurement,
    MeasurementQCResult,
    Parameter,
    Sensor,
    Unit,
)
from qaqc.admin_policy import get_check_metadata
from services.administrator_summary_domain import qc_check_display_name
from services.event_log import get_event_table_column_names

router = APIRouter(prefix="/admin", tags=["admin"])


class EventOut(BaseModel):
    event_id: int
    event_type: str
    source: str
    severity: str
    actor_user_id: Optional[str] = None
    actor_email: Optional[str] = None
    actor_display_name: Optional[str] = None
    device_id: Optional[int] = None
    sensor_id: Optional[int] = None
    external_sensor_id: Optional[str] = None
    endpoint: Optional[str] = None
    params: Optional[dict] = None
    message: Optional[str] = None
    raw_snippet: Optional[str] = None
    created_at: Optional[str] = None


class QCFailureOut(BaseModel):
    measurement_qc_result_id: int
    qc_result_created_at: datetime
    measurement_id: int
    measurement_observed_at: datetime | None
    measurement_value: float
    measurement_is_valid: bool
    device_id: int
    device_name: str
    sensor_id: int
    external_sensor_id: str | None
    data_source_id: int
    data_source_name: str
    provider_code: str | None
    parameter_code: str | None
    parameter_name: str | None
    unit_code: str | None
    unit_symbol: str | None
    check_code: str
    check_name: str
    plugin_version: str | None
    evaluation_status: Literal["failed", "indeterminate"]
    failure_action: Literal["flag_for_review", "mark_invalid"] | None
    reason_code: str | None
    message: str | None
    details: dict[str, Any] | None
    params_snapshot: dict[str, Any] | None
    rule_source: str | None
    policy_snapshot: dict[str, Any] | None
    policy_provenance: dict[str, Any] | None


class QCFailureListOut(BaseModel):
    items: list[QCFailureOut]
    total: int
    limit: int
    offset: int


@router.get("/events", response_model=List[EventOut] | HistoryPage[EventOut])
def list_events(
    limit: int = Query(100, ge=1, le=1000),
    severity: Optional[str] = Query(None, description="Filter by severity: info, warning, error"),
    source: Optional[str] = Query(None, description="Filter by source"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    offset: Annotated[int, Query(ge=0)] = 0,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    paginated: bool = False,
    session: Session = Depends(get_session)
):
    started_after, started_before = history_bounds(started_after, started_before)
    try:
        event_table = Event.__table__
        available_columns = get_event_table_column_names(session)

        actor_user_id_column = (
            event_table.c.actor_user_id
            if "actor_user_id" in available_columns
            else literal(None).label("actor_user_id")
        )
        actor_email_column = (
            event_table.c.actor_email
            if "actor_email" in available_columns
            else literal(None).label("actor_email")
        )
        actor_display_name_column = (
            event_table.c.actor_display_name
            if "actor_display_name" in available_columns
            else literal(None).label("actor_display_name")
        )

        stmt = (
            select(
                event_table.c.event_id,
                event_table.c.event_type,
                event_table.c.source,
                event_table.c.severity,
                actor_user_id_column,
                actor_email_column,
                actor_display_name_column,
                event_table.c.device_id,
                event_table.c.sensor_id,
                event_table.c.external_sensor_id,
                event_table.c.endpoint,
                event_table.c.params,
                event_table.c.message,
                event_table.c.raw_snippet,
                event_table.c.created_at,
            )
            .select_from(event_table)
            .order_by(event_table.c.created_at.desc(), event_table.c.event_id.desc())
        )
        if severity:
            stmt = stmt.where(event_table.c.severity == severity)
        if source:
            stmt = stmt.where(event_table.c.source == source)
        if event_type:
            stmt = stmt.where(event_table.c.event_type == event_type)
        if started_after:
            stmt = stmt.where(Event.created_at >= started_after)
        if started_before:
            stmt = stmt.where(Event.created_at < started_before)
        total = 0
        options = {}
        if paginated:
            total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
            options["event_type"] = list(session.scalars(select(Event.event_type).distinct().order_by(Event.event_type)).all())
            options["source"] = list(session.scalars(select(Event.source).distinct().order_by(Event.source)).all())
            options["severity"] = list(session.scalars(select(Event.severity).distinct().order_by(Event.severity)).all())
        stmt = stmt.offset(offset).limit(limit)

        rows = session.execute(stmt).mappings().all()
        items = [
            EventOut(
                event_id=r["event_id"],
                event_type=r["event_type"],
                source=r["source"],
                severity=r["severity"],
                actor_user_id=(str(r["actor_user_id"]) if r["actor_user_id"] is not None else None),
                actor_email=r["actor_email"],
                actor_display_name=r["actor_display_name"] or r["actor_email"] or (str(r["actor_user_id"]) if r["actor_user_id"] else None),
                device_id=r["device_id"],
                sensor_id=r["sensor_id"],
                external_sensor_id=r["external_sensor_id"],
                endpoint=r["endpoint"],
                params=r["params"],
                message=r["message"],
                raw_snippet=r["raw_snippet"],
                created_at=(r["created_at"].isoformat() if r["created_at"] is not None else None),
            )
            for r in rows
        ]
        return HistoryPage(items=items, total=total, options=options) if paginated else items
    except Exception:
        raise HTTPException(status_code=500, detail={"error_code": "events_unavailable"}) from None


@router.get("/events/qc-failures", response_model=QCFailureListOut)
def list_qc_failures(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, min_length=1, max_length=200),
    parameter: str | None = Query(None, min_length=1, max_length=32),
    status: Literal["failed", "indeterminate"] | None = Query(None),
    outcome: Literal["flag_for_review", "mark_invalid"] | None = Query(None),
    data_source: str | None = Query(None, min_length=1, max_length=120),
    session: Session = Depends(get_session),
) -> QCFailureListOut:
    """Return durable failed and indeterminate ingest QC results.

    The query is intentionally sourced from ``MeasurementQCResult``. Normal
    passes are excluded, while an effect filter is limited to failed rows so
    an indeterminate result is never presented as an action taken on a
    measurement.
    """
    joins = (
        MeasurementQCResult.__table__
        .join(
            Measurement.__table__,
            Measurement.measurement_id == MeasurementQCResult.measurement_id,
        )
        .join(Sensor.__table__, Sensor.sensor_id == Measurement.sensor_id)
        .join(Device.__table__, Device.device_id == Sensor.device_id)
        .join(
            ExternalAPI.__table__,
            ExternalAPI.external_api_id == Device.external_api_id,
        )
        .outerjoin(
            Parameter.__table__,
            Parameter.parameter_id
            == func.coalesce(MeasurementQCResult.parameter_id, Sensor.parameter_id),
        )
        .outerjoin(Unit.__table__, Unit.unit_id == Sensor.unit_id)
    )
    conditions = [
        MeasurementQCResult.evaluation_status.in_(
            ("failed", "indeterminate")
        ),
        # Older rows can carry a legacy passed=True value alongside the
        # post-foundation default evaluation_status. They are not issues.
        MeasurementQCResult.passed.is_not(True),
    ]

    if status:
        conditions.append(MeasurementQCResult.evaluation_status == status)

    if parameter:
        conditions.append(Parameter.code == parameter.strip())
    if outcome:
        conditions.extend(
            [
                MeasurementQCResult.evaluation_status == "failed",
                MeasurementQCResult.failure_action == outcome,
            ]
        )
    if data_source:
        normalized_data_source = data_source.strip()
        conditions.append(
            or_(
                Device.manual_data_source_name == normalized_data_source,
                (Device.manual_data_source_name.is_(None)) & (
                    (ExternalAPI.provider_code == normalized_data_source)
                    | (ExternalAPI.name == normalized_data_source)
                ),
            )
        )
    if search:
        search_term = search.strip()
        search_pattern = f"%{search_term}%"
        internal_id = int(search_term) if search_term.isascii() and search_term.isdecimal() and len(search_term) <= 10 else None
        if internal_id is not None and not 1 <= internal_id <= 2_147_483_647:
            internal_id = None
        conditions.append(
            or_(
                Device.name.ilike(search_pattern),
                Device.friendly_name.ilike(search_pattern),
                Device.manual_data_source_name.ilike(search_pattern),
                Sensor.external_sensor_id.ilike(search_pattern),
                Sensor.sensor_id == internal_id if internal_id is not None else False,
                Device.device_id == internal_id if internal_id is not None else False,
                ExternalAPI.name.ilike(search_pattern),
                ExternalAPI.provider_code.ilike(search_pattern),
                Parameter.code.ilike(search_pattern),
                Parameter.display_name.ilike(search_pattern),
                MeasurementQCResult.check_code.ilike(search_pattern),
                MeasurementQCResult.message.ilike(search_pattern),
                MeasurementQCResult.reason_code.ilike(search_pattern),
            )
        )

    total = int(
        session.scalar(
            select(func.count()).select_from(joins).where(*conditions)
        )
        or 0
    )
    rows = session.execute(
        select(
            MeasurementQCResult,
            Measurement,
            Sensor,
            Device,
            ExternalAPI,
            Parameter,
            Unit,
        )
        .select_from(joins)
        .where(*conditions)
        .order_by(
            MeasurementQCResult.created_at.desc(),
            MeasurementQCResult.measurement_qc_result_id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

    check_names = {
        check["check_code"]: check["display_name"]
        for check in get_check_metadata()
    }
    items = []
    for qc_result, measurement, sensor, device, source, result_parameter, unit in rows:
        items.append(
            QCFailureOut(
                measurement_qc_result_id=qc_result.measurement_qc_result_id,
                qc_result_created_at=qc_result.created_at,
                measurement_id=measurement.measurement_id,
                measurement_observed_at=measurement.observed_at,
                measurement_value=measurement.value,
                measurement_is_valid=measurement.is_valid,
                device_id=device.device_id,
                device_name=device.friendly_name or device.name,
                sensor_id=sensor.sensor_id,
                external_sensor_id=sensor.external_sensor_id,
                data_source_id=source.external_api_id,
                data_source_name=device.manual_data_source_name or source.name,
                provider_code=None if device.manual_data_source_name else source.provider_code,
                parameter_code=(result_parameter.code if result_parameter else None),
                parameter_name=(
                    result_parameter.display_name if result_parameter else None
                ),
                unit_code=(unit.code if unit else None),
                unit_symbol=(unit.symbol if unit else None),
                check_code=qc_result.check_code,
                check_name=qc_check_display_name(
                    qc_result.check_code,
                    "en",
                    fallback=check_names.get(qc_result.check_code),
                ),
                plugin_version=qc_result.plugin_version,
                evaluation_status=qc_result.evaluation_status,
                failure_action=qc_result.failure_action,
                reason_code=qc_result.reason_code,
                message=qc_result.message,
                details=qc_result.details,
                params_snapshot=qc_result.params_snapshot,
                rule_source=qc_result.rule_source,
                policy_snapshot=qc_result.policy_snapshot,
                policy_provenance=qc_result.policy_provenance,
            )
        )

    return QCFailureListOut(items=items, total=total, limit=limit, offset=offset)
