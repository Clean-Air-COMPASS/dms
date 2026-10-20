from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_session
from models import Device, ExternalAPI, JobRun, JobSchedule
from services.external_sources import (
    credential_for_source,
    derive_external_source_state,
    is_builtin_external_source,
    source_requires_credential,
)


router = APIRouter(prefix="/admin", tags=["admin"])


class LatestImportRunOut(BaseModel):
    job_run_id: int
    job_schedule_id: int
    task: str
    status: str
    started_at: Optional[str]
    finished_at: Optional[str]
    summary: Optional[dict]
    error_message: Optional[str]


class ExternalAPIOut(BaseModel):
    external_api_id: int
    provider_code: Optional[str]
    name: str
    base_url: Optional[str]
    description: Optional[str]
    requires_credential: bool
    has_api_key: bool
    credential_configured: bool
    params: dict
    enabled: bool
    is_configured: bool
    is_runnable: bool
    runnable_reason: str
    is_builtin: bool
    can_delete: bool
    device_count: int
    latest_import: Optional[LatestImportRunOut]


class ExternalAPIUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: Optional[str] = None
    description: Optional[str] = None
    api_key: Optional[str] = None
    params: Optional[dict] = None
    enabled: Optional[bool] = None


class ExternalAPICreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    base_url: Optional[str] = None
    description: Optional[str] = None
    api_key: Optional[str] = None
    params: Optional[dict] = None
    enabled: bool = False


def _device_count(session: Session, external_api_id: int) -> int:
    return session.scalar(
        select(func.count(Device.device_id)).where(
            Device.external_api_id == external_api_id
        )
    ) or 0


def _latest_import_run(
    session: Session, source: ExternalAPI
) -> LatestImportRunOut | None:
    if not source.provider_code:
        return None
    task = f"{source.provider_code}_import"
    row = session.execute(
        select(JobRun, JobSchedule.task)
        .join(
            JobSchedule,
            JobSchedule.job_schedule_id == JobRun.job_schedule_id,
        )
        .where(JobSchedule.task == task)
        .order_by(JobRun.started_at.desc(), JobRun.job_run_id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    job_run, task_name = row
    return LatestImportRunOut(
        job_run_id=job_run.job_run_id,
        job_schedule_id=job_run.job_schedule_id,
        task=task_name,
        status=job_run.status,
        started_at=(job_run.started_at.isoformat() if job_run.started_at else None),
        finished_at=(
            job_run.finished_at.isoformat() if job_run.finished_at else None
        ),
        summary=job_run.summary,
        error_message=job_run.error_message,
    )


def _external_api_out(
    session: Session, source: ExternalAPI, *, device_count: int
) -> ExternalAPIOut:
    state = derive_external_source_state(source)
    is_builtin = is_builtin_external_source(source)
    return ExternalAPIOut(
        external_api_id=source.external_api_id,
        provider_code=source.provider_code,
        name=source.name,
        base_url=source.base_url,
        description=source.description,
        has_api_key=bool(source.api_key and source.api_key.strip()),
        credential_configured=bool(credential_for_source(source)),
        requires_credential=source_requires_credential(source),
        params=source.params or {},
        enabled=source.enabled,
        is_configured=state.is_configured,
        is_runnable=state.is_runnable,
        runnable_reason=state.runnable_reason.value,
        is_builtin=is_builtin,
        can_delete=not is_builtin and device_count == 0,
        device_count=device_count,
        latest_import=_latest_import_run(session, source),
    )


@router.post("/external_apis", response_model=ExternalAPIOut)
def create_external_api(
    payload: ExternalAPICreateIn, session: Session = Depends(get_session)
) -> ExternalAPIOut:
    normalized_name = payload.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Data source name is required")
    existing = session.scalar(
        select(ExternalAPI).where(ExternalAPI.name == normalized_name)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"External API with name '{normalized_name}' already exists",
        )

    source = ExternalAPI(
        provider_code=None,
        name=normalized_name,
        base_url=payload.base_url.strip() if payload.base_url else None,
        description=payload.description.strip() if payload.description else None,
        api_key=payload.api_key.strip() if payload.api_key else None,
        params=payload.params or {},
        enabled=payload.enabled,
    )
    try:
        session.add(source)
        session.commit()
        session.refresh(source)
        return _external_api_out(session, source, device_count=0)
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/external_apis", response_model=List[ExternalAPIOut])
def list_external_apis(
    session: Session = Depends(get_session),
) -> list[ExternalAPIOut]:
    rows = session.execute(
        select(ExternalAPI, func.count(Device.device_id).label("device_count"))
        .join(Device, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
        .group_by(ExternalAPI.external_api_id)
        .order_by(ExternalAPI.name.asc(), ExternalAPI.external_api_id.asc())
    ).all()
    return [
        _external_api_out(session, source, device_count=device_count)
        for source, device_count in rows
    ]


@router.get("/external_apis/{external_api_id}", response_model=ExternalAPIOut)
def get_external_api(
    external_api_id: int, session: Session = Depends(get_session)
) -> ExternalAPIOut:
    source = session.get(ExternalAPI, external_api_id)
    if source is None:
        raise HTTPException(
            status_code=404, detail=f"External API {external_api_id} not found"
        )
    return _external_api_out(
        session, source, device_count=_device_count(session, external_api_id)
    )


@router.put("/external_apis/{external_api_id}", response_model=ExternalAPIOut)
def update_external_api(
    external_api_id: int,
    payload: ExternalAPIUpdateIn,
    session: Session = Depends(get_session),
) -> ExternalAPIOut:
    source = session.get(ExternalAPI, external_api_id)
    if source is None:
        raise HTTPException(
            status_code=404, detail=f"External API {external_api_id} not found"
        )

    if "base_url" in payload.model_fields_set:
        source.base_url = payload.base_url.strip() if payload.base_url else None
    if "description" in payload.model_fields_set:
        source.description = (
            payload.description.strip() if payload.description else None
        )
    if "api_key" in payload.model_fields_set:
        source.api_key = payload.api_key.strip() if payload.api_key else None
    if payload.params is not None:
        source.params = payload.params
    if payload.enabled is not None:
        source.enabled = payload.enabled

    try:
        session.add(source)
        session.commit()
        session.refresh(source)
        return _external_api_out(
            session, source, device_count=_device_count(session, external_api_id)
        )
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/external_apis/{external_api_id}")
def delete_external_api(
    external_api_id: int, session: Session = Depends(get_session)
) -> dict[str, bool]:
    source = session.get(ExternalAPI, external_api_id)
    if source is None:
        raise HTTPException(
            status_code=404, detail=f"External API {external_api_id} not found"
        )

    if is_builtin_external_source(source):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete built-in data source '{source.name}'. "
                "OpenAQ, PurpleAir, and AirGradient are required system definitions."
            ),
        )

    device_count = _device_count(session, external_api_id)
    if device_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete data source '{source.name}' because {device_count} "
                f"device{' is' if device_count == 1 else 's are'} still associated with it."
            ),
        )

    try:
        session.delete(source)
        session.commit()
        return {"success": True}
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class JobScheduleOut(BaseModel):
    job_schedule_id: int
    task: str
    cron_expr: str
    timezone: str
    enabled: bool
    allow_overlap: bool
    params: Optional[dict]


@router.get(
    "/external_apis/{external_api_id}/schedules",
    response_model=List[JobScheduleOut],
)
def list_external_api_schedules(
    external_api_id: int, session: Session = Depends(get_session)
) -> list[JobScheduleOut]:
    source = session.get(ExternalAPI, external_api_id)
    if source is None:
        raise HTTPException(
            status_code=404, detail=f"External API {external_api_id} not found"
        )

    task = f"{source.provider_code}_import" if source.provider_code else None
    rows = (
        session.scalars(
            select(JobSchedule)
            .where(JobSchedule.task == task)
            .order_by(JobSchedule.job_schedule_id)
        ).all()
        if task is not None
        else []
    )
    return [
        JobScheduleOut(
            job_schedule_id=schedule.job_schedule_id,
            task=schedule.task,
            cron_expr=schedule.cron_expr,
            timezone=schedule.timezone,
            enabled=schedule.enabled,
            allow_overlap=schedule.allow_overlap,
            params=schedule.params,
        )
        for schedule in rows
    ]
