from __future__ import annotations

"""Compare independent synthetic Philippine cases with production observations."""

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

NUMERIC_FIELDS = {
    "normalized_concentration",
    "preprocessed_concentration",
    "numeric_value",
}
CATEGORY_FIELDS = {"category_code", "category_label", "category_color"}
AVAILABILITY_FIELDS = {
    "calculation_status",
    "eligibility_status",
    "aqi_scale_status",
}
COVERAGE_FIELDS = {
    "coverage_status",
    "expected_hour_count",
    "valid_hour_count",
    "required_valid_hour_count",
    "block_valid_hour_counts",
    "maximum_consecutive_missing_hours",
    "selected_sensor_id",
    "selected_sensor_reason",
}
REASON_FIELDS = {"exclusion_reason"}
METHODOLOGY_FIELDS = {"normalized_unit"}

def _values_equal(field: str, left: Any, right: Any) -> bool:
    if field not in NUMERIC_FIELDS:
        return left == right
    if left is None or right is None:
        return left is right
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except InvalidOperation:
        return False


def _classify_field(field: str) -> str:
    if field in NUMERIC_FIELDS:
        return "numeric_difference"
    if field in CATEGORY_FIELDS:
        return "category_difference"
    if field in AVAILABILITY_FIELDS:
        return "availability_difference"
    if field in COVERAGE_FIELDS:
        return "coverage_difference"
    if field in REASON_FIELDS:
        return "reason_difference"
    return "methodology_difference"


def _compare_results(
    candidate: dict[str, Any], implementation: dict[str, Any]
) -> tuple[list[str], list[str]]:
    differing_fields = [
        field
        for field in sorted(set(candidate) | set(implementation))
        if not _values_equal(field, candidate.get(field), implementation.get(field))
    ]
    if not differing_fields:
        return ["match"], []
    classifications = sorted({_classify_field(field) for field in differing_fields})
    return classifications, differing_fields


def build_synthetic_discrepancy_report(
    candidate_path: Path,
    implementation_path: Path,
) -> dict[str, Any]:
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    implementation = json.loads(implementation_path.read_text(encoding="utf-8"))
    observations = {
        observation["case_id"]: observation
        for observation in implementation["synthetic_cases"]
    }
    cases: list[dict[str, Any]] = []
    for candidate_case in candidate["cases"]:
        case_id = candidate_case["case_id"]
        observation = observations.pop(case_id, None)
        if observation is None:
            raise ValueError(f"Production observation is missing {case_id}")
        candidate_result = candidate_case["independent_result"]
        production_result = observation["production_result"]
        classifications, differing_fields = _compare_results(
            candidate_result, production_result
        )
        cases.append(
            {
                "case_id": case_id,
                "case_kind": candidate_case["case_kind"],
                "parameter_code": candidate_case["parameter_code"],
                "component_code": candidate_case["component_code"],
                "classifications": classifications,
                "differing_fields": differing_fields,
                "independent_candidate": candidate_result,
                "implementation_observation": production_result,
                "disposition": (
                    "not_required"
                    if classifications == ["match"]
                    else "pending_investigation"
                ),
            }
        )
    if observations:
        raise ValueError(
            "Production report contains unregistered synthetic cases: "
            f"{sorted(observations)}"
        )
    discrepancies = [case for case in cases if case["classifications"] != ["match"]]
    return {
        "schema_version": "philippines-denr-synthetic-discrepancy-report-1",
        "artifact_kind": "synthetic_discrepancy_report",
        "oracle_status": "independent_candidates_unapproved",
        "candidate_sha256": sha256_file(candidate_path),
        "implementation_observations_sha256": sha256_file(implementation_path),
        "allowed_classifications": list(ALLOWED_CLASSIFICATIONS),
        "candidate_case_count": len(cases),
        "matching_case_count": len(cases) - len(discrepancies),
        "discrepancy_case_count": len(discrepancies),
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
    report = build_synthetic_discrepancy_report(
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
