"""Compare review candidates with separately recorded CompassAQ observations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any


ABSOLUTE_TOLERANCE = Decimal("0.000000000001")


def _availability(calculation_status: str | None) -> str:
    return "available" if calculation_status == "calculated" else "unavailable"


def _candidate_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    concentration_keys = (
        "weighted_concentration",
        "daily_mean_before_final_preprocessing",
        "daily_mean_before_preprocessing",
        "eight_hour_mean_before_final_preprocessing",
        "mean_before_preprocessing",
        "maximum_hour_ppb",
        "normalized_concentration",
        "hourly_concentration",
        "converted_ppb",
        "input_concentration",
    )
    concentration = next(
        (result[key] for key in concentration_keys if result.get(key) is not None), None
    )
    return {
        "availability": result.get("availability", "available"),
        "numeric_result": result.get("numeric_result"),
        "category_code": result.get("category_code"),
        "coverage_status": result.get("coverage_status"),
        "aggregation_period": {
            "eight_hour": "8h",
            "one_hour": "1h",
        }.get(result.get("selected_candidate")),
        "exclusion_reason": result.get("exclusion_reason"),
        "concentration": concentration,
        "nowcast_weight": result.get("nowcast_weight"),
    }


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "availability": candidate.get("availability"),
        "numeric_result": candidate.get("numeric_result"),
        "category_code": candidate.get("category_code"),
        "coverage_status": candidate.get("coverage_status"),
        "aggregation_period": candidate.get("aggregation_period"),
        "exclusion_reason": candidate.get("exclusion_reason"),
    }
    if "dominant_pollutants" in candidate:
        summary["dominant_pollutants"] = candidate["dominant_pollutants"]
    if "missing_pollutants" in candidate:
        summary["missing_pollutants"] = candidate["missing_pollutants"]
    results = candidate.get("results", [])
    if results:
        summary["results"] = {
            result["parameter_code"]: _candidate_result_summary(result)
            for result in results
        }
    if candidate.get("expected_fields") is not None:
        summary["expected_fields"] = candidate["expected_fields"]
    return summary


def _calculation_summary(calculation: dict[str, Any]) -> dict[str, Any]:
    calculation_status = calculation.get("calculation_status") or calculation.get(
        "candidate_status"
    )
    return {
        "availability": _availability(calculation_status),
        "numeric_result": calculation.get("numeric_value"),
        "category_code": calculation.get("category_code"),
        "coverage_status": calculation.get("coverage_status"),
        "aggregation_period": calculation.get("aggregation_period"),
        "exclusion_reason": calculation.get("exclusion_reason"),
        "concentration": calculation.get("normalized_concentration"),
        "nowcast_weight": calculation.get("nowcast_weight_factor"),
    }


def _selected_ozone_summary(observation: dict[str, Any]) -> dict[str, Any]:
    calculation = observation["calculation"]
    selected = calculation.get("selected_candidate")
    if selected is None:
        return {
            "availability": "unavailable",
            "numeric_result": None,
            "category_code": None,
            "coverage_status": calculation.get("coverage_status"),
            "aggregation_period": calculation.get("selected_aggregation_period"),
            "exclusion_reason": calculation.get("exclusion_reason"),
            "concentration": None,
            "nowcast_weight": None,
        }
    return {
        "availability": _availability(calculation.get("calculation_status")),
        "numeric_result": selected.get("numeric_value"),
        "category_code": selected.get("category_code"),
        "coverage_status": selected.get("coverage_status"),
        "aggregation_period": selected.get("aggregation_period"),
        "exclusion_reason": selected.get("exclusion_reason"),
        "concentration": selected.get("normalized_concentration"),
        "nowcast_weight": None,
    }


def _eea_summary(observation: dict[str, Any]) -> dict[str, Any]:
    result = observation["air_quality_index_result"]
    return {
        "availability": "available" if result.get("eligibility_status") == "eligible" else "unavailable",
        "numeric_result": result.get("numeric_value"),
        "category_code": result.get("category_code"),
        "coverage_status": result.get("coverage", {}).get("coverage_status"),
        "aggregation_period": "1h",
        "exclusion_reason": (result.get("exclusion_reasons") or [None])[0],
        "dominant_pollutants": result.get("dominant_pollutants"),
        "missing_pollutants": result.get("coverage", {}).get("missing_pollutants"),
        "results": {
            pollutant["parameter_code"]: {
                "availability": "available" if pollutant.get("eligibility_status") == "eligible" else "unavailable",
                "numeric_result": pollutant.get("numeric_value"),
                "category_code": pollutant.get("category_code"),
                "exclusion_reason": pollutant.get("exclusion_reason"),
                "concentration": pollutant.get("normalized_concentration"),
                "nowcast_weight": None,
            }
            for pollutant in result.get("pollutant_results", [])
        },
    }


def _fixture_summary(dataset_name: str, current: dict[str, Any]) -> dict[str, Any]:
    streams = current["database_retention"]["sensor_streams"]
    if dataset_name == "openaq":
        selected = [stream for stream in streams if stream["sensor_id"] <= 13]
        provider = "OpenAQ"
        validity_key = "openaq-provider-flags-phase-2i.4a"
    else:
        selected = [stream for stream in streams if stream["sensor_id"] >= 14]
        provider = "PurpleAir"
        validity_key = "purpleair-provider-source-phase-2i.4c"
    measurements = current["database_retention"]["measurements"]
    return {
        "availability": "not_applicable",
        "expected_fields": {
            "provider": provider,
            "measurement_count": measurements["qc_version_counts"][validity_key],
            "device_count": len(current["loaded_fixtures"][dataset_name]["device_ids"]),
            "sensor_count": len(selected),
            "active_sensor_count": sum(stream["measurement_count"] > 0 for stream in selected),
        },
    }


def _empty_runtime_summary() -> dict[str, Any]:
    return {
        "availability": "unavailable",
        "numeric_result": None,
        "category_code": None,
        "coverage_status": None,
        "aggregation_period": None,
        "exclusion_reason": "no_runtime_result_returned",
    }


def _current_summary(case_id: str, current: dict[str, Any], dataset_name: str) -> dict[str, Any]:
    service = current.get("service_observations", {})
    if case_id.startswith("fixture_"):
        return _fixture_summary(dataset_name, current)
    if case_id == "provenance_manila_airgradient_via_openaq":
        observations = service.get("eea_openaq_manila_2026_08_02T11", [])
        if not observations:
            return {"observation_status": "not_recorded"}
        return {
            "availability": "not_applicable",
            "expected_fields": {
                "owner_name": observations[0]["device_name"],
                "transport_provider": observations[0]["source_name"],
            },
        }
    if case_id in {
        "pa_ny_pm25_ordinary_boundary",
    }:
        observations = service.get(case_id, [])
        if not observations:
            return {"observation_status": "not_recorded_by_current_observations_tool"}
        observation = observations[0]
        result = {
            "availability": "available",
            "numeric_result": None,
            "category_code": None,
            "coverage_status": None,
            "aggregation_period": None,
            "exclusion_reason": None,
            "concentration": observation["value"],
            "nowcast_weight": None,
        }
        return {
            "availability": "available",
            "numeric_result": observation["value"],
            "category_code": None,
            "coverage_status": "complete",
            "aggregation_period": "1h",
            "exclusion_reason": None,
            "results": {"pm25": result},
        }
    if case_id in {
        "pa_ny_pm_boundary_assignment",
        "pa_ny_pm_full",
        "pa_ny_pm_duplicate_positions",
        "pa_rio_pm_minor_gaps",
        "pa_manila_pm_irregular",
    }:
        observations = service.get(case_id, [])
        if not observations:
            return {"observation_status": "not_recorded_by_current_observations_tool"}
        results = {}
        for observation in observations:
            calculation = observation["calculation"]
            results[observation["parameter_code"]] = {
                "availability": (
                    "available"
                    if calculation["eligibility_status"] == "eligible"
                    else "unavailable"
                ),
                "numeric_result": None,
                "category_code": None,
                "coverage_status": None,
                "aggregation_period": None,
                "exclusion_reason": calculation["exclusion_reason"],
                "concentration": calculation["hourly_concentration"],
                "nowcast_weight": None,
            }
        coverage_status = (
            "complete"
            if all(
                observation["calculation"]["valid_observation_count"]
                == observation["calculation"]["expected_observation_count"]
                for observation in observations
            )
            else "partial"
        )
        return {
            "availability": (
                "available"
                if all(result["availability"] == "available" for result in results.values())
                else "unavailable"
            ),
            "numeric_result": None,
            "category_code": None,
            "coverage_status": coverage_status,
            "aggregation_period": "1h",
            "exclusion_reason": None,
            "results": results,
        }
    if case_id.startswith("eea_"):
        observations = service.get(case_id, [])
        return _eea_summary(observations[0]) if observations else _empty_runtime_summary()
    if case_id.endswith("nowcast_inputs"):
        by_parameter = service.get(case_id, {})
        results = {}
        for parameter_code in ("pm25", "pm10"):
            observations = by_parameter.get(parameter_code, [])
            results[parameter_code] = (
                _calculation_summary(observations[0]["calculation"])
                if observations
                else _empty_runtime_summary()
            )
        return {
            "availability": "available" if all(item["availability"] == "available" for item in results.values()) else "unavailable",
            "numeric_result": None,
            "category_code": None,
            "coverage_status": "complete" if all(item["coverage_status"] == "complete" for item in results.values()) else "partial",
            "aggregation_period": "nowcast",
            "exclusion_reason": None,
            "results": results,
        }
    if case_id in {
        "pa_ny_pm25_completed_2026_08_09",
        "openaq_rio_pm10_completed_2026_08_02",
    }:
        observations = service.get(case_id, [])
        if not observations:
            return _empty_runtime_summary()
        summary = _calculation_summary(observations[0]["calculation"])
        summary["aggregation_period"] = "local_day"
        parameter_code = observations[0]["calculation"]["parameter_code"]
        result_summary = summary.copy()
        result_summary["aggregation_period"] = None
        return {**summary, "results": {parameter_code: result_summary}}
    if case_id == "openaq_ny_o3_window_2026_08_02T12":
        observations = service.get(case_id, [])
        if not observations:
            return _empty_runtime_summary()
        summary = _selected_ozone_summary(observations[0])
        return {**summary, "results": {"o3": summary.copy()}}
    gas_parameter = {
        "openaq_ny_co_window_2026_08_02T12": "co",
        "openaq_ny_no2_hour_2026_08_02T11": "no2",
        "openaq_ny_so2_window_2026_08_02T12": "so2",
    }.get(case_id)
    if gas_parameter:
        observations = service.get(case_id, [])
        if not observations:
            summary = _empty_runtime_summary()
        elif gas_parameter == "so2":
            calculation = observations[0]["calculation"]
            selected = calculation.get("selected_candidate")
            summary = (
                _calculation_summary(selected)
                if selected
                else {
                    **_empty_runtime_summary(),
                    "coverage_status": calculation.get("coverage_status"),
                    "exclusion_reason": calculation.get("exclusion_reason"),
                }
            )
        else:
            calculation = observations[0]["calculation"]
            summary = _calculation_summary(calculation["calculation"])
            summary["aggregation_period"] = "8h" if gas_parameter == "co" else "1h"
        result_summary = summary.copy()
        if gas_parameter != "so2":
            result_summary["aggregation_period"] = None
        return {**summary, "results": {gas_parameter: result_summary}}
    if case_id == "openaq_rio_epa_mass_units_unavailable":
        results = {}
        for parameter_code, observations in service.get(case_id, {}).items():
            observation = observations[0]
            blocking_reasons = observation.get("blocking_reasons", [])
            diagnostic_reason = (
                "conversion_not_supported"
                if "conversion_not_supported" in blocking_reasons
                else None
            )
            if parameter_code == "o3":
                higher_level_reason = observation["calculation"].get(
                    "exclusion_reason"
                )
            else:
                higher_level_reason = observation["calculation"].get(
                    "exclusion_reason"
                )
            results[parameter_code] = {
                **_empty_runtime_summary(),
                "exclusion_reason": diagnostic_reason or higher_level_reason,
                "higher_level_exclusion_reason": higher_level_reason,
                "blocking_reasons": blocking_reasons,
            }
        return {
            "availability": "unavailable",
            "numeric_result": None,
            "category_code": None,
            "coverage_status": "unavailable",
            "aggregation_period": None,
            "exclusion_reason": "conversion_not_supported",
            "results": results,
        }
    if case_id == "unavailable_zero_row_sensors":
        key = "openaq_ny_pm10_zero_rows" if dataset_name == "openaq" else "purpleair_zero_row_sensor_198733"
        observations = service.get(key, [])
        if not observations:
            return _empty_runtime_summary()
        observation = observations[0]
        summary = _calculation_summary(observation["calculation"])
        sensor_evaluation = observation["candidate_sensor_evaluations"][0]
        source_exclusion_reason = sensor_evaluation.get("exclusion_reason")
        final_exclusion_reason = summary["exclusion_reason"]
        summary["exclusion_reason"] = source_exclusion_reason
        candidate_parameters = ["pm10"] if dataset_name == "openaq" else ["pm25", "pm10"]
        result_summary = summary.copy()
        result_summary["coverage_status"] = None
        return {
            **summary,
            "coverage_status": "unavailable",
            "source_coverage_status": "zero_rows",
            "diagnostic_exclusion_reason": source_exclusion_reason,
            "final_exclusion_reason": final_exclusion_reason,
            "results": {parameter: result_summary for parameter in candidate_parameters},
        }
    return {"observation_status": "not_recorded"}


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        flattened = {}
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            flattened.update(_flatten(child, child_prefix))
        return flattened
    return {prefix: value}


def _values_match(candidate: Any, current: Any) -> bool:
    if candidate == current:
        return True
    if candidate is None or current is None or isinstance(candidate, bool) or isinstance(current, bool):
        return False
    try:
        return abs(Decimal(str(candidate)) - Decimal(str(current))) <= ABSOLUTE_TOLERANCE
    except (InvalidOperation, ValueError):
        return False


def _compare(candidate: dict[str, Any], current: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[str]]:
    if current.get("observation_status"):
        return "current_observation_not_recorded", [], sorted(_flatten(candidate))
    candidate_fields = _flatten(candidate)
    current_fields = _flatten(current)
    differences = []
    unobserved = []
    for field, candidate_value in candidate_fields.items():
        if field not in current_fields:
            unobserved.append(field)
            continue
        current_value = current_fields[field]
        if not _values_match(candidate_value, current_value):
            differences.append(
                {
                    "field": field,
                    "candidate": candidate_value,
                    "current": current_value,
                }
            )
    status = "match" if not differences else "mismatch"
    if unobserved and not differences:
        status = "match_on_observed_fields"
    return status, differences, unobserved


def build_discrepancy_report(
    worksheet: dict[str, Any], current_observations: dict[str, Any]
) -> dict[str, Any]:
    if worksheet.get("artifact_kind") != "analyst_derivation_worksheet":
        raise ValueError("Worksheet input has the wrong artifact_kind")
    if current_observations.get("artifact_kind") != "implementation_observations":
        raise ValueError("Current-output input has the wrong artifact_kind")
    cases = []
    for case in worksheet["cases"]:
        candidate = _candidate_summary(case["candidate_expected"])
        current = _current_summary(
            case["case_id"], current_observations, worksheet["dataset_name"]
        )
        comparison_status, differences, unobserved = _compare(candidate, current)
        resolution = _resolution_for_case(case["case_id"])
        cases.append(
            {
                "case_id": case["case_id"],
                "source_fact_hash": case["source_fact_hash"],
                "candidate_derivation_sha256": case["candidate_derivation_sha256"],
                "candidate_review_status": case["review"]["status"],
                "candidate_summary": candidate,
                "current_summary": current,
                "comparison_status": comparison_status,
                "differing_fields": differences,
                "candidate_fields_not_observed_by_current_reporter": unobserved,
                **resolution,
                "notes": (
                    "No discrepancy is auto-resolved; analyst review remains pending."
                    if comparison_status != "current_observation_not_recorded"
                    else "The current-output tool does not record this lower-level seam separately."
                ),
            }
        )
    return {
        "schema_version": "2i.5-discrepancy-report-3",
        "artifact_kind": "review_only_discrepancy_report",
        "oracle_status": "not_expected_results",
        "dataset_name": worksheet["dataset_name"],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "absolute_tolerance": str(ABSOLUTE_TOLERANCE),
        "cases": cases,
    }


def build_approved_conformance_report(
    approved_bundle: dict[str, Any], current_observations: dict[str, Any]
) -> dict[str, Any]:
    """Compare promoted expectations with current output without deriving values."""
    if approved_bundle.get("artifact_kind") != "analyst_approved_expectations":
        raise ValueError("Conformance input is not an approved expectation bundle")
    if current_observations.get("artifact_kind") != "implementation_observations":
        raise ValueError("Current-output input has the wrong artifact_kind")
    dataset_name = str(approved_bundle["dataset_name"])
    cases = []
    for case in approved_bundle["cases"]:
        candidate = _candidate_summary(case["expected"])
        current = _current_summary(case["case_id"], current_observations, dataset_name)
        comparison_status, differences, unobserved = _compare(candidate, current)
        cases.append(
            {
                "case_id": case["case_id"],
                "comparison_status": comparison_status,
                "differing_fields": differences,
                "approved_fields_not_observed_by_current_reporter": unobserved,
                **_resolution_for_case(case["case_id"]),
            }
        )
    return {
        "artifact_kind": "approved_expectation_conformance_report",
        "dataset_name": dataset_name,
        "case_count": len(cases),
        "cases": cases,
    }


def _resolution_for_case(case_id: str) -> dict[str, str]:
    resolutions = {
        "openaq_ny_co_window_2026_08_02T12": {
            "resolution_status": "implementation_corrected",
            "root_cause": "The diagnostic reporter selected the Bronx device while sensor 3952 belongs to the Elizabeth device; the provider-neutral production calculation was already correct.",
        },
        "openaq_ny_no2_hour_2026_08_02T11": {
            "resolution_status": "implementation_corrected",
            "root_cause": "The diagnostic reporter selected the Bronx device while sensor 3951 belongs to the Elizabeth device; the provider-neutral production calculation was already correct.",
        },
        "openaq_ny_so2_window_2026_08_02T12": {
            "resolution_status": "implementation_corrected",
            "root_cause": "The diagnostic reporter selected the Bronx device while sensor 3950 belongs to the Elizabeth device; the provider-neutral production calculation and 23-value divisor were already correct.",
        },
        "openaq_rio_epa_mass_units_unavailable": {
            "resolution_status": "intentional_semantic_difference",
            "root_cause": "Production retains generic final applicability status while its machine-readable blocking reasons preserve conversion_not_supported as the authoritative diagnostic.",
        },
        "unavailable_zero_row_sensors": {
            "resolution_status": "intentional_semantic_difference",
            "root_cause": "Production now records missing_measurements at the source-stream diagnostic level and keeps no_eligible_sensor_stream as the distinct final availability reason; the candidate uses the broader term insufficient_data.",
        },
    }
    return resolutions.get(case_id, {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worksheet", type=Path)
    parser.add_argument("current_observations", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    worksheet = json.loads(args.worksheet.read_text(encoding="utf-8"))
    current = json.loads(args.current_observations.read_text(encoding="utf-8"))
    report = build_discrepancy_report(worksheet, current)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
