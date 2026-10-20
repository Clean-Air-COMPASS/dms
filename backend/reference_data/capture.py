"""Zero-network capture planning. Live discovery/capture is intentionally absent."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable


def _utc_timestamp(
    value: Any,
    field_name: str,
    blockers: list[str],
    *,
    allow_explicit_offset: bool = False,
) -> datetime | None:
    if not value:
        blockers.append(field_name)
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        blockers.append(f"{field_name}_invalid")
        return None
    if parsed.tzinfo is None:
        blockers.append(f"{field_name}_must_include_timezone")
        return None
    if (
        not allow_explicit_offset
        and parsed.utcoffset() != timezone.utc.utcoffset(parsed)
    ):
        blockers.append(f"{field_name}_must_be_utc")
        return None
    return parsed.astimezone(timezone.utc)


def _nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def calculate_endpoint_points(
    *,
    request_count: int,
    expected_rows: int,
    endpoint_base_points: int | float,
    requested_fields: list[str],
    field_points: dict[str, int | float],
) -> dict[str, int | float]:
    """Calculate one endpoint's base and row-based field point costs.

    PurpleAir's historical pricing charges the endpoint base once per request,
    while requested field costs apply to every returned row. Expected rows use
    the full documented cadence, so missing observations cannot reduce the
    pre-capture estimate.
    """
    field_points_per_row = sum(field_points[field] for field in requested_fields)
    endpoint_base_points_total = request_count * endpoint_base_points
    field_points_total = expected_rows * field_points_per_row
    return {
        "endpoint_base_points_total": endpoint_base_points_total,
        "field_points_per_row": field_points_per_row,
        "field_points_total": field_points_total,
        "total_points": endpoint_base_points_total + field_points_total,
    }


def plan_capture(
    manifest_path: Path,
    request_executor: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Read local planning metadata and calculate counts without using executor."""
    raw_bytes = manifest_path.read_bytes()
    manifest = json.loads(raw_bytes.decode("utf-8"))
    blockers: list[str] = []
    provider = str(manifest.get("provider") or "").strip()
    reference_sensors = manifest.get("reference_sensors")
    planned_provider_count = None
    if isinstance(reference_sensors, list) and reference_sensors:
        planned_provider_count = len(reference_sensors)
        provider_ids = []
        seen_provider_ids: set[str] = set()
        for reference_sensor in reference_sensors:
            if not isinstance(reference_sensor, dict):
                blockers.append("reference_sensors")
                continue
            reference_area_code = str(
                reference_sensor.get("reference_area_code") or "unknown"
            )
            provider_id = str(reference_sensor.get("sensor_id") or "").strip()
            if not provider_id:
                blockers.append(f"reference_sensor_id:{reference_area_code}")
                continue
            if provider_id in seen_provider_ids:
                blockers.append(f"duplicate_provider_id:{provider_id}")
                continue
            seen_provider_ids.add(provider_id)
            provider_ids.append(provider_id)
    else:
        reference_sensors = []
        provider_ids = [
            str(value)
            for value in (manifest.get("provider_ids") or [])
            if str(value).strip()
        ]
        planned_provider_count = len(provider_ids)
    fields = [str(value) for value in (manifest.get("fields") or []) if str(value).strip()]
    metadata_fields = [
        str(value)
        for value in (manifest.get("metadata_fields") or [])
        if str(value).strip()
    ]
    if not provider:
        blockers.append("provider")
    if not provider_ids and not reference_sensors:
        blockers.append("provider_ids")
    if not fields:
        blockers.append("fields")
    window_start = _utc_timestamp(manifest.get("window_start"), "window_start", blockers)
    window_end = _utc_timestamp(manifest.get("window_end"), "window_end", blockers)
    if window_start and window_end and window_end <= window_start:
        blockers.append("window_must_end_after_start")

    frequency_seconds = manifest.get("expected_frequency_seconds")
    rows_per_page = manifest.get("rows_per_page")
    expected_rows = None
    expected_rows_per_provider_id = None
    expected_pages = None
    history_request_count = None
    if not isinstance(frequency_seconds, int) or frequency_seconds <= 0:
        blockers.append("expected_frequency_seconds")
    if not isinstance(rows_per_page, int) or rows_per_page <= 0:
        blockers.append("rows_per_page")
    if (
        window_start
        and window_end
        and isinstance(frequency_seconds, int)
        and frequency_seconds > 0
        and planned_provider_count
    ):
        expected_rows_per_provider_id = math.ceil(
            (window_end - window_start).total_seconds() / frequency_seconds
        )
        expected_rows = expected_rows_per_provider_id * planned_provider_count
        if isinstance(rows_per_page, int) and rows_per_page > 0:
            expected_pages = (
                math.ceil(expected_rows_per_provider_id / rows_per_page)
                * planned_provider_count
            )
            history_request_count = expected_pages

    retry_count = manifest.get("retry_count")
    average = manifest.get("average")
    if provider.lower() == "purpleair":
        if average != 0:
            blockers.append("average_must_be_zero")
        if retry_count != 0:
            blockers.append("retry_count_must_be_zero")

    raw_metadata_request_count = manifest.get("metadata_request_count", 0)
    metadata_request_count = None
    if (
        isinstance(raw_metadata_request_count, int)
        and not isinstance(raw_metadata_request_count, bool)
        and raw_metadata_request_count >= 0
    ):
        metadata_request_count = raw_metadata_request_count
    else:
        blockers.append("metadata_request_count")

    raw_metadata_expected_rows = manifest.get("metadata_expected_rows")
    metadata_expected_rows = None
    if metadata_request_count == 0:
        metadata_expected_rows = 0
        if raw_metadata_expected_rows not in (None, 0):
            blockers.append("metadata_rows_require_requests")
    elif metadata_request_count is not None:
        if (
            isinstance(raw_metadata_expected_rows, int)
            and not isinstance(raw_metadata_expected_rows, bool)
            and raw_metadata_expected_rows >= 0
        ):
            metadata_expected_rows = raw_metadata_expected_rows
        else:
            blockers.append("metadata_expected_rows")
        if not metadata_fields:
            blockers.append("metadata_fields")

    request_count = (
        history_request_count + metadata_request_count
        if history_request_count is not None and metadata_request_count is not None
        else None
    )

    raw_pricing = manifest.get("pricing")
    if isinstance(raw_pricing, dict):
        pricing = raw_pricing
    else:
        pricing = {}
        if provider.lower() == "purpleair":
            blockers.append("pricing")
    pricing_verified_at = None
    estimated_history_points = None
    estimated_metadata_points = None
    estimated_points = None
    recommended_max_points_ceiling = None
    history_cost = None
    metadata_cost = None
    point_formula = None
    history_endpoint_base_points = None
    history_field_points: dict[str, int | float] = {}
    metadata_endpoint_base_points = None
    metadata_field_points: dict[str, int | float] = {}
    safety_margin_percent = pricing.get("safety_margin_percent", 0)
    paid_provider = bool(manifest.get("paid_provider", provider.lower() == "purpleair"))
    if provider.lower() == "purpleair":
        pricing_verified_at = _utc_timestamp(
            pricing.get("verified_at"),
            "pricing_verified_at",
            blockers,
            allow_explicit_offset=True,
        )
        history_endpoint_base_points = pricing.get("history_endpoint_base_points")
        raw_history_field_points = pricing.get("history_field_points")
        if isinstance(raw_history_field_points, dict):
            history_field_points = raw_history_field_points
        else:
            history_field_points = {}
            blockers.append("history_field_points")
        if not _nonnegative_number(history_endpoint_base_points):
            blockers.append("history_endpoint_base_points")
        missing_history_field_prices = [
            field
            for field in fields
            if not _nonnegative_number(history_field_points.get(field))
        ]
        blockers.extend(
            f"history_field_points:{field}" for field in missing_history_field_prices
        )

        if metadata_request_count and metadata_request_count > 0:
            metadata_endpoint_base_points = pricing.get("metadata_endpoint_base_points")
            raw_metadata_field_points = pricing.get("metadata_field_points")
            if isinstance(raw_metadata_field_points, dict):
                metadata_field_points = raw_metadata_field_points
            else:
                metadata_field_points = {}
                blockers.append("metadata_field_points")
            if not _nonnegative_number(metadata_endpoint_base_points):
                blockers.append("metadata_endpoint_base_points")
            missing_metadata_field_prices = [
                field
                for field in metadata_fields
                if not _nonnegative_number(metadata_field_points.get(field))
            ]
            blockers.extend(
                f"metadata_field_points:{field}"
                for field in missing_metadata_field_prices
            )
        else:
            metadata_endpoint_base_points = 0
            metadata_field_points = {}

        if not _nonnegative_number(safety_margin_percent):
            blockers.append("pricing_safety_margin_percent")

        history_pricing_complete = (
            history_request_count is not None
            and expected_rows is not None
            and _nonnegative_number(history_endpoint_base_points)
            and not missing_history_field_prices
        )
        if history_pricing_complete:
            history_cost = calculate_endpoint_points(
                request_count=history_request_count,
                expected_rows=expected_rows,
                endpoint_base_points=history_endpoint_base_points,
                requested_fields=fields,
                field_points=history_field_points,
            )
            estimated_history_points = history_cost["total_points"]

        metadata_pricing_complete = (
            metadata_request_count is not None
            and metadata_expected_rows is not None
            and (
                metadata_request_count == 0
                or (
                    _nonnegative_number(metadata_endpoint_base_points)
                    and bool(metadata_fields)
                    and not missing_metadata_field_prices
                )
            )
        )
        if metadata_pricing_complete:
            metadata_cost = calculate_endpoint_points(
                request_count=metadata_request_count,
                expected_rows=metadata_expected_rows,
                endpoint_base_points=metadata_endpoint_base_points,
                requested_fields=metadata_fields,
                field_points=metadata_field_points,
            )
            estimated_metadata_points = metadata_cost["total_points"]

        if (
            estimated_history_points is not None
            and estimated_metadata_points is not None
            and _nonnegative_number(safety_margin_percent)
        ):
            estimated_points = estimated_history_points + estimated_metadata_points
            if pricing_verified_at is not None:
                recommended_max_points_ceiling = math.ceil(
                    estimated_points * (1 + safety_margin_percent / 100)
                )
            point_formula = (
                "history_request_count * history_endpoint_base_points + "
                "expected_rows * sum(history requested-field points) + "
                "metadata_request_count * metadata_endpoint_base_points + "
                "metadata_expected_rows * sum(metadata requested-field points)"
            )

    unique_blockers = sorted(set(blockers))
    return {
        "dry_run": True,
        "capture_ready": not unique_blockers,
        "network_requests_executed": 0,
        "provider": provider or None,
        "provider_ids": provider_ids,
        "reference_sensors": reference_sensors,
        "planned_provider_count": planned_provider_count,
        "fields": fields,
        "average": average,
        "retry_count": retry_count,
        "metadata_fields": metadata_fields,
        "window_start": window_start.isoformat().replace("+00:00", "Z") if window_start else None,
        "window_end": window_end.isoformat().replace("+00:00", "Z") if window_end else None,
        "expected_rows": expected_rows,
        "expected_rows_per_provider_id": expected_rows_per_provider_id,
        "expected_pages": expected_pages,
        "history_request_count": history_request_count,
        "metadata_request_count": metadata_request_count,
        "metadata_expected_rows": metadata_expected_rows,
        "request_count": request_count,
        "paid_provider": paid_provider,
        "pricing_verified_at": (
            str(pricing.get("verified_at"))
            if pricing_verified_at
            else None
        ),
        "purpleair_point_formula": point_formula,
        "history_endpoint_base_points": history_endpoint_base_points,
        "history_field_points": history_field_points,
        "history_point_estimate": history_cost,
        "metadata_endpoint_base_points": metadata_endpoint_base_points,
        "metadata_field_points": metadata_field_points,
        "metadata_point_estimate": metadata_cost,
        "estimated_history_points": estimated_history_points,
        "estimated_metadata_points": estimated_metadata_points,
        "estimated_points": estimated_points,
        "safety_margin_percent": (
            safety_margin_percent
            if _nonnegative_number(safety_margin_percent)
            else None
        ),
        "recommended_max_points_ceiling": recommended_max_points_ceiling,
        "output_fixture_paths": manifest.get("output_fixture_paths") or [],
        "manifest_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "blockers": unique_blockers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan an offline reference-data capture")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("Only --dry-run is implemented; live capture is not available")
    print(json.dumps(plan_capture(args.manifest.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
