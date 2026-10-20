from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


TOOLS = Path(__file__).resolve().parent / "reference_data_tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from philippines_denr_discrepancy_report import (  # noqa: E402
    build_discrepancy_report,
)
from philippines_denr_current_observations import (  # noqa: E402
    build_philippine_observation_report,
)
from philippines_denr_integrity import verify_integrity  # noqa: E402
from philippines_denr_review_package import build_review_package  # noqa: E402
from philippines_denr_synthetic_discrepancy import (  # noqa: E402
    build_synthetic_discrepancy_report,
)
from philippines_denr_synthetic_independent import (  # noqa: E402
    build_synthetic_candidate_bundle,
)


REFERENCE_ROOT = Path(__file__).resolve().parent / "fixtures" / "reference_data"
PROVENANCE = REFERENCE_ROOT / "provenance" / "philippines_denr"
CANDIDATE = PROVENANCE / "candidate.json"
SYNTHETIC = PROVENANCE / "synthetic-candidates.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_review_inputs(tmp_path: Path) -> dict[str, Path]:
    review_root = tmp_path / "review"
    review_root.mkdir()
    implementation_path = review_root / "implementation-observations.json"
    implementation = build_philippine_observation_report(
        database_path=review_root / "current.sqlite3",
        public_root=REFERENCE_ROOT / "public" / "openaq",
        restricted_root=REFERENCE_ROOT / "restricted" / "purpleair",
        synthetic_candidate_path=SYNTHETIC,
    )
    _write_json(implementation_path, implementation)

    discrepancy_path = review_root / "discrepancy-report.json"
    discrepancy = build_discrepancy_report(CANDIDATE, implementation_path)
    _write_json(discrepancy_path, discrepancy)

    synthetic_discrepancy_path = review_root / "synthetic-discrepancy-report.json"
    synthetic_discrepancy = build_synthetic_discrepancy_report(
        SYNTHETIC, implementation_path
    )
    _write_json(synthetic_discrepancy_path, synthetic_discrepancy)

    integrity_path = review_root / "integrity-verification.json"
    _write_json(integrity_path, verify_integrity(CANDIDATE))
    return {
        "implementation": implementation_path,
        "discrepancy": discrepancy_path,
        "synthetic_discrepancy": synthetic_discrepancy_path,
        "integrity": integrity_path,
    }


def test_synthetic_derivation_does_not_import_production_or_network_modules():
    source_path = TOOLS / "philippines_denr_synthetic_independent.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports.intersection(
        {"api", "db", "httpx", "models", "requests", "services", "sources"}
    )


def test_checked_in_synthetic_candidates_are_reproducible_and_unapproved():
    checked_in = _load(SYNTHETIC)
    assert checked_in == build_synthetic_candidate_bundle()
    assert checked_in["bundle_status"] == "candidate_awaiting_analyst_approval"
    assert checked_in["production_code_imported"] is False
    assert checked_in["provider_calls"] == 0
    assert checked_in["credential_reads"] == 0
    assert checked_in["purpleair_points_consumed"] == 0
    assert len(checked_in["cases"]) == 103


def test_real_and_synthetic_discrepancy_reports_are_reproducible_matches(tmp_path):
    inputs = _build_review_inputs(tmp_path)
    real_report = build_discrepancy_report(CANDIDATE, inputs["implementation"])
    synthetic_report = build_synthetic_discrepancy_report(
        SYNTHETIC, inputs["implementation"]
    )
    assert _load(inputs["discrepancy"]) == real_report
    assert _load(inputs["synthetic_discrepancy"]) == synthetic_report
    assert real_report["matching_case_count"] == 3
    assert real_report["discrepancy_case_count"] == 0
    assert synthetic_report["matching_case_count"] == 103
    assert synthetic_report["discrepancy_case_count"] == 0
    assert real_report["automatic_resolution_performed"] is False
    assert synthetic_report["automatic_resolution_performed"] is False


def test_review_package_is_reproducible_and_blocks_promotion(tmp_path):
    inputs = _build_review_inputs(tmp_path)
    package = build_review_package(
        candidate_path=CANDIDATE,
        synthetic_candidate_path=SYNTHETIC,
        implementation_path=inputs["implementation"],
        discrepancy_path=inputs["discrepancy"],
        synthetic_discrepancy_path=inputs["synthetic_discrepancy"],
        integrity_path=inputs["integrity"],
    )
    repeated = build_review_package(
        candidate_path=CANDIDATE,
        synthetic_candidate_path=SYNTHETIC,
        implementation_path=inputs["implementation"],
        discrepancy_path=inputs["discrepancy"],
        synthetic_discrepancy_path=inputs["synthetic_discrepancy"],
        integrity_path=inputs["integrity"],
    )
    assert repeated == package
    assert package["package_status"] == "pending_analyst_review"
    assert package["promotion_allowed"] is False
    assert package["approval"]["reviewer_identity"] is None
    assert package["summary"] == {
        "real_candidate_count": 3,
        "synthetic_candidate_count": 103,
        "matching_candidate_count": 106,
        "discrepancy_candidate_count": 0,
    }
    assert package["safety"]["provider_calls"] == 0
    assert package["safety"]["credential_reads"] == 0
    assert package["safety"]["purpleair_points_consumed"] == 0
