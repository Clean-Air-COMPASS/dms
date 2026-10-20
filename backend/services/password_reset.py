"""Administrator-issued password recovery; bearer secrets never enter persistence."""
import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from models import PasswordResetToken, RefreshToken, User
from services.auth import hash_password, validate_password_policy
from services.email_configuration import derive_email_readiness, EmailReadinessStatus, get_or_create_email_settings
from services.email_delivery import EmailService, email_transport_configuration_from_settings
from services.event_log import add_event
from services.system_settings import get_or_create_system_settings, resolve_default_language_code

RESET_EXPIRY_MINUTES = 60


class PasswordResetError(ValueError):
    """Stable error code with no bearer secret or provider details."""


def application_origin(request: Request | None = None) -> str:
    """Use an operator override or the authenticated browser's exact origin.

    Host alone is never sufficient. Browsers control Origin independently of
    Host; a poisoned Host must not redirect an administrator's reset email.
    Forwarded headers are not used here. Custom proxies that change the origin
    presented to the API can use the explicit deployment override.
    """
    origin = os.environ.get("COMPASSAQ_APPLICATION_URL", "").strip()
    configured = bool(origin)
    if not origin:
        if request is None:
            raise PasswordResetError("application_url_required")
        if (len(request.headers.getlist("origin")) != 1
                or len(request.headers.getlist("host")) != 1):
            raise PasswordResetError("reset_origin_invalid")
        origin = request.headers["origin"]
        # Fetch Metadata is an additional browser check when available (it is
        # absent on some ordinary HTTP/LAN deployments). Origin is mandatory.
        fetch_site = request.headers.get("sec-fetch-site")
        expected_origin = f"{request.url.scheme}://{request.headers['host']}"
        if ((fetch_site is not None and fetch_site != "same-origin")
                or origin != expected_origin):
            raise PasswordResetError("reset_origin_invalid")
    try:
        parsed = urlsplit(origin)
        valid = (
            parsed.scheme in {"https", "http"} and parsed.hostname
            and parsed.username is None and parsed.password is None
            and (parsed.path == "" or (configured and parsed.path == "/"))
            and not parsed.query and not parsed.fragment
            and not any(char.isspace() or ord(char) < 32 for char in origin)
            and "\\" not in origin
        )
        parsed.port  # Reject malformed ports as configuration errors.
    except ValueError:
        valid = False
    if not valid:
        raise PasswordResetError("application_url_required" if configured else "reset_origin_invalid")
    if parsed.scheme != "https" and os.environ.get("COMPASSAQ_ENV") == "production":
        raise PasswordResetError("application_url_requires_https")
    return origin.rstrip("/")


def recovery_readiness(session: Session) -> bool:
    return derive_email_readiness(get_or_create_email_settings(session)).status is EmailReadinessStatus.READY


def audit_reset(session: Session, event_type: str, user: User, actor=None, *, severity="info") -> None:
    add_event(
        session, event_type=event_type, source="password_reset", severity=severity,
        actor_user_id=actor.user_id if actor else user.user_id,
        actor_email=actor.email if actor else user.email,
        message=event_type.replace("_", " "),
        params={"target_user_id": str(user.user_id), "target_email": user.email},
    )


def create_reset_link(session: Session, user_id: uuid.UUID, actor, *, request: Request | None = None) -> tuple[str, PasswordResetToken, User]:
    origin = application_origin(request)
    # Serialize creation and consumption for this account, including replacement
    # of links. The conditional claim below also protects SQLite test execution.
    user = session.scalar(select(User).where(User.user_id == user_id).with_for_update())
    if user is None:
        raise PasswordResetError("user_not_found")
    now = datetime.now(timezone.utc)
    session.execute(update(PasswordResetToken).where(
        PasswordResetToken.user_id == user_id, PasswordResetToken.consumed_at.is_(None),
    ).values(consumed_at=now).execution_options(synchronize_session=False))
    raw = secrets.token_urlsafe(32)
    token = PasswordResetToken(
        token_hash=hashlib.sha256(raw.encode()).hexdigest(), user_id=user_id,
        created_at=now, expires_at=now + timedelta(minutes=RESET_EXPIRY_MINUTES),
        created_by_user_id=actor.user_id,
    )
    session.add(token)
    session.flush()
    # Fragments are not sent to HTTP servers or in Referer headers.
    return f"{origin}/reset-password#token={raw}", token, user


def send_reset_email(session: Session, user: User, link: str) -> None:
    language = user.preferred_language_code or resolve_default_language_code(get_or_create_system_settings(session).default_language_code)
    if language == "es":
        subject = "Restablece tu contraseña de CompassAQ"
        text = "Un administrador creó un enlace para restablecer tu contraseña de CompassAQ."
        action = "Restablecer contraseña"
        expiry = "El enlace se puede usar una sola vez y vence en 60 minutos."
        advice = "Si no esperabas este mensaje, ignóralo o contacta con tu administrador."
    else:
        subject = "Reset your CompassAQ password"
        text = "An administrator created a link to reset your CompassAQ password."
        action = "Reset password"
        expiry = "The link can be used once and expires in 60 minutes."
        advice = "If this was unexpected, ignore this message or contact your administrator."
    EmailService(email_transport_configuration_from_settings(get_or_create_email_settings(session))).send(
        recipients=[user.email], subject=subject,
        text_body=f"{text}\n\n{action}: {link}\n\n{expiry}\n{advice}",
        html_body=f'<h1>CompassAQ</h1><p>{text}</p><p><a href="{escape(link, quote=True)}">{action}</a></p><p>{expiry}</p><p>{advice}</p>',
    )


def token_digest(raw: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw):
        raise PasswordResetError("reset_invalid")
    return hashlib.sha256(raw.encode()).hexdigest()


def valid_reset_token(session: Session, raw: str) -> PasswordResetToken:
    token = session.get(PasswordResetToken, token_digest(raw))
    if token is None:
        raise PasswordResetError("reset_invalid")
    if token.consumed_at is not None:
        raise PasswordResetError("reset_used")
    expires = token.expires_at.replace(tzinfo=timezone.utc) if token.expires_at.tzinfo is None else token.expires_at
    if expires <= datetime.now(timezone.utc):
        raise PasswordResetError("reset_expired")
    return token


def consume_reset(session: Session, raw: str, password: str) -> None:
    token = valid_reset_token(session, raw)
    user = session.scalar(select(User).where(User.user_id == token.user_id).with_for_update())
    if user is None:
        raise PasswordResetError("reset_invalid")
    try:
        validate_password_policy(password, email=user.email)
    except ValueError:
        raise PasswordResetError("password_policy") from None
    now = datetime.now(timezone.utc)
    claimed = session.execute(update(PasswordResetToken).where(
        PasswordResetToken.token_hash == token.token_hash,
        PasswordResetToken.consumed_at.is_(None), PasswordResetToken.expires_at > now,
    ).values(consumed_at=now).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        raise PasswordResetError("reset_used")
    user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.last_failed_at = None
    user.locked_until = None
    session.execute(update(RefreshToken).where(
        RefreshToken.user_id == user.user_id, RefreshToken.revoked_at.is_(None),
    ).values(revoked_at=now))
    audit_reset(session, "password_reset_completed", user)
    session.commit()
