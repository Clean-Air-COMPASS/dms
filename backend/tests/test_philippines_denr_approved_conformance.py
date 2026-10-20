from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import shutil
import sys

import pytest


TOOLS = Path(__file__).resolve().parent / "reference_data_tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from philippines_denr_current_observations import (  # noqa: E402
    build_philippine_observation_report,
)
from promotion import (  # noqa: E402
    PromotionError,
    load_approved_expectation,
    promote_candidate,
)
from source_facts import sha256_file  # noqa: E402


REFERENCE_ROOT = (
    Path(__file__).resolve().parent / "fixtures" / "reference_data"
)
EXPECTED_ROOT = REFERENCE_ROOT / "expected"
ARTIFACT_ROOT = REFERENCE_ROOT / "provenance" / "philippines_denr"
APPROVED_EXPECTATION = (
    EXPECTED_ROOT
    / "philippines_denr"
    / "denr-emb-aqi-2021-approved-v1.json"
)
APPROVED_EXPECTATION_SHA256 = (
    "57dd36c08c1475f2889d69ce4cb91b7025795f01041b42f3d61611e3c51b08f0"
)
REVIEWER = "Spheros Environmental"
REVIEWED_AT = "2026-08-12T12:15:00-07:00"
APPROVAL_COMMENTS = (
    "Reviewed the Philippines DENR-EMB AQI conformance package, including the "
    "independent derivations, implementation observations, discrepancy results, "
    "regulatory boundary cases, completeness rules, unit handling, Manila-time "
    "semantics, and documented methodology limitations. I approve the candidate "
    "expectations for immutable promotion. The implementation correctly remains "
    "pollutant-specific with no overall/site AQI, preserves decimal interpolation, "
    "explicitly represents published gaps and undefined ranges, and keeps deferred "
    "features outside this release."
)
NUMERIC_FIELDS = {
    "normalized_concentration",
    "preprocessed_concentration",
    "numeric_value",
}


def _sha256(path: Path) -> str:
    return sha256_file(path)


@pytest.fixture(scope="module")
def approved_bundle() -> dict:
    assert _sha256(APPROVED_EXPECTATION) == APPROVED_EXPECTATION_SHA256
    return load_approved_expectation(
        APPROVED_EXPECTATION,
        artifact_root=ARTIFACT_ROOT,
        reference_root=REFERENCE_ROOT,
    )


@pytest.fixture(scope="module")
def current_observations(tmp_path_factory) -> dict:
    database_path = (
        tmp_path_factory.mktemp("philippines-approved-conformance")
        / "current.sqlite3"
    )
    return build_philippine_observation_report(
        database_path=database_path,
        public_root=REFERENCE_ROOT / "public" / "openaq",
        restricted_root=REFERENCE_ROOT / "restricted" / "purpleair",
        synthetic_candidate_path=(ARTIFACT_ROOT / "synthetic-candidates.json"),
    )


def _assert_result_matches(expected: dict, actual: dict) -> None:
    assert set(actual) == set(expected)
    for field, expected_value in expected.items():
        actual_value = actual[field]
        if field in NUMERIC_FIELDS and expected_value is not None:
            assert Decimal(str(actual_value)) == Decimal(str(expected_value))
        else:
            assert actual_value == expected_value


def test_promoted_bundle_is_hash_linked_to_frozen_sources_and_human_approval(
    approved_bundle,
):
    assert approved_bundle["artifact_kind"] == "analyst_approved_expectations"
    assert approved_bundle["standard_code"] == "philippines_denr"
    assert approved_bundle["methodology_code"] == "philippines_denr_aqi"
    assert approved_bundle["methodology_version"] == "denr_emb_aqi_2021"
    assert approved_bundle["frozen_measurement_hashes"] == {
        "openaq": (
            "dd93fda403acb4ad59e6819977c3e157c36203e12447617345fc0edd5c9d8ed3"
        ),
        "purpleair": (
            "aba35bb8e380a2e3343af724fa565b849f717f3783b006d9512405af3cd55028"
        ),
    }
    assert len(approved_bundle["cases"]) == 106
    assert len({case["case_id"] for case in approved_bundle["cases"]}) == 106
    assert sum(
        case["case_group"] == "real_manila_openaq"
        for case in approved_bundle["cases"]
    ) == 1
    assert sum(
        case["case_group"] == "real_manila_purpleair"
        for case in approved_bundle["cases"]
    ) == 2
    assert sum(
        case["case_group"] == "synthetic_regulatory_boundary_cases"
        for case in approved_bundle["cases"]
    ) == 103
    for case in approved_bundle["cases"]:
        review = case["review"]
        assert review["status"] == "approved"
        assert review["approval_decision"] == "approved"
        assert review["reviewer"] == REVIEWER
        assert review["reviewed_at"] == REVIEWED_AT
        assert review["comments"] == APPROVAL_COMMENTS
        assert review["exceptions"] == []


def test_promoted_bundle_contains_no_production_observations(approved_bundle):
    forbidden_keys = {
        "current_compassaq_observation",
        "current_output",
        "implementation_observation",
        "implementation_observations",
    }

    def walk(value):
        if isinstance(value, dict):
            assert not forbidden_keys.intersection(key.lower() for key in value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(approved_bundle)


def test_real_manila_pipeline_matches_every_approved_expectation(
    approved_bundle,
    current_observations,
):
    approved_cases = {
        case["case_id"]: case
        for case in approved_bundle["cases"]
        if case["case_group"].startswith("real_manila_")
    }
    observations = {
        case["case_id"]: case for case in current_observations["cases"]
    }
    assert set(observations) == set(approved_cases)
    for case_id, approved_case in approved_cases.items():
        expected = approved_case["expected"]
        actual = observations[case_id]
        assert actual["sensor_ref"] == expected["sensor_ref"]
        assert actual["parameter_code"] == expected["parameter_code"]
        assert actual["represented_local_date"] == expected[
            "represented_local_date"
        ]
        assert actual["utc_window_started_at"] == expected[
            "utc_window_started_at"
        ]
        assert actual["utc_window_ended_at"] == expected["utc_window_ended_at"]
        counts = actual["qualified_observation_counts"]
        assert counts["valid_hour_count"] == expected["valid_hour_count"]
        assert counts["block_valid_hour_counts"] == expected[
            "block_valid_hour_counts"
        ]
        assert counts["maximum_consecutive_missing_hours"] == expected[
            "maximum_consecutive_missing_hours"
        ]
        concentration = actual["concentration_result"]
        assert Decimal(concentration["normalized_concentration"]) == Decimal(
            expected["normalized_concentration"]
        )
        assert Decimal(concentration["preprocessed_concentration"]) == Decimal(
            expected["preprocessed_concentration"]
        )
        result = actual["aqi_result"]
        assert Decimal(result["numeric_value"]) == Decimal(
            expected["numeric_value"]
        )
        assert result["category_code"] == expected["category_code"]
        assert result["calculation_status"] == expected["calculation_status"]
        assert result["eligibility_status"] == expected["eligibility_status"]


def test_api_serialization_matches_approved_real_manila_values(
    approved_bundle,
    current_observations,
):
    approved_cases = {
        case["case_id"]: case
        for case in approved_bundle["cases"]
        if case["case_group"].startswith("real_manila_")
    }
    observations = {
        case["case_id"]: case for case in current_observations["cases"]
    }
    for case_id, approved_case in approved_cases.items():
        expected = approved_case["expected"]
        api_result = observations[case_id]["api_serialization"]
        assert Decimal(str(api_result["numeric_value"])) == Decimal(
            expected["numeric_value"]
        )
        assert api_result["category_code"] == expected["category_code"]
        assert api_result["eligibility_status"] == expected[
            "eligibility_status"
        ]
        assert api_result["calculation_status"] == expected[
            "calculation_status"
        ]
        assert api_result["represented_local_date"] == expected[
            "represented_local_date"
        ]
        assert api_result["dominant_pollutants"] == []


def test_synthetic_regulatory_oracles_match_production_without_formula_duplication(
    approved_bundle,
    current_observations,
):
    approved_cases = {
        case["case_id"]: case
        for case in approved_bundle["cases"]
        if case["case_group"] == "synthetic_regulatory_boundary_cases"
    }
    observations = {
        case["case_id"]: case
        for case in current_observations["synthetic_cases"]
    }
    assert len(approved_cases) == 103
    assert set(observations) == set(approved_cases)
    for case_id, approved_case in approved_cases.items():
        _assert_result_matches(
            approved_case["expected"],
            observations[case_id]["production_result"],
        )


def test_approved_real_manila_values_remain_exact(approved_bundle):
    cases = {case["case_id"]: case for case in approved_bundle["cases"]}
    assert cases["openaq_pm25_completed_2026_08_02"]["expected"][
        "numeric_value"
    ] == "111.39"
    assert cases["purpleair_pm25_completed_2026_08_09"]["expected"][
        "numeric_value"
    ] == "31.80"
    assert cases["purpleair_pm10_completed_2026_08_09"]["expected"][
        "numeric_value"
    ] == "19.44"


def test_approved_synthetic_matrix_covers_every_required_regulatory_behavior(
    approved_bundle,
):
    cases = {
        case["case_id"]: case
        for case in approved_bundle["cases"]
        if case["case_group"] == "synthetic_regulatory_boundary_cases"
    }
    synthetic_candidates = json.loads(
        (ARTIFACT_ROOT / "synthetic-candidates.json").read_text(encoding="utf-8")
    )
    parameter_codes = {
        source_case["parameter_code"]
        for source_case in synthetic_candidates["cases"]
    }
    assert parameter_codes == {"pm25", "pm10", "o3", "no2", "so2", "co"}
    required_case_ids = {
        "pm25_24_hour_band_1_lower",
        "pm10_24_hour_band_6_upper",
        "so2_published_gap",
        "o3_1_hour_undefined_low",
        "o3_high_eight_hour_requires_one_hour",
        "o3_high_eight_hour_selects_one_hour",
        "co_category_only_emergency",
        "no2_undefined_low",
        "no2_category_only_emergency",
        "pm25_normal_condition_rejected",
        "so2_mass_conversion_rejected",
        "two_minute_hour_22_of_30",
        "two_minute_hour_23_of_30",
        "rolling_window_5_of_8",
        "rolling_window_6_of_8",
        "completed_day_17_of_24",
        "completed_day_18_of_24",
        "completed_day_block_only_5",
        "completed_day_three_consecutive_missing",
        "completed_day_missing_all",
        "deterministic_sensor_selection",
    }
    assert required_case_ids.issubset(cases)


def test_approved_conformance_run_is_offline_and_consumes_no_paid_points(
    current_observations,
):
    assert current_observations["safety"] == {
        "provider_calls": 0,
        "credential_reads": 0,
        "purpleair_points_consumed": 0,
        "paid_imports_enabled": False,
    }


def test_loader_rejects_candidate_and_tampered_philippine_bundles(tmp_path):
    candidate = json.loads(APPROVED_EXPECTATION.read_text(encoding="utf-8"))
    candidate["artifact_kind"] = "analyst_review_candidate"
    candidate_path = tmp_path / "approved-candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(PromotionError, match="not promoted"):
        load_approved_expectation(
            candidate_path,
            artifact_root=ARTIFACT_ROOT,
            reference_root=REFERENCE_ROOT,
        )

    approved = json.loads(APPROVED_EXPECTATION.read_text(encoding="utf-8"))
    approved["cases"][0]["expected"]["numeric_value"] = "999.00"
    tampered_path = tmp_path / "tampered-approved.json"
    tampered_path.write_text(json.dumps(approved), encoding="utf-8")
    with pytest.raises(PromotionError, match="independent source"):
        load_approved_expectation(
            tampered_path,
            artifact_root=ARTIFACT_ROOT,
            reference_root=REFERENCE_ROOT,
        )


def test_loader_rejects_tampered_bound_artifact_and_review_metadata(tmp_path):
    temporary_artifacts = tmp_path / "review"
    temporary_artifacts.mkdir()
    approved = json.loads(APPROVED_EXPECTATION.read_text(encoding="utf-8"))
    for binding in approved["source_artifacts"].values():
        source = ARTIFACT_ROOT / binding["file"]
        shutil.copyfile(source, temporary_artifacts / binding["file"])
    approved_path = tmp_path / "approved.json"
    approved_path.write_text(json.dumps(approved), encoding="utf-8")
    load_approved_expectation(
        approved_path,
        artifact_root=temporary_artifacts,
        reference_root=REFERENCE_ROOT,
    )

    real_candidate = temporary_artifacts / approved["source_artifacts"][
        "real_candidate"
    ]["file"]
    real_candidate.write_text(
        real_candidate.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )
    with pytest.raises(PromotionError, match="real_candidate hash"):
        load_approved_expectation(
            approved_path,
            artifact_root=temporary_artifacts,
            reference_root=REFERENCE_ROOT,
        )

    shutil.copyfile(
        ARTIFACT_ROOT
        / approved["source_artifacts"]["real_candidate"]["file"],
        real_candidate,
    )
    approved["cases"][0]["review"]["reviewer"] = "Unapproved reviewer"
    approved_path.write_text(json.dumps(approved), encoding="utf-8")
    with pytest.raises(PromotionError, match="reviewer differs"):
        load_approved_expectation(
            approved_path,
            artifact_root=temporary_artifacts,
            reference_root=REFERENCE_ROOT,
        )


def test_promotion_never_overwrites_existing_philippine_bundle(tmp_path):
    expected_root = tmp_path / "expected"
    destination = expected_root / "philippines_denr" / "approved.json"
    destination.parent.mkdir(parents=True)
    shutil.copyfile(APPROVED_EXPECTATION, destination)
    candidate_path = tmp_path / "approved-candidate.json"
    candidate = json.loads(APPROVED_EXPECTATION.read_text(encoding="utf-8"))
    candidate["artifact_kind"] = "analyst_review_candidate"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(PromotionError, match="will not overwrite"):
        promote_candidate(
            candidate_path,
            destination,
            artifact_root=ARTIFACT_ROOT,
            expected_root=expected_root,
            reference_root=REFERENCE_ROOT,
        )
