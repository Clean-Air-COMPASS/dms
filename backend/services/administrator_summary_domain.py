"""Domain records and reporting-window rules for administrator summaries.

Reporting windows are defined in one configured IANA timezone, but their
canonical database boundaries are UTC instants. Device timezones are not used.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Final
from zoneinfo import ZoneInfo

from services.timezone import IanaTimezoneError, resolve_iana_timezone


UTC = timezone.utc
ONE_DAY = timedelta(days=1)
ONE_HOUR = timedelta(hours=1)
FIFTEEN_MINUTES = timedelta(minutes=15)


class AdministratorSummaryCadence(str, Enum):
    DAILY = "daily"
    HOURLY = "hourly"
    EVERY_15_MINUTES = "every_15_minutes"


class AdministratorSummaryStatus(str, Enum):
    ALL_SYSTEMS_NORMAL = "all_systems_normal"
    NEEDS_ATTENTION = "needs_attention"


class QcDigestOutcome(str, Enum):
    FLAGGED_FOR_REVIEW = "flagged_for_review"
    MARKED_INVALID = "marked_invalid"
    INDETERMINATE = "indeterminate"


NOT_SCHEDULED_THIS_PERIOD_STATUS: Final = "not_scheduled_this_period"
NO_SCHEDULED_RUN_STATUS: Final = "no_scheduled_run"


def administrator_summary_environment_label(
    environment: Mapping[str, str],
) -> str | None:
    """Return a concise, human-readable label from COMPASSAQ_ENV."""
    label = environment.get("COMPASSAQ_ENV", "").strip()
    if not label:
        return None
    display_labels = {
        "development": "Development",
        "production": "Production",
        "test": "Test",
    }
    return display_labels.get(label.lower(), label[:64])


# Administrator summaries use a stable, concise name for the three currently
# registered checks. Plugin metadata may use a different technical display
# name elsewhere in the application; these names belong to the summary only.
QC_CHECK_DISPLAY_NAMES: Final[dict[str, dict[str, str]]] = {
    "min_value": {
        "en": "Min Value QC Check",
        "es": "Verificación de CC de valor mínimo",
    },
    "max_value": {
        "en": "Max Value QC Check",
        "es": "Verificación de CC de valor máximo",
    },
    "baseline_drift": {
        "en": "Baseline Drift QC Check",
        "es": "Verificación de CC de deriva de línea base",
    },
}

def qc_check_display_name(
    check_code: str | None,
    language: str,
    *,
    fallback: str | None = None,
) -> str:
    """Return the summary's localized name for a QC check.

    Installed plugin metadata is authoritative when supplied as ``fallback``.
    Local names remain only for older stored rows or callers without metadata.
    """
    normalized_fallback = " ".join((fallback or "").split())
    if normalized_fallback:
        return normalized_fallback

    normalized_code = (check_code or "").strip().lower()
    localized_name = QC_CHECK_DISPLAY_NAMES.get(normalized_code, {}).get(language)
    if localized_name:
        return localized_name

    if normalized_code:
        humanized_code = normalized_code.replace("_", " ")
        return humanized_code[:1].upper() + humanized_code[1:]
    return "Unknown check"


class EventDigestSection(str, Enum):
    IMPORTS = "imports"
    SYSTEM = "system"


ReportingTimezoneError = IanaTimezoneError


def resolve_reporting_timezone(reporting_timezone: str) -> ZoneInfo:
    """Validate and return the configured IANA reporting timezone."""
    return resolve_iana_timezone(reporting_timezone, field_label="Reporting timezone")


def _require_aware_datetime(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value


def _valid_local_candidates(local_value: datetime, local_timezone: ZoneInfo) -> list[datetime]:
    candidates: list[datetime] = []
    candidate_instants: set[datetime] = set()
    for fold in (0, 1):
        candidate = local_value.replace(tzinfo=local_timezone, fold=fold)
        candidate_utc = candidate.astimezone(UTC)
        round_trip = candidate_utc.astimezone(local_timezone)
        if round_trip.replace(tzinfo=None) != local_value:
            continue
        if candidate_utc in candidate_instants:
            continue
        candidate_instants.add(candidate_utc)
        candidates.append(candidate)
    return sorted(candidates, key=lambda candidate: candidate.astimezone(UTC))


def resolve_local_datetime(
    local_value: datetime,
    reporting_timezone: str,
    *,
    preferred_fold: int = 0,
) -> datetime:
    """Resolve a naive local wall time deterministically.

    An ambiguous time uses ``preferred_fold``. A nonexistent time advances to
    the first valid local minute after the DST gap instead of silently applying
    an imaginary offset or skipping the reporting boundary.
    """
    if local_value.tzinfo is not None:
        raise ValueError("local_value must be a naive local datetime")
    if preferred_fold not in (0, 1):
        raise ValueError("preferred_fold must be 0 or 1")

    local_timezone = resolve_reporting_timezone(reporting_timezone)
    candidate_value = local_value
    for _ in range(181):
        candidates = _valid_local_candidates(candidate_value, local_timezone)
        if candidates:
            if len(candidates) == 1:
                return candidates[0]
            return candidates[preferred_fold]
        candidate_value += timedelta(minutes=1)
    raise ReportingTimezoneError(
        "Could not resolve local time within three hours of a timezone transition"
    )


def _local_midnight(local_date: date, reporting_timezone: str) -> datetime:
    return resolve_local_datetime(
        datetime.combine(local_date, time.min),
        reporting_timezone,
    )


@dataclass(frozen=True)
class ReportingWindow:
    cadence: AdministratorSummaryCadence
    reporting_timezone: str
    period_start_utc: datetime
    period_end_utc: datetime
    period_start_local: datetime
    period_end_local: datetime

    def __post_init__(self) -> None:
        start_utc = _require_aware_datetime(
            self.period_start_utc, field_name="period_start_utc"
        ).astimezone(UTC)
        end_utc = _require_aware_datetime(
            self.period_end_utc, field_name="period_end_utc"
        ).astimezone(UTC)
        _require_aware_datetime(
            self.period_start_local, field_name="period_start_local"
        )
        _require_aware_datetime(self.period_end_local, field_name="period_end_local")
        if start_utc >= end_utc:
            raise ValueError("Reporting window start must be before its end")

        local_timezone = resolve_reporting_timezone(self.reporting_timezone)
        expected_start_local = start_utc.astimezone(local_timezone)
        expected_end_local = end_utc.astimezone(local_timezone)
        if self.period_start_local.astimezone(UTC) != start_utc:
            raise ValueError("period_start_local does not match period_start_utc")
        if self.period_end_local.astimezone(UTC) != end_utc:
            raise ValueError("period_end_local does not match period_end_utc")

        object.__setattr__(self, "period_start_utc", start_utc)
        object.__setattr__(self, "period_end_utc", end_utc)
        object.__setattr__(self, "period_start_local", expected_start_local)
        object.__setattr__(self, "period_end_local", expected_end_local)


def calculate_completed_reporting_window(
    reference_time_utc: datetime,
    cadence: AdministratorSummaryCadence | str,
    reporting_timezone: str,
) -> ReportingWindow:
    """Return the most recently completed reporting window."""
    reference_utc = _require_aware_datetime(
        reference_time_utc, field_name="reference_time_utc"
    ).astimezone(UTC)
    cadence_value = AdministratorSummaryCadence(cadence)
    local_timezone = resolve_reporting_timezone(reporting_timezone)
    normalized_timezone_name = local_timezone.key
    reference_local = reference_utc.astimezone(local_timezone)

    if cadence_value is AdministratorSummaryCadence.DAILY:
        end_local = _local_midnight(reference_local.date(), normalized_timezone_name)
        start_local = _local_midnight(
            reference_local.date() - ONE_DAY,
            normalized_timezone_name,
        )
        start_utc = start_local.astimezone(UTC)
        end_utc = end_local.astimezone(UTC)
    elif cadence_value is AdministratorSummaryCadence.HOURLY:
        boundary_value = reference_local.replace(
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=None,
        )
        end_local = resolve_local_datetime(
            boundary_value,
            normalized_timezone_name,
            preferred_fold=reference_local.fold,
        )
        end_utc = end_local.astimezone(UTC)
        start_utc = end_utc - ONE_HOUR
        start_local = start_utc.astimezone(local_timezone)
    else:
        completed_minute = reference_local.minute - (reference_local.minute % 15)
        boundary_value = reference_local.replace(
            minute=completed_minute,
            second=0,
            microsecond=0,
            tzinfo=None,
        )
        end_local = resolve_local_datetime(
            boundary_value,
            normalized_timezone_name,
            preferred_fold=reference_local.fold,
        )
        end_utc = end_local.astimezone(UTC)
        start_utc = end_utc - FIFTEEN_MINUTES
        start_local = start_utc.astimezone(local_timezone)

    return ReportingWindow(
        cadence=cadence_value,
        reporting_timezone=normalized_timezone_name,
        period_start_utc=start_utc,
        period_end_utc=end_utc,
        period_start_local=start_local,
        period_end_local=end_local,
    )


@dataclass(frozen=True)
class ImportSourceSummary:
    source_code: str
    source_name: str
    job_count: int
    successful_job_count: int
    failed_job_count: int
    timed_out_job_count: int
    running_job_count: int
    skipped_job_count: int
    measurements_received: int
    measurements_inserted: int
    measurements_updated: int
    measurements_skipped: int
    interrupted_job_count: int = 0
    scheduled_job_count: int = 0
    manual_job_count: int = 0
    scheduled_run_expected: bool = False
    scheduled_job_status_code: str | None = None

    @property
    def scheduled_run_missing(self) -> bool:
        return self.scheduled_run_expected and self.scheduled_job_count == 0

    @property
    def job_status_code(self) -> str:
        """Return the status shown for this source's scheduled import.

        Collector-created summaries set ``scheduled_job_status_code`` from
        scheduled JobRun rows only. The count-based fallback keeps manually
        constructed domain records useful in tests and preview callers.
        """
        if self.scheduled_job_status_code:
            return self.scheduled_job_status_code
        if self.job_count == 0:
            return NO_SCHEDULED_RUN_STATUS
        if self.interrupted_job_count:
            return "interrupted"
        if self.timed_out_job_count:
            return "timed_out"
        if self.failed_job_count:
            return "failed"
        if self.running_job_count:
            return "running"
        if self.successful_job_count:
            return "success"
        if self.skipped_job_count:
            return "skipped"
        return NO_SCHEDULED_RUN_STATUS


@dataclass(frozen=True)
class QcActivityGroup:
    source_name: str
    device_name: str
    parameter_name: str
    check_code: str
    check_name: str
    outcome: QcDigestOutcome
    reason_code: str | None
    result_count: int
    measurement_count: int
    effective_threshold: float | None = None
    effective_unit_symbol: str | None = None
    effective_max_drift_per_day: float | None = None
    effective_drift_direction: str | None = None


@dataclass(frozen=True)
class EventDigestGroup:
    digest_code: str
    section: EventDigestSection
    source_code: str
    source_name: str
    device_name: str | None
    severity: str
    event_count: int


@dataclass(frozen=True)
class AttentionItem:
    attention_code: str
    count: int
    source_name: str | None = None
    device_name: str | None = None
    parameter_name: str | None = None
    check_name: str | None = None
    check_code: str | None = None
    reason_code: str | None = None
    successful_job_count: int | None = None
    effective_threshold: float | None = None
    effective_unit_symbol: str | None = None
    effective_max_drift_per_day: float | None = None
    effective_drift_direction: str | None = None
    free_bytes: int | None = None
    percent_free: float | None = None
    storage_status: str | None = None


@dataclass(frozen=True)
class AdministratorSummary:
    reporting_window: ReportingWindow
    generated_at_utc: datetime
    import_sources: tuple[ImportSourceSummary, ...] = ()
    qc_activity: tuple[QcActivityGroup, ...] = ()
    import_events: tuple[EventDigestGroup, ...] = ()
    system_events: tuple[EventDigestGroup, ...] = ()
    attention_items: tuple[AttentionItem, ...] = ()
    qc_groups_truncated: bool = False
    event_groups_truncated: bool = False
    environment_label: str | None = None

    def __post_init__(self) -> None:
        generated_at_utc = _require_aware_datetime(
            self.generated_at_utc, field_name="generated_at_utc"
        ).astimezone(UTC)
        object.__setattr__(self, "generated_at_utc", generated_at_utc)

    @property
    def overall_status(self) -> AdministratorSummaryStatus:
        if self.attention_items:
            return AdministratorSummaryStatus.NEEDS_ATTENTION
        return AdministratorSummaryStatus.ALL_SYSTEMS_NORMAL

    @property
    def attention_item_count(self) -> int:
        return len(self.attention_items)
