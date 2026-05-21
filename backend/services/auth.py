from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from jose import jwt
from jose.exceptions import JWTError
from passlib.context import CryptContext


                                       
ROLE_SCOPES: dict[str, Sequence[str]] = {
    "viewer": (
        "devices:read",
        "measurements:read",
    ),
    "analyst": (
        "devices:read",
        "measurements:read",
        "exports:write",
    ),
    "admin": (
        "devices:read",
        "measurements:read",
        "exports:write",
        "devices:write",
        "sources:write",
        "users:write",
        "events:write",
    ),
}


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthError(RuntimeError):
    """Raised when auth configuration is invalid."""


@dataclass(frozen=True)
class AuthSettings:
    secret_key: str
    algorithm: str
    issuer: str
    audience: str
    access_token_exp_seconds: int
    refresh_token_exp_seconds: int
    max_failed_login_count: int
    lockout_minutes: int
    login_rate_limit_window_seconds: int
    login_rate_limit_ip_max: int
    login_rate_limit_global_max: int
    password_min_length: int


@lru_cache
def get_auth_settings() -> AuthSettings:
    secret_key = os.getenv("JWT_SECRET_KEY")
    if not secret_key:
        raise AuthError("JWT_SECRET_KEY is not configured")

    algorithm = os.getenv("JWT_ALGORITHM", "HS256")
    issuer = os.getenv("JWT_ISSUER", "cleanaircompass-aq-api")
    audience = os.getenv("JWT_AUDIENCE", "cleanaircompass-aq-web")
    access_token_exp_seconds = int(os.getenv("ACCESS_TOKEN_EXPIRE_SECONDS", "900"))
    refresh_token_exp_seconds = int(os.getenv("REFRESH_TOKEN_EXPIRE_SECONDS", str(60 * 60 * 24 * 30)))
    max_failed_login_count = int(os.getenv("AUTH_MAX_FAILED_LOGINS", "5"))
    lockout_minutes = int(os.getenv("AUTH_LOCKOUT_MINUTES", "15"))
    login_rate_limit_window_seconds = int(os.getenv("AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60"))
    login_rate_limit_ip_max = int(os.getenv("AUTH_LOGIN_RATE_LIMIT_IP_MAX", "20"))
    login_rate_limit_global_max = int(os.getenv("AUTH_LOGIN_RATE_LIMIT_GLOBAL_MAX", "200"))
    password_min_length = int(os.getenv("AUTH_PASSWORD_MIN_LENGTH", "12"))
    if password_min_length < 12:
        password_min_length = 12

    return AuthSettings(
        secret_key=secret_key,
        algorithm=algorithm,
        issuer=issuer,
        audience=audience,
        access_token_exp_seconds=access_token_exp_seconds,
        refresh_token_exp_seconds=refresh_token_exp_seconds,
        max_failed_login_count=max_failed_login_count,
        lockout_minutes=lockout_minutes,
        login_rate_limit_window_seconds=login_rate_limit_window_seconds,
        login_rate_limit_ip_max=login_rate_limit_ip_max,
        login_rate_limit_global_max=login_rate_limit_global_max,
        password_min_length=password_min_length,
    )


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)

def validate_password_policy(
    password: str,
    *,
    email: str | None = None,
    username: str | None = None,
    settings: AuthSettings | None = None,
) -> None:
    if settings is None:
        min_length = int(os.getenv("AUTH_PASSWORD_MIN_LENGTH", "12"))
        if min_length < 12:
            min_length = 12
    else:
        min_length = settings.password_min_length
    if len(password) < min_length:
        raise ValueError(f"Password must be at least {min_length} characters long")

    lower = password.lower()

    if email:
        normalized_email = email.lower().strip()
        if normalized_email and normalized_email in lower:
            raise ValueError("Password must not contain the email address")
        local_part = normalized_email.split("@")[0]
        if local_part and local_part in lower:
            raise ValueError("Password must not contain the email username")

    if username:
        normalized_username = username.lower().strip()
        if normalized_username and normalized_username in lower:
            raise ValueError("Password must not contain the username")


def scopes_from_roles(roles: Iterable[str]) -> list[str]:
    scopes: set[str] = set()
    for role in roles:
        scopes.update(ROLE_SCOPES.get(role, ()))
    return sorted(scopes)


def create_access_token(
    *,
    settings: AuthSettings,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    roles: list[str],
    scopes: list[str],
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.access_token_exp_seconds)
    payload = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "sub": str(user_id),
        "org_id": str(org_id),
        "roles": roles,
        "scopes": scopes,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token, expires_at


def decode_access_token(token: str, settings: AuthSettings) -> dict:
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        audience=settings.audience,
        issuer=settings.issuer,
    )


def generate_refresh_token(settings: AuthSettings) -> tuple[str, str, uuid.UUID, datetime, datetime]:
    """Return (raw_token, token_hash, token_id, issued_at, expires_at)."""
    raw = secrets.token_urlsafe(64)
    token_hash = hash_refresh_token(raw)
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=settings.refresh_token_exp_seconds)
    return raw, token_hash, uuid.uuid4(), issued_at, expires_at


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

