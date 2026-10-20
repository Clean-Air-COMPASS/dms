"""Assemble the concise, unapproved Phase 2I.5.2 analyst review package."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

try:
    from .source_facts import sha256_file
except ImportError:
    from source_facts import sha256_file


GROUP_CASES = {
    "PurpleAir / PM / New York": [
        "fixture_purpleair_2i4c2",
        "pa_ny_pm25_ordinary_boundary",
        "pa_ny_pm_boundary_assignment",
        "pa_ny_pm_full",
        "pa_ny_pm_duplicate_positions",
        "pa_ny_pm_nowcast_inputs",
        "pa_ny_pm25_completed_2026_08_09",
    ],
    "PurpleAir / PM / Rio de Janeiro": [
        "pa_rio_pm_minor_gaps",
        "pa_rio_pm_nowcast_inputs",
    ],
    "PurpleAir / PM / Metro Manila": [
        "pa_manila_pm_irregular",
        "pa_manila_pm_nowcast_inputs",
    ],
    "OpenAQ / U.S. EPA PM": [
        "fixture_openaq_2i4a",
        "openaq_rio_pm10_completed_2026_08_02",
    ],
    "OpenAQ / U.S. EPA ozone": ["openaq_ny_o3_window_2026_08_02T12"],
    "OpenAQ / U.S. EPA CO": ["openaq_ny_co_window_2026_08_02T12"],
    "OpenAQ / U.S. EPA NO2": ["openaq_ny_no2_hour_2026_08_02T11"],
    "OpenAQ / U.S. EPA SO2": ["openaq_ny_so2_window_2026_08_02T12"],
    "European AQI": [
        "provenance_manila_airgradient_via_openaq",
        "eea_rio_2026_08_02T11",
        "eea_pa_manila_2026_08_08T03",
        "eea_openaq_manila_2026_08_02T11",
    ],
    "Expected unavailable": [
        "openaq_rio_epa_mass_units_unavailable",
        "unavailable_zero_row_sensors",
    ],
}


SELECTION_REASONS = {
    "fixture_openaq_2i4a": "Verifies the complete public frozen dataset, documented hourly metadata, QC, and zero-row stream.",
    "fixture_purpleair_2i4c2": "Verifies the complete restricted frozen dataset, six active streams, provider timestamps, QC, and provenance-only device.",
    "provenance_manila_airgradient_via_openaq": "Prevents OpenAQ-transported AirGradient hardware data from being mislabeled as a direct AirGradient API capture.",
    "pa_ny_pm25_ordinary_boundary": "Separates ordinary clock-bucket aggregation from AQI receipt-time completeness.",
    "pa_ny_pm_boundary_assignment": "Exercises the off-frequency receipt and absent end anchor at a natural boundary.",
    "pa_ny_pm_full": "Provides a natural 30-of-30 PurpleAir completeness control.",
    "pa_ny_pm_duplicate_positions": "Exercises deterministic duplicate-anchor exclusion and three missing positions.",
    "pa_rio_pm_minor_gaps": "Exercises a naturally gapped but eligible 25-of-30 hour.",
    "pa_manila_pm_irregular": "Exercises a natural 240-second gap with 29-of-30 anchors.",
    "eea_pa_manila_2026_08_08T03": "Connects provider-neutral PM completeness to the European categorical path.",
    "pa_ny_pm_nowcast_inputs": "Covers a 12-hour New York PM2.5 and PM10 NowCast window with duplicate and gap patterns.",
    "pa_rio_pm_nowcast_inputs": "Covers a 12-hour Rio PM2.5 and PM10 NowCast window including a 25-anchor hour.",
    "pa_manila_pm_nowcast_inputs": "Covers a 12-hour Manila PM2.5 and PM10 NowCast window with irregular receipt timing.",
    "pa_ny_pm25_completed_2026_08_09": "Covers a 24-hour local-day PM2.5 result with all hours eligible but none uniformly full.",
    "openaq_rio_pm10_completed_2026_08_02": "Covers an exact 24-hour provider-hourly PM10 local day and integer preprocessing.",
    "openaq_ny_o3_window_2026_08_02T12": "Covers eight-hour ozone arithmetic, one-hour applicability, and candidate selection.",
    "openaq_ny_co_window_2026_08_02T12": "Exercises the exact six-of-eight rolling CO completeness threshold.",
    "openaq_ny_no2_hour_2026_08_02T11": "Exercises exact ppm-to-ppb conversion and one-hour NO2 interpolation.",
    "openaq_ny_so2_window_2026_08_02T12": "Exercises 23-of-24 SO2 coverage and one-hour versus 24-hour applicability.",
    "openaq_rio_epa_mass_units_unavailable": "Requires explicit rejection of unsupported gas mass-to-mixing conversions.",
    "eea_rio_2026_08_02T11": "Covers all five European AQI pollutants at one represented hour and dominant-pollutant selection.",
    "eea_openaq_manila_2026_08_02T11": "Covers a single available PM2.5 category with four explicitly missing pollutants.",
    "unavailable_zero_row_sensors": "Requires explicit unavailability for frozen sensors with no measurements.",
}


def _measurement_summary(case: dict[str, Any]) -> dict[str, Any]:
    observations = case["source_observations"]
    included = [item for item in observations if not item.get("exclusion_reason")]
    excluded = [item for item in observations if item.get("exclusion_reason")]
    timestamps = sorted(item["observed_at"] for item in observations)
    return {
        "observation_occurrence_count": len(observations),
        "included_occurrence_count": len(included),
        "excluded_occurrence_count": len(excluded),
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "exclusion_reason_counts": {
            reason: sum(item.get("exclusion_reason") == reason for item in excluded)
            for reason in sorted({item.get("exclusion_reason") for item in excluded})
        },
        "detail_location": "dataset worksheet JSON and Markdown",
    }


def build_review_package(
    worksheets: list[tuple[Path, dict[str, Any]]],
    discrepancies: list[tuple[Path, dict[str, Any]]],
    current_path: Path,
    current: dict[str, Any],
) -> dict[str, Any]:
    discrepancy_by_dataset = {
        report["dataset_name"]: {case["case_id"]: case for case in report["cases"]}
        for _, report in discrepancies
    }
    parts_by_case: dict[str, list[dict[str, Any]]] = {}
    for path, worksheet in worksheets:
        dataset_name = worksheet["dataset_name"]
        worksheet_discrepancies = discrepancy_by_dataset[dataset_name]
        for case in worksheet["cases"]:
            parts_by_case.setdefault(case["case_id"], []).append(
                {
                    "dataset_name": dataset_name,
                    "access_classification": worksheet["access_classification"],
                    "source_measurements_sha256": worksheet["source_measurements_sha256"],
                    "source_facts_sha256": worksheet["source_facts_sha256"],
                    "source_fact_hash": case["source_fact_hash"],
                    "candidate_derivation_sha256": case["candidate_derivation_sha256"],
                    "source_measurements": _measurement_summary(case),
                    "derivation": case["derivation"],
                    "candidate_outcome": case["candidate_expected"],
                    "current_compassaq_observation": worksheet_discrepancies[case["case_id"]]["current_summary"],
                    "discrepancy": {
                        key: worksheet_discrepancies[case["case_id"]][key]
                        for key in (
                            "comparison_status",
                            "differing_fields",
                            "candidate_fields_not_observed_by_current_reporter",
                            "resolution_status",
                            "root_cause",
                            "notes",
                        )
                        if key in worksheet_discrepancies[case["case_id"]]
                    },
                    "worksheet_file": path.name,
                }
            )
    registered = {case_id for case_ids in GROUP_CASES.values() for case_id in case_ids}
    if registered != set(parts_by_case):
        missing = sorted(set(parts_by_case) - registered)
        extra = sorted(registered - set(parts_by_case))
        raise ValueError(f"Review grouping mismatch: ungrouped={missing}, absent={extra}")
    groups = []
    for group_name, case_ids in GROUP_CASES.items():
        groups.append(
            {
                "group_name": group_name,
                "cases": [
                    {
                        "case_id": case_id,
                        "selection_reason": SELECTION_REASONS[case_id],
                        "access_parts": parts_by_case[case_id],
                        "review": {
                            "status": "candidate",
                            "reviewer": None,
                            "reviewed_at": None,
                            "comments": "",
                            "approval_decision": "pending",
                        },
                    }
                    for case_id in case_ids
                ],
            }
        )
    return {
        "schema_version": "2i.5-analyst-review-package-2",
        "artifact_kind": "analyst_review_package",
        "phase_boundary": "Phase 2I.5.2 analyst review package; stop before promotion",
        "oracle_status": "all_candidates_unapproved",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "safety": {
            "provider_calls": current.get("provider_calls"),
            "credential_reads": current.get("credential_reads"),
            "purpleair_points_consumed": current.get("purpleair_points_consumed"),
            "paid_imports_enabled": False,
            "current_output_used_as_derivation_input": False,
            "expected_results_promoted": False,
        },
        "documented_unavailable_and_partial_limitations": [
            {
                "case_id": "openaq_rio_epa_mass_units_unavailable",
                "status": "unavailable",
                "reason": "conversion_not_supported",
            },
            {
                "case_id": "unavailable_zero_row_sensors",
                "status": "unavailable",
                "reason": "no frozen measurements",
            },
            {
                "case_id": "eea_openaq_manila_2026_08_02T11",
                "status": "available_with_partial_coverage",
                "reason": "PM10, O3, NO2, and SO2 are absent",
            },
            {
                "case_id": "eea_pa_manila_2026_08_08T03",
                "status": "available_with_partial_coverage",
                "reason": "O3, NO2, and SO2 are absent",
            },
            {
                "diagnostic_id": "openaq_outside_adequate_history",
                "status": "unavailable_current_observation_only",
                "reason": "missing required history before the frozen fixture range",
                "note": "The baseline registry has no independent candidate case for this diagnostic, so it is documented but not promoted or counted among the 23 review cases.",
            },
        ],
        "resolved_methodology_decisions": [
            "The governing AirNow Technical Assistance Document is the May 2026 EPA-403/B-26-003 reference. The existing us_epa_aqi_2024 family-level API compatibility identifier denotes the implemented 2024 breakpoint revision; product methodology references separately expose the current document code and 2026-05 publication date.",
            "A qualified 23-of-24 SO2 window averages the 23 available valid hourly values and does not synthesize a missing value. The reviewed case sum is 12 ppb, so the 24-hour candidate concentration is 12/23 ppb; the selected low-concentration result uses the one-hour candidate.",
            "NowCast window coverage is complete when all 12 hourly concentrations qualify, while each underlying subhourly hour retains its own completeness counts and partial status.",
        ],
        "open_methodology_questions": [],
        "promotion_readiness": {
            "ready": False,
            "criteria": [
                "An air-quality analyst independently checks every derivation and candidate outcome.",
                "Each case receives reviewer identity, review timestamp, comments, and an explicit approval or rejection decision.",
                "The open methodology questions are resolved and recorded.",
                "Every accepted discrepancy is documented; implementation defects are corrected and observed again without copying current output into candidates.",
                "Source-fact, worksheet, derivation, and frozen dataset hashes still match at promotion time.",
            ],
        },
        "input_artifacts": {
            "worksheets": [
                {"file": path.name, "sha256": sha256_file(path)} for path, _ in worksheets
            ],
            "discrepancy_reports": [
                {"file": path.name, "sha256": sha256_file(path)} for path, _ in discrepancies
            ],
            "current_observations": {
                "file": current_path.name,
                "sha256": sha256_file(current_path),
            },
        },
        "registered_case_count": len(parts_by_case),
        "groups": groups,
    }


def review_package_markdown(package: dict[str, Any]) -> str:
    lines = [
        "# Phase 2I.5.2 offline real-data analyst review package",
        "",
        "Status: all results are review candidates; none are approved or promotable.",
        "",
        f"Registered cases: `{package['registered_case_count']}`",
        f"Provider calls: `{package['safety']['provider_calls']}`",
        f"Credential reads: `{package['safety']['credential_reads']}`",
        "",
        "Current CompassAQ output was generated separately and was not used in any candidate derivation.",
        "",
        "## Open methodology questions",
        "",
        "- None from this discrepancy investigation; candidate approval remains an analyst task.",
        "",
        "## Resolved methodology decisions",
        "",
        *[f"- {decision}" for decision in package["resolved_methodology_decisions"]],
        "",
        "Promotion readiness: `not ready`; analyst approval and hash-matching criteria remain outstanding.",
        "",
    ]
    for group in package["groups"]:
        lines.extend([f"## {group['group_name']}", ""])
        for case in group["cases"]:
            lines.extend(
                [
                    f"### {case['case_id']}",
                    "",
                    f"Why selected: {case['selection_reason']}",
                    "",
                ]
            )
            for part in case["access_parts"]:
                lines.extend(
                    [
                        f"Access part: `{part['dataset_name']}` / `{part['access_classification']}`",
                        f"Frozen measurements SHA-256: `{part['source_measurements_sha256']}`",
                        f"Source-fact artifact SHA-256: `{part['source_facts_sha256']}`",
                        f"Case source-fact hash: `{part['source_fact_hash']}`",
                        f"Candidate derivation SHA-256: `{part['candidate_derivation_sha256']}`",
                        "",
                        "Relevant source measurements:",
                        "",
                        "```json",
                        json.dumps(part["source_measurements"], ensure_ascii=False, indent=2),
                        "```",
                        "",
                        "Independent derivation:",
                        "",
                        "```json",
                        json.dumps(part["derivation"], ensure_ascii=False, indent=2),
                        "```",
                        "",
                        "Review candidate outcome:",
                        "",
                        "```json",
                        json.dumps(part["candidate_outcome"], ensure_ascii=False, indent=2),
                        "```",
                        "",
                        "Current CompassAQ observation (separately generated):",
                        "",
                        "```json",
                        json.dumps(part["current_compassaq_observation"], ensure_ascii=False, indent=2),
                        "```",
                        "",
                        "Discrepancy:",
                        "",
                        "```json",
                        json.dumps(part["discrepancy"], ensure_ascii=False, indent=2),
                        "```",
                        "",
                    ]
                )
            lines.extend(
                [
                    "Reviewer status: `pending`",
                    "Reviewer: `not assigned`",
                    "Approval decision: `pending`",
                    "Comments: none supplied",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worksheet", action="append", required=True, type=Path)
    parser.add_argument("--discrepancy", action="append", required=True, type=Path)
    parser.add_argument("--current-observations", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    args = parser.parse_args()
    worksheets = [(path.resolve(), json.loads(path.read_text(encoding="utf-8"))) for path in args.worksheet]
    discrepancies = [(path.resolve(), json.loads(path.read_text(encoding="utf-8"))) for path in args.discrepancy]
    current_path = args.current_observations.resolve()
    current = json.loads(current_path.read_text(encoding="utf-8"))
    package = build_review_package(worksheets, discrepancies, current_path, current)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(review_package_markdown(package), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
