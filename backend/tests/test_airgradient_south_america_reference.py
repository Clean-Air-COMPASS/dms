"""Auditable, offline checks against the one-time public catalog investigation."""
import json
import math
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

import models
from reference_data.regions import validate_south_america_reference_coordinates
from sources.airgradient import importer
from tests.test_airgradient_reference_locations import (
    _mock_direct_location_requests, _provider_payloads, _reference_session,
)


@pytest.fixture(autouse=True)
def isolate_dashboard_snapshot_contract(monkeypatch):
    """This suite exercises Dashboard snapshots; Map history has its own suite."""
    monkeypatch.setattr(importer, "import_location_history", lambda *args, **kwargs: None)


CAPTURE = json.loads((Path(__file__).parent / "fixtures/airgradient/south_america_reference_20260915.json").read_text(encoding="utf-8"))


def _distance_from_rio(latitude, longitude):
    lat1, lon1, lat2, lon2 = map(math.radians, [-22.9068, -43.1729, latitude, longitude])
    haversine = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(haversine))


def test_selected_stable_id_is_nearest_verified_active_public_candidate():
    reference = next(r for r in importer.AIRGRADIENT_REFERENCE_LOCATIONS if r["code"] == "south_america_rio_reference")
    assert reference["location_id"] == CAPTURE["selected_location_id"] == "175911"
    distances = []
    for candidate in CAPTURE["candidates"]:
        location = candidate["payload"]
        assert candidate["http_status"] == 200
        assert location["offline"] is False
        age = datetime.fromisoformat(CAPTURE["captured_at"]) - datetime.fromisoformat(location["timestamp"])
        assert 0 <= age.total_seconds() <= CAPTURE["active_max_age_seconds"]
        assert isinstance(location["pm02"], (float, int))
        distance = _distance_from_rio(location["latitude"], location["longitude"])
        assert distance == pytest.approx(candidate["distance_km"])
        distances.append((distance, str(location["locationId"])))
    assert min(distances)[1] == reference["location_id"]
    # No catalog entry inside the search envelope was closer, including any
    # excluded Caribbean point. Individual endpoint verification stopped at five.
    assert CAPTURE["ranked_catalog"][0]["location_id"] == 175911
    for candidate in CAPTURE["ranked_catalog"]:
        assert _distance_from_rio(candidate["latitude"], candidate["longitude"]) >= min(distances)[0]
    selected = CAPTURE["candidates"][0]
    assert selected["country"] == "Brazil"
    assert selected["payload"]["locationName"] == "São Paulo"
    assert min(distances)[0] == pytest.approx(366.003, abs=0.001)
    validate_south_america_reference_coordinates("175911", selected["payload"]["latitude"], selected["payload"]["longitude"])
    assert set(importer._preferred_present_supported_fields(selected["payload"])) == {
        "pm1", "pm25", "pm10", "temperature", "relative_humidity", "co2", "tvoc", "tvoc_index", "nox_index",
    }


@pytest.mark.parametrize("latitude,longitude", [
    (46.886025, 8.536893),  # Switzerland
    (-22.9068, -43.1729),  # Rio is in South America but is not this provider site
    (10.6588, -61.5108),  # Caribbean, inside a naive continent rectangle
    (-25, -40),  # Ocean, also inside that rectangle
    (None, None), (float("nan"), -46.6643635),
])
@pytest.mark.parametrize("existing", [False, True])
def test_south_america_coordinate_mismatch_rejected_before_create_or_update(tmp_path, monkeypatch, latitude, longitude, existing):
    session, source = _reference_session(tmp_path)
    payloads = _provider_payloads()
    original = payloads["175911"]
    if existing:
        importer._ensure_reference_device(session, original, source.external_api_id, "175911", "America/Sao_Paulo")
        session.commit()
    payloads["175911"] = {**original, "latitude": latitude, "longitude": longitude}
    _mock_direct_location_requests(monkeypatch, payloads, [])
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: None)
    result = importer._initialize_reference_locations(session, source, "key", importer.DEFAULT_BASE_URL, force=True)
    failure = result["locations_failed"][0]
    assert failure["location_id"] == "175911"
    assert failure["region"] == "south_america_rio_reference"
    assert failure["reason"]
    device = session.scalar(select(models.Device).where(models.Device.external_id == "175911"))
    if existing:
        assert (device.latitude, device.longitude) == (-23.6473149, -46.6643635)
        assert device.name == "São Paulo"
    else:
        assert device is None
    session.close()


def test_south_america_rejects_wrong_provider_location_id(tmp_path):
    session, source = _reference_session(tmp_path)
    location = {**_provider_payloads()["175911"], "locationId": 2295}
    with pytest.raises(importer.AirGradientImporterError, match="mismatched locationId"):
        importer._ensure_reference_device(session, location, source.external_api_id, "175911", "America/Sao_Paulo")
    session.close()


@pytest.mark.parametrize("explicit_success_ids", [False, True])
def test_v2_upgrade_adds_south_america_without_recreating_deleted_ny_manila(tmp_path, monkeypatch, explicit_success_ids):
    session, source = _reference_session(tmp_path)
    source.params = {"reference_locations_version": "2026-09-11-v2"}
    if explicit_success_ids:
        source.params = {**source.params, "reference_locations_initialized_ids": ["58376", "160791"]}
    session.commit()
    calls = []
    _mock_direct_location_requests(monkeypatch, _provider_payloads(), calls)
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: None)
    result = importer._initialize_reference_locations(session, source, "key", importer.DEFAULT_BASE_URL)
    assert result["devices_created"] == 1
    assert calls == [f"{importer.DEFAULT_BASE_URL}/world/locations/175911/measures/current"]
    assert set(session.scalars(select(models.Device.external_id))) == {"175911"}
    assert importer._initialize_reference_locations(session, source, "key", importer.DEFAULT_BASE_URL)["attempted"] is False
    session.close()
