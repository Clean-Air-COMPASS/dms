from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
import models

client = TestClient(app)


def test_creating_sensor_inherits_qc_without_creating_override_rows(admin_auth_headers):
    with SessionLocal() as session:
        device = models.Device(
            name="Synthetic QC inheritance acceptance device",
            external_api_id=_ensure_external_api(session),
        )
        session.add(device)
        session.commit()
        device_id = device.device_id

    response = client.post(
        f"/admin/devices/{device_id}/sensors",
        json={"parameter_code": "pm25", "aggregation_code": "1h"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    sensor_id = response.json()["sensor_id"]
    with SessionLocal() as session:
        assert session.scalars(
            select(models.QCRule).where(models.QCRule.sensor_id == sensor_id)
        ).all() == []

    policy_response = client.get(
        f"/admin/qc/sensors/{sensor_id}/policy", headers=admin_auth_headers
    )
    assert policy_response.status_code == 200, policy_response.text
    policy = policy_response.json()
    assert policy["overrides"] == []
    checks = {check["check_code"]: check for check in policy["checks"]}
    assert checks["min_value"]["enabled"] is True
    assert checks["max_value"]["enabled"] is True
    assert checks["baseline_drift"]["enabled"] is False
    assert all(
        check["most_specific_source"]["layer"] == "compassaq_default"
        for check in policy["checks"]
    )


def _ensure_external_api(session) -> int:
    existing = session.execute(
        select(models.ExternalAPI).where(models.ExternalAPI.name == "Sensor CRUD Test API")
    ).scalar_one_or_none()
    if existing:
        return existing.external_api_id
    row = models.ExternalAPI(
        name="Sensor CRUD Test API",
        base_url="https://example.test",
        description="test",
        params={},
    )
    session.add(row)
    session.flush()
    return row.external_api_id


def test_update_and_delete_device_sensor(admin_auth_headers):
    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)
        device = models.Device(
            name="Sensor CRUD Device",
            external_api_id=external_api_id,
            allow_updates=models.UpdatePolicy.INHERIT,
        )
        session.add(device)
        session.flush()

        pm25 = session.execute(
            select(models.Parameter).where(models.Parameter.code == "pm25")
        ).scalar_one()
        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=pm25.parameter_id,
            unit_id=pm25.default_unit_id,
            external_sensor_id="before-edit",
            expected_frequency_seconds=120,
            measurement_duration_seconds=120,
            source_aggregation_duration_seconds=120,
            measurement_timestamp_semantics="provider_received_at",
            measurement_metadata_status="provider_documented",
            measurement_metadata_managed_by="purpleair_importer",
        )
        session.add(sensor)
        session.commit()
        device_id = device.device_id
        sensor_id = sensor.sensor_id

    identity_update_response = client.put(
        f"/admin/devices/{device_id}/sensors/{sensor_id}",
        json={"parameter_code": "o3", "external_sensor_id": "after-edit"},
        headers=admin_auth_headers,
    )

    assert identity_update_response.status_code == 400
    assert "external_sensor_id is immutable" in identity_update_response.json()["detail"]

    update_response = client.put(
        f"/admin/devices/{device_id}/sensors/{sensor_id}",
        json={"parameter_code": "o3"},
        headers=admin_auth_headers,
    )

    assert update_response.status_code == 200, update_response.text
    update_body = update_response.json()
    assert update_body["sensor_id"] == sensor_id
    assert update_body["parameter_code"] == "o3"
    assert update_body["external_sensor_id"] == "before-edit"
    assert update_body["expected_frequency_seconds"] == 120
    assert update_body["measurement_duration_seconds"] == 120
    assert update_body["source_aggregation_duration_seconds"] == 120
    assert update_body["measurement_timestamp_semantics"] == "provider_received_at"
    assert update_body["measurement_metadata_status"] == "provider_documented"
    assert update_body["measurement_metadata_managed_by"] == "purpleair_importer"

    rejected_response = client.put(
        f"/admin/devices/{device_id}/sensors/{sensor_id}",
        json={"expected_frequency_seconds": 60},
        headers=admin_auth_headers,
    )
    assert rejected_response.status_code == 400
    assert "read-only and importer-managed" in rejected_response.json()["detail"]

    with SessionLocal() as session:
        updated_sensor = session.get(models.Sensor, sensor_id)
        assert updated_sensor is not None
        o3 = session.execute(
            select(models.Parameter).where(models.Parameter.code == "o3")
        ).scalar_one()
        assert updated_sensor.parameter_id == o3.parameter_id
        assert updated_sensor.external_sensor_id == "before-edit"

    list_response = client.get(f"/devices/{device_id}/sensors")
    assert list_response.status_code == 200, list_response.text
    listed_sensor = list_response.json()[0]
    assert listed_sensor["expected_frequency_seconds"] == 120
    assert listed_sensor["measurement_duration_seconds"] == 120
    assert listed_sensor["source_aggregation_duration_seconds"] == 120
    assert listed_sensor["measurement_timestamp_semantics"] == "provider_received_at"
    assert listed_sensor["measurement_metadata_status"] == "provider_documented"
    assert listed_sensor["measurement_metadata_managed_by"] == "purpleair_importer"

    delete_response = client.delete(
        f"/admin/devices/{device_id}/sensors/{sensor_id}",
        headers=admin_auth_headers,
    )

    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json()["status"] == "deleted"

    with SessionLocal() as session:
        assert session.get(models.Sensor, sensor_id) is None
