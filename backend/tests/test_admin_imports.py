from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import pytest

import models
from api.routes.admin import imports


@pytest.mark.parametrize("provider_code", ["airgradient", "demo"])
def test_manual_import_uses_schedule_values_after_database_session_closes(
    tmp_path, monkeypatch, provider_code
):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'admin-imports.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add(
            models.ExternalAPI(
                provider_code=provider_code,
                name=provider_code,
                base_url="https://api.airgradient.com/public/api/v1",
                api_key="stored-key" if provider_code != "demo" else None,
                params={},
                enabled=True,
            )
        )
        schedule = models.JobSchedule(
            task=f"{provider_code}_import",
            cron_expr="0 * * * *",
            params={"lookback_hours": 24},
        )
        session.add(schedule)
        session.commit()
        schedule_id = schedule.job_schedule_id

    captured_call: dict = {}

    def fake_run_importer(job_run_id, params, task, **kwargs):
        captured_call.update(
            {
                "job_run_id": job_run_id,
                "params": params,
                "task": task,
                **kwargs,
            }
        )
        return 0, {"devices_processed": 0}, None

    monkeypatch.setattr(imports, "SessionLocal", Session)
    monkeypatch.setattr(imports, "run_importer", fake_run_importer)

    response = imports.run_import({"source": provider_code})

    assert response["returncode"] == 0
    assert captured_call["params"] == {"lookback_hours": 24}
    assert captured_call["task"] == f"{provider_code}_import"
    assert captured_call["job_schedule_id"] == schedule_id
    with Session() as session:
        job_run = session.scalar(
            select(models.JobRun).where(
                models.JobRun.job_run_id == response["job_run_id"]
            )
        )
        assert job_run is not None
        assert job_run.status == models.JobStatus.SUCCESS.value
        assert job_run.execution_trigger == models.JobExecutionTrigger.MANUAL.value
        assert job_run.summary == {"devices_processed": 0}
