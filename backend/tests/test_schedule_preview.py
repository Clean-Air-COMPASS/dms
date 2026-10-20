from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from api.routes.admin.jobs import JobScheduleUpdateIn, preview_schedule, update_schedule


@pytest.mark.parametrize('expression', ['0 * * * *', '*/15 * * * *', '0 0 L * *', '0 0 * * MON-FRI'])
def test_preview_uses_scheduler_parser_and_returns_utc_times(expression):
    preview = preview_schedule(expression)
    assert preview['valid'] is True
    assert len(preview['next_runs']) == 3
    assert preview['next_runs'] == sorted(preview['next_runs'])
    assert all(time.utcoffset().total_seconds() == 0 for time in preview['next_runs'])


@pytest.mark.parametrize('expression', ['', 'not cron', '70 * * * *'])
def test_invalid_or_impossible_cron_cannot_overwrite_saved_schedule(expression):
    session = Mock()
    job = SimpleNamespace(cron_expr='0 * * * *')
    session.get.return_value = job
    assert preview_schedule(expression) == {'valid': False, 'next_runs': []}
    with pytest.raises(HTTPException) as error:
        update_schedule(1, JobScheduleUpdateIn(cron_expr=expression), session)
    assert error.value.status_code == 422
    assert error.value.detail['error_code'] == 'invalid_cron'
    assert job.cron_expr == '0 * * * *'
    session.commit.assert_not_called()


def test_valid_expression_without_future_matches_is_explicit():
    assert preview_schedule("0 0 31 2 *") == {"valid": True, "next_runs": []}
