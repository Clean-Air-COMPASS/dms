"""Build a hash-linked approved bundle from an independently reviewed worksheet.

This tool performs only mechanical packaging. It never calculates an expected
result and never reads current CompassAQ observations or provider credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Iterable

try:
    from .promotion import EXPECTED_SCHEMA_VERSION, validate_approved_bundle
    from .source_facts import (
        DEFAULT_REFERENCE_ROOT,
        canonical_json_sha256,
        sha256_file,
    )
except ImportError:  # Direct execution from the repository root.
    from promotion import EXPECTED_SCHEMA_VERSION, validate_approved_bundle
    from source_facts import DEFAULT_REFERENCE_ROOT, canonical_json_sha256, sha256_file


class ApprovedBundleError(ValueError):
    """Raised when reviewed artifacts cannot be packaged without ambiguity."""


def _relative_artifact_name(path: Path, artifact_root: Path) -> str:
    try:
        return path.resolve().relative_to(artifact_root.resolve()).as_posix()
    except ValueError as exc:
        raise ApprovedBundleError(
            f"Reviewed artifact must remain inside {artifact_root}: {path}"
        ) from exc


def _sensor_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        sensor_ref = value.get("sensor_ref")
        if sensor_ref:
            refs.add(str(sensor_ref))
        for child in value.values():
            refs.update(_sensor_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_sensor_refs(child))
    return refs


def _source(case: dict[str, Any], worksheet: dict[str, Any]) -> dict[str, Any]:
    facts = case["source_facts"]
    source = {
        "dataset_name": worksheet["dataset_name"],
        "dataset_id": worksheet["dataset_id"],
        "access_classification": worksheet["access_classification"],
        "source_fact_hash": case["source_fact_hash"],
        "sensor_refs": sorted(_sensor_refs(facts)),
    }
    for key in (
        "provider",
        "provider_chain",
        "origin",
        "fixture_role",
        "direct_airgradient_api_data",
    ):
        if key in facts:
            source[key] = facts[key]
    return source


def _input_window(facts: dict[str, Any]) -> dict[str, Any]:
    window = {
        key: facts[key]
        for key in (
            "utc_window",
            "represented_utc_window",
            "represented_local_date",
            "timezone",
            "window_ended_at",
            "observed_at",
            "boundary_semantics",
            "timestamp_semantics",
        )
        if key in facts
    }
    sensor_windows = []
    for sensor in facts.get("sensor_results", []):
        if not isinstance(sensor, dict) or "utc_window" not in sensor:
            continue
        sensor_windows.append(
            {
                "sensor_ref": sensor.get("sensor_ref"),
                "utc_window": sensor["utc_window"],
            }
        )
    if sensor_windows:
        window["sensor_windows"] = sensor_windows
    return window


def _approved_observation(observation: dict[str, Any]) -> dict[str, Any]:
    exclusion_reason = observation.get("exclusion_reason")
    return {
        "sensor_ref": str(observation["sensor_ref"]),
        "provider_observation_ref": observation.get("provider_observation_ref"),
        "source_page": observation.get("source_page"),
        "source_result_index": observation.get("source_result_index"),
        "provider_period": observation.get("provider_period"),
        "provider_timestamp": observation.get("provider_timestamp"),
        "is_valid": observation.get("is_valid"),
        "qc_flags": observation.get("qc_flags"),
        "qc_version": observation.get("qc_version"),
        "observed_at": observation["observed_at"],
        "value": str(observation["decimal_value"]),
        "unit": str(observation["unit"]),
        "assignment": "excluded" if exclusion_reason else "included",
        "assigned_anchor": observation.get("assigned_anchor"),
        "exclusion_reason": exclusion_reason,
    }


def _walk_completeness(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if {"numerator", "denominator", "required_count"}.issubset(value):
            yield value
        for child in value.values():
            yield from _walk_completeness(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_completeness(child)


def _count_component_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
    if "observed_count" not in result or "expected_count" not in result:
        return None
    return {
        "numerator": int(result["observed_count"]),
        "denominator": int(result["expected_count"]),
        "required_count": result.get("required_count"),
        "missing_positions": result.get("missing_interval_end_positions", []),
        "duplicate_positions": [],
        "off_frequency_positions": [],
        "status": result.get("coverage_status", "not_recorded"),
        "parameter_code": result.get("parameter_code"),
        "sensor_ref": result.get("sensor_ref"),
    }


def _completeness(
    case: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    components = [dict(value) for value in _walk_completeness(case["source_facts"])]
    if not components:
        components = [
            component
            for result in expected.get("results", [])
            if (component := _count_component_from_result(result)) is not None
        ]
    if not components and expected.get("result_kind") == "frozen_source_fact_summary":
        measurement_count = int(expected["expected_fields"]["measurement_count"])
        components = [
            {
                "numerator": measurement_count,
                "denominator": measurement_count,
                "required_count": measurement_count,
                "missing_positions": [],
                "duplicate_positions": [],
                "off_frequency_positions": [],
                "status": "complete",
            }
        ]
    if not components and expected.get("result_kind") == "eea_overall_category":
        available_count = len(expected.get("results", []))
        missing_count = len(expected.get("missing_pollutants", []))
        components = [
            {
                "numerator": available_count,
                "denominator": available_count + missing_count,
                "required_count": None,
                "missing_positions": expected.get("missing_pollutants", []),
                "duplicate_positions": [],
                "off_frequency_positions": [],
                "status": expected.get("coverage_status", "not_recorded"),
            }
        ]

    numerator = sum(int(component.get("numerator", 0)) for component in components)
    denominator = sum(int(component.get("denominator", 0)) for component in components)
    required_values = [
        int(component["required_count"])
        for component in components
        if component.get("required_count") is not None
    ]
    required_count = sum(required_values) if required_values else None
    missing_positions = sorted(
        {
            str(position)
            for component in components
            for position in component.get("missing_positions", [])
        }
    )
    duplicate_positions = sorted(
        {
            str(position)
            for component in components
            for position in component.get("duplicate_positions", [])
        }
    )
    off_frequency_positions = sorted(
        {
            str(position)
            for component in components
            for position in component.get("off_frequency_positions", [])
        }
    )
    fraction = str(Decimal(numerator) / Decimal(denominator)) if denominator else None
    return {
        "numerator": numerator,
        "denominator": denominator,
        "required_count": required_count,
        "fraction": fraction,
        "missing_positions": missing_positions,
        "duplicate_positions": duplicate_positions,
        "off_frequency_positions": off_frequency_positions,
        "status": expected.get("coverage_status") or "not_applicable",
        "components": components,
    }


def _approved_expected(candidate_expected: dict[str, Any]) -> dict[str, Any]:
    expected = dict(candidate_expected)
    expected.pop("status", None)
    return expected


def build_approved_candidate_bundle(
    *,
    worksheet_path: Path,
    source_facts_path: Path,
    artifact_root: Path,
    reviewer: str,
    reviewed_at: str,
    comments: str,
    reference_root: Path = DEFAULT_REFERENCE_ROOT,
) -> dict[str, Any]:
    reviewer = reviewer.strip()
    comments = comments.strip()
    if not reviewer:
        raise ApprovedBundleError("Reviewer identity is required")
    if not comments:
        raise ApprovedBundleError("Meaningful review comments are required")
    try:
        parsed_reviewed_at = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovedBundleError("Review timestamp is invalid") from exc
    if parsed_reviewed_at.tzinfo is None:
        raise ApprovedBundleError("Review timestamp must include a timezone")

    worksheet = json.loads(worksheet_path.read_text(encoding="utf-8"))
    source_facts = json.loads(source_facts_path.read_text(encoding="utf-8"))
    source_facts_hash = sha256_file(source_facts_path)
    if worksheet.get("artifact_kind") != "analyst_derivation_worksheet":
        raise ApprovedBundleError("Input is not an analyst derivation worksheet")
    if worksheet.get("source_facts_sha256") != source_facts_hash:
        raise ApprovedBundleError("Worksheet source-fact hash is stale")
    if source_facts.get("artifact_kind") != "independently_extracted_source_facts":
        raise ApprovedBundleError("Input is not an independent source-fact artifact")

    cases = []
    for worksheet_case in worksheet["cases"]:
        derivation = worksheet_case["derivation"]
        derivation_hash = canonical_json_sha256(derivation)
        if derivation_hash != worksheet_case.get("candidate_derivation_sha256"):
            raise ApprovedBundleError(
                f"Case {worksheet_case['case_id']} derivation hash is stale"
            )
        expected = _approved_expected(worksheet_case["candidate_expected"])
        cases.append(
            {
                "case_id": worksheet_case["case_id"],
                "calculation_type": worksheet_case["calculation_type"],
                "source": _source(worksheet_case, worksheet),
                "input_window": _input_window(worksheet_case["source_facts"]),
                "source_observations": [
                    _approved_observation(observation)
                    for observation in worksheet_case["source_observations"]
                ],
                "completeness": _completeness(worksheet_case, expected),
                "methodology": derivation["methodology"],
                "derivation": derivation,
                "expected": expected,
                "review": {
                    "status": "approved",
                    "reviewer": reviewer,
                    "reviewed_at": reviewed_at,
                    "derivation_sha256": derivation_hash,
                    "comments": comments,
                    "approval_decision": "approved",
                },
            }
        )

    bundle = {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "artifact_kind": "analyst_review_candidate",
        "dataset_name": worksheet["dataset_name"],
        "access_classification": worksheet["access_classification"],
        "dataset_id": worksheet["dataset_id"],
        "source_measurements_sha256": worksheet["source_measurements_sha256"],
        "source_facts_file": _relative_artifact_name(
            source_facts_path, artifact_root
        ),
        "source_facts_sha256": source_facts_hash,
        "worksheet_file": _relative_artifact_name(worksheet_path, artifact_root),
        "worksheet_sha256": sha256_file(worksheet_path),
        "cases": cases,
    }
    validate_approved_bundle(
        bundle,
        artifact_root=artifact_root,
        reference_root=reference_root,
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worksheet", required=True, type=Path)
    parser.add_argument("--source-facts", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--comments", required=True)
    parser.add_argument("--reference-root", type=Path, default=DEFAULT_REFERENCE_ROOT)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bundle = build_approved_candidate_bundle(
        worksheet_path=args.worksheet.resolve(),
        source_facts_path=args.source_facts.resolve(),
        artifact_root=args.artifact_root.resolve(),
        reviewer=args.reviewer,
        reviewed_at=args.reviewed_at,
        comments=args.comments,
        reference_root=args.reference_root.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
