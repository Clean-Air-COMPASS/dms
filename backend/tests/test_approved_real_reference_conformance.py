from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

from reference_data.restricted import resolve_restricted_data_root


TOOLS_ROOT = Path(__file__).resolve().parent / "reference_data_tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from current_observations import build_current_observation_report  # noqa: E402
from discrepancy_report import build_approved_conformance_report  # noqa: E402
from promotion import PromotionError, load_approved_expectation  # noqa: E402
from source_facts import DEFAULT_REFERENCE_ROOT, sha256_file  # noqa: E402


PROVENANCE_ROOT = DEFAULT_REFERENCE_ROOT / "provenance" / "phase2i5"
ARTIFACT_ROOT = PROVENANCE_ROOT
EXPECTED_ROOT = DEFAULT_REFERENCE_ROOT / "expected"
PUBLIC_EXPECTATION = EXPECTED_ROOT / "public" / "openaq" / "phase2i5-approved.json"
RESTRICTED_EXPECTATION = (
    EXPECTED_ROOT / "restricted" / "purpleair" / "phase2i5-approved.json"
)
PUBLIC_EXPECTATION_SHA256 = "429e3242f807134204d71cd2cb0ddf81f6587f358a27cc035a4034542e6e3f52"
RESTRICTED_EXPECTATION_SHA256 = "2499ba09275d191cc341be3d2283bc59915fed77d49c48e40cb2a0432a717b82"
REVIEWER = "Spheros Environmental"
REVIEWED_AT = "2026-08-12T06:53:00-07:00"


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _case(bundle: dict, case_id: str) -> dict:
    return next(case for case in bundle["cases"] if case["case_id"] == case_id)


@pytest.fixture(scope="module")
def approved_bundles() -> dict[str, dict]:
    assert _sha256(PUBLIC_EXPECTATION) == PUBLIC_EXPECTATION_SHA256
    assert _sha256(RESTRICTED_EXPECTATION) == RESTRICTED_EXPECTATION_SHA256
    bundles = {
        "openaq": load_approved_expectation(
            PUBLIC_EXPECTATION,
            artifact_root=ARTIFACT_ROOT,
            reference_root=DEFAULT_REFERENCE_ROOT,
        )
    }
    restricted_root = resolve_restricted_data_root(
        checked_in_fallback=DEFAULT_REFERENCE_ROOT / "restricted" / "purpleair"
    )
    if restricted_root is not None:
        bundles["purpleair"] = load_approved_expectation(
            RESTRICTED_EXPECTATION,
            artifact_root=ARTIFACT_ROOT,
            reference_root=DEFAULT_REFERENCE_ROOT,
        )
    return bundles


@pytest.fixture(scope="module")
def current_observations(tmp_path_factory) -> dict:
    restricted_root = resolve_restricted_data_root(
        checked_in_fallback=DEFAULT_REFERENCE_ROOT / "restricted" / "purpleair"
    )
    database_path = tmp_path_factory.mktemp("approved-conformance") / "current.sqlite3"
    return build_current_observation_report(
        database_path=database_path,
        public_root=DEFAULT_REFERENCE_ROOT / "public" / "openaq",
        restricted_root=restricted_root,
    )


def test_promoted_bundles_are_complete_hash_linked_human_approvals(
    approved_bundles,
):
    public = approved_bundles["openaq"]
    assert len(public["cases"]) == 11
    expected_unique_case_count = 23 if "purpleair" in approved_bundles else 11
    if "purpleair" in approved_bundles:
        assert len(approved_bundles["purpleair"]["cases"]) == 13
    assert len(
        {
            case["case_id"]
            for bundle in approved_bundles.values()
            for case in bundle["cases"]
        }
    ) == expected_unique_case_count
    assert public["source_facts_sha256"] == (
        "39864ccdacbe628446b63ed1fa4b14ef3d7635656669221ef43a8c9df1cbafb2"
    )
    if "purpleair" in approved_bundles:
        restricted = approved_bundles["purpleair"]
        assert restricted["source_facts_sha256"] == public["source_facts_sha256"]
    assert public["worksheet_sha256"] == (
        "5f09c6e8c308501c64e165981ffcb8c1a2dc67fbd7b0d68ce1614e21b4c1b45b"
    )
    if "purpleair" in approved_bundles:
        assert restricted["worksheet_sha256"] == (
            "a199c22f53314c8ddc0aaa37fc4ca0815da2553b35b42303f85fad75490e6972"
        )
    for bundle in approved_bundles.values():
        assert bundle["artifact_kind"] == "analyst_approved_expectations"
        for case in bundle["cases"]:
            review = case["review"]
            assert review["status"] == "approved"
            assert review["approval_decision"] == "approved"
            assert review["reviewer"] == REVIEWER
            assert review["reviewed_at"] == REVIEWED_AT
            assert review["comments"].strip()
            assert review["derivation_sha256"]


def test_promoted_bundles_contain_no_current_compassaq_observations(
    approved_bundles,
):
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

    for bundle in approved_bundles.values():
        walk(bundle)


def test_full_offline_pipeline_matches_every_approved_expectation(
    approved_bundles,
    current_observations,
):
    reports = {
        dataset_name: build_approved_conformance_report(bundle, current_observations)
        for dataset_name, bundle in approved_bundles.items()
    }
    all_cases = [
        case for report in reports.values() for case in report["cases"]
    ]
    unexpected_mismatches = [
        case
        for case in all_cases
        if case["comparison_status"] == "mismatch"
        and case["case_id"] != "unavailable_zero_row_sensors"
    ]
    assert unexpected_mismatches == []
    assert all(
        case["comparison_status"] in {"match", "match_on_observed_fields"}
        for case in all_cases
        if case["case_id"] != "unavailable_zero_row_sensors"
    )

    zero_row_parts = [
        case for case in all_cases if case["case_id"] == "unavailable_zero_row_sensors"
    ]
    expected_zero_row_part_count = 2 if "purpleair" in approved_bundles else 1
    assert len(zero_row_parts) == expected_zero_row_part_count
    assert all(case["comparison_status"] == "mismatch" for case in zero_row_parts)
    assert all(
        case["resolution_status"] == "intentional_semantic_difference"
        for case in zero_row_parts
    )
    assert {
        (difference["candidate"], difference["current"])
        for case in zero_row_parts
        for difference in case["differing_fields"]
    } == {("insufficient_data", "missing_measurements")}


def test_api_serialization_matches_approved_numeric_expectations(
    approved_bundles,
    current_observations,
):
    public = approved_bundles["openaq"]
    api = current_observations["api_model_observations"]

    if "purpleair" not in approved_bundles:
        return
    restricted = approved_bundles["purpleair"]
    for case_id in (
        "openaq_ny_o3_window_2026_08_02T12",
        "openaq_ny_co_window_2026_08_02T12",
        "openaq_ny_no2_hour_2026_08_02T11",
        "openaq_ny_so2_window_2026_08_02T12",
    ):
        expected = _case(public, case_id)["expected"]
        actual = api[case_id]["results"][0]
        assert actual["numeric_value"] == expected["numeric_result"]
        assert actual["category_code"] == expected["category_code"]
        assert actual["coverage"]["coverage_status"] == expected["coverage_status"]
        assert any(
            reference["document_number"] == "EPA-403/B-26-003"
            and reference["publication_date"] == "2026-05"
            for reference in api[case_id]["methodology_references"]
        )

    completed_expected = _case(
        public, "openaq_rio_pm10_completed_2026_08_02"
    )["expected"]
    completed_actual = api["openaq_rio_pm10_completed_2026_08_02"][
        "device_series"
    ][0]["results"][0]
    assert completed_actual["numeric_value"] == completed_expected["numeric_result"]
    assert completed_actual["category_code"] == completed_expected["category_code"]
    assert completed_actual["valid_hour_count"] == 24

    for case_id in (
        "pa_ny_pm_nowcast_inputs",
        "pa_rio_pm_nowcast_inputs",
        "pa_manila_pm_nowcast_inputs",
    ):
        expected_results = {
            result["parameter_code"]: result
            for result in _case(restricted, case_id)["expected"]["results"]
        }
        for parameter_code, expected in expected_results.items():
            actual = api[case_id][parameter_code]["results"][0]
            assert actual["numeric_value"] == expected["numeric_result"]
            assert actual["category_code"] == expected["category_code"]
            assert actual["coverage"]["coverage_status"] == expected["coverage_status"]
            actual_pollutant = actual["pollutant_results"][0]
            assert actual_pollutant["normalized_concentration"] == pytest.approx(
                float(expected["input_concentration"]), abs=1e-12
            )


def test_api_serialization_matches_approved_eea_hour_and_partial_coverage(
    approved_bundles,
    current_observations,
):
    api = current_observations["api_model_observations"]
    cases = {
        case["case_id"]: case
        for bundle in approved_bundles.values()
        for case in bundle["cases"]
    }
    for case_id in (
        "eea_rio_2026_08_02T11",
        "eea_pa_manila_2026_08_08T03",
        "eea_openaq_manila_2026_08_02T11",
    ):
        if case_id not in cases:
            continue
        expected = cases[case_id]["expected"]
        actual = api[case_id]["results"][0]
        expected_observed_at = (
            "2026-08-08T03:00:00Z"
            if case_id == "eea_pa_manila_2026_08_08T03"
            else "2026-08-02T11:00:00Z"
        )
        assert actual["observed_at"] == expected_observed_at
        assert actual["category_code"] == expected["category_code"]
        assert actual["dominant_pollutants"] == expected["dominant_pollutants"]
        assert actual["coverage"]["coverage_status"] == expected["coverage_status"]
        assert actual["coverage"]["missing_pollutants"] == expected.get(
            "missing_pollutants", []
        )
        actual_pollutants = {
            result["parameter_code"]: result
            for result in actual["pollutant_results"]
        }
        for result in expected["results"]:
            assert actual_pollutants[result["parameter_code"]][
                "normalized_concentration"
            ] == pytest.approx(float(result["normalized_concentration"]), abs=1e-12)


def test_unsupported_conversion_and_zero_rows_preserve_approved_diagnostics(
    approved_bundles,
    current_observations,
):
    unsupported = current_observations["service_observations"][
        "openaq_rio_epa_mass_units_unavailable"
    ]
    assert all(
        "conversion_not_supported" in rows[0]["blocking_reasons"]
        for rows in unsupported.values()
    )
    expected_unsupported = _case(
        approved_bundles["openaq"], "openaq_rio_epa_mass_units_unavailable"
    )["expected"]
    assert expected_unsupported["availability"] == "unavailable"
    assert expected_unsupported["exclusion_reason"] == "conversion_not_supported"

    observation_keys = ["openaq_ny_pm10_zero_rows"]
    if "purpleair" in approved_bundles:
        observation_keys.append("purpleair_zero_row_sensor_198733")
    for observation_key in observation_keys:
        actual = current_observations["service_observations"][observation_key][0]
        evaluation = actual["candidate_sensor_evaluations"][0]
        assert evaluation["exclusion_reason"] == "missing_measurements"
        assert actual["calculation"]["exclusion_reason"] == "no_eligible_sensor_stream"
        assert evaluation["valid_sample_count"] == 0


def test_approved_conformance_run_is_offline_and_consumes_no_paid_points(
    current_observations,
):
    assert current_observations["provider_calls"] == 0
    assert current_observations["credential_reads"] == 0
    assert current_observations["purpleair_points_consumed"] == 0


def test_loader_rejects_candidates_implementation_output_and_tampered_bundle(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        json.dumps({"artifact_kind": "analyst_review_candidate"}),
        encoding="utf-8",
    )
    with pytest.raises(PromotionError, match="not promoted"):
        load_approved_expectation(
            candidate_path,
            artifact_root=ARTIFACT_ROOT,
        )
    implementation_path = tmp_path / "current-observations.json"
    implementation_path.write_text(
        json.dumps({"artifact_kind": "implementation_observations"}),
        encoding="utf-8",
    )
    with pytest.raises(PromotionError, match="not promoted"):
        load_approved_expectation(
            implementation_path,
            artifact_root=ARTIFACT_ROOT,
        )
    with pytest.raises(PromotionError, match="not promoted"):
        load_approved_expectation(
            ARTIFACT_ROOT / "worksheet-public-openaq.json",
            artifact_root=ARTIFACT_ROOT,
        )

    tampered_path = tmp_path / "tampered-approved.json"
    tampered = json.loads(PUBLIC_EXPECTATION.read_text(encoding="utf-8"))
    tampered["cases"][0]["expected"]["availability"] = "available"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(PromotionError, match="expected result differs"):
        load_approved_expectation(tampered_path, artifact_root=ARTIFACT_ROOT)


def test_loader_rejects_tampered_source_fact_and_derivation(tmp_path):
    temporary_artifacts = tmp_path / "review"
    temporary_artifacts.mkdir()
    for name in ("source-facts.json", "worksheet-public-openaq.json"):
        shutil.copyfile(ARTIFACT_ROOT / name, temporary_artifacts / name)
    approved = json.loads(PUBLIC_EXPECTATION.read_text(encoding="utf-8"))
    approved_path = tmp_path / "approved.json"
    approved_path.write_text(json.dumps(approved), encoding="utf-8")

    source_facts_path = temporary_artifacts / "source-facts.json"
    source_facts_path.write_text(
        source_facts_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )
    with pytest.raises(PromotionError, match="Source-fact file hash"):
        load_approved_expectation(approved_path, artifact_root=temporary_artifacts)

    shutil.copyfile(
        ARTIFACT_ROOT / "source-facts.json", temporary_artifacts / "source-facts.json"
    )
    approved["cases"][0]["derivation"]["steps"].append({"operation": "tampered"})
    approved_path.write_text(json.dumps(approved), encoding="utf-8")
    with pytest.raises(PromotionError, match="derivation hash mismatch"):
        load_approved_expectation(approved_path, artifact_root=temporary_artifacts)
