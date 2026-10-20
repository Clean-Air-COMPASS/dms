from __future__ import annotations

import json
import os
from datetime import datetime, timezone
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
from reference_data.purpleair_history_capture import (
    ACCESS_CLASSIFICATION,
    APPROVED_FIELDS,
    APPROVED_MANIFEST_SHA256,
    APPROVED_MAX_POINTS,
    APPROVED_SENSOR_IDS,
    APPROVED_WINDOW_END,
    APPROVED_WINDOW_START,
    EXPECTED_POINTS,
    HISTORY_ENDPOINT_TEMPLATE,
    PaidProviderAuthorization,
    PurpleAirHistoryCaptureError,
    build_dry_run_report,
    execute_bounded_capture,
    validate_execution_authorization,
)
from services.provider_safety import paid_provider_request_scope


SOURCE_ROOT = (
    Path(__file__).parent
    / "fixtures"
    / "reference_data"
    / "restricted"
    / "purpleair"
)
SOURCE_MANIFEST = SOURCE_ROOT / "capture_manifest.json"
FROZEN_MANIFEST = SOURCE_ROOT / "manifest.json"
ORIGINAL_FROZEN_ROOT = SOURCE_ROOT / "capture_history" / "phase_2i4c"


def _copy_capture_root(tmp_path: Path) -> Path:
    root = tmp_path / "reference_data" / "restricted" / "purpleair"
    root.mkdir(parents=True)
    shutil.copyfile(SOURCE_MANIFEST, root / SOURCE_MANIFEST.name)
    return root / SOURCE_MANIFEST.name


def _payload(sensor_index: int) -> dict:
    # Distinct constant values make exact provider-value preservation obvious.
    return {
        "sensor_index": sensor_index,
        "fields": list(APPROVED_FIELDS),
        "data": [
            [1786147200, 7.25, 12.5],
            [1786147320, 7.5, 12.75],
        ],
    }


def _authorization() -> PaidProviderAuthorization:
    return PaidProviderAuthorization(provider_name="purpleair", execution_mode="manual")


def _fixture_session(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'purpleair-fixture.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    unit = models.Unit(code="ug_m3", symbol="µg/m³", name="Micrograms per cubic meter")
    session.add(unit)
    session.flush()
    session.add_all(
        [
            models.Parameter(code="pm25", display_name="PM2.5", default_unit_id=unit.unit_id),
            models.Parameter(code="pm10", display_name="PM10", default_unit_id=unit.unit_id),
            models.AggregationPeriod(
                code="2m", display_name="2 Minutes", duration_minutes=2, is_rolling=False
            ),
        ]
    )
    session.commit()
    return session


def test_dry_run_is_exact_local_only_and_does_not_read_credentials(monkeypatch):
    calls = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("dry run touched a request executor")

    def reject_environment_read(name, default=None):
        raise AssertionError(f"dry run read environment variable {name}")

    monkeypatch.setattr(os, "getenv", reject_environment_read)
    report = build_dry_run_report(SOURCE_MANIFEST, fail_if_called)

    assert calls == []
    assert report["credentials_read"] is False
    assert report["network_requests_executed"] == 0
    assert report["authorization_manifest_sha256"] == APPROVED_MANIFEST_SHA256
    assert report["approved_sensor_ids"] == list(APPROVED_SENSOR_IDS)
    assert report["request_ceiling"] == 3
    assert report["expected_points"] == EXPECTED_POINTS == 25926
    assert report["approved_max_points"] == APPROVED_MAX_POINTS == 28519
    assert all(request["maximum_expected_provider_rows"] == 2160 for request in report["requests"])


def test_dry_run_cli_remains_zero_network_with_all_transports_patched():
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
sys.argv = ["purpleair_history_capture", "--manifest", sys.argv[1], "--dry-run"]
runpy.run_module("reference_data.purpleair_history_capture", run_name="__main__")
'''
    environment = os.environ.copy()
    environment["COMPASSAQ_ENV"] = "test"
    environment["ENABLE_PAID_API_IMPORTS"] = "false"
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, "-c", patch_and_run, str(SOURCE_MANIFEST.resolve())],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["network_requests_executed"] == 0


def test_all_execution_confirmations_and_exact_ceiling_are_required():
    valid = {
        "allow_provider_api": True,
        "allow_paid_api": True,
        "confirm_manifest_sha": APPROVED_MANIFEST_SHA256,
        "max_purpleair_points": APPROVED_MAX_POINTS,
        "confirm_bounded_history": True,
    }
    validate_execution_authorization(**valid)
    for field, invalid_value in (
        ("allow_provider_api", False),
        ("allow_paid_api", False),
        ("confirm_manifest_sha", "wrong"),
        ("max_purpleair_points", APPROVED_MAX_POINTS + 1),
        ("confirm_bounded_history", False),
    ):
        changed = {**valid, field: invalid_value}
        with pytest.raises(PurpleAirHistoryCaptureError):
            validate_execution_authorization(**changed)


def test_mocked_capture_uses_three_exact_requests_and_publishes_valid_restricted_fixture(tmp_path):
    manifest_path = _copy_capture_root(tmp_path)
    calls = []

    def executor(endpoint, query, headers):
        calls.append((endpoint, dict(query), dict(headers)))
        sensor_id = endpoint.split("/")[-2]
        return _payload(int(sensor_id))

    authorization = _authorization()
    report = execute_bounded_capture(
        manifest_path,
        "mock-key",
        authorization=authorization,
        request_executor=executor,
        request_scope=paid_provider_request_scope(authorization),
    )

    assert len(calls) == 3
    assert [call[0] for call in calls] == [
        HISTORY_ENDPOINT_TEMPLATE.format(sensor_id=sensor_id)
        for sensor_id in APPROVED_SENSOR_IDS
    ]
    assert all(
        call[1]
        == {
            "start_timestamp": 1786147200,
            "end_timestamp": 1786406400,
            "fields": "pm2.5_atm,pm10.0_atm",
            "average": 0,
        }
        for call in calls
    )
    assert all(call[2] == {"X-API-Key": "mock-key"} for call in calls)
    assert report["network_requests_executed"] == 3
    assert report["provider_rows_returned"] == 6
    assert report["measurement_rows_preserved"] == 12
    assert report["pm25_measurement_rows"] == 6
    assert report["pm10_measurement_rows"] == 6
    assert report["point_accounting"]["calculated_from_returned_rows"] == 30
    assert report["access_classification"] == ACCESS_CLASSIFICATION

    fixture_root = manifest_path.parent
    manifest = read_fixture_manifest(fixture_root)
    measurements = read_fixture_measurements(fixture_root, manifest)
    assert len(manifest.devices) == 3
    assert len(manifest.sensors) == 6
    assert len(measurements) == 12
    assert {measurement.value for measurement in measurements} == {7.25, 7.5, 12.5, 12.75}
    assert all(measurement.provider_period is None for measurement in measurements)
    assert all(measurement.provider_timestamp is not None for measurement in measurements)
    assert manifest.license.redistribution_approved is False
    assert manifest.capture.request_count == 3
    assert not (fixture_root / "expected_results.json").exists()


def test_first_failure_stops_without_retry_and_preserves_only_completed_stage(tmp_path):
    manifest_path = _copy_capture_root(tmp_path)
    calls = []

    def executor(endpoint, query, headers):
        sensor_id = endpoint.split("/")[-2]
        calls.append(sensor_id)
        if sensor_id == "175407":
            raise RuntimeError("mock provider failure")
        return _payload(int(sensor_id))

    authorization = _authorization()
    with pytest.raises(RuntimeError, match="mock provider failure"):
        execute_bounded_capture(
            manifest_path,
            "mock-key",
            authorization=authorization,
            request_executor=executor,
            request_scope=paid_provider_request_scope(authorization),
        )

    assert calls == ["198733", "175407"]
    assert (manifest_path.parent / "capture_staging" / "sensor-198733.json").exists()
    assert not (manifest_path.parent / "capture_staging" / "sensor-175407.json").exists()
    assert not (manifest_path.parent / "manifest.json").exists()
    failure = json.loads(
        (manifest_path.parent / "capture_failure_report.json").read_text(encoding="utf-8")
    )
    assert failure["network_requests_executed"] == 2
    assert failure["failed_sensor_id"] == "175407"
    assert failure["failed_request_number"] == 2
    assert failure["failed_endpoint"] == HISTORY_ENDPOINT_TEMPLATE.format(
        sensor_id="175407"
    )
    assert failure["known_points_from_completed_responses"] == 10
    assert failure["maximum_points_if_failed_request_was_fully_charged"] == 8652
    assert failure["new_explicit_approval_required_before_any_additional_request"] is True
    assert failure["retry_count"] == 0


def test_mocked_fixture_loads_idempotently_into_isolated_database(tmp_path):
    manifest_path = _copy_capture_root(tmp_path)

    def executor(endpoint, query, headers):
        return _payload(int(endpoint.split("/")[-2]))

    authorization = _authorization()
    execute_bounded_capture(
        manifest_path,
        "mock-key",
        authorization=authorization,
        request_executor=executor,
        request_scope=paid_provider_request_scope(authorization),
    )
    session = _fixture_session(tmp_path)
    first = load_reference_fixture(session, manifest_path.parent)
    second = load_reference_fixture(session, manifest_path.parent)

    assert first.inserted == 1 + 3 + 6 + 12
    assert second.inserted == 0
    assert second.updated == 0
    assert second.skipped == 1 + 3 + 6 + 12
    assert session.scalar(select(func.count(models.Measurement.measurement_id))) == 12
    source = session.scalar(
        select(models.ExternalAPI).where(models.ExternalAPI.name == "PurpleAir")
    )
    assert source.enabled is False
    assert source.params["access_classification"] == ACCESS_CLASSIFICATION
    loaded = session.scalar(select(models.Measurement).order_by(models.Measurement.measurement_id))
    capture_metadata = loaded.qc_flags["reference_fixture_provider_capture"]
    assert capture_metadata["provider_field"] in APPROVED_FIELDS
    assert capture_metadata["provider_timestamp"] == 1786147200
    session.close()


def test_checked_in_restricted_capture_validates_and_loads_idempotently(tmp_path):
    fixture_root = (
        ORIGINAL_FROZEN_ROOT if ORIGINAL_FROZEN_ROOT.exists() else SOURCE_ROOT
    )
    if not (fixture_root / "manifest.json").exists():
        pytest.skip("bounded paid capture has not been run")
    manifest = read_fixture_manifest(fixture_root)
    measurements = read_fixture_measurements(fixture_root, manifest)
    report = json.loads((fixture_root / "capture_report.json").read_text(encoding="utf-8"))

    assert manifest.access_classification == ACCESS_CLASSIFICATION
    assert manifest.capture.selection_manifest_sha256 == APPROVED_MANIFEST_SHA256
    assert manifest.capture.request_count == 3
    assert manifest.capture.retry_count == 0
    assert manifest.capture.pricing["verified_at"] == "2026-08-11T21:25:00-07:00"
    assert manifest.capture.pricing["history_endpoint_base_points"] == 2
    assert [result["provider_sensor_id"] for result in manifest.capture.sensor_results] == list(
        APPROVED_SENSOR_IDS
    )
    assert len(measurements) == report["measurement_rows_preserved"]
    assert sum(measurement.provider_field == "pm2.5_atm" for measurement in measurements) == report[
        "pm25_measurement_rows"
    ]
    assert sum(
        measurement.provider_field == "pm10.0_atm" for measurement in measurements
    ) == report["pm10_measurement_rows"]
    assert all(
        APPROVED_WINDOW_START.replace("Z", "+00:00")
        <= measurement.observed_at.isoformat()
        < APPROVED_WINDOW_END.replace("Z", "+00:00")
        for measurement in measurements
    )
    assert report["point_accounting"]["calculated_from_returned_rows"] <= APPROVED_MAX_POINTS
    assert report["point_accounting"]["within_approved_hard_ceiling"] is True
    assert not (fixture_root / "expected_results.json").exists()

    session = _fixture_session(tmp_path)
    first = load_reference_fixture(session, fixture_root)
    second = load_reference_fixture(session, fixture_root)
    expected_rows = 1 + len(manifest.devices) + len(manifest.sensors) + len(measurements)
    assert first.inserted == expected_rows
    assert second.inserted == 0
    assert second.updated == 0
    assert second.skipped == expected_rows
    assert session.scalar(select(func.count(models.Measurement.measurement_id))) == len(
        measurements
    )
    loaded_devices = session.scalars(select(models.Device)).all()
    loaded_sensors = session.scalars(select(models.Sensor)).all()
    assert {device.external_id for device in loaded_devices} == set(APPROVED_SENSOR_IDS)
    assert len(loaded_sensors) == 6
    assert {
        session.get(models.Parameter, sensor.parameter_id).code
        for sensor in loaded_sensors
    } == {"pm25", "pm10"}
    assert all(
        session.get(models.AggregationPeriod, sensor.aggregation_period_id).code == "2m"
        for sensor in loaded_sensors
    )
    assert all(sensor.expected_frequency_seconds == 120 for sensor in loaded_sensors)
    assert all(sensor.measurement_duration_seconds == 120 for sensor in loaded_sensors)
    assert all(sensor.source_aggregation_duration_seconds == 120 for sensor in loaded_sensors)
    assert all(
        sensor.measurement_timestamp_semantics == "provider_received_at"
        for sensor in loaded_sensors
    )
    assert session.scalar(
        select(models.Measurement).order_by(models.Measurement.observed_at)
    ) is not None
    session.close()


def test_checked_in_measurements_exactly_match_staged_provider_rows():
    fixture_root = (
        ORIGINAL_FROZEN_ROOT if ORIGINAL_FROZEN_ROOT.exists() else SOURCE_ROOT
    )
    if not (fixture_root / "manifest.json").exists():
        pytest.skip("bounded paid capture has not been run")
    manifest = read_fixture_manifest(fixture_root)
    measurements = read_fixture_measurements(fixture_root, manifest)
    measurements_by_source = {
        (
            measurement.sensor_ref.split("-")[1],
            measurement.source_result_index,
            measurement.provider_field,
        ): measurement
        for measurement in measurements
    }
    assert len(measurements_by_source) == len(measurements)

    raw_provider_row_count = 0
    represented_sensor_ids = set()
    for sensor_id in APPROVED_SENSOR_IDS:
        staged_path = SOURCE_ROOT / "capture_staging" / f"sensor-{sensor_id}.json"
        staged = json.loads(staged_path.read_text(encoding="utf-8"))
        assert "request_headers" not in staged
        assert "headers" not in staged
        assert staged["provider"] == "PurpleAir"
        assert staged["sensor_id"] == sensor_id
        assert staged["endpoint"] == HISTORY_ENDPOINT_TEMPLATE.format(sensor_id=sensor_id)
        assert staged["query"] == {
            "start_timestamp": 1786147200,
            "end_timestamp": 1786406400,
            "fields": "pm2.5_atm,pm10.0_atm",
            "average": 0,
        }
        assert staged["response_status_code"] == 200
        payload = staged["response_payload"]
        assert payload["sensor_index"] == int(sensor_id)
        assert payload["average"] == 0
        assert payload["start_timestamp"] == 1786147200
        assert payload["end_timestamp"] == 1786406400
        assert payload["fields"] == ["time_stamp", *APPROVED_FIELDS]
        represented_sensor_ids.add(str(payload["sensor_index"]))

        for result_index, raw_row in enumerate(payload["data"]):
            raw_provider_row_count += 1
            raw_timestamp = raw_row[0]
            assert 1786147200 <= raw_timestamp < 1786406400
            for field_index, field in enumerate(APPROVED_FIELDS, start=1):
                measurement = measurements_by_source[(sensor_id, result_index, field)]
                assert measurement.provider_timestamp == raw_timestamp
                assert measurement.value == raw_row[field_index]
                assert measurement.observed_at == datetime.fromtimestamp(
                    raw_timestamp, tz=timezone.utc
                )
                assert measurement.provider_observation_ref == (
                    f"purpleair:{sensor_id}:{raw_timestamp}:{result_index}:{field}"
                )
                assert measurement.provider_parameter == {
                    "name": field,
                    "units": "µg/m³",
                }

    assert represented_sensor_ids == set(APPROVED_SENSOR_IDS)
    assert raw_provider_row_count == 4309
    assert len(measurements) == raw_provider_row_count * len(APPROVED_FIELDS)


def test_checked_in_capture_cannot_be_refreshed_or_overwritten():
    if not FROZEN_MANIFEST.exists():
        pytest.skip("bounded paid capture has not been run")
    calls = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("frozen capture attempted another provider request")

    with pytest.raises(PurpleAirHistoryCaptureError, match="overwrite"):
        execute_bounded_capture(
            SOURCE_MANIFEST,
            "unused-mock-key",
            authorization=_authorization(),
            request_executor=fail_if_called,
        )
    assert calls == []
