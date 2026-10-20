from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth_deps import CurrentUser, get_current_user
from api.user_messages import user_message_detail
from db import get_session
from models import EmailSettings, Event
from services.event_log import add_event
from services.system_settings import (
    DEFAULT_SYSTEM_TIMEZONE,
    get_or_create_system_settings,
    resolve_default_language_code,
)
from services.system_storage import get_storage_status
from services.timezone import IanaTimezoneError, resolve_iana_timezone

router = APIRouter(prefix="/admin/system-preferences", tags=["admin-system-preferences"])


class StorageStatusResponse(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_free: float
    status: Literal["healthy", "needs_attention", "critical"]


class SystemPreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    geoapify_api_key: Optional[str] = None
    default_language_code: Literal["en", "es"] = "en"
    system_timezone: str = DEFAULT_SYSTEM_TIMEZONE
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_updated_by_email: Optional[str] = None
    last_updated_by_display_name: Optional[str] = None
    last_updated_by_user_id: Optional[str] = None
    storage: StorageStatusResponse


class SystemPreferencesUpdateRequest(BaseModel):
    geoapify_api_key: Optional[str] = None
    default_language_code: Literal["en", "es"]
    # Optional during the compatibility window so older admin clients keep
    # their saved system timezone rather than resetting it to UTC.
    system_timezone: str | None = None


def _get_last_updated_actor(session: Session, settings) -> Event | None:
    if settings.updated_at is None:
        return None

    # The preference timestamp is assigned by the API while the event timestamp
    # uses the database default, so allow a small clock-skew window when linking
    # the singleton settings row to its existing audit event.
    return session.execute(
        select(Event)
        .where(
            Event.source == "admin.system_preferences",
            Event.event_type.in_([
                "system_preferences.geoapify_api_key.changed",
                "system_preferences.default_language_code.changed",
                "system_preferences.system_timezone.changed",
            ]),
            Event.actor_email.is_not(None),
            Event.created_at >= settings.updated_at - timedelta(minutes=5),
            Event.created_at <= settings.updated_at + timedelta(minutes=5),
        )
        .order_by(Event.created_at.desc(), Event.event_id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _serialize_system_preferences(session: Session, settings) -> SystemPreferencesResponse:
    storage = get_storage_status()
    actor_event = _get_last_updated_actor(session, settings)
    return SystemPreferencesResponse(
        geoapify_api_key=settings.geoapify_api_key,
        default_language_code=resolve_default_language_code(
            settings.default_language_code
        ),
        system_timezone=settings.system_timezone or DEFAULT_SYSTEM_TIMEZONE,
        created_at=settings.created_at.isoformat() if settings.created_at else None,
        updated_at=settings.updated_at.isoformat() if settings.updated_at else None,
        last_updated_by_email=actor_event.actor_email if actor_event else None,
        last_updated_by_display_name=(actor_event.actor_display_name or actor_event.actor_email) if actor_event else None,
        last_updated_by_user_id=str(actor_event.actor_user_id) if actor_event and actor_event.actor_user_id else None,
        storage=StorageStatusResponse(
            total_bytes=storage.total_bytes,
            used_bytes=storage.used_bytes,
            free_bytes=storage.free_bytes,
            percent_free=storage.percent_free,
            status=storage.status,
        ),
    )


def _normalize_secret_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed_value = value.strip()
    if not trimmed_value:
        return None
    return trimmed_value


def _describe_geoapify_change(previous_value: Optional[str], new_value: Optional[str]) -> tuple[str, str]:
    previous_present = bool(previous_value)
    new_present = bool(new_value)

    if not previous_present and new_present:
        return "created", "Geoapify API key created"
    if previous_present and not new_present:
        return "cleared", "Geoapify API key cleared"
    return "updated", "Geoapify API key updated"


def _normalize_system_timezone(value: str) -> str:
    try:
        return resolve_iana_timezone(value, field_label="System timezone").key
    except IanaTimezoneError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=user_message_detail(
                "invalid_system_timezone",
                str(exc),
                error_context={"field": "system_timezone"},
            ),
        ) from exc


@router.get("", response_model=SystemPreferencesResponse)
def get_system_preferences(
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> SystemPreferencesResponse:
    settings = get_or_create_system_settings(session)
    return _serialize_system_preferences(session, settings)


@router.put("", response_model=SystemPreferencesResponse)
def update_system_preferences(
    payload: SystemPreferencesUpdateRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> SystemPreferencesResponse:
    settings = get_or_create_system_settings(session)

    normalized_geoapify_api_key = _normalize_secret_value(payload.geoapify_api_key)
    existing_geoapify_api_key = settings.geoapify_api_key

    existing_default_language_code = settings.default_language_code
    existing_system_timezone = settings.system_timezone or DEFAULT_SYSTEM_TIMEZONE
    normalized_system_timezone = _normalize_system_timezone(
        payload.system_timezone
        if payload.system_timezone is not None
        else existing_system_timezone
    )

    if (
        normalized_geoapify_api_key == existing_geoapify_api_key
        and payload.default_language_code == existing_default_language_code
        and normalized_system_timezone == existing_system_timezone
    ):
        return _serialize_system_preferences(session, settings)

    settings.geoapify_api_key = normalized_geoapify_api_key
    settings.default_language_code = payload.default_language_code
    settings.system_timezone = normalized_system_timezone
    changed_at = datetime.now(timezone.utc)
    settings.updated_at = changed_at

    geoapify_changed = normalized_geoapify_api_key != existing_geoapify_api_key
    language_changed = payload.default_language_code != existing_default_language_code
    system_timezone_changed = normalized_system_timezone != existing_system_timezone

    if system_timezone_changed and not language_changed and not geoapify_changed:
        event_type = "system_preferences.system_timezone.changed"
        change_message = "System timezone updated"
        event_params = {
            "field": "system_timezone",
            "action": "updated",
            "previous_system_timezone": existing_system_timezone,
            "system_timezone": normalized_system_timezone,
        }
    elif language_changed and not geoapify_changed:
        change_action = "updated"
        change_message = "System default language updated"
        event_type = "system_preferences.default_language_code.changed"
        event_params = {
            "field": "default_language_code",
            "action": change_action,
            "previous_language_code": existing_default_language_code,
            "language_code": payload.default_language_code,
        }
    else:
        change_action, change_message = _describe_geoapify_change(
            previous_value=existing_geoapify_api_key,
            new_value=normalized_geoapify_api_key,
        )
        event_type = "system_preferences.geoapify_api_key.changed"
        event_params = {
            "field": "geoapify_api_key",
            "action": change_action,
        }

    # A summary-specific override owns its timezone. An inherited enabled
    # summary must observe a system change immediately, so reset only its
    # effective boundary; the nullable override remains NULL.
    summary_settings = session.get(EmailSettings, 1)
    if (
        system_timezone_changed
        and summary_settings is not None
        and summary_settings.administrator_summary_enabled
        and summary_settings.administrator_summary_reporting_timezone_override is None
    ):
        summary_settings.administrator_summary_effective_at = changed_at
        session.add(summary_settings)

    add_event(
        session,
        event_type=event_type,
        source="admin.system_preferences",
        severity="info",
        message=change_message,
        params=event_params,
        actor_user_id=current_user.user_id,
        actor_email=current_user.email,
    )

    session.add(settings)
    session.commit()
    session.refresh(settings)

    return _serialize_system_preferences(session, settings)
