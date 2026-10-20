from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import models

from reference_data.fixture_io import read_fixture_manifest, read_fixture_measurements
from reference_data.purpleair_replacement_preflight import build_dry_run_report
from reference_data.purpleair_replacement_capture import (
    APPROVED_MANIFEST_SHA256,
    HARD_MAX_POINTS,
    HISTORY_ENDPOINT_TEMPLATE,
    PaidProviderAuthorization,
    PurpleAirReplacementCaptureError,
    ReplacementHTTPResponse,
    execute_replacement_capture,
    validate_execution_authorization,
)
from services.provider_safety import paid_provider_request_scope
from reference_data.loader import load_reference_fixture


SOURCE_ROOT = (
    Path(__file__).parent
    / "fixtures"
    / "reference_data"
    / "restricted"
    / "purpleair"
)
SOURCE_MANIFEST = SOURCE_ROOT / "new_york_replacement_capture_manifest.json"


def _copy_capture_root(tmp_path: Path) -> Path:
    copied_root = tmp_path / "purpleair"
    copied_root.mkdir()
    archived_root = SOURCE_ROOT / "capture_history" / "phase_2i4c"
    shutil.copyfile(SOURCE_MANIFEST, copied_root / SOURCE_MANIFEST.name)
    shutil.copyfile(
        SOURCE_ROOT / "capture_manifest.json", copied_root / "capture_manifest.json"
    )
    shutil.copyfile(archived_root / "manifest.json", copied_root / "manifest.json")
    shutil.copyfile(
        archived_root / "measurements.jsonl", copied_root / "measurements.jsonl"
    )
    shutil.copyfile(
        archived_root / "capture_report.json", copied_root / "capture_report.json"
    )
    copied_staging = copied_root / "capture_staging"
    copied_staging.mkdir()
    for sensor_id in ("198733", "175407", "99177"):
        shutil.copyfile(
            SOURCE_ROOT / "capture_staging" / f"sensor-{sensor_id}.json",
            copied_staging / f"sensor-{sensor_id}.json",
        )
    return copied_root / SOURCE_MANIFEST.name


def _authorization() -> PaidProviderAuthorization:
    return PaidProviderAuthorization(provider_name="purpleair", execution_mode="manual")


def _success_payload() -> dict:
    return {
        "api_version": "mock",
        "sensor_index": 159361,
        "average": 0,
        "start_timestamp": 1786147200,
        "end_timestamp": 1786406400,
        "fields": ["time_stamp", "pm2.5_atm", "pm10.0_atm"],
        "data": [
            [1786147200, 4.25, 7.5],
            [1786147320, 4.5, 7.75],
        ],
    }


def test_all_execution_confirmations_and_exact_ceiling_are_required():
    valid = {
        "allow_provider_api": True,
        "allow_paid_api": True,
        "confirm_manifest_sha": APPROVED_MANIFEST_SHA256,
        "max_purpleair_points": HARD_MAX_POINTS,
        "confirm_bounded_replacement": True,
    }
    validate_execution_authorization(**valid)
    for field_name, invalid in (
        ("allow_provider_api", False),
        ("allow_paid_api", False),
        ("confirm_manifest_sha", "wrong"),
        ("max_purpleair_points", HARD_MAX_POINTS + 1),
        ("confirm_bounded_replacement", False),
    ):
        with pytest.raises(PurpleAirReplacementCaptureError):
            validate_execution_authorization(**{**valid, field_name: invalid})


def test_success_uses_one_exact_request_and_merges_without_changing_existing_lines(tmp_path):
    manifest_path = _copy_capture_root(tmp_path)
    root = manifest_path.parent
    old_measurement_lines = (root / "measurements.jsonl").read_text(
        encoding="utf-8"
    ).splitlines(keepends=True)
    original_stage = (root / "capture_staging" / "sensor-198733.json").read_bytes()
    calls = []

    def executor(endpoint, query, headers):
        calls.append((endpoint, dict(query), dict(headers)))
        return _success_payload()

    authorization = _authorization()
    report = execute_replacement_capture(
        manifest_path,
        "mock-key",
        authorization=authorization,
        request_executor=executor,
        request_scope=paid_provider_request_scope(authorization),
    )

    assert calls == [
        (
            HISTORY_ENDPOINT_TEMPLATE.format(sensor_id="159361"),
            {
                "start_timestamp": 1786147200,
                "end_timestamp": 1786406400,
                "fields": "pm2.5_atm,pm10.0_atm",
                "average": 0,
            },
            {"X-API-Key": "mock-key"},
        )
    ]
    assert report["replacement_succeeded"] is True
    assert report["provider_rows_returned"] == 2
    assert report["pm25_rows_preserved"] == 2
    assert report["pm10_rows_preserved"] == 2
    assert report["request_count"] == 1
    assert report["retry_count"] == 0
    assert report["calculated_points_from_returned_rows"] == 10
    assert report["rio_measurement_lines_unchanged"] is True
    assert report["manila_measurement_lines_unchanged"] is True

    merged_lines = (root / "measurements.jsonl").read_text(
        encoding="utf-8"
    ).splitlines(keepends=True)
    merged_existing_lines = [
        line
        for line in merged_lines
        if json.loads(line)["sensor_ref"].split("-")[1] in {"175407", "99177"}
    ]
    assert merged_existing_lines == old_measurement_lines
    assert (root / "capture_staging" / "sensor-198733.json").read_bytes() == original_stage
    assert (root / "capture_history" / "phase_2i4c" / "manifest.json").exists()
    assert (root / "capture_history" / "phase_2i4c" / "capture_report.json").exists()
    assert (
        root / "capture_history" / "phase_2i4c" / "measurements.jsonl"
    ).read_bytes() == b"".join(line.encode("utf-8") for line in old_measurement_lines)

    fixture_manifest = read_fixture_manifest(root)
    fixture_measurements = read_fixture_measurements(root, fixture_manifest)
    assert len(fixture_measurements) == 8618 + 4
    assert fixture_manifest.capture.request_count == 4
    assert len(fixture_manifest.capture_history) == 2
    new_york_area = next(
        area
        for area in fixture_manifest.reference_areas
        if area.fixture_ref == "new_york"
    )
    assert new_york_area.active_provider_sensor_id == "159361"
    assert {
        device.external_id for device in fixture_manifest.devices
    } == {"198733", "159361", "175407", "99177"}
    new_york_rows = [
        measurement
        for measurement in fixture_measurements
        if measurement.sensor_ref.startswith("purpleair-159361-")
    ]
    assert [measurement.value for measurement in new_york_rows] == [
        7.5,
        7.75,
        4.25,
        4.5,
    ]
    post_capture_preflight = build_dry_run_report(manifest_path)
    assert post_capture_preflight["capture_ready"] is False
    assert post_capture_preflight["blockers"] == [
        "replacement_capture_already_attempted"
    ]


def test_http_200_zero_rows_stages_response_and_leaves_fixture_unchanged(tmp_path):
    manifest_path = _copy_capture_root(tmp_path)
    root = manifest_path.parent
    before_manifest = (root / "manifest.json").read_bytes()
    before_measurements = (root / "measurements.jsonl").read_bytes()
    calls = []

    def executor(endpoint, query, headers):
        calls.append(endpoint)
        payload = _success_payload()
        payload["data"] = []
        return payload

    report = execute_replacement_capture(
        manifest_path,
        "mock-key",
        authorization=_authorization(),
        request_executor=executor,
    )

    assert len(calls) == 1
    assert report["replacement_succeeded"] is False
    assert report["http_result"] == "HTTP 200"
    assert report["failure_reason"] == "zero_usable_provider_rows"
    assert report["provider_rows_returned"] == 0
    assert report["calculated_points_from_returned_rows"] == 2
    assert report["new_explicit_approval_required_before_another_candidate"] is True
    assert (root / "replacement_capture_staging" / "sensor-159361.json").exists()
    assert (root / "manifest.json").read_bytes() == before_manifest
    assert (root / "measurements.jsonl").read_bytes() == before_measurements


def test_malformed_or_failed_response_is_not_retried_and_does_not_merge(tmp_path):
    manifest_path = _copy_capture_root(tmp_path)
    root = manifest_path.parent
    before_hash = (root / "measurements.jsonl").read_bytes()
    calls = []

    def executor(endpoint, query, headers):
        calls.append(endpoint)
        payload = _success_payload()
        payload["sensor_index"] = 1
        return ReplacementHTTPResponse(200, payload, "mock", {})

    report = execute_replacement_capture(
        manifest_path,
        "mock-key",
        authorization=_authorization(),
        request_executor=executor,
    )

    assert len(calls) == 1
    assert report["replacement_succeeded"] is False
    assert report["failure_reason"] == "provider_sensor_id_mismatch"
    assert report["retry_count"] == 0
    assert (root / "measurements.jsonl").read_bytes() == before_hash


def test_real_transport_is_blocked_in_test_environment(tmp_path):
    manifest_path = _copy_capture_root(tmp_path)
    with pytest.raises(PurpleAirReplacementCaptureError, match="blocked in tests"):
        execute_replacement_capture(
            manifest_path,
            "mock-key",
            authorization=_authorization(),
        )


def test_checked_in_replacement_fixture_validates_and_loads_in_isolation(tmp_path):
    report_path = SOURCE_ROOT / "new_york_replacement_capture_report.json"
    if not report_path.exists():
        pytest.skip("approved replacement capture has not been run")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = read_fixture_manifest(SOURCE_ROOT)
    measurements = read_fixture_measurements(SOURCE_ROOT, manifest)

    assert report["replacement_sensor_id"] == "159361"
    assert report["request_count"] == 1
    assert report["retry_count"] == 0
    assert report["rio_measurement_lines_unchanged"] is True
    assert report["manila_measurement_lines_unchanged"] is True
    assert manifest.capture.request_count == 4
    assert len(manifest.capture_history) == 2
    assert len(measurements) == 12938
    new_york_measurements = [
        measurement
        for measurement in measurements
        if measurement.sensor_ref.startswith("purpleair-159361-")
    ]
    assert len(new_york_measurements) == 4320
    assert all(
        "2026-08-08T00:00:00+00:00"
        <= measurement.observed_at.isoformat()
        < "2026-08-11T00:00:00+00:00"
        for measurement in new_york_measurements
    )

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'replacement.sqlite'}")
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
    first = load_reference_fixture(session, SOURCE_ROOT)
    second = load_reference_fixture(session, SOURCE_ROOT)

    assert first.inserted == 1 + 4 + 8 + 12938
    assert second.inserted == 0
    assert second.updated == 0
    assert second.skipped == 1 + 4 + 8 + 12938
    loaded_devices = session.scalars(select(models.Device)).all()
    assert {device.external_id for device in loaded_devices} == {
        "198733",
        "159361",
        "175407",
        "99177",
    }
    loaded_new_york = next(
        device for device in loaded_devices if device.external_id == "159361"
    )
    loaded_new_york_sensors = session.scalars(
        select(models.Sensor).where(models.Sensor.device_id == loaded_new_york.device_id)
    ).all()
    assert len(loaded_new_york_sensors) == 2
    assert all(sensor.expected_frequency_seconds == 120 for sensor in loaded_new_york_sensors)
    assert all(sensor.measurement_duration_seconds == 120 for sensor in loaded_new_york_sensors)
    assert all(sensor.source_aggregation_duration_seconds == 120 for sensor in loaded_new_york_sensors)
    assert all(
        sensor.measurement_timestamp_semantics == "provider_received_at"
        for sensor in loaded_new_york_sensors
    )
    assert session.scalar(select(func.count(models.Measurement.measurement_id))) == 12938
    session.close()
