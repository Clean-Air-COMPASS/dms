"""Validate and promote analyst-approved conformance expectation bundles.

Promotion is deliberately mechanical.  It verifies frozen source/worksheet
hashes and analyst decisions, but it never derives or changes expected values.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any

try:
    from .source_facts import DEFAULT_REFERENCE_ROOT, canonical_json_sha256, sha256_file
except ImportError:  # Direct script execution keeps the tools usable without a package install.
    from source_facts import DEFAULT_REFERENCE_ROOT, canonical_json_sha256, sha256_file


EXPECTED_SCHEMA_VERSION = "2i.5-expected-1"
PHILIPPINES_EXPECTED_SCHEMA_VERSION = "2i.5-expected-2"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PromotionError(ValueError):
    """Raised when a candidate cannot cross the analyst-review boundary."""


TOP_LEVEL_FIELDS = {
    "schema_version",
    "artifact_kind",
    "dataset_name",
    "access_classification",
    "dataset_id",
    "source_measurements_sha256",
    "source_facts_file",
    "source_facts_sha256",
    "worksheet_file",
    "worksheet_sha256",
    "cases",
}
CASE_FIELDS = {
    "case_id",
    "calculation_type",
    "source",
    "input_window",
    "source_observations",
    "completeness",
    "methodology",
    "derivation",
    "expected",
    "review",
}
OBSERVATION_FIELDS = {
    "sensor_ref",
    "provider_observation_ref",
    "source_page",
    "source_result_index",
    "provider_period",
    "provider_timestamp",
    "is_valid",
    "qc_flags",
    "qc_version",
    "observed_at",
    "value",
    "unit",
    "assignment",
    "assigned_anchor",
    "exclusion_reason",
}
REVIEW_FIELDS = {
    "status",
    "reviewer",
    "reviewed_at",
    "derivation_sha256",
    "comments",
    "approval_decision",
}

PHILIPPINES_TOP_LEVEL_FIELDS = {
    "schema_version",
    "artifact_kind",
    "standard_code",
    "methodology_code",
    "methodology_version",
    "bundle_id",
    "source_artifacts",
    "frozen_measurement_hashes",
    "cases",
}
PHILIPPINES_CASE_FIELDS = {
    "case_id",
    "case_group",
    "calculation_type",
    "source",
    "methodology",
    "derivation",
    "expected",
    "review",
}
PHILIPPINES_REVIEW_FIELDS = {
    "status",
    "reviewer",
    "reviewed_at",
    "derivation_sha256",
    "comments",
    "approval_decision",
    "exceptions",
}


def _require_exact_fields(
    value: Any, required: set[str], *, label: str, allow_additional: bool = False
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PromotionError(f"{label} must be an object")
    missing = sorted(required - set(value))
    if missing:
        raise PromotionError(f"{label} is missing required fields: {missing}")
    if not allow_additional:
        additional = sorted(set(value) - required)
        if additional:
            raise PromotionError(f"{label} contains unsupported fields: {additional}")
    return value


def _validate_schema_shape(bundle: dict[str, Any]) -> None:
    _require_exact_fields(bundle, TOP_LEVEL_FIELDS, label="Approved bundle")
    cases = bundle.get("cases")
    if not isinstance(cases, list) or not cases:
        raise PromotionError("At least one reviewed case is required")
    for index, case_value in enumerate(cases):
        case = _require_exact_fields(
            case_value, CASE_FIELDS, label=f"Case at index {index}"
        )
        case_id = str(case.get("case_id") or f"index {index}")
        _require_exact_fields(
            case["review"], REVIEW_FIELDS, label=f"Case {case_id} review"
        )
        for field in (
            "source",
            "input_window",
            "completeness",
            "methodology",
            "derivation",
            "expected",
        ):
            _require_exact_fields(
                case[field], set(), label=f"Case {case_id} {field}", allow_additional=True
            )
        required_completeness = {
            "numerator",
            "denominator",
            "required_count",
            "fraction",
            "missing_positions",
            "duplicate_positions",
            "off_frequency_positions",
            "status",
        }
        _require_exact_fields(
            case["completeness"],
            required_completeness,
            label=f"Case {case_id} completeness",
            allow_additional=True,
        )
        _require_exact_fields(
            case["methodology"],
            {"methodology_code", "methodology_version", "reference_ids"},
            label=f"Case {case_id} methodology",
            allow_additional=True,
        )
        _require_exact_fields(
            case["derivation"],
            {"steps", "absolute_tolerance"},
            label=f"Case {case_id} derivation",
            allow_additional=True,
        )
        expected = _require_exact_fields(
            case["expected"],
            {
                "availability",
                "numeric_result",
                "category_code",
                "exclusion_reason",
                "coverage_status",
            },
            label=f"Case {case_id} expected",
            allow_additional=True,
        )
        if expected["availability"] not in {
            "available",
            "unavailable",
            "not_applicable",
        }:
            raise PromotionError(f"Case {case_id} has unsupported availability")
        observations = case["source_observations"]
        if not isinstance(observations, list):
            raise PromotionError(f"Case {case_id} source_observations must be an array")
        for observation_index, observation in enumerate(observations):
            _require_exact_fields(
                observation,
                OBSERVATION_FIELDS,
                label=f"Case {case_id} observation {observation_index}",
            )
            if observation["assignment"] not in {"included", "excluded"}:
                raise PromotionError(
                    f"Case {case_id} observation {observation_index} has invalid assignment"
                )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _require_sha256(label: str, value: Any) -> str:
    text = str(value or "").lower()
    if not SHA256_PATTERN.fullmatch(text):
        raise PromotionError(f"{label} must be a lowercase SHA-256 value")
    return text


def _artifact_path(artifact_root: Path, relative_name: Any, *, label: str) -> Path:
    name = str(relative_name or "").strip()
    if not name:
        raise PromotionError(f"{label} is required")
    path = (artifact_root / name).resolve()
    if not _is_within(path, artifact_root):
        raise PromotionError(f"{label} must remain within the review artifact root")
    if not path.is_file():
        raise PromotionError(f"{label} does not exist: {path}")
    return path


def _reject_implementation_observations(value: Any, *, location: str = "candidate") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if normalized_key in {
                "current_compassaq_observation",
                "current_output",
                "implementation_observation",
                "implementation_observations",
            }:
                raise PromotionError(
                    f"{location}.{key} would mix current CompassAQ output into expectations"
                )
            _reject_implementation_observations(child, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_implementation_observations(child, location=f"{location}[{index}]")


def _validate_review(case: dict[str, Any]) -> None:
    case_id = str(case.get("case_id", "<unknown>"))
    review = case.get("review")
    if not isinstance(review, dict) or review.get("status") != "approved":
        raise PromotionError(f"Case {case_id} is not analyst-approved")
    if review.get("approval_decision") != "approved":
        raise PromotionError(f"Case {case_id} approval decision is not approved")
    if not str(review.get("reviewer") or "").strip():
        raise PromotionError(f"Case {case_id} is missing reviewer identity")
    reviewed_at = str(review.get("reviewed_at") or "")
    try:
        parsed_reviewed_at = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionError(f"Case {case_id} has an invalid review timestamp") from exc
    if parsed_reviewed_at.tzinfo is None:
        raise PromotionError(f"Case {case_id} review timestamp must include a timezone")
    derivation = case.get("derivation")
    if not isinstance(derivation, dict):
        raise PromotionError(f"Case {case_id} is missing its derivation")
    declared_hash = _require_sha256(
        f"Case {case_id} derivation_sha256", review.get("derivation_sha256")
    )
    actual_hash = canonical_json_sha256(derivation)
    if declared_hash != actual_hash:
        raise PromotionError(
            f"Case {case_id} derivation hash mismatch: declared {declared_hash}, "
            f"actual {actual_hash}"
        )
    if not str(review.get("comments") or "").strip():
        raise PromotionError(f"Case {case_id} requires analyst review comments")


def _reviewed_worksheet_expected(worksheet_case: dict[str, Any]) -> Any:
    """Return the independently derived outcome without its candidate-status label."""
    expected = worksheet_case.get("candidate_expected")
    if expected is None:
        # Retain compatibility with the small synthetic promotion fixtures that
        # predate the independently derived worksheet format.
        expected = worksheet_case.get("expected")
    if not isinstance(expected, dict):
        return expected
    reviewed_expected = dict(expected)
    reviewed_expected.pop("status", None)
    return reviewed_expected


def _resolve_frozen_dataset_root(dataset_name: str, reference_root: Path) -> Path:
    if dataset_name == "openaq":
        return reference_root / "public" / "openaq"
    if dataset_name != "purpleair":
        raise PromotionError(f"Unsupported approved dataset_name: {dataset_name!r}")
    configured_root = os.getenv(
        "COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT", ""
    ).strip()
    if configured_root:
        private_root = Path(configured_root).expanduser().resolve()
        if private_root.is_dir():
            return private_root
    checked_in_root = reference_root / "restricted" / "purpleair"
    if checked_in_root.is_dir():
        return checked_in_root
    raise PromotionError(
        "Restricted frozen reference data is unavailable for checksum validation"
    )


def _validate_frozen_measurements(
    bundle: dict[str, Any], *, reference_root: Path
) -> None:
    dataset_name = str(bundle.get("dataset_name") or "")
    dataset_root = _resolve_frozen_dataset_root(dataset_name, reference_root.resolve())
    manifest_path = dataset_root / "manifest.json"
    if not manifest_path.is_file():
        raise PromotionError(f"Frozen fixture manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"Frozen fixture manifest is invalid: {exc}") from exc
    if manifest.get("dataset_id") != bundle.get("dataset_id"):
        raise PromotionError("Frozen fixture dataset_id changed after analyst review")
    measurements_name = str(manifest.get("measurements_file") or "")
    measurements_path = (dataset_root / measurements_name).resolve()
    if not measurements_name or not _is_within(measurements_path, dataset_root):
        raise PromotionError("Frozen fixture measurements_file is invalid")
    if not measurements_path.is_file():
        raise PromotionError(f"Frozen measurements are missing: {measurements_path}")
    expected_hash = _require_sha256(
        "source_measurements_sha256", bundle.get("source_measurements_sha256")
    )
    manifest_hash = _require_sha256(
        "manifest measurements_sha256", manifest.get("measurements_sha256")
    )
    actual_hash = sha256_file(measurements_path)
    if manifest_hash != expected_hash or actual_hash != expected_hash:
        raise PromotionError(
            "Frozen measurement checksum no longer matches the reviewed candidate"
        )


def _validate_named_frozen_measurement(
    dataset_name: str,
    expected_hash: Any,
    *,
    reference_root: Path,
) -> None:
    """Validate one frozen provider file without assuming a single-source bundle."""
    dataset_root = _resolve_frozen_dataset_root(
        dataset_name, reference_root.resolve()
    )
    manifest_path = dataset_root / "manifest.json"
    if not manifest_path.is_file():
        raise PromotionError(f"Frozen fixture manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"Frozen fixture manifest is invalid: {exc}") from exc
    measurements_name = str(manifest.get("measurements_file") or "")
    measurements_path = (dataset_root / measurements_name).resolve()
    if not measurements_name or not _is_within(measurements_path, dataset_root):
        raise PromotionError("Frozen fixture measurements_file is invalid")
    if not measurements_path.is_file():
        raise PromotionError(f"Frozen measurements are missing: {measurements_path}")
    reviewed_hash = _require_sha256(
        f"{dataset_name} frozen measurement hash", expected_hash
    )
    manifest_hash = _require_sha256(
        f"{dataset_name} manifest measurements_sha256",
        manifest.get("measurements_sha256"),
    )
    actual_hash = sha256_file(measurements_path)
    if reviewed_hash != manifest_hash or reviewed_hash != actual_hash:
        raise PromotionError(
            f"Frozen {dataset_name} measurement checksum changed after analyst review"
        )


def _philippine_real_case_id(case: dict[str, Any]) -> str:
    sensor_ref = str(case.get("sensor_ref") or "")
    provider = "openaq" if sensor_ref.startswith("openaq-") else "purpleair"
    represented_date = str(case.get("represented_local_date") or "").replace(
        "-", "_"
    )
    return (
        f"{provider}_{case.get('parameter_code')}_completed_{represented_date}"
    )


def _load_bound_artifact(
    artifact_root: Path,
    binding: Any,
    *,
    role: str,
) -> tuple[Path, dict[str, Any]]:
    binding = _require_exact_fields(
        binding, {"file", "sha256"}, label=f"Source artifact {role}"
    )
    path = _artifact_path(
        artifact_root, binding["file"], label=f"Source artifact {role} file"
    )
    expected_hash = _require_sha256(
        f"Source artifact {role} sha256", binding["sha256"]
    )
    if sha256_file(path) != expected_hash:
        raise PromotionError(f"Source artifact {role} hash no longer matches")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"Source artifact {role} is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise PromotionError(f"Source artifact {role} must be an object")
    return path, value


def _validate_philippine_review(
    case: dict[str, Any], approved_review: dict[str, Any]
) -> None:
    case_id = str(case.get("case_id") or "<unknown>")
    review = _require_exact_fields(
        case.get("review"),
        PHILIPPINES_REVIEW_FIELDS,
        label=f"Case {case_id} review",
    )
    if review.get("status") != "approved":
        raise PromotionError(f"Case {case_id} is not analyst-approved")
    if review.get("approval_decision") != "approved":
        raise PromotionError(f"Case {case_id} approval decision is not approved")
    if review.get("reviewer") != approved_review.get("reviewer_identity"):
        raise PromotionError(f"Case {case_id} reviewer differs from review package")
    if review.get("reviewed_at") != approved_review.get("reviewed_at"):
        raise PromotionError(
            f"Case {case_id} timestamp differs from review package"
        )
    if review.get("comments") != approved_review.get("comments"):
        raise PromotionError(f"Case {case_id} comments differ from review package")
    if review.get("exceptions") != approved_review.get("exceptions"):
        raise PromotionError(f"Case {case_id} exceptions differ from review package")
    reviewed_at = str(review.get("reviewed_at") or "")
    try:
        parsed_reviewed_at = datetime.fromisoformat(
            reviewed_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise PromotionError(
            f"Case {case_id} has an invalid review timestamp"
        ) from exc
    if parsed_reviewed_at.tzinfo is None:
        raise PromotionError(
            f"Case {case_id} review timestamp must include a timezone"
        )
    if not str(review.get("reviewer") or "").strip():
        raise PromotionError(f"Case {case_id} is missing reviewer identity")
    if not str(review.get("comments") or "").strip():
        raise PromotionError(f"Case {case_id} requires analyst comments")
    declared_hash = _require_sha256(
        f"Case {case_id} derivation_sha256",
        review.get("derivation_sha256"),
    )
    actual_hash = canonical_json_sha256(case.get("derivation"))
    if declared_hash != actual_hash:
        raise PromotionError(f"Case {case_id} derivation hash mismatch")


def _validate_philippine_bundle(
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    reference_root: Path,
) -> None:
    """Validate the multi-source Philippine bundle using Phase 2I safeguards."""
    _require_exact_fields(
        bundle,
        PHILIPPINES_TOP_LEVEL_FIELDS,
        label="Philippine approved bundle",
    )
    if bundle.get("artifact_kind") not in {
        "analyst_review_candidate",
        "analyst_approved_expectations",
    }:
        raise PromotionError("Candidate has an unsupported artifact_kind")
    _reject_implementation_observations(bundle)
    if bundle.get("standard_code") != "philippines_denr":
        raise PromotionError("Philippine bundle has an unexpected standard_code")
    if bundle.get("methodology_code") != "philippines_denr_aqi":
        raise PromotionError("Philippine bundle has an unexpected methodology_code")
    if bundle.get("methodology_version") != "denr_emb_aqi_2021":
        raise PromotionError(
            "Philippine bundle has an unexpected methodology_version"
        )

    source_artifacts = _require_exact_fields(
        bundle.get("source_artifacts"),
        {
            "real_candidate",
            "synthetic_candidate",
            "analyst_review_package",
            "approval_record",
        },
        label="Philippine source_artifacts",
    )
    _, real_candidate = _load_bound_artifact(
        artifact_root,
        source_artifacts["real_candidate"],
        role="real_candidate",
    )
    _, synthetic_candidate = _load_bound_artifact(
        artifact_root,
        source_artifacts["synthetic_candidate"],
        role="synthetic_candidate",
    )
    _, review_package = _load_bound_artifact(
        artifact_root,
        source_artifacts["analyst_review_package"],
        role="analyst_review_package",
    )
    _, approval_record = _load_bound_artifact(
        artifact_root,
        source_artifacts["approval_record"],
        role="approval_record",
    )
    if real_candidate.get("bundle_status") != (
        "candidate_awaiting_analyst_approval"
    ):
        raise PromotionError("Real Philippine source is not the reviewed candidate")
    if synthetic_candidate.get("artifact_kind") != (
        "independent_synthetic_candidates"
    ):
        raise PromotionError("Synthetic Philippine source has an unexpected kind")
    if synthetic_candidate.get("production_code_imported") is not False:
        raise PromotionError("Synthetic source imported production code")
    if review_package.get("artifact_kind") != "analyst_review_package":
        raise PromotionError("Review package has an unexpected kind")
    if review_package.get("package_status") != "analyst_approved":
        raise PromotionError("Review package is not analyst-approved")
    if review_package.get("promotion_allowed") is not True:
        raise PromotionError("Review package does not permit promotion")
    approved_review = review_package.get("approval")
    if not isinstance(approved_review, dict):
        raise PromotionError("Review package is missing its approval record")
    if approved_review.get("status") != "approved":
        raise PromotionError("Review package approval status is not approved")
    if approved_review.get("decision") != "approved":
        raise PromotionError("Review package decision is not approved")
    expected_approval_record = {
        "status": "approved",
        "reviewer_identity": approval_record.get("reviewer_identity"),
        "reviewed_at": approval_record.get("reviewed_at"),
        "decision": approval_record.get("decision"),
        "comments": approval_record.get("comments"),
        "exceptions": approval_record.get("exceptions"),
    }
    if approval_record.get("artifact_kind") != "analyst_approval_record":
        raise PromotionError("Approval record has an unexpected kind")
    if approved_review != expected_approval_record:
        raise PromotionError("Review package approval differs from approval record")

    artifact_hashes = review_package.get("artifact_hashes", {})
    if artifact_hashes.get("candidate_sha256") != source_artifacts[
        "real_candidate"
    ]["sha256"]:
        raise PromotionError("Review package real candidate hash differs")
    if artifact_hashes.get("synthetic_candidate_sha256") != source_artifacts[
        "synthetic_candidate"
    ]["sha256"]:
        raise PromotionError("Review package synthetic candidate hash differs")

    frozen_hashes = _require_exact_fields(
        bundle.get("frozen_measurement_hashes"),
        {"openaq", "purpleair"},
        label="Philippine frozen_measurement_hashes",
    )
    if frozen_hashes.get("openaq") != real_candidate.get("source_hashes", {}).get(
        "openaq_measurements_sha256"
    ):
        raise PromotionError("OpenAQ frozen hash differs from reviewed candidate")
    if frozen_hashes.get("purpleair") != real_candidate.get(
        "source_hashes", {}
    ).get("purpleair_measurements_sha256"):
        raise PromotionError("PurpleAir frozen hash differs from reviewed candidate")
    for dataset_name in ("openaq", "purpleair"):
        _validate_named_frozen_measurement(
            dataset_name,
            frozen_hashes[dataset_name],
            reference_root=reference_root,
        )

    source_cases: dict[str, tuple[str, dict[str, Any], Any]] = {}
    for source_case in real_candidate.get("cases", []):
        case_id = _philippine_real_case_id(source_case)
        source_cases[case_id] = ("real_candidate", source_case, source_case)
    for source_case in synthetic_candidate.get("cases", []):
        case_id = str(source_case.get("case_id") or "")
        source_cases[case_id] = (
            "synthetic_candidate",
            source_case,
            source_case.get("independent_result"),
        )
    cases = bundle.get("cases")
    if not isinstance(cases, list) or not cases:
        raise PromotionError("At least one Philippine reviewed case is required")
    if len(cases) != len(source_cases):
        raise PromotionError("Philippine bundle does not contain every source case")
    review_cases = {
        case["case_id"]: case
        for group in review_package.get("groups", {}).values()
        for case in group
        if isinstance(case, dict) and case.get("case_id")
    }
    seen_case_ids: set[str] = set()
    for index, case_value in enumerate(cases):
        case = _require_exact_fields(
            case_value,
            PHILIPPINES_CASE_FIELDS,
            label=f"Philippine case at index {index}",
        )
        case_id = str(case.get("case_id") or "")
        if not case_id or case_id in seen_case_ids:
            raise PromotionError("Philippine case IDs must be present and unique")
        seen_case_ids.add(case_id)
        if case_id not in source_cases:
            raise PromotionError(f"Case {case_id} is absent from source candidates")
        role, source_case, source_expected = source_cases[case_id]
        source = _require_exact_fields(
            case.get("source"),
            {"artifact_role", "source_case_id", "source_case_sha256", "evidence"},
            label=f"Case {case_id} source",
        )
        if source.get("artifact_role") != role:
            raise PromotionError(f"Case {case_id} source artifact role differs")
        if source.get("source_case_id") != case_id:
            raise PromotionError(f"Case {case_id} source_case_id differs")
        source_case_hash = canonical_json_sha256(source_case)
        if source.get("source_case_sha256") != source_case_hash:
            raise PromotionError(f"Case {case_id} source-case hash differs")
        if case.get("expected") != source_expected:
            raise PromotionError(
                f"Case {case_id} expected result differs from independent source"
            )
        derivation = _require_exact_fields(
            case.get("derivation"),
            {"source_case_sha256", "steps", "absolute_tolerance"},
            label=f"Case {case_id} derivation",
        )
        if derivation.get("source_case_sha256") != source_case_hash:
            raise PromotionError(f"Case {case_id} derivation source hash differs")
        methodology = _require_exact_fields(
            case.get("methodology"),
            {"methodology_code", "methodology_version", "reference_ids"},
            label=f"Case {case_id} methodology",
        )
        if methodology.get("methodology_code") != bundle["methodology_code"]:
            raise PromotionError(f"Case {case_id} methodology code differs")
        if methodology.get("methodology_version") != bundle[
            "methodology_version"
        ]:
            raise PromotionError(f"Case {case_id} methodology version differs")
        review_case = review_cases.get(case_id)
        if review_case is None:
            raise PromotionError(f"Case {case_id} is absent from review package")
        if review_case.get("reviewer_status", {}).get("status") != "approved":
            raise PromotionError(f"Case {case_id} review remains pending")
        if review_case.get("discrepancy_status", {}).get(
            "classifications"
        ) != ["match"]:
            raise PromotionError(f"Case {case_id} has an unresolved discrepancy")
        _validate_philippine_review(case, approved_review)
    if seen_case_ids != set(source_cases):
        raise PromotionError("Philippine bundle source case set differs")


def validate_approved_bundle(
    bundle: dict[str, Any],
    *,
    artifact_root: Path,
    reference_root: Path = DEFAULT_REFERENCE_ROOT,
) -> None:
    """Fail closed unless every review and referenced artifact still matches."""
    if bundle.get("schema_version") == PHILIPPINES_EXPECTED_SCHEMA_VERSION:
        _validate_philippine_bundle(
            bundle,
            artifact_root=artifact_root,
            reference_root=reference_root,
        )
        return
    if bundle.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        raise PromotionError("Unsupported expected-results schema_version")
    if bundle.get("artifact_kind") not in {
        "analyst_review_candidate",
        "analyst_approved_expectations",
    }:
        raise PromotionError("Candidate has an unsupported artifact_kind")
    _reject_implementation_observations(bundle)
    _validate_schema_shape(bundle)

    dataset_name = str(bundle.get("dataset_name") or "")
    if dataset_name not in {"openaq", "purpleair"}:
        raise PromotionError("Approved bundle requires dataset_name openaq or purpleair")

    source_facts_path = _artifact_path(
        artifact_root, bundle.get("source_facts_file"), label="source_facts_file"
    )
    worksheet_path = _artifact_path(
        artifact_root, bundle.get("worksheet_file"), label="worksheet_file"
    )
    expected_source_facts_hash = _require_sha256(
        "source_facts_sha256", bundle.get("source_facts_sha256")
    )
    expected_worksheet_hash = _require_sha256(
        "worksheet_sha256", bundle.get("worksheet_sha256")
    )
    if sha256_file(source_facts_path) != expected_source_facts_hash:
        raise PromotionError("Source-fact file hash no longer matches the reviewed candidate")
    if sha256_file(worksheet_path) != expected_worksheet_hash:
        raise PromotionError("Worksheet file hash no longer matches the reviewed candidate")

    try:
        source_facts = json.loads(source_facts_path.read_text(encoding="utf-8"))
        worksheet = json.loads(worksheet_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"Invalid source-fact or worksheet JSON: {exc}") from exc
    if source_facts.get("artifact_kind") != "independently_extracted_source_facts":
        raise PromotionError("source_facts_file is not an independent source-fact artifact")
    if source_facts.get("oracle_status") != "source_evidence_only_not_expected_results":
        raise PromotionError("source_facts_file does not declare its non-oracle status")
    if worksheet.get("artifact_kind") != "analyst_derivation_worksheet":
        raise PromotionError("worksheet_file is not an analyst derivation worksheet")
    if worksheet.get("source_facts_sha256") != expected_source_facts_hash:
        raise PromotionError("Worksheet was not derived from the reviewed source-fact hash")
    if worksheet.get("dataset_name") not in {None, dataset_name}:
        raise PromotionError("Approved dataset_name differs from the reviewed worksheet")
    if worksheet.get("dataset_id") not in {None, bundle.get("dataset_id")}:
        raise PromotionError("Approved dataset_id differs from the reviewed worksheet")
    if worksheet.get("access_classification") not in {
        None,
        bundle.get("access_classification"),
    }:
        raise PromotionError(
            "Approved access classification differs from the reviewed worksheet"
        )

    dataset_id = str(bundle.get("dataset_id") or "")
    source_dataset = next(
        (
            value
            for value in source_facts.get("datasets", {}).values()
            if value.get("dataset_id") == dataset_id
        ),
        None,
    )
    if source_dataset is None:
        raise PromotionError("Approved dataset_id is absent from the source-fact artifact")
    source_measurements_sha256 = _require_sha256(
        "source_measurements_sha256", bundle.get("source_measurements_sha256")
    )
    if source_dataset.get("measurements_sha256") != source_measurements_sha256:
        raise PromotionError("Frozen measurement checksum changed after analyst review")
    _validate_frozen_measurements(bundle, reference_root=reference_root)

    cases = bundle["cases"]
    case_ids: set[str] = set()
    worksheet_cases = {
        str(case.get("case_id")): case
        for case in worksheet.get("cases", [])
        if isinstance(case, dict)
    }
    for case in cases:
        if not isinstance(case, dict):
            raise PromotionError("Every expected case must be an object")
        case_id = str(case.get("case_id") or "")
        if not case_id or case_id in case_ids:
            raise PromotionError("Expected case IDs must be present and unique")
        case_ids.add(case_id)
        _validate_review(case)
        worksheet_case = worksheet_cases.get(case_id)
        if worksheet_case is None:
            raise PromotionError(f"Case {case_id} is absent from the reviewed worksheet")
        if canonical_json_sha256(worksheet_case.get("derivation")) != canonical_json_sha256(
            case.get("derivation")
        ):
            raise PromotionError(f"Case {case_id} derivation differs from the worksheet")
        if _reviewed_worksheet_expected(worksheet_case) != case.get("expected"):
            raise PromotionError(f"Case {case_id} expected result differs from the worksheet")
        source = case.get("source")
        if not isinstance(source, dict) or source.get("source_fact_hash") != (
            worksheet_case.get("source_fact_hash")
        ):
            raise PromotionError(f"Case {case_id} source-fact hash differs from the worksheet")


def load_approved_expectation(
    path: Path,
    *,
    artifact_root: Path,
    reference_root: Path = DEFAULT_REFERENCE_ROOT,
) -> dict[str, Any]:
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if bundle.get("artifact_kind") != "analyst_approved_expectations":
        raise PromotionError(f"Conformance input is not promoted: {path}")
    validate_approved_bundle(
        bundle, artifact_root=artifact_root, reference_root=reference_root
    )
    return bundle


def promote_candidate(
    candidate_path: Path,
    destination_path: Path,
    *,
    artifact_root: Path,
    expected_root: Path,
    reference_root: Path = DEFAULT_REFERENCE_ROOT,
) -> None:
    candidate_path = candidate_path.resolve()
    destination_path = destination_path.resolve()
    expected_root = expected_root.resolve()
    if _is_within(candidate_path, expected_root):
        raise PromotionError("Review candidates must remain outside the expected-results root")
    if not _is_within(destination_path, expected_root):
        raise PromotionError("Promoted output must remain within the expected-results root")
    if destination_path.exists():
        raise PromotionError("Promotion will not overwrite an existing expected-results file")
    bundle = json.loads(candidate_path.read_text(encoding="utf-8"))
    validate_approved_bundle(
        bundle,
        artifact_root=artifact_root.resolve(),
        reference_root=reference_root.resolve(),
    )
    promoted = dict(bundle)
    promoted["artifact_kind"] = "analyst_approved_expectations"
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(
        json.dumps(promoted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--expected-root", required=True, type=Path)
    parser.add_argument("--reference-root", type=Path, default=DEFAULT_REFERENCE_ROOT)
    args = parser.parse_args()
    promote_candidate(
        args.candidate,
        args.destination,
        artifact_root=args.artifact_root,
        expected_root=args.expected_root,
        reference_root=args.reference_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
