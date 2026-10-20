"""Recovery for scheduled importer JobRuns whose owner is no longer active.

The caller must hold the JobSchedule advisory lock before calling
``recover_orphaned_scheduled_runs``. A healthy scheduler holds that same lock
for the complete importer subprocess lifetime, so acquiring it is the evidence
that no scheduler can still complete a persisted scheduled run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import JobExecutionTrigger, JobRun, JobSchedule, JobStatus
from services.event_log import add_event


SCHEDULER_RESTART_RECOVERY_REASON: Final = "scheduler_restart_owner_missing"
SCHEDULE_ADMISSION_RECOVERY_REASON: Final = "schedule_admission_owner_missing"


def recover_orphaned_scheduled_runs(
    session: Session,
    job_schedule: JobSchedule,
    *,
    recovered_at: datetime,
    recovery_reason: str,
) -> tuple[int, ...]:
    """Mark orphaned scheduled runs interrupted while the task lock is held.

    Manual runs are intentionally excluded. They are owned by the API process,
    not by the scheduler advisory lock, and therefore require different proof
    before they could be considered stale.
    """
    running_job_runs = session.scalars(
        select(JobRun)
        .where(
            JobRun.job_schedule_id == job_schedule.job_schedule_id,
            JobRun.status == JobStatus.RUNNING.value,
            JobRun.execution_trigger == JobExecutionTrigger.SCHEDULED.value,
        )
        .order_by(JobRun.job_run_id)
        .with_for_update()
    ).all()

    recovered_job_run_ids: list[int] = []
    for job_run in running_job_runs:
        original_started_at = job_run.started_at
        job_run.status = JobStatus.INTERRUPTED.value
        job_run.finished_at = recovered_at
        job_run.error_message = (
            "CompassAQ marked this scheduled importer run interrupted because "
            "no scheduler still owned its schedule lock."
        )
        session.add(job_run)
        add_event(
            session,
            event_type="scheduler.job_run.interrupted",
            source="scheduler.imports",
            severity="warning",
            message=(
                f"Scheduled {job_schedule.task} import was marked interrupted "
                "because its owning scheduler was no longer active."
            ),
            params={
                "job_run_id": job_run.job_run_id,
                "job_schedule_id": job_schedule.job_schedule_id,
                "task": job_schedule.task,
                "execution_trigger": job_run.execution_trigger,
                "original_started_at": (
                    original_started_at.isoformat() if original_started_at else None
                ),
                "recovered_at": recovered_at.isoformat(),
                "recovery_reason": recovery_reason,
            },
        )
        recovered_job_run_ids.append(job_run.job_run_id)

    if recovered_job_run_ids:
        # Commit while the caller still owns the advisory lock. This makes the
        # terminal rows and their Events visible before replacement admission.
        session.commit()

    return tuple(recovered_job_run_ids)
