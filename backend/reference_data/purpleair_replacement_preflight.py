"""Zero-network preflight for the New York PurpleAir replacement candidate.

This module validates one local manifest and the existing frozen-capture
evidence. It intentionally contains no provider client, credential lookup, or
outbound request implementation. A successful report means the plan is ready
for a separate approval decision; it does not authorize live capture.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from reference_data.capture import plan_capture
from reference_data.fixture_io import sha256_file as _sha256


SCHEMA_VERSION = "2i.4c-new-york-replacement-preflight"
PROVIDER = "PurpleAir"
REPLACEMENT_SENSOR_ID = "159361"
ORIGINAL_SENSOR_ID = "198733"
PRESERVED_RIO_SENSOR_ID = "175407"
PRESERVED_METRO_MANILA_SENSOR_ID = "99177"
WINDOW_START = "2026-08-08T00:00:00Z"
WINDOW_END = "2026-08-11T00:00:00Z"
FIELDS = ("pm2.5_atm", "pm10.0_atm")
HISTORY_ENDPOINT_TEMPLATE = (
    "https://api.purpleair.com/v1/sensors/{sensor_id}/history"
)
EXPECTED_ROWS = 2160
HISTORY_REQUEST_COUNT = 1
METADATA_REQUEST_COUNT = 0
HISTORY_ENDPOINT_BASE_POINTS = 2
FIELD_POINTS_PER_ROW = {"pm2.5_atm": 2, "pm10.0_atm": 2}
PRICING_VERIFIED_AT = "2026-08-11T21:25:00-07:00"
SAFETY_MARGIN_PERCENT = 10
ESTIMATED_POINTS = 8642
HARD_MAX_POINTS = 9507
ACCESS_CLASSIFICATION = "restricted_private_not_approved_for_public_redistribution"


class PurpleAirReplacementPreflightError(ValueError):
    pass


RequestExecutor = Callable[..., Any]

def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PurpleAirReplacementPreflightError(
            f"Invalid {label} {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise PurpleAirReplacementPreflightError(f"{label} must be a JSON object")
    return value


def _validate_exact_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path, "replacement preflight manifest")
    exact_values = {
        "schema_version": SCHEMA_VERSION,
        "provider": PROVIDER,
        "provider_ids": [],
        "fields": list(FIELDS),
        "average": 0,
        "history_endpoint_template": HISTORY_ENDPOINT_TEMPLATE,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "expected_frequency_seconds": 120,
        "measurement_duration_seconds": 120,
        "source_aggregation_duration_seconds": 120,
        "measurement_timestamp_semantics": "provider_received_at",
        "expected_provider_rows": EXPECTED_ROWS,
        "history_request_capacity_rows": 21600,
        "rows_per_page": 21600,
        "history_request_ceiling": HISTORY_REQUEST_COUNT,
        "metadata_request_count": METADATA_REQUEST_COUNT,
        "metadata_expected_rows": 0,
        "metadata_fields": [],
        "discovery_request_count": 0,
        "retry_count": 0,
        "paid_provider": True,
        "hard_max_points": HARD_MAX_POINTS,
        "access_classification": ACCESS_CLASSIFICATION,
        "preflight_only": True,
        "live_capture_authorized": False,
        "automatic_refresh": False,
        "scheduled_capture": False,
    }
    for field_name, expected in exact_values.items():
        if manifest.get(field_name) != expected:
            raise PurpleAirReplacementPreflightError(
                f"{field_name} must remain {expected!r}"
            )

    reference_sensors = manifest.get("reference_sensors")
    if not isinstance(reference_sensors, list) or len(reference_sensors) != 1:
        raise PurpleAirReplacementPreflightError(
            "reference_sensors must contain exactly one New York replacement"
        )
    replacement = reference_sensors[0]
    if not isinstance(replacement, dict):
        raise PurpleAirReplacementPreflightError(
            "New York replacement sensor must be an object"
        )
    if replacement.get("reference_area_code") != "new_york":
        raise PurpleAirReplacementPreflightError(
            "replacement reference_area_code must be new_york"
        )
    if replacement.get("sensor_id") != REPLACEMENT_SENSOR_ID:
        raise PurpleAirReplacementPreflightError(
            f"replacement sensor_id must remain {REPLACEMENT_SENSOR_ID}"
        )
    if replacement.get("replaces_sensor_id") != ORIGINAL_SENSOR_ID:
        raise PurpleAirReplacementPreflightError(
            f"replaces_sensor_id must remain {ORIGINAL_SENSOR_ID}"
        )

    pricing = manifest.get("pricing")
    if not isinstance(pricing, dict):
        raise PurpleAirReplacementPreflightError("pricing must be an object")
    pricing_exact = {
        "verified_at": PRICING_VERIFIED_AT,
        "history_endpoint_base_points": HISTORY_ENDPOINT_BASE_POINTS,
        "history_field_points": FIELD_POINTS_PER_ROW,
        "metadata_endpoint_base_points": None,
        "metadata_field_points": {},
        "safety_margin_percent": SAFETY_MARGIN_PERCENT,
        "safety_margin_status": "approved",
    }
    for field_name, expected in pricing_exact.items():
        if pricing.get(field_name) != expected:
            raise PurpleAirReplacementPreflightError(
                f"pricing.{field_name} must remain {expected!r}"
            )
    return manifest


def _validate_preserved_capture(
    manifest_path: Path,
    manifest: dict[str, Any],
) -> None:
    preserved = manifest.get("preserved_existing_capture")
    if not isinstance(preserved, dict):
        raise PurpleAirReplacementPreflightError(
            "preserved_existing_capture must be an object"
        )
    expected_ids = {
        "original_new_york_sensor_id": ORIGINAL_SENSOR_ID,
        "rio_sensor_id": PRESERVED_RIO_SENSOR_ID,
        "metro_manila_sensor_id": PRESERVED_METRO_MANILA_SENSOR_ID,
    }
    for field_name, expected in expected_ids.items():
        if preserved.get(field_name) != expected:
            raise PurpleAirReplacementPreflightError(
                f"preserved_existing_capture.{field_name} must remain {expected!r}"
            )
    artifact_pairs = (
        ("authorization_manifest", "authorization_manifest_sha256"),
        ("frozen_manifest", "frozen_manifest_sha256"),
        ("frozen_measurements", "frozen_measurements_sha256"),
        ("capture_report", "capture_report_sha256"),
        (
            "original_new_york_staged_response",
            "original_new_york_staged_response_sha256",
        ),
        ("rio_staged_response", "rio_staged_response_sha256"),
        ("metro_manila_staged_response", "metro_manila_staged_response_sha256"),
    )
    for path_field, checksum_field in artifact_pairs:
        relative_path = preserved.get(path_field)
        expected_checksum = preserved.get(checksum_field)
        if not isinstance(relative_path, str) or not isinstance(expected_checksum, str):
            raise PurpleAirReplacementPreflightError(
                f"preserved artifact {path_field} and {checksum_field} are required"
            )
        artifact_path = (manifest_path.parent / relative_path).resolve()
        actual_checksum = _sha256(artifact_path)
        if actual_checksum != expected_checksum and path_field in {
            "frozen_manifest",
            "frozen_measurements",
            "capture_report",
        }:
            archived_path = (
                manifest_path.parent
                / "capture_history"
                / "phase_2i4c"
                / Path(relative_path).name
            ).resolve()
            if archived_path.exists():
                actual_checksum = _sha256(archived_path)
        if actual_checksum != expected_checksum:
            raise PurpleAirReplacementPreflightError(
                f"preserved artifact checksum mismatch for {relative_path}"
            )

    original_stage = _read_json(
        (manifest_path.parent / preserved["original_new_york_staged_response"]).resolve(),
        "original New York staged response",
    )
    original_payload = original_stage.get("response_payload")
    if (
        original_stage.get("response_status_code") != 200
        or not isinstance(original_payload, dict)
        or original_payload.get("sensor_index") != int(ORIGINAL_SENSOR_ID)
        or original_payload.get("data") != []
    ):
        raise PurpleAirReplacementPreflightError(
            "original New York provenance must remain HTTP 200 with zero provider rows"
        )


def build_dry_run_report(
    manifest_path: Path,
    request_executor: RequestExecutor | None = None,
) -> dict[str, Any]:
    """Return the local replacement plan without reading credentials or networking."""
    del request_executor
    manifest = _validate_exact_manifest(manifest_path)
    _validate_preserved_capture(manifest_path, manifest)
    planned = plan_capture(manifest_path)
    blockers = list(planned["blockers"])
    if planned["expected_rows"] != EXPECTED_ROWS:
        blockers.append("expected_rows_must_be_2160")
    if planned["history_request_count"] != HISTORY_REQUEST_COUNT:
        blockers.append("history_request_count_must_be_one")
    if planned["estimated_points"] != ESTIMATED_POINTS:
        blockers.append("estimated_points_must_be_8642")
    if planned["recommended_max_points_ceiling"] != HARD_MAX_POINTS:
        blockers.append("recommended_hard_ceiling_must_be_9507")
    unique_blockers = sorted(set(blockers))
    if (
        (manifest_path.parent / "new_york_replacement_capture_report.json").exists()
        or (manifest_path.parent / "new_york_replacement_failure_report.json").exists()
    ):
        unique_blockers = sorted(
            {*unique_blockers, "replacement_capture_already_attempted"}
        )
    per_field_totals = {
        field: EXPECTED_ROWS * FIELD_POINTS_PER_ROW[field] for field in FIELDS
    }
    return {
        "dry_run": True,
        "preflight_only": True,
        "live_capture_authorized": False,
        "replacement_sensor_id": REPLACEMENT_SENSOR_ID,
        "original_sensor_id": ORIGINAL_SENSOR_ID,
        "window_start": WINDOW_START,
        "window_end_exclusive": WINDOW_END,
        "fields": list(FIELDS),
        "expected_rows": EXPECTED_ROWS,
        "request_count": HISTORY_REQUEST_COUNT,
        "metadata_request_count": METADATA_REQUEST_COUNT,
        "endpoint_base_point_total": HISTORY_ENDPOINT_BASE_POINTS,
        "pm25_field_point_total": per_field_totals["pm2.5_atm"],
        "pm10_field_point_total": per_field_totals["pm10.0_atm"],
        "estimated_total_points": ESTIMATED_POINTS,
        "safety_margin_percent": SAFETY_MARGIN_PERCENT,
        "hard_max_points": HARD_MAX_POINTS,
        "manifest_sha256": _sha256(manifest_path),
        "blockers": unique_blockers,
        "capture_ready": not unique_blockers,
        "purpleair_requests_made": 0,
        "purpleair_points_consumed": 0,
        "credentials_read": False,
        "network_requests_executed": 0,
        "preserved_existing_capture_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zero-network New York PurpleAir replacement preflight"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("Only --dry-run is implemented; live replacement capture is unavailable")
    report = build_dry_run_report(args.manifest.resolve())
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
