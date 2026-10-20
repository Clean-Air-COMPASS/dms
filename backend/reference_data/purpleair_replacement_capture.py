"""One-request PurpleAir replacement capture for New York sensor 159361.

The command consumes the immutable Phase 2I.4C.1 preflight manifest. It stages
the single provider response before interpreting it and never retries. Empty,
failed, or malformed responses leave the existing frozen fixture untouched.
Usable data is merged deterministically while existing Rio and Metro Manila
measurement JSONL lines are copied byte-for-byte.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, ContextManager

from sqlalchemy import func, select

import models
from db import SessionLocal
from reference_data.fixture_io import (
    read_fixture_manifest,
    read_fixture_measurements,
    sha256_file as _sha256,
)
from reference_data.purpleair_history_capture import (
    PurpleAirResponse,
    _normalize_sensor_response,
)
from reference_data.purpleair_replacement_preflight import (
    ACCESS_CLASSIFICATION,
    ESTIMATED_POINTS,
    EXPECTED_ROWS,
    FIELDS,
    HARD_MAX_POINTS,
    HISTORY_ENDPOINT_BASE_POINTS,
    HISTORY_ENDPOINT_TEMPLATE,
    ORIGINAL_SENSOR_ID,
    PRESERVED_METRO_MANILA_SENSOR_ID,
    PRESERVED_RIO_SENSOR_ID,
    REPLACEMENT_SENSOR_ID,
    WINDOW_END,
    WINDOW_START,
    _validate_exact_manifest,
    _validate_preserved_capture,
)
from reference_data.schema import ReferenceFixtureManifest
from services.provider_safety import (
    PaidProviderAuthorization,
    assert_paid_provider_http_authorized,
    paid_provider_request_scope,
    require_paid_provider_authorization,
)


APPROVED_MANIFEST_SHA256 = (
    "ab907e93a1f977e041d1bb1f3e03f88c8f870792781beab0370f1d105676978a"
)
POINTS_PER_PROVIDER_ROW = 4


class PurpleAirReplacementCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplacementHTTPResponse:
    status_code: int
    payload: Any
    body_text: str
    headers: dict[str, str]


RequestExecutor = Callable[
    [str, dict[str, Any], dict[str, str]], ReplacementHTTPResponse | dict[str, Any]
]

def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PurpleAirReplacementCaptureError(f"Invalid JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PurpleAirReplacementCaptureError(f"JSON file must contain an object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _paths(manifest_path: Path) -> dict[str, Path]:
    root = manifest_path.parent
    return {
        "manifest": root / "manifest.json",
        "measurements": root / "measurements.jsonl",
        "capture_report": root / "capture_report.json",
        "replacement_report": root / "new_york_replacement_capture_report.json",
        "failure_report": root / "new_york_replacement_failure_report.json",
        "stage": root / "replacement_capture_staging" / "sensor-159361.json",
        "archive_root": root / "capture_history" / "phase_2i4c",
    }


def validate_execution_authorization(
    *,
    allow_provider_api: bool,
    allow_paid_api: bool,
    confirm_manifest_sha: str,
    max_purpleair_points: int,
    confirm_bounded_replacement: bool,
) -> None:
    if not allow_provider_api:
        raise PurpleAirReplacementCaptureError("--allow-provider-api is required")
    if not allow_paid_api:
        raise PurpleAirReplacementCaptureError("--allow-paid-api is required")
    if not confirm_bounded_replacement:
        raise PurpleAirReplacementCaptureError(
            "--confirm-bounded-new-york-replacement is required"
        )
    if confirm_manifest_sha != APPROVED_MANIFEST_SHA256:
        raise PurpleAirReplacementCaptureError(
            "--confirm-manifest-sha must equal the approved replacement manifest SHA-256"
        )
    if max_purpleair_points != HARD_MAX_POINTS:
        raise PurpleAirReplacementCaptureError(
            f"--max-purpleair-points must equal {HARD_MAX_POINTS}"
        )


def _safe_response_headers(headers: Any) -> dict[str, str]:
    if not hasattr(headers, "items"):
        return {}
    return {
        str(name): str(value)
        for name, value in headers.items()
        if str(name).lower().startswith(("x-purpleair-", "x-ratelimit-"))
    }


def _single_purpleair_get(
    endpoint: str,
    query: dict[str, Any],
    headers: dict[str, str],
) -> ReplacementHTTPResponse:
    assert_paid_provider_http_authorized("PurpleAir")
    import requests

    response = requests.get(
        endpoint,
        params=query,
        headers=headers,
        timeout=30,
        allow_redirects=False,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return ReplacementHTTPResponse(
        status_code=response.status_code,
        payload=payload,
        body_text=response.text,
        headers=_safe_response_headers(response.headers),
    )


def _coerce_response(value: ReplacementHTTPResponse | dict[str, Any]) -> ReplacementHTTPResponse:
    if isinstance(value, ReplacementHTTPResponse):
        return value
    if isinstance(value, dict):
        return ReplacementHTTPResponse(
            status_code=200,
            payload=value,
            body_text=json.dumps(value, ensure_ascii=False),
            headers={},
        )
    raise PurpleAirReplacementCaptureError("request executor returned an invalid response")


def _write_staged_response(
    path: Path,
    endpoint: str,
    query: dict[str, Any],
    response: ReplacementHTTPResponse,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise PurpleAirReplacementCaptureError(
            f"replacement staged response already exists: {path}"
        )
    _write_json(
        path,
        {
            "provider": "PurpleAir",
            "sensor_id": REPLACEMENT_SENSOR_ID,
            "endpoint": endpoint,
            "query": query,
            "response_status_code": response.status_code,
            "response_headers": response.headers,
            "response_payload": response.payload,
            "response_body_text": response.body_text,
        },
    )


def _failure_report(
    paths: dict[str, Path],
    *,
    http_result: str,
    reason: str,
    request_count: int,
    provider_rows: int | None,
    calculated_points: int | None,
) -> dict[str, Any]:
    report = {
        "provider": "PurpleAir",
        "replacement_sensor_id": REPLACEMENT_SENSOR_ID,
        "original_sensor_id": ORIGINAL_SENSOR_ID,
        "replacement_succeeded": False,
        "http_result": http_result,
        "failure_reason": reason,
        "provider_rows_returned": provider_rows,
        "pm25_rows_preserved": 0,
        "pm10_rows_preserved": 0,
        "request_count": request_count,
        "retry_count": 0,
        "calculated_points_from_returned_rows": calculated_points,
        "hard_max_points": HARD_MAX_POINTS,
        "ceiling_respected": calculated_points is None or calculated_points <= HARD_MAX_POINTS,
        "open_aq_requests": 0,
        "airgradient_requests": 0,
        "other_candidate_requests": 0,
        "frozen_fixture_modified": False,
        "original_new_york_provenance_preserved": True,
        "new_explicit_approval_required_before_another_candidate": True,
        "staged_response": str(paths["stage"]) if paths["stage"].exists() else None,
    }
    if not paths["failure_report"].exists():
        _write_json(paths["failure_report"], report)
    return report


def _new_device_and_sensors(
    old_manifest: dict[str, Any],
    sensor_result: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    new_york_area = next(
        area for area in old_manifest["reference_areas"] if area["fixture_ref"] == "new_york"
    )
    device = {
        "fixture_ref": f"purpleair-device-{REPLACEMENT_SENSOR_ID}",
        "external_id": REPLACEMENT_SENSOR_ID,
        "name": f"PurpleAir {REPLACEMENT_SENSOR_ID} (provider name not supplied)",
        "friendly_name": None,
        "latitude": None,
        "longitude": None,
        "timezone": new_york_area["timezone"],
        "reference_area_ref": "new_york",
        "provider_name": "PurpleAir",
        "hardware_provider": "PurpleAir",
        "source_metadata": {
            "provider_sensor_id": REPLACEMENT_SENSOR_ID,
            "selection_status": "manually_supplied_replacement_candidate",
            "metadata_request_performed": False,
            "active_reference_sensor": True,
            "replaces_zero_row_sensor_id": ORIGINAL_SENSOR_ID,
        },
    }
    sensors = []
    for field, parameter_code in (("pm2.5_atm", "pm25"), ("pm10.0_atm", "pm10")):
        sensors.append(
            {
                "fixture_ref": f"purpleair-{REPLACEMENT_SENSOR_ID}-{parameter_code}",
                "device_ref": f"purpleair-device-{REPLACEMENT_SENSOR_ID}",
                "external_sensor_id": f"{REPLACEMENT_SENSOR_ID}:{field}",
                "parameter_code": parameter_code,
                "unit_code": "ug_m3",
                "aggregation_period_code": "2m",
                "expected_frequency_seconds": 120,
                "measurement_duration_seconds": 120,
                "source_aggregation_duration_seconds": 120,
                "measurement_timestamp_semantics": "provider_received_at",
                "measurement_metadata_status": "provider_documented",
                "measurement_metadata_managed_by": "reference_fixture_loader",
                "provider_parameter_name": field,
                "provider_unit": "µg/m³",
                "hardware_provider": "PurpleAir",
                "temporal_qualification": {
                    "status": "provider_documented",
                    "timestamp_semantics": "provider_received_at",
                    "expected_frequency_seconds": 120,
                    "observed_timestamp_gap_values_seconds": sensor_result[
                        "observed_timestamp_gap_values_seconds"
                    ],
                },
                "capture_statistics": {
                    "provider_sensor_id": REPLACEMENT_SENSOR_ID,
                    "provider_field": field,
                    "measurement_rows_preserved": sensor_result[
                        "per_field_measurement_rows"
                    ][field],
                },
            }
        )
    return device, sensors


def _combined_measurements_text(
    old_measurements_path: Path,
    new_measurements: list[dict[str, Any]],
) -> tuple[str, bool, bool]:
    old_lines = old_measurements_path.read_text(encoding="utf-8").splitlines(keepends=True)
    entries: list[tuple[tuple[Any, ...], str, str]] = []
    old_rio_lines = []
    old_manila_lines = []
    for line in old_lines:
        if not line.strip():
            continue
        row = json.loads(line)
        sensor_id = row["sensor_ref"].split("-")[1]
        if sensor_id == PRESERVED_RIO_SENSOR_ID:
            old_rio_lines.append(line)
        elif sensor_id == PRESERVED_METRO_MANILA_SENSOR_ID:
            old_manila_lines.append(line)
        else:
            raise PurpleAirReplacementCaptureError(
                f"existing measurement unexpectedly belongs to provider sensor {sensor_id}"
            )
        entries.append(
            (
                (row["sensor_ref"], row["observed_at"], row["source_result_index"]),
                line,
                sensor_id,
            )
        )
    for row in new_measurements:
        line = json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ) + "\n"
        entries.append(
            (
                (row["sensor_ref"], row["observed_at"], row["source_result_index"]),
                line,
                REPLACEMENT_SENSOR_ID,
            )
        )
    entries.sort(key=lambda entry: entry[0])
    combined_text = "".join(entry[1] for entry in entries)
    combined_by_sensor: dict[str, list[str]] = {}
    for _, line, sensor_id in entries:
        combined_by_sensor.setdefault(sensor_id, []).append(line)
    return (
        combined_text,
        combined_by_sensor.get(PRESERVED_RIO_SENSOR_ID, []) == old_rio_lines,
        combined_by_sensor.get(PRESERVED_METRO_MANILA_SENSOR_ID, []) == old_manila_lines,
    )


def _publish_merged_fixture(
    manifest_path: Path,
    replacement_manifest: dict[str, Any],
    new_measurements: list[dict[str, Any]],
    sensor_result: dict[str, Any],
    captured_at: datetime,
) -> dict[str, Any]:
    paths = _paths(manifest_path)
    old_manifest_bytes = paths["manifest"].read_bytes()
    old_report_bytes = paths["capture_report"].read_bytes()
    old_measurements_bytes = paths["measurements"].read_bytes()
    old_manifest = json.loads(old_manifest_bytes)
    old_manifest_sha = _sha256(paths["manifest"])
    old_measurements_sha = _sha256(paths["measurements"])
    combined_text, rio_unchanged, manila_unchanged = _combined_measurements_text(
        paths["measurements"], new_measurements
    )
    if not rio_unchanged or not manila_unchanged:
        raise PurpleAirReplacementCaptureError(
            "existing Rio or Metro Manila measurement lines changed during merge"
        )

    new_device, new_sensors = _new_device_and_sensors(old_manifest, sensor_result)
    for device in old_manifest["devices"]:
        metadata = dict(device.get("source_metadata") or {})
        if device["external_id"] == ORIGINAL_SENSOR_ID:
            metadata["active_reference_sensor"] = False
            metadata["reference_capture_status"] = "historical_http_200_zero_row_attempt"
        elif device["external_id"] in {
            PRESERVED_RIO_SENSOR_ID,
            PRESERVED_METRO_MANILA_SENSOR_ID,
        }:
            metadata["active_reference_sensor"] = True
        device["source_metadata"] = metadata
    old_manifest["devices"].append(new_device)
    old_manifest["sensors"].extend(new_sensors)
    for area in old_manifest["reference_areas"]:
        if area["fixture_ref"] == "new_york":
            area["active_provider_sensor_id"] = REPLACEMENT_SENSOR_ID
        elif area["fixture_ref"] == "rio_de_janeiro":
            area["active_provider_sensor_id"] = PRESERVED_RIO_SENSOR_ID
        elif area["fixture_ref"] == "metro_manila":
            area["active_provider_sensor_id"] = PRESERVED_METRO_MANILA_SENSOR_ID

    old_capture = old_manifest["capture"]
    replacement_capture = {
        "authorization_manifest_sha256": APPROVED_MANIFEST_SHA256,
        "endpoint_template": HISTORY_ENDPOINT_TEMPLATE,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "request_count": 1,
        "retry_count": 0,
        "captured_at": _utc_text(captured_at),
        "sensor_results": [sensor_result],
        "pricing": replacement_manifest["pricing"],
    }
    old_manifest["capture_history"] = [
        {
            "capture_kind": "original_phase_2i4c_three_sensor_capture",
            "frozen_manifest_sha256_before_replacement": old_manifest_sha,
            "frozen_measurements_sha256_before_replacement": old_measurements_sha,
            "archived_manifest": "capture_history/phase_2i4c/manifest.json",
            "archived_capture_report": "capture_history/phase_2i4c/capture_report.json",
            "archived_measurements": "capture_history/phase_2i4c/measurements.jsonl",
            "capture": old_capture,
        },
        {
            "capture_kind": "phase_2i4c2_new_york_replacement",
            **replacement_capture,
            "replaces_zero_row_sensor_id": ORIGINAL_SENSOR_ID,
        },
    ]
    old_manifest["capture"] = {
        "selection_manifest_sha256": APPROVED_MANIFEST_SHA256,
        "source_discovery_commit": old_capture["source_discovery_commit"],
        "endpoint_template": HISTORY_ENDPOINT_TEMPLATE,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "page_size": EXPECTED_ROWS,
        "max_pages_per_sensor": 1,
        "absolute_request_ceiling": 4,
        "retry_count": 0,
        "request_count": 4,
        "captured_at": _utc_text(captured_at),
        "sensor_results": [*old_capture["sensor_results"], sensor_result],
        "pricing": replacement_manifest["pricing"],
    }
    old_manifest["dataset_id"] = "purpleair_phase_2i4c2_2026-08-08_2026-08-11"
    old_manifest["origin"]["captured_at"] = _utc_text(captured_at)
    old_manifest["origin"]["description"] = (
        "Original Phase 2I.4C capture plus the approved Phase 2I.4C.2 "
        "New York replacement capture."
    )
    old_manifest["provenance"]["created_by"] = (
        "CompassAQ Phase 2I.4C and Phase 2I.4C.2 bounded paid captures"
    )
    old_manifest["provenance"]["source_reference"] = manifest_path.name
    old_manifest["known_limitations"] = [
        *old_manifest.get("known_limitations", []),
        (
            "New York sensor 198733 returned HTTP 200 with zero provider rows; "
            "that attempt remains preserved in capture_history."
        ),
        (
            "New York replacement sensor 159361 was selected manually; no metadata "
            "or discovery request was authorized."
        ),
    ]

    paths["archive_root"].mkdir(parents=True, exist_ok=True)
    archived_manifest = paths["archive_root"] / "manifest.json"
    archived_report = paths["archive_root"] / "capture_report.json"
    archived_measurements = paths["archive_root"] / "measurements.jsonl"
    if (
        archived_manifest.exists()
        or archived_report.exists()
        or archived_measurements.exists()
    ):
        raise PurpleAirReplacementCaptureError("original capture archive already exists")
    archived_manifest.write_bytes(old_manifest_bytes)
    archived_report.write_bytes(old_report_bytes)
    archived_measurements.write_bytes(old_measurements_bytes)

    with tempfile.TemporaryDirectory(
        prefix="purpleair-replacement-", dir=manifest_path.parent
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        temporary_measurements = temporary_root / "measurements.jsonl"
        temporary_measurements.write_text(
            combined_text, encoding="utf-8", newline="\n"
        )
        combined_measurements_sha = _sha256(temporary_measurements)
        old_manifest["measurements_sha256"] = combined_measurements_sha
        ReferenceFixtureManifest.model_validate(old_manifest)
        temporary_manifest = temporary_root / "manifest.json"
        _write_json(temporary_manifest, old_manifest)
        validated_manifest = read_fixture_manifest(temporary_root)
        validated_measurements = read_fixture_measurements(
            temporary_root, validated_manifest
        )
        expected_count = len(new_measurements) + sum(
            int(result["measurement_rows_preserved"])
            for result in old_capture["sensor_results"]
        )
        if len(validated_measurements) != expected_count:
            raise PurpleAirReplacementCaptureError(
                "merged fixture measurement count did not reconcile"
            )

        calculated_points = sensor_result["calculated_points_for_returned_rows"]
        report = {
            "provider": "PurpleAir",
            "replacement_sensor_id": REPLACEMENT_SENSOR_ID,
            "original_sensor_id": ORIGINAL_SENSOR_ID,
            "replacement_succeeded": True,
            "http_result": "HTTP 200",
            "provider_rows_returned": sensor_result["provider_rows_returned"],
            "pm25_rows_preserved": sensor_result["per_field_measurement_rows"][
                "pm2.5_atm"
            ],
            "pm10_rows_preserved": sensor_result["per_field_measurement_rows"][
                "pm10.0_atm"
            ],
            "request_count": 1,
            "retry_count": 0,
            "calculated_points_from_returned_rows": calculated_points,
            "hard_max_points": HARD_MAX_POINTS,
            "ceiling_respected": calculated_points <= HARD_MAX_POINTS,
            "open_aq_requests": 0,
            "airgradient_requests": 0,
            "other_candidate_requests": 0,
            "original_new_york_provenance_preserved": True,
            "rio_measurement_lines_unchanged": rio_unchanged,
            "manila_measurement_lines_unchanged": manila_unchanged,
            "authorization_manifest_sha256": APPROVED_MANIFEST_SHA256,
            "old_frozen_manifest_sha256": old_manifest_sha,
            "old_frozen_measurements_sha256": old_measurements_sha,
            "merged_measurements_sha256": combined_measurements_sha,
            "staged_response_sha256": _sha256(paths["stage"]),
            "captured_at": _utc_text(captured_at),
        }
        temporary_report = temporary_root / "capture_report.json"
        _write_json(temporary_report, report)
        temporary_replacement_report = temporary_root / "replacement_report.json"
        _write_json(temporary_replacement_report, report)
        temporary_measurements.replace(paths["measurements"])
        temporary_manifest.replace(paths["manifest"])
        temporary_report.replace(paths["capture_report"])
        temporary_replacement_report.replace(paths["replacement_report"])
    return {
        **report,
        "manifest": str(paths["manifest"]),
        "measurements": str(paths["measurements"]),
        "capture_report": str(paths["capture_report"]),
        "replacement_report": str(paths["replacement_report"]),
        "staged_response": str(paths["stage"]),
    }


def execute_replacement_capture(
    manifest_path: Path,
    api_key: str,
    *,
    authorization: PaidProviderAuthorization,
    request_executor: RequestExecutor | None = None,
    request_scope: ContextManager[None] | None = None,
) -> dict[str, Any]:
    if _sha256(manifest_path) != APPROVED_MANIFEST_SHA256:
        raise PurpleAirReplacementCaptureError("approved replacement manifest checksum mismatch")
    replacement_manifest = _validate_exact_manifest(manifest_path)
    _validate_preserved_capture(manifest_path, replacement_manifest)
    if authorization.provider_name != "purpleair" or authorization.execution_mode != "manual":
        raise PurpleAirReplacementCaptureError("manual PurpleAir authorization is required")
    if not api_key.strip():
        raise PurpleAirReplacementCaptureError("configured PurpleAir API key is required")
    if request_executor is None and os.getenv("COMPASSAQ_ENV", "").strip().lower() == "test":
        raise PurpleAirReplacementCaptureError("real PurpleAir transport is blocked in tests")
    if ESTIMATED_POINTS > HARD_MAX_POINTS:
        raise PurpleAirReplacementCaptureError(
            "the request cannot be proven to remain within the approved point ceiling"
        )
    paths = _paths(manifest_path)
    for path in (
        paths["stage"],
        paths["replacement_report"],
        paths["failure_report"],
    ):
        if path.exists():
            raise PurpleAirReplacementCaptureError(
                f"replacement capture artifact already exists; another request is prohibited: {path}"
            )

    endpoint = HISTORY_ENDPOINT_TEMPLATE.format(sensor_id=REPLACEMENT_SENSOR_ID)
    query = {
        "start_timestamp": 1786147200,
        "end_timestamp": 1786406400,
        "fields": ",".join(FIELDS),
        "average": 0,
    }
    executor = request_executor or _single_purpleair_get
    scope = request_scope or nullcontext()
    try:
        with scope:
            response = _coerce_response(
                executor(endpoint, query, {"X-API-Key": api_key})
            )
    except Exception as exc:
        return _failure_report(
            paths,
            http_result="transport_error",
            reason=f"{type(exc).__name__}: {exc}",
            request_count=1,
            provider_rows=None,
            calculated_points=None,
        )

    _write_staged_response(paths["stage"], endpoint, query, response)
    raw_rows = response.payload.get("data") if isinstance(response.payload, dict) else None
    provider_row_count = len(raw_rows) if isinstance(raw_rows, list) else None
    calculated_points = (
        HISTORY_ENDPOINT_BASE_POINTS + provider_row_count * POINTS_PER_PROVIDER_ROW
        if provider_row_count is not None
        else None
    )
    if response.status_code < 200 or response.status_code >= 300:
        return _failure_report(
            paths,
            http_result=f"HTTP {response.status_code}",
            reason="non_success_http_response",
            request_count=1,
            provider_rows=provider_row_count,
            calculated_points=calculated_points,
        )
    if not isinstance(response.payload, dict):
        return _failure_report(
            paths,
            http_result="HTTP 200",
            reason="malformed_non_object_provider_response",
            request_count=1,
            provider_rows=None,
            calculated_points=None,
        )
    if response.payload.get("sensor_index") != int(REPLACEMENT_SENSOR_ID):
        return _failure_report(
            paths,
            http_result="HTTP 200",
            reason="provider_sensor_id_mismatch",
            request_count=1,
            provider_rows=provider_row_count,
            calculated_points=calculated_points,
        )
    try:
        normalized, sensor_result = _normalize_sensor_response(
            PurpleAirResponse(
                payload=response.payload,
                headers=response.headers,
                status_code=response.status_code,
            ),
            {
                "sensor_id": REPLACEMENT_SENSOR_ID,
                "reference_area_code": "new_york",
            },
        )
    except Exception as exc:
        return _failure_report(
            paths,
            http_result="HTTP 200",
            reason=f"malformed_provider_data: {type(exc).__name__}: {exc}",
            request_count=1,
            provider_rows=provider_row_count,
            calculated_points=calculated_points,
        )
    if calculated_points is None or calculated_points > HARD_MAX_POINTS:
        return _failure_report(
            paths,
            http_result="HTTP 200",
            reason="returned_row_point_calculation_exceeds_hard_ceiling",
            request_count=1,
            provider_rows=provider_row_count,
            calculated_points=calculated_points,
        )
    if (
        sensor_result["outside_window_rows_excluded"] != 0
        or sensor_result["end_boundary_rows_excluded"] != 0
        or sensor_result["provider_rows_preserved"] != provider_row_count
    ):
        return _failure_report(
            paths,
            http_result="HTTP 200",
            reason="provider_rows_outside_approved_half_open_window",
            request_count=1,
            provider_rows=provider_row_count,
            calculated_points=calculated_points,
        )
    if provider_row_count == 0 or not normalized:
        return _failure_report(
            paths,
            http_result="HTTP 200",
            reason="zero_usable_provider_rows",
            request_count=1,
            provider_rows=0,
            calculated_points=HISTORY_ENDPOINT_BASE_POINTS,
        )
    sensor_result["replacement_for_sensor_id"] = ORIGINAL_SENSOR_ID
    return _publish_merged_fixture(
        manifest_path,
        replacement_manifest,
        normalized,
        sensor_result,
        datetime.now(timezone.utc),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-request PurpleAir New York replacement capture"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-provider-api", action="store_true")
    parser.add_argument("--allow-paid-api", action="store_true")
    parser.add_argument("--confirm-manifest-sha", default="")
    parser.add_argument("--max-purpleair-points", type=int, default=0)
    parser.add_argument("--confirm-bounded-new-york-replacement", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required; use purpleair_replacement_preflight for dry-run")
    validate_execution_authorization(
        allow_provider_api=args.allow_provider_api,
        allow_paid_api=args.allow_paid_api,
        confirm_manifest_sha=args.confirm_manifest_sha,
        max_purpleair_points=args.max_purpleair_points,
        confirm_bounded_replacement=args.confirm_bounded_new_york_replacement,
    )
    manifest_path = args.manifest.resolve()
    with SessionLocal() as session:
        authorization = require_paid_provider_authorization(
            session,
            "PurpleAir",
            explicit_manual_authorization=True,
        )
        source = session.scalar(
            select(models.ExternalAPI).where(
                func.lower(models.ExternalAPI.name) == "purpleair"
            )
        )
        api_key = source.api_key if source is not None else None
        report = execute_replacement_capture(
            manifest_path,
            api_key or "",
            authorization=authorization,
            request_scope=paid_provider_request_scope(authorization),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
