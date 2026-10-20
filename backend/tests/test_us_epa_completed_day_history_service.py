from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
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
import services.us_epa_completed_day_service as completed_day_service
from services.air_quality_index.domain import ExclusionReason
from services.us_epa_completed_day_service import (
    calculate_latest_us_epa_completed_day_aqi,
    calculate_us_epa_completed_day_history,
)
from services.device_locations import set_device_location


def _create_device(
    session,
    *,
    timezone_name: str | None = "America/Los_Angeles",
    latitude: float | None = None,
    longitude: float | None = None,
) -> Device:
    external_api = ExternalAPI(
        name=f"history-{uuid4()}",
        base_url="https://example.com",
        params={},
    )
    session.add(external_api)
    session.flush()
    device = Device(
        name=f"history-device-{uuid4()}",
        external_api_id=external_api.external_api_id,
        timezone=timezone_name,
    )
    session.add(device)
    set_device_location(
        session, device, latitude=latitude, longitude=longitude
    )
    return device


def _add_sensor(
    session,
    device: Device,
    *,
    parameter_code: str = "pm25",
    unit_code: str = "ug_m3",
    metadata_is_valid: bool = True,
) -> Sensor:
    parameter = session.scalar(
        select(Parameter).where(Parameter.code == parameter_code)
    )
    unit = session.scalar(select(Unit).where(Unit.code == unit_code))
    hourly = session.scalar(
        select(AggregationPeriod).where(AggregationPeriod.code == "1h")
    )
    sensor = Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=hourly.aggregation_period_id,
        hourly_concentration_provenance=(
            "provider_reported_hourly_average" if metadata_is_valid else None
        ),
        hourly_timestamp_semantics=(
            "hour_start" if metadata_is_valid else None
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


def test_history_returns_one_ordered_result_for_every_device_date() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_sensor(session, device)
        _add_provider_hours(
            session,
            sensor,
            datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
            18,
            9.1,
        )
        _add_provider_hours(
            session,
            sensor,
            datetime(2025, 2, 3, 8, tzinfo=timezone.utc),
            17,
            35.5,
        )
        session.flush()

        results = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 3),
            device_id=device.device_id,
            current_time_utc=datetime(2025, 2, 5, tzinfo=timezone.utc),
        )

        assert [result.represented_local_date for result in results] == [
            date(2025, 2, 1),
            date(2025, 2, 2),
            date(2025, 2, 3),
        ]
        assert results[0].calculation is not None
        assert results[0].calculation.numeric_value == 51
        assert results[1].calculation is None
        assert ExclusionReason.NO_VALID_HOURLY_CONCENTRATIONS in (
            results[1].blocking_reasons
        )
        assert results[2].calculation is None
        assert ExclusionReason.DAILY_COMPLETENESS_NOT_MET in (
            results[2].blocking_reasons
        )
        assert len({(item.device_id, item.represented_local_date) for item in results}) == 3
    finally:
        session.rollback()
        session.close()


@pytest.mark.parametrize("timezone_name", (None, "Not/A_Timezone"))
def test_history_preserves_requested_dates_for_timezone_failures(
    timezone_name: str | None,
) -> None:
    session = SessionLocal()
    try:
        device = _create_device(session, timezone_name=timezone_name)
        _add_sensor(session, device)
        session.flush()
        results = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 2),
            device_id=device.device_id,
            current_time_utc=datetime(2025, 2, 5, tzinfo=timezone.utc),
        )
        expected_reason = (
            ExclusionReason.DEVICE_TIMEZONE_MISSING
            if timezone_name is None
            else ExclusionReason.DEVICE_TIMEZONE_INVALID
        )
        assert [item.represented_local_date for item in results] == [
            date(2025, 2, 1),
            date(2025, 2, 2),
        ]
        assert all(item.local_day_window is None for item in results)
        assert all(expected_reason in item.blocking_reasons for item in results)
    finally:
        session.rollback()
        session.close()


@pytest.mark.parametrize(
    ("sensor_options", "expected_reason"),
    (
        ({"metadata_is_valid": False}, ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING),
        ({"unit_code": "ppm"}, ExclusionReason.CONVERSION_NOT_SUPPORTED),
    ),
)
def test_history_preserves_dates_when_sensor_metadata_or_unit_is_unusable(
    sensor_options: dict,
    expected_reason: ExclusionReason,
) -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        _add_sensor(session, device, **sensor_options)
        session.flush()
        result = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 1),
            device_id=device.device_id,
            current_time_utc=datetime(2025, 2, 5, tzinfo=timezone.utc),
        )[0]
        assert result.represented_local_date == date(2025, 2, 1)
        assert result.local_day_window is not None
        assert result.local_day_window.expected_hour_count == 24
        assert expected_reason in result.blocking_reasons
    finally:
        session.rollback()
        session.close()


def test_history_selects_sensor_independently_for_each_date() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        first_sensor = _add_sensor(session, device)
        second_sensor = _add_sensor(session, device)
        first_date_start = datetime(2025, 2, 1, 8, tzinfo=timezone.utc)
        second_date_start = datetime(2025, 2, 2, 8, tzinfo=timezone.utc)
        _add_provider_hours(session, first_sensor, first_date_start, 18, 9.1)
        _add_provider_hours(session, second_sensor, first_date_start, 17, 200)
        _add_provider_hours(session, first_sensor, second_date_start, 17, 200)
        _add_provider_hours(session, second_sensor, second_date_start, 18, 35.5)
        session.flush()

        results = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 2),
            device_id=device.device_id,
            current_time_utc=datetime(2025, 2, 4, tzinfo=timezone.utc),
        )

        assert [result.selected_sensor.sensor_id for result in results] == [
            first_sensor.sensor_id,
            second_sensor.sensor_id,
        ]
        assert [result.calculation.numeric_value for result in results] == [51, 101]
        assert all(len(result.measurement_ids) == 18 for result in results)
    finally:
        session.rollback()
        session.close()


def test_current_and_future_local_dates_are_explicitly_unavailable() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        _add_sensor(session, device)
        session.flush()
        results = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 3),
            device_id=device.device_id,
            current_time_utc=datetime(2025, 2, 2, 18, tzinfo=timezone.utc),
        )
        assert results[0].local_day_window is not None
        assert ExclusionReason.COMPLETED_LOCAL_DAY_NOT_AVAILABLE not in (
            results[0].blocking_reasons
        )
        assert results[1].local_day_window is not None
        assert ExclusionReason.COMPLETED_LOCAL_DAY_NOT_AVAILABLE in (
            results[1].blocking_reasons
        )
        assert results[2].local_day_window is not None
        assert ExclusionReason.COMPLETED_LOCAL_DAY_NOT_AVAILABLE in (
            results[2].blocking_reasons
        )
    finally:
        session.rollback()
        session.close()


def test_history_uses_one_raw_measurement_retrieval(monkeypatch) -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        _add_sensor(session, device)
        session.flush()
        retrieval_count = 0
        real_retrieval = completed_day_service.retrieve_raw_measurement_inputs

        def counted_retrieval(*args, **kwargs):
            nonlocal retrieval_count
            retrieval_count += 1
            return real_retrieval(*args, **kwargs)

        monkeypatch.setattr(
            completed_day_service,
            "retrieve_raw_measurement_inputs",
            counted_retrieval,
        )
        calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 1, 1),
            end_local_date=date(2025, 1, 30),
            device_id=device.device_id,
            current_time_utc=datetime(2025, 2, 5, tzinfo=timezone.utc),
        )
        assert retrieval_count == 1
    finally:
        session.rollback()
        session.close()


def test_history_skips_measurement_retrieval_when_no_window_is_resolvable(
    monkeypatch,
) -> None:
    session = SessionLocal()
    try:
        device = _create_device(session, timezone_name=None)
        _add_sensor(session, device)
        session.flush()
        retrieval_count = 0

        def unexpected_retrieval(*args, **kwargs):
            nonlocal retrieval_count
            retrieval_count += 1
            return []

        monkeypatch.setattr(
            completed_day_service,
            "retrieve_raw_measurement_inputs",
            unexpected_retrieval,
        )
        results = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 1, 1),
            end_local_date=date(2025, 1, 30),
            device_id=device.device_id,
            current_time_utc=datetime(2025, 2, 5, tzinfo=timezone.utc),
        )
        assert len(results) == 30
        assert retrieval_count == 0
    finally:
        session.rollback()
        session.close()


def test_history_limit_applies_to_devices_without_truncating_dates() -> None:
    session = SessionLocal()
    try:
        first_device = _create_device(session)
        _add_sensor(session, first_device)
        second_device = Device(
            name=f"history-device-{uuid4()}",
            external_api_id=first_device.external_api_id,
            timezone="America/Los_Angeles",
        )
        session.add(second_device)
        session.flush()
        _add_sensor(session, second_device)
        session.flush()
        source_name = session.get(
            ExternalAPI,
            first_device.external_api_id,
        ).name
        results = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 2),
            external_api_name=source_name,
            limit=1,
            current_time_utc=datetime(2025, 2, 5, tzinfo=timezone.utc),
        )
        assert [(item.device_id, item.represented_local_date) for item in results] == [
            (min(first_device.device_id, second_device.device_id), date(2025, 2, 1)),
            (min(first_device.device_id, second_device.device_id), date(2025, 2, 2)),
        ]
    finally:
        session.rollback()
        session.close()


def test_history_reuses_external_source_and_bounding_box_filters() -> None:
    session = SessionLocal()
    try:
        device = _create_device(
            session,
            latitude=34.05,
            longitude=-118.25,
        )
        _add_sensor(session, device)
        session.flush()
        source_name = session.get(ExternalAPI, device.external_api_id).name
        matching = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 1),
            device_id=device.device_id,
            external_api_name=source_name.upper(),
            bbox=(-119, 33, -117, 35),
            current_time_utc=datetime(2025, 2, 5, tzinfo=timezone.utc),
        )
        wrong_source = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 1),
            device_id=device.device_id,
            external_api_name="different source",
            current_time_utc=datetime(2025, 2, 5, tzinfo=timezone.utc),
        )
        outside_bbox = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 1),
            device_id=device.device_id,
            bbox=(-100, 33, -99, 35),
            current_time_utc=datetime(2025, 2, 5, tzinfo=timezone.utc),
        )
        assert [item.device_id for item in matching] == [device.device_id]
        assert wrong_source == []
        assert outside_bbox == []
    finally:
        session.rollback()
        session.close()


@pytest.mark.parametrize(
    ("product_code", "parameter_code", "value"),
    (
        ("us_epa.pm25.completed_day", "pm25", 9.1),
        ("us_epa.pm10.completed_day", "pm10", 55),
    ),
)
def test_latest_and_history_use_equivalent_device_date_results(
    product_code: str,
    parameter_code: str,
    value: float,
) -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_sensor(
            session,
            device,
            parameter_code=parameter_code,
        )
        _add_provider_hours(
            session,
            sensor,
            datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
            18,
            value,
        )
        session.flush()
        evaluation_time = datetime(2025, 2, 2, 18, tzinfo=timezone.utc)
        latest = calculate_latest_us_epa_completed_day_aqi(
            session,
            product_code=product_code,
            reference_time_utc=evaluation_time,
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        history = calculate_us_epa_completed_day_history(
            session,
            product_code=product_code,
            start_local_date=date(2025, 2, 1),
            end_local_date=date(2025, 2, 1),
            current_time_utc=evaluation_time,
            device_id=device.device_id,
        )[0]
        assert history.local_day_window == latest.local_day_window
        assert history.calculation == latest.calculation
        assert history.selected_sensor == latest.selected_sensor
        assert history.measurement_ids == latest.measurement_ids
        assert history.blocking_reasons == latest.blocking_reasons
        assert history.candidate_sensor_evaluations == (
            latest.candidate_sensor_evaluations
        )
    finally:
        session.rollback()
        session.close()
