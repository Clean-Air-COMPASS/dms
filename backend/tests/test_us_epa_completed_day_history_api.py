from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

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


def _create_sensor(
    session,
    *,
    parameter_code: str = "pm25",
    timezone_name: str | None = "America/Los_Angeles",
    manual_source_name: str | None = None,
) -> tuple[Device, Sensor]:
    external_api = ExternalAPI(
        name=f"history-api-{uuid4()}",
        base_url="https://example.com",
        params={},
    )
    session.add(external_api)
    session.flush()
    device = Device(
        name=f"history-api-device-{uuid4()}",
        external_api_id=external_api.external_api_id,
        manual_data_source_name=manual_source_name,
        timezone=timezone_name,
    )
    session.add(device)
    session.flush()
    parameter = session.scalar(
        select(Parameter).where(Parameter.code == parameter_code)
    )
    unit = session.scalar(select(Unit).where(Unit.code == "ug_m3"))
    hourly = session.scalar(
        select(AggregationPeriod).where(AggregationPeriod.code == "1h")
    )
    sensor = Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=hourly.aggregation_period_id,
        hourly_concentration_provenance="provider_reported_hourly_average",
        hourly_timestamp_semantics="hour_start",
        measurement_metadata_status="provider_documented",
        measurement_metadata_managed_by="test_fixture",
    )
    session.add(sensor)
    session.flush()
    return device, sensor


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


def _remove_test_devices(session, devices: list[Device]) -> None:
    """Remove committed API-test rows so the shared SQLite fixture stays small."""
    external_api_ids = {device.external_api_id for device in devices}
    for device in devices:
        sensors = session.scalars(
            select(Sensor).where(Sensor.device_id == device.device_id)
        ).all()
        for sensor in sensors:
            session.execute(
                delete(Measurement).where(
                    Measurement.sensor_id == sensor.sensor_id
                )
            )
            session.delete(sensor)
        session.delete(device)
    session.flush()
    for external_api_id in external_api_ids:
        external_api = session.get(ExternalAPI, external_api_id)
        if external_api is not None:
            session.delete(external_api)
    session.commit()


def test_history_summary_is_compact_gap_complete_and_counted() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_sensor(session)
        _add_provider_hours(
            session,
            sensor,
            datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
            18,
            9.1,
        )
        session.commit()
        response = TestClient(app).get(
            "/air-quality-index/us_epa/history",
            params={
                "product_code": "us_epa.pm25.completed_day",
                "start_local_date": "2025-02-01",
                "end_local_date": "2025-02-02",
                "device_id": device.device_id,
            },
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["detail"] == "summary"
        assert body["requested_day_count"] == 2
        assert body["returned_device_count"] == 1
        assert body["returned_result_count"] == 2
        assert body["calculated_result_count"] == 1
        assert body["unavailable_result_count"] == 1
        assert body["returned_result_count"] == (
            body["calculated_result_count"]
            + body["unavailable_result_count"]
        )
        assert body["maximum_supported_day_count"] == 366
        series = body["device_series"][0]
        assert series["device_timezone"] == "America/Los_Angeles"
        assert [item["represented_local_date"] for item in series["results"]] == [
            "2025-02-01",
            "2025-02-02",
        ]
        calculated, unavailable = series["results"]
        assert calculated["calculation_status"] == "calculated"
        assert calculated["valid_hour_count"] == 18
        assert calculated["required_valid_hour_count"] == 18
        assert calculated["numeric_value"] == 51
        assert unavailable["calculation_status"] == "unavailable"
        assert unavailable["expected_hour_count"] == 24
        assert unavailable["valid_hour_count"] == 0
        assert "candidate_sensor_evaluations" not in calculated
        assert "measurement_ids" not in calculated
        assert "methodology_references" not in body
        assert "limitations" not in body
    finally:
        _remove_test_devices(session, [device])
        session.close()


def test_history_full_includes_date_specific_audit_contract() -> None:
    session = SessionLocal()
    try:
        device, sensor = _create_sensor(session)
        _add_provider_hours(
            session,
            sensor,
            datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
            18,
            9.1,
        )
        session.commit()
        response = TestClient(app).get(
            "/air-quality-index/us_epa/history",
            params={
                "product_code": "us_epa.pm25.completed_day",
                "start_local_date": "2025-02-01",
                "end_local_date": "2025-02-01",
                "device_id": device.device_id,
                "detail": "full",
            },
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["detail"] == "full"
        assert body["methodology_references"]
        assert body["limitations"]
        result = body["device_series"][0]["results"][0]
        assert result["selected_sensor"]["sensor_id"] == sensor.sensor_id
        assert result["selected_sensor"]["input_unit_code"] == "ug_m3"
        assert len(result["measurement_ids"]) == 18
        assert result["reference_basis"]
        assert result["application_provenance"]
        assert len(result["candidate_sensor_evaluations"]) == 1
        candidate = result["candidate_sensor_evaluations"][0]
        assert candidate["sensor_id"] == sensor.sensor_id
        assert candidate["input_unit_code"] == "ug_m3"
        assert len(candidate["hourly_inputs"]) == 24
        assert len(candidate["measurement_ids"]) == 18
    finally:
        _remove_test_devices(session, [device])
        session.close()


def test_history_validation_rejects_invalid_requests_without_rewriting_them() -> None:
    client = TestClient(app)
    url = "/air-quality-index/us_epa/history"
    valid = {
        "product_code": "us_epa.pm25.completed_day",
        "start_local_date": "2024-01-01",
        "end_local_date": "2024-12-31",
    }
    assert client.get(url, params=valid).status_code == 200
    assert client.get(
        url,
        params={**valid, "end_local_date": "2025-01-01"},
    ).status_code == 400
    assert client.get(
        url,
        params={**valid, "start_local_date": "2025-01-02", "end_local_date": "2025-01-01"},
    ).status_code == 400
    assert client.get(
        url,
        params={**valid, "product_code": "us_epa.pm25.nowcast"},
    ).status_code == 400
    assert client.get(
        url,
        params={**valid, "product_code": "unknown"},
    ).status_code == 400
    assert client.get(url, params={**valid, "detail": "audit"}).status_code == 422
    assert client.get(url, params={**valid, "start_local_date": "bad"}).status_code == 422
    assert client.get(url, params={"product_code": valid["product_code"]}).status_code == 422
    assert client.get(
        url,
        params={**valid, "bbox": "3,49,2,48"},
    ).status_code == 400


def test_history_invalid_timezone_retains_each_requested_date() -> None:
    session = SessionLocal()
    try:
        device, _sensor = _create_sensor(
            session,
            timezone_name="Not/A_Timezone",
        )
        session.commit()
        response = TestClient(app).get(
            "/air-quality-index/us_epa/history",
            params={
                "product_code": "us_epa.pm25.completed_day",
                "start_local_date": "2025-02-01",
                "end_local_date": "2025-02-02",
                "device_id": device.device_id,
            },
        )
        assert response.status_code == 200
        results = response.json()["device_series"][0]["results"]
        assert [item["represented_local_date"] for item in results] == [
            "2025-02-01",
            "2025-02-02",
        ]
        assert all(item["utc_window_started_at"] is None for item in results)
        assert all(item["expected_hour_count"] is None for item in results)
        assert all(
            "device_timezone_invalid" in item["blocking_reasons"]
            for item in results
        )
    finally:
        _remove_test_devices(session, [device])
        session.close()


def test_history_preserves_manual_other_source_filtering() -> None:
    session = SessionLocal()
    try:
        manual_device, _sensor = _create_sensor(
            session,
            manual_source_name="Community upload",
        )
        provider_device, _sensor = _create_sensor(session)
        session.commit()
        response = TestClient(app).get(
            "/air-quality-index/us_epa/history",
            params={
                "product_code": "us_epa.pm25.completed_day",
                "start_local_date": "2025-02-01",
                "end_local_date": "2025-02-01",
                "external_api_name": "Other",
                "device_id": manual_device.device_id,
            },
        )
        provider_response = TestClient(app).get(
            "/air-quality-index/us_epa/history",
            params={
                "product_code": "us_epa.pm25.completed_day",
                "start_local_date": "2025-02-01",
                "end_local_date": "2025-02-01",
                "external_api_name": "Other",
                "device_id": provider_device.device_id,
            },
        )
        assert response.status_code == 200
        assert provider_response.status_code == 200
        series = response.json()["device_series"]
        assert [item["device_id"] for item in series] == [manual_device.device_id]
        assert series[0]["source_name"] == "Other"
        assert provider_response.json()["device_series"] == []
    finally:
        _remove_test_devices(session, [manual_device, provider_device])
        session.close()
