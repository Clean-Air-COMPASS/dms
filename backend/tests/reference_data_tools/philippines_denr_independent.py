from __future__ import annotations

"""Independent Philippine AQI candidate derivation from frozen JSONL rows.

This review seam deliberately uses only the Python standard library and copies
the applicable source rules. It must not import production CompassAQ code.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, localcontext
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MANILA_TIMEZONE = ZoneInfo("Asia/Manila")
PM_BREAKPOINTS = {
    "pm25": (
        ("0", "25", 0, 50, "good"),
        ("25.1", "35.0", 51, 100, "fair"),
        ("35.1", "45.0", 101, 150, "unhealthy_for_sensitive_groups"),
        ("45.1", "55", 151, 200, "very_unhealthy"),
        ("55.1", "90", 201, 300, "acutely_unhealthy"),
    ),
    "pm10": (
        ("0", "54", 0, 50, "good"),
        ("55", "154", 51, 100, "fair"),
        ("155", "254", 101, 150, "unhealthy_for_sensitive_groups"),
        ("255", "354", 151, 200, "very_unhealthy"),
        ("355", "424", 201, 300, "acutely_unhealthy"),
        ("425", "504", 301, 500, "emergency"),
    ),
}


def _read_rows(path: Path, sensor_ref: str) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if row["sensor_ref"] == sensor_ref:
                rows.append(row)
    return rows


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _manila_day_bounds(represented_date: date) -> tuple[datetime, datetime]:
    local_start = datetime(
        represented_date.year,
        represented_date.month,
        represented_date.day,
        tzinfo=MANILA_TIMEZONE,
    )
    return local_start.astimezone(timezone.utc), (local_start + timedelta(days=1)).astimezone(timezone.utc)


def _interpolate(parameter_code: str, concentration: Decimal) -> dict[str, Any]:
    processed = concentration.quantize(
        Decimal("0.1") if parameter_code == "pm25" else Decimal("1"),
        rounding=ROUND_DOWN,
    )
    if parameter_code == "pm25" and processed >= Decimal("91"):
        return {"preprocessed_concentration": str(processed), "numeric_value": None, "category_code": "emergency", "calculation_status": "category_only"}
    for low_text, high_text, index_low, index_high, category_code in PM_BREAKPOINTS[parameter_code]:
        low = Decimal(low_text)
        high = Decimal(high_text)
        if low <= processed <= high:
            with localcontext() as context:
                context.prec = 50
                value = (
                    Decimal(index_high - index_low)
                    / (high - low)
                    * (processed - low)
                    + Decimal(index_low)
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return {"preprocessed_concentration": str(processed), "numeric_value": str(value), "category_code": category_code, "calculation_status": "calculated"}
    raise ValueError(f"Published breakpoint gap for {parameter_code}: {processed}")


def _purpleair_hour(rows: list[dict[str, Any]], hour_start: datetime) -> dict[str, Any]:
    hour_end = hour_start + timedelta(hours=1)
    represented = [row for row in rows if hour_start < _timestamp(row["observed_at"]) <= hour_end]
    anchors = [hour_start + timedelta(minutes=2 * position) for position in range(1, 31)]
    candidates: dict[int, list[tuple[float, str, Decimal]]] = {}
    off_frequency = []
    for row in represented:
        observed = _timestamp(row["observed_at"])
        distances = [abs((observed - anchor).total_seconds()) for anchor in anchors]
        position = min(range(30), key=lambda index: (distances[index], index))
        if distances[position] > 60:
            off_frequency.append(row["provider_observation_ref"])
            continue
        candidates.setdefault(position, []).append(
            (distances[position], row["provider_observation_ref"], Decimal(str(row["value"])))
        )
    accepted = []
    duplicates = []
    for position in sorted(candidates):
        ordered = sorted(candidates[position])
        accepted.append(ordered[0][2])
        duplicates.extend(item[1] for item in ordered[1:])
    eligible = len(accepted) >= 23
    return {
        "eligible": eligible,
        "valid_position_count": len(accepted),
        "concentration": sum(accepted, Decimal("0")) / Decimal(len(accepted)) if eligible else None,
        "duplicate_count": len(duplicates),
        "off_frequency_count": len(off_frequency),
    }


def _daily_result(hourly: list[dict[str, Any]], parameter_code: str) -> dict[str, Any]:
    valid = [hour for hour in hourly if hour["eligible"]]
    block_counts = [sum(hour["eligible"] for hour in hourly[offset : offset + 8]) for offset in (0, 8, 16)]
    maximum_missing = current_missing = 0
    for hour in hourly:
        current_missing = 0 if hour["eligible"] else current_missing + 1
        maximum_missing = max(maximum_missing, current_missing)
    eligible = len(valid) >= 18 and all(count >= 6 for count in block_counts) and maximum_missing <= 2
    result = {
        "eligibility_status": "eligible" if eligible else "ineligible",
        "valid_hour_count": len(valid),
        "block_valid_hour_counts": block_counts,
        "maximum_consecutive_missing_hours": maximum_missing,
    }
    if not eligible:
        return result
    concentration = sum((hour["concentration"] for hour in valid), Decimal("0")) / Decimal(len(valid))
    result["normalized_concentration"] = str(concentration)
    result.update(_interpolate(parameter_code, concentration))
    return result


def derive_purpleair_completed_day(
    measurements_path: Path,
    *,
    sensor_ref: str,
    parameter_code: str,
    represented_date: date,
) -> dict[str, Any]:
    rows = _read_rows(measurements_path, sensor_ref)
    utc_start, utc_end = _manila_day_bounds(represented_date)
    hourly = [_purpleair_hour(rows, utc_start + timedelta(hours=index)) for index in range(24)]
    return {
        "sensor_ref": sensor_ref,
        "parameter_code": parameter_code,
        "represented_local_date": represented_date.isoformat(),
        "utc_window_started_at": utc_start.isoformat().replace("+00:00", "Z"),
        "utc_window_ended_at": utc_end.isoformat().replace("+00:00", "Z"),
        **_daily_result(hourly, parameter_code),
    }


def derive_openaq_completed_day(
    measurements_path: Path,
    *,
    sensor_ref: str,
    represented_date: date,
) -> dict[str, Any]:
    rows = _read_rows(measurements_path, sensor_ref)
    utc_start, utc_end = _manila_day_bounds(represented_date)
    represented = [row for row in rows if utc_start < _timestamp(row["observed_at"]) <= utc_end]
    timestamps = [_timestamp(row["observed_at"]) for row in represented]
    exact_boundaries = all(item.minute == item.second == item.microsecond == 0 for item in timestamps)
    unique = len(timestamps) == len(set(timestamps))
    hourly = [
        {
            "eligible": exact_boundaries and unique,
            "concentration": Decimal(str(row["value"])),
        }
        for row in represented
    ]
    return {
        "sensor_ref": sensor_ref,
        "parameter_code": "pm25",
        "represented_local_date": represented_date.isoformat(),
        "utc_window_started_at": utc_start.isoformat().replace("+00:00", "Z"),
        "utc_window_ended_at": utc_end.isoformat().replace("+00:00", "Z"),
        **_daily_result(hourly, "pm25"),
    }


def build_candidate_bundle(public_measurements: Path, restricted_measurements: Path) -> dict[str, Any]:
    return {
        "bundle_status": "candidate_awaiting_analyst_approval",
        "methodology_code": "philippines_denr_aqi",
        "methodology_version": "denr_emb_aqi_2021",
        "provider_calls": 0,
        "source_hashes": {
            "openaq_measurements_sha256": _sha256(public_measurements),
            "purpleair_measurements_sha256": _sha256(restricted_measurements),
        },
        "cases": [
            derive_openaq_completed_day(public_measurements, sensor_ref="openaq-sensor-13191003", represented_date=date(2026, 8, 2)),
            derive_purpleair_completed_day(restricted_measurements, sensor_ref="purpleair-99177-pm25", parameter_code="pm25", represented_date=date(2026, 8, 9)),
            derive_purpleair_completed_day(restricted_measurements, sensor_ref="purpleair-99177-pm10", parameter_code="pm10", represented_date=date(2026, 8, 9)),
        ],
        "explicit_absences": {
            "openaq_manila_pm10": True,
            "openaq_manila_gases": ["so2", "o3", "co", "no2"],
            "purpleair_manila_gases": ["so2", "o3", "co", "no2"],
        },
        "provenance": {
            "transport_provider": "OpenAQ",
            "hardware_provider": "AirGradient",
            "hardware_model": "AirGradient ONE Generation 9",
            "owner": "Manila Observatory",
            "direct_airgradient_api_capture": False,
            "regulatory_monitor_conformance_claimed": False,
        },
    }
