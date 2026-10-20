from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
import models

client = TestClient(app)


def _ensure_external_api(session) -> int:
    existing = session.execute(
        select(models.ExternalAPI).where(models.ExternalAPI.name == "CSV Aggregation E2E API")
    ).scalar_one_or_none()
    if existing:
        return existing.external_api_id

    row = models.ExternalAPI(
        name="CSV Aggregation E2E API",
        base_url="https://example.test",
        description="test",
        params={},
    )
    session.add(row)
    session.flush()
    return row.external_api_id


def _get_aggregation_period(session, aggregation_code: str) -> models.AggregationPeriod:
    aggregation_period = session.execute(
        select(models.AggregationPeriod).where(models.AggregationPeriod.code == aggregation_code)
    ).scalar_one_or_none()
    if aggregation_period is None:
        raise AssertionError(f"Missing aggregation period '{aggregation_code}' in test database")
    return aggregation_period


def _ensure_aggregation_period(session, aggregation_code: str, display_name: str, duration_minutes: int) -> models.AggregationPeriod:
    existing = session.execute(
        select(models.AggregationPeriod).where(models.AggregationPeriod.code == aggregation_code)
    ).scalar_one_or_none()
    if existing:
        return existing

    aggregation_period = models.AggregationPeriod(
        code=aggregation_code,
        display_name=display_name,
        duration_minutes=duration_minutes,
    )
    session.add(aggregation_period)
    session.flush()
    return aggregation_period


def _ensure_parameter_aggregation_rule(
    session,
    parameter_code: str,
    aggregation_code: str,
    *,
    rounding_method: str,
    rounding_precision: int | None,
    truncation_method: str = "none",
    truncation_precision: int | None = None,
) -> None:
    parameter = session.execute(
        select(models.Parameter).where(models.Parameter.code == parameter_code)
    ).scalar_one()
    aggregation_period = _get_aggregation_period(session, aggregation_code)

    existing_rule = session.execute(
        select(models.ParameterAggregationRule).where(
            models.ParameterAggregationRule.parameter_id == parameter.parameter_id,
            models.ParameterAggregationRule.aggregation_period_id == aggregation_period.aggregation_period_id,
        )
    ).scalar_one_or_none()
    if existing_rule is not None:
        existing_rule.rounding_method = rounding_method
        existing_rule.rounding_precision = rounding_precision
        existing_rule.truncation_method = truncation_method
        existing_rule.truncation_precision = truncation_precision
        return

    session.add(
        models.ParameterAggregationRule(
            parameter_id=parameter.parameter_id,
            aggregation_period_id=aggregation_period.aggregation_period_id,
            rounding_method=rounding_method,
            rounding_precision=rounding_precision,
            truncation_method=truncation_method,
            truncation_precision=truncation_precision,
        )
    )


def _ensure_required_aggregation_setup() -> None:
    with SessionLocal() as session:
        _ensure_aggregation_period(session, "1m", "1 Minute", 1)
        _ensure_aggregation_period(session, "1h", "1 Hour", 60)
        _ensure_aggregation_period(session, "8h", "8 Hour", 8 * 60)
        _ensure_aggregation_period(session, "24h", "24 Hour", 24 * 60)

        _ensure_parameter_aggregation_rule(
            session,
            "pm25",
            "1m",
            rounding_method="round",
            rounding_precision=1,
        )
        _ensure_parameter_aggregation_rule(
            session,
            "pm25",
            "1h",
            rounding_method="none",
            rounding_precision=None,
            truncation_method="truncate",
            truncation_precision=1,
        )
        _ensure_parameter_aggregation_rule(
            session,
            "o3",
            "8h",
            rounding_method="round",
            rounding_precision=3,
        )
        _ensure_parameter_aggregation_rule(
            session,
            "pm25",
            "24h",
            rounding_method="round",
            rounding_precision=1,
        )
        session.commit()


def _create_device_with_sensor(
    admin_auth_headers: dict[str, str],
    parameter_code: str,
    aggregation_code: str,
    timezone_name: str = "UTC",
) -> tuple[int, int]:
    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)
        session.commit()

    create_device_response = client.post(
        "/admin/devices",
        json={
            "name": f"CSV aggregation device {uuid.uuid4()}",
            "external_api_id": external_api_id,
            "timezone": timezone_name,
        },
        headers=admin_auth_headers,
    )
    assert create_device_response.status_code == 200, create_device_response.text
    device_id = int(create_device_response.json()["device_id"])

    create_sensor_response = client.post(
        f"/admin/devices/{device_id}/sensors",
        json={
            "parameter_code": parameter_code,
            "aggregation_code": aggregation_code,
            "external_sensor_id": f"{parameter_code}-{aggregation_code}-{uuid.uuid4()}",
        },
        headers=admin_auth_headers,
    )
    assert create_sensor_response.status_code == 200, create_sensor_response.text
    sensor_body = create_sensor_response.json()
    assert sensor_body["aggregation_code"] == aggregation_code
    return device_id, int(sensor_body["sensor_id"])


def _upload_single_csv_row(admin_auth_headers: dict[str, str], sensor_id: int, observed_at: str, value: float) -> None:
    csv_text = f"internalsensorid,datetime,value\n{sensor_id},{observed_at},{value}\n"
    response = client.post(
        "/admin/imports/upload-csv",
        files={"file": ("aggregated.csv", csv_text, "text/csv")},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["total_records"] == 1
    assert body["inserted_records"] == 1
    assert body["failed_records"] == 0


def _latest_measurement_for_sensor(parameter_code: str, device_id: int, sensor_id: int) -> dict:
    response = client.get(
        f"/measurements/{parameter_code}/latest",
        params={"device_id": device_id},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    for row in payload:
        if row.get("sensor_id") == sensor_id:
            return row
    raise AssertionError(f"Sensor {sensor_id} not found in latest payload")


def _latest_all_measurement_for_sensor(sensor_id: int) -> dict:
    # A lower bound bypasses the map-oriented default limit. This shared test
    # database intentionally accumulates streams across backend modules.
    response = client.get(
        "/measurements/latest",
        params={"since": "2026-02-03T00:00:00Z"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    for row in payload:
        if row.get("sensor_id") == sensor_id:
            return row
    raise AssertionError(f"Sensor {sensor_id} not found in all-parameters latest payload")


def test_csv_upload_native_products_preserve_values_on_retrieval(admin_auth_headers):
    _ensure_required_aggregation_setup()

    cases = [
        {
            "parameter_code": "pm25",
            "aggregation_code": "1m",
            "observed_at": "2026-02-01T00:01:00Z",
            "uploaded_value": 12.36,
            "expected_retrieved_value": 12.36,
        },
        {
            "parameter_code": "pm25",
            "aggregation_code": "1h",
            "observed_at": "2026-02-01T01:00:00Z",
            "uploaded_value": 12.39,
            "expected_retrieved_value": 12.39,
        },
        {
            "parameter_code": "o3",
            "aggregation_code": "8h",
            "observed_at": "2026-02-01T08:00:00Z",
            "uploaded_value": 0.07856,
            "expected_retrieved_value": 0.07856,
        },
        {
            "parameter_code": "pm25",
            "aggregation_code": "24h",
            "observed_at": "2026-02-02T00:00:00Z",
            "uploaded_value": 10.45,
            "expected_retrieved_value": 10.45,
        },
    ]

    for case in cases:
        device_id, sensor_id = _create_device_with_sensor(
            admin_auth_headers=admin_auth_headers,
            parameter_code=case["parameter_code"],
            aggregation_code=case["aggregation_code"],
        )

        _upload_single_csv_row(
            admin_auth_headers=admin_auth_headers,
            sensor_id=sensor_id,
            observed_at=case["observed_at"],
            value=case["uploaded_value"],
        )

        with SessionLocal() as session:
            sensor = session.get(models.Sensor, sensor_id)
            assert sensor is not None

            aggregation_period = _get_aggregation_period(session, case["aggregation_code"])
            assert sensor.aggregation_period_id == aggregation_period.aggregation_period_id

            measurement = session.execute(
                select(models.Measurement)
                .where(models.Measurement.sensor_id == sensor_id)
                .order_by(models.Measurement.measurement_id.desc())
            ).scalars().first()
            assert measurement is not None
            assert float(measurement.value) == case["uploaded_value"]

        latest_row = _latest_measurement_for_sensor(
            parameter_code=case["parameter_code"],
            device_id=device_id,
            sensor_id=sensor_id,
        )
        assert latest_row["sensor_aggregation_period"] == case["aggregation_code"]
        assert abs(float(latest_row["value"]) - float(case["expected_retrieved_value"])) < 1e-9


def test_csv_upload_native_values_and_display_metadata_on_shared_latest_paths(admin_auth_headers):
    _ensure_required_aggregation_setup()

    device_id, sensor_id = _create_device_with_sensor(
        admin_auth_headers=admin_auth_headers,
        parameter_code="pm25",
        aggregation_code="24h",
    )

    _upload_single_csv_row(
        admin_auth_headers=admin_auth_headers,
        sensor_id=sensor_id,
        observed_at="2026-02-03T00:00:00Z",
        value=10.45,
    )

    device_sensors_response = client.get(f"/devices/{device_id}/sensors")
    assert device_sensors_response.status_code == 200, device_sensors_response.text
    device_sensors_payload = device_sensors_response.json()
    matching_sensor = next((row for row in device_sensors_payload if row["sensor_id"] == sensor_id), None)
    assert matching_sensor is not None
    assert matching_sensor["aggregation_code"] == "24h"
    assert matching_sensor["latest_value"] == 10.45
    assert matching_sensor["display_precision"] == 1

    latest_all_row = _latest_all_measurement_for_sensor(sensor_id)
    assert latest_all_row["parameter"] == "pm25"
    assert latest_all_row["value"] == 10.45
    assert latest_all_row["display_precision"] == 1
