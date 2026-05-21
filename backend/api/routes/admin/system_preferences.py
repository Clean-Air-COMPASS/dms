from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.auth_deps import CurrentUser, get_current_user
from db import get_session
from services.event_log import add_event
from services.system_settings import get_or_create_system_settings

router = APIRouter(prefix="/admin/system-preferences", tags=["admin-system-preferences"])


class SystemPreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    geoapify_api_key: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SystemPreferencesUpdateRequest(BaseModel):
    geoapify_api_key: Optional[str] = None


def _serialize_system_preferences(settings) -> SystemPreferencesResponse:
    return SystemPreferencesResponse(
        geoapify_api_key=settings.geoapify_api_key,
        created_at=settings.created_at.isoformat() if settings.created_at else None,
        updated_at=settings.updated_at.isoformat() if settings.updated_at else None,
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


@router.get("", response_model=SystemPreferencesResponse)
def get_system_preferences(
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> SystemPreferencesResponse:
    settings = get_or_create_system_settings(session)
    return _serialize_system_preferences(settings)


@router.put("", response_model=SystemPreferencesResponse)
def update_system_preferences(
    payload: SystemPreferencesUpdateRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> SystemPreferencesResponse:
    settings = get_or_create_system_settings(session)

    normalized_geoapify_api_key = _normalize_secret_value(payload.geoapify_api_key)
    existing_geoapify_api_key = settings.geoapify_api_key

    if normalized_geoapify_api_key == existing_geoapify_api_key:
        return _serialize_system_preferences(settings)

    settings.geoapify_api_key = normalized_geoapify_api_key
    settings.updated_at = datetime.now(timezone.utc)

    change_action, change_message = _describe_geoapify_change(
        previous_value=existing_geoapify_api_key,
        new_value=normalized_geoapify_api_key,
    )

    add_event(
        session,
        event_type="system_preferences.geoapify_api_key.changed",
        source="admin.system_preferences",
        severity="info",
        message=change_message,
        params={
            "field": "geoapify_api_key",
            "action": change_action,
        },
        actor_user_id=current_user.user_id,
        actor_email=current_user.email,
    )

    session.add(settings)
    session.commit()
    session.refresh(settings)

    return _serialize_system_preferences(settings)
