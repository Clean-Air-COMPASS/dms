from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from threading import Event as ThreadEvent, Thread

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

import models
from jobs import scheduler
from jobs.locking import advisory_unlock, try_advisory_lock
from jobs.source_activation import scheduled_run_started_since
from jobs.stale_runs import (
    SCHEDULE_ADMISSION_RECOVERY_REASON,
    recover_orphaned_scheduled_runs,
)
from postgresql_test_support import (
    POSTGRES_TEST_URL_ENV,
    temporary_postgres_database,
    upgrade,
)


UTC = timezone.utc


def _schedule_for_task(session: Session, task: str) -> models.JobSchedule:
    schedule = session.scalar(
        select(models.JobSchedule).where(models.JobSchedule.task == task)
    )
    assert schedule is not None
    return schedule


def test_postgresql_active_owner_blocks_restart_recovery() -> None:
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL scheduler tests")

    with temporary_postgres_database("stale_run_active_owner") as (
        database_url,
        engine,
    ):
        upgrade(database_url, "head")
        SessionLocal = sessionmaker(bind=engine)
        started_at = datetime(2026, 8, 24, 5, tzinfo=UTC)
        with SessionLocal() as session:
            schedule = _schedule_for_task(session, "openaq_import")
            session.add(
                models.JobRun(
                    job_schedule_id=schedule.job_schedule_id,
                    status=models.JobStatus.RUNNING.value,
                    execution_trigger=models.JobExecutionTrigger.SCHEDULED.value,
                    started_at=started_at,
                )
            )
            session.commit()
            schedule_id = schedule.job_schedule_id

        active_owner_connection = engine.connect()
        assert try_advisory_lock(active_owner_connection, schedule_id) is True
        original_session_factory = scheduler.SessionLocal
        scheduler.SessionLocal = SessionLocal
        try:
            # Age alone is not enough. Even a two-day-old run remains active
            # while its scheduler ownership lock is present.
            scheduler._recover_orphaned_runs_on_startup()
            with SessionLocal() as session:
                active_run = session.scalar(
                    select(models.JobRun).where(
                        models.JobRun.job_schedule_id == schedule_id
                    )
                )
                assert active_run is not None
                assert active_run.status == models.JobStatus.RUNNING.value
                assert active_run.finished_at is None
                assert session.scalar(
                    select(func.count()).select_from(models.Event)
                ) == 0

            advisory_unlock(active_owner_connection, schedule_id)
            active_owner_connection.close()
            scheduler._recover_orphaned_runs_on_startup()

            with SessionLocal() as session:
                recovered_run = session.scalar(
                    select(models.JobRun).where(
                        models.JobRun.job_schedule_id == schedule_id
                    )
                )
                assert recovered_run is not None
                assert recovered_run.status == models.JobStatus.INTERRUPTED.value
                assert recovered_run.finished_at is not None
                assert session.scalar(
                    select(func.count())
                    .select_from(models.Event)
                    .where(
                        models.Event.event_type
                        == "scheduler.job_run.interrupted"
                    )
                ) == 1
        finally:
            scheduler.SessionLocal = original_session_factory
            if not active_owner_connection.closed:
                advisory_unlock(active_owner_connection, schedule_id)
                active_owner_connection.close()


def test_postgresql_two_schedulers_start_only_one_replacement_run() -> None:
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL scheduler tests")

    with temporary_postgres_database("stale_run_replacement") as (
        database_url,
        engine,
    ):
        upgrade(database_url, "head")
        started_at = datetime(2026, 8, 26, 5, tzinfo=UTC)
        with Session(engine) as session:
            schedule = _schedule_for_task(session, "purpleair_import")
            stale_run = models.JobRun(
                job_schedule_id=schedule.job_schedule_id,
                status=models.JobStatus.RUNNING.value,
                execution_trigger=models.JobExecutionTrigger.SCHEDULED.value,
                started_at=started_at,
            )
            session.add(stale_run)
            session.commit()
            schedule_id = schedule.job_schedule_id
            stale_run_id = stale_run.job_run_id

        replacement_started = ThreadEvent()
        allow_replacement_to_finish = ThreadEvent()
        first_scheduler_errors: list[BaseException] = []

        def first_scheduler() -> None:
            lock_connection = engine.connect()
            try:
                assert try_advisory_lock(lock_connection, schedule_id) is True
                with Session(engine) as session:
                    schedule = session.get(models.JobSchedule, schedule_id)
                    assert schedule is not None
                    recovered_ids = recover_orphaned_scheduled_runs(
                        session,
                        schedule,
                        recovered_at=started_at + timedelta(hours=1),
                        recovery_reason=SCHEDULE_ADMISSION_RECOVERY_REASON,
                    )
                    assert recovered_ids == (stale_run_id,)
                    replacement = models.JobRun(
                        job_schedule_id=schedule_id,
                        status=models.JobStatus.RUNNING.value,
                        execution_trigger=models.JobExecutionTrigger.SCHEDULED.value,
                        started_at=started_at + timedelta(hours=1),
                    )
                    session.add(replacement)
                    session.commit()
                    replacement_id = replacement.job_run_id
                    replacement_started.set()
                    assert allow_replacement_to_finish.wait(timeout=10)
                    replacement = session.get(models.JobRun, replacement_id)
                    assert replacement is not None
                    replacement.status = models.JobStatus.SUCCESS.value
                    replacement.finished_at = started_at + timedelta(hours=1, seconds=20)
                    session.commit()
            except BaseException as exc:
                first_scheduler_errors.append(exc)
                replacement_started.set()
            finally:
                advisory_unlock(lock_connection, schedule_id)
                lock_connection.close()

        worker = Thread(target=first_scheduler)
        worker.start()
        assert replacement_started.wait(timeout=10)
        assert first_scheduler_errors == []

        competing_connection = engine.connect()
        try:
            assert try_advisory_lock(competing_connection, schedule_id) is False
        finally:
            competing_connection.close()

        allow_replacement_to_finish.set()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert first_scheduler_errors == []

        retry_connection = engine.connect()
        try:
            assert try_advisory_lock(retry_connection, schedule_id) is True
            with Session(engine) as session:
                schedule = session.get(models.JobSchedule, schedule_id)
                assert schedule is not None
                assert recover_orphaned_scheduled_runs(
                    session,
                    schedule,
                    recovered_at=started_at + timedelta(hours=1, minutes=1),
                    recovery_reason=SCHEDULE_ADMISSION_RECOVERY_REASON,
                ) == ()
                assert scheduled_run_started_since(
                    session,
                    schedule,
                    started_at + timedelta(hours=1),
                ) is True
                # The retry therefore admits no second replacement run.
        finally:
            advisory_unlock(retry_connection, schedule_id)
            retry_connection.close()

        with Session(engine) as session:
            runs = session.scalars(
                select(models.JobRun)
                .where(models.JobRun.job_schedule_id == schedule_id)
                .order_by(models.JobRun.job_run_id)
            ).all()
            assert [run.status for run in runs] == [
                models.JobStatus.INTERRUPTED.value,
                models.JobStatus.SUCCESS.value,
            ]
            assert session.scalar(
                select(func.count())
                .select_from(models.Event)
                .where(
                    models.Event.event_type == "scheduler.job_run.interrupted"
                )
            ) == 1
