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
from reference_data.capture import calculate_endpoint_points, plan_capture
from reference_data.fixture_io import (
    ReferenceFixtureError,
    read_fixture_manifest,
    read_fixture_measurements,
    sha256_file,
)
from reference_data.loader import (
    _assert_development_loader_enabled,
    load_reference_fixture,
)
from reference_data.restricted import require_restricted_data_if_configured


FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "reference_data" / "synthetic" / "purpleair_2m"
)
CAPTURE_TEMPLATE = (
    Path(__file__).parent
    / "fixtures"
    / "reference_data"
    / "restricted"
    / "purpleair"
    / "manifest.template.json"
)
PURPLEAIR_PREFLIGHT_MANIFEST = (
    Path(__file__).parent
    / "fixtures"
    / "reference_data"
    / "restricted"
    / "purpleair"
    / "capture_manifest.json"
)


def _write_capture_manifest(
    tmp_path: Path,
    *,
    manifest_overrides: dict | None = None,
    pricing_overrides: dict | None = None,
) -> Path:
    manifest = {
        "provider": "PurpleAir",
        "provider_ids": ["supplied-id"],
        "fields": ["field_a", "field_b"],
        "average": 0,
        "retry_count": 0,
        "window_start": "2026-01-01T00:00:00Z",
        "window_end": "2026-01-01T03:20:00Z",
        "expected_frequency_seconds": 120,
        "rows_per_page": 100,
        "metadata_request_count": 0,
        "metadata_expected_rows": 0,
        "metadata_fields": [],
        "paid_provider": True,
        "pricing": {
            "verified_at": "2026-01-01T00:00:00Z",
            "history_endpoint_base_points": 2,
            "history_field_points": {"field_a": 2, "field_b": 1},
            "metadata_endpoint_base_points": 3,
            "metadata_field_points": {},
            "safety_margin_percent": 0,
        },
        "output_fixture_paths": ["manifest.json", "measurements.jsonl"],
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    if pricing_overrides:
        manifest["pricing"].update(pricing_overrides)
    manifest_path = tmp_path / "capture-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _fixture_session(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'fixture.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    unit = models.Unit(code="ug_m3", symbol="ug/m3", name="Micrograms per cubic meter")
    session.add(unit)
    session.flush()
    session.add(models.Parameter(code="pm25", display_name="PM2.5", default_unit_id=unit.unit_id))
    session.add_all(
        [
            models.AggregationPeriod(code="2m", display_name="2 Minutes", duration_minutes=2, is_rolling=False),
            models.AggregationPeriod(code="1h", display_name="1 Hour", duration_minutes=60, is_rolling=False),
            models.AggregationPeriod(code="24h", display_name="24 Hours", duration_minutes=1440, is_rolling=False),
        ]
    )
    session.commit()
    return session


def test_fixture_validates_expands_and_loads_idempotently(tmp_path):
    manifest = read_fixture_manifest(FIXTURE_ROOT)
    measurements = read_fixture_measurements(FIXTURE_ROOT, manifest)
    assert len(measurements) == 822
    assert manifest.provider == "Synthetic Reference Data"
    assert all(not device.external_id.isdigit() for device in manifest.devices)

    session = _fixture_session(tmp_path)
    first = load_reference_fixture(session, FIXTURE_ROOT)
    second = load_reference_fixture(session, FIXTURE_ROOT)
    assert first.inserted == 833
    assert second.inserted == 0
    assert second.updated == 0
    assert second.skipped == 833
    assert first.device_ids == second.device_ids
    assert first.sensor_ids == second.sensor_ids
    loaded_source = session.get(
        models.ExternalAPI,
        first.external_api_ids["Synthetic Reference Data"],
    )
    assert loaded_source.params["access_classification"] == "synthetic_public"
    assert loaded_source.params["fixture_provenance"]["created_by"] == "CompassAQ maintainers"
    assert loaded_source.params["fixture_license"]["redistribution_approved"] is True
    assert session.scalar(select(func.count(models.Measurement.measurement_id))) == 822

    changed_measurement = session.scalar(
        select(models.Measurement).order_by(models.Measurement.measurement_id)
    )
    changed_measurement.value = 999.0
    session.commit()
    repaired = load_reference_fixture(session, FIXTURE_ROOT)
    assert repaired.inserted == 0
    assert repaired.updated == 1
    assert repaired.skipped == 832
    session.refresh(changed_measurement)
    assert changed_measurement.value == 12.0
    session.close()


def test_fixture_checksum_normalizes_only_checkout_line_endings(tmp_path):
    copied = tmp_path / "fixture"
    shutil.copytree(FIXTURE_ROOT, copied)
    measurements_path = copied / "measurements.jsonl"
    lf_content = measurements_path.read_bytes()

    measurements_path.write_bytes(lf_content.replace(b"\n", b"\r\n"))
    read_fixture_manifest(copied)

    measurements_path.write_bytes(
        lf_content.replace(b"\n", b"\r\n") + b" "
    )
    with pytest.raises(ReferenceFixtureError, match="checksum mismatch"):
        read_fixture_manifest(copied)


def test_checksum_unknown_sensor_unsorted_timestamp_and_nonfinite_fail_explicitly(tmp_path):
    copied = tmp_path / "fixture"
    shutil.copytree(FIXTURE_ROOT, copied)
    manifest_path = copied / "manifest.json"
    malformed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    malformed_manifest["schema_version"] = "unsupported"
    manifest_path.write_text(json.dumps(malformed_manifest), encoding="utf-8")
    with pytest.raises(ReferenceFixtureError, match="Invalid fixture manifest"):
        read_fixture_manifest(copied)
    shutil.copyfile(FIXTURE_ROOT / "manifest.json", manifest_path)

    measurements_path = copied / "measurements.jsonl"
    measurements_path.write_text(
        measurements_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceFixtureError, match="checksum mismatch"):
        read_fixture_manifest(copied)

    def write_case(lines):
        measurements_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw["measurements_sha256"] = sha256_file(measurements_path)
        manifest_path.write_text(json.dumps(raw), encoding="utf-8")
        manifest = read_fixture_manifest(copied)
        return read_fixture_measurements(copied, manifest)

    with pytest.raises(ReferenceFixtureError, match="Unknown sensor_ref"):
        write_case([json.dumps({"sensor_ref":"missing","observed_at":"2026-01-01T00:00:00Z","value":1})])
    with pytest.raises(ReferenceFixtureError, match="not sorted"):
        write_case([
            json.dumps({"sensor_ref":"complete_pm25","observed_at":"2026-01-01T00:02:00Z","value":1}),
            json.dumps({"sensor_ref":"complete_pm25","observed_at":"2026-01-01T00:00:00Z","value":1}),
        ])
    with pytest.raises(ReferenceFixtureError, match="explicit UTC"):
        write_case([json.dumps({"sensor_ref":"complete_pm25","observed_at":"2026-01-01T00:00:00","value":1})])
    with pytest.raises(ReferenceFixtureError, match="finite"):
        write_case(["{\"sensor_ref\":\"complete_pm25\",\"observed_at\":\"2026-01-01T00:00:00Z\",\"value\":NaN}"])


def test_development_loader_and_restricted_root_are_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("COMPASSAQ_ENV", "production")
    monkeypatch.setenv("ENABLE_REFERENCE_DATA_DEV_LOADER", "true")
    with pytest.raises(ReferenceFixtureError, match="COMPASSAQ_ENV=development"):
        _assert_development_loader_enabled(True)

    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    _assert_development_loader_enabled(True)

    monkeypatch.delenv("COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT", raising=False)
    monkeypatch.setenv("REQUIRE_RESTRICTED_REFERENCE_DATA", "false")
    assert require_restricted_data_if_configured() is None
    monkeypatch.setenv("REQUIRE_RESTRICTED_REFERENCE_DATA", "true")
    with pytest.raises(ReferenceFixtureError, match="required"):
        require_restricted_data_if_configured()

    private_root = tmp_path / "private-reference-data"
    private_root.mkdir()
    monkeypatch.setenv("COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT", str(private_root))
    assert require_restricted_data_if_configured() == private_root.resolve()


def test_dry_run_never_touches_executor_credentials_or_network(monkeypatch, tmp_path):
    executor_calls = []

    def fail_executor(*args, **kwargs):
        executor_calls.append((args, kwargs))
        raise AssertionError("request executor must remain unused")

    original_getenv = os.getenv

    def guarded_getenv(name, default=None):
        if name in {"PURPLEAIR_API_KEY", "OPENAQ_API_KEY", "AIRGRADIENT_API_KEY"}:
            raise AssertionError("dry-run must not read provider credentials")
        return original_getenv(name, default)

    monkeypatch.setattr(os, "getenv", guarded_getenv)
    result = plan_capture(CAPTURE_TEMPLATE, request_executor=fail_executor)
    assert executor_calls == []
    assert result["network_requests_executed"] == 0
    assert {
        "provider_ids",
        "window_start",
        "window_end",
        "pricing_verified_at",
        "history_endpoint_base_points",
        "history_field_points:pm2.5_atm",
        "history_field_points:pm10.0_atm",
    }.issubset(result["blockers"])

    complete = plan_capture(
        _write_capture_manifest(tmp_path), request_executor=fail_executor
    )
    assert executor_calls == []
    assert complete["network_requests_executed"] == 0
    assert complete["capture_ready"] is True
    assert complete["blockers"] == []


def test_history_pricing_charges_base_per_request_and_fields_per_row(tmp_path):
    result = plan_capture(_write_capture_manifest(tmp_path))

    assert result["expected_rows"] == 100
    assert result["history_request_count"] == 1
    assert result["history_point_estimate"] == {
        "endpoint_base_points_total": 2,
        "field_points_per_row": 3,
        "field_points_total": 300,
        "total_points": 302,
    }
    assert result["estimated_points"] == 302
    assert result["recommended_max_points_ceiling"] == 302
    assert result["estimated_points"] != 6  # Regression: old field-count formula.


def test_history_pricing_sums_multiple_sensors_and_requests(tmp_path):
    result = plan_capture(
        _write_capture_manifest(
            tmp_path,
            manifest_overrides={
                "provider_ids": ["supplied-id-a", "supplied-id-b"],
                "rows_per_page": 60,
            },
        )
    )

    assert result["expected_rows_per_provider_id"] == 100
    assert result["expected_rows"] == 200
    assert result["history_request_count"] == 4
    assert result["history_point_estimate"]["endpoint_base_points_total"] == 8
    assert result["history_point_estimate"]["field_points_total"] == 600
    assert result["estimated_history_points"] == 608


def test_missing_history_field_pricing_blocks_capture_planning(tmp_path):
    result = plan_capture(
        _write_capture_manifest(
            tmp_path,
            pricing_overrides={"history_field_points": {"field_a": 2}},
        )
    )

    assert "history_field_points:field_b" in result["blockers"]
    assert result["capture_ready"] is False
    assert result["estimated_history_points"] is None
    assert result["estimated_points"] is None


def test_missing_history_endpoint_pricing_blocks_capture_planning(tmp_path):
    result = plan_capture(
        _write_capture_manifest(
            tmp_path,
            pricing_overrides={"history_endpoint_base_points": None},
        )
    )

    assert "history_endpoint_base_points" in result["blockers"]
    assert result["capture_ready"] is False
    assert result["estimated_points"] is None


def test_missing_pricing_verification_date_blocks_capture_planning(tmp_path):
    result = plan_capture(
        _write_capture_manifest(
            tmp_path,
            pricing_overrides={"verified_at": None},
        )
    )

    assert "pricing_verified_at" in result["blockers"]
    assert result["capture_ready"] is False
    assert result["estimated_points"] == 302
    assert result["recommended_max_points_ceiling"] is None


def test_zero_expected_rows_still_charges_endpoint_base_cost():
    result = calculate_endpoint_points(
        request_count=1,
        expected_rows=0,
        endpoint_base_points=2,
        requested_fields=["field_a"],
        field_points={"field_a": 2},
    )

    assert result["endpoint_base_points_total"] == 2
    assert result["field_points_total"] == 0
    assert result["total_points"] == 2


def test_seventy_two_hour_two_minute_plan_uses_full_cadence_rows(tmp_path):
    result = plan_capture(
        _write_capture_manifest(
            tmp_path,
            manifest_overrides={
                "fields": ["field_a"],
                "window_end": "2026-01-04T00:00:00Z",
                "rows_per_page": 1000,
            },
            pricing_overrides={"safety_margin_percent": 10},
        )
    )

    assert result["expected_rows"] == 2160
    assert result["history_request_count"] == 3
    assert result["estimated_history_points"] == 4326
    assert result["recommended_max_points_ceiling"] == 4759


def test_reference_sensor_slots_preserve_three_request_plan_when_one_id_is_blocked(
    tmp_path,
):
    result = plan_capture(
        _write_capture_manifest(
            tmp_path,
            manifest_overrides={
                "provider_ids": [],
                "reference_sensors": [
                    {"reference_area_code": "new_york", "sensor_id": "198733"},
                    {"reference_area_code": "rio_de_janeiro", "sensor_id": "175407"},
                    {"reference_area_code": "metro_manila", "sensor_id": None},
                ],
                "window_end": "2026-01-04T00:00:00Z",
                "rows_per_page": 21600,
            },
        )
    )

    assert result["planned_provider_count"] == 3
    assert result["provider_ids"] == ["198733", "175407"]
    assert result["expected_rows_per_provider_id"] == 2160
    assert result["expected_rows"] == 6480
    assert result["history_request_count"] == 3
    assert result["request_count"] == 3
    assert result["blockers"] == ["reference_sensor_id:metro_manila"]
    assert result["capture_ready"] is False


def test_purpleair_average_and_retry_must_remain_zero(tmp_path):
    result = plan_capture(
        _write_capture_manifest(
            tmp_path,
            manifest_overrides={"average": 10, "retry_count": 1},
        )
    )

    assert "average_must_be_zero" in result["blockers"]
    assert "retry_count_must_be_zero" in result["blockers"]
    assert result["capture_ready"] is False


def test_checked_in_purpleair_preflight_is_zero_network_and_pricing_complete():
    executor_calls = []

    def fail_if_called(*args, **kwargs):
        executor_calls.append((args, kwargs))
        raise AssertionError("the checked-in preflight must remain local-only")

    result = plan_capture(
        PURPLEAIR_PREFLIGHT_MANIFEST,
        request_executor=fail_if_called,
    )
    manifest = json.loads(PURPLEAIR_PREFLIGHT_MANIFEST.read_text(encoding="utf-8"))

    assert executor_calls == []
    assert result["network_requests_executed"] == 0
    assert result["capture_ready"] is True
    assert result["planned_provider_count"] == 3
    assert result["provider_ids"] == ["198733", "175407", "99177"]
    assert result["expected_rows_per_provider_id"] == 2160
    assert result["expected_rows"] == 6480
    assert result["history_request_count"] == 3
    assert result["metadata_request_count"] == 0
    assert result["request_count"] == 3
    assert result["average"] == 0
    assert result["retry_count"] == 0
    assert result["blockers"] == []
    assert result["pricing_verified_at"] == "2026-08-11T21:25:00-07:00"
    assert result["history_endpoint_base_points"] == 2
    assert result["history_field_points"] == {
        "pm2.5_atm": 2,
        "pm10.0_atm": 2,
    }
    assert result["history_point_estimate"] == {
        "endpoint_base_points_total": 6,
        "field_points_per_row": 4,
        "field_points_total": 25920,
        "total_points": 25926,
    }
    assert result["estimated_points"] == 25926
    assert result["recommended_max_points_ceiling"] == 28519
    assert manifest["access_classification"] == (
        "restricted_private_not_approved_for_public_redistribution"
    )
    assert manifest["paid_capture_approval_requirements"] == [
        "ENABLE_PAID_API_IMPORTS=true",
        "--allow-provider-api",
        "--allow-paid-api",
        "--confirm-manifest-sha <exact SHA-256>",
        "--max-purpleair-points <approved ceiling>",
    ]
    assert manifest["automatic_refresh"] is False
    assert manifest["scheduled_capture"] is False
    manila_sensor = next(
        sensor
        for sensor in manifest["reference_sensors"]
        if sensor["reference_area_code"] == "metro_manila"
    )
    assert manila_sensor["sensor_id"] == "99177"
    assert manila_sensor["selection_status"] == "selected_from_manually_supplied_id"
    assert manila_sensor["device_name"] is None
    assert manila_sensor["latitude"] is None
    assert manila_sensor["longitude"] is None
    assert manifest["pricing"]["safety_margin_percent"] == 10
    assert manifest["pricing"]["safety_margin_status"] == "approved"


def test_metadata_request_costs_are_calculated_separately(tmp_path):
    result = plan_capture(
        _write_capture_manifest(
            tmp_path,
            manifest_overrides={
                "metadata_request_count": 2,
                "metadata_expected_rows": 2,
                "metadata_fields": ["name", "location_type"],
            },
            pricing_overrides={
                "metadata_endpoint_base_points": 3,
                "metadata_field_points": {"name": 5, "location_type": 1},
            },
        )
    )

    assert result["history_request_count"] == 1
    assert result["metadata_request_count"] == 2
    assert result["request_count"] == 3
    assert result["estimated_history_points"] == 302
    assert result["metadata_point_estimate"] == {
        "endpoint_base_points_total": 6,
        "field_points_per_row": 6,
        "field_points_total": 12,
        "total_points": 18,
    }
    assert result["estimated_metadata_points"] == 18
    assert result["estimated_points"] == 320


def test_missing_metadata_endpoint_or_field_pricing_blocks_planning(tmp_path):
    result = plan_capture(
        _write_capture_manifest(
            tmp_path,
            manifest_overrides={
                "metadata_request_count": 1,
                "metadata_expected_rows": 1,
                "metadata_fields": ["name", "location_type"],
            },
            pricing_overrides={
                "metadata_endpoint_base_points": None,
                "metadata_field_points": {"name": 5},
            },
        )
    )

    assert "metadata_endpoint_base_points" in result["blockers"]
    assert "metadata_field_points:location_type" in result["blockers"]
    assert result["estimated_metadata_points"] is None
    assert result["estimated_points"] is None
    assert result["capture_ready"] is False


def test_dry_run_cli_has_zero_network_under_subprocess_hard_block(tmp_path):
    hard_block = tmp_path / "sitecustomize.py"
    hard_block.write_text(
        "import socket, requests, httpx\n"
        "def blocked(*args, **kwargs): raise RuntimeError('subprocess network blocked')\n"
        "async def blocked_async(*args, **kwargs): raise RuntimeError('subprocess network blocked')\n"
        "socket.create_connection = blocked\n"
        "socket.socket.connect = blocked\n"
        "requests.sessions.Session.request = blocked\n"
        "httpx.HTTPTransport.handle_request = blocked\n"
        "httpx.AsyncHTTPTransport.handle_async_request = blocked_async\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(Path(__file__).parents[1])])
    environment["COMPASSAQ_ENV"] = "test"
    completed = subprocess.run(
        [sys.executable, "-m", "reference_data.capture", "--manifest", str(CAPTURE_TEMPLATE), "--dry-run"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["network_requests_executed"] == 0
