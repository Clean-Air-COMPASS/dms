from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
import models
from services.external_sources import ensure_builtin_external_apis

client = TestClient(app)


def test_list_external_apis_is_ordered_alphabetically(admin_auth_headers):
    names = [f"Zulu API {uuid.uuid4()}", f"Alpha API {uuid.uuid4()}"]
    with SessionLocal() as session:
        for name in names:
            existing = session.execute(
                select(models.ExternalAPI).where(models.ExternalAPI.name == name)
            ).scalar_one_or_none()
            if not existing:
                session.add(
                    models.ExternalAPI(
                        name=name,
                        base_url="https://example.test",
                        description="test",
                        params={},
                    )
                )
        session.commit()

    response = client.get("/admin/external_apis", headers=admin_auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    returned_names = [item["name"] for item in body]
    alpha_index = returned_names.index(names[1])
    zulu_index = returned_names.index(names[0])
    assert alpha_index < zulu_index


def test_delete_external_api_fails_when_devices_exist(admin_auth_headers):
    name = f"Protected API {uuid.uuid4()}"
    with SessionLocal() as session:
        source = models.ExternalAPI(name=name, base_url="https://example.test", description="test", params={}, enabled=True)
        session.add(source)
        session.flush()
        session.add(models.Device(name=f"device-{uuid.uuid4()}", external_api_id=source.external_api_id))
        session.commit()
        external_api_id = source.external_api_id

    response = client.delete(f"/admin/external_apis/{external_api_id}", headers=admin_auth_headers)

    assert response.status_code == 409, response.text
    assert "Cannot delete data source" in response.json()["detail"]
    assert "still associated" in response.json()["detail"]


def test_builtin_external_apis_cannot_be_deleted_even_without_devices(
    admin_auth_headers,
):
    with SessionLocal() as session:
        ensure_builtin_external_apis(session)
        session.commit()
        sources = session.scalars(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code.in_(
                    ["openaq", "purpleair", "airgradient"]
                )
            )
        ).all()
        source_ids = {source.provider_code: source.external_api_id for source in sources}
        airgradient_device_count = session.scalar(
            select(models.Device.device_id)
            .where(
                models.Device.external_api_id == source_ids["airgradient"]
            )
            .limit(1)
        )

    assert set(source_ids) == {"openaq", "purpleair", "airgradient"}
    assert airgradient_device_count is None
    for provider_code, source_id in source_ids.items():
        response = client.delete(
            f"/admin/external_apis/{source_id}", headers=admin_auth_headers
        )
        assert response.status_code == 409, response.text
        assert "Cannot delete built-in data source" in response.json()["detail"]

        detail = client.get(
            f"/admin/external_apis/{source_id}", headers=admin_auth_headers
        )
        assert detail.status_code == 200
        assert detail.json()["is_builtin"] is True
        assert detail.json()["can_delete"] is False


def test_custom_external_api_without_devices_remains_deletable(admin_auth_headers):
    name = f"Deletable custom API {uuid.uuid4()}"
    create_response = client.post(
        "/admin/external_apis",
        json={"name": name, "enabled": False},
        headers=admin_auth_headers,
    )
    assert create_response.status_code == 200, create_response.text
    body = create_response.json()
    assert body["is_builtin"] is False
    assert body["can_delete"] is True

    delete_response = client.delete(
        f"/admin/external_apis/{body['external_api_id']}",
        headers=admin_auth_headers,
    )
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json() == {"success": True}


def test_update_external_api_can_set_disabled(admin_auth_headers):
    name = f"Inactive API {uuid.uuid4()}"
    with SessionLocal() as session:
        source = models.ExternalAPI(name=name, base_url="https://example.test", description="test", params={}, enabled=True)
        session.add(source)
        session.commit()
        external_api_id = source.external_api_id

    response = client.put(
        f"/admin/external_apis/{external_api_id}",
        json={"enabled": False},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False

    with SessionLocal() as session:
        refreshed = session.get(models.ExternalAPI, external_api_id)
        assert refreshed is not None
        assert refreshed.enabled is False


def test_enabled_source_credential_lifecycle_is_derived_without_retoggle(
    admin_auth_headers,
):
    with SessionLocal() as session:
        source = session.scalar(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == "openaq"
            )
        )
        if source is None:
            source = models.ExternalAPI(
                provider_code="openaq",
                name=f"OpenAQ lifecycle {uuid.uuid4()}",
                params={},
                enabled=False,
            )
            session.add(source)
            session.commit()
        external_api_id = source.external_api_id

    enabled_without_key = client.put(
        f"/admin/external_apis/{external_api_id}",
        json={"enabled": True, "api_key": None},
        headers=admin_auth_headers,
    )
    assert enabled_without_key.status_code == 200
    assert enabled_without_key.json()["enabled"] is True
    assert enabled_without_key.json()["is_configured"] is False
    assert enabled_without_key.json()["is_runnable"] is False
    assert enabled_without_key.json()["runnable_reason"] == "configuration_required"

    credential_added = client.put(
        f"/admin/external_apis/{external_api_id}",
        json={"api_key": "stored-key"},
        headers=admin_auth_headers,
    )
    assert credential_added.status_code == 200
    assert credential_added.json()["enabled"] is True
    assert credential_added.json()["is_runnable"] is True
    assert credential_added.json()["runnable_reason"] == "ready"

    credential_cleared = client.put(
        f"/admin/external_apis/{external_api_id}",
        json={"api_key": ""},
        headers=admin_auth_headers,
    )
    assert credential_cleared.status_code == 200
    assert credential_cleared.json()["enabled"] is True
    assert credential_cleared.json()["is_configured"] is False
    assert credential_cleared.json()["runnable_reason"] == "configuration_required"


def test_external_api_rejects_removed_is_active_input(admin_auth_headers):
    with SessionLocal() as session:
        source = models.ExternalAPI(
            name=f"No alias {uuid.uuid4()}", params={}, enabled=False
        )
        session.add(source)
        session.commit()
        external_api_id = source.external_api_id

    response = client.put(
        f"/admin/external_apis/{external_api_id}",
        json={"is_active": True},
        headers=admin_auth_headers,
    )
    assert response.status_code == 422


def test_external_api_exposes_safe_credential_presence_and_provider_latest_run(
    admin_auth_headers,
):
    with SessionLocal() as session:
        source = session.scalar(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == "openaq"
            )
        )
        assert source is not None
        source.api_key = "secret-that-must-not-be-returned"
        schedule = session.scalar(
            select(models.JobSchedule).where(
                models.JobSchedule.task == "openaq_import"
            )
        )
        if schedule is None:
            schedule = models.JobSchedule(
                task="openaq_import", cron_expr="0 * * * *", enabled=True
            )
            session.add(schedule)
            session.flush()
        run = models.JobRun(
            job_schedule_id=schedule.job_schedule_id,
            status="success",
            started_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            finished_at=datetime(2099, 1, 1, 0, 1, tzinfo=timezone.utc),
            summary={
                "devices_processed": 2,
                "devices_created": 0,
                "sensors_processed": 3,
                "sensors_created": 0,
                "measurements_received": 4,
                "measurements_inserted": 4,
                "measurements_updated": 0,
                "measurements_skipped": 0,
            },
        )
        session.add_all([source, run])
        session.commit()
        source_id = source.external_api_id
        run_id = run.job_run_id

    response = client.get(
        f"/admin/external_apis/{source_id}", headers=admin_auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["has_api_key"] is True
    assert "api_key" not in body
    assert "secret-that-must-not-be-returned" not in response.text
    assert body["latest_import"]["job_run_id"] == run_id
    assert body["latest_import"]["task"] == "openaq_import"
