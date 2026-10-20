from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.us_epa_gas_hourly import (
    construct_provider_hourly_gas_hour,
    construct_subhourly_gas_hour,
)
from services.air_quality_index.us_epa_hourly_completeness import (
    RawHourlyObservation,
)


HOUR_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _minute_observations(count: int, *, concentration: float = 53.0):
    return tuple(
        RawHourlyObservation(
            measurement_id=index + 1,
            observed_at=HOUR_START + timedelta(minutes=index),
            concentration=concentration,
            is_valid=True,
        )
        for index in range(count)
    )


def test_subhourly_gas_hour_accepts_exactly_75_percent_of_expected_positions():
    result = construct_subhourly_gas_hour(
        _minute_observations(45),
        interval_started_at=HOUR_START,
        parameter_code="no2",
        input_unit="ppb",
        expected_frequency_seconds=60,
        measurement_duration_seconds=60,
        source_aggregation_duration_seconds=60,
        timestamp_semantics="interval_start",
    )

    assert result.is_eligible
    assert result.hourly_concentration == 53.0
    assert result.valid_observation_count == 45
    assert result.required_valid_observation_count == 45
    assert result.completeness_rule_code == (
        "compass_aq.us_epa_input.no2.hourly_75_percent"
    )


def test_subhourly_gas_hour_rejects_less_than_75_percent():
    result = construct_subhourly_gas_hour(
        _minute_observations(44),
        interval_started_at=HOUR_START,
        parameter_code="so2",
        input_unit="ppb",
        expected_frequency_seconds=60,
        measurement_duration_seconds=60,
        source_aggregation_duration_seconds=60,
        timestamp_semantics="interval_start",
    )

    assert not result.is_eligible
    assert result.hourly_concentration is None
    assert result.exclusion_reason is ExclusionReason.HOURLY_COMPLETENESS_NOT_MET


def test_subhourly_co_hour_applies_exact_ppb_to_ppm_conversion():
    result = construct_subhourly_gas_hour(
        _minute_observations(45, concentration=4400.0),
        interval_started_at=HOUR_START,
        parameter_code="co",
        input_unit="ppb",
        expected_frequency_seconds=60,
        measurement_duration_seconds=60,
        source_aggregation_duration_seconds=60,
        timestamp_semantics="interval_start",
    )

    assert result.is_eligible
    assert result.hourly_concentration == 4.4
    assert result.normalized_unit == "ppm"


def test_provider_hourly_gas_requires_one_value_at_the_documented_boundary():
    result = construct_provider_hourly_gas_hour(
        (
            RawHourlyObservation(
                measurement_id=1,
                observed_at=HOUR_START + timedelta(hours=1),
                concentration=75.0,
                is_valid=True,
            ),
        ),
        interval_started_at=HOUR_START,
        parameter_code="so2",
        input_unit="ppb",
        timestamp_semantics="hour_end",
    )

    assert result.is_eligible
    assert result.hourly_concentration == 75.0
    assert result.measurement_ids == (1,)


def test_provider_hourly_gas_rejects_an_off_boundary_value():
    result = construct_provider_hourly_gas_hour(
        (
            RawHourlyObservation(
                measurement_id=1,
                observed_at=HOUR_START + timedelta(minutes=59),
                concentration=75.0,
                is_valid=True,
            ),
        ),
        interval_started_at=HOUR_START,
        parameter_code="so2",
        input_unit="ppb",
        timestamp_semantics="hour_end",
    )

    assert not result.is_eligible
    assert result.exclusion_reason is ExclusionReason.OFF_FREQUENCY_OBSERVATIONS
