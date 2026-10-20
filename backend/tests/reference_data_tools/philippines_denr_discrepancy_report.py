from __future__ import annotations

"""Compare independent Philippine candidates with production observations."""

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any

try:
    from .source_facts import sha256_file
except ImportError:  # Direct script execution keeps the tools usable without installation.
    from source_facts import sha256_file


ALLOWED_CLASSIFICATIONS = (
    "match",
    "numeric_difference",
    "category_difference",
    "availability_difference",
    "coverage_difference",
    "reason_difference",
    "methodology_difference",
)

def _decimal_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except InvalidOperation:
        return False


def _candidate_case_id(case: dict[str, Any]) -> str:
    provider = "openaq" if case["sensor_ref"].startswith("openaq-") else "purpleair"
    return (
        f"{provider}_{case['parameter_code']}_completed_"
        f"{case['represented_local_date'].replace('-', '_')}"
    )


def _candidate_summary(
    case: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    eligibility = case["eligibility_status"]
    return {
        "case_id": _candidate_case_id(case),
        "methodology_code": candidate["methodology_code"],
        "methodology_version": candidate["methodology_version"],
        "sensor_ref": case["sensor_ref"],
        "parameter_code": case["parameter_code"],
        "product_code": (
            f"philippines_denr.{case['parameter_code']}.completed_day"
        ),
        "represented_local_date": case["represented_local_date"],
        "utc_window_started_at": case["utc_window_started_at"],
        "utc_window_ended_at": case["utc_window_ended_at"],
        "expected_hour_count": 24,
        "valid_hour_count": case["valid_hour_count"],
        "required_valid_hour_count": 18,
        "block_valid_hour_counts": case["block_valid_hour_counts"],
        "maximum_consecutive_missing_hours": case[
            "maximum_consecutive_missing_hours"
        ],
        "normalized_concentration": case.get("normalized_concentration"),
        "preprocessed_concentration": case.get("preprocessed_concentration"),
        "numeric_value": case.get("numeric_value"),
        "category_code": case.get("category_code"),
        "availability": "available" if eligibility == "eligible" else "unavailable",
        "calculation_status": case.get("calculation_status"),
        "eligibility_status": eligibility,
        "coverage_status": "complete" if eligibility == "eligible" else "none",
        "exclusion_reason": case.get("exclusion_reason"),
    }


def _implementation_summary(
    observation: dict[str, Any],
    implementation: dict[str, Any],
) -> dict[str, Any]:
    counts = observation["qualified_observation_counts"]
    concentration = observation["concentration_result"]
    result = observation["aqi_result"]
    return {
        "case_id": observation["case_id"],
        "methodology_code": implementation["methodology_code"],
        "methodology_version": implementation["methodology_version"],
        "sensor_ref": observation["sensor_ref"],
        "parameter_code": observation["parameter_code"],
        "product_code": observation["product_code"],
        "represented_local_date": observation["represented_local_date"],
        "utc_window_started_at": observation["utc_window_started_at"],
        "utc_window_ended_at": observation["utc_window_ended_at"],
        "expected_hour_count": counts["expected_hour_count"],
        "valid_hour_count": counts["valid_hour_count"],
        "required_valid_hour_count": counts["required_valid_hour_count"],
        "block_valid_hour_counts": counts["block_valid_hour_counts"],
        "maximum_consecutive_missing_hours": counts[
            "maximum_consecutive_missing_hours"
        ],
        "normalized_concentration": concentration["normalized_concentration"],
        "preprocessed_concentration": concentration[
            "preprocessed_concentration"
        ],
        "numeric_value": result["numeric_value"],
        "category_code": result["category_code"],
        "availability": result["availability"],
        "calculation_status": result["calculation_status"],
        "eligibility_status": result["eligibility_status"],
        "coverage_status": result["coverage_status"],
        "exclusion_reason": result["exclusion_reason"],
    }


def _classifications(
    candidate: dict[str, Any], implementation: dict[str, Any]
) -> tuple[list[str], list[str]]:
    differing_fields: list[str] = []
    classifications: list[str] = []

    numeric_fields = (
        "normalized_concentration",
        "preprocessed_concentration",
        "numeric_value",
    )
    for field in numeric_fields:
        if not _decimal_equal(candidate[field], implementation[field]):
            differing_fields.append(field)
    if any(field in differing_fields for field in numeric_fields):
        classifications.append("numeric_difference")

    if candidate["category_code"] != implementation["category_code"]:
        differing_fields.append("category_code")
        classifications.append("category_difference")

    availability_fields = (
        "availability",
        "calculation_status",
        "eligibility_status",
    )
    for field in availability_fields:
        if candidate[field] != implementation[field]:
            differing_fields.append(field)
    if any(field in differing_fields for field in availability_fields):
        classifications.append("availability_difference")

    coverage_fields = (
        "expected_hour_count",
        "valid_hour_count",
        "required_valid_hour_count",
        "block_valid_hour_counts",
        "maximum_consecutive_missing_hours",
        "coverage_status",
    )
    for field in coverage_fields:
        if candidate[field] != implementation[field]:
            differing_fields.append(field)
    if any(field in differing_fields for field in coverage_fields):
        classifications.append("coverage_difference")

    if candidate["exclusion_reason"] != implementation["exclusion_reason"]:
        differing_fields.append("exclusion_reason")
        classifications.append("reason_difference")

    methodology_fields = (
        "methodology_code",
        "methodology_version",
        "parameter_code",
        "product_code",
        "represented_local_date",
        "utc_window_started_at",
        "utc_window_ended_at",
    )
    for field in methodology_fields:
        if candidate[field] != implementation[field]:
            differing_fields.append(field)
    if any(field in differing_fields for field in methodology_fields):
        classifications.append("methodology_difference")

    if not classifications:
        classifications.append("match")
    return classifications, sorted(set(differing_fields))


def build_discrepancy_report(
    candidate_path: Path,
    implementation_path: Path,
) -> dict[str, Any]:
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    implementation = json.loads(
        implementation_path.read_text(encoding="utf-8")
    )
    observations = {
        observation["case_id"]: observation
        for observation in implementation["cases"]
    }
    cases = []
    for candidate_case in candidate["cases"]:
        candidate_summary = _candidate_summary(candidate_case, candidate)
        case_id = candidate_summary["case_id"]
        if case_id not in observations:
            raise ValueError(f"Implementation observation is missing {case_id}")
        implementation_summary = _implementation_summary(
            observations[case_id], implementation
        )
        classifications, differing_fields = _classifications(
            candidate_summary, implementation_summary
        )
        cases.append(
            {
                "case_id": case_id,
                "classifications": classifications,
                "differing_fields": differing_fields,
                "independent_candidate": candidate_summary,
                "implementation_observation": implementation_summary,
                "disposition": "not_required" if classifications == ["match"] else "pending_investigation",
            }
        )
    extra_observations = sorted(set(observations) - {case["case_id"] for case in cases})
    if extra_observations:
        raise ValueError(
            f"Implementation report contains unregistered cases: {extra_observations}"
        )
    discrepancy_cases = [
        case for case in cases if case["classifications"] != ["match"]
    ]
    return {
        "schema_version": "philippines-denr-discrepancy-report-1",
        "artifact_kind": "discrepancy_report",
        "oracle_status": "independent_candidate_unapproved",
        "candidate_sha256": sha256_file(candidate_path),
        "implementation_observations_sha256": sha256_file(implementation_path),
        "allowed_classifications": list(ALLOWED_CLASSIFICATIONS),
        "candidate_case_count": len(cases),
        "matching_case_count": len(cases) - len(discrepancy_cases),
        "discrepancy_case_count": len(discrepancy_cases),
        "cases": cases,
        "automatic_resolution_performed": False,
        "candidate_modified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("implementation_observations", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_discrepancy_report(
        args.candidate.resolve(), args.implementation_observations.resolve()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
