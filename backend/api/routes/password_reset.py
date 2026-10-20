"""Public, token-protected reset verification and completion. No account lookup."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from db import get_session
from services.auth import get_auth_settings
from services.password_reset import PasswordResetError, consume_reset, valid_reset_token

router = APIRouter(prefix="/auth/password-reset", tags=["auth"])


async def reset_payload(request: Request) -> dict:
    # Parse here to keep Pydantic validation responses from echoing bearer
    # secrets/passwords. These endpoints never include submitted input in errors.
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, detail="reset_invalid") from None
    if not isinstance(body, dict) or not isinstance(body.get("token"), str):
        raise HTTPException(400, detail="reset_invalid")
    return body


@router.post("/verify")
async def verify_reset(request: Request, response: Response, session: Session = Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    body = await reset_payload(request)
    try:
        valid_reset_token(session, body["token"])
    except PasswordResetError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    return {"valid": True, "password_min_length": get_auth_settings().password_min_length}


@router.post("/complete")
async def complete_reset(request: Request, response: Response, session: Session = Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    body = await reset_payload(request)
    password = body.get("password")
    if not isinstance(password, str) or len(password) > 4096:
        raise HTTPException(400, detail="password_policy")
    try:
        consume_reset(session, body["token"], password)
    except PasswordResetError as exc:
        session.rollback()
        raise HTTPException(400, detail=str(exc)) from None
    return {"success": True}
