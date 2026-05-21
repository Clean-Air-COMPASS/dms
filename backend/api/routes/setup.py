"""
Setup Wizard API routes.

Provides endpoints for the first-run setup wizard:
- Check if system setup is required
- Create initial admin account
- Configure external API keys
- Configure Geoapify API key
- Verify API keys
- Complete system setup

These endpoints are PUBLIC (no auth required) until setup is complete.
Once setup is complete, most endpoints become inaccessible.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select, func
from sqlalchemy.orm import Session
import httpx

from db import get_session
from models import ExternalAPI, Role, User, UserRole
from services.system_settings import get_or_create_system_settings
from services.auth import hash_password, validate_password_policy


router = APIRouter(prefix="/setup", tags=["setup"])


                          

class SetupStatusResponse(BaseModel):
    """Response indicating whether setup is required."""
    is_setup_required: bool
    has_users: bool


class ExternalAPIInfo(BaseModel):
    """External API info for setup wizard (no sensitive data)."""
    external_api_id: int
    name: str
    description: Optional[str] = None
    has_api_key: bool


class AvailableDataSourcesResponse(BaseModel):
    """List of available data sources for configuration."""
    data_sources: List[ExternalAPIInfo]


class CreateAdminRequest(BaseModel):
    """Request body for creating the initial admin account."""
    email: EmailStr
    password: str
    confirm_password: str

    @field_validator('email')
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip()

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


class ConfigureDataSourceRequest(BaseModel):
    """Request body for configuring a data source API key."""
    external_api_id: int
    api_key: str
    confirm_api_key: str


class ConfigureDataSourceResponse(BaseModel):
    """Response after configuring a data source."""
    success: bool
    message: str


class VerifyApiKeyRequest(BaseModel):
    """Request body for verifying an external API key."""
    external_api_id: int
    api_key: str


class VerifyApiKeyResponse(BaseModel):
    """Response from API key verification."""
    success: bool
    message: str
    provider_name: Optional[str] = None


class ConfigureGeoapifyRequest(BaseModel):
    """Request body for configuring Geoapify API key."""
    api_key: str


class ConfigureGeoapifyResponse(BaseModel):
    """Response after configuring Geoapify."""
    success: bool
    message: str


class VerifyGeoapifyRequest(BaseModel):
    """Request body for verifying Geoapify API key."""
    api_key: str


class VerifyGeoapifyResponse(BaseModel):
    """Response from Geoapify verification."""
    success: bool
    message: str


class CompleteSetupRequest(BaseModel):
    """Request body to complete setup (optional)."""
    pass


class CompleteSetupResponse(BaseModel):
    """Response after completing setup."""
    success: bool
    message: str


                          

def _is_setup_complete(session: Session) -> bool:
    """Check if system setup has been completed."""
    settings = get_or_create_system_settings(session)
    return settings.is_system_setup_complete


def _has_any_users(session: Session) -> bool:
    """Check if any user accounts exist."""
    count = session.execute(select(func.count()).select_from(User)).scalar()
    return count > 0


def _ensure_setup_not_complete(session: Session) -> None:
    """Raise 403 if setup is already complete."""
    if _is_setup_complete(session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System setup has already been completed"
        )


def _get_admin_role(session: Session) -> Role:
    """Get the admin role, creating it if needed."""
    role = session.execute(
        select(Role).where(Role.name == "admin")
    ).scalar_one_or_none()
    
    if not role:
                                               
        role = Role(name="admin", description="Administrative access")
        session.add(role)
        session.commit()
        session.refresh(role)
    
    return role


                   

@router.get("/status", response_model=SetupStatusResponse)
def get_setup_status(session: Session = Depends(get_session)) -> SetupStatusResponse:
    """
    Check if system setup is required.
    
    Returns whether the setup wizard should be shown:
    - is_setup_required: True if setup has not been completed
    - has_users: True if any user accounts exist (for edge case handling)
    
    This endpoint is always accessible (no auth required).
    
    Note: For existing installations that already have users but haven't explicitly
    completed setup (e.g., upgraded from a previous version), we auto-mark setup
    as complete to avoid showing the wizard unnecessarily.
    """
    settings = get_or_create_system_settings(session)
    has_users = _has_any_users(session)
    
                                                               
                                                                          
                                                                       
                                                    
    if not settings.is_system_setup_complete and has_users:
        settings.is_system_setup_complete = True
        session.add(settings)
        session.commit()
    
    return SetupStatusResponse(
        is_setup_required=not settings.is_system_setup_complete,
        has_users=has_users
    )


@router.get("/data-sources", response_model=AvailableDataSourcesResponse)
def list_data_sources(session: Session = Depends(get_session)) -> AvailableDataSourcesResponse:
    """
    List available data sources for configuration.
    
    Returns external APIs that can be configured with API keys.
    Only accessible during setup (before setup is complete).
    """
    _ensure_setup_not_complete(session)
    
    rows = session.execute(
        select(ExternalAPI).order_by(ExternalAPI.name)
    ).scalars().all()
    
    data_sources = [
        ExternalAPIInfo(
            external_api_id=r.external_api_id,
            name=r.name,
            description=r.description,
            has_api_key=bool(r.api_key and r.api_key.strip())
        )
        for r in rows
    ]
    
    return AvailableDataSourcesResponse(data_sources=data_sources)


@router.post("/admin", response_model=CreateAdminResponse)
def create_initial_admin(
    payload: CreateAdminRequest,
    session: Session = Depends(get_session),
) -> CreateAdminResponse:
    """
    Create the initial admin account.
    
    This endpoint is only available during setup (before setup is complete).
    The created user will have the 'admin' role with full system access.
    
    Validation:
    - Password and confirm_password must match
    - Password must be at least 8 characters
    - Email must be unique (no existing user with same email)
    """
    _ensure_setup_not_complete(session)
    
                                    
    if payload.password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password and confirmation do not match"
        )

    try:
        validate_password_policy(payload.password, email=payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    
                                   
    existing_user = session.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists"
        )
    
                              
    admin_role = _get_admin_role(session)
    
                                                   
                                                                           
    default_org_id = uuid.uuid4()
    
                     
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        org_id=default_org_id,
        is_active=True,
    )
    session.add(user)
    session.flush()                   
    
                       
    user_role = UserRole(user_id=user.user_id, role_id=admin_role.role_id)
    session.add(user_role)
    
    session.commit()
    
    return CreateAdminResponse(
        success=True,
        user_id=str(user.user_id),
        email=user.email,
        message="Admin account created successfully"
    )


@router.post("/data-source", response_model=ConfigureDataSourceResponse)
def configure_data_source(
    payload: ConfigureDataSourceRequest,
    session: Session = Depends(get_session),
) -> ConfigureDataSourceResponse:
    """
    Configure an external data source with an API key.
    
    This endpoint is only available during setup.
    The API key will be stored in the external_api table.
    
    Validation:
    - api_key and confirm_api_key must match
    - external_api_id must exist
    """
    _ensure_setup_not_complete(session)
    
                               
    if payload.api_key != payload.confirm_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key and confirmation do not match"
        )
    
                          
    external_api = session.get(ExternalAPI, payload.external_api_id)
    if not external_api:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External API with ID {payload.external_api_id} not found"
        )
    
                       
    external_api.api_key = payload.api_key.strip()
    session.add(external_api)
    session.commit()
    
    return ConfigureDataSourceResponse(
        success=True,
        message=f"API key configured for {external_api.name}"
    )


@router.post("/verify-data-source", response_model=VerifyApiKeyResponse)
def verify_data_source_api_key(
    payload: VerifyApiKeyRequest,
    session: Session = Depends(get_session),
) -> VerifyApiKeyResponse:
    """
    Verify an external API key before saving.
    
    Makes a lightweight request to the provider to validate the key.
    Does NOT save the key - use /data-source endpoint to save.
    
    Supported providers:
    - OpenAQ: Check API status with key
    - PurpleAir: Check API key validity
    - AirGradient: Check API connectivity
    """
    _ensure_setup_not_complete(session)
    
                                                
    external_api = session.get(ExternalAPI, payload.external_api_id)
    if not external_api:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"External API with ID {payload.external_api_id} not found"
        )
    
    provider_name = external_api.name.lower()
    api_key = payload.api_key.strip()
    
    if not api_key:
        return VerifyApiKeyResponse(
            success=False,
            message="API key cannot be empty",
            provider_name=external_api.name
        )
    
    try:
        if "openaq" in provider_name:
            return _verify_openaq_key(api_key, external_api.name)
        elif "purpleair" in provider_name:
            return _verify_purpleair_key(api_key, external_api.name)
        elif "airgradient" in provider_name:
            return _verify_airgradient_key(api_key, external_api.name, external_api.base_url)
        else:
                                                                     
            return VerifyApiKeyResponse(
                success=True,
                message=f"API key format accepted for {external_api.name}. Note: This provider does not support automatic verification.",
                provider_name=external_api.name
            )
    except Exception as e:
        return VerifyApiKeyResponse(
            success=False,
            message=f"Verification failed: {str(e)}",
            provider_name=external_api.name
        )


def _verify_openaq_key(api_key: str, provider_name: str) -> VerifyApiKeyResponse:
    """Verify OpenAQ API key by making a test request."""
    try:
        with httpx.Client(timeout=15.0) as client:
                                             
            headers = {"X-API-Key": api_key}
                                                                   
            resp = client.get(
                "https://api.openaq.org/v3/parameters?limit=1",
                headers=headers
            )
            
            if resp.status_code == 200:
                return VerifyApiKeyResponse(
                    success=True,
                    message="OpenAQ API key is valid and working",
                    provider_name=provider_name
                )
            elif resp.status_code == 401 or resp.status_code == 403:
                return VerifyApiKeyResponse(
                    success=False,
                    message="Invalid API key. Please check your OpenAQ API key and try again.",
                    provider_name=provider_name
                )
            else:
                return VerifyApiKeyResponse(
                    success=False,
                    message=f"OpenAQ returned status {resp.status_code}. The service may be temporarily unavailable.",
                    provider_name=provider_name
                )
    except httpx.TimeoutException:
        return VerifyApiKeyResponse(
            success=False,
            message="Connection to OpenAQ timed out. Please try again.",
            provider_name=provider_name
        )
    except httpx.RequestError as e:
        return VerifyApiKeyResponse(
            success=False,
            message=f"Could not connect to OpenAQ: {str(e)}",
            provider_name=provider_name
        )


def _verify_purpleair_key(api_key: str, provider_name: str) -> VerifyApiKeyResponse:
    """Verify PurpleAir API key by making a test request."""
    try:
        with httpx.Client(timeout=15.0) as client:
                                             
            headers = {"X-API-Key": api_key}
                                                         
            resp = client.get(
                "https://api.purpleair.com/v1/keys",
                headers=headers
            )
            
            if resp.status_code == 200:
                data = resp.json()
                key_type = data.get("api_key_type", "unknown")
                return VerifyApiKeyResponse(
                    success=True,
                    message=f"PurpleAir API key is valid (type: {key_type})",
                    provider_name=provider_name
                )
            elif resp.status_code == 403:
                return VerifyApiKeyResponse(
                    success=False,
                    message="Invalid API key. Please check your PurpleAir API key and try again.",
                    provider_name=provider_name
                )
            else:
                return VerifyApiKeyResponse(
                    success=False,
                    message=f"PurpleAir returned status {resp.status_code}. The service may be temporarily unavailable.",
                    provider_name=provider_name
                )
    except httpx.TimeoutException:
        return VerifyApiKeyResponse(
            success=False,
            message="Connection to PurpleAir timed out. Please try again.",
            provider_name=provider_name
        )
    except httpx.RequestError as e:
        return VerifyApiKeyResponse(
            success=False,
            message=f"Could not connect to PurpleAir: {str(e)}",
            provider_name=provider_name
        )


def _verify_airgradient_key(api_key: str, provider_name: str, base_url: Optional[str]) -> VerifyApiKeyResponse:
    """Verify AirGradient API key by making a test request."""
    try:
        base = base_url or "https://api.airgradient.com/public/api"
        with httpx.Client(timeout=15.0) as client:
                                              
            resp = client.get(
                f"{base}/v1/locations",
                params={"token": api_key}
            )
            
            if resp.status_code == 200:
                return VerifyApiKeyResponse(
                    success=True,
                    message="AirGradient API key is valid and working",
                    provider_name=provider_name
                )
            elif resp.status_code == 401 or resp.status_code == 403:
                return VerifyApiKeyResponse(
                    success=False,
                    message="Invalid API key. Please check your AirGradient API token and try again.",
                    provider_name=provider_name
                )
            else:
                return VerifyApiKeyResponse(
                    success=False,
                    message=f"AirGradient returned status {resp.status_code}. The service may be temporarily unavailable.",
                    provider_name=provider_name
                )
    except httpx.TimeoutException:
        return VerifyApiKeyResponse(
            success=False,
            message="Connection to AirGradient timed out. Please try again.",
            provider_name=provider_name
        )
    except httpx.RequestError as e:
        return VerifyApiKeyResponse(
            success=False,
            message=f"Could not connect to AirGradient: {str(e)}",
            provider_name=provider_name
        )


@router.post("/geoapify", response_model=ConfigureGeoapifyResponse)
def configure_geoapify(
    payload: ConfigureGeoapifyRequest,
    session: Session = Depends(get_session),
) -> ConfigureGeoapifyResponse:
    """
    Configure the Geoapify API key for location search.
    
    This endpoint is only available during setup.
    The API key will be stored in the system_settings table.
    """
    _ensure_setup_not_complete(session)
    
    api_key = payload.api_key.strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key cannot be empty"
        )
    
    settings = get_or_create_system_settings(session)
    settings.geoapify_api_key = api_key
    settings.updated_at = datetime.now(timezone.utc)
    session.add(settings)
    session.commit()
    
    return ConfigureGeoapifyResponse(
        success=True,
        message="Geoapify API key configured successfully"
    )


@router.post("/verify-geoapify", response_model=VerifyGeoapifyResponse)
def verify_geoapify_api_key(
    payload: VerifyGeoapifyRequest,
    session: Session = Depends(get_session),
) -> VerifyGeoapifyResponse:
    """
    Verify a Geoapify API key before saving.
    
    Makes a lightweight geocoding request to validate the key.
    Does NOT save the key - use /geoapify endpoint to save.
    """
    _ensure_setup_not_complete(session)
    
    api_key = payload.api_key.strip()
    
    if not api_key:
        return VerifyGeoapifyResponse(
            success=False,
            message="API key cannot be empty"
        )
    
    try:
        with httpx.Client(timeout=15.0) as client:
                                                                  
            resp = client.get(
                "https://api.geoapify.com/v1/geocode/autocomplete",
                params={
                    "text": "test",
                    "limit": 1,
                    "apiKey": api_key
                }
            )
            
            if resp.status_code == 200:
                return VerifyGeoapifyResponse(
                    success=True,
                    message="Geoapify API key is valid. Location search will work."
                )
            elif resp.status_code == 401 or resp.status_code == 403:
                return VerifyGeoapifyResponse(
                    success=False,
                    message="Invalid API key. Please check your Geoapify API key and try again."
                )
            else:
                return VerifyGeoapifyResponse(
                    success=False,
                    message=f"Geoapify returned status {resp.status_code}. Please try again or check your key."
                )
    except httpx.TimeoutException:
        return VerifyGeoapifyResponse(
            success=False,
            message="Connection to Geoapify timed out. Please try again."
        )
    except httpx.RequestError as e:
        return VerifyGeoapifyResponse(
            success=False,
            message=f"Could not connect to Geoapify: {str(e)}"
        )


@router.post("/complete", response_model=CompleteSetupResponse)
def complete_setup(
    session: Session = Depends(get_session),
) -> CompleteSetupResponse:
    """
    Mark system setup as complete.
    
    Requirements:
    - At least one admin user must exist
    
    After this endpoint is called, the setup wizard will no longer be shown
    and most setup endpoints will become inaccessible.
    """
    _ensure_setup_not_complete(session)
    
                                                                       
    if not _has_any_users(session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot complete setup without creating an admin account"
        )
    
                            
    settings = get_or_create_system_settings(session)
    settings.is_system_setup_complete = True
    session.add(settings)
    session.commit()
    
    return CompleteSetupResponse(
        success=True,
        message="System setup completed successfully. You can now log in with your admin account."
    )
