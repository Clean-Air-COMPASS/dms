from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from jobs import scheduler


class StopScheduler(BaseException):
    pass


def test_summary_runs_first_and_its_failure_does_not_block_importer_poll(
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'scheduler.sqlite'}")
    models.Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        session.add_all(
            [
                models.SystemSettings(is_system_setup_complete=True),
                models.ExternalAPI(
                    provider_code="airgradient",
                    name="AirGradient",
                    params={},
                    enabled=False,
                ),
                models.JobSchedule(
                    task="airgradient_import",
                    cron_expr="0 * * * *",
                    enabled=True,
                ),
            ]
        )
        session.commit()

    observed_steps: list[str] = []

    def failing_summary(_session, *, now_utc):
        observed_steps.append("administrator_summary")
        raise RuntimeError("safe test failure")

    def observe_importer_poll(_session, _job):
        observed_steps.append("importer_schedule")
        return False

    monkeypatch.setattr(scheduler, "SessionLocal", SessionLocal)
    monkeypatch.setattr(
        scheduler,
        "process_due_administrator_summary",
        failing_summary,
    )
    monkeypatch.setattr(
        scheduler,
        "initial_source_import_is_due",
        observe_importer_poll,
    )
    monkeypatch.setattr(
        scheduler.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(StopScheduler()),
    )

    try:
        scheduler.main()
    except StopScheduler:
        pass

    assert observed_steps == ["administrator_summary", "importer_schedule"]


def test_incomplete_setup_skips_summary_recovery_and_importer_poll(
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'incomplete.sqlite'}")
    models.Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        session.add(models.SystemSettings(is_system_setup_complete=False))
        session.commit()

    observed_steps: list[str] = []
    monkeypatch.setattr(scheduler, "SessionLocal", SessionLocal)
    monkeypatch.setattr(
        scheduler,
        "_recover_orphaned_runs_on_startup",
        lambda: observed_steps.append("startup_recovery"),
    )
    monkeypatch.setattr(
        scheduler,
        "process_due_administrator_summary",
        lambda *_args, **_kwargs: observed_steps.append("administrator_summary"),
    )
    monkeypatch.setattr(
        scheduler,
        "initial_source_import_is_due",
        lambda *_args, **_kwargs: observed_steps.append("importer_schedule"),
    )
    monkeypatch.setattr(
        scheduler.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(StopScheduler()),
    )

    with pytest.raises(StopScheduler):
        scheduler.main()

    assert observed_steps == []
