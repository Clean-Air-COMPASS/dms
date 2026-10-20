import os

from fastapi import APIRouter, Response
from pydantic import BaseModel

from build_identity import APPLICATION_VERSION, BACKEND_BUILD


router = APIRouter(tags=["version"])


class ComponentBuild(BaseModel):
    commit_sha: str | None
    build_time_utc: str | None


class VersionResponse(BaseModel):
    application_version: str
    backend: ComponentBuild
    environment: str | None


@router.get("/version", response_model=VersionResponse)
def version(response: Response) -> VersionResponse:
    response.headers["Cache-Control"] = "no-store"
    environment = os.environ.get("COMPASSAQ_ENV", "").strip().lower()
    return VersionResponse(
        application_version=APPLICATION_VERSION,
        backend=ComponentBuild(**BACKEND_BUILD),
        environment=environment if environment in {"development", "test", "staging", "production"} else None,
    )
