from __future__ import annotations

from datetime import datetime, time, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, EmailSettings
from services.administrator_summary_domain import AdministratorSummaryCadence
from services.administrator_summary_schedule import (
    AdministratorSummarySchedule,
    AdministratorSummaryScheduleUpdate,
    AdministratorSummaryScheduleValidationError,
    AdministratorSummaryTimezoneSource,
    administrator_summary_schedule_from_settings,
    apply_administrator_summary_schedule_update,
    latest_due_administrator_summary_window,
    next_administrator_summary_window,
)
from services.email_configuration import get_or_create_email_settings


UTC = timezone.utc


def _schedule(
    cadence: AdministratorSummaryCadence,
    *,
    effective_at: datetime,
    daily_send_time: time = time(7, 0),
    reporting_timezone: str = "UTC",
) -> AdministratorSummarySchedule:
    return AdministratorSummarySchedule(
        enabled=True,
        cadence=cadence,
        daily_send_time=daily_send_time,
        reporting_timezone=reporting_timezone,
        effective_at_utc=effective_at,
    )


def test_schedule_defaults_are_disabled_daily_at_seven_utc() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        settings = get_or_create_email_settings(session)
        session.flush()

        assert settings.administrator_summary_enabled is False
        assert settings.administrator_summary_cadence == "daily"
        assert settings.administrator_summary_daily_send_time == time(7, 0)
        assert settings.administrator_summary_reporting_timezone_override is None
        assert settings.administrator_summary_effective_at is None


def test_schedule_update_validates_cadence_timezone_and_sets_effective_at() -> None:
    settings = EmailSettings(
        email_settings_id=1,
        administrator_summary_enabled=False,
        administrator_summary_cadence="daily",
        administrator_summary_daily_send_time=time(7, 0),
        administrator_summary_reporting_timezone_override="UTC",
        last_test_status="success",
        last_tested_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    changed_at = datetime(2026, 8, 21, 17, 17, tzinfo=UTC)
    changed_fields = apply_administrator_summary_schedule_update(
        settings,
        AdministratorSummaryScheduleUpdate(
            enabled=True,
            cadence="every_15_minutes",
            daily_send_time=time(8, 30),
            reporting_timezone_override="America/Los_Angeles",
        ),
        changed_at_utc=changed_at,
    )

    assert set(changed_fields) == {
        "administrator_summary_enabled",
        "administrator_summary_cadence",
        "administrator_summary_daily_send_time",
        "administrator_summary_reporting_timezone_override",
    }
    assert settings.administrator_summary_effective_at == changed_at
    assert settings.last_test_status == "success"
    assert settings.last_test_error_code is None
    assert settings.last_tested_at == datetime(2026, 8, 20, tzinfo=UTC)

    with pytest.raises(
        AdministratorSummaryScheduleValidationError,
        match="cadence",
    ):
        apply_administrator_summary_schedule_update(
            settings,
            AdministratorSummaryScheduleUpdate(
                enabled=True,
                cadence="weekly",
                daily_send_time=time(7),
                reporting_timezone_override="UTC",
            ),
            changed_at_utc=changed_at,
        )
    with pytest.raises(
        AdministratorSummaryScheduleValidationError,
        match="timezone",
    ):
        apply_administrator_summary_schedule_update(
            settings,
            AdministratorSummaryScheduleUpdate(
                enabled=True,
                cadence="daily",
                daily_send_time=time(7),
                reporting_timezone_override="Not/A_Zone",
            ),
            changed_at_utc=changed_at,
        )


def test_summary_without_override_inherits_system_timezone() -> None:
    settings = EmailSettings(
        email_settings_id=1,
        administrator_summary_enabled=True,
        administrator_summary_cadence="daily",
        administrator_summary_daily_send_time=time(7, 0),
        administrator_summary_reporting_timezone_override=None,
    )

    schedule = administrator_summary_schedule_from_settings(
        settings,
        system_timezone="Asia/Manila",
    )

    assert schedule.reporting_timezone == "Asia/Manila"
    assert schedule.reporting_timezone_source is AdministratorSummaryTimezoneSource.SYSTEM_PREFERENCES
    assert schedule.reporting_timezone_override is None


def test_inherited_summary_uses_changed_system_timezone_but_override_does_not() -> None:
    inherited_settings = EmailSettings(
        email_settings_id=1,
        administrator_summary_enabled=True,
        administrator_summary_cadence="daily",
        administrator_summary_daily_send_time=time(7, 0),
        administrator_summary_reporting_timezone_override=None,
    )
    overridden_settings = EmailSettings(
        email_settings_id=2,
        administrator_summary_enabled=True,
        administrator_summary_cadence="daily",
        administrator_summary_daily_send_time=time(7, 0),
        administrator_summary_reporting_timezone_override="America/Los_Angeles",
    )

    inherited_before = administrator_summary_schedule_from_settings(
        inherited_settings,
        system_timezone="UTC",
    )
    inherited_after = administrator_summary_schedule_from_settings(
        inherited_settings,
        system_timezone="Asia/Manila",
    )
    overridden_after = administrator_summary_schedule_from_settings(
        overridden_settings,
        system_timezone="Asia/Manila",
    )

    assert inherited_before.reporting_timezone == "UTC"
    assert inherited_after.reporting_timezone == "Asia/Manila"
    assert overridden_after.reporting_timezone == "America/Los_Angeles"
    assert overridden_after.reporting_timezone_source is AdministratorSummaryTimezoneSource.SUMMARY_OVERRIDE


@pytest.mark.parametrize("timezone_name", ["Asia/Manila", "America/Los_Angeles", "Pacific/Apia"])
def test_valid_iana_timezones_remain_selectable_for_summary(timezone_name: str) -> None:
    settings = EmailSettings(
        email_settings_id=1,
        administrator_summary_enabled=False,
        administrator_summary_cadence="daily",
        administrator_summary_daily_send_time=time(7, 0),
        administrator_summary_reporting_timezone_override=None,
    )

    apply_administrator_summary_schedule_update(
        settings,
        AdministratorSummaryScheduleUpdate(
            enabled=False,
            cadence="daily",
            daily_send_time=time(7, 0),
            reporting_timezone_override=timezone_name,
        ),
        changed_at_utc=datetime(2026, 8, 21, 17, 17, tzinfo=UTC),
    )

    assert settings.administrator_summary_reporting_timezone_override == timezone_name


def test_invalid_system_timezone_is_rejected_for_inheritance() -> None:
    settings = EmailSettings(
        email_settings_id=1,
        administrator_summary_enabled=False,
        administrator_summary_cadence="daily",
        administrator_summary_daily_send_time=time(7, 0),
        administrator_summary_reporting_timezone_override=None,
    )

    with pytest.raises(
        AdministratorSummaryScheduleValidationError,
        match="not a valid IANA timezone",
    ):
        administrator_summary_schedule_from_settings(settings, system_timezone="Not/A_Zone")


def test_daily_window_waits_for_configured_local_send_time() -> None:
    schedule = _schedule(
        AdministratorSummaryCadence.DAILY,
        effective_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
        reporting_timezone="America/Los_Angeles",
    )

    assert latest_due_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 8, 22, 13, 59, tzinfo=UTC),
    ) is None
    due = latest_due_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 8, 22, 14, 0, tzinfo=UTC),
    )

    assert due is not None
    assert due.due_at_utc == datetime(2026, 8, 22, 14, tzinfo=UTC)
    assert due.reporting_window.period_start_local.date().isoformat() == "2026-08-21"


def test_next_daily_window_reports_the_next_local_send_and_completed_day() -> None:
    schedule = _schedule(
        AdministratorSummaryCadence.DAILY,
        effective_at=datetime(2026, 8, 21, 16, tzinfo=UTC),
        reporting_timezone="America/Los_Angeles",
    )

    next_window = next_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 8, 21, 16, 30, tzinfo=UTC),
    )

    assert next_window is not None
    assert next_window.due_at_utc == datetime(2026, 8, 22, 14, tzinfo=UTC)
    assert next_window.reporting_window.period_start_local.date().isoformat() == "2026-08-21"
    assert next_window.reporting_window.period_end_local.date().isoformat() == "2026-08-22"


def test_next_short_cadence_window_uses_the_next_boundary() -> None:
    schedule = _schedule(
        AdministratorSummaryCadence.EVERY_15_MINUTES,
        effective_at=datetime(2026, 8, 21, 10, 17, tzinfo=UTC),
    )

    next_window = next_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 8, 21, 10, 22, tzinfo=UTC),
    )

    assert next_window is not None
    assert next_window.due_at_utc == datetime(2026, 8, 21, 10, 30, tzinfo=UTC)
    assert next_window.reporting_window.period_start_utc == datetime(
        2026, 8, 21, 10, 15, tzinfo=UTC
    )


def test_hourly_effective_at_waits_for_the_next_completed_hour() -> None:
    schedule = _schedule(
        AdministratorSummaryCadence.HOURLY,
        effective_at=datetime(2026, 8, 21, 10, 17, tzinfo=UTC),
    )

    assert latest_due_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 8, 21, 10, 59, tzinfo=UTC),
    ) is None
    due = latest_due_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 8, 21, 11, 0, tzinfo=UTC),
    )

    assert due is not None
    assert due.reporting_window.period_start_utc == datetime(
        2026, 8, 21, 10, tzinfo=UTC
    )
    assert due.reporting_window.period_end_utc == datetime(
        2026, 8, 21, 11, tzinfo=UTC
    )


def test_fifteen_minute_effective_at_waits_for_window_ending_at_ten_thirty() -> None:
    schedule = _schedule(
        AdministratorSummaryCadence.EVERY_15_MINUTES,
        effective_at=datetime(2026, 8, 21, 10, 17, tzinfo=UTC),
    )

    assert latest_due_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 8, 21, 10, 29, 59, tzinfo=UTC),
    ) is None
    due = latest_due_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 8, 21, 10, 30, tzinfo=UTC),
    )

    assert due is not None
    assert due.reporting_window.period_start_utc == datetime(
        2026, 8, 21, 10, 15, tzinfo=UTC
    )
    assert due.reporting_window.period_end_utc == datetime(
        2026, 8, 21, 10, 30, tzinfo=UTC
    )


def test_only_latest_missed_short_cadence_window_is_returned() -> None:
    schedule = _schedule(
        AdministratorSummaryCadence.EVERY_15_MINUTES,
        effective_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
    )
    due = latest_due_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 8, 21, 12, 47, tzinfo=UTC),
    )

    assert due is not None
    assert due.reporting_window.period_start_utc == datetime(
        2026, 8, 21, 12, 30, tzinfo=UTC
    )
    assert due.reporting_window.period_end_utc == datetime(
        2026, 8, 21, 12, 45, tzinfo=UTC
    )


def test_nonexistent_daily_send_time_advances_to_first_valid_local_minute() -> None:
    schedule = _schedule(
        AdministratorSummaryCadence.DAILY,
        effective_at=datetime(2026, 3, 7, 8, tzinfo=UTC),
        daily_send_time=time(2, 30),
        reporting_timezone="America/Los_Angeles",
    )

    assert latest_due_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 3, 8, 9, 59, tzinfo=UTC),
    ) is None
    due = latest_due_administrator_summary_window(
        schedule,
        now_utc=datetime(2026, 3, 8, 10, 0, tzinfo=UTC),
    )

    assert due is not None
    assert due.due_at_utc == datetime(2026, 3, 8, 10, 0, tzinfo=UTC)
