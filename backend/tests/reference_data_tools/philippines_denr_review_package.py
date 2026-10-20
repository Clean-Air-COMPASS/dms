from __future__ import annotations

"""Build the pre-approval Philippine AQI analyst review package."""

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .source_facts import sha256_file
except ImportError:  # Direct script execution keeps the tools usable without installation.
    from source_facts import sha256_file


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _review_status() -> dict[str, Any]:
    return {
        "status": "pending",
        "reviewer_identity": None,
        "reviewed_at": None,
        "decision": None,
        "comments": None,
        "exceptions": [],
    }


def _real_methodology_note(provider: str) -> str:
    source = (
        "OpenAQ provider-reported hourly intervals"
        if provider == "openaq"
        else "PurpleAir provider-native two-minute expected positions"
    )
    return (
        f"{source} independently qualified into the completed Asia/Manila day; "
        "the arithmetic mean is normalized to µg/m³, PM2.5 is truncated to one "
        "decimal or PM10 to an integer, then interpolated without importing "
        "production Philippine constants or services."
    )


def _build_real_groups(
    candidate: dict[str, Any],
    implementation: dict[str, Any],
    discrepancy: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    candidate_by_id = {
        item["case_id"]: item for item in discrepancy["cases"]
    }
    implementation_by_id = {
        item["case_id"]: item for item in implementation["cases"]
    }
    groups = {"real_manila_openaq": [], "real_manila_purpleair": []}
    for case_id, comparison in candidate_by_id.items():
        observation = implementation_by_id[case_id]
        provider = observation["provider"].lower()
        group_name = (
            "real_manila_openaq"
            if provider == "openaq"
            else "real_manila_purpleair"
        )
        source_hash_key = (
            "openaq_measurements_sha256"
            if provider == "openaq"
            else "purpleair_measurements_sha256"
        )
        groups[group_name].append(
            {
                "case_id": case_id,
                "source_evidence": {
                    "transport_provider": provider,
                    "sensor_ref": observation["sensor_ref"],
                    "represented_local_date": observation[
                        "represented_local_date"
                    ],
                    "measurement_file_sha256": candidate["source_hashes"][
                        source_hash_key
                    ],
                    "qualified_observation_counts": observation[
                        "qualified_observation_counts"
                    ],
                    "provenance": observation["provenance"],
                },
                "independent_calculation": comparison["independent_candidate"],
                "expected_concentration_aqi_category": {
                    "normalized_concentration": comparison[
                        "independent_candidate"
                    ]["normalized_concentration"],
                    "preprocessed_concentration": comparison[
                        "independent_candidate"
                    ]["preprocessed_concentration"],
                    "numeric_value": comparison["independent_candidate"][
                        "numeric_value"
                    ],
                    "category_code": comparison["independent_candidate"][
                        "category_code"
                    ],
                },
                "production_result": comparison["implementation_observation"],
                "api_serialization": observation["api_serialization"],
                "discrepancy_status": {
                    "classifications": comparison["classifications"],
                    "differing_fields": comparison["differing_fields"],
                    "disposition": comparison["disposition"],
                },
                "methodology_reference_note": _real_methodology_note(provider),
                "reviewer_status": _review_status(),
            }
        )
    return groups


def _build_synthetic_group(
    candidates: dict[str, Any], discrepancy: dict[str, Any]
) -> list[dict[str, Any]]:
    comparison_by_id = {
        item["case_id"]: item for item in discrepancy["cases"]
    }
    cases = []
    for candidate in candidates["cases"]:
        comparison = comparison_by_id[candidate["case_id"]]
        expected = candidate["independent_result"]
        cases.append(
            {
                "case_id": candidate["case_id"],
                "case_kind": candidate["case_kind"],
                "parameter_code": candidate["parameter_code"],
                "source_evidence": candidate["source_evidence"],
                "independent_calculation": expected,
                "expected_concentration_aqi_category": {
                    key: expected.get(key)
                    for key in (
                        "normalized_concentration",
                        "preprocessed_concentration",
                        "numeric_value",
                        "category_code",
                        "eligibility_status",
                        "coverage_status",
                        "exclusion_reason",
                    )
                    if key in expected
                },
                "production_result": comparison[
                    "implementation_observation"
                ],
                "discrepancy_status": {
                    "classifications": comparison["classifications"],
                    "differing_fields": comparison["differing_fields"],
                    "disposition": comparison["disposition"],
                },
                "methodology_reference_note": candidate[
                    "methodology_reference_note"
                ],
                "reviewer_status": _review_status(),
            }
        )
    return cases


def build_review_package(
    *,
    candidate_path: Path,
    synthetic_candidate_path: Path,
    implementation_path: Path,
    discrepancy_path: Path,
    synthetic_discrepancy_path: Path,
    integrity_path: Path,
) -> dict[str, Any]:
    candidate = _load(candidate_path)
    synthetic_candidates = _load(synthetic_candidate_path)
    implementation = _load(implementation_path)
    discrepancy = _load(discrepancy_path)
    synthetic_discrepancy = _load(synthetic_discrepancy_path)
    integrity = _load(integrity_path)
    real_groups = _build_real_groups(candidate, implementation, discrepancy)
    groups = {
        **real_groups,
        "synthetic_regulatory_boundary_cases": _build_synthetic_group(
            synthetic_candidates, synthetic_discrepancy
        ),
    }
    return {
        "schema_version": "philippines-denr-analyst-review-package-1",
        "artifact_kind": "analyst_review_package",
        "methodology_code": candidate["methodology_code"],
        "methodology_version": candidate["methodology_version"],
        "package_status": "pending_analyst_review",
        "promotion_allowed": False,
        "approval": _review_status(),
        "summary": {
            "real_candidate_count": discrepancy["candidate_case_count"],
            "synthetic_candidate_count": synthetic_discrepancy[
                "candidate_case_count"
            ],
            "matching_candidate_count": (
                discrepancy["matching_case_count"]
                + synthetic_discrepancy["matching_case_count"]
            ),
            "discrepancy_candidate_count": (
                discrepancy["discrepancy_case_count"]
                + synthetic_discrepancy["discrepancy_case_count"]
            ),
        },
        "safety": {
            **implementation["safety"],
            "production_code_imported_by_independent_derivation": False,
        },
        "integrity_verification": integrity,
        "artifact_hashes": {
            "candidate_sha256": sha256_file(candidate_path),
            "synthetic_candidate_sha256": sha256_file(
                synthetic_candidate_path
            ),
            "implementation_observations_sha256": sha256_file(
                implementation_path
            ),
            "real_discrepancy_report_sha256": sha256_file(discrepancy_path),
            "synthetic_discrepancy_report_sha256": sha256_file(
                synthetic_discrepancy_path
            ),
            "integrity_verification_sha256": sha256_file(integrity_path),
        },
        "groups": groups,
    }


def _short_result(result: dict[str, Any]) -> str:
    if "numeric_value" in result:
        return "/".join(
            str(result.get(key) if result.get(key) is not None else "—")
            for key in ("preprocessed_concentration", "numeric_value", "category_code")
        )
    if "valid_hour_count" in result:
        return (
            f"{result.get('valid_hour_count')}/{result.get('expected_hour_count')} "
            f"{result.get('eligibility_status')}"
        )
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def render_markdown(review_package: dict[str, Any]) -> str:
    summary = review_package["summary"]
    lines = [
        "# Philippines DENR AQI analyst review package",
        "",
        "Status: **pending analyst review**. Promotion is not allowed until "
        "explicit approval metadata is recorded.",
        "",
        (
            f"- Methodology: `{review_package['methodology_code']}` / "
            f"`{review_package['methodology_version']}`"
        ),
        f"- Real candidates: {summary['real_candidate_count']}",
        f"- Synthetic candidates: {summary['synthetic_candidate_count']}",
        f"- Exact matches: {summary['matching_candidate_count']}",
        f"- Discrepancies: {summary['discrepancy_candidate_count']}",
        "- Provider calls: 0; credential reads: 0; PurpleAir points consumed: 0",
        "",
    ]
    headings = {
        "real_manila_openaq": "Real Manila — OpenAQ",
        "real_manila_purpleair": "Real Manila — PurpleAir",
        "synthetic_regulatory_boundary_cases": "Synthetic regulatory boundary cases",
    }
    for group_name, cases in review_package["groups"].items():
        lines.extend(
            [
                f"## {headings[group_name]}",
                "",
                "| Case | Kind | Independent expected | Production | "
                "Comparison | Review |",
                "|---|---|---|---|---|---|",
            ]
        )
        for case in cases:
            expected = _short_result(case["independent_calculation"])
            production = _short_result(case["production_result"])
            comparison = ", ".join(
                case["discrepancy_status"]["classifications"]
            )
            lines.append(
                f"| `{case['case_id']}` | {case.get('case_kind', 'real_fixture')} "
                f"| {expected} | {production} | {comparison} | pending |"
            )
        lines.append("")
    lines.extend(
        [
            "## Required approval record",
            "",
            "- Reviewer identity: pending",
            "- Timezone-aware review timestamp: pending",
            "- Decision (`approved` or `rejected`): pending",
            "- Comments: pending",
            "- Exceptions: none recorded",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--synthetic-candidates", required=True, type=Path)
    parser.add_argument("--implementation", required=True, type=Path)
    parser.add_argument("--discrepancy", required=True, type=Path)
    parser.add_argument("--synthetic-discrepancy", required=True, type=Path)
    parser.add_argument("--integrity", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()
    package = build_review_package(
        candidate_path=args.candidate.resolve(),
        synthetic_candidate_path=args.synthetic_candidates.resolve(),
        implementation_path=args.implementation.resolve(),
        discrepancy_path=args.discrepancy.resolve(),
        synthetic_discrepancy_path=args.synthetic_discrepancy.resolve(),
        integrity_path=args.integrity.resolve(),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.write_text(render_markdown(package), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
