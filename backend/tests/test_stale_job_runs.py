from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import models
from api.routes.admin.jobs import list_all_job_runs
from jobs.source_activation import (
    create_job_run_if_source_runnable,
    scheduled_run_started_since,
)
from jobs.stale_runs import (
    SCHEDULE_ADMISSION_RECOVERY_REASON,
    recover_orphaned_scheduled_runs,
)
from services.administrator_summary_collector import build_administrator_summary
from services.administrator_summary_domain import (
    AdministratorSummaryCadence,
    calculate_completed_reporting_window,
)
from services.administrator_summary_renderer import (
    render_administrator_summary_email,
)


UTC = timezone.utc


def _add_runnable_source_and_schedule(
    session: Session,
    provider_code: str,
) -> models.JobSchedule:
    session.add(
        models.ExternalAPI(
            provider_code=provider_code,
            name=provider_code,
            api_key="configured-key",
            params={},
            enabled=True,
        )
    )
    schedule = models.JobSchedule(
        task=f"{provider_code}_import",
        cron_expr="0 * * * *",
        timezone="UTC",
        enabled=True,
        allow_overlap=False,
    )
    session.add(schedule)
    session.commit()
    return schedule


@pytest.mark.parametrize("provider_code", ["openaq", "purpleair", "airgradient"])
def test_generic_recovery_closes_scheduled_run_and_allows_replacement(
    tmp_path,
    monkeypatch,
    provider_code: str,
) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / f'{provider_code}-recovery.sqlite'}"
    )
    models.Base.metadata.create_all(engine)
    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "false")
    started_at = datetime(2026, 8, 26, 5, tzinfo=UTC)
    recovered_at = started_at + timedelta(hours=19)

    with Session(engine) as session:
        schedule = _add_runnable_source_and_schedule(session, provider_code)
        stale_run = models.JobRun(
            job_schedule_id=schedule.job_schedule_id,
            status=models.JobStatus.RUNNING.value,
            execution_trigger=models.JobExecutionTrigger.SCHEDULED.value,
            started_at=started_at,
        )
        completed_run = models.JobRun(
            job_schedule_id=schedule.job_schedule_id,
            status=models.JobStatus.SUCCESS.value,
            execution_trigger=models.JobExecutionTrigger.SCHEDULED.value,
            started_at=started_at - timedelta(hours=1),
            finished_at=started_at - timedelta(minutes=59),
        )
        session.add_all([stale_run, completed_run])
        session.commit()

        recovered_ids = recover_orphaned_scheduled_runs(
            session,
            schedule,
            recovered_at=recovered_at,
            recovery_reason=SCHEDULE_ADMISSION_RECOVERY_REASON,
        )

        assert recovered_ids == (stale_run.job_run_id,)
        assert stale_run.status == models.JobStatus.INTERRUPTED.value
        assert stale_run.finished_at.replace(tzinfo=UTC) == recovered_at
        assert "no scheduler still owned its schedule lock" in (
            stale_run.error_message or ""
        )
        assert completed_run.status == models.JobStatus.SUCCESS.value
        assert scheduled_run_started_since(
            session,
            schedule,
            recovered_at - timedelta(minutes=30),
        ) is False

        recovery_event = session.scalar(
            select(models.Event).where(
                models.Event.event_type == "scheduler.job_run.interrupted"
            )
        )
        assert recovery_event is not None
        assert recovery_event.severity == "warning"
        assert recovery_event.params["job_run_id"] == stale_run.job_run_id
        assert recovery_event.params["job_schedule_id"] == schedule.job_schedule_id
        assert recovery_event.params["task"] == schedule.task
        assert recovery_event.params["execution_trigger"] == "scheduled"
        assert recovery_event.params["original_started_at"].startswith(
            "2026-08-26T05:00:00"
        )
        assert recovery_event.params["recovered_at"] == recovered_at.isoformat()
        assert (
            recovery_event.params["recovery_reason"]
            == SCHEDULE_ADMISSION_RECOVERY_REASON
        )
        assert "configured-key" not in (recovery_event.message or "")
        assert "configured-key" not in str(recovery_event.params)

        api_runs = list_all_job_runs(limit=100, status=None, task=None, session=session)
        interrupted_api_run = next(
            api_run
            for api_run in api_runs
            if api_run.job_run_id == stale_run.job_run_id
        )
        assert interrupted_api_run.status == models.JobStatus.INTERRUPTED.value
        assert (interrupted_api_run.finished_at or "").startswith(
            "2026-08-27T00:00:00"
        )
        assert "no scheduler still owned its schedule lock" in (
            interrupted_api_run.error_message or ""
        )

        replacement_run = create_job_run_if_source_runnable(session, schedule)
        assert replacement_run is not None
        assert replacement_run.status == models.JobStatus.RUNNING.value
        assert scheduled_run_started_since(
            session,
            schedule,
            replacement_run.started_at - timedelta(seconds=1),
        ) is True
        assert session.scalar(
            select(func.count())
            .select_from(models.JobRun)
            .where(models.JobRun.status == models.JobStatus.RUNNING.value)
        ) == 1


def test_recovery_does_not_reclassify_manual_running_job(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'manual-active.sqlite'}")
    models.Base.metadata.create_all(engine)
    started_at = datetime(2026, 8, 26, 5, tzinfo=UTC)

    with Session(engine) as session:
        schedule = _add_runnable_source_and_schedule(session, "openaq")
        manual_run = models.JobRun(
            job_schedule_id=schedule.job_schedule_id,
            status=models.JobStatus.RUNNING.value,
            execution_trigger=models.JobExecutionTrigger.MANUAL.value,
            started_at=started_at - timedelta(days=2),
        )
        session.add(manual_run)
        session.commit()

        recovered_ids = recover_orphaned_scheduled_runs(
            session,
            schedule,
            recovered_at=started_at,
            recovery_reason=SCHEDULE_ADMISSION_RECOVERY_REASON,
        )

        assert recovered_ids == ()
        assert manual_run.status == models.JobStatus.RUNNING.value
        assert manual_run.finished_at is None
        assert session.scalar(select(func.count()).select_from(models.Event)) == 0


def test_administrator_summary_reports_interrupted_scheduled_run_truthfully() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    period_reference = datetime(2026, 8, 27, 0, tzinfo=UTC)
    reporting_window = calculate_completed_reporting_window(
        period_reference,
        AdministratorSummaryCadence.DAILY,
        "UTC",
    )

    with Session(engine) as session:
        schedule = _add_runnable_source_and_schedule(session, "openaq")
        session.add(
            models.JobRun(
                job_schedule_id=schedule.job_schedule_id,
                status=models.JobStatus.INTERRUPTED.value,
                execution_trigger=models.JobExecutionTrigger.SCHEDULED.value,
                started_at=datetime(2026, 8, 26, 5, tzinfo=UTC),
                finished_at=datetime(2026, 8, 26, 6, tzinfo=UTC),
                error_message="Recovered after scheduler ownership ended.",
            )
        )
        session.commit()

        summary = build_administrator_summary(
            session,
            reporting_window,
            generated_at_utc=period_reference,
            environment={"COMPASSAQ_ENV": "development"},
        )

    source_summary = summary.import_sources[0]
    assert source_summary.scheduled_run_missing is False
    assert source_summary.failed_job_count == 0
    assert source_summary.interrupted_job_count == 1
    assert source_summary.job_status_code == "interrupted"
    assert [item.attention_code for item in summary.attention_items] == [
        "import_jobs_interrupted"
    ]
    rendered_english = render_administrator_summary_email(summary, "en")
    rendered_spanish = render_administrator_summary_email(summary, "es")
    assert "Job Status: Interrupted" in rendered_english.text_body
    assert "stale-run recovery" in rendered_english.text_body
    assert "Estado del trabajo: Interrumpido" in rendered_spanish.text_body
    assert "no scheduled import" not in rendered_english.text_body
