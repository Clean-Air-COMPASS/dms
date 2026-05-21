"""Simple DB-backed scheduler loop.

Reads JobSchedule rows, computes next run times via cron expressions, uses
Postgres advisory locks to ensure only one runner executes a job at a time,
invokes the OpenAQ importer as a subprocess, and records JobRun status.

Environment variables:
- SCHEDULER_TICK_SECONDS: poll interval (default: 15)
- SCHEDULER_CREATE_DEFAULT: if '1', create a default top-of-hour schedule
  for task 'openaq_import' when none exists.
"""

from __future__ import annotations

import os
import json
import time
import subprocess
from datetime import datetime, timezone
from typing import Dict, Optional

from croniter import croniter
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

from db import SessionLocal
from models import JobSchedule, JobRun


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_default_schedule(session: Session) -> None:
    """Create default top-of-hour schedules if none exist for known tasks."""
    created = 0
    for task in ("openaq_import", "purpleair_import", "airgradient_import"):
        q = session.scalar(select(JobSchedule).where(JobSchedule.task == task))
        if q:
            continue
        js = JobSchedule(
            task=task,
            cron_expr="0 * * * *",
            timezone="UTC",
            enabled=True,
            params=None,
            allow_overlap=False,
        )
        session.add(js)
        session.commit()
        created += 1
        print(f"Created default schedule: {task} @ top of hour (UTC)")


def try_advisory_lock(session: Session, key: int) -> bool:
    r = session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
    return bool(r)


def advisory_unlock(session: Session, key: int) -> None:
    try:
        session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
    except Exception:
        pass


def run_importer(job_run_id: int, params: Optional[dict], task: str) -> tuple[int, Optional[dict], Optional[str]]:
    """Run the importer for the given task and capture summary.

    Returns (exit_code, summary_dict, error_message)
    """
    summary_path = f"/app/tmp/scheduler_run_{job_run_id}.json"
    os.makedirs("/app/tmp", exist_ok=True)

                                                                 
    module = (
        "sources.openaq.importer"
        if task == "openaq_import"
        else "sources.purpleair.importer"
        if task == "purpleair_import"
        else "sources.airgradient.importer"
        if task == "airgradient_import"
        else None
    )
    if not module:
                                                   
        return 1, None, f"Unknown task: {task}"
    cmd = ["python", "-m", module, "--summary-json", summary_path]
                                                                               
    env = os.environ.copy()
    try:
        if params and isinstance(params, dict):
            api_key = params.get("api_key")
            if api_key:
                if task == "openaq_import":
                    env["OPENAQ_API_KEY"] = str(api_key)
                elif task == "purpleair_import":
                    env["PURPLEAIR_API_KEY"] = str(api_key)
                elif task == "airgradient_import":
                    env["AIRGRADIENT_API_KEY"] = str(api_key)
    except Exception:
        pass

                                                                      
                                                                             

    print(f"[scheduler] Starting importer for run {job_run_id} ({task}): {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd="/app", capture_output=True, text=True, env=env)

    summary: Optional[dict] = None
    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception:
            summary = None

    err = None
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "Importer failed").strip()[:2000]

    return proc.returncode, summary, err


def main() -> None:

    tick = int(os.getenv("SCHEDULER_TICK_SECONDS", "15"))
    create_default = os.getenv("SCHEDULER_CREATE_DEFAULT", "1") == "1"

                                                                                     
    next_due: Dict[int, datetime] = {}
    cron_seen: Dict[int, str] = {}

                                                                           
    with SessionLocal() as session:
                                                                               
        incomplete_runs = session.scalars(
            select(JobRun).where(JobRun.finished_at == None, JobRun.status == "running")
        ).all()
        for jr in incomplete_runs:
            jr.finished_at = _now_utc()
            jr.status = "failed"
            jr.error_message = "Scheduler was interrupted and did not complete this run. Marked as failed on startup."
            session.add(jr)
        if incomplete_runs:
            session.commit()
            print(f"[scheduler] Marked {len(incomplete_runs)} incomplete job_run(s) as failed on startup.")

        if create_default:
            try:
                ensure_default_schedule(session)
            except Exception as e:
                print(f"[scheduler] ensure_default_schedule error: {e}")

    print(f"[scheduler] Loop started; tick={tick}s")

    while True:
        try:
            with SessionLocal() as session:
                jobs = session.scalars(select(JobSchedule).where(JobSchedule.enabled == True)).all()

                now = _now_utc()
                for job in jobs:
                                                                                   
                    last = cron_seen.get(job.job_schedule_id)
                    if last is None:
                                                                                                  
                        cron_seen[job.job_schedule_id] = job.cron_expr
                                                                                                     
                        try:
                            prev_due = croniter(job.cron_expr, now).get_prev(datetime)
                        except Exception as e:
                            print(f"[scheduler] Invalid cron for job {job.job_schedule_id}: {e}")
                            prev_due = None
                        last_run_started = session.execute(
                            select(func.max(JobRun.started_at)).where(JobRun.job_schedule_id == job.job_schedule_id)
                        ).scalar()
                                                                                                                                
                        if prev_due is not None and (last_run_started is None or (last_run_started < prev_due)):
                            next_due[job.job_schedule_id] = now
                            print(
                                f"[scheduler] Detected missed run for job {job.job_schedule_id} (due {prev_due.isoformat()}); executing immediately"
                            )
                        else:
                                                                           
                            try:
                                nd = croniter(job.cron_expr, now).get_next(datetime)
                                next_due[job.job_schedule_id] = nd
                                print(f"[scheduler] Job {job.job_schedule_id} next due at {nd.isoformat()}")
                            except Exception as e:
                                print(f"[scheduler] Invalid cron for job {job.job_schedule_id}: {e}")
                                continue
                    elif last != job.cron_expr:
                                                                 
                        try:
                            nd = croniter(job.cron_expr, now).get_next(datetime)
                            next_due[job.job_schedule_id] = nd
                            cron_seen[job.job_schedule_id] = job.cron_expr
                            print(
                                f"[scheduler] Job {job.job_schedule_id} cron changed -> next due at {nd.isoformat()}"
                            )
                        except Exception as e:
                            print(f"[scheduler] Invalid cron for job {job.job_schedule_id}: {e}")
                            continue

                                                                                                      
                    nd = next_due.get(job.job_schedule_id)
                    if nd is None:
                        try:
                            nd = croniter(job.cron_expr, now).get_next(datetime)
                        except Exception as e:
                            print(f"[scheduler] Invalid cron for job {job.job_schedule_id}: {e}")
                            continue
                        next_due[job.job_schedule_id] = nd
                        print(f"[scheduler] Job {job.job_schedule_id} next due at {nd.isoformat()}")

                                                                                                              
                                                                                                               
                                                                                  
                    try:
                        prev_due2 = croniter(job.cron_expr, now).get_prev(datetime)
                    except Exception:
                        prev_due2 = None
                    last_run_started2 = session.execute(
                        select(func.max(JobRun.started_at)).where(JobRun.job_schedule_id == job.job_schedule_id)
                    ).scalar()
                    if prev_due2 is not None and (last_run_started2 is None or (last_run_started2 < prev_due2)) and now < next_due[job.job_schedule_id]:
                        next_due[job.job_schedule_id] = now
                        print(
                            f"[scheduler] Missed-run guard triggered for job {job.job_schedule_id} (prev {prev_due2.isoformat()}, last_run {last_run_started2}); executing immediately"
                        )

                                                                                                        
                    if now >= next_due[job.job_schedule_id]:
                        lock_key = int(job.job_schedule_id)
                        if not try_advisory_lock(session, lock_key):
                                                             
                                                                               
                            continue

                        try:
                                                                                                   
                            if not job.allow_overlap:
                                active = session.execute(
                                    text(
                                        "SELECT count(1) FROM job_run WHERE job_schedule_id=:sid AND status='running'"
                                    ),
                                    {"sid": job.job_schedule_id},
                                ).scalar()
                                if active and int(active) > 0:
                                    print(f"[scheduler] Skip overlap for job {job.job_schedule_id}")
                                                                                  
                                    continue

                            jr = JobRun(job_schedule_id=job.job_schedule_id, status="running", started_at=_now_utc())
                            session.add(jr)
                            session.commit()

                            code, summary, err = run_importer(jr.job_run_id, job.params, job.task)

                            jr.finished_at = _now_utc()
                            jr.summary = summary
                            jr.status = "success" if code == 0 else "failed"
                            jr.error_message = err
                            session.add(jr)
                            session.commit()
                            print(f"[scheduler] Run {jr.job_run_id} completed with status={jr.status}")

                        finally:
                            advisory_unlock(session, lock_key)
                                                                                                      
                            try:
                                prev_due = next_due[job.job_schedule_id]
                                next_due[job.job_schedule_id] = croniter(job.cron_expr, prev_due).get_next(datetime)
                            except Exception as e:
                                print(f"[scheduler] Failed to compute next due for job {job.job_schedule_id}: {e}")
                            else:
                                print(
                                    f"[scheduler] Job {job.job_schedule_id} next due at {next_due[job.job_schedule_id].isoformat()}"
                                )
                                                          

        except Exception as e:
            print(f"[scheduler] loop error: {e}")

        time.sleep(tick)


if __name__ == "__main__":
    main()
