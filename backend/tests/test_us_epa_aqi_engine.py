from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

import services.aqi_engine as aqi_engine
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
from services.aqi_engine import (
    NowCastHourlyInputEligibility,
    calculate_latest_us_epa_aqi,
    calculate_us_epa_aqi_history,
)
from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.us_epa_hourly_completeness import (
    HourlyCompletenessAuditFlag,
)


def _create_pm_sensor(
    session,
    *,
    parameter_code: str = "pm25",
    unit_code: str = "ug_m3",
    aggregation_period_code: str = "1h",
    hourly_concentration_provenance: str | None = "provider_reported_hourly_average",
    hourly_timestamp_semantics: str | None = "hour_start",
    expected_frequency_seconds: int | None = None,
    measurement_duration_seconds: int | None = None,
    source_aggregation_duration_seconds: int | None = None,
    measurement_timestamp_semantics: str | None = None,
    measurement_metadata_status: str | None = "provider_documented",
    measurement_metadata_managed_by: str | None = "test_fixture",
) -> tuple[Device, Sensor]:
    external_api = ExternalAPI(
        name=(
            f"us-epa-{parameter_code}-{unit_code}-"
            f"{aggregation_period_code}-{uuid4()}"
        ),
        base_url="https://example.com",
        params={},
    )
    session.add(external_api)
    session.flush()
    device = Device(
        name=f"us-epa-{parameter_code}",
        external_api_id=external_api.external_api_id,
    )
    session.add(device)
    session.flush()
    parameter = session.scalar(
        select(Parameter).where(Parameter.code == parameter_code)
    )
    unit = session.scalar(select(Unit).where(Unit.code == unit_code))
    aggregation_period = session.scalar(
        select(AggregationPeriod).where(
            AggregationPeriod.code == aggregation_period_code
        )
    )
    sensor = Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=aggregation_period.aggregation_period_id,
        hourly_concentration_provenance=hourly_concentration_provenance,
        hourly_timestamp_semantics=hourly_timestamp_semantics,
        expected_frequency_seconds=expected_frequency_seconds,
        measurement_duration_seconds=measurement_duration_seconds,
        source_aggregation_duration_seconds=source_aggregation_duration_seconds,
        measurement_timestamp_semantics=measurement_timestamp_semantics,
        measurement_metadata_status=measurement_metadata_status,
        measurement_metadata_managed_by=measurement_metadata_managed_by,
    )
    session.add(sensor)
    session.flush()
    return device, sensor


def _add_hourly_values(
    session,
    sensor: Sensor,
    completed_before: datetime,
    values: tuple[float, ...],
) -> None:
    for hours_ago, value in enumerate(values):
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=value,
                observed_at=completed_before - timedelta(hours=hours_ago + 1),
                is_valid=True,
            )
        )


def _add_subhourly_values(
    session,
    sensor: Sensor,
    hour_start: datetime,
    *,
    frequency_seconds: int,
    count: int,
    value: float = 10,
    is_valid: bool = True,
) -> None:
    for position in range(count):
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=value,
                observed_at=hour_start
                + timedelta(seconds=(position + 1) * frequency_seconds),
                is_valid=is_valid,
            )
        )


def test_database_timestamps_become_fixed_nowcast_slots() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_pm_sensor(session)
        completed_before = datetime(2025, 2, 1, 12, tzinfo=timezone.utc)
        for hours_ago, concentration in ((0, 10), (2, 20), (6, 30)):
            session.add(
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=concentration,
                    observed_at=(
                        completed_before - timedelta(hours=hours_ago + 1)
                    ),
                    is_valid=True,
                )
            )
        # This value is in the unfinished hour and must not enter slot zero.
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=999,
                observed_at=completed_before + timedelta(minutes=5),
                is_valid=True,
            )
        )
        session.flush()

        results = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before + timedelta(minutes=30),
            device_id=device.device_id,
        )
        assert len(results) == 1
        result = results[0]
        assert result.calculation.valid_observation_count == 3
        assert result.calculation.normalized_concentration == pytest.approx(
            12.22222222222222
        )
        assert result.window_started_at == completed_before - timedelta(hours=12)
        assert result.window_ended_at == completed_before
        assert result.valid_sample_count == 3
        assert result.nowcast_hourly_input_eligibility is (
            NowCastHourlyInputEligibility.ELIGIBLE
        )
        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == sensor.sensor_id
    finally:
        session.rollback()
        session.close()


def test_zero_row_sensor_reports_source_absence_before_metadata_limits() -> None:
    session = SessionLocal()
    try:
        device, _ = _create_pm_sensor(
            session,
            aggregation_period_code="1h",
            hourly_concentration_provenance=None,
            hourly_timestamp_semantics=None,
            measurement_metadata_status=None,
            measurement_metadata_managed_by=None,
        )
        completed_before = datetime(2025, 2, 1, 12, tzinfo=timezone.utc)

        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]

        evaluation = result.candidate_sensor_evaluations[0]
        assert evaluation.exclusion_reason is ExclusionReason.MISSING_MEASUREMENTS
        assert evaluation.exclusion_reasons[0] is ExclusionReason.MISSING_MEASUREMENTS
        assert ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING in (
            evaluation.exclusion_reasons
        )
        assert evaluation.valid_sample_count == 0
        assert evaluation.valid_hourly_slot_count == 0
        assert result.calculation.exclusion_reason is (
            ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM
        )
    finally:
        session.rollback()
        session.close()


def test_nowcast_history_uses_one_bounded_sensor_and_measurement_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_pm_sensor(session)
        first_boundary = datetime(2025, 2, 10, 12, tzinfo=timezone.utc)
        for hour_offset in range(-12, 24):
            session.add(
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=12,
                    observed_at=first_boundary + timedelta(hours=hour_offset),
                    is_valid=True,
                )
            )
        session.flush()

        retrieval_counts = {"sensors": 0, "measurements": 0}
        real_sensor_retrieval = aqi_engine.fetch_us_epa_candidate_sensors
        real_measurement_retrieval = aqi_engine.retrieve_raw_measurement_inputs

        def counted_sensor_retrieval(*args, **kwargs):
            retrieval_counts["sensors"] += 1
            return real_sensor_retrieval(*args, **kwargs)

        def counted_measurement_retrieval(*args, **kwargs):
            retrieval_counts["measurements"] += 1
            return real_measurement_retrieval(*args, **kwargs)

        monkeypatch.setattr(
            aqi_engine,
            "fetch_us_epa_candidate_sensors",
            counted_sensor_retrieval,
        )
        monkeypatch.setattr(
            aqi_engine,
            "retrieve_raw_measurement_inputs",
            counted_measurement_retrieval,
        )

        results = calculate_us_epa_aqi_history(
            session,
            product_code="us_epa.pm25.nowcast",
            start_utc=first_boundary,
            end_utc=first_boundary + timedelta(hours=24),
            current_time_utc=first_boundary + timedelta(hours=24),
            device_id=device.device_id,
        )

        assert len(results) == 24
        assert results[0].observed_at == first_boundary
        assert results[-1].observed_at == first_boundary + timedelta(hours=23)
        assert all(result.calculation.is_calculated for result in results)
        assert retrieval_counts == {"sensors": 1, "measurements": 1}
    finally:
        session.rollback()
        session.close()


def test_database_result_reports_insufficient_recent_hours() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_pm_sensor(session)
        completed_before = datetime(2025, 2, 2, 12, tzinfo=timezone.utc)
        for hours_ago, concentration in ((0, 10), (4, 20), (8, 30)):
            session.add(
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=concentration,
                    observed_at=completed_before
                    - timedelta(hours=hours_ago + 1),
                    is_valid=True,
                )
            )
        session.flush()
        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]
        assert (
            result.calculation.exclusion_reason
            is ExclusionReason.INSUFFICIENT_RECENT_HOURS
        )
        assert result.nowcast_hourly_input_eligibility is (
            NowCastHourlyInputEligibility.INSUFFICIENT_RECENT_HOURS
        )
    finally:
        session.rollback()
        session.close()


def test_unsupported_unit_and_aggregation_are_explicit() -> None:
    session = SessionLocal()
    try:
        unsupported_unit_device, unsupported_unit_sensor = _create_pm_sensor(
            session,
            unit_code="ppm",
        )
        unsupported_period_device, unsupported_period_sensor = _create_pm_sensor(
            session,
            aggregation_period_code="24h",
        )
        completed_before = datetime(2025, 2, 3, 12, tzinfo=timezone.utc)
        for sensor in (unsupported_unit_sensor, unsupported_period_sensor):
            for hours_ago in (0, 1):
                session.add(
                    Measurement(
                        sensor_id=sensor.sensor_id,
                        value=10,
                        observed_at=completed_before
                        - timedelta(hours=hours_ago + 1),
                        is_valid=True,
                    )
                )
        session.flush()
        unsupported_unit = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=unsupported_unit_device.device_id,
        )[0]
        unsupported_period = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=unsupported_period_device.device_id,
        )[0]
        assert unsupported_unit.calculation.exclusion_reason is (
            ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM
        )
        assert unsupported_unit.candidate_sensor_evaluations[
            0
        ].exclusion_reason is ExclusionReason.CONVERSION_NOT_SUPPORTED
        assert unsupported_period.calculation.exclusion_reason is (
            ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM
        )
        assert unsupported_period.candidate_sensor_evaluations[
            0
        ].exclusion_reason is ExclusionReason.EXPECTED_FREQUENCY_MISSING
    finally:
        session.rollback()
        session.close()


def test_one_minute_45_of_60_qualifies_and_unverified_hourly_is_unavailable() -> None:
    session = SessionLocal()
    try:
        one_minute_device, one_minute_sensor = _create_pm_sensor(
            session,
            aggregation_period_code="1m",
            hourly_concentration_provenance=None,
            hourly_timestamp_semantics=None,
            expected_frequency_seconds=60,
            measurement_duration_seconds=60,
            source_aggregation_duration_seconds=60,
            measurement_timestamp_semantics="interval_end",
            measurement_metadata_status="provider_documented",
        )
        unverified_device, unverified_sensor = _create_pm_sensor(
            session,
            hourly_concentration_provenance=None,
        )
        ownerless_device, ownerless_sensor = _create_pm_sensor(
            session,
            measurement_metadata_managed_by=None,
        )
        completed_before = datetime(2025, 2, 4, 12, tzinfo=timezone.utc)
        _add_subhourly_values(
            session,
            one_minute_sensor,
            completed_before - timedelta(hours=1),
            frequency_seconds=60,
            count=45,
        )
        _add_subhourly_values(
            session,
            one_minute_sensor,
            completed_before - timedelta(hours=2),
            frequency_seconds=60,
            count=45,
        )
        _add_hourly_values(session, unverified_sensor, completed_before, (10, 11))
        _add_hourly_values(session, ownerless_sensor, completed_before, (10, 11))
        session.flush()

        one_minute = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=one_minute_device.device_id,
        )[0]
        unverified = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=unverified_device.device_id,
        )[0]
        ownerless = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=ownerless_device.device_id,
        )[0]

        assert one_minute.selected_sensor is not None
        assert one_minute.calculation.is_calculated
        assert one_minute.valid_hourly_slot_count == 2
        assert one_minute.candidate_sensor_evaluations[
            0
        ].hourly_inputs[0].required_valid_observation_count == 45
        assert unverified.selected_sensor is None
        assert unverified.calculation.exclusion_reason is (
            ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM
        )
        assert unverified.candidate_sensor_evaluations[
            0
        ].exclusion_reason is (
            ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING
        )
        assert ownerless.selected_sensor is None
        assert ownerless.candidate_sensor_evaluations[
            0
        ].exclusion_reason is (
            ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING
        )
    finally:
        session.rollback()
        session.close()


def test_two_minute_stream_qualifies_at_23_of_30_without_provider_branch() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_pm_sensor(
            session,
            aggregation_period_code="2m",
            hourly_concentration_provenance=None,
            hourly_timestamp_semantics=None,
        )
        purpleair_api = session.scalar(
            select(ExternalAPI).where(ExternalAPI.name == "PurpleAir")
        )
        if purpleair_api is None:
            purpleair_api = ExternalAPI(
                name="PurpleAir",
                base_url="https://api.purpleair.com/v1/sensors",
                params={},
            )
            session.add(purpleair_api)
            session.flush()
        device.external_api_id = purpleair_api.external_api_id
        sensor.expected_frequency_seconds = 120
        sensor.measurement_duration_seconds = 120
        sensor.source_aggregation_duration_seconds = 120
        sensor.measurement_timestamp_semantics = "provider_received_at"
        sensor.measurement_metadata_status = "provider_documented"
        sensor.measurement_metadata_managed_by = "purpleair_importer"
        completed_before = datetime(2026, 7, 30, 18, tzinfo=timezone.utc)
        _add_subhourly_values(
            session,
            sensor,
            completed_before - timedelta(hours=1),
            frequency_seconds=120,
            count=23,
            value=10,
        )
        _add_subhourly_values(
            session,
            sensor,
            completed_before - timedelta(hours=2),
            frequency_seconds=120,
            count=23,
            value=12,
        )
        session.flush()

        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]

        assert result.selected_sensor is not None
        assert result.calculation.is_calculated
        assert result.valid_hourly_slot_count == 2
        latest_hour = result.candidate_sensor_evaluations[0].hourly_inputs[0]
        assert latest_hour.expected_observation_count == 30
        assert latest_hour.required_valid_observation_count == 23
        assert latest_hour.valid_observation_count == 23
    finally:
        session.rollback()
        session.close()


def test_multiple_sensor_streams_produce_one_deterministically_selected_device_result() -> None:
    session = SessionLocal()
    try:
        device, first_sensor = _create_pm_sensor(session)
        second_sensor = Sensor(
            device_id=device.device_id,
            parameter_id=first_sensor.parameter_id,
            unit_id=first_sensor.unit_id,
            aggregation_period_id=first_sensor.aggregation_period_id,
            hourly_concentration_provenance="provider_reported_hourly_average",
            hourly_timestamp_semantics="hour_start",
            measurement_metadata_status="provider_documented",
            measurement_metadata_managed_by="test_fixture",
        )
        session.add(second_sensor)
        session.flush()
        completed_before = datetime(2025, 2, 5, 12, tzinfo=timezone.utc)
        _add_hourly_values(session, first_sensor, completed_before, (100, 100))
        _add_hourly_values(session, second_sensor, completed_before, (10, 10, 10))
        session.flush()

        results = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )

        assert len(results) == 1
        result = results[0]
        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == second_sensor.sensor_id
        assert result.calculation.normalized_concentration == 10
        assert len(result.candidate_sensor_evaluations) == 2
        assert result.valid_hourly_slot_count == 3
    finally:
        session.rollback()
        session.close()


def test_equal_sensor_streams_use_lowest_sensor_id_tie_breaker() -> None:
    session = SessionLocal()
    try:
        device, first_sensor = _create_pm_sensor(session)
        second_sensor = Sensor(
            device_id=device.device_id,
            parameter_id=first_sensor.parameter_id,
            unit_id=first_sensor.unit_id,
            aggregation_period_id=first_sensor.aggregation_period_id,
            hourly_concentration_provenance="provider_reported_hourly_average",
            hourly_timestamp_semantics="hour_start",
            measurement_metadata_status="provider_documented",
            measurement_metadata_managed_by="test_fixture",
        )
        session.add(second_sensor)
        session.flush()
        completed_before = datetime(2025, 2, 6, 12, tzinfo=timezone.utc)
        _add_hourly_values(session, first_sensor, completed_before, (10, 10))
        _add_hourly_values(session, second_sensor, completed_before, (20, 20))
        session.flush()

        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]
        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == first_sensor.sensor_id
        assert result.calculation.normalized_concentration == 10
    finally:
        session.rollback()
        session.close()


def test_equal_slot_counts_prefer_more_complete_recent_hours() -> None:
    session = SessionLocal()
    try:
        device, first_sensor = _create_pm_sensor(session)
        second_sensor = Sensor(
            device_id=device.device_id,
            parameter_id=first_sensor.parameter_id,
            unit_id=first_sensor.unit_id,
            aggregation_period_id=first_sensor.aggregation_period_id,
            hourly_concentration_provenance="provider_reported_hourly_average",
            hourly_timestamp_semantics="hour_start",
            measurement_metadata_status="provider_documented",
            measurement_metadata_managed_by="test_fixture",
        )
        session.add(second_sensor)
        session.flush()
        completed_before = datetime(2025, 2, 6, 18, tzinfo=timezone.utc)
        for hours_ago in (1, 5, 6):
            session.add(
                Measurement(
                    sensor_id=first_sensor.sensor_id,
                    value=100,
                    observed_at=completed_before - timedelta(hours=hours_ago),
                    is_valid=True,
                )
            )
        for hours_ago in (1, 2, 7):
            session.add(
                Measurement(
                    sensor_id=second_sensor.sensor_id,
                    value=10,
                    observed_at=completed_before - timedelta(hours=hours_ago),
                    is_valid=True,
                )
            )
        session.flush()

        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]

        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == second_sensor.sensor_id
        assert result.valid_hourly_slot_count == 3
        assert result.valid_recent_hourly_slot_count == 2
    finally:
        session.rollback()
        session.close()


def test_incomplete_subhourly_hour_remains_a_missing_nowcast_position() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_pm_sensor(
            session,
            aggregation_period_code="2m",
            hourly_concentration_provenance=None,
            hourly_timestamp_semantics=None,
            expected_frequency_seconds=120,
            measurement_duration_seconds=120,
            source_aggregation_duration_seconds=120,
            measurement_timestamp_semantics="interval_end",
            measurement_metadata_status="provider_documented",
        )
        completed_before = datetime(2025, 2, 7, 12, tzinfo=timezone.utc)
        _add_subhourly_values(
            session,
            sensor,
            completed_before - timedelta(hours=1),
            frequency_seconds=120,
            count=22,
            value=999,
        )
        _add_subhourly_values(
            session,
            sensor,
            completed_before - timedelta(hours=2),
            frequency_seconds=120,
            count=23,
            value=10,
        )
        _add_subhourly_values(
            session,
            sensor,
            completed_before - timedelta(hours=3),
            frequency_seconds=120,
            count=23,
            value=30,
        )
        session.flush()

        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]

        evaluation = result.candidate_sensor_evaluations[0]
        assert evaluation.hourly_concentrations[:3] == (None, 10, 30)
        assert result.calculation.is_calculated
        assert result.nowcast_hourly_input_eligibility is (
            NowCastHourlyInputEligibility.ELIGIBLE
        )
        assert result.calculation.normalized_concentration == pytest.approx(
            16.666666666666668
        )
        assert evaluation.hourly_inputs[0].valid_observation_count == 22
        assert evaluation.hourly_inputs[0].exclusion_reason is (
            ExclusionReason.HOURLY_COMPLETENESS_NOT_MET
        )
    finally:
        session.rollback()
        session.close()


def test_equivalent_two_minute_streams_are_provider_neutral() -> None:
    session = SessionLocal()
    try:
        devices_and_sensors = [
            _create_pm_sensor(
                session,
                aggregation_period_code="2m",
                hourly_concentration_provenance=None,
                hourly_timestamp_semantics=None,
                expected_frequency_seconds=120,
                measurement_duration_seconds=120,
                source_aggregation_duration_seconds=120,
                measurement_timestamp_semantics="provider_received_at",
                measurement_metadata_status="provider_documented",
            )
            for _ in range(2)
        ]
        completed_before = datetime(2025, 2, 8, 12, tzinfo=timezone.utc)
        for _, sensor in devices_and_sensors:
            for hours_ago in (1, 2):
                _add_subhourly_values(
                    session,
                    sensor,
                    completed_before - timedelta(hours=hours_ago),
                    frequency_seconds=120,
                    count=23,
                    value=14,
                )
        session.flush()

        results = [
            calculate_latest_us_epa_aqi(
                session,
                product_code="us_epa.pm25.nowcast",
                reference_time_utc=completed_before,
                current_time_utc=completed_before,
                device_id=device.device_id,
            )[0]
            for device, _ in devices_and_sensors
        ]

        assert results[0].calculation.numeric_value == results[1].calculation.numeric_value
        first_hour = results[0].candidate_sensor_evaluations[0].hourly_inputs[0]
        second_hour = results[1].candidate_sensor_evaluations[0].hourly_inputs[0]
        assert first_hour.expected_observation_count == second_hour.expected_observation_count
        assert first_hour.required_valid_observation_count == second_hour.required_valid_observation_count
        assert first_hour.hourly_concentration == second_hour.hourly_concentration
    finally:
        session.rollback()
        session.close()


def test_two_minute_pm10_enters_nowcast_through_same_completeness_engine() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_pm_sensor(
            session,
            parameter_code="pm10",
            aggregation_period_code="2m",
            hourly_concentration_provenance=None,
            hourly_timestamp_semantics=None,
            expected_frequency_seconds=120,
            measurement_duration_seconds=120,
            source_aggregation_duration_seconds=120,
            measurement_timestamp_semantics="interval_end",
            measurement_metadata_status="provider_documented",
        )
        completed_before = datetime(2025, 2, 9, 12, tzinfo=timezone.utc)
        for hours_ago in (1, 2):
            _add_subhourly_values(
                session,
                sensor,
                completed_before - timedelta(hours=hours_ago),
                frequency_seconds=120,
                count=23,
                value=100,
            )
        session.flush()

        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm10.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]

        assert result.calculation.is_calculated
        assert result.calculation.numeric_value == 73
        assert result.candidate_sensor_evaluations[0].hourly_inputs[
            0
        ].required_valid_observation_count == 23
    finally:
        session.rollback()
        session.close()


def test_multiple_ineligible_stream_reasons_do_not_control_device_reason_by_id() -> None:
    session = SessionLocal()
    try:
        device, unsupported_unit_sensor = _create_pm_sensor(
            session,
            unit_code="ppm",
        )
        one_minute_period = session.scalar(
            select(AggregationPeriod).where(AggregationPeriod.code == "1m")
        )
        supported_unit = session.scalar(
            select(Unit).where(Unit.code == "ug_m3")
        )
        missing_frequency_sensor = Sensor(
            device_id=device.device_id,
            parameter_id=unsupported_unit_sensor.parameter_id,
            unit_id=supported_unit.unit_id,
            aggregation_period_id=one_minute_period.aggregation_period_id,
        )
        session.add(missing_frequency_sensor)
        session.flush()
        completed_before = datetime(2025, 2, 10, 12, tzinfo=timezone.utc)
        _add_hourly_values(
            session,
            unsupported_unit_sensor,
            completed_before,
            (10, 10),
        )
        session.flush()

        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]

        assert result.calculation.exclusion_reason is (
            ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM
        )
        reasons = {
            evaluation.exclusion_reason
            for evaluation in result.candidate_sensor_evaluations
        }
        assert reasons == {
            ExclusionReason.CONVERSION_NOT_SUPPORTED,
            ExclusionReason.MISSING_MEASUREMENTS,
        }
    finally:
        session.rollback()
        session.close()


def test_provider_hour_end_values_normalize_to_the_represented_hours() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_pm_sensor(
            session,
            hourly_timestamp_semantics="hour_end",
        )
        completed_before = datetime(2025, 2, 11, 12, tzinfo=timezone.utc)
        newest = Measurement(
            sensor_id=sensor.sensor_id,
            value=10,
            observed_at=completed_before,
            is_valid=True,
        )
        previous = Measurement(
            sensor_id=sensor.sensor_id,
            value=20,
            observed_at=completed_before - timedelta(hours=1),
            is_valid=True,
        )
        session.add_all((newest, previous))
        session.flush()

        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]

        hourly_inputs = result.candidate_sensor_evaluations[0].hourly_inputs
        assert result.calculation.is_calculated
        assert hourly_inputs[0].interval_started_at == (
            completed_before - timedelta(hours=1)
        )
        assert hourly_inputs[0].hourly_concentration == 10
        assert hourly_inputs[0].measurement_ids == (newest.measurement_id,)
        assert hourly_inputs[1].interval_started_at == (
            completed_before - timedelta(hours=2)
        )
        assert hourly_inputs[1].hourly_concentration == 20
        assert hourly_inputs[1].measurement_ids == (previous.measurement_id,)
    finally:
        session.rollback()
        session.close()


def test_provider_hourly_duplicate_records_are_rejected_not_averaged() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_pm_sensor(session)
        completed_before = datetime(2025, 2, 12, 12, tzinfo=timezone.utc)
        latest_hour_start = completed_before - timedelta(hours=1)
        exact = Measurement(
            sensor_id=sensor.sensor_id,
            value=10,
            observed_at=latest_hour_start,
            is_valid=True,
        )
        drifted_duplicate = Measurement(
            sensor_id=sensor.sensor_id,
            value=100,
            observed_at=latest_hour_start + timedelta(minutes=5),
            is_valid=True,
        )
        session.add_all((exact, drifted_duplicate))
        _add_hourly_values(
            session,
            sensor,
            completed_before - timedelta(hours=1),
            (15, 15),
        )
        session.flush()

        result = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=completed_before,
            current_time_utc=completed_before,
            device_id=device.device_id,
        )[0]

        evaluation = result.candidate_sensor_evaluations[0]
        duplicate_hour = evaluation.hourly_inputs[0]
        assert result.calculation.is_calculated
        assert evaluation.hourly_concentrations[:3] == (None, 15, 15)
        assert duplicate_hour.exclusion_reason is (
            ExclusionReason.DUPLICATE_OBSERVATION_INTERVAL
        )
        assert duplicate_hour.hourly_concentration is None
        assert duplicate_hour.measurement_ids == ()
        assert duplicate_hour.duplicate_measurement_ids == (
            drifted_duplicate.measurement_id,
        )
        assert duplicate_hour.off_frequency_measurement_ids == (
            drifted_duplicate.measurement_id,
        )
        assert duplicate_hour.audit_flags == (
            HourlyCompletenessAuditFlag.DUPLICATE_OBSERVATION_INTERVAL,
            HourlyCompletenessAuditFlag.OFF_FREQUENCY_OBSERVATIONS,
        )
        assert exact.measurement_id not in result.measurement_ids
    finally:
        session.rollback()
        session.close()


def test_equivalent_one_minute_streams_are_provider_neutral() -> None:
    session = SessionLocal()
    try:
        devices_and_sensors = [
            _create_pm_sensor(
                session,
                aggregation_period_code="1m",
                hourly_concentration_provenance=None,
                hourly_timestamp_semantics=None,
                expected_frequency_seconds=60,
                measurement_duration_seconds=60,
                source_aggregation_duration_seconds=60,
                measurement_timestamp_semantics="interval_end",
                measurement_metadata_status="provider_documented",
            )
            for _ in range(2)
        ]
        provider_names = ("Provider Alpha", "Provider Beta")
        for provider_name, (device, _) in zip(
            provider_names,
            devices_and_sensors,
            strict=True,
        ):
            external_api = session.get(ExternalAPI, device.external_api_id)
            assert external_api is not None
            external_api.name = provider_name

        completed_before = datetime(2025, 2, 13, 12, tzinfo=timezone.utc)
        for _, sensor in devices_and_sensors:
            for hours_ago in (1, 2):
                _add_subhourly_values(
                    session,
                    sensor,
                    completed_before - timedelta(hours=hours_ago),
                    frequency_seconds=60,
                    count=45,
                    value=18,
                )
        session.flush()

        results = [
            calculate_latest_us_epa_aqi(
                session,
                product_code="us_epa.pm25.nowcast",
                reference_time_utc=completed_before,
                current_time_utc=completed_before,
                device_id=device.device_id,
            )[0]
            for device, _ in devices_and_sensors
        ]
        first_evaluation = results[0].candidate_sensor_evaluations[0]
        second_evaluation = results[1].candidate_sensor_evaluations[0]
        first_hour = first_evaluation.hourly_inputs[0]
        second_hour = second_evaluation.hourly_inputs[0]

        assert provider_names[0] != provider_names[1]
        assert results[0].calculation.numeric_value == (
            results[1].calculation.numeric_value
        )
        assert first_hour.expected_observation_count == 60
        assert second_hour.expected_observation_count == 60
        assert first_hour.required_valid_observation_count == 45
        assert second_hour.required_valid_observation_count == 45
        assert first_hour.hourly_concentration == 18
        assert second_hour.hourly_concentration == 18
        assert first_evaluation.hourly_concentrations == (
            second_evaluation.hourly_concentrations
        )
    finally:
        session.rollback()
        session.close()
