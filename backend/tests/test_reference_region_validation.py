"""Offline regressions for the 2026-09-11 localhost provenance investigation."""
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import models
from api.routes import setup
from reference_data.regions import REFERENCE_REGION_BOUNDS, validate_reference_coordinates
from sources.airgradient import importer
from tests.test_airgradient_reference_locations import (
    _mock_direct_location_requests, _provider_payloads, _reference_session,
)


@pytest.fixture(autouse=True)
def isolate_dashboard_reference_validation(monkeypatch):
    monkeypatch.setattr(importer, "import_location_history", lambda *args, **kwargs: None)


@pytest.mark.parametrize("region", REFERENCE_REGION_BOUNDS)
def test_reference_bounds_accept_edges_and_reject_switzerland(region):
    bounds = REFERENCE_REGION_BOUNDS[region]
    validate_reference_coordinates(region, bounds.min_latitude, bounds.min_longitude)
    validate_reference_coordinates(region, bounds.max_latitude, bounds.max_longitude)
    with pytest.raises(ValueError, match="out-of-region"):
        validate_reference_coordinates(region, 46.886025, 8.536893)
    with pytest.raises(ValueError, match="out-of-region"):
        validate_reference_coordinates(region, bounds.max_latitude + 0.001, bounds.max_longitude)


@pytest.mark.parametrize("coordinates", [(None, None), (None, 1), (float('nan'), 1), (91, 1)])
def test_reference_requires_known_valid_coordinates(coordinates):
    with pytest.raises(ValueError):
        validate_reference_coordinates("new_york", *coordinates)


def test_configured_ids_match_captured_live_regions_and_sao_paulo_is_not_rio():
    captured = json.loads((Path(__file__).parent / "fixtures/airgradient/public_reference_identity_20260911.json").read_text())
    assert {reference["code"] for reference in importer.AIRGRADIENT_REFERENCE_LOCATIONS} == {"new_york", "south_america_rio_reference", "metro_manila"}
    for reference in importer.AIRGRADIENT_REFERENCE_LOCATIONS:
        location = captured[reference["location_id"]]
        assert str(location["locationId"]) == reference["location_id"]
        assert location["offline"] is False
        importer._validate_public_reference_location(location, reference["location_id"])
    sao_paulo = captured["175911"]
    with pytest.raises(ValueError, match="out-of-region"):
        validate_reference_coordinates("rio_de_janeiro", sao_paulo["latitude"], sao_paulo["longitude"])
    assert importer.AIRGRADIENT_UNAVAILABLE_REFERENCE_REGIONS == ()


def test_clean_setup_imports_three_public_references_without_authenticated_sites(tmp_path, monkeypatch):
    session, source = _reference_session(tmp_path)
    setup.configure_data_source(setup.ConfigureDataSourceRequest(
        external_api_id=source.external_api_id, api_key="setup-key", enabled=True,
    ), session)
    assert source.params["import_authenticated_locations"] is False
    assert setup.list_data_sources(session).data_sources[0].import_authenticated_locations is False
    Session = sessionmaker(bind=session.get_bind())
    calls = []
    events = []
    _mock_direct_location_requests(monkeypatch, _provider_payloads(), calls)
    monkeypatch.setattr(importer, "SessionLocal", Session)
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: events.append((args, kwargs)))
    summary = importer.run_import()
    assert summary["devices_created"] == 3
    assert summary["authenticated_locations_discovered"] == 0
    assert summary["reference_regions_unavailable"] == []
    assert all("/world/locations/" in path for path in calls)
    assert not any(args[0] == "airgradient_reference_region_unavailable" for args, _ in events)
    assert set(session.scalars(select(models.Device.external_id))) == {"58376", "175911", "160791"}
    calls.clear()
    assert importer.run_import()["devices_created"] == 0
    assert len(calls) == 3
    session.close()


@pytest.mark.parametrize("existing", [False, True])
def test_switzerland_response_rejected_before_reference_create_or_update(tmp_path, monkeypatch, existing):
    session, source = _reference_session(tmp_path)
    payloads = _provider_payloads()
    if existing:
        importer._ensure_reference_device(session, payloads["58376"], source.external_api_id, "58376", "America/New_York")
        session.commit()
    payloads["58376"] = {**payloads["58376"], "locationName": "Unexpected Swiss reference", "latitude": 46.886025, "longitude": 8.536893}
    events = []
    _mock_direct_location_requests(monkeypatch, payloads, [])
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: events.append(kwargs))
    result = importer._initialize_reference_locations(session, source, "key", importer.DEFAULT_BASE_URL, force=True)
    session.commit()
    failure = result["locations_failed"][0]
    assert failure["location_id"] == "58376"
    assert "new_york" in failure["reason"]
    assert "46.886025" in failure["reason"]
    assert any(event.get("payload") == failure for event in events)
    device = session.scalar(select(models.Device).where(models.Device.external_id == "58376"))
    if existing:
        assert device.latitude == 40.940119
        assert device.name == "Provider New York"
    else:
        assert device is None
    session.close()


@pytest.mark.parametrize("location_id", ["58376", "175911"])
def test_later_public_import_rejects_moved_reference_without_measurements(tmp_path, monkeypatch, location_id):
    session, source = _reference_session(tmp_path)
    source.params = {"import_authenticated_locations": False}
    session.commit()
    Session = sessionmaker(bind=session.get_bind())
    payloads = _provider_payloads()
    _mock_direct_location_requests(monkeypatch, payloads, [])
    monkeypatch.setattr(importer, "SessionLocal", Session)
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: None)
    importer.run_import()
    before = session.scalar(select(func.count()).select_from(models.Measurement))
    payloads[location_id].update(latitude=46.886025, longitude=8.536893, timestamp="2026-09-11T08:00:00Z")
    summary = importer.run_import(location_ids=[int(location_id)])
    assert "out-of-region" in summary["errors"][0]
    assert summary["measurements_received"] == 0
    assert session.scalar(select(func.count()).select_from(models.Measurement)) == before
    session.close()


def test_prior_initialization_version_does_not_recreate_deleted_devices(tmp_path, monkeypatch):
    session, source = _reference_session(tmp_path)
    source.params = {"reference_locations_version": "2026-08-17-v1", "reference_locations_initialized_ids": ["58376", "175911", "160791"]}
    session.commit()
    monkeypatch.setattr(importer, "_api_get", lambda *args, **kwargs: pytest.fail("must preserve deleted references"))
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: None)
    assert importer._initialize_reference_locations(session, source, "key", importer.DEFAULT_BASE_URL)["attempted"] is False
    assert source.params["reference_locations_initialized_ids"] == ["58376", "175911", "160791"]
    assert session.scalar(select(func.count()).select_from(models.Device)) == 0
    session.close()


def test_authenticated_swiss_site_remains_allowed_and_can_be_explicitly_selected(tmp_path, monkeypatch):
    session, source = _reference_session(tmp_path)
    payload = {"locationId": 2295, "locationName": "Junior 1", "latitude": 46.886025, "longitude": 8.536893, "timezone": "Asia/Bangkok", "pm02": 7}
    monkeypatch.setattr(importer, "_api_get", lambda path, *args, **kwargs: {"id": 133, "name": "Fixture place", "timezoneId": "Asia/Bangkok"} if path.endswith('/place') else [payload])
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: None)
    # Missing setting is an existing-installation compatibility contract.
    result = importer._discover_authenticated_locations(session, source, "key", importer.DEFAULT_BASE_URL)
    assert result["devices_created"] == 1
    session.commit()
    setup.configure_data_source(setup.ConfigureDataSourceRequest(external_api_id=source.external_api_id, enabled=True), session)
    assert importer._discover_authenticated_locations(session, source, "key", importer.DEFAULT_BASE_URL)["locations_discovered"] == 0
    assert session.scalar(select(func.count()).select_from(models.Device)) == 1
    setup.configure_data_source(setup.ConfigureDataSourceRequest(external_api_id=source.external_api_id, enabled=True, import_authenticated_locations=True), session)
    assert importer._discover_authenticated_locations(session, source, "key", importer.DEFAULT_BASE_URL)["devices_created"] == 0
    device = session.scalar(select(models.Device))
    assert device.acquisition_path == importer.AIRGRADIENT_AUTHENTICATED_PATH
    assert device.latitude == 46.886025
    session.close()


def test_static_bootstrap_contains_only_intended_regions_and_rejects_corruption(tmp_path, monkeypatch):
    from copy import deepcopy
    from reference_data.default_devices import bootstrap
    from tests.test_default_reference_devices import _reference_session as static_session

    session = static_session(tmp_path)
    assert bootstrap.initialize_default_reference_devices(session) == (7, 19)
    session.commit()
    assert {item["region_code"] for item in bootstrap._MANIFEST["devices"]} == set(REFERENCE_REGION_BOUNDS)
    for device in session.scalars(select(models.Device)):
        definition = next(item for item in bootstrap._MANIFEST["devices"] if item["external_id"] == device.external_id)
        validate_reference_coordinates(definition["region_code"], device.latitude, device.longitude)
    assert bootstrap.initialize_default_reference_devices(session) == (0, 0)
    corrupted = deepcopy(bootstrap._MANIFEST)
    corrupted["devices"][0].update(latitude=46.886025, longitude=8.536893)
    monkeypatch.setattr(bootstrap, "_MANIFEST", corrupted)
    with pytest.raises(ValueError, match="out-of-region"):
        bootstrap.restore_missing_default_reference_devices(session)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(models.Device)) == 7
    session.close()


def test_retired_public_reference_keeps_history_and_unrelated_paths(tmp_path, monkeypatch):
    session, source = _reference_session(tmp_path)
    source.params = {"reference_locations_version": importer.AIRGRADIENT_REFERENCE_LOCATIONS_VERSION, "reference_locations_initialized_ids": ["58376", "175911", "160791"]}
    for path in (importer.AIRGRADIENT_PUBLIC_REFERENCE_PATH, importer.AIRGRADIENT_AUTHENTICATED_PATH):
        session.add(models.Device(name="Synthetic retired reference", external_id="900099", external_api_id=source.external_api_id, acquisition_path=path))
    session.commit()
    Session = sessionmaker(bind=session.get_bind())
    calls = []
    def request(path, *args, **kwargs):
        calls.append(path)
        assert '/world/' not in path
        if path.endswith('/place'):
            return {"id": 1, "name": "Owner", "timezoneId": "UTC"}
        if path.endswith('/locations/measures/current'):
            return []
        return {"locationId": 900099, "timestamp": "2026-09-11T08:00:00Z", "pm02": 5}
    monkeypatch.setattr(importer, "_api_get", request)
    monkeypatch.setattr(importer, "SessionLocal", Session)
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: None)
    summary = importer.run_import()
    assert '900099 is no longer approved' in summary['errors'][0]
    assert summary['measurements_inserted'] == 1
    assert session.scalar(select(func.count()).select_from(models.Device)) == 2
    assert any('/locations/900099/' in path for path in calls)
    session.close()
