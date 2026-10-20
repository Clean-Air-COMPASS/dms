from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
import pytest

import models
from jobs import import_runner
from jobs.source_activation import (
    create_job_run_if_source_runnable,
    initial_source_import_is_due,
)
from services.external_sources import ExternalSourceNotRunnable


def test_non_runnable_schedules_create_no_work_or_diagnostics(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'scheduler.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(import_runner, "SessionLocal", Session)
    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "false")

    with Session() as session:
        sources = [
            models.ExternalAPI(
                provider_code=provider_code,
                name=provider_code,
                params={"import_authenticated_locations": True} if provider_code == "airgradient" else {},
                enabled=True,
                api_key=None,
            )
            for provider_code in ("openaq", "purpleair", "airgradient")
        ]
        schedules = [
            models.JobSchedule(task=f"{provider_code}_import", cron_expr="* * * * *")
            for provider_code in ("openaq", "purpleair", "airgradient")
        ]
        session.add_all([*sources, *schedules])
        session.commit()

        monkeypatch.setattr(
            import_runner.subprocess,
            "run",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("subprocess must not start")
            ),
        )
        for schedule in schedules:
            assert create_job_run_if_source_runnable(session, schedule) is None
            with pytest.raises(ExternalSourceNotRunnable):
                import_runner.run_importer(
                    1,
                    schedule.params,
                    schedule.task,
                    job_schedule_id=schedule.job_schedule_id,
                )

        assert session.scalar(select(func.count()).select_from(models.JobRun)) == 0
        assert session.scalar(select(func.count()).select_from(models.Event)) == 0


@pytest.mark.parametrize("provider_code", ["openaq", "purpleair", "airgradient", "demo"])
def test_newly_runnable_never_run_source_is_due_exactly_once(
    provider_code, tmp_path, monkeypatch
):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / f'{provider_code}.sqlite'}"
    )
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "false")

    with Session() as session:
        source = models.ExternalAPI(
            provider_code=provider_code,
            name=provider_code,
            params={},
            enabled=False,
            api_key=None,
        )
        schedule = models.JobSchedule(
            task=f"{provider_code}_import",
            cron_expr="0 * * * *",
            enabled=True,
        )
        session.add_all([source, schedule])
        session.commit()

        assert initial_source_import_is_due(session, schedule) is False

        source.enabled = True
        session.commit()
        assert initial_source_import_is_due(session, schedule) is (provider_code in {"demo", "airgradient"})

        source.api_key = "configured-key"
        session.commit()
        assert initial_source_import_is_due(session, schedule) is True

        first_run = create_job_run_if_source_runnable(
            session, schedule, initial_run_only=True
        )
        assert first_run is not None
        assert first_run.execution_trigger == models.JobExecutionTrigger.SCHEDULED.value
        with Session() as observer_session:
            visible_run = observer_session.get(models.JobRun, first_run.job_run_id)
            assert visible_run is not None
            assert visible_run.status == "running"
        assert initial_source_import_is_due(session, schedule) is False

        duplicate_initial_run = create_job_run_if_source_runnable(
            session, schedule, initial_run_only=True
        )
        assert duplicate_initial_run is None

        later_cron_run = create_job_run_if_source_runnable(session, schedule)
        assert later_cron_run is not None
        session.commit()
        assert session.scalar(select(func.count()).select_from(models.JobRun)) == 2
