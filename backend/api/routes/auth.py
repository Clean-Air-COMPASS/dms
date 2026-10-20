from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from api.auth_deps import CurrentUser, get_current_user
from db import get_session
from models import AuthLoginAttempt, Event, Passkey, RefreshToken, Role, User, UserRole
from services.user_identity import CanonicalEmail
from services.auth import (
    AuthError,
    create_access_token,
    generate_refresh_token,
    get_auth_settings,
    hash_refresh_token,
    scopes_from_roles,
    verify_password,
)
from services.system_settings import (
    get_or_create_system_settings,
    resolve_default_language_code,
)


router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
GENERIC_AUTH_ERROR = "Invalid email or password"

logger = logging.getLogger("auth.security")

                                                                                   
                                                                                    


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    email: CanonicalEmail
    password: str


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    first_name: str | None
    last_name: str | None
    display_name: str
    passkey_count: int
    org_id: uuid.UUID
    roles: List[str]
    scopes: List[str]
    preferred_language_code: Literal["en", "es"] | None
    system_default_language_code: Literal["en", "es"]


class MePreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferred_language_code: Literal["en", "es"] | None


def _is_secure_request(request: Request) -> bool:
                                                                       
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded:
        proto = forwarded.split(",")[0].strip().lower()
        return proto == "https"
    return request.url.scheme == "https"


def _set_refresh_cookie(response: Response, request: Request, token: str, expires_at: datetime) -> None:
                                                                                    
                                                                                 
                                                                     
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/api/auth",
        expires=int(expires_at.timestamp()),
    )


def _clear_refresh_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/auth",
        samesite="lax",
        secure=_is_secure_request(request),
    )


def _load_user_roles(session: Session, user_id: uuid.UUID) -> list[str]:
    roles = session.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(UserRole.user_id == user_id)
    ).scalars().all()
    return sorted(set(roles))


def _get_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else None


def _log_security_event(
    session: Session,
    *,
    event_type: str,
    severity: str,
    message: str,
    params: dict | None = None,
) -> None:
    payload = {
        "event_type": event_type,
        "severity": severity,
        "message": message,
        "params": params or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(json.dumps(payload, ensure_ascii=True))
                                                                                           
    event = Event(
        event_type=event_type,
        source="auth",
        severity=severity,
        message=message,
        params=params or {},
    )
    session.add(event)


def _record_login_attempt(
    session: Session,
    *,
    ip_address: str | None,
    user_id: uuid.UUID | None,
    success: bool,
) -> None:
    session.add(
        AuthLoginAttempt(
            ip_address=ip_address,
            user_id=user_id,
            success=success,
        )
    )


def _enforce_login_rate_limit(
    session: Session,
    *,
    ip_address: str | None,
    settings,
    now: datetime,
) -> None:
    window_seconds = settings.login_rate_limit_window_seconds
    if window_seconds <= 0:
        return

    window_start = now - timedelta(seconds=window_seconds)
    global_limit = settings.login_rate_limit_global_max
    ip_limit = settings.login_rate_limit_ip_max

    global_count = session.execute(
        select(func.count()).select_from(AuthLoginAttempt).where(AuthLoginAttempt.created_at >= window_start)
    ).scalar_one()

    ip_count = 0
    if ip_address:
        ip_count = session.execute(
            select(func.count())
            .select_from(AuthLoginAttempt)
            .where(AuthLoginAttempt.created_at >= window_start, AuthLoginAttempt.ip_address == ip_address)
        ).scalar_one()

    over_global = global_limit > 0 and global_count >= global_limit
    over_ip = ip_limit > 0 and ip_address and ip_count >= ip_limit
    if over_global or over_ip:
        _record_login_attempt(session, ip_address=ip_address, user_id=None, success=False)
        _log_security_event(
            session,
            event_type="auth.login.rate_limited",
            severity="warning",
            message="Login rate limit exceeded",
            params={
                "ip": ip_address,
                "window_seconds": window_seconds,
                "ip_count": ip_count,
                "ip_limit": ip_limit,
                "global_count": global_count,
                "global_limit": global_limit,
            },
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> TokenResponse:
    try:
        settings = get_auth_settings()
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    now = datetime.now(timezone.utc)
    client_ip = _get_client_ip(request)
    _enforce_login_rate_limit(session, ip_address=client_ip, settings=settings, now=now)

    normalized_email = payload.email
    user = session.execute(
        select(User).where(User.email == normalized_email).with_for_update()
    ).scalar_one_or_none()

    if user and user.locked_until and user.locked_until.replace(tzinfo=timezone.utc) > now:
        _record_login_attempt(session, ip_address=client_ip, user_id=user.user_id, success=False)
        _log_security_event(
            session,
            event_type="auth.login.locked",
            severity="warning",
            message="Login attempt against locked account",
            params={
                "ip": client_ip,
                "user_id": str(user.user_id),
                "email": normalized_email,
                "locked_until": user.locked_until.isoformat(),
            },
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_ERROR)

    password_ok = bool(user) and verify_password(payload.password, user.password_hash)
    if not user or not password_ok:
        if user:
            current_failures = user.failed_login_count or 0
            user.failed_login_count = current_failures + 1
            user.last_failed_at = now
            if settings.max_failed_login_count > 0 and settings.lockout_minutes > 0:
                if user.failed_login_count >= settings.max_failed_login_count:
                    user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                    _log_security_event(
                        session,
                        event_type="auth.account.locked",
                        severity="warning",
                        message="Account locked after failed login attempts",
                        params={
                            "ip": client_ip,
                            "user_id": str(user.user_id),
                            "email": normalized_email,
                            "failed_login_count": user.failed_login_count,
                            "locked_minutes": settings.lockout_minutes,
                        },
                    )

        _record_login_attempt(session, ip_address=client_ip, user_id=user.user_id if user else None, success=False)
        _log_security_event(
            session,
            event_type="auth.login.failed",
            severity="info",
            message="Login failed",
            params={
                "ip": client_ip,
                "email": normalized_email,
                "user_id": str(user.user_id) if user else None,
                "failed_login_count": user.failed_login_count if user else None,
            },
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_ERROR)

    if not user.is_active:
        _record_login_attempt(session, ip_address=client_ip, user_id=user.user_id, success=False)
        _log_security_event(
            session,
            event_type="auth.login.disabled",
            severity="warning",
            message="Login attempt for disabled account",
            params={
                "ip": client_ip,
                "user_id": str(user.user_id),
                "email": normalized_email,
            },
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_ERROR)

    return issue_login_session(user, request, response, session, settings)


def issue_login_session(user: User, request: Request, response: Response, session: Session, settings) -> TokenResponse:
    """Issue the same session after either password or passkey verification."""
    client_ip = _get_client_ip(request)
    user.failed_login_count = 0
    user.last_failed_at = None
    user.locked_until = None

    roles = _load_user_roles(session, user.user_id)
    scopes = scopes_from_roles(roles)

    access_token, _ = create_access_token(
        settings=settings,
        user_id=user.user_id,
        org_id=user.org_id,
        roles=roles,
        scopes=scopes,
    )

    raw_refresh, token_hash, refresh_token_id, issued_at, expires_at = generate_refresh_token(settings)
    refresh_record = RefreshToken(
        refresh_token_id=refresh_token_id,
        user_id=user.user_id,
        token_hash=token_hash,
        issued_at=issued_at,
        expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    _record_login_attempt(session, ip_address=client_ip, user_id=user.user_id, success=True)
    session.add(refresh_record)
    session.commit()

    _set_refresh_cookie(response, request, raw_refresh, expires_at)
    return TokenResponse(access_token=access_token, expires_in=settings.access_token_exp_seconds)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> TokenResponse:
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_refresh:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    try:
        settings = get_auth_settings()
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    token_hash = hash_refresh_token(raw_refresh)
    now = datetime.now(timezone.utc)
    # Match the account-change lock order. A refresh that waits for an email
    # or password change must re-read revocation before issuing a replacement.
    owner_id = session.scalar(select(RefreshToken.user_id).where(RefreshToken.token_hash == token_hash).limit(1))
    if owner_id is not None:
        session.execute(select(User).where(User.user_id == owner_id).with_for_update()
                        .execution_options(populate_existing=True)).scalar_one_or_none()
                                                                                      
    refresh_records = session.execute(
        select(RefreshToken)
        .options(joinedload(RefreshToken.user))
        .where(RefreshToken.token_hash == token_hash)
        .order_by(RefreshToken.issued_at.desc(), RefreshToken.refresh_token_id.desc())
        .limit(5)
    ).scalars().all()

    active_matches = [r for r in refresh_records if r.revoked_at is None]
    if len(active_matches) != 1 or not active_matches[0].user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    refresh_record = active_matches[0]

    if refresh_record.expires_at.replace(tzinfo=timezone.utc) <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is expired or revoked")

    user = refresh_record.user
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled")

    roles = _load_user_roles(session, user.user_id)
    scopes = scopes_from_roles(roles)
    access_token, _ = create_access_token(
        settings=settings,
        user_id=user.user_id,
        org_id=user.org_id,
        roles=roles,
        scopes=scopes,
    )

    new_raw, new_hash, new_token_id, issued_at, expires_at = generate_refresh_token(settings)
    replacement = RefreshToken(
        refresh_token_id=new_token_id,
        user_id=user.user_id,
        token_hash=new_hash,
        issued_at=issued_at,
        expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )

    session.add(replacement)
    session.flush()
    refresh_record.revoked_at = now
    refresh_record.replaced_by_refresh_token_id = new_token_id
    session.commit()

    _set_refresh_cookie(response, request, new_raw, expires_at)
    return TokenResponse(access_token=access_token, expires_in=settings.access_token_exp_seconds)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> Response:
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_refresh:
        token_hash = hash_refresh_token(raw_refresh)
        record = session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).scalar_one_or_none()
        if record and record.revoked_at is None:
            record.revoked_at = datetime.now(timezone.utc)
            session.add(record)
            session.commit()

    _clear_refresh_cookie(response, request)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeResponse)
def me(
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
    response: Response = None,
) -> MeResponse:
    if response is not None:
        response.headers["Cache-Control"] = "no-store"
    settings = get_or_create_system_settings(session)
    user = session.get(User, current_user.user_id)
    return MeResponse(
        user_id=current_user.user_id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        passkey_count=session.scalar(select(func.count()).select_from(Passkey).where(Passkey.user_id == user.user_id)),
        org_id=current_user.org_id,
        roles=current_user.roles,
        scopes=current_user.scopes,
        preferred_language_code=user.preferred_language_code,
        system_default_language_code=resolve_default_language_code(
            settings.default_language_code
        ),
    )


@router.patch("/me/preferences", response_model=MeResponse)
def update_me_preferences(
    payload: MePreferencesUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> MeResponse:
    user = session.get(User, current_user.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")

    user.preferred_language_code = payload.preferred_language_code
    session.add(user)
    session.commit()

    return me(current_user, session)
