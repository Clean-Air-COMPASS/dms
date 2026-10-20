"""Shared subprocess dispatch for scheduled and manual importer runs."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

from db import SessionLocal
from models import JobSchedule
from services.external_sources import require_task_source_runnable
from services.provider_safety import require_paid_provider_authorization


class ImporterTimedOut(RuntimeError):
    """The scheduler stopped an importer that exceeded its runtime ceiling."""

    def __init__(self, timeout_seconds: int):
        super().__init__(
            f"Importer exceeded the {timeout_seconds}-second maximum runtime."
        )
        self.timeout_seconds = timeout_seconds


def run_importer(
    job_run_id: int,
    params: Optional[dict],
    task: str,
    *,
    job_schedule_id: int | None = None,
    explicit_manual_authorization: bool = False,
    target_sensor_id: str | None = None,
    timeout_seconds: int | None = None,
) -> tuple[int, Optional[dict], Optional[str]]:
    """Run the selected importer only after applicable provider safety checks."""
    modules = {
        "demo_import": "sources.demo.importer",
        "openaq_import": "sources.openaq.importer",
        "purpleair_import": "sources.purpleair.importer",
        "airgradient_import": "sources.airgradient.importer",
    }
    module = modules.get(task)
    if module is None:
        return 1, None, f"Unknown task: {task}"

    env = os.environ.copy()
    with SessionLocal() as safety_session:
        require_task_source_runnable(safety_session, task, env)
        if task == "purpleair_import":
            schedule = (
                safety_session.get(JobSchedule, job_schedule_id)
                if job_schedule_id is not None
                else None
            )
            require_paid_provider_authorization(
                safety_session,
                "PurpleAir",
                explicit_manual_authorization=explicit_manual_authorization,
                scheduled_job=None if explicit_manual_authorization else schedule,
            )
    if task == "purpleair_import":
        if explicit_manual_authorization:
            env["PURPLEAIR_EXECUTION_MODE"] = "manual"
            env["PURPLEAIR_MANUAL_AUTHORIZED"] = "true"
        else:
            env["PURPLEAIR_EXECUTION_MODE"] = "scheduled"
            env["PURPLEAIR_JOB_SCHEDULE_ID"] = str(job_schedule_id or "")

    summary_directory = os.getenv("COMPASSAQ_TMP_DIR", "/app/tmp")
    summary_path = os.path.join(summary_directory, f"scheduler_run_{job_run_id}.json")
    os.makedirs(summary_directory, exist_ok=True)

    if target_sensor_id:
        target_environment_names = {
            "openaq_import": "OPENAQ_TARGET_SENSOR_ID",
            "purpleair_import": "PURPLEAIR_TARGET_SENSOR_ID",
        }
        target_environment_name = target_environment_names.get(task)
        if target_environment_name:
            env[target_environment_name] = str(target_sensor_id)

    command = ["python", "-m", module, "--summary-json", summary_path]
    print(f"[scheduler] Starting importer for run {job_run_id} ({task}): {' '.join(command)}")
    try:
        process = subprocess.run(
            command,
            cwd="/app",
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        if timeout_seconds is None:
            raise
        raise ImporterTimedOut(timeout_seconds) from exc

    summary: Optional[dict] = None
    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as summary_file:
                summary = json.load(summary_file)
        except (OSError, json.JSONDecodeError):
            summary = None
    error_message = None
    if process.returncode != 0:
        error_message = (process.stderr or process.stdout or "Importer failed").strip()[:2000]
    return process.returncode, summary, error_message
