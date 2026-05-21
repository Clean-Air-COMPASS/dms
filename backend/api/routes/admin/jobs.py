from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from db import get_session
from models import JobSchedule, JobRun

router = APIRouter(prefix="/admin", tags=["admin"]) 


class JobRunTriggerOut(BaseModel):
    job_run_id: int
    status: str


def _run_importer_subprocess(job_run_id: int) -> tuple[int, dict | None, str | None]:
    """Run importer and return (exit_code, summary_json, error_message)."""
    import os as _os
    import json as _json
    import subprocess as _subprocess

    summary_path = f"/app/tmp/scheduler_run_{job_run_id}.json"
    try:
        _os.makedirs("/app/tmp", exist_ok=True)
    except Exception:
        pass
    cmd = [
        "python",
        "-m",
        "sources.openaq.importer",
        "--summary-json",
        summary_path,
    ]
    proc = _subprocess.run(cmd, cwd="/app", capture_output=True, text=True)
    summary = None
    if _os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = _json.load(f)
        except Exception:
            summary = None
    err = None
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "Importer failed").strip()[:2000]
    return proc.returncode, summary, err


def _background_run_job(job_schedule_id: int, job_run_id: int):
    from db import SessionLocal as _SessionLocal
    from datetime import datetime as _dt, timezone as _tz
    with _SessionLocal() as s:
        try:
            code, summary, err = _run_importer_subprocess(job_run_id)
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
def trigger_job_run(job_schedule_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Manually trigger a job run for the given schedule.

    - Respects allow_overlap: if false and a run is already running, returns 409.
    - Spawns importer in a background task; returns the JobRun id immediately.
    """
    job = session.get(JobSchedule, job_schedule_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job schedule {job_schedule_id} not found")

                   
    if not job.allow_overlap:
        active = session.execute(text("SELECT count(1) FROM job_run WHERE job_schedule_id=:sid AND status='running'"), {"sid": job_schedule_id}).scalar()
        if active and int(active) > 0:
            raise HTTPException(status_code=409, detail="A run is already in progress for this schedule")

    from datetime import datetime, timezone
    jr = JobRun(job_schedule_id=job_schedule_id, status="running", started_at=datetime.now(timezone.utc))
    session.add(jr)
    session.commit()

    background_tasks.add_task(_background_run_job, job_schedule_id, jr.job_run_id)
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


@router.get("/jobs/runs", response_model=List[JobRunWithTaskOut])
def list_all_job_runs(
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = Query(None, description="Filter by status: running, success, failed, skipped, timeout"),
    task: Optional[str] = Query(None, description="Filter by task name"),
    session: Session = Depends(get_session)
):
    """List all job runs across all schedules, most recent first."""
    try:
        stmt = (
            select(JobRun, JobSchedule.task)
            .join(JobSchedule, JobSchedule.job_schedule_id == JobRun.job_schedule_id)
            .order_by(JobRun.started_at.desc())
        )
        if status:
            stmt = stmt.where(JobRun.status == status)
        if task:
            stmt = stmt.where(JobSchedule.task == task)
        stmt = stmt.limit(limit)

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
        return out
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


@router.put("/jobs/schedules/{job_schedule_id}/params", response_model=JobScheduleOut)
def update_schedule_params(job_schedule_id: int, payload: JobScheduleParamsIn, session: Session = Depends(get_session)):
    job = session.get(JobSchedule, job_schedule_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job schedule {job_schedule_id} not found")
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


@router.put("/jobs/schedules/{job_schedule_id}", response_model=JobScheduleOut)
def update_schedule(job_schedule_id: int, payload: JobScheduleUpdateIn, session: Session = Depends(get_session)):
    job = session.get(JobSchedule, job_schedule_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job schedule {job_schedule_id} not found")
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
