from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.us_epa import CoverageStatus
from services.air_quality_index.us_epa_carbon_monoxide import (
    calculate_latest_carbon_monoxide_window,
)
from services.air_quality_index.us_epa_hourly_completeness import (
    EligibleHourlyConcentration,
)


WINDOW_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _hour(index: int, concentration: float) -> EligibleHourlyConcentration:
    started_at = WINDOW_START + timedelta(hours=index)
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
        measurement_ids=(index + 1,),
        duplicate_measurement_ids=(),
        rejected_measurement_ids=(),
        off_frequency_measurement_ids=(),
        missing_position_count=0,
        completeness_rule_code="test.provider_hourly",
        completeness_reference_basis=(),
        application_provenance=(),
    )


def test_carbon_monoxide_averages_all_eight_hours():
    result = calculate_latest_carbon_monoxide_window(
        tuple(_hour(index, 4.4) for index in range(8)),
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_START + timedelta(hours=8),
    )

    assert result.is_calculated
    assert result.coverage_status is CoverageStatus.COMPLETE
    assert result.calculation is not None
    assert result.calculation.preprocessed_concentration == 4.4
    assert result.calculation.numeric_value == 50


def test_carbon_monoxide_averages_six_available_hours_without_zero_substitution():
    result = calculate_latest_carbon_monoxide_window(
        tuple(_hour(index, 9.4) for index in range(6)),
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_START + timedelta(hours=8),
    )

    assert result.is_calculated
    assert result.coverage_status is CoverageStatus.PARTIAL
    assert result.valid_hour_count == 6
    assert result.calculation is not None
    assert result.calculation.preprocessed_concentration == 9.4
    assert result.calculation.numeric_value == 100


def test_carbon_monoxide_rejects_five_available_hours():
    result = calculate_latest_carbon_monoxide_window(
        tuple(_hour(index, 30.4) for index in range(5)),
        window_started_at=WINDOW_START,
        window_ended_at=WINDOW_START + timedelta(hours=8),
    )

    assert not result.is_calculated
    assert result.exclusion_reason is ExclusionReason.ROLLING_8_HOUR_COMPLETENESS_NOT_MET
