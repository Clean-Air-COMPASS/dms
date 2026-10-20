from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import RefreshToken, Role, User, UserRole
from services.auth import hash_password, validate_password_policy
from services.event_log import add_event
from services.user_identity import normalize_email


class AdminRecoveryError(RuntimeError):
    """Raised when an administrator account cannot be recovered safely."""


@dataclass(frozen=True)
class AdminRecoveryResult:
    user_id: str
    email: str
    revoked_refresh_token_count: int


def list_admin_users(session: Session) -> list[User]:
    """Return users that currently have the admin role, ordered by email."""
    return list(
        session.scalars(
            select(User)
            .join(UserRole, UserRole.user_id == User.user_id)
            .join(Role, Role.role_id == UserRole.role_id)
            .where(Role.name == "admin")
            .order_by(User.email)
        ).all()
    )


def recover_admin_password(
    session: Session,
    *,
    email: str,
    new_password: str,
) -> AdminRecoveryResult:
    """Reset one active administrator password and revoke its refresh tokens.

    This function is intentionally server-side only. It is designed for the
    emergency case where operators control the CompassAQ host/database but no
    longer know any administrator password.
    """
    normalized_email = normalize_email(email)
    user = session.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.user_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(Role.name == "admin", User.email == normalized_email).with_for_update(of=User)
    )

    if user is None:
        raise AdminRecoveryError("No administrator account exists with that email address")
    if not user.is_active:
        raise AdminRecoveryError(
            "The administrator account is inactive. Reactivate it through an authenticated administrator workflow before resetting its password."
        )

    try:
        validate_password_policy(new_password, email=user.email)
    except ValueError as exc:
        raise AdminRecoveryError(str(exc)) from exc

    now = datetime.now(timezone.utc)
    active_refresh_tokens = list(
        session.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user.user_id,
                RefreshToken.revoked_at.is_(None),
            )
        ).all()
    )

    user.password_hash = hash_password(new_password)
    user.failed_login_count = 0
    user.last_failed_at = None
    user.locked_until = None

    for token in active_refresh_tokens:
        token.revoked_at = now

    add_event(
        session,
        event_type="admin_account_recovered",
        source="admin_account_recovery_cli",
        severity="warning",
        actor_user_id=user.user_id,
        actor_email=user.email,
        message="Administrator password reset through the server-side recovery CLI; active refresh tokens were revoked.",
        params={"revoked_refresh_token_count": len(active_refresh_tokens)},
    )

    session.commit()

    return AdminRecoveryResult(
        user_id=str(user.user_id),
        email=user.email,
        revoked_refresh_token_count=len(active_refresh_tokens),
    )
