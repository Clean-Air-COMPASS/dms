from __future__ import annotations

"""Mechanically package analyst-approved Philippine AQI candidates.

Expected results are copied only from the production-free real and synthetic
candidate artifacts. Production observations are retained in the approved
review package for audit context but are never read while building expectations.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

try:
    from .promotion import (
        PHILIPPINES_EXPECTED_SCHEMA_VERSION,
        validate_approved_bundle,
    )
    from .source_facts import canonical_json_sha256, sha256_file
except ImportError:  # Direct execution from the repository root.
    from promotion import (
        PHILIPPINES_EXPECTED_SCHEMA_VERSION,
        validate_approved_bundle,
    )
    from source_facts import canonical_json_sha256, sha256_file


class PhilippineApprovedBundleError(ValueError):
    """Raised when approval cannot be applied without ambiguity."""


REFERENCE_IDS = [
    "denr_dao_2000_81",
    "denr_dao_2020_14",
    "emb_mc_2021_07",
    "denr_mc_2005_013",
]


def _relative_artifact_name(path: Path, artifact_root: Path) -> str:
    try:
        return path.resolve().relative_to(artifact_root.resolve()).as_posix()
    except ValueError as exc:
        raise PhilippineApprovedBundleError(
            f"Reviewed artifact must remain inside {artifact_root}: {path}"
        ) from exc


def _real_case_id(case: dict[str, Any]) -> str:
    sensor_ref = str(case["sensor_ref"])
    provider = "openaq" if sensor_ref.startswith("openaq-") else "purpleair"
    represented_date = case["represented_local_date"].replace("-", "_")
    return (
        f"{provider}_{case['parameter_code']}_completed_{represented_date}"
    )


def _artifact_binding(path: Path, artifact_root: Path) -> dict[str, str]:
    return {
        "file": _relative_artifact_name(path, artifact_root),
        "sha256": sha256_file(path),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PhilippineApprovedBundleError(f"Artifact must be an object: {path}")
    return value


def _approval_from_record(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("artifact_kind") != "analyst_approval_record":
        raise PhilippineApprovedBundleError("Approval input has an unexpected kind")
    if record.get("decision") != "approved":
        raise PhilippineApprovedBundleError(
            "Only an explicit approved decision can be promoted"
        )
    for field in ("reviewer_identity", "reviewed_at", "comments"):
        if not str(record.get(field) or "").strip():
            raise PhilippineApprovedBundleError(
                f"Approval record requires {field}"
            )
    if not isinstance(record.get("exceptions"), list):
        raise PhilippineApprovedBundleError("Approval exceptions must be an array")
    return {
        "status": "approved",
        "reviewer_identity": record["reviewer_identity"],
        "reviewed_at": record["reviewed_at"],
        "decision": record["decision"],
        "comments": record["comments"],
        "exceptions": record["exceptions"],
    }


def build_approved_review_package(
    pending_package: dict[str, Any], approval_record: dict[str, Any]
) -> dict[str, Any]:
    if pending_package.get("package_status") != "pending_analyst_review":
        raise PhilippineApprovedBundleError(
            "Input review package is not pending analyst review"
        )
    if pending_package.get("promotion_allowed") is not False:
        raise PhilippineApprovedBundleError(
            "Pending review package unexpectedly permits promotion"
        )
    approval = _approval_from_record(approval_record)
    approved_package = deepcopy(pending_package)
    approved_package["package_status"] = "analyst_approved"
    approved_package["promotion_allowed"] = True
    approved_package["approval"] = approval
    for cases in approved_package["groups"].values():
        for case in cases:
            case["reviewer_status"] = deepcopy(approval)
    return approved_package


def _real_source_evidence(
    case: dict[str, Any], source_hashes: dict[str, str]
) -> dict[str, Any]:
    provider = (
        "openaq" if case["sensor_ref"].startswith("openaq-") else "purpleair"
    )
    return {
        "dataset": provider,
        "sensor_ref": case["sensor_ref"],
        "parameter_code": case["parameter_code"],
        "represented_local_date": case["represented_local_date"],
        "utc_window_started_at": case["utc_window_started_at"],
        "utc_window_ended_at": case["utc_window_ended_at"],
        "frozen_measurements_sha256": source_hashes[
            f"{provider}_measurements_sha256"
        ],
    }


def _approved_case(
    *,
    case_id: str,
    case_group: str,
    calculation_type: str,
    artifact_role: str,
    source_case: dict[str, Any],
    evidence: dict[str, Any],
    expected: Any,
    methodology_code: str,
    methodology_version: str,
    approval: dict[str, Any],
    independent_script: str,
) -> dict[str, Any]:
    source_case_hash = canonical_json_sha256(source_case)
    derivation = {
        "source_case_sha256": source_case_hash,
        "steps": [
            {
                "operation": "production_code_free_independent_derivation",
                "implementation": independent_script,
            },
            {
                "operation": "copy_approved_independent_result_without_recalculation",
                "source_artifact_role": artifact_role,
            },
        ],
        "absolute_tolerance": "0",
    }
    return {
        "case_id": case_id,
        "case_group": case_group,
        "calculation_type": calculation_type,
        "source": {
            "artifact_role": artifact_role,
            "source_case_id": case_id,
            "source_case_sha256": source_case_hash,
            "evidence": evidence,
        },
        "methodology": {
            "methodology_code": methodology_code,
            "methodology_version": methodology_version,
            "reference_ids": REFERENCE_IDS,
        },
        "derivation": derivation,
        "expected": expected,
        "review": {
            "status": "approved",
            "reviewer": approval["reviewer_identity"],
            "reviewed_at": approval["reviewed_at"],
            "derivation_sha256": canonical_json_sha256(derivation),
            "comments": approval["comments"],
            "approval_decision": approval["decision"],
            "exceptions": approval["exceptions"],
        },
    }


def build_approved_candidate_bundle(
    *,
    real_candidate_path: Path,
    synthetic_candidate_path: Path,
    approved_review_package_path: Path,
    approval_record_path: Path,
    artifact_root: Path,
    reference_root: Path,
) -> dict[str, Any]:
    real_candidate = _read_json(real_candidate_path)
    synthetic_candidate = _read_json(synthetic_candidate_path)
    approved_review_package = _read_json(approved_review_package_path)
    approval_record = _read_json(approval_record_path)
    approval = _approval_from_record(approval_record)
    if approved_review_package.get("approval") != approval:
        raise PhilippineApprovedBundleError(
            "Approved review package differs from the supplied approval record"
        )
    methodology_code = str(real_candidate["methodology_code"])
    methodology_version = str(real_candidate["methodology_version"])
    if synthetic_candidate.get("methodology_code") != methodology_code:
        raise PhilippineApprovedBundleError("Candidate methodology codes differ")
    if synthetic_candidate.get("methodology_version") != methodology_version:
        raise PhilippineApprovedBundleError("Candidate methodology versions differ")

    cases = []
    for source_case in real_candidate["cases"]:
        case_id = _real_case_id(source_case)
        provider = "openaq" if case_id.startswith("openaq_") else "purpleair"
        cases.append(
            _approved_case(
                case_id=case_id,
                case_group=f"real_manila_{provider}",
                calculation_type=(
                    f"philippines_denr.{source_case['parameter_code']}.completed_day"
                ),
                artifact_role="real_candidate",
                source_case=source_case,
                evidence=_real_source_evidence(
                    source_case, real_candidate["source_hashes"]
                ),
                expected=source_case,
                methodology_code=methodology_code,
                methodology_version=methodology_version,
                approval=approval,
                independent_script=(
                    "backend/tests/reference_data_tools/"
                    "philippines_denr_independent.py"
                ),
            )
        )
    for source_case in synthetic_candidate["cases"]:
        cases.append(
            _approved_case(
                case_id=source_case["case_id"],
                case_group=source_case["group"],
                calculation_type=source_case["case_kind"],
                artifact_role="synthetic_candidate",
                source_case=source_case,
                evidence=source_case["source_evidence"],
                expected=source_case["independent_result"],
                methodology_code=methodology_code,
                methodology_version=methodology_version,
                approval=approval,
                independent_script=(
                    "backend/tests/reference_data_tools/"
                    "philippines_denr_synthetic_independent.py"
                ),
            )
        )

    bundle = {
        "schema_version": PHILIPPINES_EXPECTED_SCHEMA_VERSION,
        "artifact_kind": "analyst_review_candidate",
        "standard_code": "philippines_denr",
        "methodology_code": methodology_code,
        "methodology_version": methodology_version,
        "bundle_id": "philippines-denr-aqi-2021-approved-v1",
        "source_artifacts": {
            "real_candidate": _artifact_binding(
                real_candidate_path, artifact_root
            ),
            "synthetic_candidate": _artifact_binding(
                synthetic_candidate_path, artifact_root
            ),
            "analyst_review_package": _artifact_binding(
                approved_review_package_path, artifact_root
            ),
            "approval_record": _artifact_binding(
                approval_record_path, artifact_root
            ),
        },
        "frozen_measurement_hashes": {
            "openaq": real_candidate["source_hashes"][
                "openaq_measurements_sha256"
            ],
            "purpleair": real_candidate["source_hashes"][
                "purpleair_measurements_sha256"
            ],
        },
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
    parser.add_argument("--real-candidate", required=True, type=Path)
    parser.add_argument("--synthetic-candidate", required=True, type=Path)
    parser.add_argument("--pending-review-package", required=True, type=Path)
    parser.add_argument("--approval-record", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--reference-root", required=True, type=Path)
    parser.add_argument("--approved-review-package-output", required=True, type=Path)
    parser.add_argument("--candidate-output", required=True, type=Path)
    args = parser.parse_args()

    pending_review = _read_json(args.pending_review_package.resolve())
    approval_record = _read_json(args.approval_record.resolve())
    approved_review = build_approved_review_package(
        pending_review, approval_record
    )
    approved_review_output = args.approved_review_package_output.resolve()
    approved_review_output.parent.mkdir(parents=True, exist_ok=True)
    approved_review_output.write_text(
        json.dumps(approved_review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    bundle = build_approved_candidate_bundle(
        real_candidate_path=args.real_candidate.resolve(),
        synthetic_candidate_path=args.synthetic_candidate.resolve(),
        approved_review_package_path=approved_review_output,
        approval_record_path=args.approval_record.resolve(),
        artifact_root=args.artifact_root.resolve(),
        reference_root=args.reference_root.resolve(),
    )
    candidate_output = args.candidate_output.resolve()
    candidate_output.parent.mkdir(parents=True, exist_ok=True)
    candidate_output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
