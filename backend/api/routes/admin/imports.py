from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from api.auth_deps import CurrentUser, get_current_user

from db import SessionLocal
import models
from sqlalchemy import select
from services.csv_measurement_import import (
    import_measurements_csv_upload,
)
from services.external_sources import (
    ExternalSourceNotRunnable,
    require_task_source_runnable,
)
from services.provider_safety import (
    ProviderSafetyDenied,
    require_paid_provider_authorization,
)
from jobs.import_runner import run_importer

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/imports/upload-csv")
async def upload_csv_measurements(file: UploadFile = File(...), current_user: CurrentUser = Depends(get_current_user)):
    """
    Minimal CSV ingest for admin uploads.
    Required header columns: internalsensorid, datetime, value
    """
    return await import_measurements_csv_upload(
        file, endpoint="/admin/imports/upload-csv",
        actor_user_id=current_user.user_id, actor_email=current_user.email,
    )


@router.post("/imports/run")
def run_import(payload: dict = Body(...)):
    """Run a named importer as a subprocess and return captured output.

    Payload: { source: str, target_sensor_id?: str, force?: bool }
    Supports Demo Data, OpenAQ, PurpleAir, and AirGradient. If a scheduled job for the same
    source is currently running, returns 409 with JobRun information unless
    force=true, in which case the running JobRun is marked cancelled and the
    importer is executed manually.
    """
    source = str(payload.get("source") or "").strip()
    target = payload.get("target_sensor_id")
    force = bool(payload.get("force", False))
    if not source:
        raise HTTPException(status_code=400, detail="source is required")

    task_map = {
        "demo": "demo_import",
        "openaq": "openaq_import",
        "purpleair": "purpleair_import",
        "airgradient": "airgradient_import",
    }
    task = task_map.get(source)
    if task is None:
        raise HTTPException(status_code=400, detail=f"Unknown source: {source}")

    try:
        with SessionLocal() as source_session:
            require_task_source_runnable(source_session, task)
    except ExternalSourceNotRunnable as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.state.runnable_reason.value},
        ) from exc

    if source == "purpleair":
        try:
            with SessionLocal() as safety_session:
                require_paid_provider_authorization(
                    safety_session,
                    "PurpleAir",
                    explicit_manual_authorization=True,
                )
        except ProviderSafetyDenied as exc:
            raise HTTPException(status_code=403, detail=exc.as_detail()) from exc

                                                             
    job_run_id: Optional[int] = None
    job_schedule: Optional[models.JobSchedule] = None
    job_schedule_id: Optional[int] = None
    job_schedule_params: Optional[dict] = None

                                                                                         
    if task:
        with SessionLocal() as session:
            job_schedule = session.scalar(select(models.JobSchedule).where(models.JobSchedule.task == task))
            if job_schedule:
                job_schedule_id = job_schedule.job_schedule_id
                job_schedule_params = dict(job_schedule.params or {})
                jr = session.scalar(
                    select(models.JobRun).where(
                        models.JobRun.job_schedule_id == job_schedule.job_schedule_id,
                        models.JobRun.status == "running",
                    )
                )
                if jr and not force:
                                                                           
                    raise HTTPException(status_code=409, detail={
                        "running": True,
                        "job_run": {
                            "job_run_id": jr.job_run_id,
                            "started_at": getattr(jr, "started_at", None),
                            "job_schedule_id": getattr(jr, "job_schedule_id", None),
                        },
                    })
                if jr and force:
                    jr.finished_at = datetime.now(timezone.utc)
                    jr.status = "cancelled"
                    jr.error_message = "Cancelled via API by user request"
                    session.add(jr)
                    session.commit()
                manual_summary = {
                    "manual": True,
                    "source": source,
                    "target_sensor_id": target,
                    "force": force,
                }
                new_jr = models.JobRun(
                    job_schedule_id=job_schedule.job_schedule_id,
                    status=models.JobStatus.RUNNING.value,
                    execution_trigger=models.JobExecutionTrigger.MANUAL.value,
                    summary=manual_summary,
                )
                session.add(new_jr)
                session.commit()
                job_run_id = new_jr.job_run_id

    if job_schedule is None or job_schedule_id is None or job_run_id is None:
        raise HTTPException(
            status_code=409,
            detail="No Job Schedule is configured for this importer.",
        )

    def _update_job_run(status: str, summary: dict | None = None, error_message: str | None = None):
        if job_run_id is None:
            return
        with SessionLocal() as session:
            jr = session.scalar(select(models.JobRun).where(models.JobRun.job_run_id == job_run_id))
            if not jr:
                return
            jr.status = status
            jr.finished_at = datetime.now(timezone.utc)
            if summary is not None:
                jr.summary = summary
            if error_message:
                jr.error_message = error_message
            session.add(jr)
            session.commit()

    return_code, summary, error_message = run_importer(
        job_run_id,
        job_schedule_params,
        task,
        job_schedule_id=job_schedule_id,
        explicit_manual_authorization=True,
        target_sensor_id=str(target) if target else None,
    )
    final_status = (
        models.JobStatus.SUCCESS.value
        if return_code == 0
        else models.JobStatus.FAILED.value
    )
    _update_job_run(final_status, summary=summary, error_message=error_message)
    return {
        "source": source,
        "returncode": return_code,
        "summary": summary,
        "error_message": error_message,
        "job_run_id": job_run_id,
        "manual": True,
    }
