from __future__ import annotations

"""Independent synthetic DENR-EMB review candidates.

This module deliberately uses only the Python standard library. Its constants
are copied from the cited DENR-EMB tables so production code cannot become the
review oracle.
"""

import argparse
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
import json
from pathlib import Path
from typing import Any


CATEGORIES = {
    "good": ("Good", "#00E400"),
    "fair": ("Fair", "#FFFF00"),
    "unhealthy_for_sensitive_groups": (
        "Unhealthy for Sensitive Groups",
        "#FF7E00",
    ),
    "very_unhealthy": ("Very Unhealthy", "#FF0000"),
    "acutely_unhealthy": ("Acutely Unhealthy", "#8F3F97"),
    "emergency": ("Emergency", "#7E0023"),
}


def _band(
    low: str,
    high: str | None,
    index_low: int,
    index_high: int,
    category_code: str,
) -> tuple[Decimal, Decimal | None, int, int, str]:
    return (
        Decimal(low),
        Decimal(high) if high is not None else None,
        index_low,
        index_high,
        category_code,
    )


COMPONENTS = {
    "pm25_24_hour": {
        "parameter_code": "pm25",
        "normalized_unit": "µg/m³",
        "truncate_places": 1,
        "bands": (
            _band("0", "25", 0, 50, "good"),
            _band("25.1", "35.0", 51, 100, "fair"),
            _band("35.1", "45.0", 101, 150, "unhealthy_for_sensitive_groups"),
            _band("45.1", "55", 151, 200, "very_unhealthy"),
            _band("55.1", "90", 201, 300, "acutely_unhealthy"),
            _band("91", None, 301, 500, "emergency"),
        ),
        "below_first_reason": "published_breakpoint_gap",
    },
    "pm10_24_hour": {
        "parameter_code": "pm10",
        "normalized_unit": "µg/m³",
        "truncate_places": 0,
        "bands": (
            _band("0", "54", 0, 50, "good"),
            _band("55", "154", 51, 100, "fair"),
            _band("155", "254", 101, 150, "unhealthy_for_sensitive_groups"),
            _band("255", "354", 151, 200, "very_unhealthy"),
            _band("355", "424", 201, 300, "acutely_unhealthy"),
            _band("425", "504", 301, 500, "emergency"),
        ),
        "below_first_reason": "published_breakpoint_gap",
    },
    "so2_24_hour": {
        "parameter_code": "so2",
        "normalized_unit": "ppm",
        "truncate_places": None,
        "bands": (
            _band("0.000", "0.034", 0, 50, "good"),
            _band("0.035", "0.144", 51, 100, "fair"),
            _band("0.145", "0.224", 101, 150, "unhealthy_for_sensitive_groups"),
            _band("0.225", "0.304", 151, 200, "very_unhealthy"),
            _band("0.305", "0.604", 201, 300, "acutely_unhealthy"),
            _band("0.605", "0.804", 301, 500, "emergency"),
        ),
        "below_first_reason": "published_breakpoint_gap",
    },
    "o3_8_hour": {
        "parameter_code": "o3",
        "normalized_unit": "ppm",
        "truncate_places": None,
        "bands": (
            _band("0.000", "0.064", 0, 50, "good"),
            _band("0.065", "0.084", 51, 100, "fair"),
            _band("0.085", "0.104", 101, 150, "unhealthy_for_sensitive_groups"),
            _band("0.105", "0.124", 151, 200, "very_unhealthy"),
            _band("0.125", "0.374", 201, 300, "acutely_unhealthy"),
        ),
        "below_first_reason": "published_breakpoint_gap",
    },
    "o3_1_hour": {
        "parameter_code": "o3",
        "normalized_unit": "ppm",
        "truncate_places": None,
        "bands": (
            _band("0.125", "0.164", 101, 150, "unhealthy_for_sensitive_groups"),
            _band("0.165", "0.204", 151, 200, "very_unhealthy"),
            _band("0.205", "0.404", 201, 300, "acutely_unhealthy"),
            _band("0.405", "0.504", 301, 500, "emergency"),
        ),
        "below_first_reason": "published_breakpoint_gap",
    },
    "co_8_hour": {
        "parameter_code": "co",
        "normalized_unit": "ppm",
        "truncate_places": None,
        "bands": (
            _band("0.0", "4.4", 0, 50, "good"),
            _band("4.5", "9.4", 51, 100, "fair"),
            _band("9.5", "12.4", 101, 150, "unhealthy_for_sensitive_groups"),
            _band("12.5", "15.4", 151, 200, "very_unhealthy"),
            _band("15.5", "30.4", 201, 300, "acutely_unhealthy"),
            _band("30.5", "40.4", 301, 500, "emergency"),
        ),
        "below_first_reason": "published_breakpoint_gap",
    },
    "no2_1_hour": {
        "parameter_code": "no2",
        "normalized_unit": "ppm",
        "truncate_places": None,
        "bands": (
            _band("0.65", "1.24", 201, 300, "acutely_unhealthy"),
            _band("1.25", "1.64", 301, 500, "emergency"),
        ),
        "below_first_reason": "subindex_not_defined_for_concentration",
    },
}


METHODOLOGY_NOTES = {
    "pm25": "DAO 2020-14 PM2.5 table; EMB MC 2021-07 preprocessing and interpolation.",
    "pm10": "DAO 2000-81 Annex A PM10 table; EMB MC 2021-07 integer truncation.",
    "so2": "DAO 2000-81 Annex A 24-hour SO2 table; exact Decimal gas comparison.",
    "o3": "DAO 2000-81 Annex A ozone tables and mandatory high-8-hour one-hour switch.",
    "co": "DAO 2000-81 Annex A rolling 8-hour CO table.",
    "no2": "DAO 2000-81 Annex A one-hour NO2 sparse table.",
}


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _normalize(
    parameter_code: str, concentration: Any, input_unit: str
) -> tuple[Decimal | None, str | None, str | None]:
    value = _decimal(concentration)
    if value is None:
        return None, None, "invalid_concentration"
    unit = input_unit.strip().lower()
    if parameter_code in {"pm25", "pm10"}:
        if unit == "ug_m3":
            return value, "µg/m³", None
        if unit == "mg_m3":
            return value * Decimal("1000"), "µg/m³", None
        if unit == "ug_ncm":
            return None, None, "conversion_not_supported"
        return None, None, "unsupported_unit"
    if unit == "ppm":
        return value, "ppm", None
    if unit == "ppb":
        return value / Decimal("1000"), "ppm", None
    if unit in {"ug_m3", "mg_m3"}:
        return None, None, "conversion_not_supported"
    return None, None, "unsupported_unit"


def _unavailable(
    reason: str,
    *,
    normalized_concentration: Decimal | None = None,
    normalized_unit: str | None = None,
    preprocessed_concentration: Decimal | None = None,
) -> dict[str, Any]:
    return {
        "normalized_concentration": (
            str(normalized_concentration)
            if normalized_concentration is not None
            else None
        ),
        "normalized_unit": normalized_unit,
        "preprocessed_concentration": (
            str(preprocessed_concentration)
            if preprocessed_concentration is not None
            else None
        ),
        "numeric_value": None,
        "category_code": None,
        "category_label": None,
        "category_color": None,
        "calculation_status": "unavailable",
        "eligibility_status": "ineligible",
        "coverage_status": "none",
        "exclusion_reason": reason,
        "aqi_scale_status": None,
    }


def calculate_component_independently(
    component_code: str,
    concentration: Any,
    input_unit: str,
) -> dict[str, Any]:
    component = COMPONENTS[component_code]
    parameter_code = component["parameter_code"]
    normalized, normalized_unit, reason = _normalize(
        parameter_code, concentration, input_unit
    )
    if reason or normalized is None:
        return _unavailable(reason or "unsupported_unit")
    truncate_places = component["truncate_places"]
    preprocessed = normalized
    if truncate_places is not None:
        quantum = Decimal("1").scaleb(-truncate_places)
        preprocessed = normalized.quantize(quantum, rounding=ROUND_DOWN)

    selected = next(
        (
            band
            for band in component["bands"]
            if preprocessed >= band[0]
            and (band[1] is None or preprocessed <= band[1])
        ),
        None,
    )
    if selected is None:
        first_low = component["bands"][0][0]
        last_high = component["bands"][-1][1]
        if preprocessed < first_low:
            return _unavailable(
                component["below_first_reason"],
                normalized_concentration=normalized,
                normalized_unit=normalized_unit,
                preprocessed_concentration=preprocessed,
            )
        if last_high is not None and preprocessed > last_high:
            category_label, category_color = CATEGORIES["emergency"]
            return {
                "normalized_concentration": str(normalized),
                "normalized_unit": normalized_unit,
                "preprocessed_concentration": str(preprocessed),
                "numeric_value": None,
                "category_code": "emergency",
                "category_label": category_label,
                "category_color": category_color,
                "calculation_status": "category_only",
                "eligibility_status": "eligible",
                "coverage_status": "complete",
                "exclusion_reason": None,
                "aqi_scale_status": "above_published_numeric_range",
            }
        return _unavailable(
            "published_breakpoint_gap",
            normalized_concentration=normalized,
            normalized_unit=normalized_unit,
            preprocessed_concentration=preprocessed,
        )

    low, high, index_low, index_high, category_code = selected
    category_label, category_color = CATEGORIES[category_code]
    if high is None:
        numeric_value = None
        calculation_status = "category_only"
        aqi_scale_status = "above_published_numeric_range"
    else:
        numeric_value = (
            Decimal(index_high - index_low)
            / (high - low)
            * (preprocessed - low)
            + Decimal(index_low)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        calculation_status = "calculated"
        aqi_scale_status = "within_published_numeric_range"
    return {
        "normalized_concentration": str(normalized),
        "normalized_unit": normalized_unit,
        "preprocessed_concentration": str(preprocessed),
        "numeric_value": str(numeric_value) if numeric_value is not None else None,
        "category_code": category_code,
        "category_label": category_label,
        "category_color": category_color,
        "calculation_status": calculation_status,
        "eligibility_status": "eligible",
        "coverage_status": "complete",
        "exclusion_reason": None,
        "aqi_scale_status": aqi_scale_status,
    }


def _component_case(
    case_id: str,
    component_code: str,
    concentration: str,
    input_unit: str,
    case_kind: str,
) -> dict[str, Any]:
    parameter_code = COMPONENTS[component_code]["parameter_code"]
    return {
        "case_id": case_id,
        "group": "synthetic_regulatory_boundary_cases",
        "case_kind": case_kind,
        "parameter_code": parameter_code,
        "component_code": component_code,
        "source_evidence": {
            "synthetic_concentration": concentration,
            "input_unit": input_unit,
        },
        "independent_result": calculate_component_independently(
            component_code, concentration, input_unit
        ),
        "methodology_reference_note": METHODOLOGY_NOTES[parameter_code],
        "reviewer_status": "pending",
    }


def _boundary_cases() -> list[dict[str, Any]]:
    cases = []
    default_units = {
        "pm25": "ug_m3",
        "pm10": "ug_m3",
        "so2": "ppm",
        "o3": "ppm",
        "co": "ppm",
        "no2": "ppm",
    }
    for component_code, component in COMPONENTS.items():
        parameter_code = component["parameter_code"]
        for band_index, band in enumerate(component["bands"], start=1):
            low, high, _, _, _ = band
            cases.append(
                _component_case(
                    f"{component_code}_band_{band_index}_lower",
                    component_code,
                    str(low),
                    default_units[parameter_code],
                    "exact_breakpoint",
                )
            )
            if high is not None:
                cases.append(
                    _component_case(
                        f"{component_code}_band_{band_index}_upper",
                        component_code,
                        str(high),
                        default_units[parameter_code],
                        "exact_breakpoint",
                    )
                )
    return cases


def _gap_and_range_cases() -> list[dict[str, Any]]:
    specifications = (
        ("pm25_published_gap", "pm25_24_hour", "90.5", "ug_m3"),
        ("so2_published_gap", "so2_24_hour", "0.0345", "ppm"),
        ("o3_8_hour_published_gap", "o3_8_hour", "0.0645", "ppm"),
        ("o3_1_hour_undefined_low", "o3_1_hour", "0.100", "ppm"),
        ("co_published_gap", "co_8_hour", "4.45", "ppm"),
        ("no2_undefined_low", "no2_1_hour", "0.64", "ppm"),
        ("pm10_category_only_emergency", "pm10_24_hour", "505", "ug_m3"),
        ("so2_category_only_emergency", "so2_24_hour", "0.805", "ppm"),
        ("o3_category_only_emergency", "o3_1_hour", "0.505", "ppm"),
        ("co_category_only_emergency", "co_8_hour", "40.5", "ppm"),
        ("no2_category_only_emergency", "no2_1_hour", "1.65", "ppm"),
    )
    return [
        _component_case(case_id, component, concentration, unit, "range_behavior")
        for case_id, component, concentration, unit in specifications
    ]


def _unit_cases() -> list[dict[str, Any]]:
    specifications = (
        ("pm25_exact_mg_conversion", "pm25_24_hour", "0.025", "mg_m3"),
        ("pm25_normal_condition_rejected", "pm25_24_hour", "25", "ug_ncm"),
        ("pm10_exact_mg_conversion", "pm10_24_hour", "0.054", "mg_m3"),
        ("so2_exact_ppb_conversion", "so2_24_hour", "35", "ppb"),
        ("o3_exact_ppb_conversion", "o3_8_hour", "65", "ppb"),
        ("co_exact_ppb_conversion", "co_8_hour", "4500", "ppb"),
        ("no2_exact_ppb_conversion", "no2_1_hour", "650", "ppb"),
        ("so2_mass_conversion_rejected", "so2_24_hour", "35", "ug_m3"),
        ("o3_mass_conversion_rejected", "o3_8_hour", "65", "ug_m3"),
        ("co_mass_conversion_rejected", "co_8_hour", "4500", "ug_m3"),
        ("no2_mass_conversion_rejected", "no2_1_hour", "650", "ug_m3"),
    )
    return [
        _component_case(case_id, component, concentration, unit, "unit_policy")
        for case_id, component, concentration, unit in specifications
    ]


def _ozone_switch_cases() -> list[dict[str, Any]]:
    one_hour = calculate_component_independently("o3_1_hour", "0.405", "ppm")
    return [
        {
            "case_id": "o3_high_eight_hour_requires_one_hour",
            "group": "synthetic_regulatory_boundary_cases",
            "case_kind": "ozone_switch",
            "parameter_code": "o3",
            "component_code": "ozone_latest_completed_window",
            "source_evidence": {
                "eight_hour_concentration": "0.375",
                "eight_hour_input_unit": "ppm",
                "one_hour_concentration": None,
                "one_hour_input_unit": None,
            },
            "independent_result": _unavailable(
                "no_applicable_ozone_candidate",
                normalized_concentration=Decimal("0.375"),
                normalized_unit="ppm",
                preprocessed_concentration=Decimal("0.375"),
            ),
            "methodology_reference_note": METHODOLOGY_NOTES["o3"],
            "reviewer_status": "pending",
        },
        {
            "case_id": "o3_high_eight_hour_selects_one_hour",
            "group": "synthetic_regulatory_boundary_cases",
            "case_kind": "ozone_switch",
            "parameter_code": "o3",
            "component_code": "ozone_latest_completed_window",
            "source_evidence": {
                "eight_hour_concentration": "0.375",
                "eight_hour_input_unit": "ppm",
                "one_hour_concentration": "0.405",
                "one_hour_input_unit": "ppm",
            },
            "independent_result": one_hour,
            "methodology_reference_note": METHODOLOGY_NOTES["o3"],
            "reviewer_status": "pending",
        },
    ]


def _completeness_case(
    case_id: str,
    case_kind: str,
    source_evidence: dict[str, Any],
    independent_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "group": "synthetic_regulatory_boundary_cases",
        "case_kind": case_kind,
        "parameter_code": "pm25",
        "component_code": "temporal_qualification",
        "source_evidence": source_evidence,
        "independent_result": independent_result,
        "methodology_reference_note": (
            "EMB MC 2021-07 representativeness rules applied to AQI periods "
            "as explicit CompassAQ policy."
        ),
        "reviewer_status": "pending",
    }


def _completeness_cases() -> list[dict[str, Any]]:
    return [
        _completeness_case(
            "two_minute_hour_22_of_30",
            "hourly_completeness",
            {"expected_position_count": 30, "valid_position_count": 22},
            {
                "eligibility_status": "ineligible",
                "coverage_status": "none",
                "expected_observation_count": 30,
                "valid_observation_count": 22,
                "required_valid_observation_count": 23,
                "exclusion_reason": "hourly_completeness_not_met",
            },
        ),
        _completeness_case(
            "two_minute_hour_23_of_30",
            "hourly_completeness",
            {"expected_position_count": 30, "valid_position_count": 23},
            {
                "eligibility_status": "eligible",
                "coverage_status": "complete",
                "expected_observation_count": 30,
                "valid_observation_count": 23,
                "required_valid_observation_count": 23,
                "exclusion_reason": None,
            },
        ),
        _completeness_case(
            "rolling_window_5_of_8",
            "rolling_completeness",
            {"expected_hour_count": 8, "valid_hour_positions": [3, 4, 5, 6, 7]},
            {
                "eligibility_status": "ineligible",
                "coverage_status": "none",
                "expected_hour_count": 8,
                "valid_hour_count": 5,
                "required_valid_hour_count": 6,
                "exclusion_reason": "rolling_8_hour_completeness_not_met",
            },
        ),
        _completeness_case(
            "rolling_window_6_of_8",
            "rolling_completeness",
            {"expected_hour_count": 8, "valid_hour_positions": [2, 3, 4, 5, 6, 7]},
            {
                "eligibility_status": "eligible",
                "coverage_status": "complete",
                "expected_hour_count": 8,
                "valid_hour_count": 6,
                "required_valid_hour_count": 6,
                "exclusion_reason": None,
            },
        ),
        _completeness_case(
            "completed_day_17_of_24",
            "daily_completeness",
            {
                "missing_hour_positions": [0, 1, 2, 8, 9, 16, 17],
                "expected_hour_count": 24,
            },
            {
                "eligibility_status": "ineligible",
                "coverage_status": "none",
                "expected_hour_count": 24,
                "valid_hour_count": 17,
                "required_valid_hour_count": 18,
                "block_valid_hour_counts": [5, 6, 6],
                "maximum_consecutive_missing_hours": 3,
                "exclusion_reason": "daily_completeness_not_met",
            },
        ),
        _completeness_case(
            "completed_day_18_of_24",
            "daily_completeness",
            {
                "missing_hour_positions": [0, 1, 8, 9, 16, 17],
                "expected_hour_count": 24,
            },
            {
                "eligibility_status": "eligible",
                "coverage_status": "complete",
                "expected_hour_count": 24,
                "valid_hour_count": 18,
                "required_valid_hour_count": 18,
                "block_valid_hour_counts": [6, 6, 6],
                "maximum_consecutive_missing_hours": 2,
                "exclusion_reason": None,
            },
        ),
        _completeness_case(
            "completed_day_block_only_5",
            "daily_completeness",
            {
                "missing_hour_positions": [0, 3, 6],
                "expected_hour_count": 24,
            },
            {
                "eligibility_status": "ineligible",
                "coverage_status": "none",
                "expected_hour_count": 24,
                "valid_hour_count": 21,
                "required_valid_hour_count": 18,
                "block_valid_hour_counts": [5, 8, 8],
                "maximum_consecutive_missing_hours": 1,
                "exclusion_reason": "daily_completeness_not_met",
            },
        ),
        _completeness_case(
            "completed_day_three_consecutive_missing",
            "daily_completeness",
            {
                "missing_hour_positions": [7, 8, 9],
                "expected_hour_count": 24,
            },
            {
                "eligibility_status": "ineligible",
                "coverage_status": "none",
                "expected_hour_count": 24,
                "valid_hour_count": 21,
                "required_valid_hour_count": 18,
                "block_valid_hour_counts": [7, 6, 8],
                "maximum_consecutive_missing_hours": 3,
                "exclusion_reason": "daily_completeness_not_met",
            },
        ),
        _completeness_case(
            "completed_day_missing_all",
            "missing_data",
            {
                "missing_hour_positions": list(range(24)),
                "expected_hour_count": 24,
            },
            {
                "eligibility_status": "ineligible",
                "coverage_status": "none",
                "expected_hour_count": 24,
                "valid_hour_count": 0,
                "required_valid_hour_count": 18,
                "block_valid_hour_counts": [0, 0, 0],
                "maximum_consecutive_missing_hours": 24,
                "exclusion_reason": "daily_completeness_not_met",
            },
        ),
        _completeness_case(
            "deterministic_sensor_selection",
            "sensor_selection",
            {
                "candidate_sensor_ids": [100011, 100007],
                "eligible_sensor_ids": [100011, 100007],
            },
            {
                "eligibility_status": "eligible",
                "coverage_status": "complete",
                "selected_sensor_id": 100007,
                "selected_sensor_reason": "lowest_eligible_sensor_id",
                "exclusion_reason": None,
            },
        ),
    ]


def build_synthetic_candidate_bundle() -> dict[str, Any]:
    cases = (
        _boundary_cases()
        + _gap_and_range_cases()
        + _unit_cases()
        + _ozone_switch_cases()
        + _completeness_cases()
    )
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Synthetic Philippine case IDs must be unique")
    return {
        "schema_version": "philippines-denr-synthetic-candidates-1",
        "artifact_kind": "independent_synthetic_candidates",
        "bundle_status": "candidate_awaiting_analyst_approval",
        "methodology_code": "philippines_denr_aqi",
        "methodology_version": "denr_emb_aqi_2021",
        "production_code_imported": False,
        "provider_calls": 0,
        "credential_reads": 0,
        "purpleair_points_consumed": 0,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            build_synthetic_candidate_bundle(),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
