"""Public Map history contract, distinct from Dashboard current snapshots.

Verified 2026-10-13 against Map OpenAPI and provider source commit c361a6f.
date_bin returns the UTC bucket start. The provider filters, aggregates, and
corrects values; neither underlying sample count nor measured coverage is given.
The provider SQL includes both request endpoints, so end is sent minus 1 ms.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any

import requests

BASE_URL = "https://map-data.airgradient.com/map/api/v1"
BUCKET_SECONDS = 900
INITIAL_LOOKBACK = timedelta(days=1)
PUBLICATION_DELAY = timedelta(hours=1)
OVERLAP = timedelta(hours=6)
CHUNK = timedelta(days=1)
MAX_WINDOWS_PER_STREAM = 2
MAX_RUN_SECONDS = 240


class MapHistoryError(RuntimeError):
    """An interval was not examined successfully; retain its checkpoint."""


class MapHistoryRateLimit(MapHistoryError):
    """Stop public history requests for this execution and resume next run."""


@dataclass(frozen=True)
class ReferenceMapping:
    map_id: int
    name: str
    latitude: float
    longitude: float


# Separate provider namespaces. These pairs were checked using both APIs;
# metadata must still match on every import before history is requested.
REFERENCE_MAPPINGS = {
    "58376": ReferenceMapping(4955171, "Larchmont, NY", 40.940119, -73.7561704),
    "175911": ReferenceMapping(14699912, "São Paulo", -23.6473149, -46.6643635),
    "160791": ReferenceMapping(8334410, "Manila Observatory", 14.6354, 121.0779),
}


@dataclass(frozen=True)
class ParameterMapping:
    parameter_code: str
    unit_code: str


# Only verified fields present on these AirGradient monitors. Map o3/no2 are
# other-provider products; PM1, pressure, TVOC and NOx remain snapshot-only.
PARAMETERS = {
    "pm25": ParameterMapping("pm25", "ug_m3"),
    "pm10": ParameterMapping("pm10", "ug_m3"),
    "atmp": ParameterMapping("temperature", "celsius"),
    "rhum": ParameterMapping("relative_humidity", "percent"),
    "rco2": ParameterMapping("co2", "ppm"),
}


@dataclass(frozen=True)
class HistoryObservation:
    bucket_start: datetime
    value: float


def public_get(path: str, params: dict | None = None) -> Any:
    """Fixed public host, no credential argument, headers or session reuse."""
    try:
        response = requests.get(
            f"{BASE_URL}/{path}", params=params, timeout=20, allow_redirects=False,
        )
    except requests.Timeout as exc:
        raise MapHistoryError("AirGradient Map request timed out") from exc
    except requests.RequestException as exc:
        raise MapHistoryError("AirGradient Map could not be reached") from exc
    if response.status_code == 429:
        raise MapHistoryRateLimit("AirGradient Map rate limit; resume next execution")
    if response.status_code != 200:
        raise MapHistoryError(f"AirGradient Map request failed (HTTP {response.status_code})")
    try:
        return response.json()
    except ValueError as exc:
        raise MapHistoryError("AirGradient Map returned malformed JSON") from exc


def validate_location(dashboard_id: str, dashboard: dict, metadata: Any) -> ReferenceMapping:
    mapping = REFERENCE_MAPPINGS.get(dashboard_id)
    if mapping is None or not isinstance(metadata, dict):
        raise MapHistoryError("Unapproved or malformed AirGradient Map location")
    if (
        str(dashboard.get("locationId")) != dashboard_id
        or metadata.get("locationId") != mapping.map_id
        or metadata.get("dataSource") != "AirGradient"
        or metadata.get("provider") != "AirGradient"
        or dashboard.get("locationName") != mapping.name
        or metadata.get("locationName") != mapping.name
        or metadata.get("licenses") != ["CC BY-SA 4.0"]
        or (metadata.get("ownerName") is not None and metadata.get("ownerName") != dashboard.get("publicContributorName"))
        or (metadata.get("url") is not None and metadata.get("url") != dashboard.get("publicPlaceUrl"))
    ):
        raise MapHistoryError("AirGradient Dashboard/Map identity or license mismatch")
    for payload in (dashboard, metadata):
        for field, expected in (("latitude", mapping.latitude), ("longitude", mapping.longitude)):
            value = payload.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MapHistoryError("AirGradient location coordinates unavailable")
            if not math.isfinite(value) or abs(value - expected) > 0.00001:
                raise MapHistoryError("AirGradient Dashboard/Map coordinates mismatch")
    return mapping


def floor_bucket(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise MapHistoryError("History window must use timezone-aware UTC dates")
    seconds = int(value.timestamp()) // BUCKET_SECONDS * BUCKET_SECONDS
    return datetime.fromtimestamp(seconds, timezone.utc)


def closed_until(now: datetime) -> datetime:
    return floor_bucket(now - PUBLICATION_DELAY)


def windows(checkpoint: datetime | None, until: datetime, initial_start: datetime | None = None):
    """Catch up oldest unexamined intervals; overlap once per execution."""
    if checkpoint is None:
        start = initial_start if initial_start is not None else until - INITIAL_LOOKBACK
        if start != floor_bucket(start) or start > until:
            raise MapHistoryError("Invalid initial AirGradient history interval")
    else:
        # SQLite stores UTC columns without an offset.
        checkpoint = (checkpoint.replace(tzinfo=timezone.utc) if checkpoint.tzinfo is None
                      else checkpoint.astimezone(timezone.utc))
        if checkpoint != floor_bucket(checkpoint) or checkpoint > until:
            raise MapHistoryError("Invalid AirGradient history checkpoint")
        start = checkpoint - OVERLAP
    for _ in range(MAX_WINDOWS_PER_STREAM):
        if start >= until:
            break
        end = min(start + CHUNK, until)
        yield start, end
        start = end


def parse_history(raw: Any, start: datetime, end: datetime) -> tuple[list[HistoryObservation], int]:
    """Validate the entire response before writes; nulls are missing, never zero."""
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        raise MapHistoryError("Malformed AirGradient Map history envelope")
    rows = raw["data"]
    if type(raw.get("total")) is not int or raw["total"] != len(rows):
        raise MapHistoryError("Truncated AirGradient Map history response")
    if len(rows) > int((end - start).total_seconds()) // BUCKET_SECONDS:
        raise MapHistoryError("Unsupported AirGradient Map history resolution")
    observations = []
    missing = 0
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("timebucket"), str) or "value" not in row:
            raise MapHistoryError("Malformed AirGradient Map history row")
        try:
            timestamp = datetime.fromisoformat(row["timebucket"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise MapHistoryError("Malformed AirGradient Map bucket timestamp") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
            raise MapHistoryError("AirGradient Map bucket timestamp is not UTC")
        if timestamp != floor_bucket(timestamp) or not start <= timestamp < end or timestamp in seen:
            raise MapHistoryError("Unaligned, incomplete or duplicate AirGradient Map bucket")
        seen.add(timestamp)
        value = row["value"]
        if value is None:
            missing += 1
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise MapHistoryError("Malformed AirGradient Map bucket value")
        # PostgreSQL NUMERIC fields arrive as decimal strings for non-PM2.5.
        if isinstance(value, str) and not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
            raise MapHistoryError("Malformed AirGradient Map decimal value")
        try:
            numeric = float(value)
        except (ValueError, OverflowError) as exc:
            raise MapHistoryError("Malformed AirGradient Map bucket value") from exc
        if not math.isfinite(numeric):
            raise MapHistoryError("Nonfinite AirGradient Map bucket value")
        observations.append(HistoryObservation(timestamp, numeric))
    return observations, missing


def fetch_history(map_id: int, parameter: str, start: datetime, end: datetime):
    if parameter not in PARAMETERS:
        raise MapHistoryError("Unsupported AirGradient historical parameter")
    if start != floor_bucket(start) or end != floor_bucket(end) or not start < end or end - start > CHUNK:
        raise MapHistoryError("Invalid AirGradient history window")
    raw = public_get(f"locations/{map_id}/measures/history", {
        "measure": parameter,
        "bucketSize": "15m",
        "start": start.isoformat(),
        "end": (end - timedelta(milliseconds=1)).isoformat(),
        "excludeOutliers": "true",
    })
    return parse_history(raw, start, end)


def provenance(dashboard_id: str, map_id: int, parameter: str, metadata: dict) -> dict:
    return {
        "provider": "AirGradient",
        "acquisition_method": "map_processed_history",
        "endpoint": f"{BASE_URL}/locations/{map_id}/measures/history",
        "dashboard_location_id": dashboard_id,
        "map_location_id": map_id,
        "upstream_parameter": parameter,
        "canonical_unit_code": PARAMETERS[parameter].unit_code,
        "provider_contract_verified_on": "2026-10-13",
        "native_resolution_seconds": BUCKET_SECONDS,
        "timestamp_semantics": "interval_start",
        "interval_bounds": "nominal_utc_bucket_start_plus_900_seconds",
        "underlying_sample_count": None,
        "underlying_coverage_seconds": None,
        "provider_processing": ["time_bucket_mean", "value_range_filter", "rounding"] + (
            ["pm25_outlier_exclusion", "humidity_pm25_correction", "corrected_value_rounding_and_clamping"]
            if parameter == "pm25" else []
        ),
        "provider_processing_is_compassaq_qc": False,
        "contributor_name": metadata.get("ownerName"),
        "contributor_url": metadata.get("url"),
        "provider_url": "https://www.airgradient.com",
        "license_code": "CC-BY-SA-4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "license_share_alike": True,
    }
