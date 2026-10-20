from __future__ import annotations

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import models
from api.routes.admin.jobs import trigger_job_run


def test_manual_job_endpoint_persists_manual_execution_trigger(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'manual-job.sqlite'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            models.ExternalAPI(
                provider_code="airgradient",
                name="AirGradient",
                base_url="https://api.airgradient.com/public/api",
                api_key="configured-key",
                params={},
                enabled=True,
            )
        )
        schedule = models.JobSchedule(
            task="airgradient_import",
            cron_expr="0 * * * *",
            enabled=True,
        )
        session.add(schedule)
        session.commit()

        result = trigger_job_run(
            schedule.job_schedule_id,
            BackgroundTasks(),
            allow_paid_api=False,
            session=session,
        )

        job_run = session.get(models.JobRun, result.job_run_id)
        assert job_run is not None
        assert job_run.execution_trigger == models.JobExecutionTrigger.MANUAL.value
