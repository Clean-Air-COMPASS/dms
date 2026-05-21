from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import literal, select
from sqlalchemy.orm import Session

from db import get_session
from models import Event
from services.event_log import get_event_table_column_names

router = APIRouter(prefix="/admin", tags=["admin"])


class EventOut(BaseModel):
    event_id: int
    event_type: str
    source: str
    severity: str
    actor_user_id: Optional[str] = None
    actor_email: Optional[str] = None
    device_id: Optional[int] = None
    sensor_id: Optional[int] = None
    external_sensor_id: Optional[str] = None
    endpoint: Optional[str] = None
    params: Optional[dict] = None
    message: Optional[str] = None
    raw_snippet: Optional[str] = None
    created_at: Optional[str] = None


@router.get("/events", response_model=List[EventOut])
def list_events(
    limit: int = Query(100, ge=1, le=1000),
    severity: Optional[str] = Query(None, description="Filter by severity: info, warning, error"),
    source: Optional[str] = Query(None, description="Filter by source"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    session: Session = Depends(get_session)
):
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

        stmt = (
            select(
                event_table.c.event_id,
                event_table.c.event_type,
                event_table.c.source,
                event_table.c.severity,
                actor_user_id_column,
                actor_email_column,
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
            .order_by(event_table.c.event_id.desc())
        )
        if severity:
            stmt = stmt.where(event_table.c.severity == severity)
        if source:
            stmt = stmt.where(event_table.c.source == source)
        if event_type:
            stmt = stmt.where(event_table.c.event_type == event_type)
        stmt = stmt.limit(limit)

        rows = session.execute(stmt).mappings().all()
        return [
            EventOut(
                event_id=r["event_id"],
                event_type=r["event_type"],
                source=r["source"],
                severity=r["severity"],
                actor_user_id=(str(r["actor_user_id"]) if r["actor_user_id"] is not None else None),
                actor_email=r["actor_email"],
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
