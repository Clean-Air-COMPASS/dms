"""Explicit safety gates for paid external-provider requests.

PurpleAir requests can consume purchased API points.  Every authorized path
must therefore pass the same environment, source-state, and execution-context
checks before it can reach an HTTP boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
import os
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from services.external_sources import credential_for_source


class ProviderSafetyDenialCode(str, Enum):
    PAID_API_REQUESTS_DISABLED = "paid_api_requests_disabled"
    PROVIDER_SOURCE_DISABLED = "provider_source_disabled"
    PROVIDER_CREDENTIAL_REQUIRED = "provider_credential_required"
    EXPLICIT_PAID_API_AUTHORIZATION_MISSING = "explicit_paid_api_authorization_missing"
    TEST_ENVIRONMENT_EXTERNAL_HTTP_BLOCKED = "test_environment_external_http_blocked"


class ProviderSafetyDenied(RuntimeError):
    def __init__(self, code: ProviderSafetyDenialCode, message: str):
        self.code = code
        super().__init__(message)

    def as_detail(self) -> dict[str, str]:
        return {"code": self.code.value, "message": str(self)}


@dataclass(frozen=True)
class PaidProviderAuthorization:
    provider_name: str
    execution_mode: str


_request_authorization: ContextVar[PaidProviderAuthorization | None] = ContextVar(
    "paid_provider_request_authorization", default=None
)


def _environment_flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def require_paid_provider_authorization(
    session: Session,
    provider_name: str,
    *,
    explicit_manual_authorization: bool = False,
    scheduled_job: models.JobSchedule | None = None,
) -> PaidProviderAuthorization:
    """Authorize a paid-provider request from stored administrator intent.

    Enabling the source and storing its credential is the normal production
    authorization. Tests remain hard-blocked, and operators retain an explicit
    emergency opt-out. The returned object is still required at the HTTP
    boundary so provider clients cannot make an unscoped request.
    """
    if os.getenv("COMPASSAQ_ENV", "").strip().lower() == "test":
        raise ProviderSafetyDenied(
            ProviderSafetyDenialCode.TEST_ENVIRONMENT_EXTERNAL_HTTP_BLOCKED,
            "External provider HTTP is blocked in the test environment.",
        )
    if _environment_flag("DISABLE_PAID_API_REQUESTS"):
        raise ProviderSafetyDenied(
            ProviderSafetyDenialCode.PAID_API_REQUESTS_DISABLED,
            "Paid-provider requests are disabled by DISABLE_PAID_API_REQUESTS.",
        )

    provider = session.scalar(
        select(models.ExternalAPI).where(
            models.ExternalAPI.provider_code == provider_name.strip().lower()
        )
    )
    if provider is None or not provider.enabled:
        raise ProviderSafetyDenied(
            ProviderSafetyDenialCode.PROVIDER_SOURCE_DISABLED,
            f"The {provider_name} data source is missing or disabled.",
        )
    if credential_for_source(provider) is None:
        raise ProviderSafetyDenied(
            ProviderSafetyDenialCode.PROVIDER_CREDENTIAL_REQUIRED,
            f"The {provider_name} data source requires a configured credential.",
        )

    return PaidProviderAuthorization(
        provider_name=provider_name.strip().lower(),
        execution_mode="scheduled" if scheduled_job is not None else "manual",
    )


def require_purpleair_import_authorization(session: Session) -> PaidProviderAuthorization:
    """Re-check subprocess authorization from scheduler-provided context."""
    execution_mode = os.getenv("PURPLEAIR_EXECUTION_MODE", "").strip().lower()
    if execution_mode == "manual":
        return require_paid_provider_authorization(
            session,
            "PurpleAir",
            explicit_manual_authorization=_environment_flag("PURPLEAIR_MANUAL_AUTHORIZED"),
        )
    if execution_mode == "scheduled":
        raw_schedule_id = os.getenv("PURPLEAIR_JOB_SCHEDULE_ID", "").strip()
        schedule = session.get(models.JobSchedule, int(raw_schedule_id)) if raw_schedule_id.isdigit() else None
        return require_paid_provider_authorization(
            session, "PurpleAir", scheduled_job=schedule
        )
    return require_paid_provider_authorization(session, "PurpleAir")


@contextmanager
def paid_provider_request_scope(
    authorization: PaidProviderAuthorization,
) -> Iterator[None]:
    token = _request_authorization.set(authorization)
    try:
        yield
    finally:
        _request_authorization.reset(token)


def assert_paid_provider_http_authorized(provider_name: str) -> None:
    """Last-line guard placed immediately before provider HTTP calls."""
    authorization = _request_authorization.get()
    if (
        authorization is None
        or authorization.provider_name != provider_name.strip().lower()
    ):
        raise ProviderSafetyDenied(
            ProviderSafetyDenialCode.EXPLICIT_PAID_API_AUTHORIZATION_MISSING,
            f"No authorized {provider_name} request scope is active.",
        )
