from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from reference_data.fixture_io import sha256_file
from reference_data.purpleair_replacement_preflight import (
    HARD_MAX_POINTS,
    ORIGINAL_SENSOR_ID,
    REPLACEMENT_SENSOR_ID,
    PurpleAirReplacementPreflightError,
    build_dry_run_report,
)


RESTRICTED_ROOT = (
    Path(__file__).parent
    / "fixtures"
    / "reference_data"
    / "restricted"
    / "purpleair"
)
MANIFEST_PATH = RESTRICTED_ROOT / "new_york_replacement_capture_manifest.json"
PRESERVED_ARTIFACTS = (
    "capture_manifest.json",
    "capture_report.json",
    "manifest.json",
    "measurements.jsonl",
    "capture_staging/sensor-198733.json",
    "capture_staging/sensor-175407.json",
    "capture_staging/sensor-99177.json",
)


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _copy_preflight_inputs(tmp_path: Path) -> Path:
    copied_root = tmp_path / "purpleair"
    copied_root.mkdir(parents=True)
    shutil.copyfile(MANIFEST_PATH, copied_root / MANIFEST_PATH.name)
    for relative_path in PRESERVED_ARTIFACTS:
        source = RESTRICTED_ROOT / relative_path
        destination = copied_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return copied_root / MANIFEST_PATH.name


def test_checked_in_replacement_preflight_is_complete_and_zero_network(monkeypatch):
    executor_calls = []

    def fail_if_called(*args, **kwargs):
        executor_calls.append((args, kwargs))
        raise AssertionError("replacement dry run touched the request executor")

    def reject_environment_read(name, default=None):
        raise AssertionError(f"replacement dry run read environment variable {name}")

    before_hashes = {
        relative_path: _sha256(RESTRICTED_ROOT / relative_path)
        for relative_path in PRESERVED_ARTIFACTS
    }
    monkeypatch.setattr(os, "getenv", reject_environment_read)
    report = build_dry_run_report(MANIFEST_PATH, request_executor=fail_if_called)
    after_hashes = {
        relative_path: _sha256(RESTRICTED_ROOT / relative_path)
        for relative_path in PRESERVED_ARTIFACTS
    }

    assert executor_calls == []
    assert before_hashes == after_hashes
    assert report == {
        "dry_run": True,
        "preflight_only": True,
        "live_capture_authorized": False,
        "replacement_sensor_id": REPLACEMENT_SENSOR_ID,
        "original_sensor_id": ORIGINAL_SENSOR_ID,
        "window_start": "2026-08-08T00:00:00Z",
        "window_end_exclusive": "2026-08-11T00:00:00Z",
        "fields": ["pm2.5_atm", "pm10.0_atm"],
        "expected_rows": 2160,
        "request_count": 1,
        "metadata_request_count": 0,
        "endpoint_base_point_total": 2,
        "pm25_field_point_total": 4320,
        "pm10_field_point_total": 4320,
        "estimated_total_points": 8642,
        "safety_margin_percent": 10,
        "hard_max_points": HARD_MAX_POINTS,
        "manifest_sha256": _sha256(MANIFEST_PATH),
        "blockers": ["replacement_capture_already_attempted"],
        "capture_ready": False,
        "purpleair_requests_made": 0,
        "purpleair_points_consumed": 0,
        "credentials_read": False,
        "network_requests_executed": 0,
        "preserved_existing_capture_verified": True,
    }
    assert (RESTRICTED_ROOT / "new_york_replacement_capture_report.json").exists()


def test_manifest_contains_only_the_approved_replacement_and_preserves_empty_original():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["reference_sensors"] == [
        {
            "reference_area_code": "new_york",
            "reference_area_name": "New York City / New York metropolitan area",
            "sensor_id": REPLACEMENT_SENSOR_ID,
            "replaces_sensor_id": ORIGINAL_SENSOR_ID,
            "selection_status": "manually_supplied_replacement_candidate",
        }
    ]
    assert manifest["preflight_only"] is True
    assert manifest["live_capture_authorized"] is False
    assert manifest["history_request_ceiling"] == 1
    assert manifest["hard_max_points"] == 9507
    assert manifest["automatic_refresh"] is False
    assert manifest["scheduled_capture"] is False

    original_stage = json.loads(
        (RESTRICTED_ROOT / "capture_staging" / "sensor-198733.json").read_text(
            encoding="utf-8"
        )
    )
    assert original_stage["response_status_code"] == 200
    assert original_stage["response_payload"]["sensor_index"] == 198733
    assert original_stage["response_payload"]["data"] == []


def test_changed_replacement_or_preserved_capture_is_rejected(tmp_path):
    manifest_path = _copy_preflight_inputs(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reference_sensors"][0]["sensor_id"] = "not-approved"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PurpleAirReplacementPreflightError, match="sensor_id"):
        build_dry_run_report(manifest_path)

    manifest_path = _copy_preflight_inputs(tmp_path / "second")
    preserved_rio = manifest_path.parent / "capture_staging" / "sensor-175407.json"
    preserved_rio.write_text(
        preserved_rio.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    with pytest.raises(PurpleAirReplacementPreflightError, match="checksum mismatch"):
        build_dry_run_report(manifest_path)


def test_cli_dry_run_remains_zero_network_with_all_transports_patched():
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
sys.argv = ["purpleair_replacement_preflight", "--manifest", sys.argv[1], "--dry-run"]
runpy.run_module("reference_data.purpleair_replacement_preflight", run_name="__main__")
'''
    environment = os.environ.copy()
    environment["COMPASSAQ_ENV"] = "test"
    environment["ENABLE_PAID_API_IMPORTS"] = "false"
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, "-c", patch_and_run, str(MANIFEST_PATH.resolve())],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["purpleair_requests_made"] == 0
    assert report["purpleair_points_consumed"] == 0
    assert report["network_requests_executed"] == 0
    assert report["credentials_read"] is False


def test_cli_has_no_live_mode():
    environment = os.environ.copy()
    environment["COMPASSAQ_ENV"] = "test"
    environment["ENABLE_PAID_API_IMPORTS"] = "false"
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "reference_data.purpleair_replacement_preflight",
            "--manifest",
            str(MANIFEST_PATH.resolve()),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "live replacement capture is unavailable" in completed.stderr
