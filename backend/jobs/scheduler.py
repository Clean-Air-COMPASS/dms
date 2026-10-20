"""Simple DB-backed scheduler loop.

Reads JobSchedule rows, computes next run times via cron expressions, uses
Postgres advisory locks to ensure only one runner executes a job at a time,
invokes the selected importer as a subprocess, and records JobRun status.

Environment variables:
- SCHEDULER_TICK_SECONDS: poll interval (default: 15)
- SCHEDULER_IMPORT_MAX_RUNTIME_SECONDS: scheduled importer ceiling (default: 21600)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Final

from croniter import croniter
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

from db import SessionLocal
from models import JobExecutionTrigger, JobRun, JobSchedule, JobStatus
from jobs.import_runner import ImporterTimedOut, run_importer
from jobs.locking import advisory_unlock, try_advisory_lock
from jobs.source_activation import (
    create_job_run_if_source_runnable,
    initial_source_import_is_due,
    scheduled_run_started_since,
)
from jobs.stale_runs import (
    SCHEDULE_ADMISSION_RECOVERY_REASON,
    SCHEDULER_RESTART_RECOVERY_REASON,
    recover_orphaned_scheduled_runs,
)
from services.external_sources import (
    ExternalSourceNotRunnable,
    require_task_source_runnable,
)
from services.administrator_summary_delivery import (
    process_due_administrator_summary,
)
from services.system_settings import is_system_setup_complete


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_IMPORT_MAX_RUNTIME_SECONDS: Final = 6 * 60 * 60


def _scheduled_import_max_runtime_seconds() -> int:
    configured_value = os.getenv(
        "SCHEDULER_IMPORT_MAX_RUNTIME_SECONDS",
        str(DEFAULT_IMPORT_MAX_RUNTIME_SECONDS),
    )
    timeout_seconds = int(configured_value)
    if timeout_seconds <= 0:
        raise ValueError("SCHEDULER_IMPORT_MAX_RUNTIME_SECONDS must be positive")
    return timeout_seconds


def _recover_orphaned_runs_on_startup() -> None:
    """Reconcile prior scheduled owners one schedule at a time under its lock."""
    with SessionLocal() as session:
        schedule_ids = session.scalars(
            select(JobRun.job_schedule_id)
            .where(
                JobRun.finished_at == None,
                JobRun.status == JobStatus.RUNNING.value,
                JobRun.execution_trigger == JobExecutionTrigger.SCHEDULED.value,
            )
            .distinct()
            .order_by(JobRun.job_schedule_id)
        ).all()

    for job_schedule_id in schedule_ids:
        with SessionLocal() as session:
            job_schedule = session.get(JobSchedule, job_schedule_id)
            if job_schedule is None:
                continue
            lock_connection = session.get_bind().connect()
            lock_acquired = False
            try:
                lock_acquired = try_advisory_lock(
                    lock_connection,
                    int(job_schedule_id),
                )
                if not lock_acquired:
                    continue
                recovered_ids = recover_orphaned_scheduled_runs(
                    session,
                    job_schedule,
                    recovered_at=_now_utc(),
                    recovery_reason=SCHEDULER_RESTART_RECOVERY_REASON,
                )
                if recovered_ids:
                    print(
                        "[scheduler] Recovered interrupted job_run(s) on startup: "
                        + ", ".join(str(job_run_id) for job_run_id in recovered_ids)
                    )
            finally:
                if lock_acquired:
                    advisory_unlock(lock_connection, int(job_schedule_id))
                lock_connection.close()


def main() -> None:

    tick = int(os.getenv("SCHEDULER_TICK_SECONDS", "15"))
    import_max_runtime_seconds = _scheduled_import_max_runtime_seconds()
                                                                                     
    next_due: Dict[int, datetime] = {}
    cron_seen: Dict[int, str] = {}
    startup_recovery_pending = True
    waiting_for_setup = False

    print(
        f"[scheduler] Loop started; tick={tick}s; "
        f"import_max_runtime={import_max_runtime_seconds}s"
    )

    while True:
        try:
            with SessionLocal() as setup_session:
                setup_complete = is_system_setup_complete(setup_session)

            if not setup_complete:
                if not waiting_for_setup:
                    print(
                        "[scheduler] Waiting for first-run setup to be completed"
                    )
                waiting_for_setup = True
                next_due.clear()
                cron_seen.clear()
                time.sleep(tick)
                continue

            if waiting_for_setup:
                print("[scheduler] Setup complete; scheduled work is enabled")
                waiting_for_setup = False

            if startup_recovery_pending:
                _recover_orphaned_runs_on_startup()
                startup_recovery_pending = False

            with SessionLocal() as session:
                now = _now_utc()
                try:
                    summary_result = process_due_administrator_summary(
                        session,
                        now_utc=now,
                    )
                    if summary_result.status.value == "sent":
                        print(
                            "[scheduler] Administrator summary sent for "
                            f"{summary_result.period_start_utc}–"
                            f"{summary_result.period_end_utc}"
                        )
                except Exception as summary_error:
                    # Summary failure must not prevent normal importer work in
                    # the same polling loop.
                    session.rollback()
                    print(
                        "[scheduler] Administrator summary processing error: "
                        f"{type(summary_error).__name__}"
                    )

                jobs = session.scalars(
                    select(JobSchedule).where(JobSchedule.enabled == True)
                ).all()
                for job in jobs:
                    initial_run_due = initial_source_import_is_due(session, job)
                    # A disabled or blocked source is normal scheduler control flow.
                    # Advance its in-memory due time without treating the absence of a
                    # JobRun as a missed execution on every scheduler tick.
                    try:
                        require_task_source_runnable(session, job.task)
                    except ExternalSourceNotRunnable:
                        cron_seen[job.job_schedule_id] = job.cron_expr
                        try:
                            next_due[job.job_schedule_id] = croniter(
                                job.cron_expr, now
                            ).get_next(datetime)
                        except Exception as e:
                            print(f"[scheduler] Invalid cron for job {job.job_schedule_id}: {e}")
                        continue

                    if initial_run_due:
                        # JobRun is the authoritative record. A runnable schedule
                        # with no prior run must not wait for an arbitrary cron edge.
                        cron_seen[job.job_schedule_id] = job.cron_expr
                        next_due[job.job_schedule_id] = now

                                                                                   
                    last = cron_seen.get(job.job_schedule_id)
                    if initial_run_due:
                        pass
                    elif last is None:
                                                                                                  
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
                        # Recheck immediately before locking and creating a JobRun in
                        # case an administrator changed the source while it was due.
                        try:
                            require_task_source_runnable(session, job.task)
                        except ExternalSourceNotRunnable:
                            next_due[job.job_schedule_id] = croniter(
                                job.cron_expr, next_due[job.job_schedule_id]
                            ).get_next(datetime)
                            continue

                        lock_key = int(job.job_schedule_id)
                        # Keep the session-level advisory lock on a dedicated
                        # connection. JobRun admission commits before provider
                        # work, which may return the ORM connection to the pool.
                        lock_connection = session.get_bind().connect()
                        try:
                            lock_acquired = try_advisory_lock(
                                lock_connection, lock_key
                            )
                        except Exception:
                            lock_connection.close()
                            raise
                        if not lock_acquired:
                            lock_connection.close()
                            continue

                        try:
                            recovered_ids = recover_orphaned_scheduled_runs(
                                session,
                                job,
                                recovered_at=_now_utc(),
                                recovery_reason=SCHEDULE_ADMISSION_RECOVERY_REASON,
                            )
                            if recovered_ids:
                                print(
                                    "[scheduler] Recovered interrupted job_run(s) "
                                    f"for job {job.job_schedule_id}: "
                                    + ", ".join(
                                        str(job_run_id) for job_run_id in recovered_ids
                                    )
                                )

                            occurrence_started_at = croniter(
                                job.cron_expr,
                                now + timedelta(microseconds=1),
                            ).get_prev(datetime)
                            if scheduled_run_started_since(
                                session,
                                job,
                                occurrence_started_at,
                            ):
                                print(
                                    "[scheduler] Cron occurrence already handled "
                                    f"for job {job.job_schedule_id} at "
                                    f"{occurrence_started_at.isoformat()}"
                                )
                                continue

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

                            jr = create_job_run_if_source_runnable(
                                session,
                                job,
                                initial_run_only=initial_run_due,
                            )
                            if jr is None:
                                continue

                            try:
                                code, summary, err = run_importer(
                                    jr.job_run_id,
                                    job.params,
                                    job.task,
                                    job_schedule_id=job.job_schedule_id,
                                    timeout_seconds=import_max_runtime_seconds,
                                )
                                jr.summary = summary
                                jr.status = "success" if code == 0 else "failed"
                                jr.error_message = err
                            except ImporterTimedOut as timeout_error:
                                jr.status = JobStatus.TIMEOUT.value
                                jr.error_message = str(timeout_error)
                            jr.finished_at = _now_utc()
                            session.add(jr)
                            session.commit()
                            print(f"[scheduler] Run {jr.job_run_id} completed with status={jr.status}")

                        finally:
                            advisory_unlock(lock_connection, lock_key)
                            lock_connection.close()
                                                                                                      
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
