from __future__ import annotations

import ast
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


TOOLS_ROOT = Path(__file__).resolve().parent / "reference_data_tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from promotion import (  # noqa: E402
    PromotionError,
    load_approved_expectation,
    promote_candidate,
)
from source_facts import (  # noqa: E402
    DEFAULT_REFERENCE_ROOT,
    canonical_json_sha256,
    extract_source_facts,
    read_frozen_dataset,
    sha256_file,
)
from discrepancy_report import build_discrepancy_report  # noqa: E402
from review_package import build_review_package, review_package_markdown  # noqa: E402
from worksheet import build_candidate_worksheet, worksheet_markdown  # noqa: E402
from current_observations import build_current_observation_report  # noqa: E402
from reference_data.fixture_io import ReferenceFixtureError  # noqa: E402
from reference_data.restricted import resolve_restricted_data_root  # noqa: E402
from api.main import app  # noqa: E402
from db import get_session  # noqa: E402
import models  # noqa: E402


PUBLIC_ROOT = DEFAULT_REFERENCE_ROOT / "public" / "openaq"
CHECKED_IN_RESTRICTED_ROOT = DEFAULT_REFERENCE_ROOT / "restricted" / "purpleair"
EXPECTED_ROOT = DEFAULT_REFERENCE_ROOT / "expected"
REVIEW_ARTIFACT_ROOT = DEFAULT_REFERENCE_ROOT / "provenance" / "phase2i5"
PHILIPPINES_REVIEW_ARTIFACT_ROOT = (
    DEFAULT_REFERENCE_ROOT / "provenance" / "philippines_denr"
)
APPROVED_PUBLIC_PATH = EXPECTED_ROOT / "public" / "openaq" / "phase2i5-approved.json"
APPROVED_RESTRICTED_PATH = (
    EXPECTED_ROOT / "restricted" / "purpleair" / "phase2i5-approved.json"
)
APPROVED_PHILIPPINES_PATH = (
    EXPECTED_ROOT
    / "philippines_denr"
    / "denr-emb-aqi-2021-approved-v1.json"
)
PHILIPPINES_SCHEMA_PATH = EXPECTED_ROOT / "philippines_denr" / "schema.json"


@pytest.fixture(scope="module")
def source_fact_report() -> dict:
    restricted_root = resolve_restricted_data_root(
        checked_in_fallback=CHECKED_IN_RESTRICTED_ROOT
    )
    dataset_roots = {"openaq": PUBLIC_ROOT}
    if restricted_root is not None:
        dataset_roots["purpleair"] = restricted_root
    return extract_source_facts(DEFAULT_REFERENCE_ROOT, dataset_roots=dataset_roots)


@pytest.fixture(scope="module")
def current_real_database(tmp_path_factory):
    restricted_root = resolve_restricted_data_root(
        checked_in_fallback=CHECKED_IN_RESTRICTED_ROOT
    )
    database_path = tmp_path_factory.mktemp("phase-2i5-current") / "current.sqlite3"
    report = build_current_observation_report(
        database_path=database_path,
        public_root=PUBLIC_ROOT,
        restricted_root=restricted_root,
    )
    return database_path, report, restricted_root


def _case(report: dict, case_id: str) -> dict:
    return next(case for case in report["cases"] if case["case_id"] == case_id)


@pytest.fixture(scope="module")
def candidate_worksheets(source_fact_report):
    worksheets = {
        "openaq": build_candidate_worksheet(
            source_fact_report,
            source_facts_file="source-facts.json",
            source_facts_sha256="source-facts-review-hash",
            dataset_name="openaq",
        )
    }
    if "purpleair" not in source_fact_report["absent_datasets"]:
        worksheets["purpleair"] = build_candidate_worksheet(
            source_fact_report,
            source_facts_file="source-facts.json",
            source_facts_sha256="source-facts-review-hash",
            dataset_name="purpleair",
        )
    return worksheets


def test_source_fact_extractor_has_no_production_or_network_imports():
    source_path = TOOLS_ROOT / "source_facts.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
    assert not imported_modules.intersection(
        {
            "api",
            "db",
            "httpx",
            "models",
            "reference_data",
            "requests",
            "services",
            "socket",
            "sources",
        }
    )
    assert imported_modules <= {
        "__future__",
        "argparse",
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "typing",
        "zoneinfo",
    }


def test_reference_text_hash_normalizes_only_checkout_line_endings(tmp_path):
    lf_path = tmp_path / "lf.json"
    crlf_path = tmp_path / "crlf.json"
    changed_whitespace_path = tmp_path / "changed-whitespace.json"

    lf_content = b'{\n  "status": "approved"\n}\n'
    lf_path.write_bytes(lf_content)
    crlf_path.write_bytes(lf_content.replace(b"\n", b"\r\n"))
    changed_whitespace_path.write_bytes(
        b'{\r\n  "status": "approved" \r\n}\r\n'
    )

    expected_hash = sha256(lf_content).hexdigest()
    assert sha256_file(lf_path) == expected_hash
    assert sha256_file(crlf_path) == expected_hash
    assert sha256_file(changed_whitespace_path) != expected_hash


def test_public_fixture_source_facts_are_exact(source_fact_report):
    summary = _case(source_fact_report, "fixture_openaq_2i4a")["facts"]
    assert summary["measurement_count"] == 1_939
    assert summary["device_count"] == 4
    assert summary["sensor_count"] == 13
    assert summary["active_sensor_count"] == 12
    assert summary["validity_counts"] == {"True": 1_939}
    assert summary["provider_has_flags_counts"] == {"False": 1_939}
    assert summary["measurements_sha256"] == (
        "dd93fda403acb4ad59e6819977c3e157c36203e12447617345fc0edd5c9d8ed3"
    )
    documented_hourly = [
        sensor
        for sensor in summary["sensors"]
        if sensor["aggregation_period_code"] == "1h"
        and sensor["measurement_count"] > 0
    ]
    assert len(documented_hourly) == 12
    assert all(sensor["expected_frequency_seconds"] == 3600 for sensor in documented_hourly)
    zero_row = next(
        sensor for sensor in summary["sensors"] if sensor["sensor_ref"] == "openaq-sensor-1099"
    )
    assert zero_row["measurement_count"] == 0
    assert zero_row["aggregation_period_code"] is None
    assert zero_row["measurement_metadata_status"] == "unknown_or_inconsistent"


def test_restricted_fixture_source_facts_are_exact(source_fact_report):
    if "purpleair" in source_fact_report["absent_datasets"]:
        pytest.skip("restricted PurpleAir reference data is unavailable")
    summary = _case(source_fact_report, "fixture_purpleair_2i4c2")["facts"]
    assert summary["measurement_count"] == 12_938
    assert summary["device_count"] == 4
    assert summary["sensor_count"] == 8
    assert summary["active_sensor_count"] == 6
    assert summary["validity_counts"] == {"True": 12_938}
    assert summary["provider_validity_status_counts"] == {"not_supplied": 12_938}
    assert summary["measurements_sha256"] == (
        "aba35bb8e380a2e3343af724fa565b849f717f3783b006d9512405af3cd55028"
    )
    assert {
        sensor["sensor_ref"]
        for sensor in summary["sensors"]
        if sensor["measurement_count"] > 0
    } == {
        "purpleair-159361-pm25",
        "purpleair-159361-pm10",
        "purpleair-175407-pm25",
        "purpleair-175407-pm10",
        "purpleair-99177-pm25",
        "purpleair-99177-pm10",
    }
    assert {
        sensor["sensor_ref"]
        for sensor in summary["sensors"]
        if sensor["measurement_count"] == 0
    } == {"purpleair-198733-pm25", "purpleair-198733-pm10"}


def test_provider_timestamps_and_source_references_are_preserved():
    restricted_root = resolve_restricted_data_root(
        checked_in_fallback=CHECKED_IN_RESTRICTED_ROOT
    )
    if restricted_root is None:
        pytest.skip("restricted PurpleAir reference data is unavailable")
    dataset = read_frozen_dataset("purpleair", restricted_root)
    assert all(row["provider_observation_ref"] for row in dataset.measurements)
    assert all(row["source_page"] == 1 for row in dataset.measurements)
    assert all(
        datetime.fromtimestamp(int(row["provider_timestamp"]), tz=timezone.utc)
        == datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        for row in dataset.measurements
    )


def test_manila_provenance_never_claims_direct_airgradient_api(source_fact_report):
    facts = _case(
        source_fact_report, "provenance_manila_airgradient_via_openaq"
    )["facts"]
    assert facts["device"]["hardware_provider"] == "AirGradient"
    assert facts["device"]["owner_name"] == "Manila Observatory"
    assert facts["provider"] == "OpenAQ"
    assert facts["fixture_role"] == "CompassAQ frozen fixture"
    assert facts["direct_airgradient_api_data"] is False
    assert {entry["role"]: entry["provider"] for entry in facts["provider_chain"]}[
        "transport"
    ] == "OpenAQ"


def test_ordinary_and_aqi_hour_assignments_remain_distinct(source_fact_report):
    if "purpleair" in source_fact_report["absent_datasets"]:
        pytest.skip("restricted PurpleAir reference data is unavailable")
    ordinary = _case(source_fact_report, "pa_ny_pm25_ordinary_boundary")["facts"]
    ordinary_result = ordinary["sensor_results"][0]
    assert ordinary_result["included_count"] == 30
    assert ordinary_result["included_observations"][0]["observed_at"] == "2026-08-08T01:00:35Z"
    anchored = _case(source_fact_report, "pa_ny_pm_boundary_assignment")["facts"]
    for sensor in anchored["sensor_results"]:
        assert sensor["completeness"]["numerator"] == 29
        assert sensor["completeness"]["denominator"] == 30
        assert sensor["completeness"]["required_count"] == 23
        assert sensor["completeness"]["off_frequency_positions"] == [
            "2026-08-08T01:00:35Z"
        ]
        assert sensor["completeness"]["missing_positions"] == [
            "2026-08-08T02:00:00Z"
        ]


@pytest.mark.parametrize(
    ("case_id", "expected_count", "missing_positions", "duplicate_count"),
    (
        ("pa_ny_pm_full", 30, [], 0),
        (
            "pa_ny_pm_duplicate_positions",
            27,
            [
                "2026-08-10T03:14:00Z",
                "2026-08-10T03:46:00Z",
                "2026-08-10T04:00:00Z",
            ],
            3,
        ),
        (
            "pa_rio_pm_minor_gaps",
            25,
            [
                "2026-08-10T16:44:00Z",
                "2026-08-10T16:46:00Z",
                "2026-08-10T16:50:00Z",
                "2026-08-10T16:56:00Z",
                "2026-08-10T16:58:00Z",
            ],
            0,
        ),
        ("pa_manila_pm_irregular", 29, ["2026-08-08T03:32:00Z"], 0),
    ),
)
def test_real_purpleair_hour_position_facts(
    source_fact_report, case_id, expected_count, missing_positions, duplicate_count
):
    if "purpleair" in source_fact_report["absent_datasets"]:
        pytest.skip("restricted PurpleAir reference data is unavailable")
    for sensor in _case(source_fact_report, case_id)["facts"]["sensor_results"]:
        assert sensor["completeness"]["numerator"] == expected_count
        assert sensor["completeness"]["required_count"] == 23
        assert sensor["completeness"]["missing_positions"] == missing_positions
        assert len(sensor["completeness"]["duplicate_positions"]) == duplicate_count
        assert sensor["completeness"]["coverage_status"] == "eligible"


@pytest.mark.parametrize(
    ("case_id", "expected_counts"),
    (
        ("pa_ny_pm_nowcast_inputs", [30, 30, 30, 30, 30, 30, 30, 29, 27, 29, 29, 27]),
        ("pa_rio_pm_nowcast_inputs", [30, 25, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30]),
        ("pa_manila_pm_nowcast_inputs", [29, 29, 30, 30, 30, 29, 29, 30, 29, 30, 30, 30]),
    ),
)
def test_real_purpleair_nowcast_input_counts(source_fact_report, case_id, expected_counts):
    if "purpleair" in source_fact_report["absent_datasets"]:
        pytest.skip("restricted PurpleAir reference data is unavailable")
    hours = _case(source_fact_report, case_id)["facts"]["hours_most_recent_first"]
    for pollutant_position in (0, 1):
        assert [
            hour["sensor_results"][pollutant_position]["completeness"]["numerator"]
            for hour in hours
        ] == expected_counts


def test_completed_day_source_windows(source_fact_report):
    if "purpleair" not in source_fact_report["absent_datasets"]:
        purpleair = _case(
            source_fact_report, "pa_ny_pm25_completed_2026_08_09"
        )["facts"]
        assert purpleair["utc_window"] == {
            "started_at": "2026-08-09T04:00:00Z",
            "ended_at": "2026-08-10T04:00:00Z",
        }
        counts = [
            hour["sensor_results"][0]["completeness"]["numerator"]
            for hour in purpleair["hours"]
        ]
        assert Counter(counts) == Counter({29: 22, 27: 2})
    openaq = _case(
        source_fact_report, "openaq_rio_pm10_completed_2026_08_02"
    )["facts"]
    assert openaq["utc_window"] == {
        "started_at": "2026-08-02T03:00:00Z",
        "ended_at": "2026-08-03T03:00:00Z",
    }
    assert openaq["sensor_results"][0]["observed_count"] == 24
    assert openaq["sensor_results"][0]["missing_interval_end_positions"] == []


def test_openaq_gas_windows_and_unsupported_mass_units(source_fact_report):
    expected = {
        "openaq_ny_o3_window_2026_08_02T12": (
            8,
            [],
            ["0.038", "0.038", "0.035", "0.037", "0.038", "0.039", "0.037", "0.037"],
        ),
        "openaq_ny_co_window_2026_08_02T12": (
            6,
            ["2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z"],
            ["0.4"] * 6,
        ),
        "openaq_ny_no2_hour_2026_08_02T11": (1, [], ["0.015"]),
        "openaq_ny_so2_window_2026_08_02T12": (23, ["2026-08-02T10:00:00Z"], None),
    }
    for case_id, (count, missing, values) in expected.items():
        result = _case(source_fact_report, case_id)["facts"]["sensor_results"][0]
        assert result["observed_count"] == count
        assert result["missing_interval_end_positions"] == missing
        if values is not None:
            assert [item["decimal_value"] for item in result["accepted_observations"]] == values

    unsupported = _case(
        source_fact_report, "openaq_rio_epa_mass_units_unavailable"
    )["facts"]
    assert unsupported["expected_unavailability_reason"] == "conversion_not_supported"
    assert [
        result["observations"][0]["unit"] for result in unsupported["sensor_results"]
    ] == ["µg/m³", "µg/m³", "µg/m³"]


def test_eea_represented_hour_source_values(source_fact_report):
    rio = _case(source_fact_report, "eea_rio_2026_08_02T11")["facts"]
    assert rio["represented_utc_window"] == {
        "started_at": "2026-08-02T11:00:00Z",
        "ended_at": "2026-08-02T12:00:00Z",
    }
    assert [
        result["observations"][0]["decimal_value"] for result in rio["sensor_results"]
    ] == ["11.33", "22.5", "28.16", "40.55", "11.99"]
    assert all(
        result["observations"][0]["provider_period"]["datetimeFrom"]["utc"]
        == "2026-08-02T11:00:00Z"
        for result in rio["sensor_results"]
    )
    manila = _case(
        source_fact_report, "eea_openaq_manila_2026_08_02T11"
    )["facts"]
    assert manila["sensor_results"][0]["observations"][0]["decimal_value"] == "48.5"


def test_restricted_root_prefers_private_then_falls_back(monkeypatch, tmp_path):
    private = tmp_path / "private"
    fallback = tmp_path / "checked-in"
    private.mkdir()
    fallback.mkdir()
    monkeypatch.setenv("COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT", str(private))
    assert resolve_restricted_data_root(checked_in_fallback=fallback) == private.resolve()
    monkeypatch.setenv(
        "COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT", str(tmp_path / "absent-private")
    )
    assert resolve_restricted_data_root(checked_in_fallback=fallback) == fallback.resolve()


def test_restricted_root_requirement_fails_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT", raising=False)
    monkeypatch.setenv("REQUIRE_RESTRICTED_REFERENCE_DATA", "true")
    with pytest.raises(ReferenceFixtureError, match="Restricted reference data is required"):
        resolve_restricted_data_root(checked_in_fallback=tmp_path / "absent")


def _write_approved_candidate(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, dict]:
    artifact_root = tmp_path / "review-artifacts"
    artifact_root.mkdir(parents=True)
    reference_root = tmp_path / "reference-data"
    fixture_root = reference_root / "public" / "openaq"
    fixture_root.mkdir(parents=True)
    measurements_path = fixture_root / "measurements.jsonl"
    measurements_path.write_text('{"reviewed": true}\n', encoding="utf-8")
    measurements_sha256 = sha256_file(measurements_path)
    (fixture_root / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "test-dataset",
                "measurements_file": "measurements.jsonl",
                "measurements_sha256": measurements_sha256,
            }
        ),
        encoding="utf-8",
    )
    source_facts = {
        "artifact_kind": "independently_extracted_source_facts",
        "oracle_status": "source_evidence_only_not_expected_results",
        "datasets": {
            "openaq": {
                "dataset_id": "test-dataset",
                "measurements_sha256": measurements_sha256,
            }
        },
    }
    source_path = artifact_root / "source-facts.json"
    source_path.write_text(json.dumps(source_facts), encoding="utf-8")
    derivation = {"steps": [{"operation": "independent arithmetic"}], "absolute_tolerance": "0.000000000001"}
    expected = {
        "availability": "available",
        "numeric_result": 1,
        "category_code": "test",
        "exclusion_reason": None,
        "coverage_status": "complete",
    }
    worksheet = {
        "artifact_kind": "analyst_derivation_worksheet",
        "source_facts_sha256": sha256_file(source_path),
        "dataset_name": "openaq",
        "dataset_id": "test-dataset",
        "access_classification": "public_frozen_reference_data",
        "cases": [
            {
                "case_id": "reviewed-case",
                "source_fact_hash": "b" * 64,
                "derivation": derivation,
                "candidate_expected": {"status": "review_candidate_not_approved", **expected},
            }
        ],
    }
    worksheet_path = artifact_root / "worksheet.json"
    worksheet_path.write_text(json.dumps(worksheet), encoding="utf-8")
    case = {
        "case_id": "reviewed-case",
        "calculation_type": "test",
        "source": {"source_fact_hash": "b" * 64},
        "input_window": {},
        "source_observations": [],
        "completeness": {
            "numerator": 1,
            "denominator": 1,
            "required_count": 1,
            "fraction": "1",
            "missing_positions": [],
            "duplicate_positions": [],
            "off_frequency_positions": [],
            "status": "complete",
        },
        "methodology": {
            "methodology_code": "test",
            "methodology_version": "1",
            "reference_ids": ["test-reference"],
        },
        "derivation": derivation,
        "expected": expected,
        "review": {
            "status": "approved",
            "reviewer": "Air Quality Analyst",
            "reviewed_at": "2026-08-12T00:00:00Z",
            "derivation_sha256": canonical_json_sha256(derivation),
            "comments": "Independently checked.",
            "approval_decision": "approved",
        },
    }
    candidate = {
        "schema_version": "2i.5-expected-1",
        "artifact_kind": "analyst_review_candidate",
        "dataset_name": "openaq",
        "access_classification": "public_frozen_reference_data",
        "dataset_id": "test-dataset",
        "source_measurements_sha256": measurements_sha256,
        "source_facts_file": "source-facts.json",
        "source_facts_sha256": sha256_file(source_path),
        "worksheet_file": "worksheet.json",
        "worksheet_sha256": sha256_file(worksheet_path),
        "cases": [case],
    }
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    return candidate_path, artifact_root, tmp_path / "expected", reference_root, candidate


def test_promotion_accepts_only_approved_hash_matching_candidates(tmp_path):
    candidate_path, artifact_root, expected_root, reference_root, _ = (
        _write_approved_candidate(tmp_path)
    )
    destination = expected_root / "public" / "openaq" / "approved.json"
    promote_candidate(
        candidate_path,
        destination,
        artifact_root=artifact_root,
        expected_root=expected_root,
        reference_root=reference_root,
    )
    approved = load_approved_expectation(
        destination,
        artifact_root=artifact_root,
        reference_root=reference_root,
    )
    assert approved["artifact_kind"] == "analyst_approved_expectations"
    assert approved["cases"][0]["review"]["status"] == "approved"
    with pytest.raises(PromotionError, match="will not overwrite"):
        promote_candidate(
            candidate_path,
            destination,
            artifact_root=artifact_root,
            expected_root=expected_root,
            reference_root=reference_root,
        )


def test_promotion_refuses_unapproved_stale_or_current_output(tmp_path):
    candidate_path, artifact_root, expected_root, reference_root, candidate = (
        _write_approved_candidate(tmp_path)
    )
    destination = expected_root / "approved.json"

    candidate["cases"][0]["review"]["status"] = "candidate"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(PromotionError, match="not analyst-approved"):
        promote_candidate(
            candidate_path,
            destination,
            artifact_root=artifact_root,
            expected_root=expected_root,
            reference_root=reference_root,
        )

    candidate["cases"][0]["review"]["status"] = "approved"
    candidate["current_output"] = {"numeric_value": 1}
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(PromotionError, match="mix current CompassAQ output"):
        promote_candidate(
            candidate_path,
            destination,
            artifact_root=artifact_root,
            expected_root=expected_root,
            reference_root=reference_root,
        )

    candidate.pop("current_output")
    candidate["worksheet_sha256"] = "b" * 64
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(PromotionError, match="Worksheet file hash"):
        promote_candidate(
            candidate_path,
            destination,
            artifact_root=artifact_root,
            expected_root=expected_root,
            reference_root=reference_root,
        )


def test_promotion_fails_closed_for_tampered_expected_derivation_and_fixture(tmp_path):
    candidate_path, artifact_root, expected_root, reference_root, candidate = (
        _write_approved_candidate(tmp_path)
    )
    destination = expected_root / "public" / "openaq" / "approved.json"

    candidate["cases"][0]["expected"]["numeric_result"] = 999
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(PromotionError, match="expected result differs"):
        promote_candidate(
            candidate_path,
            destination,
            artifact_root=artifact_root,
            expected_root=expected_root,
            reference_root=reference_root,
        )

    _, _, _, _, candidate = _write_approved_candidate(tmp_path / "derivation")
    candidate_path = tmp_path / "derivation" / "candidate.json"
    artifact_root = tmp_path / "derivation" / "review-artifacts"
    expected_root = tmp_path / "derivation" / "expected"
    reference_root = tmp_path / "derivation" / "reference-data"
    candidate["cases"][0]["derivation"]["steps"][0]["operation"] = "tampered"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(PromotionError, match="derivation hash mismatch"):
        promote_candidate(
            candidate_path,
            expected_root / "approved.json",
            artifact_root=artifact_root,
            expected_root=expected_root,
            reference_root=reference_root,
        )

    candidate_path, artifact_root, expected_root, reference_root, _ = (
        _write_approved_candidate(tmp_path / "fixture")
    )
    measurements_path = reference_root / "public" / "openaq" / "measurements.jsonl"
    measurements_path.write_text('{"reviewed": false}\n', encoding="utf-8")
    with pytest.raises(PromotionError, match="Frozen measurement checksum"):
        promote_candidate(
            candidate_path,
            expected_root / "approved.json",
            artifact_root=artifact_root,
            expected_root=expected_root,
            reference_root=reference_root,
        )


def test_expected_tree_contains_only_schema_and_approved_result_records():
    json_files = sorted(EXPECTED_ROOT.rglob("*.json"))
    assert json_files == sorted(
        [
            EXPECTED_ROOT / "schema.json",
            APPROVED_PUBLIC_PATH,
            APPROVED_RESTRICTED_PATH,
            APPROVED_PHILIPPINES_PATH,
            PHILIPPINES_SCHEMA_PATH,
        ]
    )
    schema = json.loads((EXPECTED_ROOT / "schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["artifact_kind"]["const"] == "analyst_approved_expectations"
    review_statuses = schema["$defs"]["case"]["properties"]["review"][
        "properties"
    ]["status"]["enum"]
    assert review_statuses == [
        "candidate",
        "approved",
        "rejected",
    ]
    public = load_approved_expectation(
        APPROVED_PUBLIC_PATH, artifact_root=REVIEW_ARTIFACT_ROOT
    )
    assert len(public["cases"]) == 11
    bundles = [public]
    restricted_root = resolve_restricted_data_root(
        checked_in_fallback=CHECKED_IN_RESTRICTED_ROOT
    )
    if restricted_root is not None:
        restricted = load_approved_expectation(
            APPROVED_RESTRICTED_PATH, artifact_root=REVIEW_ARTIFACT_ROOT
        )
        assert len(restricted["cases"]) == 13
        bundles.append(restricted)
    philippines = load_approved_expectation(
        APPROVED_PHILIPPINES_PATH,
        artifact_root=PHILIPPINES_REVIEW_ARTIFACT_ROOT,
    )
    assert len(philippines["cases"]) == 106
    bundles.append(philippines)
    assert all(
        case["review"]["status"] == "approved"
        for bundle in bundles
        for case in bundle["cases"]
    )


def test_candidate_worksheet_enumerates_evidence_and_unapproved_independent_derivations(
    source_fact_report, tmp_path
):
    source_path = tmp_path / "source-facts.json"
    source_path.write_text(json.dumps(source_fact_report, default=str), encoding="utf-8")
    worksheet = build_candidate_worksheet(
        source_fact_report,
        source_facts_file="source-facts.json",
        source_facts_sha256=sha256_file(source_path),
        dataset_name="openaq",
    )
    assert worksheet["artifact_kind"] == "analyst_derivation_worksheet"
    assert worksheet["oracle_status"] == "candidate_not_approved"
    assert all(
        case["candidate_expected"]["status"] == "review_candidate_not_approved"
        for case in worksheet["cases"]
    )
    assert all(case["review"]["status"] == "candidate" for case in worksheet["cases"])
    assert all(case["review"]["reviewer"] is None for case in worksheet["cases"])
    assert all(case["review"]["approval_decision"] == "pending" for case in worksheet["cases"])
    assert all(case["candidate_derivation_sha256"] for case in worksheet["cases"])
    ozone = next(
        case
        for case in worksheet["cases"]
        if case["case_id"] == "openaq_ny_o3_window_2026_08_02T12"
    )
    assert len(ozone["source_observations"]) == 8
    assert ozone["candidate_expected"]["numeric_result"] == 34
    assert ozone["candidate_expected"]["category_code"] == "good"
    markdown = worksheet_markdown(worksheet)
    assert "no AQI value or category is approved" in markdown
    assert "Independent derivation" in markdown
    assert "openaq:1098:" in markdown


def test_independent_derivation_module_has_no_production_or_network_imports():
    source_path = TOOLS_ROOT / "independent_derivations.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
    assert not imported_modules.intersection(
        {
            "api",
            "db",
            "httpx",
            "models",
            "reference_data",
            "requests",
            "services",
            "socket",
            "sources",
        }
    )
    assert imported_modules <= {"__future__", "decimal", "typing"}


def test_public_review_candidates_have_explicit_decimal_derivations(candidate_worksheets):
    worksheet = candidate_worksheets["openaq"]
    expected = {
        "openaq_rio_pm10_completed_2026_08_02": (29, "good", "complete"),
        "openaq_ny_o3_window_2026_08_02T12": (34, "good", "complete"),
        "openaq_ny_co_window_2026_08_02T12": (5, "good", "partial"),
        "openaq_ny_no2_hour_2026_08_02T11": (14, "good", "complete"),
        "openaq_ny_so2_window_2026_08_02T12": (3, "good", "partial"),
    }
    for case_id, (numeric_result, category_code, coverage_status) in expected.items():
        case = _case(worksheet, case_id)
        candidate = case["candidate_expected"]
        assert candidate["numeric_result"] == numeric_result
        assert candidate["category_code"] == category_code
        assert candidate["coverage_status"] == coverage_status
        assert case["derivation"]["decimal_arithmetic"] is True
        assert case["candidate_derivation_sha256"] == canonical_json_sha256(
            case["derivation"]
        )

    unsupported = _case(
        worksheet, "openaq_rio_epa_mass_units_unavailable"
    )["candidate_expected"]
    assert unsupported["availability"] == "unavailable"
    assert unsupported["exclusion_reason"] == "conversion_not_supported"
    assert {result["parameter_code"] for result in unsupported["results"]} == {
        "o3",
        "no2",
        "so2",
    }


def test_restricted_review_candidates_cover_nowcast_completed_day_and_eea(
    candidate_worksheets,
):
    if "purpleair" not in candidate_worksheets:
        pytest.skip("restricted PurpleAir reference data is unavailable")
    worksheet = candidate_worksheets["purpleair"]
    expected_nowcast = {
        "pa_ny_pm_nowcast_inputs": {"pm25": 52, "pm10": 9},
        "pa_rio_pm_nowcast_inputs": {"pm25": 28, "pm10": 6},
        "pa_manila_pm_nowcast_inputs": {"pm25": 69, "pm10": 22},
    }
    for case_id, expected_results in expected_nowcast.items():
        candidate = _case(worksheet, case_id)["candidate_expected"]
        assert candidate["coverage_status"] == "complete"
        observed = {
            result["parameter_code"]: result["numeric_result"]
            for result in candidate["results"]
        }
        assert observed == expected_results
        assert all(
            len(result["hourly_inputs_most_recent_first"]) == 12
            for result in candidate["results"]
        )

    completed = _case(
        worksheet, "pa_ny_pm25_completed_2026_08_09"
    )["candidate_expected"]
    assert completed["numeric_result"] == 73
    assert completed["category_code"] == "moderate"
    assert completed["results"][0]["daily_mean_before_final_preprocessing"] == "20.9125"

    european = _case(
        worksheet, "eea_pa_manila_2026_08_08T03"
    )["candidate_expected"]
    assert european["category_code"] == "fair"
    assert european["dominant_pollutants"] == ["pm25", "pm10"]
    assert european["missing_pollutants"] == ["o3", "no2", "so2"]


def test_review_candidates_cover_every_registered_case_once_after_access_merge(
    candidate_worksheets,
):
    occurrences = Counter(
        case["case_id"]
        for worksheet in candidate_worksheets.values()
        for case in worksheet["cases"]
    )
    expected_case_count = 23 if "purpleair" in candidate_worksheets else 11
    assert len(occurrences) == expected_case_count
    if "purpleair" in candidate_worksheets:
        assert occurrences["unavailable_zero_row_sensors"] == 2
        assert all(
            count == 1
            for case_id, count in occurrences.items()
            if case_id != "unavailable_zero_row_sensors"
        )
    assert all(
        case["review"] == {
            "status": "candidate",
            "reviewer": None,
            "reviewed_at": None,
            "derivation_sha256": None,
            "comments": "",
            "approval_decision": "pending",
        }
        for worksheet in candidate_worksheets.values()
        for case in worksheet["cases"]
    )


def test_discrepancy_report_keeps_current_output_outside_candidate(
    source_fact_report, current_real_database, tmp_path
):
    source_path = tmp_path / "source-facts.json"
    source_path.write_text(json.dumps(source_fact_report, default=str), encoding="utf-8")
    worksheet = build_candidate_worksheet(
        source_fact_report,
        source_facts_file="source-facts.json",
        source_facts_sha256=sha256_file(source_path),
        dataset_name="openaq",
    )
    _, current, _ = current_real_database
    report = build_discrepancy_report(worksheet, current)
    ozone = next(
        case
        for case in report["cases"]
        if case["case_id"] == "openaq_ny_o3_window_2026_08_02T12"
    )
    assert ozone["current_summary"]["numeric_result"] == 34
    assert ozone["comparison_status"] == "match"
    carbon_monoxide = next(
        case
        for case in report["cases"]
        if case["case_id"] == "openaq_ny_co_window_2026_08_02T12"
    )
    assert carbon_monoxide["comparison_status"] == "match"
    assert carbon_monoxide["resolution_status"] == "implementation_corrected"
    assert carbon_monoxide["current_summary"]["availability"] == "available"
    assert carbon_monoxide["candidate_summary"]["availability"] == "available"
    for case_id in (
        "openaq_ny_no2_hour_2026_08_02T11",
        "openaq_ny_so2_window_2026_08_02T12",
    ):
        gas_case = next(case for case in report["cases"] if case["case_id"] == case_id)
        assert gas_case["comparison_status"] == "match"
        assert gas_case["resolution_status"] == "implementation_corrected"

    unsupported = next(
        case
        for case in report["cases"]
        if case["case_id"] == "openaq_rio_epa_mass_units_unavailable"
    )
    assert unsupported["comparison_status"] == "match_on_observed_fields"
    assert unsupported["resolution_status"] == "intentional_semantic_difference"
    assert all(
        result["exclusion_reason"] == "conversion_not_supported"
        for result in unsupported["current_summary"]["results"].values()
    )
    zero_rows = next(
        case
        for case in report["cases"]
        if case["case_id"] == "unavailable_zero_row_sensors"
    )
    assert zero_rows["comparison_status"] == "mismatch"
    assert zero_rows["resolution_status"] == "intentional_semantic_difference"
    assert zero_rows["current_summary"]["source_coverage_status"] == "zero_rows"
    assert zero_rows["current_summary"]["diagnostic_exclusion_reason"] == (
        "missing_measurements"
    )
    assert "current_summary" not in json.dumps(worksheet, default=str)


def test_review_package_groups_all_cases_and_keeps_review_pending(
    candidate_worksheets, current_real_database, tmp_path
):
    if "purpleair" not in candidate_worksheets:
        pytest.skip("restricted PurpleAir reference data is unavailable")
    _, current, _ = current_real_database
    current_path = tmp_path / "current-observations.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    worksheet_inputs = []
    discrepancy_inputs = []
    for dataset_name, worksheet in candidate_worksheets.items():
        worksheet_path = tmp_path / f"worksheet-{dataset_name}.json"
        worksheet_path.write_text(json.dumps(worksheet, default=str), encoding="utf-8")
        discrepancy = build_discrepancy_report(worksheet, current)
        discrepancy_path = tmp_path / f"discrepancy-{dataset_name}.json"
        discrepancy_path.write_text(json.dumps(discrepancy), encoding="utf-8")
        worksheet_inputs.append((worksheet_path, worksheet))
        discrepancy_inputs.append((discrepancy_path, discrepancy))
    package = build_review_package(
        worksheet_inputs,
        discrepancy_inputs,
        current_path,
        current,
    )
    cases = [case for group in package["groups"] for case in group["cases"]]
    assert package["registered_case_count"] == 23
    assert len(cases) == 23
    assert len({case["case_id"] for case in cases}) == 23
    assert package["safety"]["provider_calls"] == 0
    assert package["safety"]["credential_reads"] == 0
    assert package["safety"]["purpleair_points_consumed"] == 0
    assert package["safety"]["expected_results_promoted"] is False
    assert all(case["review"]["status"] == "candidate" for case in cases)
    assert all(case["review"]["approval_decision"] == "pending" for case in cases)
    assert all(
        "observation_status" not in part["current_compassaq_observation"]
        for case in cases
        for part in case["access_parts"]
    )
    markdown = review_package_markdown(package)
    assert "none are approved or promotable" in markdown
    assert "Current CompassAQ output was generated separately" in markdown


def test_current_output_report_uses_separate_alembic_sqlite_and_correct_represented_hour(
    current_real_database,
):
    database_path, report, restricted_root = current_real_database
    assert report["artifact_kind"] == "implementation_observations"
    assert report["oracle_status"] == "not_expected_results"
    assert report["database_creation"].startswith("alembic_autogenerated")
    assert report["provider_calls"] == 0
    assert report["credential_reads"] == 0
    assert report["purpleair_points_consumed"] == 0
    if restricted_root is not None:
        ordinary = report["service_observations"]["pa_ny_pm25_ordinary_boundary"]
        assert ordinary[0]["value"] == pytest.approx(3.5, abs=1e-12)
        assert ordinary[0]["sample_count"] == 30
        duplicate_hour = report["service_observations"][
            "pa_ny_pm_duplicate_positions"
        ]
        assert {
            result["parameter_code"]: result["calculation"]["valid_observation_count"]
            for result in duplicate_hour
        } == {"pm25": 27, "pm10": 27}
    restricted_count = 12_938 if restricted_root is not None else 0
    expected_versions = {"openaq-provider-flags-phase-2i.4a": 1_939}
    if restricted_root is not None:
        expected_versions["purpleair-provider-source-phase-2i.4c"] = 12_938
    assert report["database_retention"]["measurements"] == {
        "count": 1_939 + restricted_count,
        "valid_count": 1_939 + restricted_count,
        "qc_version_counts": expected_versions,
        "provider_capture_complete_count": 1_939 + restricted_count,
        "provider_period_count": 1_939,
        "provider_flag_info_count": 1_939,
        "provider_timestamp_count": restricted_count,
    }
    rio = report["service_observations"]["eea_rio_2026_08_02T11"][0]
    assert rio["observed_at"] == "2026-08-02T11:00:00Z"
    pollutant_results = rio["air_quality_index_result"]["pollutant_results"]
    concentrations = {
        result["parameter_code"]: result["normalized_concentration"]
        for result in pollutant_results
    }
    independently_extracted = {
        "pm25": 11.33,
        "pm10": 22.5,
        "o3": 28.16,
        "no2": 40.55,
        "so2": 11.99,
    }
    for parameter_code, expected_concentration in independently_extracted.items():
        assert concentrations[parameter_code] == pytest.approx(
            expected_concentration, abs=1e-12
        )
    unsupported_gases = report["service_observations"][
        "openaq_rio_epa_mass_units_unavailable"
    ]
    assert all(
        "conversion_not_supported" in results[0]["blocking_reasons"]
        for results in unsupported_gases.values()
    )
    gas_candidates = {
        "openaq_ny_co_window_2026_08_02T12": ("3952", 5, "partial", 6),
        "openaq_ny_no2_hour_2026_08_02T11": ("3951", 14, "complete", 1),
        "openaq_ny_so2_window_2026_08_02T12": ("3950", 3, "partial", 23),
    }
    for case_id, (sensor_id, expected_aqi, coverage_status, valid_hours) in (
        gas_candidates.items()
    ):
        gas_result = report["service_observations"][case_id][0]
        assert gas_result["selected_sensor"]["external_sensor_id"] == sensor_id
        if case_id == "openaq_ny_so2_window_2026_08_02T12":
            calculation = gas_result["calculation"]["selected_candidate"]
            assert gas_result["calculation"]["valid_hour_count"] == valid_hours
            assert gas_result["calculation"]["twenty_four_hour_candidate"][
                "normalized_concentration"
            ] == pytest.approx(12 / 23, abs=1e-12)
        else:
            calculation = gas_result["calculation"]["calculation"]
            assert gas_result["calculation"]["valid_hour_count"] == valid_hours
        assert calculation["numeric_value"] == expected_aqi
        assert calculation["coverage_status"] == coverage_status
        api_observation = report["api_model_observations"][case_id]
        assert api_observation["count"] == 1
        assert api_observation["results"][0]["numeric_value"] == expected_aqi
        assert api_observation["results"][0]["category_code"] == "good"
        assert api_observation["results"][0]["coverage"]["coverage_status"] == (
            coverage_status
        )
        assert any(
            reference["document_number"] == "EPA-403/B-26-003"
            and reference["publication_date"] == "2026-05"
            for reference in api_observation["methodology_references"]
        )
    zero_pm10 = report["service_observations"]["openaq_ny_pm10_zero_rows"][0]
    assert zero_pm10["calculation"]["calculation_status"] == "unavailable"
    assert zero_pm10["candidate_sensor_evaluations"][0]["exclusion_reason"] == (
        "missing_measurements"
    )
    outside_history = report["service_observations"][
        "openaq_outside_adequate_history"
    ][0]
    assert outside_history["calculation"]["calculation_status"] == "unavailable"
    assert outside_history["candidate_sensor_evaluations"][0]["exclusion_reason"] == (
        "missing_measurements"
    )
    manila = report["service_observations"][
        "eea_openaq_manila_2026_08_02T11"
    ][0]
    assert manila["air_quality_index_result"]["coverage"] == {
        "coverage_status": "partial",
        "available_pollutants": ["pm25"],
        "missing_pollutants": ["pm10", "o3", "no2", "so2"],
        "ineligible_pollutants": [],
        "missing_or_ineligible_pollutants": ["pm10", "o3", "no2", "so2"],
        "display_qualification": "not_evaluated",
    }
    if restricted_root is not None:
        zero_purpleair = report["service_observations"][
            "purpleair_zero_row_sensor_198733"
        ][0]
        assert zero_purpleair["calculation"]["calculation_status"] == "unavailable"
        assert zero_purpleair["candidate_sensor_evaluations"][0][
            "exclusion_reason"
        ] == "missing_measurements"

    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}", poolclass=NullPool
    )
    with Session(engine) as session:
        openaq_sensor = session.scalar(
            select(models.Sensor).where(models.Sensor.external_sensor_id == "6819305")
        )
        openaq_measurement = session.scalar(
            select(models.Measurement).where(
                models.Measurement.sensor_id == openaq_sensor.sensor_id,
                models.Measurement.observed_at
                == datetime.fromisoformat("2026-08-02T12:00:00+00:00"),
            )
        )
        openaq_capture = openaq_measurement.qc_flags[
            "reference_fixture_provider_capture"
        ]
        assert openaq_measurement.value == pytest.approx(11.33, abs=1e-12)
        assert openaq_measurement.is_valid is True
        assert openaq_measurement.qc_version == "openaq-provider-flags-phase-2i.4a"
        assert openaq_capture["provider_observation_ref"] == (
            "openaq:6819305:page-1:result-35"
        )
        assert openaq_capture["source_page"] == 1
        assert openaq_capture["source_result_index"] == 35
        assert openaq_capture["provider_period"]["interval"] == "01:00:00"
        assert openaq_capture["provider_flag_info"]["hasFlags"] is False
        assert session.get(models.Unit, openaq_sensor.unit_id).code == "ug_m3"
        assert session.get(
            models.AggregationPeriod, openaq_sensor.aggregation_period_id
        ).code == "1h"

        if restricted_root is not None:
            purpleair_sensor = session.scalar(
                select(models.Sensor).where(
                    models.Sensor.external_sensor_id == "159361:pm2.5_atm"
                )
            )
            purpleair_measurement = session.scalar(
                select(models.Measurement).where(
                    models.Measurement.sensor_id == purpleair_sensor.sensor_id
                ).order_by(models.Measurement.observed_at)
            )
            purpleair_capture = purpleair_measurement.qc_flags[
                "reference_fixture_provider_capture"
            ]
            assert purpleair_measurement.value == pytest.approx(1.2, abs=1e-12)
            assert purpleair_measurement.is_valid is True
            assert purpleair_measurement.qc_version == (
                "purpleair-provider-source-phase-2i.4c"
            )
            assert purpleair_capture["provider_observation_ref"].startswith(
                "purpleair:159361:"
            )
            assert purpleair_capture["source_page"] == 1
            assert purpleair_capture["source_result_index"] is not None
            assert purpleair_capture["provider_timestamp"] is not None
            assert purpleair_measurement.qc_flags["provider_validity_status"] == (
                "not_supplied"
            )
            assert session.get(models.Unit, purpleair_sensor.unit_id).code == "ug_m3"
            assert session.get(
                models.AggregationPeriod, purpleair_sensor.aggregation_period_id
            ).code == "2m"
    engine.dispose()


def test_real_reference_api_and_analytics_paths_expose_source_facts(
    current_real_database, source_fact_report
):
    database_path, report, restricted_root = current_real_database
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}", poolclass=NullPool
    )
    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            rio_device_id = report["loaded_fixtures"]["openaq"]["device_ids"][
                "openaq-location-820326"
            ]
            eea_response = client.get(
                "/air-quality-index/eea_european/history",
                params={
                    "start": "2026-08-02T11:00:00Z",
                    "end": "2026-08-02T12:00:00Z",
                    "device_id": rio_device_id,
                },
            )
            analytics_response = client.post(
                "/air-quality-index/analytics-history",
                json={
                    "range_started_at": "2026-08-02T11:00:00Z",
                    "range_ended_at": "2026-08-02T13:00:00Z",
                    "series": [
                        {
                            "standard_code": "eea_european",
                            "product_code": "eea_european.overall.hourly",
                            "device_id": rio_device_id,
                        }
                    ],
                },
            )
            assert eea_response.status_code == 200, eea_response.text
            assert analytics_response.status_code == 200, analytics_response.text

            eea_result = eea_response.json()["results"][0]
            assert eea_result["observed_at"] == "2026-08-02T11:00:00Z"
            assert eea_result["source_name"] == "OpenAQ"
            independent_rio = _case(source_fact_report, "eea_rio_2026_08_02T11")
            expected_concentrations = {
                sensor["sensor_ref"]: float(sensor["observations"][0]["decimal_value"])
                for sensor in independent_rio["facts"]["sensor_results"]
            }
            observed_by_parameter = {
                pollutant["parameter_code"]: pollutant["normalized_concentration"]
                for pollutant in eea_result["pollutant_results"]
            }
            sensor_to_parameter = {
                "openaq-sensor-6819305": "pm25",
                "openaq-sensor-4475454": "pm10",
                "openaq-sensor-6459542": "o3",
                "openaq-sensor-4475455": "no2",
                "openaq-sensor-11268993": "so2",
            }
            for sensor_ref, concentration in expected_concentrations.items():
                assert observed_by_parameter[sensor_to_parameter[sensor_ref]] == pytest.approx(
                    concentration, abs=1e-12
                )
            analytics_series = analytics_response.json()["series"][0]
            assert len(analytics_series["points"]) == 1
            assert analytics_series["points"][0]["observed_at"] == "2026-08-02T12:00:00Z"
            assert analytics_series["points"][0]["coverage_status"] == "complete"

            if restricted_root is None:
                return
            ny_device_id = report["loaded_fixtures"]["purpleair"]["device_ids"][
                "purpleair-device-159361"
            ]
            aggregate_response = client.get(
                "/measurements/pm25/aggregate",
                params={
                    "from": "2m",
                    "to": "1h",
                    "since": "2026-08-08T01:00:00Z",
                    "until": "2026-08-08T02:00:00Z",
                    "external_api_name": "PurpleAir",
                },
            )
            nowcast_response = client.get(
                "/air-quality-index/us_epa/current-history",
                params={
                    "product_code": "us_epa.pm25.nowcast",
                    "start": "2026-08-10T12:00:00Z",
                    "end": "2026-08-10T13:00:00Z",
                    "device_id": ny_device_id,
                },
            )
            completed_response = client.get(
                "/air-quality-index/us_epa/history",
                params={
                    "product_code": "us_epa.pm25.completed_day",
                    "start_local_date": "2026-08-09",
                    "end_local_date": "2026-08-09",
                    "device_id": ny_device_id,
                    "detail": "full",
                },
            )
            assert aggregate_response.status_code == 200, aggregate_response.text
            assert nowcast_response.status_code == 200, nowcast_response.text
            assert completed_response.status_code == 200, completed_response.text

            ordinary_fact = _case(
                source_fact_report, "pa_ny_pm25_ordinary_boundary"
            )["facts"]["sensor_results"][0]
            aggregate_row = next(
                row
                for row in aggregate_response.json()
                if row["external_sensor_id"] == "159361:pm2.5_atm"
            )
            assert aggregate_row["sample_count"] == ordinary_fact["included_count"] == 30
            assert aggregate_row["device"]["network"] == "PurpleAir"
            assert aggregate_row["value"] == pytest.approx(
                float(ordinary_fact["arithmetic"]["unformatted_mean"]), abs=1e-12
            )
            nowcast_result = nowcast_response.json()["results"][0]
            assert nowcast_result["source_name"] == "PurpleAir"
            expected_latest_count = _case(
                source_fact_report, "pa_ny_pm_nowcast_inputs"
            )["facts"]["hours_most_recent_first"][0]["sensor_results"][0][
                "completeness"
            ]["numerator"]
            assert nowcast_result["latest_completed_hour_valid_observation_count"] == expected_latest_count
            completed_result = completed_response.json()["device_series"][0]["results"][0]
            assert completed_result["valid_hour_count"] == 24
            assert completed_result["coverage_status"] == "complete"
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()
