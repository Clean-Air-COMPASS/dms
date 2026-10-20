"""Liveness and core-system readiness endpoints."""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine, text

from db import engine


router = APIRouter(prefix="/health", tags=["health"])
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class ReadinessResponse(BaseModel):
    """Public readiness state without internal diagnostic details."""

    status: str


def get_expected_schema_revisions() -> set[str]:
    """Return every Alembic head required by the running application."""
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location",
        str(BACKEND_ROOT / "migrations"),
    )
    return set(ScriptDirectory.from_config(alembic_config).get_heads())


def is_core_system_ready(database_engine: Engine) -> bool:
    """Check database connectivity and the deployed schema revision.

    Provider credentials, SMTP, internet access, and scheduled imports are
    intentionally outside this core readiness contract.
    """
    try:
        with database_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            applied_revisions = set(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
        return applied_revisions == get_expected_schema_revisions()
    except Exception:
        return False


@router.get("", response_model=ReadinessResponse)
def liveness() -> ReadinessResponse:
    """Confirm that the API process can answer requests."""
    return ReadinessResponse(status="ok")


@router.get("/readiness", response_model=ReadinessResponse)
def readiness() -> ReadinessResponse | JSONResponse:
    """Report whether core database services and schema are ready for use."""
    if not is_core_system_ready(engine):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready"},
        )
    return ReadinessResponse(status="ready")
