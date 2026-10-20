"""Short-lived, one-use proof for authenticated account changes."""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from models import PasskeyChallenge, PasswordResetToken, ReauthenticationGrant, RefreshToken, User
from services.event_log import add_event

if TYPE_CHECKING:
    from api.auth_deps import CurrentUser

REAUTHENTICATION_SECONDS = 300


def account_error(code: str, status: int = 400) -> HTTPException:
    return HTTPException(status, detail={"error_code": code})


def locked_account(session: Session, user_id: uuid.UUID) -> User:
    # Refresh ORM state after acquiring the lock: authentication dependencies
    # may already have read this account before a concurrent credential change.
    user = session.scalar(select(User).where(User.user_id == user_id)
                          .with_for_update().execution_options(populate_existing=True))
    if user is None or not user.is_active:
        raise account_error("account_unavailable", 401)
    if user.locked_until and user.locked_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
        raise account_error("account_locked", 403)
    return user


def authentication_state(user: User) -> str:
    # Invalidates outstanding proofs after email changes or any existing
    # password reset/recovery path, without introducing a second auth version.
    return hashlib.sha256(f"{user.email}\0{user.password_hash}".encode()).hexdigest()


def issue_reauthentication(session: Session, user: User, current_user: CurrentUser) -> dict[str, str | int]:
    now = int(time.time())
    expires_at = min(now + REAUTHENTICATION_SECONDS, int(current_user.token_exp.timestamp()))
    session.execute(delete(ReauthenticationGrant).where(ReauthenticationGrant.expires_at <= now))
    raw = secrets.token_urlsafe(32)
    session.add(ReauthenticationGrant(
        token_hash=hashlib.sha256(raw.encode()).hexdigest(), user_id=user.user_id,
        access_token_jti=current_user.token_jti, authentication_state=authentication_state(user),
        expires_at=expires_at,
    ))
    session.commit()
    return {"reauthentication_token": raw, "expires_in": max(0, expires_at - now)}


def consume_reauthentication(session: Session, user: User, current_user: CurrentUser, raw: str | None) -> None:
    if not raw or len(raw) > 128:
        raise account_error("reauthentication_required", 403)
    grant = session.execute(delete(ReauthenticationGrant).where(
        ReauthenticationGrant.token_hash == hashlib.sha256(raw.encode()).hexdigest(),
        ReauthenticationGrant.user_id == user.user_id,
        ReauthenticationGrant.access_token_jti == current_user.token_jti,
        ReauthenticationGrant.authentication_state == authentication_state(user),
        ReauthenticationGrant.expires_at > int(time.time()),
    ).returning(ReauthenticationGrant.token_hash)).scalar_one_or_none()
    if grant is None:
        raise account_error("reauthentication_required", 403)


def invalidate_account_sessions(session: Session, user: User) -> None:
    """Caller holds the user lock until replacement session commit."""
    now = datetime.now(timezone.utc)
    session.execute(update(RefreshToken).where(
        RefreshToken.user_id == user.user_id, RefreshToken.revoked_at.is_(None),
    ).values(revoked_at=now))
    # A reset link sent to the previous email must not recover the new login.
    session.execute(update(PasswordResetToken).where(
        PasswordResetToken.user_id == user.user_id, PasswordResetToken.consumed_at.is_(None),
    ).values(consumed_at=now))
    session.execute(delete(ReauthenticationGrant).where(ReauthenticationGrant.user_id == user.user_id))
    session.execute(delete(PasskeyChallenge).where(PasskeyChallenge.user_id == user.user_id))


def audit_account(session: Session, user: User, event_type: str, *, params: dict | None = None) -> None:
    add_event(session, event_type=event_type, source="auth.account",
              actor_user_id=user.user_id, actor_email=user.email,
              message=event_type.replace("_", " "), params=params)
