from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from services.administrator_summary_domain import (
    AdministratorSummaryCadence,
    ReportingWindow,
    ReportingTimezoneError,
    calculate_completed_reporting_window,
    resolve_local_datetime,
    resolve_reporting_timezone,
)


UTC = timezone.utc
LOS_ANGELES = "America/Los_Angeles"


@pytest.mark.parametrize(
    ("reference_time_utc", "expected_local_date", "expected_duration"),
    [
        (datetime(2026, 1, 16, 16, tzinfo=UTC), "2026-01-15", timedelta(hours=24)),
        (datetime(2026, 3, 9, 16, tzinfo=UTC), "2026-03-08", timedelta(hours=23)),
        (datetime(2026, 11, 2, 16, tzinfo=UTC), "2026-11-01", timedelta(hours=25)),
    ],
)
def test_daily_window_uses_previous_completed_local_day_across_dst(
    reference_time_utc: datetime,
    expected_local_date: str,
    expected_duration: timedelta,
) -> None:
    window = calculate_completed_reporting_window(
        reference_time_utc,
        AdministratorSummaryCadence.DAILY,
        LOS_ANGELES,
    )

    assert window.period_start_local.date().isoformat() == expected_local_date
    assert window.period_start_local.hour == 0
    assert window.period_end_local.hour == 0
    assert window.period_end_utc - window.period_start_utc == expected_duration
    assert window.reporting_timezone == LOS_ANGELES


def test_hourly_window_distinguishes_both_repeated_fall_back_hours() -> None:
    first_window = calculate_completed_reporting_window(
        datetime(2026, 11, 1, 8, 30, tzinfo=UTC),
        AdministratorSummaryCadence.HOURLY,
        LOS_ANGELES,
    )
    second_window = calculate_completed_reporting_window(
        datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
        AdministratorSummaryCadence.HOURLY,
        LOS_ANGELES,
    )

    assert first_window.period_start_local.hour == 0
    assert first_window.period_end_local.hour == 1
    assert first_window.period_end_local.fold == 0
    assert second_window.period_start_local.hour == 1
    assert second_window.period_start_local.fold == 0
    assert second_window.period_end_local.hour == 1
    assert second_window.period_end_local.fold == 1
    assert first_window.period_end_utc == second_window.period_start_utc
    assert second_window.period_end_utc - second_window.period_start_utc == timedelta(hours=1)


def test_hourly_window_spans_the_nonexistent_spring_hour_as_elapsed_time() -> None:
    window = calculate_completed_reporting_window(
        datetime(2026, 3, 8, 10, 30, tzinfo=UTC),
        AdministratorSummaryCadence.HOURLY,
        LOS_ANGELES,
    )

    assert window.period_start_local.hour == 1
    assert window.period_start_local.tzname() == "PST"
    assert window.period_end_local.hour == 3
    assert window.period_end_local.tzname() == "PDT"
    assert window.period_end_utc - window.period_start_utc == timedelta(hours=1)


def test_every_15_minutes_uses_latest_completed_local_quarter_hour() -> None:
    window = calculate_completed_reporting_window(
        datetime(2026, 8, 21, 17, 37, 42, tzinfo=UTC),
        AdministratorSummaryCadence.EVERY_15_MINUTES,
        LOS_ANGELES,
    )

    assert window.period_start_local.isoformat() == "2026-08-21T10:15:00-07:00"
    assert window.period_end_local.isoformat() == "2026-08-21T10:30:00-07:00"
    assert window.period_end_utc - window.period_start_utc == timedelta(minutes=15)


def test_every_15_minutes_preserves_fold_during_repeated_hour() -> None:
    window = calculate_completed_reporting_window(
        datetime(2026, 11, 1, 9, 37, tzinfo=UTC),
        AdministratorSummaryCadence.EVERY_15_MINUTES,
        LOS_ANGELES,
    )

    assert window.period_start_local.hour == 1
    assert window.period_start_local.minute == 15
    assert window.period_start_local.fold == 1
    assert window.period_end_local.hour == 1
    assert window.period_end_local.minute == 30
    assert window.period_end_local.fold == 1


def test_nonexistent_local_time_advances_to_first_valid_minute() -> None:
    resolved = resolve_local_datetime(
        datetime(2026, 3, 8, 2, 30),
        LOS_ANGELES,
    )

    assert resolved.isoformat() == "2026-03-08T03:00:00-07:00"


def test_ambiguous_local_time_uses_requested_fold() -> None:
    first = resolve_local_datetime(
        datetime(2026, 11, 1, 1, 30),
        LOS_ANGELES,
        preferred_fold=0,
    )
    second = resolve_local_datetime(
        datetime(2026, 11, 1, 1, 30),
        LOS_ANGELES,
        preferred_fold=1,
    )

    assert first.tzname() == "PDT"
    assert second.tzname() == "PST"
    assert second.astimezone(UTC) - first.astimezone(UTC) == timedelta(hours=1)


@pytest.mark.parametrize("timezone_name", ["", "Not/A_Timezone", "UTC+7"])
def test_invalid_reporting_timezone_is_explicit(timezone_name: str) -> None:
    with pytest.raises(ReportingTimezoneError):
        resolve_reporting_timezone(timezone_name)


def test_reporting_window_is_immutable() -> None:
    window = calculate_completed_reporting_window(
        datetime(2026, 8, 22, 14, tzinfo=UTC),
        AdministratorSummaryCadence.DAILY,
        LOS_ANGELES,
    )

    with pytest.raises(FrozenInstanceError):
        window.reporting_timezone = "UTC"  # type: ignore[misc]


def test_reporting_window_normalizes_utc_fields_and_validates_dst_fold() -> None:
    timezone_name = "America/Los_Angeles"
    correct_local_start = resolve_local_datetime(
        datetime(2026, 11, 1, 1),
        timezone_name,
        preferred_fold=1,
    )
    end_local = resolve_local_datetime(datetime(2026, 11, 1, 2), timezone_name)
    start_utc = correct_local_start.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)

    window = ReportingWindow(
        cadence=AdministratorSummaryCadence.HOURLY,
        reporting_timezone=timezone_name,
        period_start_utc=start_utc.astimezone(ZoneInfo("America/New_York")),
        period_end_utc=end_utc.astimezone(ZoneInfo("America/New_York")),
        period_start_local=correct_local_start,
        period_end_local=end_local,
    )

    assert window.period_start_utc.tzinfo is UTC
    assert window.period_end_utc.tzinfo is UTC
    assert window.period_start_local.fold == 1

    wrong_fold_start = resolve_local_datetime(
        datetime(2026, 11, 1, 1),
        timezone_name,
        preferred_fold=0,
    )
    with pytest.raises(ValueError, match="period_start_local"):
        ReportingWindow(
            cadence=AdministratorSummaryCadence.HOURLY,
            reporting_timezone=timezone_name,
            period_start_utc=start_utc,
            period_end_utc=end_utc,
            period_start_local=wrong_fold_start,
            period_end_local=end_local,
        )
