from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
import models
from services.csv_measurement_import import (
    CSV_UPLOAD_API_KEY_ENV,
    CSV_UPLOAD_MAX_BYTES_ENV,
    CSV_UPLOAD_TOO_LARGE_ERROR_CODE,
    DEFAULT_CSV_UPLOAD_MAX_BYTES,
    get_csv_upload_max_bytes,
)

client = TestClient(app)


def test_programmatic_csv_upload_default_size_limit_is_five_megabytes(monkeypatch):
    monkeypatch.delenv(CSV_UPLOAD_MAX_BYTES_ENV, raising=False)
    assert get_csv_upload_max_bytes() == DEFAULT_CSV_UPLOAD_MAX_BYTES == 5_000_000


def _ensure_external_api(session) -> int:
    existing = session.execute(
        select(models.ExternalAPI).where(models.ExternalAPI.name == "Programmatic CSV Test API")
    ).scalar_one_or_none()
    if existing:
        return existing.external_api_id
    row = models.ExternalAPI(
        name="Programmatic CSV Test API",
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


def _create_sensor(timezone_name: str = "UTC") -> int:
    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)
        parameter_id = _ensure_pm25_parameter_id(session)
        device = models.Device(
            name="Programmatic CSV Device",
            external_api_id=external_api_id,
            timezone=timezone_name,
        )
        session.add(device)
        session.flush()
        sensor = models.Sensor(device_id=device.device_id, parameter_id=parameter_id)
        session.add(sensor)
        session.commit()
        return sensor.sensor_id


def test_programmatic_csv_upload_success(monkeypatch):
    monkeypatch.setenv(CSV_UPLOAD_API_KEY_ENV, "test-upload-key")
    sensor_id = _create_sensor()
    csv_text = "internalsensorid,datetime,value\n" f"{sensor_id},2026-01-15T00:00:00Z,12.5\n"

    response = client.post(
        "/ingest/upload-csv",
        files={"file": ("upload.csv", csv_text, "text/csv")},
        headers={"X-API-Key": "test-upload-key"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["inserted_records"] == 1
    assert body["failed_records"] == 0


def test_programmatic_csv_upload_missing_api_key(monkeypatch):
    monkeypatch.setenv(CSV_UPLOAD_API_KEY_ENV, "test-upload-key")
    sensor_id = _create_sensor()
    csv_text = "internalsensorid,datetime,value\n" f"{sensor_id},2026-01-15T00:00:00Z,12.5\n"

    response = client.post(
        "/ingest/upload-csv",
        files={"file": ("upload.csv", csv_text, "text/csv")},
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "Missing X-API-Key header"


def test_programmatic_csv_upload_invalid_api_key(monkeypatch):
    monkeypatch.setenv(CSV_UPLOAD_API_KEY_ENV, "test-upload-key")
    sensor_id = _create_sensor()
    csv_text = "internalsensorid,datetime,value\n" f"{sensor_id},2026-01-15T00:00:00Z,12.5\n"

    response = client.post(
        "/ingest/upload-csv",
        files={"file": ("upload.csv", csv_text, "text/csv")},
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Invalid API key"


def test_programmatic_csv_upload_invalid_csv_format(monkeypatch):
    monkeypatch.setenv(CSV_UPLOAD_API_KEY_ENV, "test-upload-key")
    invalid_csv = "sensor_id,when,val\n1,2026-01-15T00:00:00Z,12.5\n"

    response = client.post(
        "/ingest/upload-csv",
        files={"file": ("upload.csv", invalid_csv, "text/csv")},
        headers={"X-API-Key": "test-upload-key"},
    )

    assert response.status_code == 400, response.text
    assert "missing required CSV columns" in response.json()["detail"]


def test_programmatic_csv_upload_oversized_file(monkeypatch):
    monkeypatch.setenv(CSV_UPLOAD_API_KEY_ENV, "test-upload-key")
    monkeypatch.setenv(CSV_UPLOAD_MAX_BYTES_ENV, "32")
    oversized_csv = "internalsensorid,datetime,value\n1,2026-01-15T00:00:00Z,12.5\n"

    response = client.post(
        "/ingest/upload-csv",
        files={"file": ("upload.csv", oversized_csv, "text/csv")},
        headers={"X-API-Key": "test-upload-key"},
    )

    assert response.status_code == 413, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == CSV_UPLOAD_TOO_LARGE_ERROR_CODE
    assert detail["error_context"] == {"max_bytes": 32}
    assert "Upload exceeds maximum size" in detail["message"]


def test_programmatic_csv_upload_rejects_binary_payload(monkeypatch):
    monkeypatch.setenv(CSV_UPLOAD_API_KEY_ENV, "test-upload-key")
    binary_payload = b"\x89PNG\r\n\x1a\n\x00\x00\x00IHDR\x00\x01"

    response = client.post(
        "/ingest/upload-csv",
        files={"file": ("upload.csv", binary_payload, "application/octet-stream")},
        headers={"X-API-Key": "test-upload-key"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Uploaded file must be a text-based CSV"
