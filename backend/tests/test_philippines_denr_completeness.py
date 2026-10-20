from dataclasses import replace
from datetime import datetime, timedelta, timezone

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.hourly_measurements import (
    HourlySensorStreamMetadata,
    RawMeasurementInput,
)
from services.air_quality_index.philippines_denr_service import (
    QualifiedPhilippineHour,
    qualify_completed_day_hours,
    qualify_hour,
    qualify_rolling_eight_hour_hours,
)


HOUR_START = datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc)


def _sensor(**changes) -> HourlySensorStreamMetadata:
    sensor = HourlySensorStreamMetadata(
        sensor_id=1,
        external_sensor_id="99177",
        aggregation_period="2m",
        hourly_concentration_provenance=None,
        hourly_timestamp_semantics=None,
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        measurement_timestamp_semantics="interval_end",
        measurement_metadata_status="provider_documented",
        measurement_metadata_managed_by="fixture",
        input_unit_code="ug_m3",
        input_unit_symbol="µg/m³",
        parameter_code="pm25",
        device_id=1,
        device_name="Manila sensor",
        device_friendly_name=None,
        latitude=None,
        longitude=None,
        device_timezone="Asia/Manila",
        source_name="PurpleAir",
    )
    return replace(sensor, **changes)


def _observations(count: int) -> list[RawMeasurementInput]:
    return [
        RawMeasurementInput(
            measurement_id=index + 1,
            sensor_id=1,
            observed_at=HOUR_START + timedelta(minutes=2 * (index + 1)),
            concentration=10 + index,
            is_valid=True,
        )
        for index in range(count)
    ]


def test_documented_two_minute_stream_requires_23_of_30_positions():
    failed = qualify_hour(_sensor(), _observations(22), interval_started_at=HOUR_START)
    assert failed.expected_observation_count == 30
    assert failed.required_valid_observation_count == 23
    assert failed.exclusion_reason is ExclusionReason.HOURLY_COMPLETENESS_NOT_MET
    passed = qualify_hour(_sensor(), _observations(23), interval_started_at=HOUR_START)
    assert passed.is_eligible
    assert passed.valid_observation_count == 23


def test_duplicate_off_frequency_and_invalid_observations_remain_explicit():
    duplicate_inputs = _observations(23)
    duplicate_inputs.append(
        replace(duplicate_inputs[0], measurement_id=99, observed_at=duplicate_inputs[0].observed_at)
    )
    duplicate = qualify_hour(_sensor(), duplicate_inputs, interval_started_at=HOUR_START)
    assert duplicate.is_eligible
    assert duplicate.duplicate_measurement_ids == (99,)
    assert duplicate.exclusion_reason is None

    invalid_inputs = _observations(23)
    invalid_inputs.append(
        RawMeasurementInput(100, 1, HOUR_START + timedelta(minutes=47), 10, False)
    )
    invalid = qualify_hour(_sensor(), invalid_inputs, interval_started_at=HOUR_START)
    assert invalid.is_eligible
    assert invalid.rejected_measurement_ids == (100,)


def test_provider_hourly_requires_verified_provenance_and_exactly_one_boundary_value():
    sensor = _sensor(
        aggregation_period="1h",
        hourly_concentration_provenance="provider_reported_hourly_average",
        hourly_timestamp_semantics="hour_end",
        expected_frequency_seconds=3600,
        measurement_duration_seconds=3600,
        source_aggregation_duration_seconds=3600,
        measurement_timestamp_semantics="interval_end",
    )
    valid = [RawMeasurementInput(1, 1, HOUR_START + timedelta(hours=1), 12, True)]
    result = qualify_hour(sensor, valid, interval_started_at=HOUR_START)
    assert result.is_eligible
    assert result.measurement_ids == (1,)

    missing_provenance = qualify_hour(
        replace(sensor, hourly_concentration_provenance=None),
        valid,
        interval_started_at=HOUR_START,
    )
    assert missing_provenance.exclusion_reason is ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING


def _qualified_hours(missing_positions: set[int], count: int = 24):
    return tuple(
        QualifiedPhilippineHour(
            HOUR_START + index * timedelta(hours=1),
            HOUR_START + (index + 1) * timedelta(hours=1),
            None if index in missing_positions else 10,
            "µg/m³",
            "ineligible" if index in missing_positions else "eligible",
            ExclusionReason.MISSING_MEASUREMENTS if index in missing_positions else None,
            1,
            0 if index in missing_positions else 1,
            1,
            (),
            (),
            (),
            (),
        )
        for index in range(count)
    )


def test_daily_18_hour_and_each_block_6_hour_boundaries_are_explicit():
    eligible = qualify_completed_day_hours(_qualified_hours({0, 1, 8, 9, 16, 17}))
    assert eligible.eligibility_status == "eligible"
    assert eligible.valid_hour_count == 18
    assert eligible.block_valid_hour_counts == (6, 6, 6)

    seventeen = qualify_completed_day_hours(_qualified_hours({0, 1, 2, 8, 9, 16, 17}))
    assert seventeen.exclusion_reason is ExclusionReason.DAILY_COMPLETENESS_NOT_MET

    weak_block = qualify_completed_day_hours(_qualified_hours({0, 1, 2, 8, 16, 17}))
    assert weak_block.valid_hour_count == 18
    assert weak_block.block_valid_hour_counts[0] == 5
    assert weak_block.exclusion_reason is ExclusionReason.DAILY_COMPLETENESS_NOT_MET


def test_three_consecutive_missing_hours_fail_an_otherwise_complete_day():
    result = qualify_completed_day_hours(_qualified_hours({6, 7, 8}))
    assert result.valid_hour_count == 21
    assert result.maximum_consecutive_missing_hours == 3
    assert result.exclusion_reason is ExclusionReason.DAILY_COMPLETENESS_NOT_MET


def test_rolling_window_accepts_six_hours_and_rejects_five():
    six = qualify_rolling_eight_hour_hours(_qualified_hours({0, 1}, count=8))
    assert six.eligibility_status == "eligible"
    five = qualify_rolling_eight_hour_hours(_qualified_hours({0, 1, 2}, count=8))
    assert five.exclusion_reason is ExclusionReason.ROLLING_8_HOUR_COMPLETENESS_NOT_MET
