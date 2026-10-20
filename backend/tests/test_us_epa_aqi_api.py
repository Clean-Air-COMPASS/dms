from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
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
from services.air_quality_index.us_epa import calculate_pm_nowcast


def _create_sensor(
    session,
    parameter_code: str,
    *,
    unit_code: str = "ug_m3",
    aggregation_period_code: str = "1h",
    expected_frequency_seconds: int | None = None,
    measurement_duration_seconds: int | None = None,
    source_aggregation_duration_seconds: int | None = None,
    measurement_timestamp_semantics: str | None = None,
    measurement_metadata_status: str | None = None,
    timezone_name: str | None = None,
) -> tuple[Device, Sensor]:
    external_api = ExternalAPI(
        name=f"us-epa-api-{uuid4()}",
        base_url="https://example.com",
        params={},
    )
    session.add(external_api)
    session.flush()
    device = Device(
        name=f"us-epa-api-{parameter_code}-{uuid4()}",
        external_api_id=external_api.external_api_id,
        timezone=timezone_name,
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
    provider_hourly = aggregation_period_code == "1h"
    sensor = Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=aggregation_period.aggregation_period_id,
        hourly_concentration_provenance=(
            "provider_reported_hourly_average" if provider_hourly else None
        ),
        hourly_timestamp_semantics="hour_start" if provider_hourly else None,
        expected_frequency_seconds=expected_frequency_seconds,
        measurement_duration_seconds=measurement_duration_seconds,
        source_aggregation_duration_seconds=source_aggregation_duration_seconds,
        measurement_timestamp_semantics=measurement_timestamp_semantics,
        measurement_metadata_status=(
            measurement_metadata_status
            or ("provider_documented" if provider_hourly else None)
        ),
        measurement_metadata_managed_by=(
            "test_fixture"
            if measurement_metadata_status or provider_hourly
            else None
        ),
    )
    session.add(sensor)
    session.flush()
    return device, sensor


def _add_completed_hour_values(
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
) -> None:
    for position in range(count):
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=10 + position,
                observed_at=hour_start
                + timedelta(seconds=(position + 1) * frequency_seconds),
                is_valid=True,
            )
        )


def _add_local_day_provider_hours(
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


def test_us_epa_metadata_exposes_nowcast_and_completed_day_products_and_sources() -> None:
    response = TestClient(app).get("/air-quality-index/standards")
    assert response.status_code == 200
    standard = next(
        item
        for item in response.json()
        if item["standard_code"] == "us_epa"
    )
    assert standard["methodology_code"] == (
        "us_epa_aqi_40_cfr_58_appendix_g"
    )
    assert standard["methodology_revision"] == "2024-05"
    assert standard["methodology_effective_date"] == "2024-05-06"
    assert [product["product_code"] for product in standard["products"]] == [
        "us_epa.pm25.nowcast",
        "us_epa.pm10.nowcast",
        "us_epa.o3.latest",
        "us_epa.co.latest",
        "us_epa.no2.latest",
        "us_epa.so2.latest",
        "us_epa.pm25.completed_day",
        "us_epa.pm10.completed_day",
    ]
    assert [
        product["is_parameter_default"] for product in standard["products"]
    ] == [True, True, True, True, True, True, False, False]
    completed_products = [
        product
        for product in standard["products"]
        if product["product_kind"] == "completed_day"
    ]
    assert {product["aggregation_display_name"] for product in completed_products} == {
        "Completed Day"
    }
    assert all(
        product["history_status"] == "available"
        for product in standard["products"]
    )
    assert {
        product["history_interval"] for product in completed_products
    } == {"represented_device_local_date"}
    assert {
        product["maximum_history_interval_count"]
        for product in completed_products
    } == {366}
    assert {
        product["maximum_history_interval_count"]
        for product in standard["products"]
        if product["product_kind"] != "completed_day"
    } == {2160}
    assert {
        reference["document_number"]
        for product in completed_products
        for reference in product["methodology_references"]
    } >= {
        "40 CFR Part 50, Appendix N",
        "40 CFR Part 50, Appendix K",
    }
    assert {
        reference["document_number"]
        for reference in standard["methodology_references"]
    } >= {
        "40 CFR Part 58, Appendix G",
        "EPA-454/B-24-002",
        "89 FR 16202",
    }
    ozone_product = next(
        product
        for product in standard["products"]
        if product["product_code"] == "us_epa.o3.latest"
    )
    assert ozone_product["display_name"] == "Ozone AQI"
    assert any(
        "official EPA reporting areas universally use one-hour ozone AQI"
        in limitation
        for limitation in ozone_product["limitations"]
    )
    carbon_monoxide_product = next(
        product
        for product in standard["products"]
        if product["product_code"] == "us_epa.co.latest"
    )
    assert carbon_monoxide_product["display_name"] == "Carbon Monoxide AQI"
    assert carbon_monoxide_product["methodology_revision"] == "1999-08"
    assert carbon_monoxide_product["methodology_effective_date"] == "1999-10-04"
    nitrogen_dioxide_product = next(
        product
        for product in standard["products"]
        if product["product_code"] == "us_epa.no2.latest"
    )
    assert nitrogen_dioxide_product["display_name"] == "Nitrogen Dioxide AQI"
    assert nitrogen_dioxide_product["methodology_revision"] == "2010-02"
    assert nitrogen_dioxide_product["methodology_effective_date"] == "2010-04-12"
    sulfur_dioxide_product = next(
        product
        for product in standard["products"]
        if product["product_code"] == "us_epa.so2.latest"
    )
    assert sulfur_dioxide_product["display_name"] == "Sulfur Dioxide AQI"
    assert sulfur_dioxide_product["methodology_revision"] == "2010-06"
    assert sulfur_dioxide_product["methodology_effective_date"] == "2010-08-23"
    assert "trailing UTC window is a CompassAQ application policy" in " ".join(
        sulfur_dioxide_product["limitations"]
    )
    assert standard["averaging_minutes"] is None
    assert standard["required_averaging_period"] is None


def test_completed_day_api_exposes_explicit_daily_contract_without_nowcast_fields() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_sensor(
            session,
            "pm25",
            timezone_name="America/Los_Angeles",
        )
        _add_local_day_provider_hours(
            session,
            sensor,
            datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
            18,
            9.1,
        )
        session.commit()
        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm25.completed_day",
                "device_id": device.device_id,
                "until": datetime(
                    2025, 2, 2, 18, tzinfo=timezone.utc
                ).isoformat(),
            },
        )
        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["product_code"] == "us_epa.pm25.completed_day"
        assert payload["product_kind"] == "completed_day"
        result = payload["results"][0]
        assert result["parameter_code"] == "pm25"
        assert result["represented_local_date"] == "2025-02-01"
        assert result["device_timezone"] == "America/Los_Angeles"
        assert result["local_day_started_at"] == "2025-02-01T00:00:00-08:00"
        assert result["local_day_ended_at"] == "2025-02-02T00:00:00-08:00"
        assert result["utc_window_started_at"] == "2025-02-01T08:00:00Z"
        assert result["utc_window_ended_at"] == "2025-02-02T08:00:00Z"
        assert result["expected_hour_count"] == 24
        assert result["valid_hour_count"] == 18
        assert result["required_valid_hour_count"] == 18
        assert result["required_completeness_fraction"] == 0.75
        assert result["achieved_completeness_fraction"] == 0.75
        assert result["daily_concentration"] == 9.1
        assert result["numeric_value"] == 51
        assert result["category_code"] == "moderate"
        assert result["expected_observation_count"] == 24
        assert result["valid_observation_count"] == 18
        assert result["valid_hourly_slot_count"] == 18
        assert result["missing_hourly_slot_count"] == 6
        assert result["window_started_at"] == result["utc_window_started_at"]
        assert result["window_ended_at"] == result["utc_window_ended_at"]
        assert result["selected_aggregation_period"] == "completed_local_day"
        assert result["selected_calculation_code"] == "pm_completed_local_day"
        assert result["sensor_id"] == sensor.sensor_id
        assert len(result["measurement_ids"]) == 18
        assert result["sensor_provenance"] == []
        assert result["candidate_sensor_evaluations"] == []
        assert result["nowcast_hourly_input_eligibility"] is None
        assert result["latest_completed_hour_eligibility_status"] is None
        assert any(
            "regulatory monitor" in limitation
            for limitation in result["limitations"]
        )
        assert result["limitations"] == payload["limitations"]
        candidate = result["completed_day_candidate_sensor_evaluations"][0]
        assert candidate["expected_hour_count"] == 24
        assert candidate["valid_hour_count"] == 18
        assert len(candidate["hourly_inputs"]) == 24
        assert candidate["blocking_reasons"] == []
        assert all(
            isinstance(reason, str)
            for reason in candidate["blocking_reasons"]
        )
    finally:
        session.close()


def test_completed_day_api_preserves_candidate_hourly_audit_flags() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_sensor(
            session,
            "pm25",
            aggregation_period_code="2m",
            expected_frequency_seconds=120,
            measurement_duration_seconds=120,
            source_aggregation_duration_seconds=120,
            measurement_timestamp_semantics="interval_end",
            measurement_metadata_status="provider_documented",
            timezone_name="America/Los_Angeles",
        )
        first_hour = datetime(2025, 2, 1, 8, tzinfo=timezone.utc)
        for hour_index in range(18):
            _add_subhourly_values(
                session,
                sensor,
                first_hour + timedelta(hours=hour_index),
                frequency_seconds=120,
                count=23,
            )
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=999,
                observed_at=first_hour + timedelta(minutes=7),
                is_valid=False,
            )
        )
        session.commit()
        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm25.completed_day",
                "device_id": device.device_id,
                "until": datetime(
                    2025, 2, 2, 18, tzinfo=timezone.utc
                ).isoformat(),
            },
        )
        assert response.status_code == 200, response.json()
        result = response.json()["results"][0]
        candidate = result["completed_day_candidate_sensor_evaluations"][0]
        assert result["calculation_status"] == "calculated"
        assert candidate["valid_hour_count"] == 18
        assert "invalid_observations_rejected" in candidate["audit_flags"]
        assert "invalid_observations_rejected" in (
            candidate["hourly_inputs"][0]["audit_flags"]
        )
        assert candidate["blocking_reasons"] == []
        assert candidate["reference_basis"]
        assert candidate["application_provenance"]
    finally:
        session.close()


def test_completed_day_api_reports_specific_timezone_failure() -> None:
    session = SessionLocal()
    try:
        device, _sensor = _create_sensor(session, "pm10", timezone_name=None)
        session.commit()
        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm10.completed_day",
                "device_id": device.device_id,
                "until": datetime(
                    2025, 2, 2, 18, tzinfo=timezone.utc
                ).isoformat(),
            },
        )
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["calculation_status"] == "unavailable"
        assert result["coverage_status"] == "none"
        for field_name in (
            "expected_observation_count",
            "valid_observation_count",
            "valid_hourly_slot_count",
            "missing_hourly_slot_count",
            "window_started_at",
            "window_ended_at",
            "selected_aggregation_period",
            "selected_calculation_code",
        ):
            assert result[field_name] is None
        assert result["exclusion_reason"] == "device_timezone_missing"
        assert result["blocking_reasons"] == [
            "no_eligible_sensor_stream",
            "device_timezone_missing",
        ]
        assert result["represented_local_date"] is None
    finally:
        session.close()


def test_completed_day_api_reports_one_below_threshold_in_plain_fields() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_sensor(
            session,
            "pm10",
            timezone_name="America/Los_Angeles",
        )
        _add_local_day_provider_hours(
            session,
            sensor,
            datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
            17,
            100,
        )
        session.commit()
        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm10.completed_day",
                "device_id": device.device_id,
                "until": datetime(
                    2025, 2, 2, 18, tzinfo=timezone.utc
                ).isoformat(),
            },
        )
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["exclusion_reason"] == "daily_completeness_not_met"
        assert result["expected_hour_count"] == 24
        assert result["valid_hour_count"] == 17
        assert result["required_valid_hour_count"] == 18
        assert result["daily_concentration"] == 100
        assert result["numeric_value"] is None
        assert result["coverage_status"] == "none"
        assert result["normalized_concentration"] is None
        assert result["normalized_unit"] is None
        assert result["preprocessed_concentration"] is None
        assert result["measurement_ids"] == []
        for field_name in (
            "expected_observation_count",
            "valid_observation_count",
            "valid_hourly_slot_count",
            "missing_hourly_slot_count",
            "window_started_at",
            "window_ended_at",
            "selected_aggregation_period",
            "selected_calculation_code",
        ):
            assert result[field_name] is None
        candidate = result["completed_day_candidate_sensor_evaluations"][0]
        assert candidate["daily_concentration"] == 100
        assert candidate["valid_hour_count"] == 17
        assert candidate["achieved_completeness_fraction"] == 17 / 24
        assert "daily_completeness_not_met" in result["blocking_reasons"]
    finally:
        session.close()


def test_completed_day_api_uses_dst_expected_hour_counts_and_boundaries() -> None:
    cases = (
        (
            datetime(2025, 3, 10, 12, tzinfo=timezone.utc),
            datetime(2025, 3, 9, 8, tzinfo=timezone.utc),
            23,
            18,
            "2025-03-10T07:00:00Z",
        ),
        (
            datetime(2025, 11, 3, 12, tzinfo=timezone.utc),
            datetime(2025, 11, 2, 7, tzinfo=timezone.utc),
            25,
            19,
            "2025-11-03T08:00:00Z",
        ),
    )
    session = SessionLocal()
    try:
        for evaluation_time, first_hour, expected_hours, required_hours, utc_end in cases:
            device, sensor = _create_sensor(
                session,
                "pm25",
                timezone_name="America/Los_Angeles",
            )
            _add_local_day_provider_hours(
                session,
                sensor,
                first_hour,
                required_hours,
                10,
            )
            session.commit()
            response = TestClient(app).get(
                "/air-quality-index/us_epa/latest",
                params={
                    "product_code": "us_epa.pm25.completed_day",
                    "device_id": device.device_id,
                    "until": evaluation_time.isoformat(),
                },
            )
            assert response.status_code == 200
            result = response.json()["results"][0]
            assert result["expected_hour_count"] == expected_hours
            assert result["required_valid_hour_count"] == required_hours
            assert result["utc_window_ended_at"] == utc_end
            hourly_inputs = result[
                "completed_day_candidate_sensor_evaluations"
            ][0]["hourly_inputs"]
            assert len(hourly_inputs) == expected_hours
            assert len(
                {hourly_input["interval_started_at"] for hourly_input in hourly_inputs}
            ) == expected_hours
    finally:
        session.close()
def test_structured_pm25_nowcast_matches_authoritative_service_path() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_sensor(session, "pm25")
        completed_before = datetime(2025, 4, 1, 12, tzinfo=timezone.utc)
        values = (35, 30, 25, 20, 15, 10, 10, 10, 10, 10, 10, 10)
        _add_completed_hour_values(
            session,
            sensor,
            completed_before,
            values,
        )
        session.commit()

        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm25.nowcast",
                "device_id": device.device_id,
                "until": completed_before.isoformat(),
            },
        )
        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["product_code"] == "us_epa.pm25.nowcast"
        assert payload["count"] == 1
        result = payload["results"][0]
        expected = calculate_pm_nowcast("pm25", values, "ug_m3")
        assert result["numeric_value"] == expected.numeric_value
        assert result["calculation_status"] == "calculated"
        assert result["coverage_status"] == "complete"
        assert result["expected_observation_count"] == 12
        assert result["valid_observation_count"] == 12
        assert result["selected_aggregation_period"] == "12h_nowcast"
        assert result["selected_calculation_code"] == "pm_nowcast"
        assert result["sensor_id"] == sensor.sensor_id
        assert result["methodology_revision"] == "2024-05"
        assert "hourly_data_quality_policy" not in result
        assert result["valid_hourly_slot_count"] == 12
        assert result["missing_hourly_slot_count"] == 0
        assert result["latest_completed_hour_input_frequency_seconds"] == 3600
        assert result["latest_completed_hour_measurement_duration_seconds"] == 3600
        assert (
            result["latest_completed_hour_source_aggregation_duration_seconds"]
            == 3600
        )
        assert (
            result["latest_completed_hour_required_completeness_fraction"]
            == 1.0
        )
        assert result["nowcast_hourly_input_eligibility"] == "eligible"
        provenance = result["sensor_provenance"][0]
        assert provenance["selected_sensor_id"] == sensor.sensor_id
        assert provenance["candidate_sensor_ids"] == [sensor.sensor_id]
        assert result["candidate_sensor_evaluations"][0][
            "valid_hourly_slot_count"
        ] == 12
        assert result["candidate_sensor_evaluations"][0][
            "source_aggregation_duration_seconds"
        ] == 3600
    finally:
        session.close()


def test_structured_pm10_nowcast_is_available() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_sensor(session, "pm10")
        completed_before = datetime(2025, 4, 2, 12, tzinfo=timezone.utc)
        _add_completed_hour_values(
            session,
            sensor,
            completed_before,
            (100,) * 12,
        )
        session.commit()
        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm10.nowcast",
                "device_id": device.device_id,
                "until": completed_before.isoformat(),
            },
        )
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["numeric_value"] == 73
        assert result["category_code"] == "moderate"
    finally:
        session.close()


def test_two_minute_completeness_metadata_serializes_23_and_22_of_30() -> None:
    session = SessionLocal()
    try:
        qualifying_device, qualifying_sensor = _create_sensor(
            session,
            "pm25",
            aggregation_period_code="2m",
            expected_frequency_seconds=120,
            measurement_duration_seconds=120,
            source_aggregation_duration_seconds=120,
            measurement_timestamp_semantics="provider_received_at",
            measurement_metadata_status="provider_documented",
        )
        incomplete_device, incomplete_sensor = _create_sensor(
            session,
            "pm25",
            aggregation_period_code="2m",
            expected_frequency_seconds=120,
            measurement_duration_seconds=120,
            source_aggregation_duration_seconds=120,
            measurement_timestamp_semantics="provider_received_at",
            measurement_metadata_status="provider_documented",
        )
        completed_before = datetime(2025, 4, 2, 12, tzinfo=timezone.utc)
        for hours_ago in (1, 2):
            _add_subhourly_values(
                session,
                qualifying_sensor,
                completed_before - timedelta(hours=hours_ago),
                frequency_seconds=120,
                count=23,
            )
        latest_hour_started_at = completed_before - timedelta(hours=1)
        session.add_all(
            (
                Measurement(
                    sensor_id=qualifying_sensor.sensor_id,
                    value=999,
                    observed_at=latest_hour_started_at + timedelta(seconds=121),
                    is_valid=True,
                ),
                Measurement(
                    sensor_id=qualifying_sensor.sensor_id,
                    value=999,
                    observed_at=latest_hour_started_at + timedelta(seconds=48 * 60),
                    is_valid=False,
                ),
            )
        )
        _add_subhourly_values(
            session,
            incomplete_sensor,
            completed_before - timedelta(hours=1),
            frequency_seconds=120,
            count=22,
        )
        session.commit()
        client = TestClient(app)
        qualifying = client.get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm25.nowcast",
                "device_id": qualifying_device.device_id,
                "until": completed_before.isoformat(),
            },
        ).json()["results"][0]
        incomplete = client.get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm25.nowcast",
                "device_id": incomplete_device.device_id,
                "until": completed_before.isoformat(),
            },
        ).json()["results"][0]

        assert qualifying["calculation_status"] == "calculated"
        assert qualifying["latest_completed_hour_input_frequency_seconds"] == 120
        assert qualifying["latest_completed_hour_input_frequency_display"] == "2 minutes"
        assert qualifying["latest_completed_hour_measurement_duration_seconds"] == 120
        assert (
            qualifying["latest_completed_hour_source_aggregation_duration_seconds"]
            == 120
        )
        assert qualifying["latest_completed_hour_target_duration_seconds"] == 3600
        assert qualifying["latest_completed_hour_expected_observation_count"] == 30
        assert qualifying["latest_completed_hour_valid_observation_count"] == 23
        assert qualifying["latest_completed_hour_required_observation_count"] == 23
        assert (
            qualifying["latest_completed_hour_required_completeness_fraction"]
            == 0.75
        )
        assert qualifying["latest_completed_hour_eligibility_status"] == "eligible"
        assert qualifying["latest_completed_hour_completeness_rule_code"] == (
            "compass_aq.us_epa_input.pm.hourly_75_percent"
        )
        assert qualifying["valid_recent_hourly_slot_count"] == 2
        assert qualifying["nowcast_hourly_input_eligibility"] == "eligible"
        candidate = qualifying["candidate_sensor_evaluations"][0]
        assert candidate["source_aggregation_duration_seconds"] == 120
        assert len(candidate["hourly_inputs"]) == 12
        assert candidate["hourly_inputs"][0][
            "source_aggregation_duration_seconds"
        ] == 120
        assert candidate["hourly_inputs"][0]["measurement_ids"]
        assert candidate["completeness_reference_basis"]
        assert candidate["application_provenance"]
        assert candidate["hourly_inputs"][0]["completeness_reference_basis"]
        assert candidate["hourly_inputs"][0]["application_provenance"]
        assert candidate["hourly_inputs"][0]["exclusion_reasons"] == []
        assert candidate["hourly_inputs"][0]["audit_flags"] == [
            "duplicate_observation_interval",
            "invalid_observations_rejected",
        ]
        assert candidate["exclusion_reasons"] == [
            "no_valid_observations",
            "hourly_completeness_not_met",
        ]
        assert candidate["audit_flags"] == [
            "duplicate_observation_interval",
            "invalid_observations_rejected",
        ]
        assert qualifying["latest_completed_hour_audit_flags"] == [
            "duplicate_observation_interval",
            "invalid_observations_rejected",
        ]
        assert candidate["metadata_is_verified_and_complete"] is True
        assert "provider_completeness_threshold" not in qualifying
        assert "hourly_data_quality_policy" not in qualifying
        assert "expected_observation_count_per_hour" not in qualifying
        assert "nowcast_eligibility_result" not in qualifying

        assert incomplete["calculation_status"] == "unavailable"
        assert incomplete["exclusion_reason"] == "no_eligible_sensor_stream"
        assert incomplete["latest_completed_hour_valid_observation_count"] == 22
        assert incomplete["latest_completed_hour_required_observation_count"] == 23
        assert incomplete["latest_completed_hour_eligibility_status"] == "ineligible"
        assert incomplete["nowcast_hourly_input_eligibility"] == "not_evaluated"
        assert incomplete["candidate_sensor_evaluations"][0][
            "hourly_inputs"
        ][0]["exclusion_reason"] == "hourly_completeness_not_met"
    finally:
        session.close()


def test_calculated_nowcast_can_report_an_incomplete_latest_hour() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_sensor(
            session,
            "pm25",
            aggregation_period_code="2m",
            expected_frequency_seconds=120,
            measurement_duration_seconds=120,
            source_aggregation_duration_seconds=120,
            measurement_timestamp_semantics="provider_received_at",
            measurement_metadata_status="provider_documented",
        )
        completed_before = datetime(2025, 4, 2, 18, tzinfo=timezone.utc)
        _add_subhourly_values(
            session,
            sensor,
            completed_before - timedelta(hours=1),
            frequency_seconds=120,
            count=22,
        )
        for hours_ago in (2, 3):
            _add_subhourly_values(
                session,
                sensor,
                completed_before - timedelta(hours=hours_ago),
                frequency_seconds=120,
                count=23,
            )
        session.commit()

        result = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm25.nowcast",
                "device_id": device.device_id,
                "until": completed_before.isoformat(),
            },
        ).json()["results"][0]

        assert result["calculation_status"] == "calculated"
        assert result["exclusion_reason"] is None
        assert result["nowcast_hourly_input_eligibility"] == "eligible"
        assert result["latest_completed_hour_eligibility_status"] == "ineligible"
        assert result["latest_completed_hour_valid_observation_count"] == 22
        assert result["latest_completed_hour_required_observation_count"] == 23
        assert result["candidate_sensor_evaluations"][0]["hourly_inputs"][0][
            "exclusion_reasons"
        ] == ["hourly_completeness_not_met"]
    finally:
        session.close()


def test_api_returns_explicit_insufficient_data_and_unsupported_unit() -> None:
    session = SessionLocal()
    try:
        incomplete_device, incomplete_sensor = _create_sensor(
            session,
            "pm25",
        )
        unsupported_device, unsupported_sensor = _create_sensor(
            session,
            "pm25",
            unit_code="ppm",
        )
        completed_before = datetime(2025, 4, 3, 12, tzinfo=timezone.utc)
        _add_completed_hour_values(
            session,
            incomplete_sensor,
            completed_before,
            (10,),
        )
        _add_completed_hour_values(
            session,
            unsupported_sensor,
            completed_before,
            (10, 11),
        )
        session.commit()
        client = TestClient(app)
        incomplete = client.get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm25.nowcast",
                "device_id": incomplete_device.device_id,
                "until": completed_before.isoformat(),
            },
        ).json()["results"][0]
        unsupported = client.get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm25.nowcast",
                "device_id": unsupported_device.device_id,
                "until": completed_before.isoformat(),
            },
        ).json()["results"][0]
        assert incomplete["calculation_status"] == "unavailable"
        assert incomplete["coverage_status"] == "none"
        assert incomplete["coverage"]["coverage_status"] == "none"
        assert incomplete["exclusion_reason"] == "insufficient_recent_hours"
        assert incomplete["normalized_concentration"] is None
        assert incomplete["normalized_unit"] is None
        assert incomplete["sensor_id"] is None
        assert incomplete["external_sensor_id"] is None
        assert (
            incomplete["nowcast_hourly_input_eligibility"]
            == "insufficient_recent_hours"
        )
        for field_name in (
            "expected_observation_count",
            "valid_observation_count",
            "valid_hourly_slot_count",
            "valid_recent_hourly_slot_count",
            "missing_hourly_slot_count",
            "window_started_at",
            "window_ended_at",
            "selected_aggregation_period",
            "selected_calculation_code",
        ):
            assert incomplete[field_name] is None
        assert incomplete["measurement_ids"] == []
        assert incomplete["valid_sample_count"] == 0
        assert incomplete["candidate_sensor_evaluations"][0][
            "valid_hourly_slot_count"
        ] == 1
        assert unsupported["calculation_status"] == "unavailable"
        assert unsupported["exclusion_reason"] == "no_eligible_sensor_stream"
        assert unsupported["nowcast_hourly_input_eligibility"] == "not_evaluated"
        assert unsupported["candidate_sensor_evaluations"][0][
            "exclusion_reason"
        ] == "conversion_not_supported"
    finally:
        session.close()


def test_api_represents_above_500_without_clamping() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_sensor(session, "pm25")
        completed_before = datetime(2025, 4, 4, 12, tzinfo=timezone.utc)
        _add_completed_hour_values(
            session,
            sensor,
            completed_before,
            (400,) * 12,
        )
        session.commit()
        result = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.pm25.nowcast",
                "device_id": device.device_id,
                "until": completed_before.isoformat(),
            },
        ).json()["results"][0]
        assert result["numeric_value"] == 649
        assert result["category_code"] == "hazardous"
        assert result["aqi_scale_status"] == "above_500"
    finally:
        session.close()


def test_removed_and_unknown_products_are_rejected() -> None:
    client = TestClient(app)
    removed = client.get(
        "/air-quality-index/us_epa/latest",
        params={"product_code": "us_epa.co.1_hour"},
    )
    unknown = client.get(
        "/air-quality-index/us_epa/latest",
        params={"product_code": "us_epa.unknown"},
    )
    assert removed.status_code == 400
    assert unknown.status_code == 400


def test_measurements_route_no_longer_calculates_us_epa_aqi() -> None:
    response = TestClient(app).get(
        "/measurements/pm25/latest",
        params={"aggregation": "aqi-nowcast"},
    )
    assert response.status_code == 400
    assert "/air-quality-index/us_epa/latest" in response.json()["detail"]
