from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, File, HTTPException, UploadFile

from db import SessionLocal
import models
from sqlalchemy import select
from services.csv_measurement_import import (
    import_measurements_csv_text,
    validate_csv_upload_file,
)

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/imports/upload-csv")
async def upload_csv_measurements(file: UploadFile = File(...)):
    """
    Minimal CSV ingest for admin uploads.
    Required header columns: internalsensorid, datetime, value
    """
    upload = await validate_csv_upload_file(file)
    return import_measurements_csv_text(upload.text)


@router.post("/imports/run")
def run_import(payload: dict = Body(...)):
    """Run a named importer as a subprocess and return captured output.

    Payload: { source: str, target_sensor_id?: str, force?: bool }
    Currently supports 'openaq'. If a scheduled job for the same source is currently
    running, returns 409 with job_run info unless force=true, in which case the
    running JobRun is marked cancelled and the importer is executed manually.
    """
    source = str(payload.get("source") or "").strip()
    target = payload.get("target_sensor_id")
    api_key = str(payload.get("api_key") or "").strip()
    force = bool(payload.get("force", False))
    if not source:
        raise HTTPException(status_code=400, detail="source is required")

                                                             
    task_map = {
        "openaq": "openaq_import",
        "purpleair": "purpleair_import",
        "airgradient": "airgradient_import",
    }
    task = task_map.get(source)

    job_run_id: Optional[int] = None
    job_schedule: Optional[models.JobSchedule] = None

                                                                                         
    if task:
        with SessionLocal() as session:
            job_schedule = session.scalar(select(models.JobSchedule).where(models.JobSchedule.task == task))
            if job_schedule:
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
                    jr.finished_at = datetime.utcnow()
                    jr.status = "cancelled"
                    jr.error_message = "Cancelled via API by user request"
                    session.add(jr)
                    session.commit()
                manual_summary = {
                    "manual": True,
                    "source": source,
                    "target_sensor_id": target,
                    "force": force,
                    "api_key_supplied": bool(api_key),
                }
                new_jr = models.JobRun(
                    job_schedule_id=job_schedule.job_schedule_id,
                    status=models.JobStatus.RUNNING.value,
                    summary=manual_summary,
                )
                session.add(new_jr)
                session.commit()
                job_run_id = new_jr.job_run_id

    def _update_job_run(status: str, summary: dict | None = None, error_message: str | None = None):
        if job_run_id is None:
            return
        with SessionLocal() as session:
            jr = session.scalar(select(models.JobRun).where(models.JobRun.job_run_id == job_run_id))
            if not jr:
                return
            jr.status = status
            jr.finished_at = datetime.utcnow()
            if summary:
                jr.summary = {**(jr.summary or {}), **summary}
            if error_message:
                jr.error_message = error_message
            session.add(jr)
            session.commit()

    if source == "openaq":
        cmd = ["python", "-m", "sources.openaq.importer"]
        env = os.environ.copy()
        if target:
            env["OPENAQ_TARGET_SENSOR_ID"] = str(target)
        if api_key:
            env["OPENAQ_API_KEY"] = api_key
                                         
        try:
            proc = subprocess.run(cmd, cwd="/app", env=env, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            _update_job_run(models.JobStatus.FAILED.value, error_message="Importer timed out")
            raise HTTPException(status_code=500, detail="Importer timed out")
        summary = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "manual": True,
        }
        _update_job_run(models.JobStatus.SUCCESS.value if proc.returncode == 0 else models.JobStatus.FAILED.value, summary=summary)
        return {
            "source": source,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "job_run_id": job_run_id,
            "manual": True,
        }
    elif source == "purpleair":
        cmd = ["python", "-m", "sources.purpleair.importer"]
        env = os.environ.copy()
        if target:
            env["PURPLEAIR_TARGET_SENSOR_ID"] = str(target)
        if api_key:
            env["PURPLEAIR_API_KEY"] = api_key
        try:
            proc = subprocess.run(cmd, cwd="/app", env=env, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            _update_job_run(models.JobStatus.FAILED.value, error_message="Importer timed out")
            raise HTTPException(status_code=500, detail="Importer timed out")
        summary = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "manual": True,
        }
        _update_job_run(models.JobStatus.SUCCESS.value if proc.returncode == 0 else models.JobStatus.FAILED.value, summary=summary)
        return {
            "source": source,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "job_run_id": job_run_id,
            "manual": True,
        }
    elif source == "airgradient":
        cmd = ["python", "-m", "sources.airgradient.importer"]
        env = os.environ.copy()
        if api_key:
            env["AIRGRADIENT_API_KEY"] = api_key
        try:
            proc = subprocess.run(cmd, cwd="/app", env=env, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            _update_job_run(models.JobStatus.FAILED.value, error_message="Importer timed out")
            raise HTTPException(status_code=500, detail="Importer timed out")
        summary = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "manual": True,
        }
        _update_job_run(models.JobStatus.SUCCESS.value if proc.returncode == 0 else models.JobStatus.FAILED.value, summary=summary)
        return {
            "source": source,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "job_run_id": job_run_id,
            "manual": True,
        }
    else:
        raise HTTPException(status_code=400, detail=f"Unknown source: {source}")
