from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import models
from api.main import app
from db import get_session
from sources.airgradient import importer
from tests.test_airgradient_reference_locations import (
    _provider_payloads,
    _reference_session,
)


@pytest.fixture(autouse=True)
def isolate_dashboard_snapshot_contract(monkeypatch):
    """This suite exercises Dashboard snapshots; Map history has its own suite."""
    monkeypatch.setattr(importer, "import_location_history", lambda *args, **kwargs: None)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "airgradient"


def test_admin_saves_airgradient_credentials_without_provider_verification(tmp_path, monkeypatch):
    from api.routes.admin.external_apis import ExternalAPIUpdateIn, update_external_api

    session, source = _reference_session(tmp_path)
    monkeypatch.setattr(importer.requests, "get", lambda *args, **kwargs: pytest.fail("saving must not contact provider"))
    result = update_external_api(
        source.external_api_id,
        ExternalAPIUpdateIn(api_key="saved-unverified-token", enabled=True, params={"import_authenticated_locations": False}),
        session,
    )
    assert result.has_api_key is True
    assert source.api_key == "saved-unverified-token"
    assert source.params["import_authenticated_locations"] is False
    session.close()


def _authenticated_fixtures() -> tuple[dict, list[dict]]:
    place = json.loads((FIXTURE_ROOT / "authenticated_place.json").read_text())
    locations = json.loads(
        (FIXTURE_ROOT / "authenticated_locations_current.json").read_text()
    )
    return place, locations


def test_issue_6_discovery_sends_token_to_place_never_bare_locations(tmp_path, monkeypatch):
    """Exercise the HTTP adapter as well as discovery's endpoint selection."""
    session, source = _reference_session(tmp_path)
    place, locations = _authenticated_fixtures()
    calls = []

    def get(url, params, timeout):
        calls.append((url, params))
        assert params == {"token": "regression-token"}
        assert timeout == 30
        payloads = {
            f"{importer.DEFAULT_BASE_URL}/place": place,
            f"{importer.DEFAULT_BASE_URL}/locations/measures/current": locations,
        }
        assert url in payloads, f"Unexpected authenticated endpoint: {url}"

        class Response:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return payloads[url]

        return Response()

    monkeypatch.setattr(importer.requests, "get", get)
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: None)
    try:
        importer._discover_authenticated_locations(
            session, source, "regression-token", importer.DEFAULT_BASE_URL
        )
        assert [url for url, _ in calls] == [
            f"{importer.DEFAULT_BASE_URL}/place",
            f"{importer.DEFAULT_BASE_URL}/locations/measures/current",
        ]
        assert not any(url.endswith("/locations") for url, _ in calls)
    finally:
        session.close()


def test_authenticated_discovery_creates_and_idempotently_updates_all_locations(tmp_path, monkeypatch):
    session, source = _reference_session(tmp_path)
    place, locations = _authenticated_fixtures()
    requests: list[tuple[str, str, bool]] = []

    def fake_api_get(path, api_key, params=None, include_token=True):
        requests.append((path, api_key, include_token))
        if path.endswith("/place"):
            return place
        if path.endswith("/locations/measures/current"):
            return locations
        raise AssertionError(path)

    monkeypatch.setattr(importer, "_api_get", fake_api_get)
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: None)

    try:
        first = importer._discover_authenticated_locations(
            session, source, "saved-secret", importer.DEFAULT_BASE_URL
        )
        session.commit()
        assert first == {
            "place_id": "2468",
            "locations_discovered": 2,
            "location_ids": ["70001", "70002"],
            "devices_created": 2,
            "sensors_created": 13,
        }

        library = session.scalar(
            select(models.Device).where(
                models.Device.external_id == "70001",
                models.Device.acquisition_path
                == importer.AIRGRADIENT_AUTHENTICATED_PATH,
            )
        )
        library.friendly_name = "Administrator label"
        session.commit()

        locations[0]["locationName"] = "Library roof updated by provider"
        second = importer._discover_authenticated_locations(
            session, source, "saved-secret", importer.DEFAULT_BASE_URL
        )
        session.commit()

        assert second["devices_created"] == 0
        assert second["sensors_created"] == 0
        assert session.scalar(select(func.count()).select_from(models.Device)) == 2
        assert session.scalar(select(func.count()).select_from(models.Sensor)) == 13
        session.refresh(library)
        assert library.name == "Library roof updated by provider"
        assert library.friendly_name == "Administrator label"
        assert library.external_id == "70001"
        assert library.contributor_name == "Neighborhood Air Team"
        assert library.contributor_url == "https://example.org/neighborhood-air"
        assert library.license_code is None
        assert library.license_share_alike is None
        assert all(api_key == "saved-secret" for _, api_key, _ in requests)
        assert all(include_token is True for _, _, include_token in requests)
    finally:
        session.close()


def test_import_uses_authenticated_location_paths_and_token_but_public_world_has_no_token(tmp_path, monkeypatch):
    setup_session, source = _reference_session(tmp_path)
    Session = sessionmaker(bind=setup_session.get_bind())
    setup_session.close()
    place, locations = _authenticated_fixtures()
    locations[0]["rhum"] = 101.0
    locations[1]["pm02_corrected"] = -20.0
    references = _provider_payloads()
    calls: list[tuple[str, str, bool]] = []

    def fake_api_get(path, api_key, params=None, include_token=True):
        calls.append((path, api_key, include_token))
        if path.endswith("/place"):
            return place
        if path.endswith("/locations/measures/current"):
            return locations
        if "/world/locations/" in path:
            location_id = path.split("/world/locations/")[1].split("/")[0]
            return references[location_id]
        location_id = path.split("/locations/")[1].split("/")[0]
        return next(row for row in locations if str(row["locationId"]) == location_id)

    monkeypatch.setattr(importer, "SessionLocal", Session)
    monkeypatch.setattr(importer, "_api_get", fake_api_get)
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: None)

    summary = importer.run_import(location_ids=[70001, 70002, 58376])

    authenticated_calls = [call for call in calls if "/world/" not in call[0]]
    public_calls = [call for call in calls if "/world/locations/" in call[0]]
    assert any(path.endswith("/place") for path, _, _ in authenticated_calls)
    assert any(path.endswith("/locations/measures/current") for path, _, _ in authenticated_calls)
    assert any(
        path.endswith("/locations/70001/measures/current")
        for path, _, _ in authenticated_calls
    )
    assert all(api_key == "stored-key" and include_token for _, api_key, include_token in authenticated_calls)
    assert {path.split("/world/locations/")[1].split("/")[0] for path, _, _ in public_calls} == {
        "58376",
        "175911",
        "160791",
    }
    assert all(include_token is False for _, _, include_token in public_calls)
    assert summary["authenticated_locations_discovered"] == 2
    assert summary["measurements_inserted"] > 0
    assert summary["qc"]["evaluated"] > 0

    with Session() as session:
        authenticated_device = session.scalar(
            select(models.Device).where(
                models.Device.external_id == "70001",
                models.Device.acquisition_path
                == importer.AIRGRADIENT_AUTHENTICATED_PATH,
            )
        )
        assert authenticated_device is not None
        assert session.scalar(
            select(func.count())
            .select_from(models.Measurement)
            .join(models.Sensor)
            .where(models.Sensor.device_id == authenticated_device.device_id)
        ) == 10
        qc_failures = session.execute(
            select(
                models.MeasurementQCResult.check_code,
                models.MeasurementQCResult.failure_action,
            )
            .join(models.Measurement)
            .join(models.Sensor)
            .join(models.Device)
            .where(
                models.Device.acquisition_path
                == importer.AIRGRADIENT_AUTHENTICATED_PATH
            )
            .order_by(models.MeasurementQCResult.check_code)
        ).all()
        assert qc_failures == [
            ("max_value", "mark_invalid"),
            ("min_value", "flag_for_review"),
        ]
        device_id = authenticated_device.device_id
        pm25_sensor_id = session.scalar(
            select(models.Sensor.sensor_id)
            .join(models.Parameter)
            .where(
                models.Sensor.device_id == authenticated_device.device_id,
                models.Parameter.code == "pm25",
            )
        )

    def override_session():
        with Session() as api_session:
            yield api_session

    app.dependency_overrides[get_session] = override_session
    try:
        latest_response = TestClient(app).get(
            "/measurements/pm25/latest", params={"device_id": device_id}
        )
        assert latest_response.status_code == 200, latest_response.text
        latest_row = latest_response.json()[0]
        assert latest_row["value"] == 7.2
        assert latest_row["device"]["data_attribution"] == {
            "acquisition_path": "airgradient_authenticated",
            "data_provider_name": "AirGradient",
            "hardware_provider_name": "AirGradient",
            "provider_url": "https://www.airgradient.com",
            "contributor_name": "Neighborhood Air Team",
            "contributor_url": "https://example.org/neighborhood-air",
            "license_code": None,
            "license_url": None,
            "license_share_alike": None,
        }

        history_response = TestClient(app).get(
            f"/sensors/{pm25_sensor_id}/history",
            params={
                "aggregation": "1m",
                "start": "2026-09-03T11:00:00Z",
                "end": "2026-09-03T13:00:00Z",
            },
        )
        assert history_response.status_code == 200, history_response.text
        assert history_response.json()["data_attribution"] == latest_row["device"][
            "data_attribution"
        ]
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_rejected_token_reports_authentication_error_without_secret(tmp_path, monkeypatch):
    setup_session, _source = _reference_session(tmp_path)
    Session = sessionmaker(bind=setup_session.get_bind())
    setup_session.close()
    references = _provider_payloads()
    emitted_events: list[dict] = []

    def fake_api_get(path, api_key, params=None, include_token=True):
        if "/world/locations/" in path:
            location_id = path.split("/world/locations/")[1].split("/")[0]
            return references[location_id]
        raise importer.AirGradientAuthenticationError(
            "AirGradient rejected the saved API token"
        )

    monkeypatch.setattr(importer, "SessionLocal", Session)
    monkeypatch.setattr(importer, "_api_get", fake_api_get)
    monkeypatch.setattr(
        importer,
        "_emit_event",
        lambda event_type, severity="info", **kwargs: emitted_events.append(
            {"event_type": event_type, "severity": severity, **kwargs}
        ),
    )

    with pytest.raises(importer.AirGradientAuthenticationError) as exc_info:
        importer.run_import()

    assert "stored-key" not in str(exc_info.value)
    authentication_events = [
        event for event in emitted_events
        if event["event_type"] == "airgradient_authentication_error"
    ]
    assert len(authentication_events) == 1
    assert "stored-key" not in json.dumps(authentication_events)


def test_api_get_classifies_unauthorized_without_echoing_query_token(monkeypatch):
    class Response:
        status_code = 401

    captured = {}

    def fake_get(url, params, timeout):
        captured.update({"url": url, "params": params, "timeout": timeout})
        return Response()

    monkeypatch.setattr(importer.requests, "get", fake_get)
    with pytest.raises(importer.AirGradientAuthenticationError) as exc_info:
        importer._api_get("place", "top-secret")

    assert captured["params"] == {"token": "top-secret"}
    assert "top-secret" not in str(exc_info.value)


def test_authenticated_payload_rejects_malformed_and_duplicate_locations():
    with pytest.raises(importer.AirGradientMalformedResponse, match="not an array"):
        importer._authenticated_location_payloads({"locationId": 1})
    with pytest.raises(importer.AirGradientMalformedResponse, match="repeated locationId"):
        importer._authenticated_location_payloads(
            [
                {"locationId": 1, "locationName": "One"},
                {"locationId": 1, "locationName": "Duplicate"},
            ]
        )
