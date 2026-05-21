from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from models import Event


def get_event_table_column_names(session: Session) -> set[str]:
    """
    Return the currently available columns on the event table.

    This keeps event reads and writes compatible with databases that have not
    applied the newest forward migration yet.
    """
    bind = session.get_bind()
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns("event")}


def add_event(
    session: Session,
    *,
    event_type: str,
    source: str,
    severity: str = "info",
    message: Optional[str] = None,
    params: Optional[dict] = None,
    device_id: Optional[int] = None,
    sensor_id: Optional[int] = None,
    external_sensor_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    raw_snippet: Optional[str] = None,
    actor_user_id: Optional[uuid.UUID] = None,
    actor_email: Optional[str] = None,
) -> Event:
    """
    Create an event row using the shared event table.

    Actor fields are stored directly on the event row so the log remains
    readable even if the user record is later deleted.
    """
    available_columns = get_event_table_column_names(session)

    event_kwargs = dict(
        event_type=event_type,
        source=source,
        severity=severity,
        message=message,
        params=params,
        device_id=device_id,
        sensor_id=sensor_id,
        external_sensor_id=external_sensor_id,
        endpoint=endpoint,
        raw_snippet=raw_snippet,
    )
    if "actor_user_id" in available_columns:
        event_kwargs["actor_user_id"] = actor_user_id
    if "actor_email" in available_columns:
        event_kwargs["actor_email"] = actor_email

    event = Event(**event_kwargs)
    session.add(event)
    return event
