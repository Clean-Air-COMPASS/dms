from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
import models

client = TestClient(app)


def _ensure_external_api(session) -> int:
    existing = session.execute(
        select(models.ExternalAPI).where(models.ExternalAPI.name == "Device Create Test API")
    ).scalar_one_or_none()
    if existing:
        return existing.external_api_id
    row = models.ExternalAPI(
        name="Device Create Test API",
        base_url="https://example.test",
        description="test",
        params={},
    )
    session.add(row)
    session.flush()
    return row.external_api_id


def test_create_device_name_only_multiple_times(admin_auth_headers):
    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)
        session.commit()

    payload_1 = {"name": "Manual Name Only 1", "external_api_id": external_api_id}
    payload_2 = {"name": "Manual Name Only 2", "external_api_id": external_api_id}

    r1 = client.post("/admin/devices", json=payload_1, headers=admin_auth_headers)
    r2 = client.post("/admin/devices", json=payload_2, headers=admin_auth_headers)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    b1 = r1.json()
    b2 = r2.json()
    assert b1["device_id"] != b2["device_id"]
    assert b1.get("external_id") in (None, "")
    assert b2.get("external_id") in (None, "")


def test_create_device_name_only_without_external_api_id_uses_first_available_external_api(admin_auth_headers):
    with SessionLocal() as session:
        _ensure_external_api(session)
        secondary = session.execute(
            select(models.ExternalAPI).where(models.ExternalAPI.name == "Device Create Test API Secondary")
        ).scalar_one_or_none()
        if not secondary:
            session.add(
                models.ExternalAPI(
                    name="Device Create Test API Secondary",
                    base_url="https://example-2.test",
                    description="test",
                    params={},
                )
            )
        session.commit()

    response = client.post(
        "/admin/devices",
        json={"name": "Manual Name Only No External API", "friendly_name": "", "allow_updates": "inherit"},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Manual Name Only No External API"
    assert body["external_api_id"] is not None


def test_create_device_with_new_other_data_source_saves_manual_metadata_only(admin_auth_headers):
    with SessionLocal() as session:
        existing = session.execute(
            select(models.ExternalAPI).where(models.ExternalAPI.name == "Neighborhood Lab")
        ).scalar_one_or_none()
        if existing is not None:
            session.delete(existing)
            session.commit()

    response = client.post(
        "/admin/devices",
        json={"name": "Manual Device Other Source", "network": "Neighborhood Lab"},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Manual Device Other Source"
    assert body["network"] == "Neighborhood Lab"
    assert body["manual_data_source_name"] == "Neighborhood Lab"
    assert body["external_api_id"] is not None

    with SessionLocal() as session:
        created = session.execute(
            select(models.ExternalAPI).where(models.ExternalAPI.name == "Neighborhood Lab")
        ).scalar_one_or_none()
        assert created is None
        device = session.get(models.Device, body["device_id"])
        assert device is not None
        assert device.manual_data_source_name == "Neighborhood Lab"


def test_list_devices_filters_other_manual_data_sources(admin_auth_headers):
    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)
        session.add_all([
            models.Device(
                name="Managed Source Device",
                external_api_id=external_api_id,
                manual_data_source_name=None,
            ),
            models.Device(
                name="Manual Other Source Device",
                external_api_id=external_api_id,
                manual_data_source_name="Neighborhood Lab",
            ),
        ])
        session.commit()

    response = client.get("/admin/devices?network=__other__", headers=admin_auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    names = [row["name"] for row in body]
    assert "Manual Other Source Device" in names
    assert "Managed Source Device" not in names


def test_list_devices_page_parameter_is_zero_based(admin_auth_headers):
    token = uuid4().hex[:10]
    prefix = f"CSV Pagination Contract {token}"

    with SessionLocal() as session:
        external_api_id = _ensure_external_api(session)
        session.add_all([
            models.Device(
                name=f"{prefix} {index:02d}",
                external_api_id=external_api_id,
            )
            for index in range(21)
        ])
        session.commit()

    all_response = client.get(
        "/admin/devices",
        params={"name": prefix, "page": 0, "page_size": 100},
        headers=admin_auth_headers,
    )
    first_page_response = client.get(
        "/admin/devices",
        params={"name": prefix, "page": 0, "page_size": 20},
        headers=admin_auth_headers,
    )
    second_page_response = client.get(
        "/admin/devices",
        params={"name": prefix, "page": 1, "page_size": 20},
        headers=admin_auth_headers,
    )

    assert all_response.status_code == 200, all_response.text
    assert first_page_response.status_code == 200, first_page_response.text
    assert second_page_response.status_code == 200, second_page_response.text

    all_names = [row["name"] for row in all_response.json()]
    first_page_names = [row["name"] for row in first_page_response.json()]
    second_page_names = [row["name"] for row in second_page_response.json()]

    assert len(all_names) == 21
    assert first_page_names == all_names[:20]
    assert second_page_names == all_names[20:]
    assert set(first_page_names + second_page_names) == set(all_names)
