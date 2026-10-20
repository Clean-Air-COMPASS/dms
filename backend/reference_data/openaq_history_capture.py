"""Strictly bounded OpenAQ history capture for the approved Phase 2I.4A sensors.

The dry-run path reads local files only. The execution path permits one endpoint
shape, never retries, and enforces both per-sensor and global request ceilings.
It has no PurpleAir or direct AirGradient transport implementation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Callable


CAPTURE_SCHEMA_VERSION = "2i.4a"
FIXTURE_SCHEMA_VERSION = "2i.1"
OPENAQ_MEASUREMENTS_ENDPOINT_TEMPLATE = (
    "https://api.openaq.org/v3/sensors/{sensor_id}/measurements"
)
WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-08T00:00:00Z"
PAGE_SIZE = 1000
MAX_PAGES_PER_SENSOR = 11
ABSOLUTE_REQUEST_CEILING = 143
APPROVED_SELECTION_SHA256 = (
    "28c61c3d66c1f2a8739f56ca5812313d46c183e6b88a31482dac2c1a1e7859a2"
)
APPROVED_SENSOR_IDS = (
    1758,
    3951,
    3950,
    3952,
    1099,
    1098,
    6819305,
    4475454,
    6459542,
    4475455,
    11268993,
    4475449,
    13191003,
)
KNOWN_AGGREGATION_CODES = {
    60: "1m",
    120: "2m",
    3600: "1h",
    86400: "24h",
}


class OpenAQHistoryCaptureError(RuntimeError):
    pass


RequestExecutor = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


def _sha256(path: Path) -> str:
    """Hash standalone capture text with checkout line endings normalized."""

    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def request_ceiling_blocker(
    global_request_count: int,
    sensor_request_count: int,
) -> str | None:
    """Return the denial code that prevents the next provider request, if any."""
    if global_request_count >= ABSOLUTE_REQUEST_CEILING:
        return "global_request_ceiling_reached"
    if sensor_request_count >= MAX_PAGES_PER_SENSOR:
        return "per_sensor_request_ceiling_reached"
    return None

def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpenAQHistoryCaptureError(f"Invalid {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OpenAQHistoryCaptureError(f"{label} must be a JSON object")
    return value


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise OpenAQHistoryCaptureError(f"{label} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OpenAQHistoryCaptureError(f"{label} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise OpenAQHistoryCaptureError(f"{label} must be an explicit UTC timestamp")
    return parsed.astimezone(timezone.utc)


def _flatten_selection(selection: dict[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    areas = selection.get("reference_areas")
    if not isinstance(areas, list):
        raise OpenAQHistoryCaptureError("selection reference_areas must be a list")
    for area in areas:
        if not isinstance(area, dict):
            raise OpenAQHistoryCaptureError("selection reference area must be an object")
        for location in area.get("selected_locations") or []:
            if not isinstance(location, dict):
                raise OpenAQHistoryCaptureError("selected location must be an object")
            for sensor in location.get("selected_sensors") or []:
                if not isinstance(sensor, dict):
                    raise OpenAQHistoryCaptureError("selected sensor must be an object")
                selected.append(
                    {
                        "reference_area_code": area.get("reference_area_code"),
                        "reference_area_name": area.get("reference_area_name"),
                        "timezone_reference": area.get("timezone_reference"),
                        "coverage": area.get("coverage"),
                        "location": location,
                        "sensor": sensor,
                    }
                )
    ids = tuple(int(entry["sensor"].get("openaq_sensor_id")) for entry in selected)
    if ids != APPROVED_SENSOR_IDS:
        raise OpenAQHistoryCaptureError(
            f"selected sensor IDs must remain the approved ordered set {APPROVED_SENSOR_IDS}"
        )
    return selected


def _validate_plan(plan_path: Path) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    plan = _read_json(plan_path, "capture plan")
    exact_fields = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "provider": "OpenAQ",
        "endpoint_template": OPENAQ_MEASUREMENTS_ENDPOINT_TEMPLATE,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "page_size": PAGE_SIZE,
        "max_pages_per_sensor": MAX_PAGES_PER_SENSOR,
        "absolute_request_ceiling": ABSOLUTE_REQUEST_CEILING,
        "retry_count": 0,
        "selection_manifest_sha256": APPROVED_SELECTION_SHA256,
    }
    for name, expected in exact_fields.items():
        if plan.get(name) != expected:
            raise OpenAQHistoryCaptureError(f"{name} must remain {expected!r}")
    selection_relative = plan.get("selection_manifest")
    if not isinstance(selection_relative, str):
        raise OpenAQHistoryCaptureError("selection_manifest must be a local path")
    selection_path = (plan_path.parent / selection_relative).resolve()
    if _sha256(selection_path) != APPROVED_SELECTION_SHA256:
        raise OpenAQHistoryCaptureError("approved selection manifest checksum mismatch")
    selection = _read_json(selection_path, "selection manifest")
    if selection.get("measurement_capture_performed") is not False:
        raise OpenAQHistoryCaptureError("selection manifest must remain pre-capture")
    proposed = selection.get("proposed_capture_window") or {}
    if proposed.get("window_start") != WINDOW_START or proposed.get("window_end") != WINDOW_END:
        raise OpenAQHistoryCaptureError("selection capture window does not match Phase 2I.4A")
    selected = _flatten_selection(selection)
    if len(selected) * MAX_PAGES_PER_SENSOR != ABSOLUTE_REQUEST_CEILING:
        raise OpenAQHistoryCaptureError("approved sensor/page ceilings no longer total 143")
    return plan, selection_path, selected


def build_dry_run_report(
    plan_path: Path,
    request_executor: RequestExecutor | None = None,
) -> dict[str, Any]:
    """Build the mandatory local-only request plan without reading credentials."""
    # Accepted only so tests can inject a fail-fast executor and prove it is untouched.
    del request_executor
    plan, selection_path, selected = _validate_plan(plan_path)
    requests = []
    for entry in selected:
        location = entry["location"]
        sensor = entry["sensor"]
        sensor_id = int(sensor["openaq_sensor_id"])
        requests.append(
            {
                "reference_area_code": entry["reference_area_code"],
                "reference_area_name": entry["reference_area_name"],
                "location_name": location.get("location_name"),
                "openaq_location_id": location.get("openaq_location_id"),
                "openaq_sensor_id": sensor_id,
                "parameter_code": sensor.get("parameter_code"),
                "provider_parameter_name": sensor.get("openaq_parameter_name"),
                "provider_unit": sensor.get("provider_unit"),
                "endpoint": OPENAQ_MEASUREMENTS_ENDPOINT_TEMPLATE.format(sensor_id=sensor_id),
                "window_start": WINDOW_START,
                "window_end_exclusive": WINDOW_END,
                "page_size": PAGE_SIZE,
                "maximum_pages": MAX_PAGES_PER_SENSOR,
                "per_sensor_request_ceiling": MAX_PAGES_PER_SENSOR,
                "output_fixture_path": str((plan_path.parent / plan["measurements_output"]).resolve()),
            }
        )
    return {
        "dry_run": True,
        "network_requests_executed": 0,
        "credentials_read": False,
        "provider": "OpenAQ",
        "selection_manifest": str(selection_path),
        "selection_manifest_sha256": APPROVED_SELECTION_SHA256,
        "source_discovery_commit": plan["source_discovery_commit"],
        "absolute_utc_window": {"start_inclusive": WINDOW_START, "end_exclusive": WINDOW_END},
        "selected_sensor_count": len(requests),
        "requests": requests,
        "page_size": PAGE_SIZE,
        "maximum_pages_per_sensor": MAX_PAGES_PER_SENSOR,
        "maximum_requests_per_sensor": MAX_PAGES_PER_SENSOR,
        "openaq_absolute_request_ceiling": ABSOLUTE_REQUEST_CEILING,
        "retry_count": 0,
        "direct_provider_request_counts": {"PurpleAir": 0, "AirGradient": 0},
        "paid_provider_status": {
            "PurpleAir": "disabled_and_not_used",
            "expected_point_spend": 0,
        },
        "output_paths": {
            "manifest": str((plan_path.parent / plan["manifest_output"]).resolve()),
            "measurements": str((plan_path.parent / plan["measurements_output"]).resolve()),
            "capture_report": str((plan_path.parent / plan["capture_report_output"]).resolve()),
        },
    }


def _single_openaq_get(
    endpoint: str,
    query: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    import httpx

    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        response = client.get(endpoint, params=query, headers=headers)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise OpenAQHistoryCaptureError("OpenAQ response must be a JSON object")
    return payload


def _interval_seconds(value: Any) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().upper()
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", text)
    if match:
        seconds = int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60
        seconds += float(match.group(3) or 0)
        return int(seconds) if seconds > 0 and seconds.is_integer() else None
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})", text)
    if match:
        seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
        return seconds if seconds > 0 else None
    return None


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _period_utc(period: dict[str, Any], field: str) -> datetime:
    value = period.get(field)
    if isinstance(value, dict):
        value = value.get("utc")
    return _parse_utc(value, f"period.{field}.utc")


def _normalize_measurement(
    raw: dict[str, Any],
    entry: dict[str, Any],
    page: int,
    result_index: int,
) -> dict[str, Any] | None:
    sensor = entry["sensor"]
    sensor_id = int(sensor["openaq_sensor_id"])
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise OpenAQHistoryCaptureError(f"sensor {sensor_id} returned a non-finite numeric value")
    parameter = raw.get("parameter")
    if not isinstance(parameter, dict):
        raise OpenAQHistoryCaptureError(f"sensor {sensor_id} measurement is missing parameter metadata")
    if parameter.get("name") != sensor.get("openaq_parameter_name"):
        raise OpenAQHistoryCaptureError(f"sensor {sensor_id} provider parameter identity changed")
    if parameter.get("units") != sensor.get("provider_unit"):
        raise OpenAQHistoryCaptureError(f"sensor {sensor_id} provider unit changed")
    period = raw.get("period")
    if not isinstance(period, dict):
        raise OpenAQHistoryCaptureError(f"sensor {sensor_id} measurement is missing period metadata")
    period_start = _period_utc(period, "datetimeFrom")
    period_end = _period_utc(period, "datetimeTo")
    if period_end <= period_start:
        raise OpenAQHistoryCaptureError(f"sensor {sensor_id} returned a non-positive period")
    window_start = _parse_utc(WINDOW_START, "window_start")
    window_end = _parse_utc(WINDOW_END, "window_end")
    if period_end < window_start or period_end >= window_end:
        return None
    explicit_interval = _interval_seconds(period.get("interval"))
    duration_seconds = int((period_end - period_start).total_seconds())
    flag_info = raw.get("flagInfo") if isinstance(raw.get("flagInfo"), dict) else None
    has_flags = bool(flag_info and flag_info.get("hasFlags"))
    provider_ref = f"openaq:{sensor_id}:page-{page}:result-{result_index}"
    return {
        "sensor_ref": f"openaq-sensor-{sensor_id}",
        "observed_at": _utc_text(period_end),
        "value": value,
        "is_valid": not has_flags,
        "qc_flags": {
            "provider_flagged": has_flags,
            "transport_provider": "OpenAQ",
            "value_and_unit_preserved_without_conversion": True,
        },
        "qc_version": "openaq-provider-flags-phase-2i.4a",
        "provider_observation_ref": provider_ref,
        "source_page": page,
        "source_result_index": result_index,
        "provider_parameter": parameter,
        "provider_period": period,
        "provider_flag_info": flag_info,
        "provider_coordinates": raw.get("coordinates") if isinstance(raw.get("coordinates"), dict) else None,
        "provider_summary": raw.get("summary") if isinstance(raw.get("summary"), dict) else None,
        "provider_coverage": raw.get("coverage") if isinstance(raw.get("coverage"), dict) else None,
        "_explicit_interval_seconds": explicit_interval,
        "_duration_seconds": duration_seconds,
    }


def _qualify_temporal_metadata(rows: list[dict[str, Any]]) -> dict[str, Any]:
    intervals = sorted({row["_explicit_interval_seconds"] for row in rows if row["_explicit_interval_seconds"]})
    durations = sorted({row["_duration_seconds"] for row in rows})
    missing_intervals = sum(row["_explicit_interval_seconds"] is None for row in rows)
    observed = sorted(_parse_utc(row["observed_at"], "observed_at") for row in rows)
    observed_gaps = sorted({int((later - earlier).total_seconds()) for earlier, later in zip(observed, observed[1:])})
    documented = len(intervals) == 1 and len(durations) == 1 and missing_intervals == 0
    interval = intervals[0] if documented else None
    return {
        "status": "provider_documented" if documented else "unknown_or_inconsistent",
        "timestamp_semantics": "interval_end" if rows else "unknown",
        "provider_interval_seconds": interval,
        "provider_duration_seconds": durations[0] if documented else None,
        "provider_interval_values_seconds": intervals,
        "provider_duration_values_seconds": durations,
        "records_missing_explicit_interval": missing_intervals,
        "observed_timestamp_gap_values_seconds": observed_gaps,
        "cadence_status": (
            "regular_at_documented_interval"
            if documented and set(observed_gaps).issubset({interval})
            else "contains_gaps_or_irregular_timestamps"
        ) if rows else "no_observations",
    }


def _device_and_sensor_manifests(
    selected: list[dict[str, Any]],
    rows_by_sensor: dict[int, list[dict[str, Any]]],
    sensor_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    devices: dict[int, dict[str, Any]] = {}
    sensors: list[dict[str, Any]] = []
    result_by_id = {result["openaq_sensor_id"]: result for result in sensor_results}
    for entry in selected:
        area_code = entry["reference_area_code"]
        location = entry["location"]
        sensor = entry["sensor"]
        location_id = int(location["openaq_location_id"])
        sensor_id = int(sensor["openaq_sensor_id"])
        devices.setdefault(
            location_id,
            {
                "fixture_ref": f"openaq-location-{location_id}",
                "external_id": f"openaq-location-{location_id}",
                "name": location["location_name"],
                "friendly_name": f"{location['location_name']} ({entry['reference_area_name']})",
                "latitude": location["coordinates"]["latitude"],
                "longitude": location["coordinates"]["longitude"],
                "timezone": location["timezone"],
                "reference_area_ref": area_code,
                "provider_name": (location.get("provider") or {}).get("name"),
                "owner_name": (location.get("owner") or {}).get("name"),
                "hardware_provider": location.get("hardware_provider"),
                "source_metadata": {
                    "openaq_location_id": location_id,
                    "locality": location.get("locality"),
                    "is_mobile": location.get("is_mobile"),
                    "is_reference_monitor": location.get("is_reference_monitor"),
                    "instruments": location.get("instruments") or [],
                    "licenses": location.get("licenses") or [],
                    "provider": location.get("provider"),
                    "owner": location.get("owner"),
                    "transport_provider": "OpenAQ",
                },
            },
        )
        rows = rows_by_sensor[sensor_id]
        temporal = _qualify_temporal_metadata(rows)
        documented_seconds = temporal["provider_interval_seconds"]
        sensors.append(
            {
                "fixture_ref": f"openaq-sensor-{sensor_id}",
                "device_ref": f"openaq-location-{location_id}",
                "external_sensor_id": str(sensor_id),
                "parameter_code": sensor["parameter_code"],
                "unit_code": sensor["unit_code"],
                "aggregation_period_code": KNOWN_AGGREGATION_CODES.get(documented_seconds),
                "expected_frequency_seconds": documented_seconds,
                "measurement_duration_seconds": temporal["provider_duration_seconds"],
                "source_aggregation_duration_seconds": temporal["provider_duration_seconds"],
                "measurement_timestamp_semantics": temporal["timestamp_semantics"],
                "measurement_metadata_status": temporal["status"],
                "measurement_metadata_managed_by": "reference_fixture_loader",
                "provider_parameter_name": sensor["openaq_parameter_name"],
                "provider_unit": sensor["provider_unit"],
                "hardware_provider": sensor.get("hardware_provider"),
                "temporal_qualification": temporal,
                "capture_statistics": result_by_id[sensor_id],
            }
        )
    return list(devices.values()), sensors


def _write_fixture(
    plan_path: Path,
    plan: dict[str, Any],
    selection_path: Path,
    selected: list[dict[str, Any]],
    rows_by_sensor: dict[int, list[dict[str, Any]]],
    sensor_results: list[dict[str, Any]],
    request_count: int,
    captured_at: datetime,
) -> dict[str, Any]:
    devices, sensors = _device_and_sensor_manifests(
        selected, rows_by_sensor, sensor_results
    )
    all_rows = [row for sensor_id in APPROVED_SENSOR_IDS for row in rows_by_sensor[sensor_id]]
    all_rows.sort(key=lambda row: (row["sensor_ref"], row["observed_at"], row["provider_observation_ref"]))
    for row in all_rows:
        row.pop("_explicit_interval_seconds")
        row.pop("_duration_seconds")
        for optional in (
            "provider_flag_info", "provider_coordinates", "provider_summary", "provider_coverage"
        ):
            if row.get(optional) is None:
                row.pop(optional, None)
    measurements_path = (plan_path.parent / plan["measurements_output"]).resolve()
    measurements_path.parent.mkdir(parents=True, exist_ok=True)
    measurement_text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in all_rows
    )
    measurements_path.write_text(measurement_text, encoding="utf-8", newline="\n")
    measurement_sha = _sha256(measurements_path)
    selection = _read_json(selection_path, "selection manifest")
    reference_areas = [
        {
            "fixture_ref": area["reference_area_code"],
            "name": area["reference_area_name"],
            "description": "Approved Phase 2I.4A OpenAQ historical reference area.",
            "timezone": area["timezone_reference"],
        }
        for area in selection["reference_areas"]
    ]
    manifest = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "dataset_id": "openaq_phase_2i4a_2026-08-01_2026-08-08",
        "provider": "OpenAQ",
        "provider_profile": "openaq_v3_historical_measurements",
        "access_classification": "public_frozen_reference_data",
        "origin": {
            "origin_kind": "provider_capture",
            "captured_at": _utc_text(captured_at),
            "description": "Bounded OpenAQ v3 history capture for the Phase 2I.3 approved sensors.",
        },
        "reference_area": {
            "name": "Phase 2I.4A approved reference areas",
            "description": "New York, Rio de Janeiro, and Metro Manila selections.",
            "timezone": "UTC",
        },
        "reference_areas": reference_areas,
        "license": {
            "status": "public_transport_with_origin_terms_preserved_per_device",
            "attribution": "OpenAQ and the origin providers identified in each device's source metadata",
            "redistribution_approved": False,
        },
        "provider_chain": [
            {"provider": "AirNow", "role": "origin"},
            {"provider": "Rio City Hall", "role": "origin"},
            {"provider": "AirGradient", "role": "hardware"},
            {"provider": "OpenAQ", "role": "transport"},
            {"provider": "CompassAQ frozen fixture", "role": "fixture"},
        ],
        "provenance": {
            "created_by": "CompassAQ Phase 2I.4A bounded capture",
            "methodology": "Exact allowlisted sensor history; preserved provider values, units, flags, periods, and provenance; no gas conversion.",
            "source_reference": "selected_reference_manifest.json",
        },
        "capture": {
            "selection_manifest_sha256": APPROVED_SELECTION_SHA256,
            "source_discovery_commit": plan["source_discovery_commit"],
            "endpoint_template": OPENAQ_MEASUREMENTS_ENDPOINT_TEMPLATE,
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "page_size": PAGE_SIZE,
            "max_pages_per_sensor": MAX_PAGES_PER_SENSOR,
            "absolute_request_ceiling": ABSOLUTE_REQUEST_CEILING,
            "retry_count": 0,
            "request_count": request_count,
            "captured_at": _utc_text(captured_at),
            "sensor_results": sensor_results,
        },
        "coverage_matrix": selection.get("coverage_matrix"),
        "coverage_gaps": {
            area["reference_area_code"]: area.get("gaps") or {}
            for area in selection["reference_areas"]
        },
        "known_limitations": [
            "OpenAQ period metadata describes a one-hour reporting interval, but it does not independently establish every origin provider's upstream instrument averaging method.",
            "OpenAQ sensor 1099 returned no observations in the approved window; its native temporal metadata therefore remains unknown.",
            "Observed timestamp gaps are preserved and reported separately from provider-documented interval metadata.",
            "Origin license metadata varies by location; an empty origin license list is preserved rather than replaced with an inferred license.",
            "Metro Manila has only the approved PM2.5 stream; its PM10, O3, NO2, SO2, and CO gaps remain explicit.",
        ],
        "devices": devices,
        "sensors": sensors,
        "measurements_file": measurements_path.name,
        "measurements_sha256": measurement_sha,
    }
    manifest_path = (plan_path.parent / plan["manifest_output"]).resolve()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report = {
        "provider": "OpenAQ",
        "network_requests_executed": request_count,
        "absolute_request_ceiling": ABSOLUTE_REQUEST_CEILING,
        "retry_count": 0,
        "direct_provider_request_counts": {"PurpleAir": 0, "AirGradient": 0},
        "purpleair_point_spend": 0,
        "window_start": WINDOW_START,
        "window_end_exclusive": WINDOW_END,
        "measurement_count": len(all_rows),
        "sensor_results": sensor_results,
        "manifest": str(manifest_path),
        "measurements": str(measurements_path),
        "measurements_sha256": measurement_sha,
    }
    report_path = (plan_path.parent / plan["capture_report_output"]).resolve()
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def execute_bounded_capture(
    plan_path: Path,
    api_key: str,
    request_executor: RequestExecutor | None = None,
) -> dict[str, Any]:
    plan, selection_path, selected = _validate_plan(plan_path)
    frozen_outputs = [
        (plan_path.parent / plan[output_name]).resolve()
        for output_name in ("manifest_output", "measurements_output", "capture_report_output")
    ]
    existing_outputs = [str(path) for path in frozen_outputs if path.exists()]
    if existing_outputs:
        raise OpenAQHistoryCaptureError(
            "frozen capture output already exists; automatic refresh and overwrite are prohibited: "
            + ", ".join(existing_outputs)
        )
    if not api_key.strip():
        raise OpenAQHistoryCaptureError("OpenAQ API key is required only for execution")
    if request_executor is None and os.getenv("COMPASSAQ_ENV", "").strip().lower() == "test":
        raise OpenAQHistoryCaptureError("real OpenAQ transport is blocked in the test environment")
    executor = request_executor or _single_openaq_get
    rows_by_sensor: dict[int, list[dict[str, Any]]] = {
        sensor_id: [] for sensor_id in APPROVED_SENSOR_IDS
    }
    sensor_results: list[dict[str, Any]] = []
    request_count = 0
    captured_at = datetime.now(timezone.utc)
    for entry in selected:
        sensor = entry["sensor"]
        sensor_id = int(sensor["openaq_sensor_id"])
        endpoint = OPENAQ_MEASUREMENTS_ENDPOINT_TEMPLATE.format(sensor_id=sensor_id)
        sensor_request_count = 0
        excluded_end_boundary = 0
        completion_status = "complete_natural_pagination"
        failure_reason = None
        for page in range(1, MAX_PAGES_PER_SENSOR + 1):
            request_blocker = request_ceiling_blocker(
                request_count, sensor_request_count
            )
            if request_blocker is not None:
                if request_blocker == "global_request_ceiling_reached":
                    completion_status = "stopped_at_global_request_ceiling"
                else:
                    completion_status = "stopped_at_per_sensor_request_ceiling"
                failure_reason = request_blocker
                break
            query = {
                "datetime_from": WINDOW_START,
                "datetime_to": WINDOW_END,
                "limit": PAGE_SIZE,
                "page": page,
            }
            try:
                request_count += 1
                sensor_request_count += 1
                payload = executor(endpoint, query, {"X-API-Key": api_key})
                if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                    raise OpenAQHistoryCaptureError("response is missing a results array")
                results = payload["results"]
                for result_index, raw in enumerate(results):
                    if not isinstance(raw, dict):
                        raise OpenAQHistoryCaptureError("measurement result must be an object")
                    normalized = _normalize_measurement(raw, entry, page, result_index)
                    if normalized is None:
                        excluded_end_boundary += 1
                    else:
                        rows_by_sensor[sensor_id].append(normalized)
                meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
                found = meta.get("found")
                natural_end = len(results) < PAGE_SIZE
                if isinstance(found, int) and page * PAGE_SIZE >= found:
                    natural_end = True
                if natural_end:
                    break
                if page == MAX_PAGES_PER_SENSOR:
                    completion_status = "stopped_at_per_sensor_request_ceiling"
                    failure_reason = "per_sensor_request_ceiling_reached_before_natural_completion"
            except Exception as exc:
                completion_status = "failed_without_retry"
                failure_reason = f"{type(exc).__name__}: {exc}"
                break
        rows = rows_by_sensor[sensor_id]
        duplicate_count = len(rows) - len({row["observed_at"] for row in rows})
        sensor_results.append(
            {
                "openaq_sensor_id": sensor_id,
                "reference_area_code": entry["reference_area_code"],
                "parameter_code": sensor["parameter_code"],
                "provider_unit": sensor["provider_unit"],
                "requests_executed": sensor_request_count,
                "rows_preserved": len(rows),
                "exact_timestamp_duplicate_count": duplicate_count,
                "end_boundary_rows_excluded": excluded_end_boundary,
                "completion_status": completion_status,
                "failure_reason": failure_reason,
            }
        )
    return _write_fixture(
        plan_path,
        plan,
        selection_path,
        selected,
        rows_by_sensor,
        sensor_results,
        request_count,
        captured_at,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded OpenAQ Phase 2I.4A history capture")
    parser.add_argument("--plan", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-bounded-openaq-history", action="store_true")
    args = parser.parse_args()
    plan_path = args.plan.resolve()
    if args.dry_run:
        report = build_dry_run_report(plan_path)
    else:
        if not args.confirm_bounded_openaq_history:
            parser.error("--execute requires --confirm-bounded-openaq-history")
        report = execute_bounded_capture(
            plan_path,
            api_key=os.getenv("OPENAQ_API_KEY", ""),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
