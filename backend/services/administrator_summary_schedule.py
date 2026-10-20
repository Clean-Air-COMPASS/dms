"""Administrator-summary schedule validation and due-window calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum

from models import EmailSettings
from services.administrator_summary_domain import (
    AdministratorSummaryCadence,
    ReportingTimezoneError,
    ReportingWindow,
    calculate_completed_reporting_window,
    resolve_local_datetime,
    resolve_reporting_timezone,
)


UTC = timezone.utc
DEFAULT_ADMINISTRATOR_SUMMARY_DAILY_SEND_TIME = time(7, 0)
DEFAULT_ADMINISTRATOR_SUMMARY_REPORTING_TIMEZONE = "UTC"


class AdministratorSummaryTimezoneSource(str, Enum):
    SYSTEM_PREFERENCES = "system_preferences"
    SUMMARY_OVERRIDE = "summary_override"


class AdministratorSummaryScheduleValidationError(ValueError):
    """Stable schedule-validation failure for persistence and scheduler use."""

    def __init__(self, error_code: str, field: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.field = field


@dataclass(frozen=True)
class AdministratorSummaryScheduleUpdate:
    enabled: bool
    cadence: AdministratorSummaryCadence | str
    daily_send_time: time
    reporting_timezone_override: str | None = None
    # Kept as a compatibility input for callers from the previous API shape.
    # New callers must use reporting_timezone_override so inheritance is explicit.
    reporting_timezone: str | None = None


@dataclass(frozen=True)
class AdministratorSummarySchedule:
    enabled: bool
    cadence: AdministratorSummaryCadence
    daily_send_time: time
    reporting_timezone: str
    effective_at_utc: datetime | None
    reporting_timezone_source: AdministratorSummaryTimezoneSource = (
        AdministratorSummaryTimezoneSource.SUMMARY_OVERRIDE
    )
    reporting_timezone_override: str | None = None


@dataclass(frozen=True)
class DueAdministratorSummaryWindow:
    reporting_window: ReportingWindow
    due_at_utc: datetime


def next_administrator_summary_window(
    schedule: AdministratorSummarySchedule,
    *,
    now_utc: datetime,
) -> DueAdministratorSummaryWindow | None:
    """Return the next window expected to be eligible for scheduled delivery."""
    now = _normalize_aware_utc(now_utc, field="now_utc")
    if not schedule.enabled or schedule.effective_at_utc is None:
        return None

    if schedule.cadence is AdministratorSummaryCadence.DAILY:
        local_timezone = resolve_reporting_timezone(schedule.reporting_timezone)
        local_now = now.astimezone(local_timezone)
        due_local_date = local_now.date()
        local_due_value = datetime.combine(
            due_local_date,
            schedule.daily_send_time,
        )
        due_at = resolve_local_datetime(
            local_due_value,
            schedule.reporting_timezone,
        ).astimezone(UTC)
        if due_at < now:
            due_local_date += timedelta(days=1)
            due_at = resolve_local_datetime(
                datetime.combine(due_local_date, schedule.daily_send_time),
                schedule.reporting_timezone,
            ).astimezone(UTC)
        reporting_window = calculate_completed_reporting_window(
            due_at,
            schedule.cadence,
            schedule.reporting_timezone,
        )
    else:
        completed_window = calculate_completed_reporting_window(
            now,
            schedule.cadence,
            schedule.reporting_timezone,
        )
        if completed_window.period_end_utc >= now:
            reporting_window = completed_window
        else:
            cadence_interval = (
                timedelta(hours=1)
                if schedule.cadence is AdministratorSummaryCadence.HOURLY
                else timedelta(minutes=15)
            )
            reporting_window = calculate_completed_reporting_window(
                completed_window.period_end_utc + cadence_interval,
                schedule.cadence,
                schedule.reporting_timezone,
            )
        due_at = reporting_window.period_end_utc

    return DueAdministratorSummaryWindow(
        reporting_window=reporting_window,
        due_at_utc=due_at,
    )


def _normalize_aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AdministratorSummaryScheduleValidationError(
            "invalid_schedule_timestamp",
            field,
            f"{field} must include a timezone",
        )
    return value.astimezone(UTC)


def _normalize_daily_send_time(value: time) -> time:
    if not isinstance(value, time) or value.tzinfo is not None:
        raise AdministratorSummaryScheduleValidationError(
            "invalid_administrator_summary_daily_send_time",
            "administrator_summary_daily_send_time",
            "Daily send time must be a local wall-clock time without a timezone",
        )
    return value.replace(microsecond=0)


def _normalize_cadence(
    value: AdministratorSummaryCadence | str,
) -> AdministratorSummaryCadence:
    try:
        return AdministratorSummaryCadence(value)
    except (TypeError, ValueError) as exc:
        raise AdministratorSummaryScheduleValidationError(
            "invalid_administrator_summary_cadence",
            "administrator_summary_cadence",
            "Administrator summary cadence must be daily, hourly, or every_15_minutes",
        ) from exc


def _normalize_reporting_timezone(value: str) -> str:
    try:
        return resolve_reporting_timezone(value).key
    except ReportingTimezoneError as exc:
        raise AdministratorSummaryScheduleValidationError(
            "invalid_administrator_summary_reporting_timezone",
            "administrator_summary_reporting_timezone_override",
            str(exc),
        ) from exc


def _normalize_system_timezone(value: str) -> str:
    try:
        return resolve_reporting_timezone(value).key
    except ReportingTimezoneError as exc:
        raise AdministratorSummaryScheduleValidationError(
            "invalid_system_timezone",
            "system_timezone",
            str(exc),
        ) from exc


def administrator_summary_schedule_from_settings(
    settings: EmailSettings,
    *,
    system_timezone: str = DEFAULT_ADMINISTRATOR_SUMMARY_REPORTING_TIMEZONE,
) -> AdministratorSummarySchedule:
    effective_at = settings.administrator_summary_effective_at
    # SQLite drops timezone metadata in local unit tests. The persisted field is
    # defined as a UTC instant, so only this database-read boundary restores UTC.
    if effective_at is not None and (
        effective_at.tzinfo is None or effective_at.utcoffset() is None
    ):
        normalized_effective_at = effective_at.replace(tzinfo=UTC)
    elif effective_at is not None:
        normalized_effective_at = effective_at.astimezone(UTC)
    else:
        normalized_effective_at = None
    stored_override = settings.administrator_summary_reporting_timezone_override
    if stored_override is None:
        effective_reporting_timezone = _normalize_system_timezone(system_timezone)
        timezone_source = AdministratorSummaryTimezoneSource.SYSTEM_PREFERENCES
        normalized_override = None
    else:
        normalized_override = _normalize_reporting_timezone(stored_override)
        effective_reporting_timezone = normalized_override
        timezone_source = AdministratorSummaryTimezoneSource.SUMMARY_OVERRIDE

    return AdministratorSummarySchedule(
        enabled=bool(settings.administrator_summary_enabled),
        cadence=_normalize_cadence(settings.administrator_summary_cadence),
        daily_send_time=_normalize_daily_send_time(
            settings.administrator_summary_daily_send_time
        ),
        reporting_timezone=effective_reporting_timezone,
        effective_at_utc=normalized_effective_at,
        reporting_timezone_source=timezone_source,
        reporting_timezone_override=normalized_override,
    )


def apply_administrator_summary_schedule_update(
    settings: EmailSettings,
    update: AdministratorSummaryScheduleUpdate,
    *,
    changed_at_utc: datetime,
    system_timezone: str = DEFAULT_ADMINISTRATOR_SUMMARY_REPORTING_TIMEZONE,
) -> tuple[str, ...]:
    """Validate and persist a schedule, resetting its effective boundary."""
    if not isinstance(update.enabled, bool):
        raise AdministratorSummaryScheduleValidationError(
            "invalid_administrator_summary_enabled",
            "administrator_summary_enabled",
            "Administrator summary enabled state must be true or false",
        )
    cadence = _normalize_cadence(update.cadence)
    daily_send_time = _normalize_daily_send_time(update.daily_send_time)
    requested_override = update.reporting_timezone_override
    if requested_override is None and update.reporting_timezone is not None:
        requested_override = update.reporting_timezone
    reporting_timezone_override = (
        _normalize_reporting_timezone(requested_override)
        if requested_override is not None
        else None
    )
    if reporting_timezone_override is None:
        _normalize_system_timezone(system_timezone)
    changed_at = _normalize_aware_utc(changed_at_utc, field="changed_at_utc")

    candidate_values: dict[str, object] = {
        "administrator_summary_enabled": update.enabled,
        "administrator_summary_cadence": cadence.value,
        "administrator_summary_daily_send_time": daily_send_time,
        "administrator_summary_reporting_timezone_override": reporting_timezone_override,
    }
    changed_fields = tuple(
        field
        for field, value in candidate_values.items()
        if getattr(settings, field) != value
    )
    for field in changed_fields:
        setattr(settings, field, candidate_values[field])
    if changed_fields:
        settings.administrator_summary_effective_at = changed_at
    return changed_fields


def latest_due_administrator_summary_window(
    schedule: AdministratorSummarySchedule,
    *,
    now_utc: datetime,
) -> DueAdministratorSummaryWindow | None:
    """Return only the latest completed, due, post-effective reporting window."""
    now = _normalize_aware_utc(now_utc, field="now_utc")
    if not schedule.enabled or schedule.effective_at_utc is None:
        return None

    reporting_window = calculate_completed_reporting_window(
        now,
        schedule.cadence,
        schedule.reporting_timezone,
    )
    if schedule.cadence is AdministratorSummaryCadence.DAILY:
        local_due_value = datetime.combine(
            reporting_window.period_end_local.date(),
            schedule.daily_send_time,
        )
        due_at = resolve_local_datetime(
            local_due_value,
            schedule.reporting_timezone,
        ).astimezone(UTC)
    else:
        due_at = reporting_window.period_end_utc

    if now < due_at or due_at < schedule.effective_at_utc:
        return None
    return DueAdministratorSummaryWindow(
        reporting_window=reporting_window,
        due_at_utc=due_at,
    )
