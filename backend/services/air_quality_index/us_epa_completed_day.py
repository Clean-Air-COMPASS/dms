from __future__ import annotations

"""Pure completed-local-day rules for U.S. EPA PM2.5 and PM10 AQI.

The federal PM appendices use 18 of 24 hourly values for an ordinary day.
CompassAQ applies the same 75-percent fraction provider-neutrally to the actual
elapsed-hour count of an IANA local date. That DST extension is application
provenance; it is not a claim of regulatory-monitor qualification.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from typing import Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.air_quality_index.domain import (
    ExclusionReason,
    MethodologyReference,
)
from services.air_quality_index.hourly_measurements import normalize_utc
from services.air_quality_index.us_epa import (
    CoverageStatus,
    PM10_DAILY_COMPLETENESS_REFERENCE,
    PM25_DAILY_COMPLETENESS_REFERENCE,
    UsEpaCalculationResult,
    calculate_component_aqi,
    truncate_concentration,
)
from services.air_quality_index.us_epa_hourly_completeness import (
    CompletenessApplicationProvenance,
    EligibleHourlyConcentration,
    HourlyCompletenessAuditFlag,
)


COMPLETED_DAY_CALCULATION_CODE = "pm_completed_local_day"
DAILY_REQUIRED_COMPLETENESS_FRACTION = Decimal("0.75")
MAXIMUM_HISTORICAL_LOCAL_DATE_COUNT = 366
DAILY_COMPLETENESS_RULE_CODE = (
    "compass_aq.us_epa_completed_day.pm.hourly_75_percent"
)

ACTUAL_LOCAL_DAY_HOUR_COUNT_PROVENANCE = CompletenessApplicationProvenance(
    provenance_code="compass_aq.actual_iana_local_day_hour_count",
    description=(
        "CompassAQ derives expected hours from the UTC elapsed time between "
        "successive local midnights, preserving 23- and 25-hour DST days."
    ),
)

DAILY_REQUIRED_COUNT_PROVENANCE = CompletenessApplicationProvenance(
    provenance_code="compass_aq.daily_75_percent_required_count",
    description=(
        "CompassAQ applies 75 percent to the actual local-day hour count and "
        "rounds upward. This provider-neutral operational rule does not qualify "
        "a sensor as a regulatory monitor."
    ),
)

AVAILABLE_HOUR_MEAN_PROVENANCE = CompletenessApplicationProvenance(
    provenance_code="compass_aq.mean_of_eligible_hourly_concentrations",
    description=(
        "CompassAQ calculates one sensor stream's daily arithmetic mean from "
        "eligible hourly concentrations only."
    ),
)


@dataclass(frozen=True)
class CompletedLocalDayWindow:
    represented_local_date: date
    device_timezone: str
    local_day_started_at: datetime
    local_day_ended_at: datetime
    utc_window_started_at: datetime
    utc_window_ended_at: datetime
    expected_hour_count: int
    hourly_interval_starts_utc: Tuple[datetime, ...]


@dataclass(frozen=True)
class CompletedLocalDayResolution:
    window: Optional[CompletedLocalDayWindow]
    blocking_reasons: Tuple[ExclusionReason, ...]
    represented_local_date: Optional[date] = None

    @property
    def is_available(self) -> bool:
        return self.window is not None and not self.blocking_reasons


@dataclass(frozen=True)
class DailyCompletenessDecision:
    expected_hour_count: int
    valid_hour_count: int
    required_valid_hour_count: int
    required_completeness_fraction: float
    achieved_completeness_fraction: float
    eligibility_status: str
    blocking_reasons: Tuple[ExclusionReason, ...]
    completeness_rule_code: str
    reference_basis: Tuple[MethodologyReference, ...]
    application_provenance: Tuple[CompletenessApplicationProvenance, ...]

    @property
    def is_eligible(self) -> bool:
        return self.eligibility_status == "eligible"


@dataclass(frozen=True)
class CompletedDayCalculation:
    daily_concentration: Optional[float]
    normalized_unit: Optional[str]
    calculation: Optional[UsEpaCalculationResult]
    completeness: DailyCompletenessDecision
    blocking_reasons: Tuple[ExclusionReason, ...]
    audit_flags: Tuple[HourlyCompletenessAuditFlag, ...]
    measurement_ids: Tuple[int, ...]
    reference_basis: Tuple[MethodologyReference, ...]
    application_provenance: Tuple[CompletenessApplicationProvenance, ...]

    @property
    def is_eligible(self) -> bool:
        return (
            not self.blocking_reasons
            and self.calculation is not None
            and self.calculation.is_calculated
        )


def generate_inclusive_local_dates(
    start_local_date: date,
    end_local_date: date,
) -> Tuple[date, ...]:
    """Return a validated inclusive sequence of represented local dates."""
    if start_local_date > end_local_date:
        raise ValueError(
            "start_local_date must be on or before end_local_date"
        )
    requested_day_count = (end_local_date - start_local_date).days + 1
    if requested_day_count > MAXIMUM_HISTORICAL_LOCAL_DATE_COUNT:
        raise ValueError(
            "Inclusive represented-local-date range cannot exceed "
            f"{MAXIMUM_HISTORICAL_LOCAL_DATE_COUNT} days"
        )
    return tuple(
        start_local_date + timedelta(days=day_offset)
        for day_offset in range(requested_day_count)
    )


def _resolve_timezone(
    device_timezone: Optional[str],
    *,
    represented_local_date: Optional[date],
) -> tuple[Optional[str], Optional[ZoneInfo], Optional[CompletedLocalDayResolution]]:
    timezone_name = str(device_timezone or "").strip()
    if not timezone_name:
        return None, None, CompletedLocalDayResolution(
            window=None,
            blocking_reasons=(ExclusionReason.DEVICE_TIMEZONE_MISSING,),
            represented_local_date=represented_local_date,
        )
    try:
        local_timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone_name, None, CompletedLocalDayResolution(
            window=None,
            blocking_reasons=(ExclusionReason.DEVICE_TIMEZONE_INVALID,),
            represented_local_date=represented_local_date,
        )
    return timezone_name, local_timezone, None


def _build_local_day_window(
    represented_local_date: date,
    timezone_name: str,
    local_timezone: ZoneInfo,
) -> CompletedLocalDayResolution:
    """Build UTC interval identity for one IANA represented local date."""
    local_start = datetime.combine(
        represented_local_date,
        time.min,
        tzinfo=local_timezone,
    )
    local_end = datetime.combine(
        represented_local_date + timedelta(days=1),
        time.min,
        tzinfo=local_timezone,
    )
    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_end.astimezone(timezone.utc)
    elapsed_seconds = int((utc_end - utc_start).total_seconds())
    if elapsed_seconds <= 0 or elapsed_seconds % 3600 != 0:
        return CompletedLocalDayResolution(
            window=None,
            blocking_reasons=(
                ExclusionReason.COMPLETED_LOCAL_DAY_NOT_AVAILABLE,
            ),
            represented_local_date=represented_local_date,
        )
    expected_hours = elapsed_seconds // 3600
    hourly_starts = tuple(
        utc_start + timedelta(hours=hour_index)
        for hour_index in range(expected_hours)
    )
    return CompletedLocalDayResolution(
        window=CompletedLocalDayWindow(
            represented_local_date=represented_local_date,
            device_timezone=timezone_name,
            local_day_started_at=local_start,
            local_day_ended_at=local_end,
            utc_window_started_at=utc_start,
            utc_window_ended_at=utc_end,
            expected_hour_count=expected_hours,
            hourly_interval_starts_utc=hourly_starts,
        ),
        blocking_reasons=(),
        represented_local_date=represented_local_date,
    )


def resolve_represented_local_day(
    represented_local_date: date,
    device_timezone: Optional[str],
) -> CompletedLocalDayResolution:
    """Resolve one requested date in a device's configured IANA timezone."""
    timezone_name, local_timezone, failure = _resolve_timezone(
        device_timezone,
        represented_local_date=represented_local_date,
    )
    if failure is not None:
        return failure
    if timezone_name is None or local_timezone is None:
        raise RuntimeError("Resolved timezone is unexpectedly unavailable")
    return _build_local_day_window(
        represented_local_date,
        timezone_name,
        local_timezone,
    )


def resolve_completed_local_day(
    evaluation_time_utc: datetime,
    device_timezone: Optional[str],
) -> CompletedLocalDayResolution:
    """Resolve the immediately preceding complete IANA local calendar date."""
    timezone_name, local_timezone, failure = _resolve_timezone(
        device_timezone,
        represented_local_date=None,
    )
    if failure is not None:
        return failure
    if timezone_name is None or local_timezone is None:
        raise RuntimeError("Resolved timezone is unexpectedly unavailable")

    evaluation_utc = normalize_utc(evaluation_time_utc)
    current_local_date = evaluation_utc.astimezone(local_timezone).date()
    represented_date = current_local_date - timedelta(days=1)
    return _build_local_day_window(
        represented_date,
        timezone_name,
        local_timezone,
    )


def calculate_required_daily_hour_count(expected_hour_count: int) -> int:
    """Apply the Phase 2A 75-percent rule to the actual IANA-day hours."""
    if expected_hour_count <= 0:
        return 0
    return int(
        (
            Decimal(expected_hour_count)
            * DAILY_REQUIRED_COMPLETENESS_FRACTION
        ).to_integral_value(rounding=ROUND_CEILING)
    )


def _daily_reference_basis(
    pollutant_code: str,
) -> Tuple[MethodologyReference, ...]:
    if pollutant_code == "pm25":
        return (PM25_DAILY_COMPLETENESS_REFERENCE,)
    if pollutant_code == "pm10":
        return (PM10_DAILY_COMPLETENESS_REFERENCE,)
    return ()


def resolve_daily_completeness(
    *,
    standard_code: str,
    pollutant_code: str,
    calculation_code: str,
    represented_local_date: date,
    expected_hour_count: int,
    valid_hour_count: int,
) -> DailyCompletenessDecision:
    """Resolve one explicit, provider-neutral completed-day decision."""
    del represented_local_date  # Retained in the signature for auditable context.
    reasons: list[ExclusionReason] = []
    if standard_code != "us_epa" or calculation_code != COMPLETED_DAY_CALCULATION_CODE:
        reasons.append(ExclusionReason.UNSUPPORTED_DAILY_METHODOLOGY)
    if pollutant_code not in {"pm25", "pm10"}:
        reasons.append(ExclusionReason.UNSUPPORTED_DAILY_POLLUTANT)
    if expected_hour_count not in {23, 24, 25}:
        reasons.append(ExclusionReason.COMPLETED_LOCAL_DAY_NOT_AVAILABLE)

    required_count = calculate_required_daily_hour_count(expected_hour_count)
    achieved_fraction = (
        valid_hour_count / expected_hour_count if expected_hour_count > 0 else 0.0
    )
    if valid_hour_count <= 0:
        reasons.append(ExclusionReason.NO_VALID_HOURLY_CONCENTRATIONS)
    elif valid_hour_count < required_count:
        reasons.append(ExclusionReason.DAILY_COMPLETENESS_NOT_MET)

    return DailyCompletenessDecision(
        expected_hour_count=expected_hour_count,
        valid_hour_count=valid_hour_count,
        required_valid_hour_count=required_count,
        required_completeness_fraction=float(DAILY_REQUIRED_COMPLETENESS_FRACTION),
        achieved_completeness_fraction=achieved_fraction,
        eligibility_status="eligible" if not reasons else "ineligible",
        blocking_reasons=tuple(dict.fromkeys(reasons)),
        completeness_rule_code=DAILY_COMPLETENESS_RULE_CODE,
        reference_basis=_daily_reference_basis(pollutant_code),
        application_provenance=(
            ACTUAL_LOCAL_DAY_HOUR_COUNT_PROVENANCE,
            DAILY_REQUIRED_COUNT_PROVENANCE,
        ),
    )


def calculate_completed_day_pm(
    *,
    parameter_code: str,
    represented_local_date: date,
    expected_hour_count: int,
    hourly_inputs: Sequence[EligibleHourlyConcentration],
) -> CompletedDayCalculation:
    """Calculate a daily PM concentration and AQI from eligible hourly inputs."""
    eligible_inputs = tuple(item for item in hourly_inputs if item.is_eligible)
    completeness = resolve_daily_completeness(
        standard_code="us_epa",
        pollutant_code=parameter_code,
        calculation_code=COMPLETED_DAY_CALCULATION_CODE,
        represented_local_date=represented_local_date,
        expected_hour_count=expected_hour_count,
        valid_hour_count=len(eligible_inputs),
    )
    audit_flags = tuple(
        dict.fromkeys(
            flag
            for hourly_input in hourly_inputs
            for flag in hourly_input.audit_flags
        )
    )
    measurement_ids = tuple(
        sorted(
            measurement_id
            for hourly_input in eligible_inputs
            for measurement_id in hourly_input.measurement_ids
        )
    )
    concentrations = [
        Decimal(str(hourly_input.hourly_concentration))
        for hourly_input in eligible_inputs
        if hourly_input.hourly_concentration is not None
    ]
    if parameter_code == "pm25":
        # Appendix N 3.0(b) reports hourly PM2.5 to one decimal before the
        # available-hour daily arithmetic mean in 3.0(c).
        concentrations = [
            truncate_concentration(concentration, 1)
            for concentration in concentrations
        ]
    daily_concentration_decimal = (
        sum(concentrations, Decimal("0")) / Decimal(len(concentrations))
        if concentrations
        else None
    )
    normalized_unit = (
        eligible_inputs[0].normalized_unit or "µg/m³"
        if eligible_inputs
        else None
    )
    concentration_provenance = (
        (AVAILABLE_HOUR_MEAN_PROVENANCE,)
        if daily_concentration_decimal is not None
        else ()
    )
    if not completeness.is_eligible:
        return CompletedDayCalculation(
            daily_concentration=(
                float(daily_concentration_decimal)
                if daily_concentration_decimal is not None
                else None
            ),
            normalized_unit=normalized_unit,
            calculation=None,
            completeness=completeness,
            blocking_reasons=completeness.blocking_reasons,
            audit_flags=audit_flags,
            measurement_ids=measurement_ids,
            reference_basis=completeness.reference_basis,
            application_provenance=(
                *completeness.application_provenance,
                *concentration_provenance,
            ),
        )

    if daily_concentration_decimal is None or normalized_unit is None:
        raise RuntimeError("Eligible completed day has no concentration")
    calculation = calculate_component_aqi(
        parameter_code,
        f"{parameter_code}_24_hour",
        daily_concentration_decimal,
        normalized_unit,
        coverage_status=(
            CoverageStatus.COMPLETE
            if len(eligible_inputs) == expected_hour_count
            else CoverageStatus.PARTIAL
        ),
        expected_observation_count=expected_hour_count,
        valid_observation_count=len(eligible_inputs),
    )
    calculation_reason = (
        (calculation.exclusion_reason,)
        if calculation.exclusion_reason is not None
        else ()
    )
    return CompletedDayCalculation(
        daily_concentration=float(daily_concentration_decimal),
        normalized_unit=calculation.normalized_unit,
        calculation=calculation,
        completeness=completeness,
        blocking_reasons=calculation_reason,
        audit_flags=audit_flags,
        measurement_ids=measurement_ids,
        reference_basis=completeness.reference_basis,
        application_provenance=(
            *completeness.application_provenance,
            *concentration_provenance,
        ),
    )
