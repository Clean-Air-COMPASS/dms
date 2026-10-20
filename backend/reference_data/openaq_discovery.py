"""Bounded OpenAQ location discovery for frozen reference-data selection.

This module permits only the OpenAQ v3 locations endpoint. It cannot call
measurement history, PurpleAir, or AirGradient, and it never retries a failed
request. The dry run does not read credentials or create an HTTP client.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable


OPENAQ_LOCATIONS_ENDPOINT = "https://api.openaq.org/v3/locations"
DISCOVERY_SCHEMA_VERSION = "2i.3"
TARGET_PARAMETER_CODES = ("pm25", "pm10", "o3", "no2", "so2", "co")
RECENT_DATA_MAX_AGE_DAYS = 30
APPROVED_REFERENCE_AREAS = {
    "new_york": {
        "coordinates": "40.7128,-74.0060",
        "radius_m": 25000,
        "timezone_reference": "America/New_York",
    },
    "rio_de_janeiro": {
        "coordinates": "-22.9068,-43.1729",
        "radius_m": 25000,
        "timezone_reference": "America/Sao_Paulo",
    },
    "metro_manila": {
        "coordinates": "14.5995,120.9842",
        "radius_m": 25000,
        "timezone_reference": "Asia/Manila",
    },
}


class OpenAQDiscoveryError(RuntimeError):
    pass


RequestExecutor = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]

UNIT_CODE_BY_PROVIDER_UNIT = {
    "µg/m³": "ug_m3",
    "μg/m³": "ug_m3",
    "ug/m3": "ug_m3",
    "ug/m^3": "ug_m3",
    "ug_m3": "ug_m3",
    "mg/m³": "mg_m3",
    "mg/m3": "mg_m3",
    "mg/m^3": "mg_m3",
    "mg_m3": "mg_m3",
    "ppm": "ppm",
    "ppb": "ppb",
}
COMPATIBLE_UNIT_CODES = {
    "pm25": {"ug_m3", "mg_m3"},
    "pm10": {"ug_m3", "mg_m3"},
    "o3": {"ppm", "ppb", "ug_m3", "mg_m3"},
    "no2": {"ppm", "ppb", "ug_m3", "mg_m3"},
    "so2": {"ppm", "ppb", "ug_m3", "mg_m3"},
    "co": {"ppm", "ppb", "ug_m3", "mg_m3"},
}
PREFERRED_UNIT_CODES = {
    "pm25": ("ug_m3", "mg_m3"),
    "pm10": ("ug_m3", "mg_m3"),
    "o3": ("ppm", "ppb", "ug_m3", "mg_m3"),
    "co": ("ppm", "ppb", "ug_m3", "mg_m3"),
    "no2": ("ppb", "ppm", "ug_m3", "mg_m3"),
    "so2": ("ppb", "ppm", "ug_m3", "mg_m3"),
}


def _read_plan(plan_path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpenAQDiscoveryError(f"Invalid discovery plan {plan_path}: {exc}") from exc
    if not isinstance(plan, dict):
        raise OpenAQDiscoveryError("Discovery plan must be a JSON object")
    return plan


def validate_discovery_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the exact three approved, single-page OpenAQ requests."""
    if plan.get("schema_version") != DISCOVERY_SCHEMA_VERSION:
        raise OpenAQDiscoveryError(
            f"schema_version must be {DISCOVERY_SCHEMA_VERSION}"
        )
    if plan.get("provider") != "OpenAQ":
        raise OpenAQDiscoveryError("provider must be OpenAQ")
    if plan.get("endpoint") != OPENAQ_LOCATIONS_ENDPOINT:
        raise OpenAQDiscoveryError(
            f"Only {OPENAQ_LOCATIONS_ENDPOINT} is allowed for discovery"
        )
    if plan.get("absolute_request_ceiling") != 3:
        raise OpenAQDiscoveryError("absolute_request_ceiling must be exactly 3")
    if plan.get("max_pages_per_area") != 1:
        raise OpenAQDiscoveryError("max_pages_per_area must be exactly 1")
    if plan.get("retry_count") != 0:
        raise OpenAQDiscoveryError("retry_count must be exactly 0")
    if tuple(plan.get("target_parameter_codes") or ()) != TARGET_PARAMETER_CODES:
        raise OpenAQDiscoveryError("target_parameter_codes do not match Phase 2I.3")

    areas = plan.get("reference_areas")
    if not isinstance(areas, list) or len(areas) != len(APPROVED_REFERENCE_AREAS):
        raise OpenAQDiscoveryError("Exactly three reference areas are required")

    validated_areas: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for area in areas:
        if not isinstance(area, dict):
            raise OpenAQDiscoveryError("Each reference area must be an object")
        area_code = area.get("reference_area_code")
        approved = APPROVED_REFERENCE_AREAS.get(str(area_code))
        if approved is None or area_code in seen_codes:
            raise OpenAQDiscoveryError(f"Unexpected or duplicate area: {area_code}")
        seen_codes.add(area_code)
        for field_name, approved_value in approved.items():
            if area.get(field_name) != approved_value:
                raise OpenAQDiscoveryError(
                    f"{area_code}.{field_name} must remain {approved_value!r}"
                )

        query = area.get("query")
        expected_query = {
            "coordinates": approved["coordinates"],
            "radius": approved["radius_m"],
            "limit": 1000,
            "page": 1,
            "order_by": "id",
            "sort_order": "asc",
        }
        if query != expected_query:
            raise OpenAQDiscoveryError(
                f"{area_code}.query must be the approved deterministic query"
            )
        destination = area.get("staging_destination")
        if not isinstance(destination, str) or not destination.startswith("staging/"):
            raise OpenAQDiscoveryError(
                f"{area_code}.staging_destination must be below staging/"
            )
        validated_areas.append(area)

    if seen_codes != set(APPROVED_REFERENCE_AREAS):
        raise OpenAQDiscoveryError("All approved reference areas are required")
    return validated_areas


def build_dry_run_report(plan_path: Path) -> dict[str, Any]:
    """Return the complete request plan without reading credentials or networking."""
    plan = _read_plan(plan_path)
    areas = validate_discovery_plan(plan)
    requests = []
    for area in areas:
        requests.append(
            {
                "reference_area_code": area["reference_area_code"],
                "endpoint": plan["endpoint"],
                "coordinates": area["coordinates"],
                "radius_m": area["radius_m"],
                "parameters_filter": None,
                "parameter_selection": "client-side exact target-code compatibility",
                "page_size": area["query"]["limit"],
                "maximum_pages": plan["max_pages_per_area"],
                "query": area["query"],
                "authentication_required": True,
                "authentication_header": "X-API-Key",
                "staging_destination": str(
                    (plan_path.parent / area["staging_destination"]).resolve()
                ),
            }
        )
    return {
        "dry_run": True,
        "network_requests_executed": 0,
        "provider": "OpenAQ",
        "expected_request_count": len(requests),
        "absolute_request_ceiling": plan["absolute_request_ceiling"],
        "retry_count": plan["retry_count"],
        "requests": requests,
    }


def _single_openaq_get(
    endpoint: str,
    query: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    """Issue exactly one request; redirects and retries are intentionally disabled."""
    import httpx

    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        response = client.get(endpoint, params=query, headers=headers)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise OpenAQDiscoveryError("OpenAQ response must be a JSON object")
    return payload


def _minimal_location(location: dict[str, Any]) -> dict[str, Any]:
    sensors = []
    for sensor in location.get("sensors") or []:
        if not isinstance(sensor, dict):
            continue
        parameter = sensor.get("parameter") or {}
        sensors.append(
            {
                "id": sensor.get("id"),
                "name": sensor.get("name"),
                "parameter": {
                    "id": parameter.get("id") if isinstance(parameter, dict) else None,
                    "name": parameter.get("name") if isinstance(parameter, dict) else None,
                    "units": parameter.get("units") if isinstance(parameter, dict) else None,
                    "displayName": parameter.get("displayName") if isinstance(parameter, dict) else None,
                },
            }
        )
    sensors.sort(key=lambda sensor: (str(sensor.get("id") or ""), str(sensor.get("name") or "")))
    return {
        "id": location.get("id"),
        "name": location.get("name"),
        "locality": location.get("locality"),
        "timezone": location.get("timezone"),
        "country": location.get("country"),
        "owner": location.get("owner"),
        "provider": location.get("provider"),
        "isMobile": location.get("isMobile"),
        "isMonitor": location.get("isMonitor"),
        "instruments": location.get("instruments") or [],
        "sensors": sensors,
        "coordinates": location.get("coordinates"),
        "licenses": location.get("licenses") or [],
        "distance": location.get("distance"),
        "datetimeFirst": location.get("datetimeFirst"),
        "datetimeLast": location.get("datetimeLast"),
    }


def _write_staging_payload(
    plan_path: Path,
    area: dict[str, Any],
    endpoint: str,
    payload: dict[str, Any],
) -> Path:
    results = payload.get("results")
    if not isinstance(results, list):
        raise OpenAQDiscoveryError("OpenAQ response is missing a results array")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    locations = [
        _minimal_location(location)
        for location in results
        if isinstance(location, dict)
    ]
    locations.sort(key=lambda location: int(location["id"]))
    found = meta.get("found")
    staging_payload = {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "provider": "OpenAQ",
        "reference_area_code": area["reference_area_code"],
        "reference_area_name": area["reference_area_name"],
        "timezone_reference": area["timezone_reference"],
        "request": {
            "endpoint": endpoint,
            "query": area["query"],
            "executed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "response_meta": {
            "page": meta.get("page"),
            "limit": meta.get("limit"),
            "found": found,
            "returned": len(locations),
            "result_truncated_by_request_ceiling": (
                isinstance(found, int) and found > len(locations)
            ),
        },
        "locations": locations,
    }
    destination = (plan_path.parent / area["staging_destination"]).resolve()
    allowed_root = (plan_path.parent / "staging").resolve()
    if allowed_root not in destination.parents:
        raise OpenAQDiscoveryError("Staging destination escaped the approved root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(staging_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def execute_bounded_discovery(
    plan_path: Path,
    *,
    api_key: str,
    request_executor: RequestExecutor | None = None,
) -> dict[str, Any]:
    """Execute exactly one allowlisted locations request for each approved area."""
    if not api_key.strip():
        raise OpenAQDiscoveryError("OPENAQ_API_KEY is required for discovery")
    if (
        os.getenv("COMPASSAQ_ENV", "").strip().lower() == "test"
        and request_executor is None
    ):
        raise OpenAQDiscoveryError(
            "External OpenAQ HTTP is blocked in the test environment"
        )
    plan = _read_plan(plan_path)
    areas = validate_discovery_plan(plan)
    executor = request_executor or _single_openaq_get
    request_count = 0
    destinations = []
    for area in areas:
        if request_count >= plan["absolute_request_ceiling"]:
            raise OpenAQDiscoveryError("OpenAQ discovery request ceiling reached")
        request_count += 1
        payload = executor(
            plan["endpoint"],
            area["query"],
            {"X-API-Key": api_key},
        )
        destinations.append(
            str(_write_staging_payload(plan_path, area, plan["endpoint"], payload))
        )
    return {
        "provider": "OpenAQ",
        "network_requests_executed": request_count,
        "absolute_request_ceiling": plan["absolute_request_ceiling"],
        "retry_count": 0,
        "staging_destinations": destinations,
    }


def _entity_name(entity: Any) -> str | None:
    if not isinstance(entity, dict):
        return None
    name = entity.get("name")
    return str(name).strip() if name is not None and str(name).strip() else None


def _airgradient_evidence(location: dict[str, Any]) -> list[str]:
    evidence = []
    for instrument in location.get("instruments") or []:
        name = _entity_name(instrument)
        if name and "airgradient" in name.lower():
            evidence.append(f"instrument:{name}")
    for field_name in ("owner", "provider"):
        name = _entity_name(location.get(field_name))
        if name and "airgradient" in name.lower():
            evidence.append(f"{field_name}:{name}")
    return sorted(set(evidence))


def evaluate_sensor_compatibility(sensor: dict[str, Any]) -> dict[str, Any]:
    """Preserve provider identity and reject ambiguous parameters or units."""
    parameter = sensor.get("parameter") if isinstance(sensor, dict) else None
    parameter = parameter if isinstance(parameter, dict) else {}
    provider_parameter_name = str(parameter.get("name") or "").strip()
    parameter_code = provider_parameter_name.lower()
    provider_unit = str(parameter.get("units") or "").strip()
    unit_code = UNIT_CODE_BY_PROVIDER_UNIT.get(provider_unit)
    if parameter_code not in TARGET_PARAMETER_CODES:
        compatibility_status = "unsuitable"
        exclusion_reason = "unsupported_parameter"
        mapped_parameter_code = None
    elif unit_code not in COMPATIBLE_UNIT_CODES[parameter_code]:
        compatibility_status = "unsuitable"
        exclusion_reason = "unsupported_unit"
        mapped_parameter_code = None
    else:
        compatibility_status = "compatible"
        exclusion_reason = None
        mapped_parameter_code = parameter_code
    return {
        "openaq_sensor_id": sensor.get("id"),
        "sensor_name": sensor.get("name"),
        "openaq_parameter_id": parameter.get("id"),
        "openaq_parameter_name": provider_parameter_name or None,
        "openaq_parameter_display_name": parameter.get("displayName"),
        "provider_unit": provider_unit or None,
        "parameter_code": mapped_parameter_code,
        "unit_code": unit_code,
        "compatibility_status": compatibility_status,
        "exclusion_reason": exclusion_reason,
        "native_temporal_metadata": {
            "status": "not_provided_by_location_discovery",
            "aggregation_period": None,
            "expected_frequency_seconds": None,
        },
    }


def _datetime_last_timestamp(location: dict[str, Any]) -> float:
    datetime_last = location.get("datetimeLast")
    if not isinstance(datetime_last, dict):
        return float("-inf")
    raw_utc = datetime_last.get("utc")
    if not isinstance(raw_utc, str):
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(raw_utc.replace("Z", "+00:00"))
    except ValueError:
        return float("-inf")
    if parsed.tzinfo is None:
        return float("-inf")
    return parsed.timestamp()


def _parse_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _candidate_location(
    location: dict[str, Any],
    *,
    discovery_executed_at: datetime,
) -> dict[str, Any]:
    sensor_evaluations = [
        evaluate_sensor_compatibility(sensor)
        for sensor in (location.get("sensors") or [])
        if isinstance(sensor, dict)
    ]
    compatible_sensors = [
        sensor
        for sensor in sensor_evaluations
        if sensor["compatibility_status"] == "compatible"
    ]
    unsuitable_sensors = [
        sensor
        for sensor in sensor_evaluations
        if sensor["compatibility_status"] != "compatible"
    ]
    airgradient_evidence = _airgradient_evidence(location)
    datetime_last = location.get("datetimeLast")
    latest_utc = (
        _parse_utc_datetime(datetime_last.get("utc"))
        if isinstance(datetime_last, dict)
        else None
    )
    if latest_utc is None:
        recent_data_status = "unknown"
    elif latest_utc >= discovery_executed_at - timedelta(
        days=RECENT_DATA_MAX_AGE_DAYS
    ):
        recent_data_status = "recent"
    else:
        recent_data_status = "stale"
    return {
        "openaq_location_id": location.get("id"),
        "location_name": location.get("name"),
        "locality": location.get("locality"),
        "timezone": location.get("timezone"),
        "coordinates": location.get("coordinates"),
        "owner": location.get("owner"),
        "provider": location.get("provider"),
        "is_mobile": bool(location.get("isMobile")),
        "is_reference_monitor": bool(location.get("isMonitor")),
        "instruments": location.get("instruments") or [],
        "licenses": location.get("licenses") or [],
        "datetime_first": location.get("datetimeFirst"),
        "datetime_last": location.get("datetimeLast"),
        "recent_data_status": recent_data_status,
        "selection_eligible": bool(compatible_sensors) and recent_data_status == "recent",
        "compatible_parameter_codes": sorted(
            {sensor["parameter_code"] for sensor in compatible_sensors}
        ),
        "compatible_sensors": compatible_sensors,
        "unsuitable_sensors": unsuitable_sensors,
        "transport_provider": "OpenAQ",
        "hardware_provider": "AirGradient" if airgradient_evidence else None,
        "airgradient_metadata_evidence": airgradient_evidence,
    }


def _location_rank(
    candidate: dict[str, Any],
    uncovered_parameters: set[str],
) -> tuple[int, int, float, int]:
    newly_covered = uncovered_parameters.intersection(
        candidate["compatible_parameter_codes"]
    )
    stationary_reference = (
        candidate["is_reference_monitor"] and not candidate["is_mobile"]
    )
    location_id = int(candidate["openaq_location_id"])
    # Sorted ascending: reference monitors first, then broad new coverage,
    # then most recent metadata, then the stable OpenAQ location ID.
    return (
        0 if stationary_reference else 1,
        -len(newly_covered),
        -_datetime_last_timestamp({"datetimeLast": candidate["datetime_last"]}),
        location_id,
    )


def _select_one_sensor_per_parameter(
    candidate: dict[str, Any],
    newly_covered_parameters: set[str],
) -> list[dict[str, Any]]:
    selected_sensors = []
    for parameter_code in TARGET_PARAMETER_CODES:
        if parameter_code not in newly_covered_parameters:
            continue
        unit_preference = PREFERRED_UNIT_CODES[parameter_code]
        matching = [
            sensor
            for sensor in candidate["compatible_sensors"]
            if sensor["parameter_code"] == parameter_code
        ]
        matching.sort(
            key=lambda sensor: (
                unit_preference.index(sensor["unit_code"]),
                int(sensor["openaq_sensor_id"]),
            )
        )
        selected_sensor = matching[0]
        if (
            parameter_code in {"o3", "no2", "so2", "co"}
            and selected_sensor["unit_code"] in {"ug_m3", "mg_m3"}
        ):
            unit_limitation = (
                "Gas mass concentration is preserved exactly; no mass-to-mixing-"
                "ratio conversion is authorized during discovery or capture."
            )
        else:
            unit_limitation = "Provider parameter identity and unit are preserved without conversion."
        selected_sensors.append(
            {
                **selected_sensor,
                "transport_provider": "OpenAQ",
                "hardware_provider": candidate["hardware_provider"],
                "selection_reason": (
                    "Exact target parameter identity, compatible preserved unit, "
                    "and deterministic preferred-unit/sensor-ID ranking."
                ),
                "known_limitation": unit_limitation,
            }
        )
    return selected_sensors


def select_reference_candidates(staging_payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the documented deterministic ranking to one saved response."""
    locations = staging_payload.get("locations")
    if not isinstance(locations, list):
        raise OpenAQDiscoveryError("Staging payload is missing locations")
    source_request = staging_payload.get("request")
    discovery_executed_at = _parse_utc_datetime(
        source_request.get("executed_at") if isinstance(source_request, dict) else None
    )
    if discovery_executed_at is None:
        raise OpenAQDiscoveryError("Staging payload has no valid request executed_at")
    candidates = [
        _candidate_location(
            location,
            discovery_executed_at=discovery_executed_at,
        )
        for location in locations
        if isinstance(location, dict)
    ]
    candidates.sort(key=lambda candidate: int(candidate["openaq_location_id"]))
    all_compatible_parameters = {
        parameter
        for candidate in candidates
        for parameter in candidate["compatible_parameter_codes"]
    }
    available_parameters = {
        parameter
        for candidate in candidates
        if candidate["selection_eligible"]
        for parameter in candidate["compatible_parameter_codes"]
    }
    uncovered = set(available_parameters)
    selected_locations = []
    while uncovered:
        contributing = [
            candidate
            for candidate in candidates
            if candidate["selection_eligible"]
            and uncovered.intersection(candidate["compatible_parameter_codes"])
        ]
        if not contributing:
            break
        contributing.sort(key=lambda candidate: _location_rank(candidate, uncovered))
        selected = contributing[0]
        newly_covered = uncovered.intersection(
            selected["compatible_parameter_codes"]
        )
        selected_sensors = _select_one_sensor_per_parameter(
            selected, newly_covered
        )
        selected_locations.append(
            {
                **{
                    key: value
                    for key, value in selected.items()
                    if key not in {"compatible_sensors", "unsuitable_sensors"}
                },
                "selected_sensors": selected_sensors,
                "selection_reason": (
                    "Deterministic ranking: stationary reference monitor, "
                    "new compatible-parameter coverage, recent availability, "
                    "then stable OpenAQ location ID."
                ),
                "known_limitation": (
                    "The locations discovery response does not provide native "
                    "sensor interval or aggregation metadata; Phase 2I.4 must "
                    "qualify temporal semantics before measurement capture."
                ),
            }
        )
        uncovered.difference_update(newly_covered)

    coverage = {
        parameter: parameter in available_parameters
        for parameter in TARGET_PARAMETER_CODES
    }
    gaps = {}
    for parameter, covered in coverage.items():
        if covered:
            continue
        if parameter in all_compatible_parameters:
            gaps[parameter] = (
                "no_recent_compatible_openaq_sensor_in_approved_radius"
            )
        else:
            gaps[parameter] = "no_compatible_openaq_sensor_in_approved_radius"
    airgradient_matches = [
        {
            "openaq_location_id": candidate["openaq_location_id"],
            "location_name": candidate["location_name"],
            "metadata_evidence": candidate["airgradient_metadata_evidence"],
        }
        for candidate in candidates
        if candidate["airgradient_metadata_evidence"]
    ]
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "provider": "OpenAQ",
        "reference_area_code": staging_payload.get("reference_area_code"),
        "reference_area_name": staging_payload.get("reference_area_name"),
        "timezone_reference": staging_payload.get("timezone_reference"),
        "source_request": source_request,
        "response_meta": staging_payload.get("response_meta"),
        "target_parameter_codes": list(TARGET_PARAMETER_CODES),
        "recent_data_max_age_days": RECENT_DATA_MAX_AGE_DAYS,
        "candidate_locations": candidates,
        "selected_locations": selected_locations,
        "coverage": coverage,
        "gaps": gaps,
        "airgradient_status": (
            "confirmed_airgradient_hardware_via_openaq_metadata"
            if airgradient_matches
            else "no_confirmed_public_airgradient_device_in_reference_area"
        ),
        "airgradient_matches": airgradient_matches,
    }


def write_selection_manifests(plan_path: Path) -> dict[str, Any]:
    """Select from saved discovery only; this function has no HTTP path."""
    plan = _read_plan(plan_path)
    areas = validate_discovery_plan(plan)
    selections = []
    discovery_destinations = []
    for area in areas:
        staging_path = (plan_path.parent / area["staging_destination"]).resolve()
        try:
            staging_payload = json.loads(staging_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpenAQDiscoveryError(
                f"Invalid staged discovery file {staging_path}: {exc}"
            ) from exc
        selection = select_reference_candidates(staging_payload)
        selection_path = (
            plan_path.parent / "discovery" / f"{area['reference_area_code']}.json"
        ).resolve()
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        selection_path.write_text(
            json.dumps(selection, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        selections.append(selection)
        discovery_destinations.append(str(selection_path))

    selected_sensor_count = sum(
        len(location["selected_sensors"])
        for selection in selections
        for location in selection["selected_locations"]
    )
    phase_2i4_proposal = plan.get("phase_2i4_proposal")
    if not isinstance(phase_2i4_proposal, dict):
        raise OpenAQDiscoveryError("phase_2i4_proposal is required")
    capture_window_start = _parse_utc_datetime(
        phase_2i4_proposal.get("window_start")
    )
    capture_window_end = _parse_utc_datetime(phase_2i4_proposal.get("window_end"))
    page_size = phase_2i4_proposal.get("measurement_page_size")
    cadence_seconds = phase_2i4_proposal.get("conservative_cadence_seconds")
    if (
        capture_window_start is None
        or capture_window_end is None
        or capture_window_end <= capture_window_start
        or page_size != 1000
        or cadence_seconds != 60
    ):
        raise OpenAQDiscoveryError("phase_2i4_proposal is invalid")
    expected_rows_per_sensor_ceiling = int(
        (capture_window_end - capture_window_start).total_seconds()
        / cadence_seconds
    )
    expected_pages_per_sensor_ceiling = (
        expected_rows_per_sensor_ceiling + page_size - 1
    ) // page_size
    conservative_expected_request_count = (
        selected_sensor_count * expected_pages_per_sensor_ceiling
    )

    combined_manifest = {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "provider": "OpenAQ",
        "transport_provider": "OpenAQ",
        "measurement_capture_performed": False,
        "target_parameter_codes": list(TARGET_PARAMETER_CODES),
        "reference_areas": [
            {
                "reference_area_code": selection["reference_area_code"],
                "reference_area_name": selection["reference_area_name"],
                "timezone_reference": selection["timezone_reference"],
                "selected_locations": selection["selected_locations"],
                "coverage": selection["coverage"],
                "gaps": selection["gaps"],
                "airgradient_status": selection["airgradient_status"],
                "airgradient_matches": selection["airgradient_matches"],
            }
            for selection in selections
        ],
        "coverage_matrix": {
            selection["reference_area_code"]: selection["coverage"]
            for selection in selections
        },
        "proposed_capture_window": {
            "window_start": phase_2i4_proposal["window_start"],
            "window_end": phase_2i4_proposal["window_end"],
            "duration_days": 7,
        },
        "phase_2i4_request_estimate": {
            "selected_sensor_count": selected_sensor_count,
            "measurement_page_size": page_size,
            "conservative_cadence_seconds": cadence_seconds,
            "expected_rows_per_sensor_ceiling": expected_rows_per_sensor_ceiling,
            "expected_pages_per_sensor_ceiling": expected_pages_per_sensor_ceiling,
            "conservative_expected_request_count": conservative_expected_request_count,
            "native_temporal_metadata_qualified": False,
            "requires_separate_phase_2i4_approval": True,
            "rationale": phase_2i4_proposal["rationale"],
        },
    }
    combined_path = (plan_path.parent / "selected_reference_manifest.json").resolve()
    combined_path.write_text(
        json.dumps(combined_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "network_requests_executed": 0,
        "discovery_destinations": discovery_destinations,
        "selected_manifest_destination": str(combined_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded OpenAQ reference discovery")
    parser.add_argument("--plan", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--select-staged", action="store_true")
    parser.add_argument("--confirm-bounded-openaq-discovery", action="store_true")
    args = parser.parse_args()
    plan_path = args.plan.resolve()
    if args.dry_run:
        report = build_dry_run_report(plan_path)
    elif args.execute:
        if not args.confirm_bounded_openaq_discovery:
            parser.error("--execute requires --confirm-bounded-openaq-discovery")
        report = execute_bounded_discovery(
            plan_path,
            api_key=os.getenv("OPENAQ_API_KEY", ""),
        )
    else:
        report = write_selection_manifests(plan_path)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
