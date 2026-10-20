from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from reference_data.openaq_discovery import (
    OPENAQ_LOCATIONS_ENDPOINT,
    OpenAQDiscoveryError,
    _minimal_location,
    build_dry_run_report,
    evaluate_sensor_compatibility,
    execute_bounded_discovery,
    select_reference_candidates,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "reference_data"
PLAN_PATH = FIXTURE_ROOT / "public" / "openaq" / "discovery_plan.json"
MOCK_RESPONSE_PATH = (
    FIXTURE_ROOT / "synthetic" / "openaq_discovery" / "locations_response.json"
)


def _mock_staging_payload() -> dict:
    raw = json.loads(MOCK_RESPONSE_PATH.read_text(encoding="utf-8"))
    return {
        "schema_version": "2i.3",
        "provider": "OpenAQ",
        "reference_area_code": "synthetic_area",
        "reference_area_name": "Synthetic reference area",
        "timezone_reference": "UTC",
        "request": {
            "endpoint": OPENAQ_LOCATIONS_ENDPOINT,
            "query": {"coordinates": "0,0", "radius": 25000},
            "executed_at": "2026-08-01T00:00:00Z",
        },
        "response_meta": {"page": 1, "limit": 1000, "found": 4, "returned": 4},
        "locations": [_minimal_location(location) for location in raw["results"]],
    }


def test_dry_run_has_zero_requests_and_exact_approved_ceiling(monkeypatch):
    def reject_environment_read(name, default=None):
        raise AssertionError(f"dry run must not read environment variable {name}")

    monkeypatch.setattr("os.getenv", reject_environment_read)
    report = build_dry_run_report(PLAN_PATH)

    assert report["network_requests_executed"] == 0
    assert report["expected_request_count"] == 3
    assert report["absolute_request_ceiling"] == 3
    assert report["retry_count"] == 0
    assert {request["endpoint"] for request in report["requests"]} == {
        OPENAQ_LOCATIONS_ENDPOINT
    }
    assert all(request["maximum_pages"] == 1 for request in report["requests"])


def test_test_environment_rejects_real_discovery_transport(monkeypatch):
    monkeypatch.setenv("COMPASSAQ_ENV", "test")
    with pytest.raises(OpenAQDiscoveryError, match="blocked in the test environment"):
        execute_bounded_discovery(PLAN_PATH, api_key="mock-openaq-key")


def test_execute_uses_only_three_openaq_location_requests_and_no_retries(tmp_path):
    copied_root = tmp_path / "openaq"
    copied_root.mkdir()
    copied_plan = copied_root / "discovery_plan.json"
    shutil.copyfile(PLAN_PATH, copied_plan)
    mock_payload = json.loads(MOCK_RESPONSE_PATH.read_text(encoding="utf-8"))
    calls = []

    def fake_executor(endpoint, query, headers):
        calls.append((endpoint, query, headers))
        assert endpoint == OPENAQ_LOCATIONS_ENDPOINT
        assert "measurements" not in endpoint
        assert "purpleair" not in endpoint.lower()
        assert "airgradient" not in endpoint.lower()
        return mock_payload

    report = execute_bounded_discovery(
        copied_plan,
        api_key="mock-openaq-key",
        request_executor=fake_executor,
    )

    assert report["network_requests_executed"] == 3
    assert len(calls) == 3
    assert report["retry_count"] == 0
    assert all(call[2] == {"X-API-Key": "mock-openaq-key"} for call in calls)


def test_plan_refuses_a_lower_or_expandable_request_ceiling(tmp_path):
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    plan["absolute_request_ceiling"] = 2
    invalid_plan = tmp_path / "invalid-plan.json"
    invalid_plan.write_text(json.dumps(plan), encoding="utf-8")
    calls = []

    with pytest.raises(OpenAQDiscoveryError, match="exactly 3"):
        execute_bounded_discovery(
            invalid_plan,
            api_key="mock-openaq-key",
            request_executor=lambda *args: calls.append(args),
        )
    assert calls == []


def test_parameter_compatibility_never_maps_ambiguous_identity_or_unit():
    assert evaluate_sensor_compatibility(
        {"id": 1, "parameter": {"name": "no2", "units": "ppb"}}
    )["compatibility_status"] == "compatible"
    nox = evaluate_sensor_compatibility(
        {"id": 2, "parameter": {"name": "nox", "units": "ppb"}}
    )
    ozone_proxy = evaluate_sensor_compatibility(
        {"id": 3, "parameter": {"name": "tvoc", "units": "ppb"}}
    )
    unknown_unit = evaluate_sensor_compatibility(
        {"id": 4, "parameter": {"name": "o3", "units": "mystery"}}
    )
    assert (nox["parameter_code"], nox["exclusion_reason"]) == (
        None,
        "unsupported_parameter",
    )
    assert ozone_proxy["parameter_code"] is None
    assert unknown_unit["exclusion_reason"] == "unsupported_unit"


def test_candidate_selection_is_deterministic_and_preserves_provenance():
    staging = _mock_staging_payload()
    first = select_reference_candidates(staging)
    second = select_reference_candidates(staging)

    assert first == second
    assert [
        location["openaq_location_id"] for location in first["selected_locations"]
    ] == [990002, 990001, 990003]
    sensor_ids = {
        sensor["openaq_sensor_id"]
        for location in first["selected_locations"]
        for sensor in location["selected_sensors"]
    }
    assert sensor_ids == {991001, 992001, 992002, 992003, 993001, 993002}
    assert all(
        location["transport_provider"] == "OpenAQ"
        for location in first["selected_locations"]
    )
    assert first["coverage"] == {
        "pm25": True,
        "pm10": True,
        "o3": True,
        "no2": True,
        "so2": True,
        "co": True,
    }
    assert all(
        sensor["native_temporal_metadata"]["status"]
        == "not_provided_by_location_discovery"
        for location in first["selected_locations"]
        for sensor in location["selected_sensors"]
    )


def test_airgradient_attribution_and_unsupported_records_are_explicit():
    selection = select_reference_candidates(_mock_staging_payload())
    airgradient = next(
        candidate
        for candidate in selection["candidate_locations"]
        if candidate["openaq_location_id"] == 990001
    )
    assert airgradient["transport_provider"] == "OpenAQ"
    assert airgradient["hardware_provider"] == "AirGradient"
    assert airgradient["airgradient_metadata_evidence"] == [
        "instrument:AirGradient Synthetic Model"
    ]
    exclusions = {
        sensor["exclusion_reason"] for sensor in airgradient["unsuitable_sensors"]
    }
    assert exclusions == {"unsupported_parameter", "unsupported_unit"}


def test_gap_and_no_airgradient_status_are_explicit():
    staging = _mock_staging_payload()
    staging["locations"] = [
        location for location in staging["locations"] if location["id"] == 990002
    ]
    selection = select_reference_candidates(staging)

    assert selection["gaps"] == {
        "pm25": "no_compatible_openaq_sensor_in_approved_radius",
        "so2": "no_compatible_openaq_sensor_in_approved_radius",
        "co": "no_compatible_openaq_sensor_in_approved_radius",
    }
    assert selection["airgradient_status"] == (
        "no_confirmed_public_airgradient_device_in_reference_area"
    )


def test_stale_compatible_sensor_is_an_explicit_recent_data_gap():
    staging = _mock_staging_payload()
    staging["locations"] = [
        location for location in staging["locations"] if location["id"] == 990004
    ]
    selection = select_reference_candidates(staging)

    assert selection["selected_locations"] == []
    assert selection["gaps"]["pm10"] == (
        "no_recent_compatible_openaq_sensor_in_approved_radius"
    )
    assert selection["gaps"]["o3"] == (
        "no_recent_compatible_openaq_sensor_in_approved_radius"
    )


def test_checked_in_discovery_manifest_preserves_reviewed_ids_and_capture_boundary():
    public_root = FIXTURE_ROOT / "public" / "openaq"
    manifest = json.loads(
        (public_root / "selected_reference_manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["measurement_capture_performed"] is False
    assert manifest["phase_2i4_request_estimate"]["requires_separate_phase_2i4_approval"] is True
    assert manifest["phase_2i4_request_estimate"]["selected_sensor_count"] == 13
    assert manifest["phase_2i4_request_estimate"]["conservative_expected_request_count"] == 143

    expected_location_ids = {
        "new_york": [971, 626],
        "rio_de_janeiro": [820326],
        "metro_manila": [4565934],
    }
    expected_sensor_ids = {
        "new_york": {1758, 3951, 3950, 3952, 1099, 1098},
        "rio_de_janeiro": {6819305, 4475454, 6459542, 4475455, 11268993, 4475449},
        "metro_manila": {13191003},
    }
    for area in manifest["reference_areas"]:
        area_code = area["reference_area_code"]
        assert [
            location["openaq_location_id"]
            for location in area["selected_locations"]
        ] == expected_location_ids[area_code]
        assert {
            sensor["openaq_sensor_id"]
            for location in area["selected_locations"]
            for sensor in location["selected_sensors"]
        } == expected_sensor_ids[area_code]

    for area_code in expected_location_ids:
        staged = json.loads(
            (public_root / "staging" / f"{area_code}.json").read_text(encoding="utf-8")
        )
        assert staged["request"]["endpoint"] == OPENAQ_LOCATIONS_ENDPOINT
        assert staged["response_meta"]["result_truncated_by_request_ceiling"] is False
        assert "/measurements" not in json.dumps(staged).lower()
