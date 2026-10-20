from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from api.main import app
from db import SessionLocal
from models import AggregationPeriod, Device, ExternalAPI, Measurement, Parameter, Sensor, Unit
from services.air_quality_index.domain import ExclusionReason
from services.us_epa_gas_service import (
    GAS_SENSOR_SELECTION_RULE,
    calculate_latest_us_epa_carbon_monoxide_aqi,
    calculate_latest_us_epa_nitrogen_dioxide_aqi,
    calculate_latest_us_epa_sulfur_dioxide_aqi,
    calculate_us_epa_gas_history,
)
import services.us_epa_gas_service as gas_service


WINDOW_END = datetime(2025, 2, 2, 12, tzinfo=timezone.utc)
WINDOW_START = WINDOW_END - timedelta(hours=8)
SO2_WINDOW_START = WINDOW_END - timedelta(hours=24)


def _create_device(session, external_api: ExternalAPI | None = None) -> Device:
    if external_api is None:
        external_api = ExternalAPI(
            name=f"gas-service-{uuid4()}",
            base_url="https://example.com",
            params={},
        )
        session.add(external_api)
        session.flush()
    device = Device(
        name=f"gas-device-{uuid4()}",
        external_api_id=external_api.external_api_id,
    )
    session.add(device)
    session.flush()
    return device


def _add_provider_hourly_sensor(
    session,
    device: Device,
    parameter_code: str,
    *,
    unit_code: str,
    metadata_is_valid: bool = True,
) -> Sensor:
    parameter = session.scalar(
        select(Parameter).where(Parameter.code == parameter_code)
    )
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
        measurement_metadata_managed_by=("test_fixture" if metadata_is_valid else None),
    )
    session.add(sensor)
    session.flush()
    return sensor


def _add_hourly_values(
    session,
    sensor: Sensor,
    values: tuple[float, ...],
    *,
    window_start: datetime = WINDOW_START,
) -> None:
    for hour_index, value in enumerate(values):
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=value,
                observed_at=window_start + timedelta(hours=hour_index),
                is_valid=True,
            )
        )


def test_gas_history_uses_one_bounded_sensor_and_measurement_retrieval(
    monkeypatch,
) -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(
            session, device, "no2", unit_code="ppb"
        )
        first_boundary = WINDOW_END
        _add_hourly_values(
            session,
            sensor,
            (53.0,) * 24,
            window_start=first_boundary - timedelta(hours=1),
        )
        session.flush()

        retrieval_counts = {"sensors": 0, "measurements": 0}
        real_sensor_retrieval = gas_service.fetch_us_epa_candidate_sensors
        real_measurement_retrieval = gas_service.retrieve_raw_measurement_inputs

        def counted_sensor_retrieval(*args, **kwargs):
            retrieval_counts["sensors"] += 1
            return real_sensor_retrieval(*args, **kwargs)

        def counted_measurement_retrieval(*args, **kwargs):
            retrieval_counts["measurements"] += 1
            return real_measurement_retrieval(*args, **kwargs)

        monkeypatch.setattr(
            gas_service,
            "fetch_us_epa_candidate_sensors",
            counted_sensor_retrieval,
        )
        monkeypatch.setattr(
            gas_service,
            "retrieve_raw_measurement_inputs",
            counted_measurement_retrieval,
        )

        results = calculate_us_epa_gas_history(
            session,
            product_code="us_epa.no2.latest",
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


def test_carbon_monoxide_service_uses_fixed_latest_completed_window():
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(
            session, device, "co", unit_code="ppm"
        )
        _add_hourly_values(session, sensor, (4.4,) * 8)
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=50.4,
                observed_at=WINDOW_END,
                is_valid=True,
            )
        )
        session.flush()

        result = calculate_latest_us_epa_carbon_monoxide_aqi(
            session,
            product_code="us_epa.co.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END + timedelta(minutes=30),
            device_id=device.device_id,
        )[0]

        assert result.window_started_at == WINDOW_START
        assert result.window_ended_at == WINDOW_END
        assert result.calculation.calculation is not None
        assert result.calculation.calculation.numeric_value == 50
        assert result.calculation.valid_hour_count == 8
    finally:
        session.rollback()
        session.close()


def test_carbon_monoxide_sensor_selection_uses_coverage_not_aqi_magnitude():
    session = SessionLocal()
    try:
        device = _create_device(session)
        partial_high_sensor = _add_provider_hourly_sensor(
            session, device, "co", unit_code="ppm"
        )
        complete_low_sensor = _add_provider_hourly_sensor(
            session, device, "co", unit_code="ppm"
        )
        _add_hourly_values(session, partial_high_sensor, (30.4,) * 6)
        _add_hourly_values(session, complete_low_sensor, (4.4,) * 8)
        session.flush()

        result = calculate_latest_us_epa_carbon_monoxide_aqi(
            session,
            product_code="us_epa.co.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=device.device_id,
        )[0]

        assert result.selected_sensor is not None
        assert result.selected_sensor.sensor_id == complete_low_sensor.sensor_id
        assert result.calculation.calculation is not None
        assert result.calculation.calculation.numeric_value == 50
        assert result.selected_sensor_reason == GAS_SENSOR_SELECTION_RULE
    finally:
        session.rollback()
        session.close()


def test_carbon_monoxide_mass_unit_is_explicitly_ineligible():
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(
            session, device, "co", unit_code="ug_m3"
        )
        _add_hourly_values(session, sensor, (5000.0,) * 8)
        session.flush()

        result = calculate_latest_us_epa_carbon_monoxide_aqi(
            session,
            product_code="us_epa.co.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=device.device_id,
        )[0]

        assert result.selected_sensor is None
        assert result.candidate_sensor_evaluations[0].metadata_exclusion_reason is (
            ExclusionReason.CONVERSION_NOT_SUPPORTED
        )
    finally:
        session.rollback()
        session.close()


def test_zero_row_gas_sensor_reports_source_absence_separately() -> None:
    session = SessionLocal()
    try:
        device = _create_device(session)
        _add_provider_hourly_sensor(session, device, "co", unit_code="ppm")

        result = calculate_latest_us_epa_carbon_monoxide_aqi(
            session,
            product_code="us_epa.co.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=device.device_id,
        )[0]

        evaluation = result.candidate_sensor_evaluations[0]
        assert evaluation.blocking_reasons[0] is ExclusionReason.MISSING_MEASUREMENTS
        assert ExclusionReason.ROLLING_8_HOUR_COMPLETENESS_NOT_MET in (
            evaluation.blocking_reasons
        )
        assert evaluation.valid_sample_count == 0
        assert evaluation.valid_hour_count == 0
        assert result.blocking_reasons[0] is ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM
        assert ExclusionReason.MISSING_MEASUREMENTS in result.blocking_reasons
    finally:
        session.rollback()
        session.close()


def test_carbon_monoxide_latest_api_serializes_selected_result_and_provenance():
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(
            session, device, "co", unit_code="ppb"
        )
        _add_hourly_values(session, sensor, (4400.0,) * 6)
        session.commit()

        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.co.latest",
                "device_id": device.device_id,
                "until": WINDOW_END.isoformat(),
            },
        )
        assert response.status_code == 200, response.json()
        result = response.json()["results"][0]
        assert result["numeric_value"] == 50
        assert result["normalized_unit"] == "ppm"
        assert result["preprocessed_concentration"] == 4.4
        assert result["coverage_status"] == "partial"
        assert result["exclusion_reason"] is None
        assert result["valid_observation_count"] == 6
        assert result["expected_observation_count"] == 8
        assert result["selected_aggregation_period"] == "8h"
        assert result["selected_calculation_code"] == (
            "co_latest_completed_8_hour_window"
        )
        assert result["sensor_id"] == sensor.sensor_id
        assert len(result["gas_candidate_sensor_evaluations"]) == 1
    finally:
        session.close()


def test_nitrogen_dioxide_uses_only_the_latest_completed_hour():
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(
            session, device, "no2", unit_code="ppb"
        )
        latest_hour_start = WINDOW_END - timedelta(hours=1)
        _add_hourly_values(
            session,
            sensor,
            (100.9,),
            window_start=latest_hour_start,
        )
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=2049.0,
                observed_at=WINDOW_END,
                is_valid=True,
            )
        )
        session.flush()

        result = calculate_latest_us_epa_nitrogen_dioxide_aqi(
            session,
            product_code="us_epa.no2.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END + timedelta(minutes=30),
            device_id=device.device_id,
        )[0]

        assert result.window_started_at == latest_hour_start
        assert result.window_ended_at == WINDOW_END
        assert result.calculation.calculation is not None
        assert result.calculation.calculation.preprocessed_concentration == 100.0
        assert result.calculation.calculation.numeric_value == 100
        assert result.measurement_ids
    finally:
        session.rollback()
        session.close()


def test_nitrogen_dioxide_latest_api_exposes_one_hour_selected_contract():
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(
            session, device, "no2", unit_code="ppm"
        )
        _add_hourly_values(
            session,
            sensor,
            (0.053,),
            window_start=WINDOW_END - timedelta(hours=1),
        )
        session.commit()

        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.no2.latest",
                "device_id": device.device_id,
                "until": WINDOW_END.isoformat(),
            },
        )
        assert response.status_code == 200, response.json()
        result = response.json()["results"][0]
        assert result["numeric_value"] == 50
        assert result["normalized_unit"] == "ppb"
        assert result["preprocessed_concentration"] == 53.0
        assert result["selected_aggregation_period"] == "1h"
        assert result["selected_calculation_code"] == "no2_latest_completed_hour"
        assert result["expected_observation_count"] == 1
        assert result["valid_observation_count"] == 1
        assert result["sensor_id"] == sensor.sensor_id
    finally:
        session.close()


def test_sulfur_dioxide_service_selects_high_24_hour_basis():
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(
            session, device, "so2", unit_code="ppb"
        )
        _add_hourly_values(
            session,
            sensor,
            (305.0,) * 24,
            window_start=SO2_WINDOW_START,
        )
        session.flush()

        result = calculate_latest_us_epa_sulfur_dioxide_aqi(
            session,
            product_code="us_epa.so2.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=device.device_id,
        )[0]

        assert result.selected_sensor is not None
        assert result.calculation.selected_aggregation_period == "24h"
        assert result.calculation.selected_calculation_code == "so2_24_hour_high"
        assert result.calculation.selected_candidate is not None
        assert result.calculation.selected_candidate.numeric_value == 201
        assert len(result.measurement_ids) == 24
    finally:
        session.rollback()
        session.close()


def test_sulfur_dioxide_service_caps_high_hour_with_low_24_hour_mean():
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(
            session, device, "so2", unit_code="ppb"
        )
        _add_hourly_values(
            session,
            sensor,
            (100.0,) * 23 + (305.0,),
            window_start=SO2_WINDOW_START,
        )
        session.flush()

        result = calculate_latest_us_epa_sulfur_dioxide_aqi(
            session,
            product_code="us_epa.so2.latest",
            reference_time_utc=WINDOW_END,
            current_time_utc=WINDOW_END,
            device_id=device.device_id,
        )[0]

        assert result.calculation.selected_calculation_code == (
            "so2_1_hour_capped_at_200"
        )
        assert result.calculation.selected_candidate is not None
        assert result.calculation.selected_candidate.numeric_value == 200
        assert len(result.measurement_ids) == 1
    finally:
        session.rollback()
        session.close()


def test_sulfur_dioxide_latest_api_keeps_top_fields_consistent_with_selected_candidate():
    session = SessionLocal()
    try:
        device = _create_device(session)
        sensor = _add_provider_hourly_sensor(
            session, device, "so2", unit_code="ppm"
        )
        _add_hourly_values(
            session,
            sensor,
            (0.100,) * 23 + (0.305,),
            window_start=SO2_WINDOW_START,
        )
        session.commit()

        response = TestClient(app).get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.so2.latest",
                "device_id": device.device_id,
                "until": WINDOW_END.isoformat(),
            },
        )
        assert response.status_code == 200, response.json()
        result = response.json()["results"][0]
        selected_candidate = result["so2_1_hour_candidate"]
        assert result["selected_calculation_code"] == (
            "so2_1_hour_capped_at_200"
        )
        assert result["selected_aggregation_period"] == "1h"
        assert result["numeric_value"] == selected_candidate["numeric_value"] == 200
        assert result["normalized_concentration"] == (
            selected_candidate["normalized_concentration"]
        )
        assert result["preprocessed_concentration"] == (
            selected_candidate["preprocessed_concentration"]
        )
        assert result["window_started_at"] == selected_candidate["interval_started_at"]
        assert result["window_ended_at"] == selected_candidate["interval_ended_at"]
        assert len(result["measurement_ids"]) == 1
        assert result["so2_24_hour_candidate"]["candidate_status"] == (
            "not_applicable"
        )
        assert len(result["so2_candidate_sensor_evaluations"]) == 1
        assert result["exclusion_reason"] is None
    finally:
        session.close()


def test_unavailable_gas_results_keep_selected_fields_empty_and_candidate_diagnostics() -> None:
    session = SessionLocal()
    try:
        carbon_monoxide_device = _create_device(session)
        carbon_monoxide_sensor = _add_provider_hourly_sensor(
            session,
            carbon_monoxide_device,
            "co",
            unit_code="ug_m3",
        )
        sulfur_dioxide_device = _create_device(session)
        sulfur_dioxide_sensor = _add_provider_hourly_sensor(
            session,
            sulfur_dioxide_device,
            "so2",
            unit_code="ug_m3",
        )
        _add_hourly_values(session, carbon_monoxide_sensor, (4400.0,) * 8)
        _add_hourly_values(
            session,
            sulfur_dioxide_sensor,
            (75.0,) * 24,
            window_start=SO2_WINDOW_START,
        )
        session.commit()

        client = TestClient(app)
        carbon_monoxide_result = client.get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.co.latest",
                "device_id": carbon_monoxide_device.device_id,
                "until": WINDOW_END.isoformat(),
            },
        ).json()["results"][0]
        sulfur_dioxide_result = client.get(
            "/air-quality-index/us_epa/latest",
            params={
                "product_code": "us_epa.so2.latest",
                "device_id": sulfur_dioxide_device.device_id,
                "until": WINDOW_END.isoformat(),
            },
        ).json()["results"][0]

        for result in (carbon_monoxide_result, sulfur_dioxide_result):
            assert result["calculation_status"] == "unavailable"
            assert result["coverage_status"] == "none"
            assert result["coverage"]["coverage_status"] == "none"
            for field_name in (
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
                "selected_aggregation_period",
                "selected_calculation_code",
            ):
                assert result[field_name] is None
            assert result["measurement_ids"] == []

        assert "conversion_not_supported" in carbon_monoxide_result[
            "gas_candidate_sensor_evaluations"
        ][0]["blocking_reasons"]
        assert "conversion_not_supported" in sulfur_dioxide_result[
            "so2_candidate_sensor_evaluations"
        ][0]["blocking_reasons"]
    finally:
        session.close()


def test_sulfur_dioxide_service_batches_metadata_and_measurement_retrieval(
    monkeypatch,
    record_property,
):
    session = SessionLocal()
    try:
        external_api = ExternalAPI(
            name=f"gas-performance-{uuid4()}",
            base_url="https://example.com",
            params={},
        )
        session.add(external_api)
        session.flush()
        for _ in range(3):
            device = _create_device(session, external_api)
            sensor = _add_provider_hourly_sensor(
                session, device, "so2", unit_code="ppb"
            )
            _add_hourly_values(
                session,
                sensor,
                (75.0,) * 24,
                window_start=SO2_WINDOW_START,
            )
        session.flush()

        metadata_retrieval_count = 0
        measurement_retrieval_count = 0
        real_metadata_retrieval = gas_service.fetch_us_epa_candidate_sensors
        real_measurement_retrieval = gas_service.retrieve_raw_measurement_inputs

        def counted_metadata_retrieval(*args, **kwargs):
            nonlocal metadata_retrieval_count
            metadata_retrieval_count += 1
            return real_metadata_retrieval(*args, **kwargs)

        def counted_measurement_retrieval(*args, **kwargs):
            nonlocal measurement_retrieval_count
            measurement_retrieval_count += 1
            return real_measurement_retrieval(*args, **kwargs)

        monkeypatch.setattr(
            gas_service,
            "fetch_us_epa_candidate_sensors",
            counted_metadata_retrieval,
        )
        monkeypatch.setattr(
            gas_service,
            "retrieve_raw_measurement_inputs",
            counted_measurement_retrieval,
        )
        select_statement_count = 0

        def count_select_statements(
            connection,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ):
            del connection, cursor, parameters, context, executemany
            nonlocal select_statement_count
            if statement.lstrip().upper().startswith("SELECT"):
                select_statement_count += 1

        database_engine = session.get_bind()
        event.listen(
            database_engine,
            "before_cursor_execute",
            count_select_statements,
        )
        try:
            started_at = perf_counter()
            results = calculate_latest_us_epa_sulfur_dioxide_aqi(
                session,
                product_code="us_epa.so2.latest",
                reference_time_utc=WINDOW_END,
                current_time_utc=WINDOW_END,
                external_api_name=external_api.name,
                limit=10,
            )
            elapsed_seconds = perf_counter() - started_at
        finally:
            event.remove(
                database_engine,
                "before_cursor_execute",
                count_select_statements,
            )

        record_property("service_seconds", elapsed_seconds)
        record_property("measurement_row_count", 3 * 24)
        record_property("select_statement_count", select_statement_count)
        assert metadata_retrieval_count == 1
        assert measurement_retrieval_count == 1
        assert select_statement_count == 2
        assert len(results) == 3
        assert elapsed_seconds < 1.0
    finally:
        session.rollback()
        session.close()
