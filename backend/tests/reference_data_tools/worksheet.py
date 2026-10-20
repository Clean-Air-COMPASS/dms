"""Create review worksheets from independent source facts, without an AQI oracle."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

try:
    from .independent_derivations import derive_review_candidate
    from .source_facts import DecimalJsonEncoder, canonical_json_sha256, sha256_file
except ImportError:
    from independent_derivations import derive_review_candidate
    from source_facts import DecimalJsonEncoder, canonical_json_sha256, sha256_file


def _walk_observations(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "observed_at" in value and "decimal_value" in value:
            yield value
        for child in value.values():
            yield from _walk_observations(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_observations(child)


def build_candidate_worksheet(
    source_facts: dict[str, Any],
    *,
    source_facts_file: str,
    source_facts_sha256: str,
    dataset_name: str,
) -> dict[str, Any]:
    dataset = source_facts["datasets"].get(dataset_name)
    if dataset is None:
        raise ValueError(f"Dataset {dataset_name!r} is absent from source facts")
    cases = []
    for extracted_case in source_facts["cases"]:
        if extracted_case.get("dataset") not in {dataset_name, None}:
            continue
        if extracted_case.get("extraction_status") != "extracted":
            continue
        facts = extracted_case["facts"]
        if extracted_case.get("dataset") is None and "sensor_results" in facts:
            facts = {
                **facts,
                "sensor_results": [
                    sensor
                    for sensor in facts["sensor_results"]
                    if sensor.get("dataset") == dataset_name
                ],
            }
        derivation, candidate_expected = derive_review_candidate(
            extracted_case["case_id"], extracted_case["case_type"], facts
        )
        # Hash the exact JSON-stable representation analysts will review. This
        # prevents Decimal or tuple serialization from making an in-memory hash
        # differ from the persisted worksheet record.
        derivation = json.loads(
            json.dumps(derivation, cls=DecimalJsonEncoder, ensure_ascii=False)
        )
        candidate_expected = json.loads(
            json.dumps(candidate_expected, cls=DecimalJsonEncoder, ensure_ascii=False)
        )
        observations = list(_walk_observations(facts))
        cases.append(
            {
                "case_id": extracted_case["case_id"],
                "calculation_type": extracted_case["case_type"],
                "source_fact_hash": extracted_case["source_fact_hash"],
                "source_observations": observations,
                "source_facts": facts,
                "derivation": derivation,
                "candidate_derivation_sha256": canonical_json_sha256(derivation),
                "candidate_expected": candidate_expected,
                "review": {
                    "status": "candidate",
                    "reviewer": None,
                    "reviewed_at": None,
                    "derivation_sha256": None,
                    "comments": "",
                    "approval_decision": "pending",
                },
            }
        )
    return {
        "schema_version": "2i.5-worksheet-2",
        "artifact_kind": "analyst_derivation_worksheet",
        "oracle_status": "candidate_not_approved",
        "dataset_name": dataset_name,
        "dataset_id": dataset["dataset_id"],
        "access_classification": dataset["access_classification"],
        "source_measurements_sha256": dataset["measurements_sha256"],
        "source_facts_file": source_facts_file,
        "source_facts_sha256": source_facts_sha256,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cases": cases,
    }


def worksheet_markdown(worksheet: dict[str, Any]) -> str:
    lines = [
        f"# Phase 2I.5 {worksheet['dataset_name']} analyst worksheet",
        "",
        "Status: independently derived review candidate; no AQI value or category is approved.",
        "",
        f"Dataset: `{worksheet['dataset_id']}`",
        f"Frozen measurements SHA-256: `{worksheet['source_measurements_sha256']}`",
        f"Source-fact artifact SHA-256: `{worksheet['source_facts_sha256']}`",
        "",
    ]
    for case in worksheet["cases"]:
        lines.extend(
            [
                f"## {case['case_id']}",
                "",
                f"Calculation type: `{case['calculation_type']}`",
                f"Source fact hash: `{case['source_fact_hash']}`",
                f"Candidate derivation SHA-256: `{case['candidate_derivation_sha256']}`",
                f"Candidate availability: `{case['candidate_expected']['availability']}`",
                f"Candidate numeric result: `{case['candidate_expected']['numeric_result']}`",
                f"Candidate category: `{case['candidate_expected']['category_code']}`",
                f"Candidate coverage: `{case['candidate_expected']['coverage_status']}`",
                "",
                "### Independent derivation",
                "",
                "```json",
                json.dumps(case["derivation"], ensure_ascii=False, indent=2),
                "```",
                "",
                "### Source observations",
                "",
            ]
        )
        observations = case["source_observations"]
        if not observations:
            lines.append("No source observations are available for this case.")
        for observation in observations:
            assignment = (
                "excluded: " + str(observation.get("exclusion_reason"))
                if observation.get("exclusion_reason")
                else "included"
            )
            lines.append(
                "- "
                f"`{observation['observed_at']}` = `{observation['decimal_value']}` "
                f"`{observation.get('unit') or 'unit from sensor manifest'}`; "
                f"{assignment}; provider ref "
                f"`{observation.get('provider_observation_ref')}`; assigned anchor "
                f"`{observation.get('assigned_anchor')}`"
            )
        lines.extend(["", "### Review", "", "Reviewer: pending", "Decision: pending", ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_facts", type=Path)
    parser.add_argument("--dataset", required=True, choices=("openaq", "purpleair"))
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    args = parser.parse_args()
    source_path = args.source_facts.resolve()
    source_facts = json.loads(source_path.read_text(encoding="utf-8"))
    if source_facts.get("artifact_kind") != "independently_extracted_source_facts":
        raise ValueError("Input is not an independent source-fact artifact")
    worksheet = build_candidate_worksheet(
        source_facts,
        source_facts_file=str(source_path),
        source_facts_sha256=sha256_file(source_path),
        dataset_name=args.dataset,
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(
            worksheet, cls=DecimalJsonEncoder, ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(worksheet_markdown(worksheet), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
