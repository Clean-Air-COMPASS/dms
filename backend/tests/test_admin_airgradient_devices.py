import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import models
from api.routes.admin.airgradient_devices import router
from db import get_session
from sources.airgradient import importer
from tests.test_airgradient_authenticated import _authenticated_fixtures
from tests.test_airgradient_reference_locations import _reference_session

PATH = "/admin/devices/airgradient/locations"


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    session, source = _reference_session(tmp_path)
    source.params = {**source.params, "import_authenticated_locations": False}
    session.commit()
    place, locations = _authenticated_fixtures()
    locations[0].update(wifi=-40, boot=12, serialno="private-serial", token="stored-key")
    calls = []

    def get(url, params, timeout):
        calls.append(url)
        assert params == {"token": "stored-key"}
        assert timeout == 30
        assert url in [f"{importer.DEFAULT_BASE_URL}/place", f"{importer.DEFAULT_BASE_URL}/locations/measures/current"]

        class Response:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return place if url.endswith("/place") else locations
        return Response()

    monkeypatch.setattr(importer.requests, "get", get)
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_session] = lambda: session
    with TestClient(test_app) as client:
        yield client, session, source, locations, calls
    session.close()


def test_lists_saved_account_locations_without_secrets_or_writes(workflow):
    client, session, source, _, calls = workflow
    response = client.get(PATH)
    assert response.status_code == 200
    assert response.json()["automatic_imports_enabled"] is False
    assert [row["location_id"] for row in response.json()["locations"]] == ["70001", "70002"]
    assert response.json()["locations"][0]["timezone"] == "America/Los_Angeles"
    assert all(secret not in response.text for secret in ["stored-key", "token", "private-serial", "api_key"])
    assert len(calls) == 2
    assert session.scalar(select(func.count()).select_from(models.Device)) == 0


def test_adds_only_selected_location_with_canonical_sensors_and_current_readings(workflow):
    client, session, source, _, calls = workflow
    original_params = dict(source.params)
    response = client.post(PATH, json={"location_id": "70001"})
    assert response.status_code == 200, response.text
    assert response.json()["already_exists"] is False
    assert response.json()["measurements_imported"] > 0
    device = session.get(models.Device, response.json()["device_id"])
    assert device.external_id == "70001"
    assert device.external_api_id == source.external_api_id
    assert device.acquisition_path == importer.AIRGRADIENT_AUTHENTICATED_PATH
    assert device.name == "Library roof"
    assert device.latitude == pytest.approx(34.0522)
    assert device.longitude == pytest.approx(-118.2437)
    assert device.timezone == "America/Los_Angeles"
    assert device.hardware_provider_name == "AirGradient"
    assert device.contributor_name == "Neighborhood Air Team"
    assert device.license_code is None
    rows = session.execute(select(models.Sensor.external_sensor_id, models.Parameter.code, models.Unit.code)
        .select_from(models.Sensor).join(models.Parameter, models.Sensor.parameter_id == models.Parameter.parameter_id)
        .join(models.Unit, models.Sensor.unit_id == models.Unit.unit_id)).all()
    assert ("70001:atmp", "temperature", "celsius") in rows
    assert ("70001:rhum", "relative_humidity", "percent") in rows
    assert ("70001:pm02", "pm25", "ug_m3") in rows
    assert len(rows) == 10
    assert not any("wifi" in row[0] or "boot" in row[0] for row in rows)
    assert session.scalar(select(func.count()).select_from(models.Device)) == 1
    assert source.params == original_params
    assert len(calls) == 2  # The enumeration already contains current readings.

    # A later enabled scheduled discovery updates this same canonical record.
    source.params = {**source.params, "import_authenticated_locations": True}
    importer._discover_authenticated_locations(session, source, source.api_key, importer.DEFAULT_BASE_URL)
    assert session.scalar(select(func.count()).select_from(models.Device)) == 2
    assert session.get(models.Device, device.device_id).external_id == "70001"


@pytest.mark.parametrize("automatic", [False, True])
def test_duplicate_resolves_by_identity_without_another_provider_call(workflow, automatic):
    client, session, source, locations, calls = workflow
    source.params = {**source.params, "import_authenticated_locations": automatic}
    first = client.post(PATH, json={"location_id": "70001"}).json()
    session.get(models.Device, first["device_id"]).name = "Renamed locally"
    session.commit()
    calls.clear()
    second = client.post(PATH, json={"location_id": "70001"})
    assert second.json() == {**first, "already_exists": True, "measurements_imported": 0}
    assert calls == []
    listed = client.get(PATH).json()["locations"]
    assert listed[0]["existing_device_id"] == first["device_id"]
    assert session.scalar(select(func.count()).select_from(models.Device)) == 1


@pytest.mark.parametrize("credential", [None, "", "   "])
def test_missing_credential_directs_to_configuration(workflow, credential):
    client, session, source, _, calls = workflow
    source.api_key = credential
    session.commit()
    response = client.get(PATH)
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "configuration_required"
    assert calls == []


@pytest.mark.parametrize("error,code,status", [
    (importer.AirGradientAuthenticationError, "authentication_failed", 422),
    (importer.AirGradientProviderUnavailable, "provider_unavailable", 503),
    (importer.AirGradientRateLimit, "rate_limited", 429),
    (importer.AirGradientMalformedResponse, "invalid_response", 502),
])
def test_provider_errors_are_safe(workflow, monkeypatch, error, code, status):
    client, *_ = workflow
    def fail(*args, **kwargs):
        raise error("unsafe provider token=stored-key")
    monkeypatch.setattr(importer, "_api_get", fail)
    response = client.get(PATH)
    assert response.status_code == status
    assert response.json() == {"detail": {"error_code": code}}
    assert "stored-key" not in response.text


def test_empty_and_invalid_identity_are_distinct(workflow):
    client, _, _, locations, _ = workflow
    locations.clear()
    assert client.get(PATH).json()["locations"] == []
    locations.append({"locationName": "Missing identity"})
    assert client.get(PATH).json()["detail"]["error_code"] == "invalid_response"


def test_revalidates_membership_and_rejects_browser_metadata(workflow):
    client, session, *_ = workflow
    assert client.post(PATH, json={"location_id": "not-owned"}).status_code == 404
    assert client.post(PATH, json={"location_id": "70001", "api_key": "browser-secret"}).status_code == 422
    assert session.scalar(select(func.count()).select_from(models.Device)) == 0


def test_creation_failure_rolls_back_device_and_sensors(workflow, monkeypatch):
    client, session, *_ = workflow
    def fail(*args, **kwargs):
        raise RuntimeError("stored-key")
    monkeypatch.setattr(importer, "_store_measurements", fail)
    response = client.post(PATH, json={"location_id": "70001"})
    assert response.json() == {"detail": {"error_code": "operation_failed"}}
    assert session.scalar(select(func.count()).select_from(models.Device)) == 0
    assert session.scalar(select(func.count()).select_from(models.Sensor)) == 0


def test_absent_source_and_disabled_source_with_saved_credential(workflow):
    client, session, source, _, calls = workflow
    source.enabled = False
    session.commit()
    assert client.get(PATH).json()["automatic_imports_enabled"] is False
    source_id = source.external_api_id
    session.delete(source)
    session.commit()
    calls.clear()
    assert client.get(PATH).json()["detail"]["error_code"] == "configuration_required"
    assert session.get(models.ExternalAPI, source_id) is None
    assert calls == []


def test_no_usable_readings_is_explicit_and_keeps_supported_sensors(workflow):
    client, session, _, locations, _ = workflow
    locations[0].pop("timestamp")
    result = client.post(PATH, json={"location_id": "70001"}).json()
    assert result["measurements_imported"] == 0
    assert result["already_exists"] is False
    assert session.scalar(select(func.count()).select_from(models.Sensor)) == 10


def test_public_reference_identity_and_settings_are_unchanged(workflow):
    client, session, source, _, _ = workflow
    reference = models.Device(name="Public reference", external_id="70001", external_api_id=source.external_api_id,
                              acquisition_path=importer.AIRGRADIENT_PUBLIC_REFERENCE_PATH)
    session.add(reference)
    session.commit()
    params = dict(source.params)
    result = client.post(PATH, json={"location_id": "70001"}).json()
    assert result["device_id"] != reference.device_id
    assert reference.acquisition_path == importer.AIRGRADIENT_PUBLIC_REFERENCE_PATH
    assert reference.name == "Public reference"
    assert source.params == params


def test_actual_routes_require_admin_authentication():
    from api.main import app
    client = TestClient(app)
    assert client.get(PATH).status_code == 401
    assert client.post(PATH, json={"location_id": "70001"}).status_code == 401
