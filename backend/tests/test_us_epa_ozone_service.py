from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
from models import AggregationPeriod, Device, ExternalAPI, Measurement, Parameter, Sensor, Unit
from services.air_quality_index.domain import ExclusionReason
from services.us_epa_ozone_service import (
    OZONE_SENSOR_SELECTION_RULE,
    calculate_latest_us_epa_ozone_aqi,
    calculate_us_epa_ozone_history,
)
import services.us_epa_ozone_service as ozone_service


WINDOW_END = datetime(2025, 2, 2, 12, tzinfo=timezone.utc)
WINDOW_START = WINDOW_END - timedelta(hours=8)


def _create_device(session) -> Device:
    external_api = ExternalAPI(
        name=f"ozone-service-{uuid4()}",
        base_url="https://example.com",
        params={},
    )
    session.add(external_api)
    session.flush()
    device = Device(
        name=f"ozone-device-{uuid4()}",
        external_api_id=external_api.external_api_id,
    )
    session.add(device)
    session.flush()
    return device


def _add_provider_hourly_sensor(
    session,
    device: Device,
    *,
    unit_code: str = "ppm",
    metadata_is_valid: bool = True,
) -> Sensor:
    parameter = session.scalar(select(Parameter).where(Parameter.code == "o3"))
    unit = session.scalar(select(Unit).where(Unit.code == unit_code))
    aggregation = session.scalar(
        select(AggregationPeriod).where(AggregationPeriod.code == "1h")
    )
    sensor = Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=aggregation.aggregation_period_id,
        hourly_concentration_provenance=(
            "provider_reported_hourly_average" if metadata_is_valid else None
        ),
        hourly_timestamp_semantics="hour_start" if metadata_is_valid else None,
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


def _add_hourly_values(session, sensor: Sensor, values: tuple[float, ...]) -> None:
    for hour_index, value in enumerate(values):
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=value,
                observed_at=WINDOW_START + timedelta(hours=hour_index),
                is_valid=True,
            )
        )


def test_ozone_history_uses_one_bounded_sensor_and_measurement_retrieval(
    monkeypatch,
) -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(session, device)
        first_boundary = WINDOW_END
        for hour_offset in range(-8, 23):
            session.add(
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=0.050,
                    observed_at=first_boundary + timedelta(hours=hour_offset),
                    is_valid=True,
                )
            )
        session.flush()

        retrieval_counts = {"sensors": 0, "measurements": 0}
        real_sensor_retrieval = ozone_service.fetch_us_epa_candidate_sensors
        real_measurement_retrieval = ozone_service.retrieve_raw_measurement_inputs

        def counted_sensor_retrieval(*args, **kwargs):
            retrieval_counts["sensors"] += 1
            return real_sensor_retrieval(*args, **kwargs)

        def counted_measurement_retrieval(*args, **kwargs):
            retrieval_counts["measurements"] += 1
            return real_measurement_retrieval(*args, **kwargs)

        monkeypatch.setattr(
            ozone_service,
            "fetch_us_epa_candidate_sensors",
            counted_sensor_retrieval,
        )
        monkeypatch.setattr(
            ozone_service,
            "retrieve_raw_measurement_inputs",
            counted_measurement_retrieval,
        )

        results = calculate_us_epa_ozone_history(
            session,
            product_code="us_epa.o3.latest",
            start_utc=first_boundary,
            end_utc=first_boundary + timedelta(hours=24),
            current_time_utc=first_boundary + timedelta(hours=24),
            device_id=device.device_id,
        )

        assert len(results) == 24
        assert results[0].observed_at == first_boundary
        assert results[-1].observed_at == first_boundary + timedelta(hours=23)
        assert all(result.calculation.selected_candidate is not None for result in results)
        assert retrieval_counts == {"sensors": 1, "measurements": 1}
    finally:
        session.rollback()
        session.close()


def test_service_uses_fixed_window_and_selects_one_hour_candidate() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(session, device)
        _add_hourly_values(
            session,
            sensor,
            (0.050, 0.050, 0.405, 0.050, 0.050, 0.050, 0.050, 0.050),
        )
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=0.604,
                observed_at=WINDOW_END,
                is_valid=True,
            )
        )
        session.flush()

        result = calculate_latest_us_epa_ozone_aqi(
            session,
            product_code="us_epa.o3.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END + timedelta(minutes=30),
            device_id=device.device_id,
        )[0]

        assert result.window_started_at == WINDOW_START
        assert result.window_ended_at == WINDOW_END
        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == sensor.sensor_id
        assert result.calculation.selected_aggregation_period == "1h"
        assert result.calculation.selected_candidate is not None
        assert result.calculation.selected_candidate.numeric_value == 301
        assert WINDOW_END not in {
            hourly.interval_started_at
            for hourly in result.candidate_sensor_evaluations[0].hourly_inputs
        }
    finally:
        session.rollback()
        session.close()


def test_sensor_ranking_never_uses_aqi_severity() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        lower_id_sensor = _add_provider_hourly_sensor(session, device)
        higher_id_sensor = _add_provider_hourly_sensor(session, device)
        _add_hourly_values(session, lower_id_sensor, (0.060,) * 8)
        _add_hourly_values(session, higher_id_sensor, (0.405,) * 8)
        session.flush()

        result = calculate_latest_us_epa_ozone_aqi(
            session,
            product_code="us_epa.o3.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=device.device_id,
        )[0]

        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == lower_id_sensor.sensor_id
        assert result.calculation.selected_candidate is not None
        assert result.calculation.selected_candidate.numeric_value == 67
        assert result.selected_sensor_reason == OZONE_SENSOR_SELECTION_RULE
    finally:
        session.rollback()
        session.close()


def test_sensor_ranking_prefers_complete_coverage_over_a_higher_aqi() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        partial_high_aqi_sensor = _add_provider_hourly_sensor(session, device)
        complete_lower_aqi_sensor = _add_provider_hourly_sensor(session, device)
        _add_hourly_values(
            session,
            partial_high_aqi_sensor,
            (0.050, 0.050, 0.405, 0.050, 0.050, 0.050),
        )
        _add_hourly_values(session, complete_lower_aqi_sensor, (0.060,) * 8)
        session.flush()

        result = calculate_latest_us_epa_ozone_aqi(
            session,
            product_code="us_epa.o3.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=device.device_id,
        )[0]

        partial_evaluation = next(
            evaluation
            for evaluation in result.candidate_sensor_evaluations
            if evaluation.sensor.sensor_id == partial_high_aqi_sensor.sensor_id
        )
        assert partial_evaluation.calculation.selected_candidate is not None
        assert partial_evaluation.calculation.selected_candidate.numeric_value == 301
        assert partial_evaluation.valid_hour_count == 6

        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == complete_lower_aqi_sensor.sensor_id
        assert result.calculation.selected_candidate is not None
        assert result.calculation.selected_candidate.numeric_value == 67
        assert result.selected_sensor_reason == OZONE_SENSOR_SELECTION_RULE
    finally:
        session.rollback()
        session.close()


def test_mass_unit_and_unverified_hourly_streams_are_explicitly_ineligible() -> None:
    session = SessionLocal()
    try:
        mass_device = _create_device(session)
        mass_sensor = _add_provider_hourly_sensor(session, mass_device, unit_code="ug_m3")
        unverified_device = _create_device(session)
        unverified_sensor = _add_provider_hourly_sensor(
            session, unverified_device, metadata_is_valid=False
        )
        ownerless_device = _create_device(session)
        ownerless_sensor = _add_provider_hourly_sensor(session, ownerless_device)
        ownerless_sensor.measurement_metadata_managed_by = None
        _add_hourly_values(session, mass_sensor, (120.0,) * 8)
        _add_hourly_values(session, unverified_sensor, (0.078,) * 8)
        _add_hourly_values(session, ownerless_sensor, (0.078,) * 8)
        session.flush()

        mass_result = calculate_latest_us_epa_ozone_aqi(
            session,
            product_code="us_epa.o3.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=mass_device.device_id,
        )[0]
        unverified_result = calculate_latest_us_epa_ozone_aqi(
            session,
            product_code="us_epa.o3.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=unverified_device.device_id,
        )[0]
        ownerless_result = calculate_latest_us_epa_ozone_aqi(
            session,
            product_code="us_epa.o3.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=ownerless_device.device_id,
        )[0]

        assert mass_result.selected_sensor is None
        assert mass_result.candidate_sensor_evaluations[0].metadata_exclusion_reason is ExclusionReason.CONVERSION_NOT_SUPPORTED
        assert unverified_result.selected_sensor is None
        assert unverified_result.candidate_sensor_evaluations[0].metadata_exclusion_reason is ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING
        assert ownerless_result.selected_sensor is None
        assert ownerless_result.candidate_sensor_evaluations[0].metadata_exclusion_reason is ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING
    finally:
        session.rollback()
        session.close()


def test_latest_api_exposes_both_candidates_and_provenance() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(session, device, unit_code="ppb")
        _add_hourly_values(session, sensor, (78.53333,) * 8)
        session.commit()

        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.o3.latest",
                "device_id": device.device_id,
                "until": WINDOW_END.isoformat(),
            },
        )
        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["product_kind"] == "latest_window"
        result = payload["results"][0]
        assert result["selected_aggregation_period"] == "8h"
        selected_candidate = result["ozone_8_hour_candidate"]
        assert result["numeric_value"] == selected_candidate["numeric_value"] == 126
        assert result["category_code"] == selected_candidate["category_code"]
        assert result["category_label"] == selected_candidate["category_label"]
        assert result["normalized_concentration"] == selected_candidate["normalized_concentration"]
        assert result["normalized_unit"] == selected_candidate["normalized_unit"] == "ppm"
        assert result["preprocessed_concentration"] == selected_candidate["preprocessed_concentration"]
        assert result["expected_observation_count"] == selected_candidate["expected_hour_count"] == 8
        assert result["valid_observation_count"] == selected_candidate["valid_hour_count"] == 8
        assert result["valid_hourly_slot_count"] == 8
        assert result["missing_hourly_slot_count"] == 0
        assert result["window_started_at"] == selected_candidate["interval_started_at"]
        assert result["window_ended_at"] == selected_candidate["interval_ended_at"]
        assert result["coverage_status"] == selected_candidate["coverage_status"] == "complete"
        assert result["coverage"]["coverage_status"] == "complete"
        assert result["ozone_1_hour_candidate"]["candidate_status"] == "not_applicable"
        assert result["sensor_id"] == sensor.sensor_id
        assert result["selected_sensor_reason"] == OZONE_SENSOR_SELECTION_RULE
        assert len(result["ozone_candidate_sensor_evaluations"]) == 1
        assert result["candidate_sensor_evaluations"] == []
        assert result["completed_day_candidate_sensor_evaluations"] == []
    finally:
        session.close()


def test_latest_api_top_level_fields_follow_one_hour_selected_candidate() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(session, device)
        _add_hourly_values(
            session,
            sensor,
            (0.050, 0.050, 0.405, 0.050, 0.050, 0.050, 0.050, 0.050),
        )
        session.commit()

        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.o3.latest",
                "device_id": device.device_id,
                "until": WINDOW_END.isoformat(),
            },
        )
        assert response.status_code == 200, response.json()
        result = response.json()["results"][0]
        selected_candidate = result["ozone_1_hour_candidate"]
        eight_hour_candidate = result["ozone_8_hour_candidate"]

        assert result["selected_aggregation_period"] == "1h"
        assert result["numeric_value"] == selected_candidate["numeric_value"] == 301
        assert result["category_code"] == selected_candidate["category_code"]
        assert result["category_label"] == selected_candidate["category_label"]
        assert result["normalized_concentration"] == selected_candidate["normalized_concentration"]
        assert result["normalized_unit"] == selected_candidate["normalized_unit"] == "ppm"
        assert result["preprocessed_concentration"] == selected_candidate["preprocessed_concentration"]
        assert result["expected_observation_count"] == selected_candidate["expected_hour_count"] == 1
        assert result["valid_observation_count"] == selected_candidate["valid_hour_count"] == 1
        assert result["valid_hourly_slot_count"] == 1
        assert result["missing_hourly_slot_count"] == 0
        assert result["window_started_at"] == selected_candidate["interval_started_at"]
        assert result["window_ended_at"] == selected_candidate["interval_ended_at"]
        assert result["observed_at"] == selected_candidate["interval_ended_at"]
        assert result["coverage_status"] == selected_candidate["coverage_status"] == "complete"
        assert result["coverage"]["coverage_status"] == "complete"
        assert len(result["measurement_ids"]) == 1
        assert result["valid_sample_count"] == 1

        assert eight_hour_candidate["expected_hour_count"] == 8
        assert eight_hour_candidate["valid_hour_count"] == 8
        assert eight_hour_candidate["interval_started_at"] == WINDOW_START.isoformat().replace("+00:00", "Z")
        assert eight_hour_candidate["interval_ended_at"] == WINDOW_END.isoformat().replace("+00:00", "Z")
        assert result["window_started_at"] != eight_hour_candidate["interval_started_at"]
    finally:
        session.close()


def test_latest_api_has_no_selected_result_fields_when_no_candidate_is_available() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(session, device, unit_code="ug_m3")
        _add_hourly_values(session, sensor, (120.0,) * 8)
        session.commit()

        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.o3.latest",
                "device_id": device.device_id,
                "until": WINDOW_END.isoformat(),
            },
        )
        assert response.status_code == 200, response.json()
        result = response.json()["results"][0]

        assert result["selected_aggregation_period"] is None
        for field_name in (
            "numeric_value",
            "category_code",
            "category_label",
            "normalized_concentration",
            "normalized_unit",
            "preprocessed_concentration",
            "sensor_id",
            "external_sensor_id",
            "expected_observation_count",
            "valid_observation_count",
            "valid_hourly_slot_count",
            "missing_hourly_slot_count",
            "window_started_at",
            "window_ended_at",
        ):
            assert result[field_name] is None
        assert result["coverage_status"] == "none"
        assert result["coverage"]["coverage_status"] == "none"
        assert result["measurement_ids"] == []
        assert result["valid_sample_count"] == 0
        assert result["ozone_8_hour_candidate"]["interval_started_at"] is not None
        assert result["ozone_1_hour_candidate"]["interval_ended_at"] is not None
    finally:
        session.close()
