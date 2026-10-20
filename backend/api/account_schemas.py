"""Sanitized validation for account requests, including password/proof bodies."""
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from services.account_security import account_error


class AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReauthenticationResponse(BaseModel):
    reauthentication_token: str
    expires_in: int


class AccountRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sanitized_handler(request: Request):
            try:
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError as exc:
                code = "invalid_request"
                for error in exc.errors():
                    field = error["loc"][-1]
                    if field in {"first_name", "last_name"}:
                        code = "invalid_name_length" if "invalid_name_length" in error["msg"] else "invalid_name"
                    elif field == "email":
                        code = "invalid_email"
                    elif field in {"password", "confirm_password"}:
                        code = "password_policy"
                raise account_error(code, 422) from None

        return sanitized_handler
