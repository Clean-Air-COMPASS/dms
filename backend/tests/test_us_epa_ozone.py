from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.us_epa import CoverageStatus
from services.air_quality_index.us_epa_hourly_completeness import (
    EligibleHourlyConcentration,
    RawHourlyObservation,
)
from services.air_quality_index.us_epa_ozone import (
    OzoneCandidateStatus,
    calculate_latest_ozone_window,
    construct_provider_hourly_ozone_hour,
    construct_subhourly_ozone_hour,
)


WINDOW_START = datetime(2026, 8, 1, tzinfo=timezone.utc)
WINDOW_END = WINDOW_START + timedelta(hours=8)


def _eligible_hour(hour_index: int, concentration: float) -> EligibleHourlyConcentration:
    started_at = WINDOW_START + timedelta(hours=hour_index)
    return EligibleHourlyConcentration(
        interval_started_at=started_at,
        interval_ended_at=started_at + timedelta(hours=1),
        hourly_concentration=concentration,
        normalized_unit="ppm",
        eligibility_status="eligible",
        exclusion_reason=None,
        exclusion_reasons=(),
        audit_flags=(),
        input_frequency_seconds=3600,
        measurement_duration_seconds=3600,
        source_aggregation_duration_seconds=3600,
        target_duration_seconds=3600,
        expected_observation_count=1,
        valid_observation_count=1,
        required_valid_observation_count=1,
        required_completeness_fraction=1.0,
        achieved_completeness_fraction=1.0,
        measurement_ids=(hour_index + 1,),
        duplicate_measurement_ids=(),
        rejected_measurement_ids=(),
        off_frequency_measurement_ids=(),
        missing_position_count=0,
        completeness_rule_code="test.provider_hourly",
        completeness_reference_basis=(),
        application_provenance=(),
    )


def test_complete_eight_hour_candidate_uses_hourly_then_rolling_truncation() -> None:
    hourly_inputs = tuple(_eligible_hour(index, 0.07853333) for index in range(8))
    result = calculate_latest_ozone_window(
        hourly_inputs,
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_END,
    )
    assert result.coverage_status is CoverageStatus.COMPLETE
    assert result.eight_hour_candidate.preprocessed_concentration == 0.078
    assert result.eight_hour_candidate.numeric_value == 126
    assert result.one_hour_candidate.candidate_status is OzoneCandidateStatus.NOT_APPLICABLE
    assert result.selected_aggregation_period == "8h"


@pytest.mark.parametrize("valid_hour_count", (6, 7))
def test_six_or_seven_hours_use_available_values_and_remain_partial(
    valid_hour_count: int,
) -> None:
    hourly_inputs = tuple(_eligible_hour(index, 0.060) for index in range(valid_hour_count))
    result = calculate_latest_ozone_window(
        hourly_inputs,
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_END,
    )
    assert result.eight_hour_candidate.candidate_status is OzoneCandidateStatus.CALCULATED
    assert result.eight_hour_candidate.coverage_status is CoverageStatus.PARTIAL
    assert result.eight_hour_candidate.valid_hour_count == valid_hour_count


def test_five_hours_use_zero_substitution_only_above_appendix_u_threshold() -> None:
    passing = calculate_latest_ozone_window(
        tuple(_eligible_hour(index, 0.114) for index in range(5)),
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_END,
    )
    failing = calculate_latest_ozone_window(
        tuple(_eligible_hour(index, 0.1139) for index in range(5)),
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_END,
    )
    assert passing.eight_hour_candidate.zero_substitution_used is True
    assert passing.eight_hour_candidate.preprocessed_concentration == 0.071
    assert failing.eight_hour_candidate.candidate_status is OzoneCandidateStatus.UNAVAILABLE
    assert failing.eight_hour_candidate.exclusion_reason is ExclusionReason.ROLLING_8_HOUR_COMPLETENESS_NOT_MET


def test_one_hour_maximum_can_win_and_equal_concentrations_choose_latest_hour() -> None:
    hourly_inputs = tuple(
        _eligible_hour(index, concentration)
        for index, concentration in enumerate((0.050, 0.405, 0.050, 0.050, 0.405, 0.050, 0.050, 0.050))
    )
    result = calculate_latest_ozone_window(
        hourly_inputs,
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_END,
    )
    assert result.selected_aggregation_period == "1h"
    assert result.one_hour_candidate.numeric_value == 301
    assert result.one_hour_candidate.interval_started_at == WINDOW_START + timedelta(hours=4)


def test_eight_hour_above_scale_is_not_applicable_but_one_hour_remains_available() -> None:
    result = calculate_latest_ozone_window(
        tuple(_eligible_hour(index, 0.201) for index in range(8)),
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_END,
    )
    assert result.eight_hour_candidate.candidate_status is OzoneCandidateStatus.NOT_APPLICABLE
    assert result.eight_hour_candidate.exclusion_reason is ExclusionReason.OZONE_8_HOUR_NOT_APPLICABLE
    assert result.one_hour_candidate.candidate_status is OzoneCandidateStatus.CALCULATED
    assert result.selected_aggregation_period == "1h"


def test_empty_window_returns_explicit_unavailable_candidates() -> None:
    result = calculate_latest_ozone_window(
        (),
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_END,
    )
    assert result.calculation_status == "unavailable"
    assert result.coverage_status is CoverageStatus.NONE
    assert result.exclusion_reason is ExclusionReason.NO_APPLICABLE_OZONE_CANDIDATE


@pytest.mark.parametrize(
    ("expected_count", "valid_count"),
    ((60, 45), (30, 23), (12, 9), (6, 5), (4, 3)),
)
def test_subhourly_ozone_requires_ceil_seventy_five_percent(
    expected_count: int,
    valid_count: int,
) -> None:
    frequency_seconds = 3600 // expected_count
    observations = tuple(
        RawHourlyObservation(
            measurement_id=index + 1,
            observed_at=WINDOW_START + timedelta(seconds=index * frequency_seconds),
            concentration=78,
            is_valid=True,
        )
        for index in range(valid_count)
    )
    result = construct_subhourly_ozone_hour(
        observations,
        interval_started_at=WINDOW_START,
        input_unit="ppb",
        expected_frequency_seconds=frequency_seconds,
        measurement_duration_seconds=frequency_seconds,
        source_aggregation_duration_seconds=frequency_seconds,
        timestamp_semantics="interval_start",
    )
    assert result.is_eligible
    assert result.expected_observation_count == expected_count
    assert result.required_valid_observation_count == valid_count
    assert result.hourly_concentration == pytest.approx(0.078)


def test_provider_hourly_requires_exactly_one_value_at_documented_boundary() -> None:
    exact = RawHourlyObservation(1, WINDOW_END, 0.078, True)
    eligible = construct_provider_hourly_ozone_hour(
        (exact,),
        interval_started_at=WINDOW_END - timedelta(hours=1),
        input_unit="ppm",
        timestamp_semantics="hour_end",
    )
    duplicate = construct_provider_hourly_ozone_hour(
        (exact, RawHourlyObservation(2, WINDOW_END, 0.079, True)),
        interval_started_at=WINDOW_END - timedelta(hours=1),
        input_unit="ppm",
        timestamp_semantics="hour_end",
    )
    assert eligible.is_eligible
    assert duplicate.is_eligible is False
    assert duplicate.exclusion_reason is ExclusionReason.DUPLICATE_OBSERVATION_INTERVAL
