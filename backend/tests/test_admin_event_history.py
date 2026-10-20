from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.admin import events, jobs
from db import SessionLocal
from models import Event, JobRun, JobSchedule


@pytest.fixture
def history_client():
    app = FastAPI()
    app.include_router(events.router)
    app.include_router(jobs.router)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("kind", ["events", "jobs"])
def test_history_reaches_older_rows_and_keeps_full_filter_options(history_client, kind):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with SessionLocal() as session:
        schedule = JobSchedule(task="history_test_import", cron_expr="0 * * * *")
        session.add(schedule)
        session.flush()
        rows = []
        for index in range(126):
            # Equal timestamps exercise deterministic ID ordering across pages.
            time = start + timedelta(minutes=index // 2)
            rows.append(
                Event(event_type="history_older" if index == 0 else "history_recent",
                      source="history_test", severity="error" if index == 0 else "info", created_at=time)
                if kind == "events" else
                JobRun(job_schedule_id=schedule.job_schedule_id, started_at=time,
                       status="failed" if index == 0 else "success")
            )
        session.add_all(rows)
        session.commit()
        row_ids = [row.event_id if kind == "events" else row.job_run_id for row in rows]
        schedule_id = schedule.job_schedule_id
    path = "/admin/events" if kind == "events" else "/admin/jobs/runs"
    filters = {"source": "history_test"} if kind == "events" else {"task": "history_test_import"}
    params = {**filters, "paginated": True, "limit": 25,
              "started_after": start.isoformat(), "started_before": (start + timedelta(days=1)).isoformat()}
    try:
        seen = []
        for offset in range(0, 126, 25):
            response = history_client.get(path, params={**params, "offset": offset})
            assert response.status_code == 200, response.text
            page = response.json()
            assert page["total"] == 126
            assert ("history_older" in page["options"]["event_type"] if kind == "events"
                    else "failed" in page["options"]["status"])
            seen.extend(row["event_id" if kind == "events" else "job_run_id"] for row in page["items"])
        assert seen == list(reversed(row_ids))
        assert len(set(seen)) == 126
        # Inclusive lower and exclusive upper boundary, independent of pagination.
        boundary = history_client.get(path, params={**params, "started_before": (start + timedelta(minutes=1)).isoformat()}).json()
        assert boundary["total"] == 2
        assert len(history_client.get(path, params={**filters, "limit": 10}).json()) == 10
        empty = history_client.get(path, params={**params, "started_after": (start + timedelta(hours=2)).isoformat()}).json()
        assert empty["items"] == []
        assert empty["options"] == page["options"]
    finally:
        with SessionLocal() as session:
            model = Event if kind == "events" else JobRun
            key = model.event_id if kind == "events" else model.job_run_id
            session.query(model).filter(key.in_(row_ids)).delete(synchronize_session=False)
            session.query(JobSchedule).filter(JobSchedule.job_schedule_id == schedule_id).delete()
            session.commit()


@pytest.mark.parametrize("path", ["/admin/events", "/admin/jobs/runs"])
@pytest.mark.parametrize("params", [
    {"offset": -1},
    {"started_after": "2020-01-01T00:00:00"},
    {"started_after": "2020-01-02T00:00:00Z", "started_before": "2020-01-01T00:00:00Z"},
])
def test_history_rejects_invalid_bounds(history_client, path, params):
    assert history_client.get(path, params=params).status_code == 422
