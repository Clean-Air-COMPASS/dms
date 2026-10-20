from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


TOOLS = Path(__file__).resolve().parent / "reference_data_tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from philippines_denr_independent import build_candidate_bundle  # noqa: E402


ROOT = Path(__file__).resolve().parent / "fixtures" / "reference_data"
PUBLIC = ROOT / "public" / "openaq" / "measurements.jsonl"
RESTRICTED = ROOT / "restricted" / "purpleair" / "measurements.jsonl"
CANDIDATE = ROOT / "provenance" / "philippines_denr" / "candidate.json"


def test_independent_derivation_has_no_production_or_network_imports():
    source_path = TOOLS / "philippines_denr_independent.py"
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


def test_frozen_manila_candidates_are_offline_and_preserve_source_hashes():
    bundle = build_candidate_bundle(PUBLIC, RESTRICTED)
    assert bundle["bundle_status"] == "candidate_awaiting_analyst_approval"
    assert bundle["provider_calls"] == 0
    assert bundle["source_hashes"] == {
        "openaq_measurements_sha256": (
            "dd93fda403acb4ad59e6819977c3e157c36203e12447617345fc0edd5c9d8ed3"
        ),
        "purpleair_measurements_sha256": (
            "aba35bb8e380a2e3343af724fa565b849f717f3783b006d9512405af3cd55028"
        ),
    }
    assert [case["sensor_ref"] for case in bundle["cases"]] == [
        "openaq-sensor-13191003",
        "purpleair-99177-pm25",
        "purpleair-99177-pm10",
    ]
    assert bundle["provenance"]["transport_provider"] == "OpenAQ"
    assert bundle["provenance"]["direct_airgradient_api_capture"] is False
    assert bundle["provenance"]["regulatory_monitor_conformance_claimed"] is False


def test_checked_in_candidate_matches_the_independent_derivation_and_is_not_approved():
    checked_in = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    assert checked_in == build_candidate_bundle(PUBLIC, RESTRICTED)
    assert checked_in["bundle_status"] == "candidate_awaiting_analyst_approval"


def test_real_manila_candidate_periods_are_independently_eligible():
    bundle = build_candidate_bundle(PUBLIC, RESTRICTED)
    for case in bundle["cases"]:
        assert case["eligibility_status"] == "eligible"
        assert case["valid_hour_count"] >= 18
        assert all(count >= 6 for count in case["block_valid_hour_counts"])
        assert case["maximum_consecutive_missing_hours"] <= 2
        assert case["calculation_status"] in {"calculated", "category_only"}
    assert [
        (case["preprocessed_concentration"], case["numeric_value"], case["category_code"])
        for case in bundle["cases"]
    ] == [
        ("37.2", "111.39", "unhealthy_for_sensitive_groups"),
        ("15.9", "31.80", "good"),
        ("21", "19.44", "good"),
    ]
