from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

import models
from api.main import app
from db import SessionLocal


client = TestClient(app)


def _sensor_context():
    with SessionLocal() as session:
        suffix = uuid.uuid4().hex
        parameter = session.scalar(
            select(models.Parameter).where(models.Parameter.code == "pm25")
        )
        source = models.ExternalAPI(
            provider_code=f"qc-api-{suffix}",
            name=f"QC API source {suffix}",
            params={},
        )
        session.add(source)
        session.flush()
        device = models.Device(
            name=f"QC API device {suffix}",
            external_id=f"device-{suffix}",
            external_api_id=source.external_api_id,
        )
        session.add(device)
        session.flush()
        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=parameter.default_unit_id,
            external_sensor_id=f"sensor-{suffix}",
        )
        session.add(sensor)
        session.commit()
        return source.external_api_id, sensor.sensor_id, parameter.parameter_id


def test_legacy_rule_adapter_rejects_global_scope(admin_auth_headers):
    response = client.post(
        "/admin/qc/rules",
        json={"check_code": "min_value", "enabled": True, "params": {"min": 0}},
        headers=admin_auth_headers,
    )
    assert response.status_code == 400
    assert "scope" in response.json()["detail"].lower()


def test_rule_adapter_supports_sparse_source_override(admin_auth_headers):
    source_id, _, parameter_id = _sensor_context()
    with SessionLocal() as session:
        policy_unit_id = session.get(models.Parameter, parameter_id).default_unit_id
    response = client.post(
        "/admin/qc/rules",
        json={
            "check_code": "max_value",
            "parameter_id": parameter_id,
            "external_api_id": source_id,
            "settings": {"max": 800},
            "policy_unit_id": policy_unit_id,
        },
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is None
    assert body["enabled_override"] is None
    assert body["settings"] == {"max": 800}
    assert body["params"] == {"max": 800}
    assert body["external_api_id"] == source_id

    deleted = client.delete(
        f"/admin/qc/rules/{body['qc_rule_id']}", headers=admin_auth_headers
    )
    assert deleted.status_code == 200


def test_effective_diagnostic_uses_authoritative_resolver(admin_auth_headers):
    _, sensor_id, parameter_id = _sensor_context()
    response = client.get(
        "/admin/qc/effective",
        params={
            "sensor_id": sensor_id,
            "parameter_id": parameter_id,
            "check_code": "min_value",
            "aggregate_code": "1h",
        },
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["threshold"] == -10.0
    assert body["source"] == "compassaq_default"
    assert body["effective_policy"]["status"] == "ready"
    assert body["effective_policy"]["default_profile_version"] == "2026.2"


def test_effective_diagnostic_requires_sensor_for_unit_resolution(admin_auth_headers):
    response = client.get(
        "/admin/qc/effective",
        params={"check_code": "min_value"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 400
    assert "sensor_id" in response.json()["detail"]
