"""Extract frozen reference facts without importing CompassAQ production code.

This module is intentionally limited to Python's standard library.  It reads the
frozen JSON artifacts as source evidence and performs only plainly documented
selection, clock-position assignment, and Decimal arithmetic.  Its output is a
candidate worksheet input, never an AQI expectation or approval decision.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


UTC = timezone.utc
SOURCE_FACT_SCHEMA_VERSION = "2i.5-source-facts-1"
DEFAULT_REGISTRY = Path(__file__).with_name("case_registry.json")
DEFAULT_REFERENCE_ROOT = Path(__file__).parents[1] / "fixtures" / "reference_data"


class SourceFactError(ValueError):
    """Raised when frozen evidence does not match its declared manifest."""


def _decimal_json_loads(text: str) -> Any:
    return json.loads(text, parse_float=Decimal)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SourceFactError(f"Timestamp must include a timezone: {value}")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    """Hash a text fixture with repository line endings normalized to LF.

    Reference artifacts are UTF-8 JSON or JSONL files. Their line-ending style
    is not scientific evidence, but every other byte remains significant so a
    content, encoding, formatting, or whitespace change still breaks the hash.
    """

    content = path.read_bytes()
    normalized_content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized_content).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        cls=DecimalJsonEncoder,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DecimalJsonEncoder(json.JSONEncoder):
    """Serialize Decimal values as their exact source text, not binary floats."""

    def default(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, datetime):
            return _iso(value)
        if isinstance(value, Path):
            return str(value)
        return super().default(value)


@dataclass(frozen=True)
class FrozenDataset:
    name: str
    root: Path
    manifest: dict[str, Any]
    measurements: tuple[dict[str, Any], ...]
    measurements_by_sensor: dict[str, tuple[dict[str, Any], ...]]
    manifest_sha256: str
    measurements_sha256: str


def read_frozen_dataset(name: str, fixture_root: Path) -> FrozenDataset:
    """Read and checksum one fixture using no CompassAQ loader or schema."""
    manifest_path = fixture_root / "manifest.json"
    if not manifest_path.is_file():
        raise SourceFactError(f"Missing manifest: {manifest_path}")
    manifest = _decimal_json_loads(manifest_path.read_text(encoding="utf-8"))
    measurements_path = fixture_root / str(manifest["measurements_file"])
    actual_measurements_sha256 = sha256_file(measurements_path)
    declared_sha256 = str(manifest["measurements_sha256"]).lower()
    if actual_measurements_sha256.lower() != declared_sha256:
        raise SourceFactError(
            f"Measurement checksum mismatch for {name}: declared "
            f"{declared_sha256}, actual {actual_measurements_sha256}"
        )

    sensor_refs = {str(sensor["fixture_ref"]) for sensor in manifest["sensors"]}
    expanded: list[dict[str, Any]] = []
    previous_timestamp: dict[str, datetime] = {}
    with measurements_path.open("r", encoding="utf-8") as measurement_file:
        for line_number, line in enumerate(measurement_file, start=1):
            if not line.strip():
                continue
            source_row = _decimal_json_loads(line)
            sensor_ref = str(source_row.get("sensor_ref", ""))
            if sensor_ref not in sensor_refs:
                raise SourceFactError(
                    f"Unknown sensor_ref {sensor_ref!r} at {measurements_path}:{line_number}"
                )
            repeat_count = int(source_row.get("repeat_count", 1))
            interval_seconds = int(source_row.get("interval_seconds", 0))
            first_observed_at = _utc(str(source_row["observed_at"]))
            for repeat_index in range(repeat_count):
                observed_at = first_observed_at + timedelta(
                    seconds=repeat_index * interval_seconds
                )
                if observed_at < previous_timestamp.get(sensor_ref, observed_at):
                    raise SourceFactError(
                        f"Rows for {sensor_ref} are not timestamp-sorted at line {line_number}"
                    )
                previous_timestamp[sensor_ref] = observed_at
                expanded_row = dict(source_row)
                expanded_row["observed_at"] = _iso(observed_at)
                expanded_row.pop("repeat_count", None)
                expanded_row.pop("interval_seconds", None)
                expanded_row["source_line"] = line_number
                if repeat_count > 1:
                    expanded_row["source_repeat_index"] = repeat_index
                expanded.append(expanded_row)

    by_sensor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for measurement in expanded:
        by_sensor[str(measurement["sensor_ref"])].append(measurement)
    return FrozenDataset(
        name=name,
        root=fixture_root,
        manifest=manifest,
        measurements=tuple(expanded),
        measurements_by_sensor={
            sensor_ref: tuple(rows) for sensor_ref, rows in by_sensor.items()
        },
        manifest_sha256=sha256_file(manifest_path),
        measurements_sha256=actual_measurements_sha256,
    )


def _measurement_fact(
    measurement: dict[str, Any],
    *,
    assigned_anchor: datetime | None = None,
    exclusion_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "sensor_ref": measurement["sensor_ref"],
        "observed_at": measurement["observed_at"],
        "decimal_value": str(measurement["value"]),
        "unit": measurement.get("provider_parameter", {}).get("units"),
        "provider_observation_ref": measurement.get("provider_observation_ref"),
        "source_page": measurement.get("source_page"),
        "source_result_index": measurement.get("source_result_index"),
        "provider_timestamp": measurement.get("provider_timestamp"),
        "provider_period": measurement.get("provider_period"),
        "is_valid": measurement.get("is_valid"),
        "qc_flags": measurement.get("qc_flags"),
        "qc_version": measurement.get("qc_version"),
        "assigned_anchor": _iso(assigned_anchor) if assigned_anchor else None,
        "exclusion_reason": exclusion_reason,
    }


def _fixture_summary(dataset: FrozenDataset) -> dict[str, Any]:
    manifest = dataset.manifest
    rows_by_sensor = Counter(row["sensor_ref"] for row in dataset.measurements)
    sensor_summaries = []
    for sensor in manifest["sensors"]:
        sensor_ref = str(sensor["fixture_ref"])
        rows = dataset.measurements_by_sensor.get(sensor_ref, ())
        sensor_summaries.append(
            {
                "sensor_ref": sensor_ref,
                "device_ref": sensor.get("device_ref"),
                "parameter_code": sensor.get("parameter_code"),
                "provider_unit": sensor.get("provider_unit"),
                "aggregation_period_code": sensor.get("aggregation_period_code"),
                "expected_frequency_seconds": sensor.get("expected_frequency_seconds"),
                "measurement_duration_seconds": sensor.get("measurement_duration_seconds"),
                "source_aggregation_duration_seconds": sensor.get(
                    "source_aggregation_duration_seconds"
                ),
                "measurement_timestamp_semantics": sensor.get(
                    "measurement_timestamp_semantics"
                ),
                "measurement_metadata_status": sensor.get(
                    "measurement_metadata_status"
                ),
                "temporal_qualification": sensor.get("temporal_qualification"),
                "measurement_count": rows_by_sensor[sensor_ref],
                "observed_first": rows[0]["observed_at"] if rows else None,
                "observed_last": rows[-1]["observed_at"] if rows else None,
            }
        )
    validity = Counter(str(row.get("is_valid")) for row in dataset.measurements)
    provider_flag_values = Counter(
        str(row.get("provider_flag_info", {}).get("hasFlags"))
        for row in dataset.measurements
        if "provider_flag_info" in row
    )
    provider_validity_values = Counter(
        str(row.get("qc_flags", {}).get("provider_validity_status"))
        for row in dataset.measurements
        if "provider_validity_status" in row.get("qc_flags", {})
    )
    return {
        "dataset_id": manifest["dataset_id"],
        "access_classification": manifest["access_classification"],
        "provider": manifest["provider"],
        "provider_chain": manifest.get("provider_chain"),
        "manifest_sha256": dataset.manifest_sha256,
        "measurements_sha256": dataset.measurements_sha256,
        "measurement_count": len(dataset.measurements),
        "device_count": len(manifest["devices"]),
        "sensor_count": len(manifest["sensors"]),
        "active_sensor_count": sum(summary["measurement_count"] > 0 for summary in sensor_summaries),
        "validity_counts": dict(sorted(validity.items())),
        "provider_has_flags_counts": dict(sorted(provider_flag_values.items())),
        "provider_validity_status_counts": dict(sorted(provider_validity_values.items())),
        "sensors": sensor_summaries,
    }


def _device_provenance(dataset: FrozenDataset, case: dict[str, Any]) -> dict[str, Any]:
    device_ref = case["device_ref"]
    device = next(
        (item for item in dataset.manifest["devices"] if item["fixture_ref"] == device_ref),
        None,
    )
    if device is None:
        raise SourceFactError(f"Unknown device_ref {device_ref}")
    return {
        "device": device,
        "provider": dataset.manifest.get("provider"),
        "provider_chain": dataset.manifest.get("provider_chain"),
        "origin": dataset.manifest.get("origin"),
        "fixture_role": "CompassAQ frozen fixture",
        "direct_airgradient_api_data": False,
    }


def _rows_for_sensor(
    dataset: FrozenDataset,
    sensor_ref: str,
    *,
    started_at: datetime,
    ended_at: datetime,
    start_inclusive: bool,
    end_inclusive: bool,
) -> list[dict[str, Any]]:
    selected = []
    for row in dataset.measurements_by_sensor.get(sensor_ref, ()):
        observed_at = _utc(str(row["observed_at"]))
        starts = observed_at >= started_at if start_inclusive else observed_at > started_at
        ends = observed_at <= ended_at if end_inclusive else observed_at < ended_at
        if starts and ends:
            selected.append(row)
    return selected


def _ordinary_aggregation(dataset: FrozenDataset, case: dict[str, Any]) -> dict[str, Any]:
    started_at = _utc(case["interval_started_at"])
    ended_at = _utc(case["interval_ended_at"])
    sensor_results = []
    for sensor_ref in case["sensor_refs"]:
        rows = _rows_for_sensor(
            dataset,
            sensor_ref,
            started_at=started_at,
            ended_at=ended_at,
            start_inclusive=True,
            end_inclusive=False,
        )
        values = [Decimal(str(row["value"])) for row in rows]
        arithmetic_mean = sum(values, Decimal("0")) / Decimal(len(values)) if values else None
        sensor_results.append(
            {
                "sensor_ref": sensor_ref,
                "included_observations": [_measurement_fact(row) for row in rows],
                "included_count": len(rows),
                "arithmetic": {
                    "operation": "sum(values) / count",
                    "operands": [str(value) for value in values],
                    "sum": str(sum(values, Decimal("0"))),
                    "divisor": str(len(values)),
                    "unformatted_mean": str(arithmetic_mean) if arithmetic_mean is not None else None,
                },
            }
        )
    return {
        "utc_window": {"started_at": _iso(started_at), "ended_at": _iso(ended_at)},
        "boundary_semantics": case["boundary_semantics"],
        "sensor_results": sensor_results,
    }


def _expected_anchors(
    interval_started_at: datetime,
    expected_frequency_seconds: int,
    expected_count: int,
) -> tuple[datetime, ...]:
    frequency = timedelta(seconds=expected_frequency_seconds)
    return tuple(
        interval_started_at + frequency * (position + 1)
        for position in range(expected_count)
    )


def _anchored_sensor_hour(
    dataset: FrozenDataset,
    *,
    sensor_ref: str,
    interval_started_at: datetime,
    expected_frequency_seconds: int,
    required_completeness: Decimal,
) -> dict[str, Any]:
    interval_ended_at = interval_started_at + timedelta(hours=1)
    expected_count = 3600 // expected_frequency_seconds
    required_count = int(
        (Decimal(expected_count) * required_completeness).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    anchors = _expected_anchors(
        interval_started_at, expected_frequency_seconds, expected_count
    )
    rows = _rows_for_sensor(
        dataset,
        sensor_ref,
        started_at=interval_started_at,
        ended_at=interval_ended_at,
        start_inclusive=True,
        end_inclusive=True,
    )
    maximum_distance = Decimal(expected_frequency_seconds) / Decimal(2)
    candidates: dict[int, list[tuple[Decimal, datetime, str, dict[str, Any]]]] = defaultdict(list)
    excluded: list[dict[str, Any]] = []
    for row in rows:
        observed_at = _utc(str(row["observed_at"]))
        distances = tuple(
            Decimal(str(abs((observed_at - anchor).total_seconds())))
            for anchor in anchors
        )
        nearest_position = min(
            range(len(anchors)), key=lambda position: (distances[position], position)
        )
        if distances[nearest_position] > maximum_distance:
            excluded.append(_measurement_fact(row, exclusion_reason="off_frequency"))
            continue
        candidates[nearest_position].append(
            (
                distances[nearest_position],
                observed_at,
                str(row.get("provider_observation_ref", "")),
                row,
            )
        )

    accepted: list[dict[str, Any]] = []
    duplicate_positions: list[str] = []
    for position in sorted(candidates):
        ordered = sorted(candidates[position], key=lambda item: (item[0], item[1], item[2]))
        accepted.append(_measurement_fact(ordered[0][3], assigned_anchor=anchors[position]))
        for duplicate in ordered[1:]:
            excluded.append(
                _measurement_fact(
                    duplicate[3],
                    assigned_anchor=anchors[position],
                    exclusion_reason="duplicate_anchor_candidate",
                )
            )
            duplicate_positions.append(_iso(anchors[position]))

    assigned_anchors = {item["assigned_anchor"] for item in accepted}
    missing_positions = [_iso(anchor) for anchor in anchors if _iso(anchor) not in assigned_anchors]
    values = [Decimal(item["decimal_value"]) for item in accepted]
    mean = sum(values, Decimal("0")) / Decimal(len(values)) if values else None
    accepted_count = len(accepted)
    return {
        "sensor_ref": sensor_ref,
        "utc_window": {
            "started_at": _iso(interval_started_at),
            "ended_at": _iso(interval_ended_at),
        },
        "boundary_semantics": "start_inclusive_end_inclusive_for_anchor_assignment",
        "expected_frequency_seconds": expected_frequency_seconds,
        "accepted_observations": accepted,
        "excluded_observations": sorted(
            excluded, key=lambda item: (item["observed_at"], item["provider_observation_ref"] or "")
        ),
        "completeness": {
            "numerator": accepted_count,
            "denominator": expected_count,
            "required_count": required_count,
            "required_fraction": str(required_completeness),
            "fraction": str(Decimal(accepted_count) / Decimal(expected_count)),
            "missing_positions": missing_positions,
            "duplicate_positions": sorted(duplicate_positions),
            "off_frequency_positions": [
                item["observed_at"]
                for item in excluded
                if item["exclusion_reason"] == "off_frequency"
            ],
            "coverage_status": "eligible" if accepted_count >= required_count else "incomplete_coverage",
        },
        "arithmetic": {
            "operation": "sum(accepted values) / accepted count",
            "operands": [str(value) for value in values],
            "sum": str(sum(values, Decimal("0"))),
            "divisor": str(accepted_count),
            "unformatted_mean": str(mean) if mean is not None else None,
        },
    }


def _anchored_hour(dataset: FrozenDataset, case: dict[str, Any]) -> dict[str, Any]:
    started_at = _utc(case["interval_started_at"])
    return {
        "timestamp_semantics": case["timestamp_semantics"],
        "sensor_results": [
            _anchored_sensor_hour(
                dataset,
                sensor_ref=sensor_ref,
                interval_started_at=started_at,
                expected_frequency_seconds=int(case["expected_frequency_seconds"]),
                required_completeness=Decimal(str(case["required_completeness"])),
            )
            for sensor_ref in case["sensor_refs"]
        ],
    }


def _anchored_window(dataset: FrozenDataset, case: dict[str, Any]) -> dict[str, Any]:
    ended_at = _utc(case["window_ended_at"])
    hours = []
    for position in range(int(case["hour_count"])):
        hour_ended_at = ended_at - timedelta(hours=position)
        hour_started_at = hour_ended_at - timedelta(hours=1)
        hours.append(
            {
                "most_recent_first_position": position,
                "hour_ended_at": _iso(hour_ended_at),
                "sensor_results": [
                    _anchored_sensor_hour(
                        dataset,
                        sensor_ref=sensor_ref,
                        interval_started_at=hour_started_at,
                        expected_frequency_seconds=int(case["expected_frequency_seconds"]),
                        required_completeness=Decimal(str(case["required_completeness"])),
                    )
                    for sensor_ref in case["sensor_refs"]
                ],
            }
        )
    return {"window_ended_at": _iso(ended_at), "hours_most_recent_first": hours}


def _local_day_bounds(local_date_text: str, timezone_name: str) -> tuple[datetime, datetime]:
    local_date = date.fromisoformat(local_date_text)
    local_zone = ZoneInfo(timezone_name)
    local_start = datetime.combine(local_date, datetime.min.time(), tzinfo=local_zone)
    local_end = datetime.combine(local_date + timedelta(days=1), datetime.min.time(), tzinfo=local_zone)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def _anchored_local_day(dataset: FrozenDataset, case: dict[str, Any]) -> dict[str, Any]:
    utc_start, utc_end = _local_day_bounds(case["represented_local_date"], case["timezone"])
    hour_count = int((utc_end - utc_start).total_seconds() // 3600)
    hours = []
    for hour_index in range(hour_count):
        started_at = utc_start + timedelta(hours=hour_index)
        hours.append(
            {
                "hour_position": hour_index,
                "sensor_results": [
                    _anchored_sensor_hour(
                        dataset,
                        sensor_ref=sensor_ref,
                        interval_started_at=started_at,
                        expected_frequency_seconds=int(case["expected_frequency_seconds"]),
                        required_completeness=Decimal(str(case["required_completeness"])),
                    )
                    for sensor_ref in case["sensor_refs"]
                ],
            }
        )
    return {
        "represented_local_date": case["represented_local_date"],
        "timezone": case["timezone"],
        "utc_window": {"started_at": _iso(utc_start), "ended_at": _iso(utc_end)},
        "hours": hours,
    }


def _provider_window(
    dataset: FrozenDataset,
    *,
    sensor_refs: Iterable[str],
    started_at: datetime,
    ended_at: datetime,
    expected_hour_count: int,
) -> dict[str, Any]:
    expected_end_positions = tuple(
        started_at + timedelta(hours=position + 1)
        for position in range(expected_hour_count)
    )
    results = []
    for sensor_ref in sensor_refs:
        rows = _rows_for_sensor(
            dataset,
            sensor_ref,
            started_at=started_at,
            ended_at=ended_at,
            start_inclusive=False,
            end_inclusive=True,
        )
        found = {_utc(str(row["observed_at"])) for row in rows}
        results.append(
            {
                "sensor_ref": sensor_ref,
                "accepted_observations": [_measurement_fact(row) for row in rows],
                "observed_count": len(rows),
                "expected_count": expected_hour_count,
                "missing_interval_end_positions": [
                    _iso(position) for position in expected_end_positions if position not in found
                ],
            }
        )
    return {
        "utc_window": {"started_at": _iso(started_at), "ended_at": _iso(ended_at)},
        "boundary_semantics": "start_exclusive_end_inclusive",
        "sensor_results": results,
    }


def _provider_local_day(dataset: FrozenDataset, case: dict[str, Any]) -> dict[str, Any]:
    utc_start, utc_end = _local_day_bounds(case["represented_local_date"], case["timezone"])
    result = _provider_window(
        dataset,
        sensor_refs=case["sensor_refs"],
        started_at=utc_start,
        ended_at=utc_end,
        expected_hour_count=int((utc_end - utc_start).total_seconds() // 3600),
    )
    result["represented_local_date"] = case["represented_local_date"]
    result["timezone"] = case["timezone"]
    return result


def _provider_hour_window(dataset: FrozenDataset, case: dict[str, Any]) -> dict[str, Any]:
    ended_at = _utc(case["window_ended_at"])
    hour_count = int(case["hour_count"])
    return _provider_window(
        dataset,
        sensor_refs=case["sensor_refs"],
        started_at=ended_at - timedelta(hours=hour_count),
        ended_at=ended_at,
        expected_hour_count=hour_count,
    )


def _source_rows_at_timestamp(dataset: FrozenDataset, case: dict[str, Any]) -> dict[str, Any]:
    observed_at = _utc(case["observed_at"])
    return {
        "observed_at": _iso(observed_at),
        "expected_unavailability_reason": case["expected_reason"],
        "sensor_results": [
            {
                "sensor_ref": sensor_ref,
                "observations": [
                    _measurement_fact(row)
                    for row in dataset.measurements_by_sensor.get(sensor_ref, ())
                    if _utc(str(row["observed_at"])) == observed_at
                ],
            }
            for sensor_ref in case["sensor_refs"]
        ],
    }


def _represented_hour(dataset: FrozenDataset, case: dict[str, Any]) -> dict[str, Any]:
    started_at = _utc(case["interval_started_at"])
    ended_at = _utc(case["interval_ended_at"])
    return {
        "represented_utc_window": {"started_at": _iso(started_at), "ended_at": _iso(ended_at)},
        "timestamp_semantics": case["timestamp_semantics"],
        "sensor_results": [
            {
                "sensor_ref": sensor_ref,
                "observations": [
                    _measurement_fact(row)
                    for row in dataset.measurements_by_sensor.get(sensor_ref, ())
                    if _utc(str(row["observed_at"])) == ended_at
                ],
            }
            for sensor_ref in case["sensor_refs"]
        ],
    }


def _zero_row_sensors(
    datasets: dict[str, FrozenDataset], case: dict[str, Any]
) -> dict[str, Any]:
    results = []
    for dataset_name, sensor_refs in case["datasets_and_sensor_refs"].items():
        dataset = datasets.get(dataset_name)
        if dataset is None:
            results.append({"dataset": dataset_name, "availability": "dataset_absent"})
            continue
        for sensor_ref in sensor_refs:
            results.append(
                {
                    "dataset": dataset_name,
                    "sensor_ref": sensor_ref,
                    "measurement_count": len(dataset.measurements_by_sensor.get(sensor_ref, ())),
                    "availability": "unavailable_no_measurements",
                }
            )
    return {"sensor_results": results}


CASE_EXTRACTORS = {
    "fixture_summary": lambda datasets, dataset, case: _fixture_summary(dataset),
    "device_provenance": lambda datasets, dataset, case: _device_provenance(dataset, case),
    "ordinary_aggregation": lambda datasets, dataset, case: _ordinary_aggregation(dataset, case),
    "anchored_hour": lambda datasets, dataset, case: _anchored_hour(dataset, case),
    "anchored_window": lambda datasets, dataset, case: _anchored_window(dataset, case),
    "anchored_local_day": lambda datasets, dataset, case: _anchored_local_day(dataset, case),
    "provider_local_day": lambda datasets, dataset, case: _provider_local_day(dataset, case),
    "provider_hour_window": lambda datasets, dataset, case: _provider_hour_window(dataset, case),
    "source_rows_at_timestamp": lambda datasets, dataset, case: _source_rows_at_timestamp(dataset, case),
    "represented_hour": lambda datasets, dataset, case: _represented_hour(dataset, case),
    "zero_row_sensors": lambda datasets, dataset, case: _zero_row_sensors(datasets, case),
}


def extract_source_facts(
    reference_root: Path = DEFAULT_REFERENCE_ROOT,
    registry_path: Path = DEFAULT_REGISTRY,
    *,
    dataset_roots: dict[str, Path] | None = None,
) -> dict[str, Any]:
    registry = _decimal_json_loads(registry_path.read_text(encoding="utf-8"))
    resolved_roots = dict(dataset_roots or {})
    datasets: dict[str, FrozenDataset] = {}
    absent_datasets: list[str] = []
    for dataset_name, definition in registry["datasets"].items():
        fixture_root = resolved_roots.get(dataset_name)
        if fixture_root is None and dataset_name == "purpleair":
            configured_private_root = os.getenv(
                "COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT", ""
            ).strip()
            configured_path = (
                Path(configured_private_root).expanduser().resolve()
                if configured_private_root
                else None
            )
            if configured_path is not None and configured_path.is_dir():
                fixture_root = configured_path
        if fixture_root is None:
            fixture_root = reference_root / definition["fixture_relative_path"]
        if not fixture_root.is_dir():
            if dataset_name == "purpleair" and os.getenv(
                "REQUIRE_RESTRICTED_REFERENCE_DATA", "false"
            ).strip().lower() in {"1", "true", "yes", "on"}:
                raise SourceFactError(
                    "Restricted reference data is required but neither the configured "
                    "private root nor the checked-in root is available"
                )
            absent_datasets.append(dataset_name)
            continue
        dataset = read_frozen_dataset(dataset_name, fixture_root)
        if dataset.manifest["dataset_id"] != definition["expected_dataset_id"]:
            raise SourceFactError(
                f"Unexpected dataset_id for {dataset_name}: {dataset.manifest['dataset_id']}"
            )
        datasets[dataset_name] = dataset

    case_results = []
    for case in registry["cases"]:
        dataset_name = case.get("dataset")
        if dataset_name is not None and dataset_name not in datasets:
            case_results.append(
                {
                    "case_id": case["case_id"],
                    "case_type": case["case_type"],
                    "dataset": dataset_name,
                    "extraction_status": "dataset_absent",
                }
            )
            continue
        extractor = CASE_EXTRACTORS.get(case["case_type"])
        if extractor is None:
            raise SourceFactError(f"Unsupported case_type {case['case_type']}")
        facts = extractor(datasets, datasets.get(dataset_name), case)
        case_result = {
            "case_id": case["case_id"],
            "case_type": case["case_type"],
            "dataset": dataset_name,
            "extraction_status": "extracted",
            "facts": facts,
        }
        case_result["source_fact_hash"] = canonical_json_sha256(case_result)
        case_results.append(case_result)

    return {
        "schema_version": SOURCE_FACT_SCHEMA_VERSION,
        "artifact_kind": "independently_extracted_source_facts",
        "oracle_status": "source_evidence_only_not_expected_results",
        "extractor_constraints": {
            "production_imports": False,
            "provider_calls": False,
            "credential_reads": False,
            "arithmetic": "decimal_strings",
        },
        "registry_sha256": sha256_file(registry_path),
        "datasets": {
            name: {
                "dataset_id": dataset.manifest["dataset_id"],
                "access_classification": dataset.manifest["access_classification"],
                "manifest_sha256": dataset.manifest_sha256,
                "measurements_sha256": dataset.measurements_sha256,
            }
            for name, dataset in sorted(datasets.items())
        },
        "absent_datasets": absent_datasets,
        "cases": case_results,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, cls=DecimalJsonEncoder, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, default=DEFAULT_REFERENCE_ROOT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--openaq-root", type=Path)
    parser.add_argument("--purpleair-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    roots = {
        name: root.resolve()
        for name, root in {
            "openaq": args.openaq_root,
            "purpleair": args.purpleair_root,
        }.items()
        if root is not None
    }
    result = extract_source_facts(
        args.reference_root.resolve(), args.registry.resolve(), dataset_roots=roots
    )
    if args.output:
        write_json(args.output.resolve(), result)
    else:
        print(json.dumps(result, cls=DecimalJsonEncoder, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
