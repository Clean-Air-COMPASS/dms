from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.us_epa_hourly_completeness import (
    EligibleHourlyConcentration,
)
from services.air_quality_index.us_epa_nitrogen_dioxide import (
    calculate_latest_nitrogen_dioxide_hour,
)


HOUR_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _eligible_hour(concentration: float) -> EligibleHourlyConcentration:
    return EligibleHourlyConcentration(
        interval_started_at=HOUR_START,
        interval_ended_at=HOUR_START + timedelta(hours=1),
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
        measurement_ids=(1,),
        duplicate_measurement_ids=(),
        rejected_measurement_ids=(),
        off_frequency_measurement_ids=(),
        missing_position_count=0,
        completeness_rule_code="test.provider_hourly",
        completeness_reference_basis=(),
        application_provenance=(),
    )


def test_nitrogen_dioxide_uses_the_single_completed_hour_and_integer_truncation():
    result = calculate_latest_nitrogen_dioxide_hour(
        (_eligible_hour(100.9),),
        window_started_at=HOUR_START,
        window_ended_at=HOUR_START + timedelta(hours=1),
    )

    assert result.is_calculated
    assert result.calculation is not None
    assert result.calculation.preprocessed_concentration == 100.0
    assert result.calculation.numeric_value == 100


def test_nitrogen_dioxide_rejects_an_ineligible_completed_hour():
    incomplete = replace(
        _eligible_hour(100.0),
        eligibility_status="ineligible",
        hourly_concentration=None,
        exclusion_reason=ExclusionReason.HOURLY_COMPLETENESS_NOT_MET,
        exclusion_reasons=(ExclusionReason.HOURLY_COMPLETENESS_NOT_MET,),
        valid_observation_count=0,
    )
    result = calculate_latest_nitrogen_dioxide_hour(
        (incomplete,),
        window_started_at=HOUR_START,
        window_ended_at=HOUR_START + timedelta(hours=1),
    )

    assert not result.is_calculated
    assert result.exclusion_reason is ExclusionReason.INCOMPLETE_HOUR
