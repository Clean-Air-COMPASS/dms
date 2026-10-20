from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest

from reference_data.restricted import resolve_restricted_data_root
from services.air_quality_index.hourly_pm_completeness import (
    RawHourlyObservation,
    construct_subhourly_pm_hour,
)


TOOLS_ROOT = Path(__file__).resolve().parent / "reference_data_tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from source_facts import DEFAULT_REFERENCE_ROOT, extract_source_facts, read_frozen_dataset  # noqa: E402


CHECKED_IN_RESTRICTED_ROOT = DEFAULT_REFERENCE_ROOT / "restricted" / "purpleair"


@pytest.fixture(scope="module")
def restricted_fixture_and_facts():
    restricted_root = resolve_restricted_data_root(
        checked_in_fallback=CHECKED_IN_RESTRICTED_ROOT
    )
    if restricted_root is None:
        pytest.skip("restricted PurpleAir reference data is unavailable")
    dataset = read_frozen_dataset("purpleair", restricted_root)
    report = extract_source_facts(
        DEFAULT_REFERENCE_ROOT, dataset_roots={"purpleair": restricted_root}
    )
    return dataset, {case["case_id"]: case for case in report["cases"]}


@pytest.mark.parametrize(
    "case_id",
    (
        "pa_ny_pm_boundary_assignment",
        "pa_ny_pm_full",
        "pa_ny_pm_duplicate_positions",
        "pa_rio_pm_minor_gaps",
        "pa_manila_pm_irregular",
    ),
)
def test_production_pm_completeness_matches_independent_real_position_assignment(
    restricted_fixture_and_facts, case_id
):
    dataset, cases = restricted_fixture_and_facts
    case = cases[case_id]
    assert case["extraction_status"] == "extracted"
    for expected_sensor in case["facts"]["sensor_results"]:
        sensor_ref = expected_sensor["sensor_ref"]
        interval_started_at = datetime.fromisoformat(
            expected_sensor["utc_window"]["started_at"].replace("Z", "+00:00")
        )
        interval_ended_at = datetime.fromisoformat(
            expected_sensor["utc_window"]["ended_at"].replace("Z", "+00:00")
        )
        rows = [
            row
            for row in dataset.measurements_by_sensor[sensor_ref]
            if interval_started_at
            <= datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
            <= interval_ended_at
        ]
        timestamp_by_measurement_id = {}
        observations = []
        for measurement_id, row in enumerate(rows, start=1):
            observed_at = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
            timestamp_by_measurement_id[measurement_id] = row["observed_at"]
            observations.append(
                RawHourlyObservation(
                    measurement_id=measurement_id,
                    observed_at=observed_at,
                    concentration=row["value"],
                    is_valid=row["is_valid"],
                )
            )
        parameter_code = "pm25" if sensor_ref.endswith("pm25") else "pm10"
        actual = construct_subhourly_pm_hour(
            observations,
            interval_started_at=interval_started_at,
            parameter_code=parameter_code,
            input_unit="ug_m3",
            expected_frequency_seconds=120,
            measurement_duration_seconds=120,
            source_aggregation_duration_seconds=120,
            timestamp_semantics="provider_received_at",
        )

        expected_completeness = expected_sensor["completeness"]
        assert actual.expected_observation_count == expected_completeness["denominator"]
        assert actual.required_valid_observation_count == expected_completeness["required_count"]
        assert actual.valid_observation_count == expected_completeness["numerator"]
        assert actual.missing_position_count == len(expected_completeness["missing_positions"])
        assert len(actual.duplicate_measurement_ids) == len(
            expected_completeness["duplicate_positions"]
        )
        assert len(actual.off_frequency_measurement_ids) == len(
            expected_completeness["off_frequency_positions"]
        )
        assert actual.eligibility_status == expected_completeness["coverage_status"]
        assert {
            timestamp_by_measurement_id[measurement_id]
            for measurement_id in actual.measurement_ids
        } == {
            observation["observed_at"]
            for observation in expected_sensor["accepted_observations"]
        }


def test_real_fixture_has_no_naturally_ineligible_purpleair_hour(
    restricted_fixture_and_facts,
):
    _, cases = restricted_fixture_and_facts
    real_hour_cases = (
        "pa_ny_pm_boundary_assignment",
        "pa_ny_pm_full",
        "pa_ny_pm_duplicate_positions",
        "pa_rio_pm_minor_gaps",
        "pa_manila_pm_irregular",
    )
    assert all(
        sensor["completeness"]["numerator"] >= 23
        for case_id in real_hour_cases
        for sensor in cases[case_id]["facts"]["sensor_results"]
    )
