from __future__ import annotations

from typing import Annotated, Optional, List
from datetime import datetime, timezone

from croniter import CroniterBadDateError, croniter

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from api.routes.admin.history import HistoryPage, history_bounds
from db import get_session
from models import JobExecutionTrigger, JobSchedule, JobRun
from jobs.import_runner import run_importer
from services.external_sources import (
    ExternalSourceNotRunnable,
    require_task_source_runnable,
)
from services.provider_safety import (
    ProviderSafetyDenied,
    require_paid_provider_authorization,
)

router = APIRouter(prefix="/admin", tags=["admin"]) 


class JobRunTriggerOut(BaseModel):
    job_run_id: int
    status: str


def _background_run_job(
    job_schedule_id: int,
    job_run_id: int,
    task: str,
    params: dict | None,
    allow_paid_api: bool,
):
    from db import SessionLocal as _SessionLocal
    from datetime import datetime as _dt, timezone as _tz
    with _SessionLocal() as s:
        try:
            code, summary, err = run_importer(
                job_run_id,
                params,
                task,
                job_schedule_id=job_schedule_id,
                explicit_manual_authorization=allow_paid_api,
            )
            jr = s.get(JobRun, job_run_id)
            if jr:
                jr.finished_at = _dt.now(_tz.utc)
                jr.summary = summary
                jr.status = "success" if code == 0 else "failed"
                jr.error_message = err
                s.add(jr)
                s.commit()
        except Exception as e:                                        
            jr = s.get(JobRun, job_run_id)
            if jr:
                jr.finished_at = _dt.now(_tz.utc)
                jr.status = "failed"
                jr.error_message = str(e)[:2000]
                s.add(jr)
                s.commit()


@router.post("/jobs/{job_schedule_id}/run", response_model=JobRunTriggerOut)
def trigger_job_run(
    job_schedule_id: int,
    background_tasks: BackgroundTasks,
    allow_paid_api: bool = Query(False),
    session: Session = Depends(get_session),
):
    """Manually trigger a job run for the given schedule.

    - Respects allow_overlap: if false and a run is already running, returns 409.
    - Spawns importer in a background task; returns the JobRun id immediately.
    """
    job = session.get(JobSchedule, job_schedule_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job schedule {job_schedule_id} not found")

    try:
        require_task_source_runnable(session, job.task)
    except ExternalSourceNotRunnable as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.state.runnable_reason.value},
        ) from exc

    if job.task == "purpleair_import":
        try:
            require_paid_provider_authorization(
                session,
                "PurpleAir",
                explicit_manual_authorization=allow_paid_api,
            )
        except ProviderSafetyDenied as exc:
            raise HTTPException(status_code=403, detail=exc.as_detail()) from exc

                   
    if not job.allow_overlap:
        active = session.execute(text("SELECT count(1) FROM job_run WHERE job_schedule_id=:sid AND status='running'"), {"sid": job_schedule_id}).scalar()
        if active and int(active) > 0:
            raise HTTPException(status_code=409, detail="A run is already in progress for this schedule")

    from datetime import datetime, timezone
    jr = JobRun(
        job_schedule_id=job_schedule_id,
        status="running",
        execution_trigger=JobExecutionTrigger.MANUAL.value,
        started_at=datetime.now(timezone.utc),
    )
    session.add(jr)
    session.commit()

    background_tasks.add_task(
        _background_run_job,
        job_schedule_id,
        jr.job_run_id,
        job.task,
        job.params,
        allow_paid_api,
    )
    return JobRunTriggerOut(job_run_id=jr.job_run_id, status="running")


class JobRunOut(BaseModel):
    job_run_id: int
    job_schedule_id: int
    status: str
    started_at: Optional[str]
    finished_at: Optional[str]
    summary: Optional[dict]
    error_message: Optional[str]


@router.get("/jobs/{job_schedule_id}/runs", response_model=List[JobRunOut])
def list_job_runs(job_schedule_id: int, limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
    try:
        rows = (
            session.execute(
                select(JobRun).where(JobRun.job_schedule_id == job_schedule_id).order_by(JobRun.started_at.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
        out: List[JobRunOut] = []
        for jr in rows:
            out.append(
                JobRunOut(
                    job_run_id=jr.job_run_id,
                    job_schedule_id=jr.job_schedule_id,
                    status=jr.status,
                    started_at=jr.started_at.isoformat() if jr.started_at else None,
                    finished_at=jr.finished_at.isoformat() if getattr(jr, "finished_at", None) else None,
                    summary=jr.summary,
                    error_message=jr.error_message,
                )
            )
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class JobRunWithTaskOut(BaseModel):
    job_run_id: int
    job_schedule_id: int
    task: str
    status: str
    started_at: Optional[str]
    finished_at: Optional[str]
    duration_seconds: Optional[float]
    summary: Optional[dict]
    error_message: Optional[str]


@router.get("/jobs/runs", response_model=List[JobRunWithTaskOut] | HistoryPage[JobRunWithTaskOut])
def list_all_job_runs(
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = Query(None, description="Filter by status: running, success, failed, skipped, timeout, interrupted"),
    task: Optional[str] = Query(None, description="Filter by task name"),
    offset: Annotated[int, Query(ge=0)] = 0,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    paginated: bool = False,
    session: Session = Depends(get_session)
):
    """List all job runs across all schedules, most recent first."""
    started_after, started_before = history_bounds(started_after, started_before)
    try:
        stmt = (
            select(JobRun, JobSchedule.task)
            .join(JobSchedule, JobSchedule.job_schedule_id == JobRun.job_schedule_id)
            .order_by(JobRun.started_at.desc(), JobRun.job_run_id.desc())
        )
        if status:
            stmt = stmt.where(JobRun.status == status)
        if task:
            stmt = stmt.where(JobSchedule.task == task)
        if started_after:
            stmt = stmt.where(JobRun.started_at >= started_after)
        if started_before:
            stmt = stmt.where(JobRun.started_at < started_before)
        total = 0
        options = {}
        if paginated:
            total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
            options["status"] = list(session.scalars(select(JobRun.status).distinct().order_by(JobRun.status)).all())
            options["task"] = list(session.scalars(select(JobSchedule.task).distinct().order_by(JobSchedule.task)).all())
        stmt = stmt.offset(offset).limit(limit)

        rows = session.execute(stmt).all()
        out: List[JobRunWithTaskOut] = []
        for jr, task_name in rows:
            duration = None
            if jr.started_at and jr.finished_at:
                duration = (jr.finished_at - jr.started_at).total_seconds()
            out.append(
                JobRunWithTaskOut(
                    job_run_id=jr.job_run_id,
                    job_schedule_id=jr.job_schedule_id,
                    task=task_name,
                    status=jr.status,
                    started_at=jr.started_at.isoformat() if jr.started_at else None,
                    finished_at=jr.finished_at.isoformat() if getattr(jr, "finished_at", None) else None,
                    duration_seconds=duration,
                    summary=jr.summary,
                    error_message=jr.error_message,
                )
            )
        return HistoryPage(items=out, total=total, options=options) if paginated else out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class JobScheduleOut(BaseModel):
    job_schedule_id: int
    task: str
    cron_expr: str
    timezone: str
    enabled: bool
    params: Optional[dict]
    allow_overlap: bool


@router.get("/jobs/schedules", response_model=List[JobScheduleOut])
def list_schedules(task: Optional[str] = None, session: Session = Depends(get_session)):
    try:
        stmt = select(JobSchedule)
        if task:
            stmt = stmt.where(JobSchedule.task == task)
        rows = session.execute(stmt.order_by(JobSchedule.job_schedule_id)).scalars().all()
        return [
            JobScheduleOut(
                job_schedule_id=j.job_schedule_id,
                task=j.task,
                cron_expr=j.cron_expr,
                timezone=j.timezone,
                enabled=j.enabled,
                params=j.params,
                allow_overlap=j.allow_overlap,
            )
            for j in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class JobScheduleParamsIn(BaseModel):
    params: dict


def _reject_schedule_credentials(params: dict | None) -> None:
    if params and "api_key" in params:
        raise HTTPException(
            status_code=400,
            detail="Store provider credentials on the data source, not in schedule params.",
        )


@router.put("/jobs/schedules/{job_schedule_id}/params", response_model=JobScheduleOut)
def update_schedule_params(job_schedule_id: int, payload: JobScheduleParamsIn, session: Session = Depends(get_session)):
    job = session.get(JobSchedule, job_schedule_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job schedule {job_schedule_id} not found")
    _reject_schedule_credentials(payload.params)
    try:
        job.params = payload.params
        session.add(job)
        session.commit()
        return JobScheduleOut(
            job_schedule_id=job.job_schedule_id,
            task=job.task,
            cron_expr=job.cron_expr,
            timezone=job.timezone,
            enabled=job.enabled,
            params=job.params,
            allow_overlap=job.allow_overlap,
        )
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


class JobScheduleUpdateIn(BaseModel):
    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    enabled: Optional[bool] = None
    allow_overlap: Optional[bool] = None
    params: Optional[dict] = None


@router.get("/jobs/schedule-preview")
def preview_schedule(cron_expr: str = Query(max_length=64)):
    """Preview the same UTC cron evaluation used by the importer scheduler."""
    try:
        iterator = croniter(cron_expr.strip(), datetime.now(timezone.utc))
        next_runs = []
        for _ in range(3):
            try:
                next_runs.append(iterator.get_next(datetime))
            except CroniterBadDateError:
                # A valid expression can have fewer than three future matches,
                # for example a schedule restricted to a particular year.
                break
        return {"valid": True, "next_runs": next_runs}
    except (ValueError, KeyError, OverflowError):
        return {"valid": False, "next_runs": []}


@router.put("/jobs/schedules/{job_schedule_id}", response_model=JobScheduleOut)
def update_schedule(job_schedule_id: int, payload: JobScheduleUpdateIn, session: Session = Depends(get_session)):
    job = session.get(JobSchedule, job_schedule_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job schedule {job_schedule_id} not found")
    _reject_schedule_credentials(payload.params)
    if payload.cron_expr is not None and not preview_schedule(payload.cron_expr)["valid"]:
        raise HTTPException(status_code=422, detail={"error_code": "invalid_cron"})
    try:
        if payload.cron_expr is not None:
            job.cron_expr = payload.cron_expr.strip()
        if payload.timezone is not None:
            job.timezone = payload.timezone.strip()
        if payload.enabled is not None:
            job.enabled = bool(payload.enabled)
        if payload.allow_overlap is not None:
            job.allow_overlap = bool(payload.allow_overlap)
        if payload.params is not None:
            job.params = payload.params
        session.add(job)
        session.commit()
        return JobScheduleOut(
            job_schedule_id=job.job_schedule_id,
            task=job.task,
            cron_expr=job.cron_expr,
            timezone=job.timezone,
            enabled=job.enabled,
            params=job.params,
            allow_overlap=job.allow_overlap,
        )
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
