"""
Setup Wizard API routes.

Provides endpoints for the first-run setup wizard:
- Check if system setup is required
- Create initial admin account
- Configure external API keys
- Configure Geoapify API key
- Complete system setup

These endpoints are PUBLIC (no auth required) until setup is complete.
Once setup is complete, most endpoints become inaccessible.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, List, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from services.user_identity import CanonicalEmail
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from db import get_session
from models import ExternalAPI, Role, User, UserRole
from services.system_settings import (
    DEFAULT_SYSTEM_TIMEZONE,
    get_or_create_system_settings,
    is_system_setup_complete,
    resolve_default_language_code,
)
from services.timezone import IanaTimezoneError, resolve_iana_timezone
from services.auth import hash_password, validate_password_policy
from services.external_sources import derive_external_source_state, source_requires_credential
from api.user_messages import user_message_detail
from sources.demo.importer import import_current_slot


router = APIRouter(prefix="/setup", tags=["setup"])
logger = logging.getLogger(__name__)
SETUP_ADMIN_ADVISORY_LOCK_ID = 90126001


class SetupStatusResponse(BaseModel):
    """Response indicating whether setup is required."""
    is_setup_required: bool
    has_users: bool
    default_language_code: Literal["en", "es"]


class ExternalAPIInfo(BaseModel):
    """External API info for setup wizard (no sensitive data)."""
    external_api_id: int
    provider_code: Optional[str]
    name: str
    description: Optional[str] = None
    requires_credential: bool
    has_api_key: bool
    enabled: bool
    is_configured: bool
    is_runnable: bool
    runnable_reason: str
    import_authenticated_locations: bool = False


class AvailableDataSourcesResponse(BaseModel):
    """List of available data sources for configuration."""
    data_sources: List[ExternalAPIInfo]


class CreateAdminRequest(BaseModel):
    """Request body for creating the initial admin account."""
    email: CanonicalEmail
    password: str
    confirm_password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError('Password must be at least 12 characters long')
        return v


class CreateAdminResponse(BaseModel):
    """Response after creating the admin account."""
    success: bool
    user_id: str
    email: str
    message: str
    message_code: str
    message_context: dict[str, Any] = Field(default_factory=dict)


class ConfigureDataSourceRequest(BaseModel):
    """Request body for saving setup-time source intent and credentials."""
    external_api_id: int
    api_key: Optional[str] = None
    enabled: bool = False
    import_authenticated_locations: bool = False
    model_config = ConfigDict(extra="forbid")


class ConfigureDataSourceResponse(BaseModel):
    """Response after configuring a data source."""
    success: bool
    message: str
    message_code: str
    message_context: dict[str, Any] = Field(default_factory=dict)
    is_configured: bool


class ConfigureGeoapifyRequest(BaseModel):
    """Request body for configuring Geoapify API key."""
    api_key: str


class ConfigureGeoapifyResponse(BaseModel):
    """Response after configuring Geoapify."""
    success: bool
    message: str
    message_code: str
    message_context: dict[str, Any] = Field(default_factory=dict)


class CompleteSetupRequest(BaseModel):
    """Request body that confirms setup defaults from the setup browser."""
    default_language_code: Literal["en", "es"]
    system_timezone: str | None = None


class CompleteSetupResponse(BaseModel):
    """Response after completing setup."""
    success: bool
    message: str
    message_code: str
    message_context: dict[str, Any] = Field(default_factory=dict)


def _is_setup_complete(session: Session) -> bool:
    """Read the authoritative persisted setup-complete marker."""
    return is_system_setup_complete(session)


def _has_any_users(session: Session) -> bool:
    """Check if any user accounts exist."""
    count = session.execute(select(func.count()).select_from(User)).scalar()
    return count > 0


def _ensure_setup_not_complete(session: Session) -> None:
    """Raise 403 if setup is already complete."""
    if _is_setup_complete(session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=user_message_detail(
                "setup_already_completed",
                "System setup has already been completed",
            ),
        )


def _lock_initial_admin_creation(session: Session) -> None:
    """Serialize first-admin creation when PostgreSQL is in use.

    SQLite remains used by lightweight unit tests and does not support
    PostgreSQL advisory locks. Direct Windows/Linux and Docker production paths
    use PostgreSQL, so they receive the race-safe lock.
    """
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": SETUP_ADMIN_ADVISORY_LOCK_ID},
        )


def _get_admin_role(session: Session) -> Role:
    """Get the admin role, creating it if needed."""
    role = session.execute(
        select(Role).where(Role.name == "admin")
    ).scalar_one_or_none()
    if not role:
        role = Role(
            role_id=uuid.uuid4(),
            name="admin",
            description="Administrative access",
        )
        session.add(role)
        session.flush()
    return role


@router.get("/status", response_model=SetupStatusResponse)
def get_setup_status(session: Session = Depends(get_session)) -> SetupStatusResponse:
    settings = get_or_create_system_settings(session)
    has_users = _has_any_users(session)
    return SetupStatusResponse(
        is_setup_required=not is_system_setup_complete(session),
        has_users=has_users,
        default_language_code=resolve_default_language_code(
            settings.default_language_code
        ),
    )


@router.get("/data-sources", response_model=AvailableDataSourcesResponse)
def list_data_sources(session: Session = Depends(get_session)) -> AvailableDataSourcesResponse:
    _ensure_setup_not_complete(session)
    rows = session.execute(
        select(ExternalAPI).order_by(ExternalAPI.name)
    ).scalars().all()
    data_sources = []
    for row in rows:
        source_state = derive_external_source_state(row)
        data_sources.append(ExternalAPIInfo(
            external_api_id=row.external_api_id,
            provider_code=row.provider_code,
            name=row.name,
            description=row.description,
            has_api_key=bool(row.api_key and row.api_key.strip()),
            requires_credential=source_requires_credential(row),
            enabled=row.enabled,
            is_configured=source_state.is_configured,
            is_runnable=source_state.is_runnable,
            runnable_reason=source_state.runnable_reason.value,
            import_authenticated_locations=(row.params or {}).get("import_authenticated_locations", False),
        ))
    return AvailableDataSourcesResponse(data_sources=data_sources)


@router.post("/admin", response_model=CreateAdminResponse)
def create_initial_admin(
    payload: CreateAdminRequest,
    session: Session = Depends(get_session),
) -> CreateAdminResponse:
    """Create the one and only unauthenticated first-run administrator."""
    _ensure_setup_not_complete(session)
    _lock_initial_admin_creation(session)

    if _has_any_users(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=user_message_detail(
                "setup_admin_already_created",
                "The initial administrator account has already been created",
            ),
        )

    if payload.password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_message_detail(
                "password_confirmation_mismatch",
                "Password and confirmation do not match",
            ),
        )

    try:
        validate_password_policy(payload.password, email=payload.email)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_message_detail("password_policy_not_met", str(exc)),
        )

    admin_role = _get_admin_role(session)
    default_org_id = uuid.uuid4()
    user = User(
        user_id=uuid.uuid4(),
        email=payload.email,
        password_hash=hash_password(payload.password),
        org_id=default_org_id,
        is_active=True,
    )
    session.add(user)
    session.flush()
    session.add(UserRole(user_id=user.user_id, role_id=admin_role.role_id))
    session.commit()

    return CreateAdminResponse(
        success=True,
        user_id=str(user.user_id),
        email=user.email,
        message="Admin account created successfully",
        message_code="setup_admin_created",
    )


@router.post("/data-source", response_model=ConfigureDataSourceResponse)
def configure_data_source(
    payload: ConfigureDataSourceRequest,
    session: Session = Depends(get_session),
) -> ConfigureDataSourceResponse:
    _ensure_setup_not_complete(session)
    external_api = session.get(ExternalAPI, payload.external_api_id)
    if not external_api:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=user_message_detail(
                "data_source_not_found",
                f"External API with ID {payload.external_api_id} not found",
                error_context={"external_api_id": payload.external_api_id},
            ),
        )
    if "api_key" in payload.model_fields_set:
        external_api.api_key = payload.api_key.strip() if payload.api_key else None
    external_api.enabled = payload.enabled
    if external_api.provider_code == "airgradient":
        external_api.params = {
            **(external_api.params or {}),
            "import_authenticated_locations": payload.import_authenticated_locations,
        }
    session.add(external_api)
    session.commit()
    source_state = derive_external_source_state(external_api)
    return ConfigureDataSourceResponse(
        success=True,
        message=f"Data source configuration saved for {external_api.name}",
        message_code="setup_data_source_configured",
        message_context={"provider_name": external_api.name},
        is_configured=source_state.is_configured,
    )


@router.post("/geoapify", response_model=ConfigureGeoapifyResponse)
def configure_geoapify(
    payload: ConfigureGeoapifyRequest,
    session: Session = Depends(get_session),
) -> ConfigureGeoapifyResponse:
    _ensure_setup_not_complete(session)
    api_key = payload.api_key.strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_message_detail("api_key_required", "API key cannot be empty"),
        )
    settings = get_or_create_system_settings(session)
    settings.geoapify_api_key = api_key
    settings.updated_at = datetime.now(timezone.utc)
    session.add(settings)
    session.commit()
    return ConfigureGeoapifyResponse(
        success=True,
        message="Geoapify API key configured successfully",
        message_code="setup_geoapify_configured",
    )


@router.post("/complete", response_model=CompleteSetupResponse)
def complete_setup(
    payload: CompleteSetupRequest,
    session: Session = Depends(get_session),
) -> CompleteSetupResponse:
    _ensure_setup_not_complete(session)
    if not _has_any_users(session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_message_detail(
                "setup_admin_required",
                "Cannot complete setup without creating an admin account",
            ),
        )
    settings = get_or_create_system_settings(session)
    settings.default_language_code = payload.default_language_code
    try:
        settings.system_timezone = (
            resolve_iana_timezone(
                payload.system_timezone,
                field_label="System timezone",
            ).key
            if payload.system_timezone is not None
            else DEFAULT_SYSTEM_TIMEZONE
        )
    except IanaTimezoneError:
        settings.system_timezone = DEFAULT_SYSTEM_TIMEZONE
    settings.is_system_setup_complete = True
    session.add(settings)
    session.commit()
    # Setup is authoritative before optional sample ingestion starts. A failed
    # import rolls back only its observations/state, leaving scheduler retry due.
    try:
        demo = session.scalar(select(ExternalAPI).where(
            ExternalAPI.provider_code == "demo",
            ExternalAPI.enabled.is_(True),
        ))
        if demo is not None:
            summary = import_current_slot(session, now=datetime.now(timezone.utc))
            session.commit()
            logger.info("Demo initialization after setup: %s", summary)
    except Exception:
        session.rollback()
        logger.exception("Demo initialization failed after setup completion; scheduler can retry")
    return CompleteSetupResponse(
        success=True,
        message="System setup completed successfully. You can now log in with your admin account.",
        message_code="setup_completed",
    )
