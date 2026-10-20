"""Self-service account APIs. Administrative permissions are never writable here."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.account_schemas import AccountRequest, AccountRoute, ReauthenticationResponse
from api.auth_deps import CurrentUser, get_current_user
from api.routes.auth import (
    MeResponse, TokenResponse, _enforce_login_rate_limit, _get_client_ip,
    _record_login_attempt, issue_login_session, me,
)
from db import get_session
from models import User
from services.account_security import (
    account_error, audit_account, consume_reauthentication, invalidate_account_sessions,
    issue_reauthentication, locked_account,
)
from services.auth import get_auth_settings, hash_password, validate_password_policy, verify_password
from services.user_identity import CanonicalEmail, ProfileName

router = APIRouter(prefix="/auth", tags=["auth"], route_class=AccountRoute)


class ProfileUpdate(AccountRequest):
    first_name: ProfileName = None
    last_name: ProfileName = None


class ReauthenticateRequest(AccountRequest):
    current_password: str = Field(max_length=4096)


class SensitiveRequest(AccountRequest):
    reauthentication_token: str | None = Field(default=None, max_length=128)


class EmailChange(SensitiveRequest):
    email: CanonicalEmail


class PasswordChange(SensitiveRequest):
    password: str = Field(max_length=4096)
    confirm_password: str = Field(max_length=4096)


@router.patch("/me", response_model=MeResponse)
def update_profile(payload: ProfileUpdate, current_user: CurrentUser = Depends(get_current_user),
                   session: Session = Depends(get_session)):
    user = locked_account(session, current_user.user_id)
    changed = []
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed.append(field)
    if changed:
        audit_account(session, user, "profile_updated", params={"changed_fields": sorted(changed)})
    session.commit()
    return me(current_user, session)


@router.post("/reauthenticate", response_model=ReauthenticationResponse)
def reauthenticate(payload: ReauthenticateRequest, request: Request,
                   current_user: CurrentUser = Depends(get_current_user),
                   session: Session = Depends(get_session)):
    settings = get_auth_settings()
    now = datetime.now(timezone.utc)
    ip = _get_client_ip(request)
    _enforce_login_rate_limit(session, ip_address=ip, settings=settings, now=now)
    user = locked_account(session, current_user.user_id)
    valid = verify_password(payload.current_password, user.password_hash)
    _record_login_attempt(session, ip_address=ip, user_id=user.user_id, success=valid)
    if not valid:
        user.failed_login_count = (user.failed_login_count or 0) + 1
        user.last_failed_at = now
        if settings.max_failed_login_count > 0 and settings.lockout_minutes > 0 and user.failed_login_count >= settings.max_failed_login_count:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
        audit_account(session, user, "reauthentication_failed")
        session.commit()
        raise account_error("incorrect_current_password", 403)
    user.failed_login_count = 0
    user.last_failed_at = None
    user.locked_until = None
    return issue_reauthentication(session, user, current_user)


@router.post("/me/email", response_model=TokenResponse)
def change_email(payload: EmailChange, request: Request, response: Response,
                 current_user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    user = locked_account(session, current_user.user_id)
    consume_reauthentication(session, user, current_user, payload.reauthentication_token)
    existing = session.scalar(select(User.user_id).where(User.email == payload.email, User.user_id != user.user_id))
    if existing:
        raise account_error("email_already_in_use", 409)
    previous_email = user.email
    user.email = payload.email
    try:
        # The unique constraint also arbitrates concurrent claims of an email.
        session.flush()
    except IntegrityError:
        session.rollback()
        raise account_error("email_already_in_use", 409) from None
    invalidate_account_sessions(session, user)
    audit_account(session, user, "email_changed", params={"previous_email": previous_email})
    return issue_login_session(user, request, response, session, get_auth_settings())


@router.post("/me/password", response_model=TokenResponse)
def change_password(payload: PasswordChange, request: Request, response: Response,
                    current_user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    user = locked_account(session, current_user.user_id)
    consume_reauthentication(session, user, current_user, payload.reauthentication_token)
    if payload.password != payload.confirm_password:
        raise account_error("password_confirmation_mismatch")
    try:
        validate_password_policy(payload.password, email=user.email)
    except ValueError:
        raise account_error("password_policy") from None
    user.password_hash = hash_password(payload.password)
    invalidate_account_sessions(session, user)
    audit_account(session, user, "password_changed")
    return issue_login_session(user, request, response, session, get_auth_settings())
