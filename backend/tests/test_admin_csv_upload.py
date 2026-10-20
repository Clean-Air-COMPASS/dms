from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.main import app
from db import SessionLocal
import models

client = TestClient(app)


def _ensure_external_api(session) -> int:
    existing = session.execute(
        select(models.ExternalAPI).where(models.ExternalAPI.name == "CSV Test API")
    ).scalar_one_or_none()
    if existing:
        return existing.external_api_id
    row = models.ExternalAPI(
        name="CSV Test API",
        base_url="https://example.test",
        description="test",
        params={},
    )
    session.add(row)
    session.flush()
    return row.external_api_id


def _ensure_pm25_parameter_id(session) -> int:
    parameter = session.execute(
        select(models.Parameter).where(models.Parameter.code == "pm25")
    ).scalar_one()
    return parameter.parameter_id


def test_csv_upload_uses_device_timezone_for_naive_datetime(admin_auth_headers):
    sensor_id: int
    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)
        parameter_id = _ensure_pm25_parameter_id(session)

        device = models.Device(
            name="CSV TZ Device",
            external_api_id=external_api_id,
            timezone="America/Los_Angeles",
        )
        session.add(device)
        session.flush()

        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=parameter_id,
        )
        session.add(sensor)
        session.commit()
        sensor_id = sensor.sensor_id

    csv_text = "internalsensorid,datetime,value\n" f"{sensor_id},2026-01-15T00:00:00,12.5\n"
    response = client.post(
        "/admin/imports/upload-csv",
        files={"file": ("test.csv", csv_text, "text/csv")},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["total_records"] == 1
    assert body["inserted_records"] == 1
    assert body["failed_records"] == 0

    with SessionLocal() as session:
        measurement = session.execute(
            select(models.Measurement)
            .where(models.Measurement.sensor_id == sensor_id)
            .order_by(models.Measurement.measurement_id.desc())
        ).scalars().first()
        assert measurement is not None
                                                                                 
        assert measurement.observed_at.hour == 8
        assert measurement.observed_at.minute == 0


def test_csv_upload_naive_datetime_fails_when_device_timezone_missing(admin_auth_headers):
    sensor_id: int
    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)
        parameter_id = _ensure_pm25_parameter_id(session)

        device = models.Device(
            name="CSV No TZ Device",
            external_api_id=external_api_id,
            timezone=None,
        )
        session.add(device)
        session.flush()

        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=parameter_id,
        )
        session.add(sensor)
        session.commit()
        sensor_id = sensor.sensor_id

    csv_text = "internalsensorid,datetime,value\n" f"{sensor_id},2026-01-15T00:00:00,8.0\n"
    response = client.post(
        "/admin/imports/upload-csv",
        files={"file": ("test.csv", csv_text, "text/csv")},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["total_records"] == 1
    assert body["inserted_records"] == 0
    assert body["failed_records"] == 1
    assert any("device timezone is not configured" in item for item in body.get("errors", []))


def test_csv_upload_allows_unparameterized_sensor_if_sensor_exists(admin_auth_headers):
    sensor_id: int
    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)

        device = models.Device(
            name="CSV Unparameterized Device",
            external_api_id=external_api_id,
            timezone="UTC",
        )
        session.add(device)
        session.flush()

        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=None,
        )
        session.add(sensor)
        session.commit()
        sensor_id = sensor.sensor_id

    csv_text = "internalsensorid,datetime,value\n" f"{sensor_id},2026-01-15T00:00:00Z,3.0\n"
    response = client.post(
        "/admin/imports/upload-csv",
        files={"file": ("test.csv", csv_text, "text/csv")},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["total_records"] == 1
    assert body["inserted_records"] == 1
    assert body["failed_records"] == 0


def test_csv_upload_allows_multiple_sensor_ids_and_fails_unknown_sensor(admin_auth_headers):
    sensor_id_1: int
    sensor_id_2: int
    unknown_sensor_id = 99999999

    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)
        parameter_id = _ensure_pm25_parameter_id(session)

        device_1 = models.Device(
            name="CSV Mixed Sensor Device 1",
            external_api_id=external_api_id,
            timezone="UTC",
        )
        session.add(device_1)
        session.flush()
        sensor_1 = models.Sensor(device_id=device_1.device_id, parameter_id=parameter_id)
        session.add(sensor_1)

        device_2 = models.Device(
            name="CSV Mixed Sensor Device 2",
            external_api_id=external_api_id,
            timezone="UTC",
        )
        session.add(device_2)
        session.flush()
        sensor_2 = models.Sensor(device_id=device_2.device_id, parameter_id=parameter_id)
        session.add(sensor_2)

        session.commit()
        sensor_id_1 = sensor_1.sensor_id
        sensor_id_2 = sensor_2.sensor_id

    csv_text = (
        "internalsensorid,datetime,value\n"
        f"{sensor_id_1},2026-01-15T01:00:00Z,10.0\n"
        f"{unknown_sensor_id},2026-01-15T01:01:00Z,11.0\n"
        f"{sensor_id_2},2026-01-15T01:02:00Z,12.0\n"
    )
    response = client.post(
        "/admin/imports/upload-csv",
        files={"file": ("test.csv", csv_text, "text/csv")},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["total_records"] == 3
    assert body["inserted_records"] == 2
    assert body["failed_records"] == 1
    assert any("sensor not found" in item for item in body.get("errors", []))

    with SessionLocal() as session:
        m1 = session.execute(
            select(models.Measurement)
            .where(models.Measurement.sensor_id == sensor_id_1)
            .order_by(models.Measurement.measurement_id.desc())
        ).scalars().first()
        m2 = session.execute(
            select(models.Measurement)
            .where(models.Measurement.sensor_id == sensor_id_2)
            .order_by(models.Measurement.measurement_id.desc())
        ).scalars().first()
        assert m1 is not None
        assert m2 is not None


def test_csv_upload_invalid_sensor_identifier_has_a_clear_row_error(admin_auth_headers):
    csv_text = (
        "internalsensorid,datetime,value\n"
        "not-a-sensor-id,2030-01-01T00:00:00Z,12.5\n"
    )

    response = client.post(
        "/admin/imports/upload-csv",
        files={"file": ("test.csv", csv_text, "text/csv")},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["inserted_records"] == 0
    assert body["failed_records"] == 1
    assert body["errors"] == [
        "Line 2: internalsensorid must be an integer sensor ID"
    ]


def test_csv_upload_null_and_malformed_dates_remain_row_level_errors(admin_auth_headers):
    csv_text = (
        "internalsensorid,datetime,value\n"
        "1,,12.5\n"
        "1,not-a-date,8.5\n"
    )

    response = client.post(
        "/admin/imports/upload-csv",
        files={"file": ("test.csv", csv_text, "text/csv")},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["total_records"] == 2
    assert body["inserted_records"] == 0
    assert body["failed_records"] == 2
    assert body["errors"] == [
        "Line 2: datetime is required",
        "Line 3: datetime must be ISO 8601",
    ]


def test_csv_upload_rejects_oversized_file_before_any_measurement_write(
    admin_auth_headers, monkeypatch
):
    monkeypatch.setenv("COMPASSAQ_CSV_UPLOAD_MAX_BYTES", "32")
    csv_text = "internalsensorid,datetime,value\n1,2030-01-01T00:00:00Z,12.5\n"

    with SessionLocal() as session:
        before = session.scalar(select(func.count()).select_from(models.Measurement))

    response = client.post(
        "/admin/imports/upload-csv",
        files={"file": ("test.csv", csv_text, "text/csv")},
        headers=admin_auth_headers,
    )

    with SessionLocal() as session:
        after = session.scalar(select(func.count()).select_from(models.Measurement))

    assert response.status_code == 413
    assert response.json()["detail"]["error_code"] == "csv_file_too_large"
    assert after == before


def test_manual_device_add_sensor_then_upload_csv(admin_auth_headers):
    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)

                                           
    create_device_resp = client.post(
        "/admin/devices",
        json={
            "name": "Manual Device For CSV Flow",
            "external_api_id": external_api_id,
            "timezone": "UTC",
        },
        headers=admin_auth_headers,
    )
    assert create_device_resp.status_code == 200
    device_body = create_device_resp.json()
    device_id = int(device_body["device_id"])

                                                
    create_sensor_resp = client.post(
        f"/admin/devices/{device_id}/sensors",
        json={"parameter_code": "pm25", "external_sensor_id": "manual-s-1"},
        headers=admin_auth_headers,
    )
    assert create_sensor_resp.status_code == 200
    sensor_body = create_sensor_resp.json()
    sensor_id = int(sensor_body["sensor_id"])
    assert sensor_body["device_id"] == device_id
    assert sensor_body["parameter_code"] == "pm25"

                                           
    csv_text = "internalsensorid,datetime,value\n" f"{sensor_id},2026-01-15T05:00:00Z,22.4\n"
    upload_resp = client.post(
        "/admin/imports/upload-csv",
        files={"file": ("test.csv", csv_text, "text/csv")},
        headers=admin_auth_headers,
    )
    assert upload_resp.status_code == 200
    body = upload_resp.json()
    assert body["success"] is True
    assert body["total_records"] == 1
    assert body["inserted_records"] == 1
    assert body["failed_records"] == 0

                                  
    with SessionLocal() as session:
        measurement = session.execute(
            select(models.Measurement)
            .where(models.Measurement.sensor_id == sensor_id)
            .order_by(models.Measurement.measurement_id.desc())
        ).scalars().first()
        assert measurement is not None
        assert float(measurement.value) == 22.4
