from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.us_epa import CoverageStatus, calculate_component_aqi
from services.air_quality_index.us_epa_hourly_completeness import (
    EligibleHourlyConcentration,
)
from services.air_quality_index.us_epa_sulfur_dioxide import (
    SulfurDioxideCandidateStatus,
    calculate_latest_sulfur_dioxide_window,
)


WINDOW_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
WINDOW_END = WINDOW_START + timedelta(hours=24)


def _hour(index: int, concentration: float) -> EligibleHourlyConcentration:
    started_at = WINDOW_START + timedelta(hours=index)
    return EligibleHourlyConcentration(
        interval_started_at=started_at,
        interval_ended_at=started_at + timedelta(hours=1),
        hourly_concentration=concentration,
        normalized_unit="ppb",
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
        measurement_ids=(index + 1,),
        duplicate_measurement_ids=(),
        rejected_measurement_ids=(),
        off_frequency_measurement_ids=(),
        missing_position_count=0,
        completeness_rule_code="test.provider_hourly",
        completeness_reference_basis=(),
        application_provenance=(),
    )


def _calculate(values: tuple[float, ...]):
    return calculate_latest_sulfur_dioxide_window(
        tuple(_hour(index, value) for index, value in enumerate(values)),
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_END,
    )


def test_so2_selects_low_one_hour_table_when_maximum_is_304_ppb():
    result = _calculate((100.0,) * 23 + (304.0,))

    assert result.is_calculated
    assert result.selected_aggregation_period == "1h"
    assert result.selected_calculation_code == "so2_1_hour_low"
    assert result.selected_candidate is not None
    assert result.selected_candidate.numeric_value == 200
    assert result.twenty_four_hour_candidate.candidate_status is (
        SulfurDioxideCandidateStatus.NOT_APPLICABLE
    )
    assert result.selected_candidate.interval_started_at == WINDOW_START + timedelta(hours=23)


def test_so2_uses_preprocessed_integer_for_304_9_ppb_applicability():
    result = _calculate((100.0,) * 23 + (304.9,))

    assert result.selected_calculation_code == "so2_1_hour_low"
    assert result.selected_candidate is not None
    assert result.selected_candidate.preprocessed_concentration == 304.0


def test_so2_selects_high_24_hour_table_when_mean_is_305_ppb():
    result = _calculate((305.0,) * 24)

    assert result.is_calculated
    assert result.selected_aggregation_period == "24h"
    assert result.selected_calculation_code == "so2_24_hour_high"
    assert result.selected_candidate is not None
    assert result.selected_candidate.numeric_value == 201
    assert result.one_hour_candidate.candidate_status is (
        SulfurDioxideCandidateStatus.NOT_APPLICABLE
    )


def test_so2_caps_at_200_when_high_hour_has_low_24_hour_mean():
    result = _calculate((100.0,) * 23 + (305.0,))

    assert result.is_calculated
    assert result.selected_aggregation_period == "1h"
    assert result.selected_calculation_code == "so2_1_hour_capped_at_200"
    assert result.selected_candidate is not None
    assert result.selected_candidate.numeric_value == 200
    assert result.selected_candidate.preprocessed_concentration == 305.0


def test_so2_accepts_18_hours_as_partial_but_rejects_17():
    partial = _calculate((75.0,) * 18)
    unavailable = _calculate((75.0,) * 17)

    assert partial.is_calculated
    assert partial.coverage_status is CoverageStatus.PARTIAL
    assert partial.valid_hour_count == 18
    assert not unavailable.is_calculated
    assert unavailable.exclusion_reason is ExclusionReason.NO_APPLICABLE_SO2_CANDIDATE
    assert unavailable.one_hour_candidate.exclusion_reason is (
        ExclusionReason.ROLLING_24_HOUR_COMPLETENESS_NOT_MET
    )


def test_so2_partial_day_mean_divides_by_23_available_hours() -> None:
    result = _calculate((0.0,) * 22 + (23.0,))

    assert result.is_calculated
    assert result.valid_hour_count == 23
    assert result.coverage_status is CoverageStatus.PARTIAL
    assert result.twenty_four_hour_candidate.normalized_concentration == 1.0
    assert len(result.twenty_four_hour_candidate.measurement_ids) == 23


def test_so2_high_table_boundaries_and_above_500_slope():
    expected_values = {
        305: 201,
        604: 300,
        605: 301,
        1004: 500,
    }
    for concentration, expected_aqi in expected_values.items():
        calculation = calculate_component_aqi(
            "so2", "so2_24_hour_high", concentration, "ppb"
        )
        assert calculation.numeric_value == expected_aqi

    above = calculate_component_aqi(
        "so2", "so2_24_hour_high", 1007, "ppb"
    )
    assert above.numeric_value is not None and above.numeric_value > 500
