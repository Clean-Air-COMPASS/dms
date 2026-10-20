from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from db import SessionLocal
from models import Event, RefreshToken, Role, User, UserRole
from services.admin_account_recovery import AdminRecoveryError, recover_admin_password
from services.auth import hash_password, verify_password


def _role(session, name: str) -> Role:
    role = session.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(role_id=uuid.uuid4(), name=name, description=name.title())
        session.add(role)
        session.flush()
    return role


def _create_user_with_role(*, role_name: str, is_active: bool = True) -> User:
    unique_suffix = uuid.uuid4().hex
    user = User(
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        email=f"recovery-{role_name}-{unique_suffix}@example.com",
        password_hash=hash_password("OriginalPassword123!"),
        is_active=is_active,
        failed_login_count=4,
        last_failed_at=datetime.now(timezone.utc),
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    with SessionLocal() as session:
        role = _role(session, role_name)
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.user_id, role_id=role.role_id))
        session.commit()
        session.refresh(user)
        session.expunge(user)

    return user


def test_recovery_resets_password_unlocks_account_revokes_refresh_tokens_and_logs_event():
    user = _create_user_with_role(role_name="admin")
    token_id = uuid.uuid4()

    with SessionLocal() as session:
        session.add(
            RefreshToken(
                refresh_token_id=token_id,
                user_id=user.user_id,
                token_hash=f"token-{uuid.uuid4().hex}",
                issued_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        session.commit()

    with SessionLocal() as session:
        result = recover_admin_password(
            session,
            email=user.email.upper(),
            new_password="ReplacementPassword456!",
        )

    assert result.email == user.email
    assert result.revoked_refresh_token_count == 1

    with SessionLocal() as session:
        recovered_user = session.get(User, user.user_id)
        token = session.get(RefreshToken, token_id)
        event = session.scalar(
            select(Event)
            .where(
                Event.event_type == "admin_account_recovered",
                Event.actor_user_id == user.user_id,
            )
            .order_by(Event.event_id.desc())
        )

        assert recovered_user is not None
        assert verify_password("ReplacementPassword456!", recovered_user.password_hash)
        assert recovered_user.failed_login_count == 0
        assert recovered_user.last_failed_at is None
        assert recovered_user.locked_until is None
        assert token is not None
        assert token.revoked_at is not None
        assert event is not None
        assert event.source == "admin_account_recovery_cli"
        assert event.actor_email == user.email


def test_recovery_rejects_non_admin_user():
    user = _create_user_with_role(role_name="viewer")

    with SessionLocal() as session:
        with pytest.raises(AdminRecoveryError, match="No administrator account"):
            recover_admin_password(
                session,
                email=user.email,
                new_password="ReplacementPassword456!",
            )


def test_recovery_rejects_inactive_admin_without_reactivating_it():
    user = _create_user_with_role(role_name="admin", is_active=False)

    with SessionLocal() as session:
        with pytest.raises(AdminRecoveryError, match="inactive"):
            recover_admin_password(
                session,
                email=user.email,
                new_password="ReplacementPassword456!",
            )

    with SessionLocal() as session:
        unchanged_user = session.get(User, user.user_id)
        assert unchanged_user is not None
        assert unchanged_user.is_active is False
        assert verify_password("OriginalPassword123!", unchanged_user.password_hash)


def test_recovery_uses_normal_password_policy():
    user = _create_user_with_role(role_name="admin")

    with SessionLocal() as session:
        with pytest.raises(AdminRecoveryError, match="at least"):
            recover_admin_password(
                session,
                email=user.email,
                new_password="short",
            )
