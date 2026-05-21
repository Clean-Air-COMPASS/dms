from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from db import get_session
from models import Device, ExternalAPI, JobSchedule

router = APIRouter(prefix="/admin", tags=["admin"])


class ExternalAPIOut(BaseModel):
    external_api_id: int
    name: str
    base_url: Optional[str]
    description: Optional[str]
    api_key: Optional[str]
    params: Optional[dict]
    is_active: bool
    device_count: int


class ExternalAPIUpdateIn(BaseModel):
    base_url: Optional[str] = None
    description: Optional[str] = None
    api_key: Optional[str] = None
    params: Optional[dict] = None
    is_active: Optional[bool] = None


class ExternalAPICreateIn(BaseModel):
    name: str
    base_url: Optional[str] = None
    description: Optional[str] = None
    api_key: Optional[str] = None
    params: Optional[dict] = None
    is_active: bool = True


@router.post("/external_apis", response_model=ExternalAPIOut)
def create_external_api(payload: ExternalAPICreateIn, session: Session = Depends(get_session)):
                        
    existing = session.execute(select(ExternalAPI).where(ExternalAPI.name == payload.name)).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail=f"External API with name '{payload.name}' already exists")
    try:
        ea = ExternalAPI(
            name=payload.name,
            base_url=payload.base_url.strip() if payload.base_url else None,
            description=payload.description.strip() if payload.description else None,
            api_key=payload.api_key.strip() if payload.api_key else None,
            params=payload.params or {},
            is_active=payload.is_active,
        )
        session.add(ea)
        session.commit()
        session.refresh(ea)
        device_count = session.execute(
            select(func.count(Device.device_id)).where(Device.external_api_id == ea.external_api_id)
        ).scalar_one()
        return ExternalAPIOut(
            external_api_id=ea.external_api_id,
            name=ea.name,
            base_url=ea.base_url,
            description=ea.description,
            api_key=ea.api_key,
            params=ea.params,
            is_active=ea.is_active,
            device_count=device_count,
        )
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/external_apis", response_model=List[ExternalAPIOut])
def list_external_apis(session: Session = Depends(get_session)):
    try:
        rows = session.execute(
            select(ExternalAPI, func.count(Device.device_id).label("device_count"))
            .join(Device, Device.external_api_id == ExternalAPI.external_api_id, isouter=True)
            .group_by(ExternalAPI.external_api_id)
            .order_by(ExternalAPI.name.asc(), ExternalAPI.external_api_id.asc())
        ).all()
        return [
            ExternalAPIOut(
                external_api_id=api.external_api_id,
                name=api.name,
                base_url=api.base_url,
                description=api.description,
                api_key=api.api_key,
                params=api.params,
                is_active=api.is_active,
                device_count=device_count,
            )
            for api, device_count in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/external_apis/{external_api_id}", response_model=ExternalAPIOut)
def get_external_api(external_api_id: int, session: Session = Depends(get_session)):
    row = session.get(ExternalAPI, external_api_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"External API {external_api_id} not found")
    device_count = session.execute(
        select(func.count(Device.device_id)).where(Device.external_api_id == external_api_id)
    ).scalar_one()
    return ExternalAPIOut(
        external_api_id=row.external_api_id,
        name=row.name,
        base_url=row.base_url,
        description=row.description,
        api_key=row.api_key,
        params=row.params,
        is_active=row.is_active,
        device_count=device_count,
    )


@router.put("/external_apis/{external_api_id}", response_model=ExternalAPIOut)
def update_external_api(external_api_id: int, payload: ExternalAPIUpdateIn, session: Session = Depends(get_session)):
    row = session.get(ExternalAPI, external_api_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"External API {external_api_id} not found")
    try:
        if payload.base_url is not None:
            row.base_url = payload.base_url.strip() or None
        if payload.description is not None:
            row.description = payload.description.strip() or None
        if payload.api_key is not None:
            row.api_key = payload.api_key.strip() or None
        if payload.params is not None:
            row.params = payload.params
        if payload.is_active is not None:
            row.is_active = payload.is_active
        session.add(row)
        session.commit()
        device_count = session.execute(
            select(func.count(Device.device_id)).where(Device.external_api_id == external_api_id)
        ).scalar_one()
        return ExternalAPIOut(
            external_api_id=row.external_api_id,
            name=row.name,
            base_url=row.base_url,
            description=row.description,
            api_key=row.api_key,
            params=row.params,
            is_active=row.is_active,
            device_count=device_count,
        )
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/external_apis/{external_api_id}")
def delete_external_api(external_api_id: int, session: Session = Depends(get_session)):
    row = session.get(ExternalAPI, external_api_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"External API {external_api_id} not found")

    device_count = session.execute(
        select(func.count(Device.device_id)).where(Device.external_api_id == external_api_id)
    ).scalar_one()
    if device_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete data source '{row.name}' because {device_count} "
                f"device{' is' if device_count == 1 else 's are'} still associated with it."
            ),
        )

    try:
        session.delete(row)
        session.commit()
        return {"success": True}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


class JobScheduleOut(BaseModel):
    job_schedule_id: int
    task: str
    cron_expr: str
    timezone: str
    enabled: bool
    allow_overlap: bool
    params: Optional[dict]


@router.get("/external_apis/{external_api_id}/schedules", response_model=List[JobScheduleOut])
def list_external_api_schedules(external_api_id: int, session: Session = Depends(get_session)):
    api = session.get(ExternalAPI, external_api_id)
    if not api:
        raise HTTPException(status_code=404, detail=f"External API {external_api_id} not found")

                                                                                       
    name_key = api.name.lower()
    rows = session.execute(select(JobSchedule).order_by(JobSchedule.job_schedule_id)).scalars().all()
    matched = [r for r in rows if name_key in r.task.lower()]
    return [
        JobScheduleOut(
            job_schedule_id=j.job_schedule_id,
            task=j.task,
            cron_expr=j.cron_expr,
            timezone=j.timezone,
            enabled=j.enabled,
            allow_overlap=j.allow_overlap,
            params=j.params,
        )
        for j in matched
    ]
