from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import inspect

import pytest

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.us_epa_completed_day import (
    DAILY_COMPLETENESS_RULE_CODE,
    calculate_completed_day_pm,
    generate_inclusive_local_dates,
    resolve_completed_local_day,
    resolve_daily_completeness,
    resolve_represented_local_day,
)
from services.air_quality_index.us_epa_hourly_completeness import (
    EligibleHourlyConcentration,
    HourlyCompletenessAuditFlag,
)


def _eligible_hour(
    hour_start: datetime,
    concentration: float,
    measurement_id: int,
    *,
    audit_flags: tuple[HourlyCompletenessAuditFlag, ...] = (),
) -> EligibleHourlyConcentration:
    return EligibleHourlyConcentration(
        interval_started_at=hour_start,
        interval_ended_at=hour_start + timedelta(hours=1),
        hourly_concentration=concentration,
        normalized_unit="µg/m³",
        eligibility_status="eligible",
        exclusion_reason=None,
        exclusion_reasons=(),
        audit_flags=audit_flags,
        input_frequency_seconds=3600,
        measurement_duration_seconds=3600,
        source_aggregation_duration_seconds=3600,
        target_duration_seconds=3600,
        expected_observation_count=1,
        valid_observation_count=1,
        required_valid_observation_count=1,
        required_completeness_fraction=1.0,
        achieved_completeness_fraction=1.0,
        measurement_ids=(measurement_id,),
        duplicate_measurement_ids=(),
        rejected_measurement_ids=(),
        off_frequency_measurement_ids=(),
        missing_position_count=0,
        completeness_rule_code="us_epa.pm.hourly_provider_reported",
        completeness_reference_basis=(),
        application_provenance=(),
    )


@pytest.mark.parametrize(
    ("start_date", "end_date", "expected_dates"),
    (
        (date(2024, 2, 29), date(2024, 2, 29), (date(2024, 2, 29),)),
        (
            date(2024, 2, 28),
            date(2024, 3, 1),
            (date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)),
        ),
        (
            date(2025, 12, 31),
            date(2026, 1, 1),
            (date(2025, 12, 31), date(2026, 1, 1)),
        ),
    ),
)
def test_inclusive_local_date_generation_is_ordered_and_duplicate_free(
    start_date: date,
    end_date: date,
    expected_dates: tuple[date, ...],
) -> None:
    generated = generate_inclusive_local_dates(start_date, end_date)
    assert generated == expected_dates
    assert len(generated) == len(set(generated))


def test_inclusive_local_date_generation_enforces_range_limit() -> None:
    start_date = date(2024, 1, 1)
    allowed = generate_inclusive_local_dates(
        start_date,
        start_date + timedelta(days=365),
    )
    assert len(allowed) == 366
    with pytest.raises(ValueError, match="cannot exceed 366 days"):
        generate_inclusive_local_dates(
            start_date,
            start_date + timedelta(days=366),
        )
    with pytest.raises(ValueError, match="must be on or before"):
        generate_inclusive_local_dates(date(2025, 1, 2), date(2025, 1, 1))


@pytest.mark.parametrize(
    ("represented_date", "expected_hours"),
    (
        (date(2025, 2, 1), 24),
        (date(2025, 3, 9), 23),
        (date(2025, 11, 2), 25),
    ),
)
def test_arbitrary_represented_local_day_uses_actual_elapsed_hours(
    represented_date: date,
    expected_hours: int,
) -> None:
    resolution = resolve_represented_local_day(
        represented_date,
        "America/Los_Angeles",
    )
    assert resolution.represented_local_date == represented_date
    assert resolution.window is not None
    assert resolution.window.expected_hour_count == expected_hours


def test_arbitrary_date_is_retained_when_timezone_cannot_be_resolved() -> None:
    represented_date = date(2025, 2, 1)
    missing = resolve_represented_local_day(represented_date, None)
    invalid = resolve_represented_local_day(
        represented_date,
        "Not/A_Timezone",
    )
    assert missing.represented_local_date == represented_date
    assert invalid.represented_local_date == represented_date
    assert missing.blocking_reasons == (ExclusionReason.DEVICE_TIMEZONE_MISSING,)
    assert invalid.blocking_reasons == (ExclusionReason.DEVICE_TIMEZONE_INVALID,)


@pytest.mark.parametrize(
    ("evaluation_time", "timezone_name", "represented_date", "utc_start", "utc_end"),
    (
        (
            datetime(2025, 2, 2, 18, tzinfo=timezone.utc),
            "America/Los_Angeles",
            date(2025, 2, 1),
            datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
            datetime(2025, 2, 2, 8, tzinfo=timezone.utc),
        ),
        (
            datetime(2025, 2, 2, 1, tzinfo=timezone.utc),
            "Pacific/Kiritimati",
            date(2025, 2, 1),
            datetime(2025, 1, 31, 10, tzinfo=timezone.utc),
            datetime(2025, 2, 1, 10, tzinfo=timezone.utc),
        ),
        (
            datetime(2025, 2, 2, 5, tzinfo=timezone.utc),
            "America/New_York",
            date(2025, 2, 1),
            datetime(2025, 2, 1, 5, tzinfo=timezone.utc),
            datetime(2025, 2, 2, 5, tzinfo=timezone.utc),
        ),
    ),
)
def test_completed_local_day_uses_device_timezone_and_preceding_date(
    evaluation_time: datetime,
    timezone_name: str,
    represented_date: date,
    utc_start: datetime,
    utc_end: datetime,
) -> None:
    resolution = resolve_completed_local_day(evaluation_time, timezone_name)
    assert resolution.is_available
    assert resolution.window is not None
    assert resolution.window.represented_local_date == represented_date
    assert resolution.window.utc_window_started_at == utc_start
    assert resolution.window.utc_window_ended_at == utc_end
    assert resolution.window.expected_hour_count == 24


@pytest.mark.parametrize(
    ("evaluation_time", "expected_date", "expected_count", "utc_start", "utc_end"),
    (
        (
            datetime(2025, 3, 10, 12, tzinfo=timezone.utc),
            date(2025, 3, 9),
            23,
            datetime(2025, 3, 9, 8, tzinfo=timezone.utc),
            datetime(2025, 3, 10, 7, tzinfo=timezone.utc),
        ),
        (
            datetime(2025, 11, 3, 12, tzinfo=timezone.utc),
            date(2025, 11, 2),
            25,
            datetime(2025, 11, 2, 7, tzinfo=timezone.utc),
            datetime(2025, 11, 3, 8, tzinfo=timezone.utc),
        ),
    ),
)
def test_dst_days_use_actual_utc_elapsed_hours(
    evaluation_time: datetime,
    expected_date: date,
    expected_count: int,
    utc_start: datetime,
    utc_end: datetime,
) -> None:
    resolution = resolve_completed_local_day(
        evaluation_time,
        "America/Los_Angeles",
    )
    assert resolution.window is not None
    window = resolution.window
    assert window.represented_local_date == expected_date
    assert window.expected_hour_count == expected_count
    assert window.utc_window_started_at == utc_start
    assert window.utc_window_ended_at == utc_end
    assert len(set(window.hourly_interval_starts_utc)) == expected_count
    assert all(
        second - first == timedelta(hours=1)
        for first, second in zip(
            window.hourly_interval_starts_utc,
            window.hourly_interval_starts_utc[1:],
        )
    )


def test_fall_back_repeated_local_hour_has_two_distinct_utc_intervals() -> None:
    resolution = resolve_completed_local_day(
        datetime(2025, 11, 3, 12, tzinfo=timezone.utc),
        "America/Los_Angeles",
    )
    assert resolution.window is not None
    repeated_hours = [
        hour_start
        for hour_start in resolution.window.hourly_interval_starts_utc
        if hour_start.astimezone(
            resolution.window.local_day_started_at.tzinfo
        ).hour == 1
    ]
    assert repeated_hours == [
        datetime(2025, 11, 2, 8, tzinfo=timezone.utc),
        datetime(2025, 11, 2, 9, tzinfo=timezone.utc),
    ]


def test_spring_forward_does_not_create_nonexistent_local_hour() -> None:
    resolution = resolve_completed_local_day(
        datetime(2025, 3, 10, 12, tzinfo=timezone.utc),
        "America/Los_Angeles",
    )
    assert resolution.window is not None
    local_hours = [
        hour_start.astimezone(resolution.window.local_day_started_at.tzinfo).hour
        for hour_start in resolution.window.hourly_interval_starts_utc
    ]
    assert 2 not in local_hours


def test_timezone_missing_and_invalid_are_explicit() -> None:
    evaluation_time = datetime(2025, 2, 2, tzinfo=timezone.utc)
    missing = resolve_completed_local_day(evaluation_time, None)
    invalid = resolve_completed_local_day(evaluation_time, "Not/A_Timezone")
    assert missing.blocking_reasons == (ExclusionReason.DEVICE_TIMEZONE_MISSING,)
    assert invalid.blocking_reasons == (ExclusionReason.DEVICE_TIMEZONE_INVALID,)


def test_exact_local_midnight_still_selects_the_preceding_date() -> None:
    resolution = resolve_completed_local_day(
        datetime(2025, 8, 1, 7, tzinfo=timezone.utc),
        "America/Los_Angeles",
    )
    assert resolution.window is not None
    assert resolution.window.represented_local_date == date(2025, 7, 31)
    assert resolution.window.local_day_ended_at == datetime(
        2025,
        8,
        1,
        tzinfo=resolution.window.local_day_started_at.tzinfo,
    )


def test_daily_completeness_resolver_has_no_provider_identity_input() -> None:
    parameter_names = set(inspect.signature(resolve_daily_completeness).parameters)
    assert "provider" not in " ".join(parameter_names)
    assert parameter_names == {
        "standard_code",
        "pollutant_code",
        "calculation_code",
        "represented_local_date",
        "expected_hour_count",
        "valid_hour_count",
    }


@pytest.mark.parametrize(
    ("expected_hours", "required_hours"),
    ((23, 18), (24, 18), (25, 19)),
)
def test_daily_completeness_required_counts_follow_actual_day_length(
    expected_hours: int,
    required_hours: int,
) -> None:
    exact = resolve_daily_completeness(
        standard_code="us_epa",
        pollutant_code="pm25",
        calculation_code="pm_completed_local_day",
        represented_local_date=date(2025, 1, 1),
        expected_hour_count=expected_hours,
        valid_hour_count=required_hours,
    )
    below = resolve_daily_completeness(
        standard_code="us_epa",
        pollutant_code="pm25",
        calculation_code="pm_completed_local_day",
        represented_local_date=date(2025, 1, 1),
        expected_hour_count=expected_hours,
        valid_hour_count=required_hours - 1,
    )
    assert exact.is_eligible
    assert exact.required_valid_hour_count == required_hours
    assert exact.completeness_rule_code == DAILY_COMPLETENESS_RULE_CODE
    assert below.blocking_reasons == (
        ExclusionReason.DAILY_COMPLETENESS_NOT_MET,
    )


def test_zero_valid_hours_has_specific_daily_reason() -> None:
    decision = resolve_daily_completeness(
        standard_code="us_epa",
        pollutant_code="pm10",
        calculation_code="pm_completed_local_day",
        represented_local_date=date(2025, 1, 1),
        expected_hour_count=24,
        valid_hour_count=0,
    )
    assert decision.blocking_reasons == (
        ExclusionReason.NO_VALID_HOURLY_CONCENTRATIONS,
    )


def test_pm25_hourly_values_are_truncated_before_daily_mean_and_aqi() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    hourly_inputs = tuple(
        _eligible_hour(start + timedelta(hours=index), 9.19, index + 1)
        for index in range(18)
    )
    result = calculate_completed_day_pm(
        parameter_code="pm25",
        represented_local_date=date(2025, 1, 1),
        expected_hour_count=24,
        hourly_inputs=hourly_inputs,
    )
    assert result.is_eligible
    assert result.daily_concentration == pytest.approx(9.1)
    assert result.calculation is not None
    assert result.calculation.preprocessed_concentration == 9.1
    assert result.calculation.numeric_value == 51


def test_pm10_daily_mean_is_not_integerized_until_aqi_preprocessing() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    hourly_inputs = tuple(
        _eligible_hour(start + timedelta(hours=index), 54.9, index + 1)
        for index in range(18)
    )
    result = calculate_completed_day_pm(
        parameter_code="pm10",
        represented_local_date=date(2025, 1, 1),
        expected_hour_count=24,
        hourly_inputs=hourly_inputs,
    )
    assert result.daily_concentration == pytest.approx(54.9)
    assert result.calculation is not None
    assert result.calculation.preprocessed_concentration == 54
    assert result.calculation.numeric_value == 50


@pytest.mark.parametrize(
    ("parameter_code", "concentration", "expected_aqi", "expected_category"),
    (
        ("pm25", 9.0, 50, "good"),
        ("pm25", 9.1, 51, "moderate"),
        ("pm25", 35.5, 101, "unhealthy_for_sensitive_groups"),
        ("pm10", 54, 50, "good"),
        ("pm10", 55, 51, "moderate"),
        ("pm10", 155, 101, "unhealthy_for_sensitive_groups"),
    ),
)
def test_completed_day_products_preserve_pm_breakpoint_boundaries(
    parameter_code: str,
    concentration: float,
    expected_aqi: int,
    expected_category: str,
) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    result = calculate_completed_day_pm(
        parameter_code=parameter_code,
        represented_local_date=date(2025, 1, 1),
        expected_hour_count=24,
        hourly_inputs=tuple(
            _eligible_hour(
                start + timedelta(hours=index),
                concentration,
                index + 1,
            )
            for index in range(18)
        ),
    )
    assert result.calculation is not None
    assert result.calculation.numeric_value == expected_aqi
    assert result.calculation.category_code == expected_category


@pytest.mark.parametrize(
    ("parameter_code", "concentration"),
    (("pm25", 400), ("pm10", 700)),
)
def test_completed_day_products_preserve_above_500_behavior(
    parameter_code: str,
    concentration: float,
) -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    result = calculate_completed_day_pm(
        parameter_code=parameter_code,
        represented_local_date=date(2025, 1, 1),
        expected_hour_count=24,
        hourly_inputs=tuple(
            _eligible_hour(
                start + timedelta(hours=index),
                concentration,
                index + 1,
            )
            for index in range(18)
        ),
    )
    assert result.calculation is not None
    assert result.calculation.numeric_value is not None
    assert result.calculation.numeric_value > 500
    assert result.calculation.category_code == "hazardous"
    assert result.calculation.aqi_scale_status is not None
    assert result.calculation.aqi_scale_status.value == "above_500"


def test_nonblocking_hourly_audit_flag_does_not_invalidate_daily_result() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    hourly_inputs = tuple(
        _eligible_hour(
            start + timedelta(hours=index),
            10,
            index + 1,
            audit_flags=(HourlyCompletenessAuditFlag.INVALID_OBSERVATIONS_REJECTED,)
            if index == 0
            else (),
        )
        for index in range(18)
    )
    result = calculate_completed_day_pm(
        parameter_code="pm25",
        represented_local_date=date(2025, 1, 1),
        expected_hour_count=24,
        hourly_inputs=hourly_inputs,
    )
    assert result.is_eligible
    assert result.audit_flags == (
        HourlyCompletenessAuditFlag.INVALID_OBSERVATIONS_REJECTED,
    )
