"""Authenticated enrollment and discoverable, password-free passkey sign-in."""
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options, generate_registration_options, options_to_json,
    verify_authentication_response, verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
    ResidentKeyRequirement, UserVerificationRequirement,
)

from api.auth_deps import CurrentUser, get_current_user
from api.account_schemas import AccountRequest, ReauthenticationResponse
from api.routes.auth import (
    TokenResponse, _enforce_login_rate_limit, _get_client_ip, _is_secure_request,
    _record_login_attempt, issue_login_session,
)
from db import get_session
from models import Passkey, PasskeyChallenge, ReauthenticationGrant, SystemSettings
from services.auth import get_auth_settings, pwd_context
from services.account_security import (
    account_error, audit_account, consume_reauthentication, issue_reauthentication, locked_account,
)
from services.user_identity import ProfileName

class PasskeyRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sanitized_handler(request: Request):
            try:
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError:
                # FastAPI's default validation response can echo credential input.
                raise unavailable() from None

        return sanitized_handler


router = APIRouter(prefix="/auth/passkeys", tags=["auth"], route_class=PasskeyRoute)
COOKIE = "passkey_ceremony"
CHALLENGE_LIFETIME_SECONDS = 300


class CredentialResponse(BaseModel):
    # Keep malformed credentials out of validation responses that echo input.
    credential: dict = Field(default_factory=dict)


class RegistrationResponse(CredentialResponse):
    name: ProfileName = None


class EnrollmentRequest(AccountRequest):
    reauthentication_token: str | None = Field(default=None, max_length=128)


class PasskeyOut(BaseModel):
    id: str
    name: str | None
    created_at: datetime | None
    last_used_at: datetime | None


class PasskeyList(BaseModel):
    passkeys: list[PasskeyOut]


@router.get("", response_model=PasskeyList)
def list_passkeys(response: Response, user: CurrentUser = Depends(get_current_user),
                 session: Session = Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    keys = session.scalars(select(Passkey).where(Passkey.user_id == user.user_id)
                           .order_by(Passkey.created_at, Passkey.credential_id)).all()
    return PasskeyList(passkeys=[PasskeyOut(id=key.credential_id, name=key.name,
                                          created_at=key.created_at, last_used_at=key.last_used_at) for key in keys])


@router.delete("/{passkey_id}")
def remove_passkey(passkey_id: str, user: CurrentUser = Depends(get_current_user),
                   reauthentication_token: str | None = Header(default=None, alias="X-Reauthentication-Token"),
                   session: Session = Depends(get_session)):
    account = locked_account(session, user.user_id)
    consume_reauthentication(session, account, user, reauthentication_token)
    key = session.get(Passkey, passkey_id)
    if key is None:
        raise account_error("passkey_not_found", 404)
    if key.user_id != user.user_id:
        raise account_error("passkey_not_owned", 403)
    # Every supported account is password-backed today. Fail closed if that
    # invariant ever changes, unless another passkey remains.
    others = session.scalar(select(Passkey.credential_id).where(
        Passkey.user_id == user.user_id, Passkey.credential_id != passkey_id).limit(1))
    if not pwd_context.identify(account.password_hash) and others is None:
        raise account_error("last_authentication_method", 409)
    session.delete(key)
    session.execute(delete(ReauthenticationGrant).where(ReauthenticationGrant.user_id == user.user_id))
    audit_account(session, account, "passkey_removed")
    session.commit()
    return {"success": True}


def unavailable() -> HTTPException:
    return HTTPException(400, detail={"error_code": "passkey_failed"})


def relying_party(request: Request) -> tuple[str, str]:
    # Same-origin deployment: never trust an arbitrary Origin header as the RP.
    scheme = "https" if _is_secure_request(request) else "http"
    origin = os.environ.get("PASSKEY_ORIGIN", f"{scheme}://{request.url.netloc}").rstrip("/")
    parsed = urlsplit(origin)
    hostname = parsed.hostname
    if (not hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or parsed.scheme not in {"http", "https"}
            or (parsed.scheme != "https" and hostname != "localhost")):
        raise unavailable()
    if request.headers.get("origin") != origin:
        raise unavailable()
    return hostname, origin


def save_challenge(session, request, response, options, origin, purpose, user_id=None):
    token = secrets.token_urlsafe(32)
    session.execute(delete(PasskeyChallenge).where(PasskeyChallenge.expires_at <= int(time.time())))
    session.add(PasskeyChallenge(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        challenge=bytes_to_base64url(options.challenge), user_id=user_id,
        purpose=purpose, origin=origin,
        expires_at=int(time.time()) + CHALLENGE_LIFETIME_SECONDS,
    ))
    session.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=origin.startswith("https://"),
                        samesite="strict", path="/api/auth/passkeys", max_age=CHALLENGE_LIFETIME_SECONDS)
    response.headers["Cache-Control"] = "no-store"
    return json.loads(options_to_json(options))


def consume_challenge(session, request, purpose, user_id=None):
    _, origin = relying_party(request)
    token = request.cookies.get(COOKIE, "")
    # DELETE RETURNING makes consumption atomic across workers, including failed verification.
    challenge = session.execute(delete(PasskeyChallenge).where(
        PasskeyChallenge.token_hash == hashlib.sha256(token.encode()).hexdigest(),
    ).returning(*PasskeyChallenge.__table__.c)).first()
    session.commit()
    if (not challenge or challenge.expires_at <= int(time.time())
            or challenge.purpose != purpose or challenge.origin != origin
            or challenge.user_id != user_id):
        raise unavailable()
    return base64url_to_bytes(challenge.challenge)


@router.post("/register/options")
def registration_options(request: Request, response: Response,
                         payload: EnrollmentRequest | None = None,
                         user: CurrentUser = Depends(get_current_user),
                         session: Session = Depends(get_session)):
    rp_id, origin = relying_party(request)
    account = locked_account(session, user.user_id)
    existing = session.scalars(select(Passkey).where(Passkey.user_id == user.user_id)).all()
    setup_complete = session.scalar(select(SystemSettings.is_system_setup_complete).limit(1))
    # A missing singleton is also incomplete setup in the existing setup API.
    if existing or setup_complete is True:
        consume_reauthentication(session, account, user, payload.reauthentication_token if payload else None)
    options = generate_registration_options(
        rp_id=rp_id, rp_name="CompassAQ", user_id=user.user_id.bytes, user_name=user.email,
        user_display_name=account.display_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id)) for p in existing],
    )
    return save_challenge(session, request, response, options, origin, "register", user.user_id)


@router.post("/register/verify")
def registration_verify(payload: RegistrationResponse, request: Request,
                        user: CurrentUser = Depends(get_current_user),
                        session: Session = Depends(get_session)):
    rp_id, origin = relying_party(request)
    challenge = consume_challenge(session, request, "register", user.user_id)
    account = locked_account(session, user.user_id)
    try:
        verified = verify_registration_response(
            credential=payload.credential, expected_challenge=challenge,
            expected_rp_id=rp_id, expected_origin=origin, require_user_verification=True,
        )
        session.add(Passkey(
            credential_id=bytes_to_base64url(verified.credential_id), user_id=user.user_id,
            public_key=bytes_to_base64url(verified.credential_public_key),
            sign_count=verified.sign_count, rp_id=rp_id,
            name=payload.name, created_at=datetime.now(timezone.utc),
        ))
        audit_account(session, account, "passkey_registered")
        session.commit()
    except (WebAuthnException, ValueError, TypeError, KeyError, IntegrityError):
        session.rollback()
        raise unavailable() from None
    return {"success": True}


@router.post("/login/options")
def authentication_options(request: Request, response: Response, session: Session = Depends(get_session)):
    rp_id, origin = relying_party(request)
    settings = get_auth_settings()
    _enforce_login_rate_limit(session, ip_address=_get_client_ip(request), settings=settings, now=datetime.now(timezone.utc))
    _record_login_attempt(session, ip_address=_get_client_ip(request), user_id=None, success=False)
    options = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    return save_challenge(session, request, response, options, origin, "login")


@router.post("/login/verify", response_model=TokenResponse)
def authentication_verify(payload: CredentialResponse, request: Request, response: Response,
                          session: Session = Depends(get_session)):
    rp_id, origin = relying_party(request)
    challenge = consume_challenge(session, request, "login")
    settings = get_auth_settings()
    _enforce_login_rate_limit(session, ip_address=_get_client_ip(request), settings=settings, now=datetime.now(timezone.utc))
    user = verify_assertion(session, payload, rp_id, origin, challenge)
    return issue_login_session(user, request, response, session, settings)


def verify_assertion(session, payload, rp_id, origin, challenge, expected_user_id=None):
    """Share signature, RP, origin, user verification and counter checks."""
    credential_id = payload.credential.get("id")
    if not isinstance(credential_id, str):
        raise unavailable()
    owner_id = session.scalar(select(Passkey.user_id).where(Passkey.credential_id == credential_id))
    if owner_id is None or (expected_user_id is not None and owner_id != expected_user_id):
        raise unavailable()
    try:
        user = locked_account(session, owner_id)
    except HTTPException:
        raise unavailable() from None
    passkey = session.scalar(select(Passkey).where(Passkey.credential_id == credential_id)
                             .with_for_update().execution_options(populate_existing=True))
    if passkey is None or passkey.rp_id != rp_id:
        raise unavailable()
    try:
        handle = payload.credential.get("response", {}).get("userHandle")
        if not handle or base64url_to_bytes(handle) != user.user_id.bytes:
            raise ValueError("Invalid user handle")
        verified = verify_authentication_response(
            credential=payload.credential, expected_challenge=challenge,
            expected_rp_id=rp_id, expected_origin=origin,
            credential_public_key=base64url_to_bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count, require_user_verification=True,
        )
    except (WebAuthnException, ValueError, TypeError, KeyError, AttributeError):
        raise unavailable() from None
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = datetime.now(timezone.utc)
    return user


@router.post("/reauthenticate/options")
def reauthentication_options(request: Request, response: Response,
                             user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    rp_id, origin = relying_party(request)
    settings = get_auth_settings()
    _enforce_login_rate_limit(session, ip_address=_get_client_ip(request), settings=settings, now=datetime.now(timezone.utc))
    locked_account(session, user.user_id)
    existing = session.scalars(select(Passkey).where(Passkey.user_id == user.user_id, Passkey.rp_id == rp_id)).all()
    if not existing:
        raise account_error("passkey_not_found", 404)
    _record_login_attempt(session, ip_address=_get_client_ip(request), user_id=user.user_id, success=False)
    options = generate_authentication_options(
        rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(key.credential_id)) for key in existing],
    )
    return save_challenge(session, request, response, options, origin, "reauthenticate", user.user_id)


@router.post("/reauthenticate/verify", response_model=ReauthenticationResponse)
def reauthentication_verify(payload: CredentialResponse, request: Request, response: Response,
                            user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    rp_id, origin = relying_party(request)
    challenge = consume_challenge(session, request, "reauthenticate", user.user_id)
    _enforce_login_rate_limit(session, ip_address=_get_client_ip(request), settings=get_auth_settings(), now=datetime.now(timezone.utc))
    account = verify_assertion(session, payload, rp_id, origin, challenge, expected_user_id=user.user_id)
    response.headers["Cache-Control"] = "no-store"
    return issue_reauthentication(session, account, user)
