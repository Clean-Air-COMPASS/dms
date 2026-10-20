from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Iterable, List

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError as JWTError
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from db import get_session
from models import User
from services.auth import AuthError, decode_access_token, get_auth_settings


class CurrentUser(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: uuid.UUID
    org_id: uuid.UUID
    email: str
    roles: List[str]
    scopes: List[str]
    preferred_language_code: str | None = None
    token_jti: uuid.UUID
    token_exp: datetime


bearer_scheme = HTTPBearer(auto_error=False)


def _auth_error(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _auth_error()

    token = credentials.credentials
    try:
        settings = get_auth_settings()
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    try:
        payload = decode_access_token(token, settings)
    except JWTError:
        raise _auth_error("Invalid or expired access token")

    required_keys = ("sub", "org_id", "roles", "scopes", "jti", "exp")
    if any(key not in payload for key in required_keys):
        raise _auth_error("Missing required token claims")

    try:
        user_id = uuid.UUID(str(payload["sub"]))
        org_id = uuid.UUID(str(payload["org_id"]))
        token_jti = uuid.UUID(str(payload["jti"]))
        token_exp = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except Exception:
        raise _auth_error("Invalid token claim types")

    roles = list(payload.get("roles") or [])
    scopes = list(payload.get("scopes") or [])
    now = datetime.now(timezone.utc)
    if token_exp <= now:
        raise _auth_error("Access token expired")

    user = session.get(User, user_id)
    if not user or not user.is_active:
        raise _auth_error()

                                                                                  
                                                                             
    if user.org_id != org_id:
        raise _auth_error("Token org_id mismatch")

    return CurrentUser(
        user_id=user_id,
        org_id=org_id,
        email=user.email,
        roles=roles,
        scopes=scopes,
        preferred_language_code=user.preferred_language_code,
        token_jti=token_jti,
        token_exp=token_exp,
    )


def require_scopes(required_scopes: Iterable[str]) -> Callable[[CurrentUser], CurrentUser]:
    required = set(required_scopes)

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        missing = required.difference(set(current_user.scopes))
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scopes: {', '.join(sorted(missing))}",
            )
        return current_user

    return dependency
