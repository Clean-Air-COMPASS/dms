from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import models
from reference_data.fixture_io import read_fixture_manifest, read_fixture_measurements
from reference_data.loader import load_reference_fixture
from reference_data.openaq_history_capture import (
    ABSOLUTE_REQUEST_CEILING,
    APPROVED_SENSOR_IDS,
    MAX_PAGES_PER_SENSOR,
    OPENAQ_MEASUREMENTS_ENDPOINT_TEMPLATE,
    OpenAQHistoryCaptureError,
    _normalize_measurement,
    _qualify_temporal_metadata,
    build_dry_run_report,
    execute_bounded_capture,
    request_ceiling_blocker,
)


PUBLIC_ROOT = Path(__file__).parent / "fixtures" / "reference_data" / "public" / "openaq"
PLAN_PATH = PUBLIC_ROOT / "history_capture_plan.json"


def _copy_capture_inputs(tmp_path: Path) -> Path:
    root = tmp_path / "openaq"
    root.mkdir(parents=True)
    shutil.copyfile(PLAN_PATH, root / PLAN_PATH.name)
    shutil.copyfile(
        PUBLIC_ROOT / "selected_reference_manifest.json",
        root / "selected_reference_manifest.json",
    )
    return root / PLAN_PATH.name


def _selected_entries() -> list[dict]:
    selection = json.loads(
        (PUBLIC_ROOT / "selected_reference_manifest.json").read_text(encoding="utf-8")
    )
    entries = []
    for area in selection["reference_areas"]:
        for location in area["selected_locations"]:
            for sensor in location["selected_sensors"]:
                entries.append(
                    {
                        "reference_area_code": area["reference_area_code"],
                        "location": location,
                        "sensor": sensor,
                    }
                )
    return entries


def _provider_measurement(entry: dict, *, value: float = 7.25, end: str = "2026-08-01T01:00:00Z") -> dict:
    sensor = entry["sensor"]
    return {
        "value": value,
        "flagInfo": {"hasFlags": False},
        "parameter": {
            "id": sensor["openaq_parameter_id"],
            "name": sensor["openaq_parameter_name"],
            "units": sensor["provider_unit"],
            "displayName": sensor["openaq_parameter_display_name"],
        },
        "period": {
            "label": "1 hour",
            "interval": "01:00:00",
            "datetimeFrom": {"utc": "2026-08-01T00:00:00Z", "local": "2026-08-01T00:00:00+00:00"},
            "datetimeTo": {"utc": end, "local": end.replace("Z", "+00:00")},
        },
        "coordinates": entry["location"]["coordinates"],
        "summary": {"min": value, "max": value, "avg": value, "sd": 0.0},
        "coverage": {"expectedCount": 1, "observedCount": 1, "percentComplete": 100.0},
    }


def test_mandatory_dry_run_is_local_only_complete_and_does_not_read_credentials(monkeypatch):
    calls = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("dry run touched the request executor")

    def reject_environment_read(name, default=None):
        raise AssertionError(f"dry run read environment variable {name}")

    monkeypatch.setattr(os, "getenv", reject_environment_read)
    report = build_dry_run_report(PLAN_PATH, request_executor=fail_if_called)

    assert calls == []
    assert report["network_requests_executed"] == 0
    assert report["credentials_read"] is False
    assert report["selected_sensor_count"] == 13
    assert report["openaq_absolute_request_ceiling"] == 143
    assert report["retry_count"] == 0
    assert report["direct_provider_request_counts"] == {"PurpleAir": 0, "AirGradient": 0}
    assert report["paid_provider_status"]["expected_point_spend"] == 0
    assert [request["openaq_sensor_id"] for request in report["requests"]] == list(APPROVED_SENSOR_IDS)
    assert all(request["maximum_pages"] == 11 for request in report["requests"])
    assert all(request["window_end_exclusive"] == "2026-08-08T00:00:00Z" for request in report["requests"])


def test_next_request_is_refused_at_global_or_per_sensor_ceiling():
    assert request_ceiling_blocker(142, 10) is None
    assert request_ceiling_blocker(143, 0) == "global_request_ceiling_reached"
    assert request_ceiling_blocker(0, 11) == "per_sensor_request_ceiling_reached"


def test_dry_run_cli_subprocess_remains_zero_network_with_all_transports_patched():
    patch_and_run = r'''
import httpx, requests, runpy, socket, sys
def blocked(*args, **kwargs):
    raise AssertionError("network transport touched")
async def blocked_async(*args, **kwargs):
    raise AssertionError("async network transport touched")
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
requests.sessions.Session.request = blocked
httpx.HTTPTransport.handle_request = blocked
httpx.AsyncHTTPTransport.handle_async_request = blocked_async
sys.argv = ["openaq_history_capture", "--plan", sys.argv[1], "--dry-run"]
runpy.run_module("reference_data.openaq_history_capture", run_name="__main__")
'''
    environment = os.environ.copy()
    environment["COMPASSAQ_ENV"] = "test"
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, "-c", patch_and_run, str(PLAN_PATH.resolve())],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["network_requests_executed"] == 0


def test_execution_uses_only_allowlisted_sensor_endpoints_and_preserves_provider_values(tmp_path):
    plan_path = _copy_capture_inputs(tmp_path)
    entry_by_sensor = {int(entry["sensor"]["openaq_sensor_id"]): entry for entry in _selected_entries()}
    calls = []

    def executor(endpoint, query, headers):
        calls.append((endpoint, dict(query), dict(headers)))
        sensor_id = int(endpoint.split("/")[-2])
        assert sensor_id in APPROVED_SENSOR_IDS
        assert endpoint == OPENAQ_MEASUREMENTS_ENDPOINT_TEMPLATE.format(sensor_id=sensor_id)
        assert query == {
            "datetime_from": "2026-08-01T00:00:00Z",
            "datetime_to": "2026-08-08T00:00:00Z",
            "limit": 1000,
            "page": 1,
        }
        return {"meta": {"found": 1}, "results": [_provider_measurement(entry_by_sensor[sensor_id])]}

    report = execute_bounded_capture(plan_path, "mock-key", executor)

    assert report["network_requests_executed"] == 13
    assert len(calls) == 13
    assert all(call[2] == {"X-API-Key": "mock-key"} for call in calls)
    assert all("/locations" not in call[0] and "/latest" not in call[0] for call in calls)
    assert report["direct_provider_request_counts"] == {"PurpleAir": 0, "AirGradient": 0}
    assert report["purpleair_point_spend"] == 0
    manifest = read_fixture_manifest(plan_path.parent)
    measurements = read_fixture_measurements(plan_path.parent, manifest)
    assert len(measurements) == 13
    assert {measurement.value for measurement in measurements} == {7.25}
    assert all(measurement.provider_period["interval"] == "01:00:00" for measurement in measurements)
    assert {sensor.aggregation_period_code for sensor in manifest.sensors} == {"1h"}


def test_failed_sensor_is_not_retried_and_other_approved_sensors_continue(tmp_path):
    plan_path = _copy_capture_inputs(tmp_path)
    entry_by_sensor = {int(entry["sensor"]["openaq_sensor_id"]): entry for entry in _selected_entries()}
    calls = []

    def executor(endpoint, query, headers):
        sensor_id = int(endpoint.split("/")[-2])
        calls.append(sensor_id)
        if sensor_id == APPROVED_SENSOR_IDS[0]:
            raise RuntimeError("synthetic provider failure")
        return {"meta": {"found": 1}, "results": [_provider_measurement(entry_by_sensor[sensor_id])]}

    report = execute_bounded_capture(plan_path, "mock-key", executor)

    assert len(calls) == 13
    assert calls.count(APPROVED_SENSOR_IDS[0]) == 1
    assert report["retry_count"] == 0
    first = report["sensor_results"][0]
    assert first["completion_status"] == "failed_without_retry"
    assert "synthetic provider failure" in first["failure_reason"]


def test_per_sensor_pagination_ceiling_stops_without_a_twelfth_request(tmp_path):
    plan_path = _copy_capture_inputs(tmp_path)
    entry_by_sensor = {int(entry["sensor"]["openaq_sensor_id"]): entry for entry in _selected_entries()}
    calls = []

    def executor(endpoint, query, headers):
        sensor_id = int(endpoint.split("/")[-2])
        calls.append((sensor_id, query["page"]))
        row = _provider_measurement(entry_by_sensor[sensor_id])
        if sensor_id == APPROVED_SENSOR_IDS[0]:
            return {"meta": {"found": 50000}, "results": [row] * 1000}
        return {"meta": {"found": 0}, "results": []}

    report = execute_bounded_capture(plan_path, "mock-key", executor)

    first_calls = [page for sensor_id, page in calls if sensor_id == APPROVED_SENSOR_IDS[0]]
    assert first_calls == list(range(1, MAX_PAGES_PER_SENSOR + 1))
    assert report["network_requests_executed"] == 11 + 12
    assert report["network_requests_executed"] <= ABSOLUTE_REQUEST_CEILING
    assert report["sensor_results"][0]["completion_status"] == "stopped_at_per_sensor_request_ceiling"


def test_fixture_measurement_serialization_is_deterministic_for_identical_responses(tmp_path):
    entry_by_sensor = {int(entry["sensor"]["openaq_sensor_id"]): entry for entry in _selected_entries()}

    def executor(endpoint, query, headers):
        sensor_id = int(endpoint.split("/")[-2])
        return {"meta": {"found": 1}, "results": [_provider_measurement(entry_by_sensor[sensor_id])]}

    first_plan = _copy_capture_inputs(tmp_path / "first")
    second_plan = _copy_capture_inputs(tmp_path / "second")
    execute_bounded_capture(first_plan, "mock-key", executor)
    execute_bounded_capture(second_plan, "mock-key", executor)

    assert (first_plan.parent / "measurements.jsonl").read_bytes() == (
        second_plan.parent / "measurements.jsonl"
    ).read_bytes()


def test_exact_timestamp_duplicates_remain_distinct_fixture_records(tmp_path):
    plan_path = _copy_capture_inputs(tmp_path)
    entry_by_sensor = {int(entry["sensor"]["openaq_sensor_id"]): entry for entry in _selected_entries()}

    def executor(endpoint, query, headers):
        sensor_id = int(endpoint.split("/")[-2])
        if sensor_id == APPROVED_SENSOR_IDS[0]:
            row = _provider_measurement(entry_by_sensor[sensor_id])
            return {"meta": {"found": 2}, "results": [row, row]}
        return {"meta": {"found": 0}, "results": []}

    report = execute_bounded_capture(plan_path, "mock-key", executor)
    manifest = read_fixture_manifest(plan_path.parent)
    measurements = read_fixture_measurements(plan_path.parent, manifest)

    assert len(measurements) == 2
    assert measurements[0].observed_at == measurements[1].observed_at
    assert measurements[0].provider_observation_ref != measurements[1].provider_observation_ref
    assert report["sensor_results"][0]["exact_timestamp_duplicate_count"] == 1


def test_unknown_sensor_or_changed_selection_is_rejected_before_executor(tmp_path):
    plan_path = _copy_capture_inputs(tmp_path)
    selection_path = plan_path.parent / "selected_reference_manifest.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["reference_areas"][0]["selected_locations"][0]["selected_sensors"][0]["openaq_sensor_id"] = 999999999
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    calls = []

    with pytest.raises(OpenAQHistoryCaptureError, match="checksum mismatch"):
        execute_bounded_capture(plan_path, "mock-key", lambda *args: calls.append(args))
    assert calls == []


def test_existing_frozen_output_blocks_refresh_before_executor(tmp_path):
    plan_path = _copy_capture_inputs(tmp_path)
    (plan_path.parent / "manifest.json").write_text("already frozen", encoding="utf-8")
    calls = []

    with pytest.raises(OpenAQHistoryCaptureError, match="automatic refresh and overwrite"):
        execute_bounded_capture(plan_path, "mock-key", lambda *args: calls.append(args))
    assert calls == []


def test_provider_period_controls_timestamp_and_unknown_timing_is_not_invented():
    entry = _selected_entries()[0]
    raw = _provider_measurement(entry, value=12.345678)
    row = _normalize_measurement(raw, entry, page=3, result_index=7)

    assert row["observed_at"] == "2026-08-01T01:00:00Z"
    assert row["value"] == 12.345678
    assert row["provider_parameter"]["units"] == entry["sensor"]["provider_unit"]
    assert row["provider_observation_ref"].endswith("page-3:result-7")
    row_without_interval = dict(row)
    row_without_interval["_explicit_interval_seconds"] = None
    qualification = _qualify_temporal_metadata([row_without_interval])
    assert qualification["status"] == "unknown_or_inconsistent"
    assert qualification["provider_interval_seconds"] is None


def test_end_exclusive_boundary_is_locally_excluded():
    entry = _selected_entries()[0]
    raw = _provider_measurement(entry, end="2026-08-08T00:00:00Z")
    raw["period"]["datetimeFrom"] = {
        "utc": "2026-08-07T23:00:00Z",
        "local": "2026-08-07T23:00:00+00:00",
    }
    assert _normalize_measurement(raw, entry, page=1, result_index=0) is None


def test_checked_in_fixture_is_loader_compatible_and_contains_no_expected_results():
    manifest_path = PUBLIC_ROOT / "manifest.json"
    measurements_path = PUBLIC_ROOT / "measurements.jsonl"
    if not manifest_path.exists() or not measurements_path.exists():
        pytest.skip("bounded live capture has not been run yet")
    manifest = read_fixture_manifest(PUBLIC_ROOT)
    measurements = read_fixture_measurements(PUBLIC_ROOT, manifest)
    assert len(manifest.sensors) == 13
    assert manifest.capture.absolute_request_ceiling == 143
    assert manifest.capture.request_count <= 143
    assert manifest.coverage_gaps["metro_manila"] == {
        "pm10": "no_recent_compatible_openaq_sensor_in_approved_radius",
        "o3": "no_compatible_openaq_sensor_in_approved_radius",
        "no2": "no_compatible_openaq_sensor_in_approved_radius",
        "so2": "no_compatible_openaq_sensor_in_approved_radius",
        "co": "no_compatible_openaq_sensor_in_approved_radius",
    }
    assert all(
        "2026-08-01T00:00:00+00:00" <= measurement.observed_at.isoformat()
        < "2026-08-08T00:00:00+00:00"
        for measurement in measurements
    )
    assert not (PUBLIC_ROOT / "expected_results.json").exists()


def test_checked_in_fixture_smoke_loads_idempotently_into_isolated_database(tmp_path):
    if not (PUBLIC_ROOT / "manifest.json").exists():
        pytest.skip("bounded live capture has not been run yet")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'openaq-fixture.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    units = {
        "ug_m3": models.Unit(code="ug_m3", symbol="µg/m³", name="Micrograms per cubic meter"),
        "ppm": models.Unit(code="ppm", symbol="ppm", name="Parts per million"),
    }
    session.add_all(units.values())
    session.flush()
    for code in ("pm25", "pm10", "o3", "no2", "so2", "co"):
        default_unit = units["ug_m3"] if code in {"pm25", "pm10"} else units["ppm"]
        session.add(
            models.Parameter(
                code=code,
                display_name=code.upper(),
                default_unit_id=default_unit.unit_id,
            )
        )
    session.add(
        models.AggregationPeriod(
            code="1h",
            display_name="1 Hour",
            duration_minutes=60,
            is_rolling=False,
        )
    )
    session.commit()

    first = load_reference_fixture(session, PUBLIC_ROOT)
    second = load_reference_fixture(session, PUBLIC_ROOT)

    assert first.inserted == 1 + 4 + 13 + 1939
    assert second.inserted == 0
    assert second.updated == 0
    assert second.skipped == 1 + 4 + 13 + 1939
    assert session.scalar(select(func.count(models.Measurement.measurement_id))) == 1939
    loaded = session.scalar(select(models.Measurement).order_by(models.Measurement.measurement_id))
    assert loaded.qc_flags["reference_fixture_provider_capture"]["provider_period"]["interval"] == "01:00:00"
    source = session.scalar(select(models.ExternalAPI).where(models.ExternalAPI.name == "OpenAQ"))
    assert source.enabled is False
    assert source.params["fixture_capture"]["request_count"] == 13
    manila_device = session.scalar(
        select(models.Device).where(models.Device.external_id == "openaq-location-4565934")
    )
    manila_sensor = session.scalar(
        select(models.Sensor).where(models.Sensor.device_id == manila_device.device_id)
    )
    assert source.params["fixture_provider_chain"][2] == {
        "provider": "AirGradient",
        "role": "hardware",
    }
    assert first.device_ids["openaq-location-4565934"] == manila_device.device_id
    assert first.sensor_ids["openaq-sensor-13191003"] == manila_sensor.sensor_id
    assert session.get(models.Unit, manila_sensor.unit_id).code == "ug_m3"
    assert session.get(
        models.AggregationPeriod, manila_sensor.aggregation_period_id
    ).code == "1h"
    loaded_sensors = session.scalars(
        select(models.Sensor).order_by(models.Sensor.external_sensor_id)
    ).all()
    active_hourly_sensors = [
        sensor
        for sensor in loaded_sensors
        if sensor.external_sensor_id != "1099"
    ]
    assert len(active_hourly_sensors) == 12
    assert all(
        sensor.hourly_concentration_provenance
        == "provider_reported_hourly_average"
        for sensor in active_hourly_sensors
    )
    assert all(
        sensor.hourly_timestamp_semantics == "hour_end"
        for sensor in active_hourly_sensors
    )
    zero_row_sensor = next(
        sensor for sensor in loaded_sensors if sensor.external_sensor_id == "1099"
    )
    assert zero_row_sensor.hourly_concentration_provenance is None
    assert zero_row_sensor.hourly_timestamp_semantics is None
    session.close()
