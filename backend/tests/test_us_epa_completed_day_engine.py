from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from db import SessionLocal
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    Sensor,
    Unit,
)
from services.air_quality_index.domain import ExclusionReason
from services.us_epa_completed_day_service import (
    calculate_latest_us_epa_completed_day_aqi,
)


def _create_device(
    session,
    *,
    timezone_name: str | None = "America/Los_Angeles",
    latitude: float | None = None,
    longitude: float | None = None,
) -> Device:
    external_api = ExternalAPI(
        name=f"completed-day-{uuid4()}",
        base_url="https://example.com",
        params={},
    )
    session.add(external_api)
    session.flush()
    device = Device(
        name=f"completed-day-device-{uuid4()}",
        external_api_id=external_api.external_api_id,
        timezone=timezone_name,
    )
    session.add(device)
    from services.device_locations import set_device_location

    set_device_location(
        session, device, latitude=latitude, longitude=longitude
    )
    return device


def _add_sensor(
    session,
    device: Device,
    *,
    parameter_code: str = "pm25",
    aggregation_period_code: str = "1h",
    hourly_timestamp_semantics: str = "hour_start",
    metadata_is_valid: bool = True,
) -> Sensor:
    parameter = session.scalar(select(Parameter).where(Parameter.code == parameter_code))
    unit = session.scalar(select(Unit).where(Unit.code == "ug_m3"))
    aggregation_period = session.scalar(
        select(AggregationPeriod).where(
            AggregationPeriod.code == aggregation_period_code
        )
    )
    # This suite must also run alone, without another test creating the 1m period.
    if aggregation_period is None and aggregation_period_code == "1m":
        aggregation_period = AggregationPeriod(
            code="1m", display_name="1 Minute", duration_minutes=1, is_rolling=False,
        )
        session.add(aggregation_period)
        session.flush()
    provider_hourly = aggregation_period_code == "1h"
    subhourly_duration_seconds = {
        "1m": 60,
        "2m": 120,
    }.get(aggregation_period_code)
    sensor = Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=aggregation_period.aggregation_period_id,
        hourly_concentration_provenance=(
            "provider_reported_hourly_average"
            if provider_hourly and metadata_is_valid
            else None
        ),
        hourly_timestamp_semantics=(
            hourly_timestamp_semantics
            if provider_hourly and metadata_is_valid
            else None
        ),
        expected_frequency_seconds=subhourly_duration_seconds,
        measurement_duration_seconds=subhourly_duration_seconds,
        source_aggregation_duration_seconds=subhourly_duration_seconds,
        measurement_timestamp_semantics=(
            None if provider_hourly else "interval_end"
        ),
        measurement_metadata_status=(
            "provider_documented" if metadata_is_valid else None
        ),
        measurement_metadata_managed_by=(
            "test_fixture" if metadata_is_valid else None
        ),
    )
    session.add(sensor)
    session.flush()
    return sensor


def _add_provider_hours(
    session,
    sensor: Sensor,
    first_hour_utc: datetime,
    count: int,
    value: float,
) -> None:
    for hour_index in range(count):
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=value,
                observed_at=first_hour_utc + timedelta(hours=hour_index),
                is_valid=True,
            )
        )


def test_completed_day_engine_calculates_one_provider_hourly_stream() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_sensor(session, device)
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        first_hour = datetime(2025, 2, 1, 8, tzinfo=timezone.utc)
        _add_provider_hours(session, sensor, first_hour, 18, 9.1)
        session.flush()

        results = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )

        assert len(results) == 1
        result = results[0]
        assert result.local_day_window is not None
        assert str(result.local_day_window.represented_local_date) == "2025-02-01"
        assert result.local_day_window.expected_hour_count == 24
        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == sensor.sensor_id
        assert result.calculation is not None
        assert result.calculation.numeric_value == 51
        assert len(result.measurement_ids) == 18
        evaluation = result.candidate_sensor_evaluations[0]
        assert evaluation.valid_hour_count == 18
        assert evaluation.completed_day_calculation is not None
        assert (
            evaluation.completed_day_calculation.completeness
            .required_valid_hour_count
        ) == 18
    finally:
        session.rollback()
        session.close()


def test_provider_hour_end_semantics_assign_values_to_the_daily_intervals() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_sensor(
            session,
            device,
            hourly_timestamp_semantics="hour_end",
        )
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        first_interval_start = datetime(2025, 2, 1, 8, tzinfo=timezone.utc)
        _add_provider_hours(
            session,
            sensor,
            first_interval_start + timedelta(hours=1),
            18,
            10,
        )
        session.flush()
        result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        evaluation = result.candidate_sensor_evaluations[0]
        assert evaluation.is_daily_eligible
        assert evaluation.valid_hour_count == 18
        assert evaluation.hourly_inputs[0].interval_started_at == first_interval_start
        assert evaluation.hourly_inputs[0].measurement_ids
    finally:
        session.rollback()
        session.close()


def test_one_below_daily_threshold_is_unavailable_with_candidate_reason() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_sensor(session, device, parameter_code="pm10")
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        _add_provider_hours(
            session,
            sensor,
            datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
            17,
            100,
        )
        session.flush()
        result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm10.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        assert result.calculation is None
        assert result.blocking_reasons == (
            ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM,
            ExclusionReason.DAILY_COMPLETENESS_NOT_MET,
        )
        assert result.candidate_sensor_evaluations[0].valid_hour_count == 17
        assert (
            result.candidate_sensor_evaluations[0]
            .completed_day_calculation
            .daily_concentration
        ) == 100
    finally:
        session.rollback()
        session.close()


def test_missing_and_invalid_device_timezones_are_not_substituted() -> None:
    session = SessionLocal()
    try:
        missing_device = _create_device(session, timezone_name=None)
        invalid_device = _create_device(session, timezone_name="Not/A_Timezone")
        _add_sensor(session, missing_device)
        _add_sensor(session, invalid_device)
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        session.flush()
        missing_result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=missing_device.device_id,
        )[0]
        invalid_result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=invalid_device.device_id,
        )[0]
        assert ExclusionReason.DEVICE_TIMEZONE_MISSING in (
            missing_result.blocking_reasons
        )
        assert ExclusionReason.DEVICE_TIMEZONE_INVALID in (
            invalid_result.blocking_reasons
        )
    finally:
        session.rollback()
        session.close()


def test_sensor_selection_uses_completeness_then_sensor_id_without_averaging() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        first_sensor = _add_sensor(session, device)
        more_complete_sensor = _add_sensor(session, device)
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        first_hour = datetime(2025, 2, 1, 8, tzinfo=timezone.utc)
        _add_provider_hours(session, first_sensor, first_hour, 18, 9.1)
        _add_provider_hours(session, more_complete_sensor, first_hour, 20, 35.5)
        session.flush()
        result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == more_complete_sensor.sensor_id
        assert result.calculation is not None
        assert result.calculation.normalized_concentration == 35.5

        # Equalize completeness; stable sensor ID is the final tie-breaker.
        _add_provider_hours(session, first_sensor, first_hour + timedelta(hours=18), 2, 9.1)
        session.flush()
        tied_result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        assert tied_result.selected_sensor is not None
        assert tied_result.selected_sensor.sensor_id == first_sensor.sensor_id
        assert tied_result.calculation is not None
        assert tied_result.calculation.normalized_concentration == 9.1
    finally:
        session.rollback()
        session.close()


def test_eligible_stream_wins_over_an_ineligible_lower_id_stream() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        ineligible_sensor = _add_sensor(
            session,
            device,
            metadata_is_valid=False,
        )
        eligible_sensor = _add_sensor(session, device)
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        _add_provider_hours(
            session,
            eligible_sensor,
            datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
            18,
            10,
        )
        session.flush()
        result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        assert ineligible_sensor.sensor_id < eligible_sensor.sensor_id
        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == eligible_sensor.sensor_id
        evaluations = {
            evaluation.sensor.sensor_id: evaluation
            for evaluation in result.candidate_sensor_evaluations
        }
        assert not evaluations[ineligible_sensor.sensor_id].is_daily_eligible
        assert evaluations[eligible_sensor.sensor_id].is_daily_eligible
    finally:
        session.rollback()
        session.close()


def test_completed_day_returns_one_result_for_each_matching_device() -> None:
    session = SessionLocal()
    try:
        first_device = _create_device(session, latitude=88, longitude=10)
        second_device = _create_device(session, latitude=88.1, longitude=10.1)
        first_sensor = _add_sensor(session, first_device)
        second_sensor = _add_sensor(session, second_device)
        first_hour = datetime(2025, 2, 1, 8, tzinfo=timezone.utc)
        _add_provider_hours(session, first_sensor, first_hour, 18, 10)
        _add_provider_hours(session, second_sensor, first_hour, 18, 20)
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        session.flush()
        results = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            bbox=(9, 87, 11, 89),
            limit=1000,
        )
        expected_ids = {first_device.device_id, second_device.device_id}
        matching_results = [
            result for result in results if result.device_id in expected_ids
        ]
        assert len(matching_results) == 2
        assert {result.device_id for result in matching_results} == expected_ids
    finally:
        session.rollback()
        session.close()


def test_duplicate_provider_hour_is_rejected_and_preserved_in_hourly_audit() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_sensor(session, device)
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        first_hour = datetime(2025, 2, 1, 8, tzinfo=timezone.utc)
        _add_provider_hours(session, sensor, first_hour, 18, 10)
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=12,
                observed_at=first_hour + timedelta(minutes=1),
                is_valid=True,
            )
        )
        session.flush()
        result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        evaluation = result.candidate_sensor_evaluations[0]
        assert evaluation.valid_hour_count == 17
        assert evaluation.hourly_inputs[0].exclusion_reason is (
            ExclusionReason.DUPLICATE_OBSERVATION_INTERVAL
        )
        assert ExclusionReason.DAILY_COMPLETENESS_NOT_MET in evaluation.blocking_reasons
    finally:
        session.rollback()
        session.close()


def test_one_minute_subhourly_stream_reuses_45_of_60_hourly_construction() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_sensor(session, device, aggregation_period_code="1m")
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        first_hour = datetime(2025, 2, 1, 8, tzinfo=timezone.utc)
        for hour_index in range(18):
            hour_start = first_hour + timedelta(hours=hour_index)
            for position in range(45):
                session.add(
                    Measurement(
                        sensor_id=sensor.sensor_id,
                        value=10,
                        observed_at=hour_start + timedelta(minutes=position + 1),
                        is_valid=True,
                    )
                )
        session.flush()
        result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        evaluation = result.candidate_sensor_evaluations[0]
        assert evaluation.is_daily_eligible
        assert evaluation.valid_hour_count == 18
        assert all(
            hourly_input.required_valid_observation_count == 45
            for hourly_input in evaluation.hourly_inputs[:18]
        )
    finally:
        session.rollback()
        session.close()


def test_incomplete_subhourly_hour_remains_missing_from_daily_inputs() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_sensor(session, device, aggregation_period_code="2m")
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        first_hour = datetime(2025, 2, 1, 8, tzinfo=timezone.utc)
        for hour_index in range(19):
            hour_start = first_hour + timedelta(hours=hour_index)
            observation_count = 23 if hour_index < 18 else 22
            for position in range(observation_count):
                session.add(
                    Measurement(
                        sensor_id=sensor.sensor_id,
                        value=10,
                        observed_at=hour_start
                        + timedelta(minutes=2 * (position + 1)),
                        is_valid=True,
                    )
                )
        session.flush()
        result = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code="us_epa.pm25.completed_day",
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        evaluation = result.candidate_sensor_evaluations[0]
        incomplete_hour = evaluation.hourly_inputs[18]
        assert evaluation.is_daily_eligible
        assert evaluation.valid_hour_count == 18
        assert not incomplete_hour.is_eligible
        assert incomplete_hour.hourly_concentration is None
        assert incomplete_hour.exclusion_reason is (
            ExclusionReason.HOURLY_COMPLETENESS_NOT_MET
        )
    finally:
        session.rollback()
        session.close()
