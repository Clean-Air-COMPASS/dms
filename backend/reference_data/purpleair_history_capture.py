"""One-shot, bounded PurpleAir capture for the approved Phase 2I.4C window.

This module is deliberately separate from the production importer. It supports
one immutable manifest, three allowlisted history requests, no discovery,
metadata requests, pagination, or retries, and refuses to overwrite a frozen
fixture. The local dry-run path does not read credentials or import an HTTP
client.
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
from reference_data.capture import plan_capture
from reference_data.fixture_io import (
    read_fixture_manifest,
    read_fixture_measurements,
    sha256_file as _sha256,
)
from reference_data.schema import FixtureMeasurement, ReferenceFixtureManifest
from services.provider_safety import (
    PaidProviderAuthorization,
    paid_provider_request_scope,
    require_paid_provider_authorization,
)


APPROVED_MANIFEST_SHA256 = (
    "c3a2a23290958b7818c497315f1b157ece44ce8b2c60d1f53e2f4809d7392d4f"
)
APPROVED_SENSOR_IDS = ("198733", "175407", "99177")
APPROVED_FIELDS = ("pm2.5_atm", "pm10.0_atm")
APPROVED_WINDOW_START = "2026-08-08T00:00:00Z"
APPROVED_WINDOW_END = "2026-08-11T00:00:00Z"
APPROVED_PRICING_VERIFIED_AT = "2026-08-11T21:25:00-07:00"
APPROVED_MAX_POINTS = 28519
EXPECTED_ROWS_PER_SENSOR = 2160
EXPECTED_PROVIDER_ROWS = EXPECTED_ROWS_PER_SENSOR * len(APPROVED_SENSOR_IDS)
HISTORY_BASE_POINTS = 2
POINTS_PER_PROVIDER_ROW = 4
EXPECTED_POINTS = len(APPROVED_SENSOR_IDS) * HISTORY_BASE_POINTS + (
    EXPECTED_PROVIDER_ROWS * POINTS_PER_PROVIDER_ROW
)
HISTORY_ENDPOINT_TEMPLATE = (
    "https://api.purpleair.com/v1/sensors/{sensor_id}/history"
)
REFERENCE_FIXTURE_SCHEMA_VERSION = "2i.1"
SOURCE_BASELINE_COMMIT = "8b881cc10b8b8c84d7e62639eba121d7d0d4cd6c"
ACCESS_CLASSIFICATION = "restricted_private_not_approved_for_public_redistribution"
PROVIDER_UNIT = "µg/m³"


class PurpleAirHistoryCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class PurpleAirResponse:
    payload: dict[str, Any]
    headers: dict[str, str]
    status_code: int = 200


RequestExecutor = Callable[
    [str, dict[str, Any], dict[str, str]], PurpleAirResponse | dict[str, Any]
]

def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PurpleAirHistoryCaptureError(f"timestamp must be explicit UTC: {value!r}")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_approved_manifest(path: Path) -> dict[str, Any]:
    actual_sha = _sha256(path)
    if actual_sha != APPROVED_MANIFEST_SHA256:
        raise PurpleAirHistoryCaptureError(
            "approved capture manifest checksum mismatch: "
            f"expected {APPROVED_MANIFEST_SHA256}, got {actual_sha}"
        )
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PurpleAirHistoryCaptureError(f"invalid capture manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PurpleAirHistoryCaptureError("capture manifest must be a JSON object")

    exact_values = {
        "schema_version": "2i.4b",
        "provider": "PurpleAir",
        "fields": list(APPROVED_FIELDS),
        "average": 0,
        "history_endpoint_template": HISTORY_ENDPOINT_TEMPLATE,
        "window_start": APPROVED_WINDOW_START,
        "window_end": APPROVED_WINDOW_END,
        "expected_frequency_seconds": 120,
        "measurement_duration_seconds": 120,
        "source_aggregation_duration_seconds": 120,
        "measurement_timestamp_semantics": "provider_received_at",
        "metadata_request_count": 0,
        "retry_count": 0,
        "paid_provider": True,
        "access_classification": ACCESS_CLASSIFICATION,
        "automatic_refresh": False,
        "scheduled_capture": False,
    }
    for field, expected in exact_values.items():
        if manifest.get(field) != expected:
            raise PurpleAirHistoryCaptureError(f"{field} must remain {expected!r}")
    reference_sensors = manifest.get("reference_sensors")
    if not isinstance(reference_sensors, list):
        raise PurpleAirHistoryCaptureError("reference_sensors must be a list")
    ids = tuple(str(sensor.get("sensor_id")) for sensor in reference_sensors)
    if ids != APPROVED_SENSOR_IDS:
        raise PurpleAirHistoryCaptureError(
            f"sensor IDs must remain the approved ordered set {APPROVED_SENSOR_IDS}"
        )
    pricing = manifest.get("pricing")
    if not isinstance(pricing, dict):
        raise PurpleAirHistoryCaptureError("pricing must be an object")
    pricing_exact = {
        "verified_at": APPROVED_PRICING_VERIFIED_AT,
        "history_endpoint_base_points": HISTORY_BASE_POINTS,
        "history_field_points": {"pm2.5_atm": 2, "pm10.0_atm": 2},
        "safety_margin_percent": 10,
        "safety_margin_status": "approved",
    }
    for field, expected in pricing_exact.items():
        if pricing.get(field) != expected:
            raise PurpleAirHistoryCaptureError(f"pricing.{field} must remain {expected!r}")
    if EXPECTED_POINTS != 25926 or math.ceil(EXPECTED_POINTS * 1.10) != APPROVED_MAX_POINTS:
        raise PurpleAirHistoryCaptureError("internal approved point calculation changed")
    return manifest


def build_dry_run_report(
    manifest_path: Path,
    request_executor: RequestExecutor | None = None,
) -> dict[str, Any]:
    """Validate the immutable capture locally without reading environment secrets."""
    del request_executor
    manifest = _read_approved_manifest(manifest_path)
    planned = plan_capture(manifest_path)
    if not planned["capture_ready"]:
        raise PurpleAirHistoryCaptureError(
            f"approved manifest has local blockers: {planned['blockers']}"
        )
    return {
        **planned,
        "authorization_manifest_sha256": APPROVED_MANIFEST_SHA256,
        "approved_sensor_ids": list(APPROVED_SENSOR_IDS),
        "approved_max_points": APPROVED_MAX_POINTS,
        "expected_points": EXPECTED_POINTS,
        "request_ceiling": 3,
        "requests": [
            {
                "sensor_id": str(sensor["sensor_id"]),
                "endpoint": HISTORY_ENDPOINT_TEMPLATE.format(
                    sensor_id=sensor["sensor_id"]
                ),
                "query": {
                    "start_timestamp": int(_utc(APPROVED_WINDOW_START).timestamp()),
                    "end_timestamp": int(_utc(APPROVED_WINDOW_END).timestamp()),
                    "fields": ",".join(APPROVED_FIELDS),
                    "average": 0,
                },
                "maximum_expected_provider_rows": EXPECTED_ROWS_PER_SENSOR,
                "maximum_expected_points": (
                    HISTORY_BASE_POINTS
                    + EXPECTED_ROWS_PER_SENSOR * POINTS_PER_PROVIDER_ROW
                ),
            }
            for sensor in manifest["reference_sensors"]
        ],
        "credentials_read": False,
        "network_requests_executed": 0,
    }


def validate_execution_authorization(
    *,
    allow_provider_api: bool,
    allow_paid_api: bool,
    confirm_manifest_sha: str,
    max_purpleair_points: int,
    confirm_bounded_history: bool,
) -> None:
    if not allow_provider_api:
        raise PurpleAirHistoryCaptureError("--allow-provider-api is required")
    if not allow_paid_api:
        raise PurpleAirHistoryCaptureError("--allow-paid-api is required")
    if not confirm_bounded_history:
        raise PurpleAirHistoryCaptureError(
            "--confirm-bounded-purpleair-history is required"
        )
    if confirm_manifest_sha != APPROVED_MANIFEST_SHA256:
        raise PurpleAirHistoryCaptureError(
            "--confirm-manifest-sha must equal the approved manifest SHA-256"
        )
    if max_purpleair_points != APPROVED_MAX_POINTS:
        raise PurpleAirHistoryCaptureError(
            f"--max-purpleair-points must equal {APPROVED_MAX_POINTS}"
        )


def _safe_response_headers(headers: Any) -> dict[str, str]:
    if not hasattr(headers, "items"):
        return {}
    allowed_prefixes = ("x-purpleair-", "x-ratelimit-")
    return {
        str(name): str(value)
        for name, value in headers.items()
        if str(name).lower().startswith(allowed_prefixes)
    }


def _single_purpleair_get(
    endpoint: str,
    query: dict[str, Any],
    headers: dict[str, str],
) -> PurpleAirResponse:
    from services.provider_safety import assert_paid_provider_http_authorized

    assert_paid_provider_http_authorized("PurpleAir")
    import requests

    response = requests.get(
        endpoint,
        params=query,
        headers=headers,
        timeout=30,
        allow_redirects=False,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise PurpleAirHistoryCaptureError("PurpleAir response must be a JSON object")
    return PurpleAirResponse(
        payload=payload,
        headers=_safe_response_headers(response.headers),
        status_code=response.status_code,
    )


def _coerce_response(value: PurpleAirResponse | dict[str, Any]) -> PurpleAirResponse:
    if isinstance(value, PurpleAirResponse):
        return value
    if isinstance(value, dict):
        return PurpleAirResponse(payload=value, headers={})
    raise PurpleAirHistoryCaptureError("PurpleAir response executor returned an invalid value")


def _field_positions(payload_fields: Any) -> dict[str, int]:
    if payload_fields == list(APPROVED_FIELDS):
        return {field: index + 1 for index, field in enumerate(APPROVED_FIELDS)}
    if payload_fields == ["time_stamp", *APPROVED_FIELDS]:
        return {field: index + 1 for index, field in enumerate(APPROVED_FIELDS)}
    raise PurpleAirHistoryCaptureError(
        "PurpleAir response fields changed; expected only time_stamp and the two approved fields"
    )


def _normalize_sensor_response(
    response: PurpleAirResponse,
    sensor: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sensor_id = str(sensor["sensor_id"])
    payload = response.payload
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise PurpleAirHistoryCaptureError(
            f"sensor {sensor_id} response is missing a data array"
        )
    positions = _field_positions(payload.get("fields"))
    window_start = _utc(APPROVED_WINDOW_START)
    window_end = _utc(APPROVED_WINDOW_END)
    measurements: list[dict[str, Any]] = []
    timestamps: list[datetime] = []
    end_boundary_excluded = 0
    outside_window_excluded = 0
    for result_index, row in enumerate(rows):
        if not isinstance(row, list):
            raise PurpleAirHistoryCaptureError(
                f"sensor {sensor_id} result {result_index} is not an array"
            )
        if len(row) <= max(positions.values()):
            raise PurpleAirHistoryCaptureError(
                f"sensor {sensor_id} result {result_index} is missing an approved field"
            )
        raw_timestamp = row[0]
        if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (int, float)):
            raise PurpleAirHistoryCaptureError(
                f"sensor {sensor_id} result {result_index} has an invalid timestamp"
            )
        try:
            observed_at = datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise PurpleAirHistoryCaptureError(
                f"sensor {sensor_id} result {result_index} has an invalid timestamp"
            ) from exc
        if observed_at == window_end:
            end_boundary_excluded += 1
            continue
        if observed_at < window_start or observed_at >= window_end:
            outside_window_excluded += 1
            continue
        timestamps.append(observed_at)
        for field in APPROVED_FIELDS:
            raw_value = row[positions[field]]
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise PurpleAirHistoryCaptureError(
                    f"sensor {sensor_id} result {result_index} field {field} is not numeric"
                )
            value = float(raw_value)
            if not math.isfinite(value):
                raise PurpleAirHistoryCaptureError(
                    f"sensor {sensor_id} result {result_index} field {field} is not finite"
                )
            parameter_code = "pm25" if field == "pm2.5_atm" else "pm10"
            measurements.append(
                {
                    "sensor_ref": f"purpleair-{sensor_id}-{parameter_code}",
                    "observed_at": _utc_text(observed_at),
                    "value": raw_value,
                    "is_valid": True,
                    "qc_flags": {
                        "provider": "PurpleAir",
                        "provider_validity_status": "not_supplied",
                        "value_and_unit_preserved_without_conversion": True,
                        "timestamp_semantics": "provider_received_at",
                    },
                    "qc_version": "purpleair-provider-source-phase-2i.4c",
                    "provider_observation_ref": (
                        f"purpleair:{sensor_id}:{raw_timestamp}:{result_index}:{field}"
                    ),
                    "source_page": 1,
                    "source_result_index": result_index,
                    "provider_parameter": {"name": field, "units": PROVIDER_UNIT},
                    "provider_field": field,
                    "provider_timestamp": raw_timestamp,
                }
            )
    timestamp_counts: dict[str, int] = {}
    for observed_at in timestamps:
        key = _utc_text(observed_at)
        timestamp_counts[key] = timestamp_counts.get(key, 0) + 1
    duplicate_count = sum(count - 1 for count in timestamp_counts.values() if count > 1)
    sorted_unique = sorted(set(timestamps))
    gaps = sorted(
        {
            int((later - earlier).total_seconds())
            for earlier, later in zip(sorted_unique, sorted_unique[1:])
        }
    )
    return measurements, {
        "provider_sensor_id": sensor_id,
        "reference_area_code": sensor["reference_area_code"],
        "requests_executed": 1,
        "provider_rows_returned": len(rows),
        "provider_rows_preserved": len(timestamps),
        "measurement_rows_preserved": len(measurements),
        "per_field_measurement_rows": {
            field: sum(row["provider_field"] == field for row in measurements)
            for field in APPROVED_FIELDS
        },
        "exact_timestamp_duplicate_count": duplicate_count,
        "end_boundary_rows_excluded": end_boundary_excluded,
        "outside_window_rows_excluded": outside_window_excluded,
        "observed_timestamp_gap_values_seconds": gaps,
        "calculated_points_for_returned_rows": (
            HISTORY_BASE_POINTS + len(rows) * POINTS_PER_PROVIDER_ROW
        ),
        "provider_point_headers": response.headers,
        "http_status_code": response.status_code,
        "completion_status": "complete_single_request",
        "failure_reason": None,
    }


def _fixture_paths(manifest_path: Path) -> dict[str, Path]:
    fixture_base = manifest_path.parent.parents[1]
    output_root = fixture_base / "restricted" / "purpleair"
    return {
        "manifest": output_root / "manifest.json",
        "measurements": output_root / "measurements.jsonl",
        "report": output_root / "capture_report.json",
        "failure_report": output_root / "capture_failure_report.json",
        "staging": output_root / "capture_staging",
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_staged_response(
    staging_root: Path,
    sensor_id: str,
    endpoint: str,
    query: dict[str, Any],
    response: PurpleAirResponse,
) -> Path:
    path = staging_root / f"sensor-{sensor_id}.json"
    if path.exists():
        raise PurpleAirHistoryCaptureError(
            f"staged response already exists and will not be overwritten: {path}"
        )
    _write_json(
        path,
        {
            "provider": "PurpleAir",
            "sensor_id": sensor_id,
            "endpoint": endpoint,
            "query": query,
            "response_status_code": response.status_code,
            "response_headers": response.headers,
            "response_payload": response.payload,
        },
    )
    return path


def _device_and_sensor_records(
    selected: list[dict[str, Any]],
    result_by_sensor: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    devices = []
    sensors = []
    areas = []
    for selected_sensor in selected:
        sensor_id = str(selected_sensor["sensor_id"])
        area_code = selected_sensor["reference_area_code"]
        device_name = selected_sensor.get("device_name") or (
            f"PurpleAir {sensor_id} (provider name not supplied)"
        )
        areas.append(
            {
                "fixture_ref": area_code,
                "name": selected_sensor["reference_area_name"],
                "description": "Approved Phase 2I.4C PurpleAir reference area.",
                "timezone": selected_sensor["timezone"],
            }
        )
        devices.append(
            {
                "fixture_ref": f"purpleair-device-{sensor_id}",
                "external_id": sensor_id,
                "name": device_name,
                "friendly_name": selected_sensor.get("device_name"),
                "latitude": selected_sensor.get("latitude"),
                "longitude": selected_sensor.get("longitude"),
                "timezone": selected_sensor["timezone"],
                "reference_area_ref": area_code,
                "provider_name": "PurpleAir",
                "hardware_provider": "PurpleAir",
                "source_metadata": {
                    "provider_sensor_id": sensor_id,
                    "selection_status": selected_sensor["selection_status"],
                    "identification_source": selected_sensor["identification_source"],
                    "known_limitations": selected_sensor["known_limitations"],
                    "metadata_request_performed": False,
                },
            }
        )
        capture_result = result_by_sensor[sensor_id]
        for field, parameter_code in (("pm2.5_atm", "pm25"), ("pm10.0_atm", "pm10")):
            field_rows = capture_result["per_field_measurement_rows"][field]
            sensors.append(
                {
                    "fixture_ref": f"purpleair-{sensor_id}-{parameter_code}",
                    "device_ref": f"purpleair-device-{sensor_id}",
                    "external_sensor_id": f"{sensor_id}:{field}",
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
                    "provider_unit": PROVIDER_UNIT,
                    "hardware_provider": "PurpleAir",
                    "temporal_qualification": {
                        "status": "provider_documented",
                        "timestamp_semantics": "provider_received_at",
                        "expected_frequency_seconds": 120,
                        "observed_timestamp_gap_values_seconds": capture_result[
                            "observed_timestamp_gap_values_seconds"
                        ],
                    },
                    "capture_statistics": {
                        "provider_sensor_id": sensor_id,
                        "provider_field": field,
                        "measurement_rows_preserved": field_rows,
                    },
                }
            )
    return devices, sensors, areas


def _publish_fixture(
    manifest_path: Path,
    approved_manifest: dict[str, Any],
    measurements: list[dict[str, Any]],
    sensor_results: list[dict[str, Any]],
    captured_at: datetime,
    staged_paths: list[Path],
) -> dict[str, Any]:
    paths = _fixture_paths(manifest_path)
    devices, sensors, areas = _device_and_sensor_records(
        approved_manifest["reference_sensors"],
        {result["provider_sensor_id"]: result for result in sensor_results},
    )
    measurements.sort(
        key=lambda row: (
            row["sensor_ref"],
            row["observed_at"],
            row["source_result_index"],
        )
    )
    for row in measurements:
        FixtureMeasurement.model_validate(row)

    with tempfile.TemporaryDirectory(
        prefix="purpleair-capture-", dir=paths["manifest"].parent
    ) as temp:
        temporary_root = Path(temp)
        temporary_measurements = temporary_root / "measurements.jsonl"
        temporary_measurements.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
                for row in measurements
            ),
            encoding="utf-8",
            newline="\n",
        )
        measurement_sha = _sha256(temporary_measurements)
        fixture_manifest = {
            "schema_version": REFERENCE_FIXTURE_SCHEMA_VERSION,
            "dataset_id": "purpleair_phase_2i4c_2026-08-08_2026-08-11",
            "provider": "PurpleAir",
            "provider_profile": "purpleair_2m",
            "access_classification": ACCESS_CLASSIFICATION,
            "origin": {
                "origin_kind": "provider_capture",
                "captured_at": _utc_text(captured_at),
                "description": (
                    "Bounded three-sensor PurpleAir history capture approved "
                    "for Phase 2I.4C."
                ),
            },
            "reference_area": {
                "name": "Phase 2I.4C approved PurpleAir reference areas",
                "description": "New York, Rio de Janeiro, and Metro Manila allowlisted sensors.",
                "timezone": "UTC",
            },
            "reference_areas": areas,
            "license": {
                "status": ACCESS_CLASSIFICATION,
                "attribution": "PurpleAir and the sensor owners identified in source metadata",
                "redistribution_approved": False,
            },
            "provider_chain": [
                {"provider": "PurpleAir", "role": "origin"},
                {"provider": "CompassAQ frozen fixture", "role": "fixture"},
            ],
            "provenance": {
                "created_by": "CompassAQ Phase 2I.4C bounded paid capture",
                "methodology": (
                    "Exact allowlisted PurpleAir history requests with average=0; source values "
                    "and provider-received timestamps preserved without conversion, AQI, "
                    "correction, interpolation, or invented metadata."
                ),
                "source_reference": manifest_path.name,
            },
            "capture": {
                "selection_manifest_sha256": APPROVED_MANIFEST_SHA256,
                "source_discovery_commit": SOURCE_BASELINE_COMMIT,
                "endpoint_template": HISTORY_ENDPOINT_TEMPLATE,
                "window_start": APPROVED_WINDOW_START,
                "window_end": APPROVED_WINDOW_END,
                "page_size": EXPECTED_ROWS_PER_SENSOR,
                "max_pages_per_sensor": 1,
                "absolute_request_ceiling": 3,
                "retry_count": 0,
                "request_count": 3,
                "captured_at": _utc_text(captured_at),
                "sensor_results": sensor_results,
                "pricing": approved_manifest["pricing"],
            },
            "known_limitations": [
                "This restricted fixture is not approved for public redistribution.",
                (
                    "No metadata request was authorized; unknown device names or "
                    "coordinates remain unknown."
                ),
                (
                    "PurpleAir time_stamp is preserved as provider_received_at and "
                    "is not treated as a documented interval boundary."
                ),
                (
                    "No provider validity flags were supplied by this history "
                    "response; records retain an explicit not-supplied status."
                ),
            ],
            "devices": devices,
            "sensors": sensors,
            "measurements_file": "measurements.jsonl",
            "measurements_sha256": measurement_sha,
        }
        ReferenceFixtureManifest.model_validate(fixture_manifest)
        temporary_manifest = temporary_root / "manifest.json"
        _write_json(temporary_manifest, fixture_manifest)
        validated = read_fixture_manifest(temporary_root)
        validated_rows = read_fixture_measurements(temporary_root, validated)
        if len(validated_rows) != len(measurements):
            raise PurpleAirHistoryCaptureError("fixture validation changed measurement row count")

        total_provider_rows = sum(
            result["provider_rows_returned"] for result in sensor_results
        )
        point_total = sum(
            result["calculated_points_for_returned_rows"] for result in sensor_results
        )
        report = {
            "provider": "PurpleAir",
            "authorization_manifest_sha256": APPROVED_MANIFEST_SHA256,
            "capture_code_baseline_commit": SOURCE_BASELINE_COMMIT,
            "network_requests_executed": 3,
            "request_ceiling": 3,
            "retry_count": 0,
            "request_counts": {
                "PurpleAir history": 3,
                "PurpleAir metadata": 0,
                "OpenAQ": 0,
                "AirGradient": 0,
            },
            "window_start": APPROVED_WINDOW_START,
            "window_end_exclusive": APPROVED_WINDOW_END,
            "average": 0,
            "fields": list(APPROVED_FIELDS),
            "pricing": approved_manifest["pricing"],
            "provider_rows_returned": total_provider_rows,
            "expected_provider_rows_at_full_two_minute_cadence": EXPECTED_PROVIDER_ROWS,
            "measurement_rows_preserved": len(measurements),
            "pm25_measurement_rows": sum(
                row["provider_field"] == "pm2.5_atm" for row in measurements
            ),
            "pm10_measurement_rows": sum(
                row["provider_field"] == "pm10.0_atm" for row in measurements
            ),
            "point_accounting": {
                "formula": "requests * 2 + provider_rows * (2 + 2)",
                "calculated_from_returned_rows": point_total,
                "approved_expected_points": EXPECTED_POINTS,
                "approved_hard_ceiling": APPROVED_MAX_POINTS,
                "within_approved_hard_ceiling": point_total <= APPROVED_MAX_POINTS,
                "provider_headers_by_sensor": {
                    result["provider_sensor_id"]: result["provider_point_headers"]
                    for result in sensor_results
                },
            },
            "sensor_results": sensor_results,
            "staged_responses": [str(path) for path in staged_paths],
            "measurements_sha256": measurement_sha,
            "access_classification": ACCESS_CLASSIFICATION,
            "automatic_refresh": False,
            "scheduled_capture": False,
            "fixture_validation_status": "passed_before_publication",
        }
        temporary_report = temporary_root / "capture_report.json"
        _write_json(temporary_report, report)
        temporary_measurements.replace(paths["measurements"])
        temporary_manifest.replace(paths["manifest"])
        temporary_report.replace(paths["report"])
    return {
        **report,
        "manifest": str(paths["manifest"]),
        "measurements": str(paths["measurements"]),
        "capture_report": str(paths["report"]),
    }


def execute_bounded_capture(
    manifest_path: Path,
    api_key: str,
    *,
    authorization: PaidProviderAuthorization,
    request_executor: RequestExecutor | None = None,
    request_scope: ContextManager[None] | None = None,
) -> dict[str, Any]:
    approved_manifest = _read_approved_manifest(manifest_path)
    if authorization.provider_name != "purpleair" or authorization.execution_mode != "manual":
        raise PurpleAirHistoryCaptureError("manual PurpleAir authorization is required")
    if not api_key.strip():
        raise PurpleAirHistoryCaptureError("configured PurpleAir API key is required")
    if request_executor is None and os.getenv("COMPASSAQ_ENV", "").strip().lower() == "test":
        raise PurpleAirHistoryCaptureError("real PurpleAir transport is blocked in tests")
    paths = _fixture_paths(manifest_path)
    final_paths = [paths["manifest"], paths["measurements"], paths["report"]]
    existing = [str(path) for path in final_paths if path.exists()]
    if existing:
        raise PurpleAirHistoryCaptureError(
            "frozen capture output already exists; overwrite and automatic refresh are prohibited: "
            + ", ".join(existing)
        )
    paths["staging"].mkdir(parents=True, exist_ok=True)
    existing_staged = list(paths["staging"].glob("sensor-*.json"))
    if existing_staged:
        raise PurpleAirHistoryCaptureError(
            "staged responses already exist and will not be overwritten: "
            + ", ".join(str(path) for path in existing_staged)
        )
    executor = request_executor or _single_purpleair_get
    scope = request_scope or nullcontext()
    measurements: list[dict[str, Any]] = []
    sensor_results: list[dict[str, Any]] = []
    staged_paths: list[Path] = []
    request_count = 0
    calculated_points = 0
    captured_at = datetime.now(timezone.utc)
    current_sensor_id: str | None = None
    current_endpoint: str | None = None
    try:
        with scope:
            for sensor in approved_manifest["reference_sensors"]:
                remaining_after_this = len(APPROVED_SENSOR_IDS) - request_count - 1
                maximum_after_next_request = (
                    calculated_points
                    + HISTORY_BASE_POINTS
                    + EXPECTED_ROWS_PER_SENSOR * POINTS_PER_PROVIDER_ROW
                    + remaining_after_this
                    * (HISTORY_BASE_POINTS + EXPECTED_ROWS_PER_SENSOR * POINTS_PER_PROVIDER_ROW)
                )
                if maximum_after_next_request > APPROVED_MAX_POINTS:
                    raise PurpleAirHistoryCaptureError(
                        "next request cannot be proven to remain within the approved point ceiling"
                    )
                sensor_id = str(sensor["sensor_id"])
                endpoint = HISTORY_ENDPOINT_TEMPLATE.format(sensor_id=sensor_id)
                current_sensor_id = sensor_id
                current_endpoint = endpoint
                query = {
                    "start_timestamp": int(_utc(APPROVED_WINDOW_START).timestamp()),
                    "end_timestamp": int(_utc(APPROVED_WINDOW_END).timestamp()),
                    "fields": ",".join(APPROVED_FIELDS),
                    "average": 0,
                }
                request_count += 1
                response = _coerce_response(
                    executor(endpoint, query, {"X-API-Key": api_key})
                )
                staged_paths.append(
                    _write_staged_response(
                        paths["staging"], sensor_id, endpoint, query, response
                    )
                )
                sensor_measurements, sensor_result = _normalize_sensor_response(
                    response, sensor
                )
                calculated_points += sensor_result["calculated_points_for_returned_rows"]
                if calculated_points > APPROVED_MAX_POINTS:
                    raise PurpleAirHistoryCaptureError(
                        "returned-row point calculation exceeds the approved hard ceiling"
                    )
                measurements.extend(sensor_measurements)
                sensor_results.append(sensor_result)
    except Exception as exc:
        failure = {
            "provider": "PurpleAir",
            "status": "failed_without_retry",
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "network_requests_executed": request_count,
            "failed_sensor_id": current_sensor_id,
            "failed_request_number": request_count,
            "failed_endpoint": current_endpoint,
            "retry_count": 0,
            "completed_sensor_results": sensor_results,
            "staged_responses": [str(path) for path in staged_paths],
            "known_points_from_completed_responses": calculated_points,
            "maximum_points_if_failed_request_was_fully_charged": (
                calculated_points
                + HISTORY_BASE_POINTS
                + EXPECTED_ROWS_PER_SENSOR * POINTS_PER_PROVIDER_ROW
            ),
            "approved_hard_ceiling": APPROVED_MAX_POINTS,
            "new_explicit_approval_required_before_any_additional_request": True,
        }
        if not paths["failure_report"].exists():
            _write_json(paths["failure_report"], failure)
        raise
    if request_count != 3 or len(sensor_results) != 3:
        raise PurpleAirHistoryCaptureError("capture did not complete exactly three requests")
    return _publish_fixture(
        manifest_path,
        approved_manifest,
        measurements,
        sensor_results,
        captured_at,
        staged_paths,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bounded PurpleAir Phase 2I.4C history capture"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-provider-api", action="store_true")
    parser.add_argument("--allow-paid-api", action="store_true")
    parser.add_argument("--confirm-manifest-sha", default="")
    parser.add_argument("--max-purpleair-points", type=int, default=0)
    parser.add_argument("--confirm-bounded-purpleair-history", action="store_true")
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    if args.dry_run:
        report = build_dry_run_report(manifest_path)
    else:
        validate_execution_authorization(
            allow_provider_api=args.allow_provider_api,
            allow_paid_api=args.allow_paid_api,
            confirm_manifest_sha=args.confirm_manifest_sha,
            max_purpleair_points=args.max_purpleair_points,
            confirm_bounded_history=args.confirm_bounded_purpleair_history,
        )
        _read_approved_manifest(manifest_path)
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
            report = execute_bounded_capture(
                manifest_path,
                api_key or "",
                authorization=authorization,
                request_scope=paid_provider_request_scope(authorization),
            )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
