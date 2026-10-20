import logging
from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from db import get_session
from sources.airgradient import admin_locations, importer

router = APIRouter(prefix="/admin/devices/airgradient", tags=["admin"])
logger = logging.getLogger("admin.airgradient_devices")
Result = TypeVar("Result")


class LocationChoice(BaseModel):
    location_id: str
    name: str
    latitude: float | None
    longitude: float | None
    timezone: str | None
    existing_device_id: int | None


class LocationList(BaseModel):
    locations: list[LocationChoice]
    automatic_imports_enabled: bool


class AddLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    location_id: str = Field(min_length=1, max_length=128)


class LocationAdded(BaseModel):
    device_id: int
    already_exists: bool
    measurements_imported: int


def _run(session: Session, operation: Callable[[], Result]) -> Result:
    try:
        return operation()
    except admin_locations.LocationWorkflowError as exc:
        status, code = exc.status, exc.code
    except importer.AirGradientAuthenticationError:
        status, code = 422, "authentication_failed"
    except importer.AirGradientRateLimit:
        status, code = 429, "rate_limited"
    except importer.AirGradientMalformedResponse:
        status, code = 502, "invalid_response"
    except importer.AirGradientProviderUnavailable:
        status, code = 503, "provider_unavailable"
    except importer.AirGradientImporterError:
        status, code = 502, "provider_error"
    except Exception:
        # Neither SQL parameters nor provider exceptions are safe to serialize/log.
        status, code = 500, "operation_failed"
    session.rollback()
    logger.warning("AirGradient location workflow failed: %s", code)
    raise HTTPException(status_code=status, detail={"error_code": code})


@router.get("/locations", response_model=LocationList)
def list_locations(session: Session = Depends(get_session)):
    return _run(session, lambda: admin_locations.list_locations(session))


@router.post("/locations", response_model=LocationAdded)
def add_location(payload: AddLocation, session: Session = Depends(get_session)):
    def create():
        result = admin_locations.add_location(session, payload.location_id)
        session.commit()
        return result
    return _run(session, create)
