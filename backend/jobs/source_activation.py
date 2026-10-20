"""Scheduler admission control for external-source jobs."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import JobExecutionTrigger, JobRun, JobSchedule, JobStatus
from services.external_sources import (
    ExternalSourceNotRunnable,
    require_task_source_runnable,
)


def job_schedule_has_prior_run(session: Session, job: JobSchedule) -> bool:
    """Return whether JobRun records any attempt for this schedule."""
    return session.scalar(
        select(JobRun.job_run_id)
        .where(JobRun.job_schedule_id == job.job_schedule_id)
        .limit(1)
    ) is not None


def initial_source_import_is_due(session: Session, job: JobSchedule) -> bool:
    """A runnable built-in source with no authoritative JobRun is due now."""
    try:
        require_task_source_runnable(session, job.task)
    except ExternalSourceNotRunnable:
        return False
    return not job_schedule_has_prior_run(session, job)


def scheduled_run_started_since(
    session: Session,
    job: JobSchedule,
    occurrence_started_at: datetime,
) -> bool:
    """Return whether another scheduler already admitted this occurrence.

    This check is performed while holding the schedule advisory lock. An
    interrupted row does not satisfy an occurrence because stale recovery must
    be allowed to admit its replacement.
    """
    return session.scalar(
        select(JobRun.job_run_id)
        .where(
            JobRun.job_schedule_id == job.job_schedule_id,
            JobRun.execution_trigger == JobExecutionTrigger.SCHEDULED.value,
            JobRun.status != JobStatus.INTERRUPTED.value,
            JobRun.started_at >= occurrence_started_at,
        )
        .limit(1)
    ) is not None


def create_job_run_if_source_runnable(
    session: Session,
    job: JobSchedule,
    *,
    initial_run_only: bool = False,
) -> JobRun | None:
    """Create and commit a run after locking and rechecking its source.

    Committing before provider work makes JobRun immediately authoritative and
    releases the source-row lock. AirGradient updates its per-location reference
    initialization state on that same source row from the importer subprocess.
    """
    try:
        require_task_source_runnable(session, job.task, for_update=True)
    except ExternalSourceNotRunnable:
        return None
    if initial_run_only and job_schedule_has_prior_run(session, job):
        return None
    job_run = JobRun(
        job_schedule_id=job.job_schedule_id,
        status="running",
        execution_trigger=JobExecutionTrigger.SCHEDULED.value,
        started_at=datetime.now(timezone.utc),
    )
    session.add(job_run)
    session.commit()
    return job_run
