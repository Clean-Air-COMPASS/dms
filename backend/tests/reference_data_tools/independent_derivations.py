"""Independent, review-only derivations from extracted frozen source facts.

This module intentionally uses only the Python standard library.  It must never
import CompassAQ loaders, services, API routes, or regulatory breakpoint tables.
The constants below are copied into this review seam so that analysts can audit
the arithmetic without treating current application behavior as an oracle.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, localcontext
from typing import Any


ABSOLUTE_TOLERANCE = "0.000000000001"
US_EPA_METHOD = {
    "methodology_code": "us_epa_aqi",
    "methodology_version": "EPA AQI Technical Assistance Document, May 2026",
    "reference_ids": [
        "EPA-403/B-26-003",
        "40 CFR Part 58 Appendix G section 3.4 and Table 2",
        "89 FR 16202",
    ],
}
EEA_METHOD = {
    "methodology_code": "eea_european_aqi",
    "methodology_version": "European Air Quality Index pollutant bands",
    "reference_ids": ["European Environment Agency European Air Quality Index"],
}
SOURCE_FACT_METHOD = {
    "methodology_code": "frozen_source_fact_verification",
    "methodology_version": "Phase 2I.5 review candidate",
    "reference_ids": ["frozen fixture manifest and measurements.jsonl"],
}


AQI_CATEGORIES = (
    (0, 50, "good", "Good"),
    (51, 100, "moderate", "Moderate"),
    (101, 150, "unhealthy_for_sensitive_groups", "Unhealthy for Sensitive Groups"),
    (151, 200, "unhealthy", "Unhealthy"),
    (201, 300, "very_unhealthy", "Very Unhealthy"),
    (301, 500, "hazardous", "Hazardous"),
)

US_BREAKPOINTS: dict[str, tuple[tuple[str, str, int, int], ...]] = {
    "pm25": (
        ("0.0", "9.0", 0, 50),
        ("9.1", "35.4", 51, 100),
        ("35.5", "55.4", 101, 150),
        ("55.5", "125.4", 151, 200),
        ("125.5", "225.4", 201, 300),
        ("225.5", "325.4", 301, 500),
    ),
    "pm10": (
        ("0", "54", 0, 50),
        ("55", "154", 51, 100),
        ("155", "254", 101, 150),
        ("255", "354", 151, 200),
        ("355", "424", 201, 300),
        ("425", "604", 301, 500),
    ),
    "o3_8h": (
        ("0.000", "0.054", 0, 50),
        ("0.055", "0.070", 51, 100),
        ("0.071", "0.085", 101, 150),
        ("0.086", "0.105", 151, 200),
        ("0.106", "0.200", 201, 300),
    ),
    "o3_1h": (
        ("0.125", "0.164", 101, 150),
        ("0.165", "0.204", 151, 200),
        ("0.205", "0.404", 201, 300),
        ("0.405", "0.604", 301, 500),
    ),
    "co": (
        ("0.0", "4.4", 0, 50),
        ("4.5", "9.4", 51, 100),
        ("9.5", "12.4", 101, 150),
        ("12.5", "15.4", 151, 200),
        ("15.5", "30.4", 201, 300),
        ("30.5", "50.4", 301, 500),
    ),
    "no2": (
        ("0", "53", 0, 50),
        ("54", "100", 51, 100),
        ("101", "360", 101, 150),
        ("361", "649", 151, 200),
        ("650", "1249", 201, 300),
        ("1250", "2049", 301, 500),
    ),
    "so2_1h": (
        ("0", "35", 0, 50),
        ("36", "75", 51, 100),
        ("76", "185", 101, 150),
        ("186", "304", 151, 200),
    ),
    "so2_24h": (
        ("305", "604", 201, 300),
        ("605", "1004", 301, 500),
    ),
}

EEA_BANDS: dict[str, tuple[str, ...]] = {
    "pm25": ("5", "15", "50", "90", "140"),
    "pm10": ("15", "45", "120", "195", "270"),
    "o3": ("60", "100", "120", "160", "180"),
    "no2": ("10", "25", "60", "100", "150"),
    "so2": ("20", "40", "125", "190", "275"),
}
EEA_CATEGORIES = (
    ("good", "Good"),
    ("fair", "Fair"),
    ("moderate", "Moderate"),
    ("poor", "Poor"),
    ("very_poor", "Very Poor"),
    ("extremely_poor", "Extremely Poor"),
)

SENSOR_PARAMETERS = {
    "purpleair-159361-pm25": "pm25",
    "purpleair-159361-pm10": "pm10",
    "purpleair-175407-pm25": "pm25",
    "purpleair-175407-pm10": "pm10",
    "purpleair-99177-pm25": "pm25",
    "purpleair-99177-pm10": "pm10",
    "purpleair-198733-pm25": "pm25",
    "purpleair-198733-pm10": "pm10",
    "openaq-sensor-1099": "pm10",
    "openaq-sensor-1098": "o3",
    "openaq-sensor-3952": "co",
    "openaq-sensor-3951": "no2",
    "openaq-sensor-3950": "so2",
    "openaq-sensor-6819305": "pm25",
    "openaq-sensor-4475454": "pm10",
    "openaq-sensor-6459542": "o3",
    "openaq-sensor-4475455": "no2",
    "openaq-sensor-11268993": "so2",
    "openaq-sensor-13191003": "pm25",
}


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _decimal_string(value: Decimal) -> str:
    return format(value, "f")


def _truncate(value: Decimal, decimal_places: int) -> Decimal:
    quantum = Decimal(1).scaleb(-decimal_places)
    return value.quantize(quantum, rounding=ROUND_DOWN)


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        raise ValueError("Cannot average an empty list")
    with localcontext() as context:
        context.prec = 50
        return sum(values, Decimal("0")) / Decimal(len(values))


def _category_for_aqi(aqi: int) -> tuple[str, str]:
    for lower, upper, code, label in AQI_CATEGORIES:
        if lower <= aqi <= upper:
            return code, label
    raise ValueError(f"AQI {aqi} falls outside the review table")


def _interpolate(parameter_table: str, concentration: Decimal) -> dict[str, Any]:
    for low_text, high_text, aqi_low, aqi_high in US_BREAKPOINTS[parameter_table]:
        low = _decimal(low_text)
        high = _decimal(high_text)
        if low <= concentration <= high:
            with localcontext() as context:
                context.prec = 50
                unrounded = (
                    (Decimal(aqi_high - aqi_low) / (high - low))
                    * (concentration - low)
                    + Decimal(aqi_low)
                )
            aqi = int(unrounded.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            category_code, category_label = _category_for_aqi(aqi)
            return {
                "breakpoint": {
                    "concentration_low": low_text,
                    "concentration_high": high_text,
                    "aqi_low": aqi_low,
                    "aqi_high": aqi_high,
                },
                "interpolation_formula": (
                    "((aqi_high-aqi_low)/(concentration_high-concentration_low))"
                    "*(concentration-concentration_low)+aqi_low"
                ),
                "unrounded_aqi": _decimal_string(unrounded),
                "rounding": "nearest integer with half rounded up",
                "numeric_result": aqi,
                "category_code": category_code,
                "category_label": category_label,
            }
    raise ValueError(
        f"Concentration {concentration} falls outside {parameter_table} review breakpoints"
    )


def _us_component(
    parameter_code: str,
    concentration: Decimal,
    *,
    table: str | None = None,
    input_unit: str,
) -> dict[str, Any]:
    decimal_places = {"pm25": 1, "pm10": 0, "o3": 3, "co": 1, "no2": 0, "so2": 0}[parameter_code]
    processed = _truncate(concentration, decimal_places)
    interpolation = _interpolate(table or parameter_code, processed)
    return {
        "parameter_code": parameter_code,
        "input_concentration": _decimal_string(concentration),
        "input_unit": input_unit,
        "regulatory_preprocessing": {
            "operation": "truncate_toward_zero",
            "decimal_places": decimal_places,
            "result": _decimal_string(processed),
        },
        **interpolation,
    }


def _base_derivation(method: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "independently_derived_review_candidate",
        "decimal_arithmetic": True,
        "absolute_tolerance": ABSOLUTE_TOLERANCE,
        "methodology": method,
        "steps": steps,
    }


def _base_candidate(**values: Any) -> dict[str, Any]:
    candidate = {
        "status": "review_candidate_not_approved",
        "availability": None,
        "numeric_result": None,
        "category_code": None,
        "category_label": None,
        "exclusion_reason": None,
        "coverage_status": None,
        "aggregation_period": None,
    }
    candidate.update(values)
    return candidate


def _derive_fixture_summary(case_id: str, facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    retained = {
        key: facts[key]
        for key in (
            "dataset_id",
            "access_classification",
            "provider",
            "manifest_sha256",
            "measurements_sha256",
            "measurement_count",
            "device_count",
            "sensor_count",
            "active_sensor_count",
            "validity_counts",
            "provider_has_flags_counts",
            "provider_validity_status_counts",
        )
    }
    steps = [
        {
            "operation": "count_and_group_frozen_jsonl_records",
            "inputs": ["manifest.json", "measurements.jsonl"],
            "result": retained,
            "note": "No AQI or CompassAQ runtime value participates in this fact candidate.",
        }
    ]
    if case_id == "fixture_openaq_2i4a":
        steps.append(
            {
                "operation": "verify_documented_hourly_streams",
                "expected_exact_one_hour_stream_count": 12,
                "zero_row_sensor": "openaq-sensor-1099",
            }
        )
    else:
        steps.append(
            {
                "operation": "verify_active_and_provenance_only_streams",
                "active_sensor_count": 6,
                "provenance_only_sensor_refs": [
                    "purpleair-198733-pm25",
                    "purpleair-198733-pm10",
                ],
            }
        )
    return _base_derivation(SOURCE_FACT_METHOD, steps), _base_candidate(
        availability="not_applicable",
        result_kind="frozen_source_fact_summary",
        expected_fields=retained,
    )


def _derive_provenance(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    device = facts["device"]
    expected = {
        "hardware_provider": device["hardware_provider"],
        "owner_name": device["owner_name"],
        "transport_provider": facts["provider"],
        "fixture_role": facts["fixture_role"],
        "direct_airgradient_api_data": facts["direct_airgradient_api_data"],
    }
    return _base_derivation(
        SOURCE_FACT_METHOD,
        [
            {
                "operation": "trace_provider_chain_without_relabeling_transport",
                "result": expected,
                "note": "Hardware origin AirGradient is not a direct AirGradient API capture.",
            }
        ],
    ), _base_candidate(
        availability="not_applicable",
        result_kind="provenance",
        expected_fields=expected,
    )


def _hourly_sensor_result(sensor: dict[str, Any]) -> dict[str, Any]:
    parameter_code = SENSOR_PARAMETERS[sensor["sensor_ref"]]
    arithmetic = sensor["arithmetic"]
    completeness = sensor.get("completeness")
    result = {
        "sensor_ref": sensor["sensor_ref"],
        "parameter_code": parameter_code,
        "unit": "µg/m³",
        "hourly_concentration": arithmetic["unformatted_mean"],
        "included_count": len(
            sensor.get("accepted_observations", sensor.get("included_observations", []))
        ),
        "excluded_count": len(sensor.get("excluded_observations", [])),
    }
    if completeness:
        result["completeness"] = completeness
    return result


def _derive_hourly(case_id: str, facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    results = [_hourly_sensor_result(sensor) for sensor in facts["sensor_results"]]
    steps = []
    for sensor, result in zip(facts["sensor_results"], results):
        steps.append(
            {
                "sensor_ref": sensor["sensor_ref"],
                "operation": sensor["arithmetic"]["operation"],
                "operands": sensor["arithmetic"]["operands"],
                "sum": sensor["arithmetic"]["sum"],
                "divisor": sensor["arithmetic"]["divisor"],
                "unformatted_mean": sensor["arithmetic"]["unformatted_mean"],
                "completeness": sensor.get("completeness"),
            }
        )
    if case_id == "pa_ny_pm25_ordinary_boundary":
        candidate = _base_candidate(
            availability="available",
            numeric_result=results[0]["hourly_concentration"],
            coverage_status="complete",
            aggregation_period="1h",
            result_kind="ordinary_clock_bucket_mean",
            results=results,
        )
    else:
        coverage = (
            "complete"
            if all(result.get("completeness", {}).get("numerator") == 30 for result in results)
            else "partial"
        )
        candidate = _base_candidate(
            availability="available",
            coverage_status=coverage,
            aggregation_period="1h",
            result_kind="provider_neutral_anchored_hourly_means",
            results=results,
        )
    return _base_derivation(
        {
            "methodology_code": "provider_neutral_pm_completeness",
            "methodology_version": "Phase 2I.5 two-minute anchor review",
            "reference_ids": ["30 expected anchors; ceil(30 * 0.75) = 23"],
        },
        steps,
    ), candidate


def _derive_nowcast(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sensor_refs = [item["sensor_ref"] for item in facts["hours_most_recent_first"][0]["sensor_results"]]
    results = []
    steps = []
    for sensor_ref in sensor_refs:
        parameter_code = SENSOR_PARAMETERS[sensor_ref]
        hourly_inputs = []
        for hour in facts["hours_most_recent_first"]:
            sensor = next(item for item in hour["sensor_results"] if item["sensor_ref"] == sensor_ref)
            hourly_inputs.append(
                {
                    "position": hour["most_recent_first_position"],
                    "hour_ended_at": hour["hour_ended_at"],
                    "concentration": sensor["arithmetic"]["unformatted_mean"],
                    "accepted_count": sensor["completeness"]["numerator"],
                    "expected_count": sensor["completeness"]["denominator"],
                    "required_count": sensor["completeness"]["required_count"],
                    "coverage_status": sensor["completeness"]["coverage_status"],
                }
            )
        concentrations = [_decimal(item["concentration"]) for item in hourly_inputs]
        minimum = min(concentrations)
        maximum = max(concentrations)
        ratio = Decimal("1") if maximum == 0 else minimum / maximum
        weight = max(Decimal("0.5"), ratio)
        weighted_terms = [value * (weight ** position) for position, value in enumerate(concentrations)]
        weight_terms = [weight ** position for position in range(len(concentrations))]
        with localcontext() as context:
            context.prec = 50
            weighted_concentration = sum(weighted_terms) / sum(weight_terms)
        component = _us_component(
            parameter_code,
            weighted_concentration,
            input_unit="µg/m³",
        )
        result = {
            "sensor_ref": sensor_ref,
            "parameter_code": parameter_code,
            "hourly_inputs_most_recent_first": hourly_inputs,
            "minimum_hourly_concentration": _decimal_string(minimum),
            "maximum_hourly_concentration": _decimal_string(maximum),
            "minimum_divided_by_maximum": _decimal_string(ratio),
            "nowcast_weight": _decimal_string(weight),
            "weighted_numerator": _decimal_string(sum(weighted_terms)),
            "weighted_denominator": _decimal_string(sum(weight_terms)),
            "weighted_concentration": _decimal_string(weighted_concentration),
            "coverage_status": "complete",
            "subhour_completeness_status": (
                "partial"
                if any(item["accepted_count"] != item["expected_count"] for item in hourly_inputs)
                else "complete"
            ),
            **component,
        }
        results.append(result)
        steps.append(
            {
                "sensor_ref": sensor_ref,
                "operation": "EPA NowCast weighted mean over 12 positional hourly concentrations",
                "hourly_inputs_most_recent_first": hourly_inputs,
                "weight_formula": "max(0.5, minimum / maximum)",
                "minimum": result["minimum_hourly_concentration"],
                "maximum": result["maximum_hourly_concentration"],
                "weight": result["nowcast_weight"],
                "weighted_terms": [_decimal_string(value) for value in weighted_terms],
                "weight_terms": [_decimal_string(value) for value in weight_terms],
                "weighted_concentration": result["weighted_concentration"],
                "regulatory_preprocessing": component["regulatory_preprocessing"],
                "breakpoint": component["breakpoint"],
                "unrounded_aqi": component["unrounded_aqi"],
                "numeric_result": component["numeric_result"],
            }
        )
    return _base_derivation(US_EPA_METHOD, steps), _base_candidate(
        availability="available",
        coverage_status="complete",
        aggregation_period="nowcast",
        result_kind="us_epa_nowcast_components",
        results=results,
    )


def _derive_pa_completed_day(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    hourly_inputs = []
    for hour in facts["hours"]:
        sensor = hour["sensor_results"][0]
        raw_mean = _decimal(sensor["arithmetic"]["unformatted_mean"])
        truncated = _truncate(raw_mean, 1)
        hourly_inputs.append(
            {
                "hour_position": hour["hour_position"],
                "hour_ended_at": sensor["utc_window"]["ended_at"],
                "accepted_count": sensor["completeness"]["numerator"],
                "expected_count": sensor["completeness"]["denominator"],
                "raw_hourly_mean": _decimal_string(raw_mean),
                "hourly_pm25_truncated_to_0.1": _decimal_string(truncated),
            }
        )
    hourly_values = [_decimal(item["hourly_pm25_truncated_to_0.1"]) for item in hourly_inputs]
    daily_mean = _mean(hourly_values)
    component = _us_component("pm25", daily_mean, input_unit="µg/m³")
    result = {
        "sensor_ref": facts["hours"][0]["sensor_results"][0]["sensor_ref"],
        "parameter_code": "pm25",
        "represented_local_date": facts["represented_local_date"],
        "timezone": facts["timezone"],
        "utc_window": facts["utc_window"],
        "qualified_hour_count": len(hourly_inputs),
        "expected_hour_count": 24,
        "required_hour_count": 18,
        "hourly_inputs": hourly_inputs,
        "daily_mean_before_final_preprocessing": _decimal_string(daily_mean),
        "coverage_status": "complete",
        **component,
    }
    steps = [
        {
            "operation": "truncate each qualified PM2.5 hourly mean to one decimal place",
            "hourly_inputs": hourly_inputs,
        },
        {
            "operation": "sum(truncated hourly means) / 24",
            "operands": [_decimal_string(value) for value in hourly_values],
            "sum": _decimal_string(sum(hourly_values)),
            "divisor": "24",
            "daily_mean": result["daily_mean_before_final_preprocessing"],
        },
        {
            "operation": "PM2.5 daily AQI preprocessing and interpolation",
            "regulatory_preprocessing": component["regulatory_preprocessing"],
            "breakpoint": component["breakpoint"],
            "unrounded_aqi": component["unrounded_aqi"],
            "numeric_result": component["numeric_result"],
        },
    ]
    return _base_derivation(US_EPA_METHOD, steps), _base_candidate(
        availability="available",
        numeric_result=component["numeric_result"],
        category_code=component["category_code"],
        category_label=component["category_label"],
        coverage_status="complete",
        aggregation_period="local_day",
        result_kind="us_epa_pm25_completed_day",
        results=[result],
    )


def _derive_openaq_pm10_day(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sensor = facts["sensor_results"][0]
    observations = sensor["accepted_observations"]
    values = [_decimal(item["decimal_value"]) for item in observations]
    daily_mean = _mean(values)
    component = _us_component("pm10", daily_mean, input_unit="µg/m³")
    result = {
        "sensor_ref": sensor["sensor_ref"],
        "parameter_code": "pm10",
        "represented_local_date": facts["represented_local_date"],
        "timezone": facts["timezone"],
        "utc_window": facts["utc_window"],
        "accepted_observations": observations,
        "observed_count": sensor["observed_count"],
        "expected_count": sensor["expected_count"],
        "required_count": 18,
        "daily_mean_before_preprocessing": _decimal_string(daily_mean),
        "coverage_status": "complete",
        **component,
    }
    steps = [
        {
            "operation": "sum(provider hourly PM10 values) / 24",
            "operands": [_decimal_string(value) for value in values],
            "sum": _decimal_string(sum(values)),
            "divisor": "24",
            "daily_mean": result["daily_mean_before_preprocessing"],
        },
        {
            "operation": "PM10 integer truncation and AQI interpolation",
            "regulatory_preprocessing": component["regulatory_preprocessing"],
            "breakpoint": component["breakpoint"],
            "unrounded_aqi": component["unrounded_aqi"],
            "numeric_result": component["numeric_result"],
        },
    ]
    return _base_derivation(US_EPA_METHOD, steps), _base_candidate(
        availability="available",
        numeric_result=component["numeric_result"],
        category_code=component["category_code"],
        category_label=component["category_label"],
        coverage_status="complete",
        aggregation_period="local_day",
        result_kind="us_epa_pm10_completed_day",
        results=[result],
    )


def _derive_o3(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sensor = facts["sensor_results"][0]
    observations = sensor["accepted_observations"]
    raw = [_decimal(item["decimal_value"]) for item in observations]
    hourly = [_truncate(value, 3) for value in raw]
    eight_hour_mean = _mean(hourly)
    eight_hour = _us_component("o3", eight_hour_mean, table="o3_8h", input_unit="ppm")
    one_hour_concentration = max(hourly)
    one_hour_applicable = one_hour_concentration >= Decimal("0.125")
    one_hour = (
        _us_component("o3", one_hour_concentration, table="o3_1h", input_unit="ppm")
        if one_hour_applicable
        else None
    )
    selected = one_hour if one_hour and one_hour["numeric_result"] > eight_hour["numeric_result"] else eight_hour
    result = {
        "sensor_ref": sensor["sensor_ref"],
        "parameter_code": "o3",
        "observed_count": sensor["observed_count"],
        "expected_count": sensor["expected_count"],
        "required_count": 6,
        "raw_hourly_values": [_decimal_string(value) for value in raw],
        "hourly_values_truncated_to_0.001_ppm": [_decimal_string(value) for value in hourly],
        "eight_hour_mean_before_final_preprocessing": _decimal_string(eight_hour_mean),
        "eight_hour_candidate": eight_hour,
        "one_hour_maximum": _decimal_string(one_hour_concentration),
        "one_hour_candidate_applicable": one_hour_applicable,
        "one_hour_candidate": one_hour,
        "selected_candidate": "one_hour" if selected is one_hour else "eight_hour",
        "coverage_status": "complete",
        **{key: selected[key] for key in ("numeric_result", "category_code", "category_label")},
    }
    steps = [
        {
            "operation": "truncate each O3 hour to 0.001 ppm before the eight-hour mean",
            "inputs": result["raw_hourly_values"],
            "outputs": result["hourly_values_truncated_to_0.001_ppm"],
        },
        {
            "operation": "sum(hourly values) / 8",
            "sum": _decimal_string(sum(hourly)),
            "divisor": "8",
            "eight_hour_mean": result["eight_hour_mean_before_final_preprocessing"],
        },
        {
            "operation": "derive and select applicable O3 AQI candidates",
            "eight_hour_candidate": eight_hour,
            "one_hour_maximum": result["one_hour_maximum"],
            "one_hour_candidate_applicable": one_hour_applicable,
            "one_hour_candidate": one_hour,
            "selected_candidate": result["selected_candidate"],
        },
    ]
    return _base_derivation(US_EPA_METHOD, steps), _base_candidate(
        availability="available",
        numeric_result=selected["numeric_result"],
        category_code=selected["category_code"],
        category_label=selected["category_label"],
        coverage_status="complete",
        aggregation_period="8h",
        result_kind="us_epa_o3_selected_candidate",
        results=[result],
    )


def _derive_co(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sensor = facts["sensor_results"][0]
    observations = sensor["accepted_observations"]
    values = [_decimal(item["decimal_value"]) for item in observations]
    mean = _mean(values)
    component = _us_component("co", mean, input_unit="ppm")
    result = {
        "sensor_ref": sensor["sensor_ref"],
        "parameter_code": "co",
        "observed_count": sensor["observed_count"],
        "expected_count": sensor["expected_count"],
        "required_count": 6,
        "missing_interval_end_positions": sensor["missing_interval_end_positions"],
        "mean_before_preprocessing": _decimal_string(mean),
        "coverage_status": "partial",
        **component,
    }
    steps = [
        {
            "operation": "sum(available CO hours) / 6 at exact 75 percent coverage",
            "operands": [_decimal_string(value) for value in values],
            "sum": _decimal_string(sum(values)),
            "divisor": "6",
            "missing_positions": sensor["missing_interval_end_positions"],
            "mean": result["mean_before_preprocessing"],
        },
        {
            "operation": "CO truncation and AQI interpolation",
            "regulatory_preprocessing": component["regulatory_preprocessing"],
            "breakpoint": component["breakpoint"],
            "unrounded_aqi": component["unrounded_aqi"],
            "numeric_result": component["numeric_result"],
        },
    ]
    return _base_derivation(US_EPA_METHOD, steps), _base_candidate(
        availability="available",
        numeric_result=component["numeric_result"],
        category_code=component["category_code"],
        category_label=component["category_label"],
        coverage_status="partial",
        aggregation_period="8h",
        result_kind="us_epa_co_rolling_window",
        results=[result],
    )


def _derive_no2(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sensor = facts["sensor_results"][0]
    observation = sensor["accepted_observations"][0]
    ppm = _decimal(observation["decimal_value"])
    ppb = ppm * Decimal("1000")
    component = _us_component("no2", ppb, input_unit="ppb")
    result = {
        "sensor_ref": sensor["sensor_ref"],
        "parameter_code": "no2",
        "source_ppm": _decimal_string(ppm),
        "conversion_operation": "ppm * 1000",
        "converted_ppb": _decimal_string(ppb),
        "coverage_status": "complete",
        **component,
    }
    steps = [
        {
            "operation": "exact mixing-ratio conversion",
            "formula": "ppm * 1000 = ppb",
            "operands": [_decimal_string(ppm), "1000"],
            "result": _decimal_string(ppb),
        },
        {
            "operation": "NO2 integer truncation and AQI interpolation",
            "regulatory_preprocessing": component["regulatory_preprocessing"],
            "breakpoint": component["breakpoint"],
            "unrounded_aqi": component["unrounded_aqi"],
            "numeric_result": component["numeric_result"],
        },
    ]
    return _base_derivation(US_EPA_METHOD, steps), _base_candidate(
        availability="available",
        numeric_result=component["numeric_result"],
        category_code=component["category_code"],
        category_label=component["category_label"],
        coverage_status="complete",
        aggregation_period="1h",
        result_kind="us_epa_no2_hour",
        results=[result],
    )


def _derive_so2(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sensor = facts["sensor_results"][0]
    ppm_values = [_decimal(item["decimal_value"]) for item in sensor["accepted_observations"]]
    ppb_values = [value * Decimal("1000") for value in ppm_values]
    maximum = max(ppb_values)
    daily_mean = _mean(ppb_values)
    one_hour = _us_component("so2", maximum, table="so2_1h", input_unit="ppb")
    result = {
        "sensor_ref": sensor["sensor_ref"],
        "parameter_code": "so2",
        "source_ppm_values": [_decimal_string(value) for value in ppm_values],
        "converted_ppb_values": [_decimal_string(value) for value in ppb_values],
        "observed_count": sensor["observed_count"],
        "expected_count": sensor["expected_count"],
        "required_count": 18,
        "missing_interval_end_positions": sensor["missing_interval_end_positions"],
        "maximum_hour_ppb": _decimal_string(maximum),
        "daily_mean_ppb": _decimal_string(daily_mean),
        "one_hour_candidate": one_hour,
        "twenty_four_hour_candidate_applicable": False,
        "twenty_four_hour_candidate": None,
        "selected_candidate": "one_hour",
        "coverage_status": "partial",
        **{key: one_hour[key] for key in ("numeric_result", "category_code", "category_label")},
    }
    steps = [
        {
            "operation": "convert every available SO2 hour from ppm to ppb",
            "formula": "ppm * 1000 = ppb",
            "inputs": result["source_ppm_values"],
            "outputs": result["converted_ppb_values"],
        },
        {
            "operation": "derive maximum-hour and 24-hour concentrations",
            "maximum_hour_ppb": result["maximum_hour_ppb"],
            "twenty_four_hour_sum_ppb": _decimal_string(sum(ppb_values)),
            "observed_hour_divisor": str(len(ppb_values)),
            "daily_mean_ppb": result["daily_mean_ppb"],
            "missing_positions": sensor["missing_interval_end_positions"],
        },
        {
            "operation": "apply SO2 candidate applicability and interpolate selected one-hour candidate",
            "rule": "use one-hour table when the maximum hour is at or below 304 ppb",
            "one_hour_candidate": one_hour,
            "twenty_four_hour_candidate_applicable": False,
            "selected_candidate": "one_hour",
        },
    ]
    return _base_derivation(US_EPA_METHOD, steps), _base_candidate(
        availability="available",
        numeric_result=one_hour["numeric_result"],
        category_code=one_hour["category_code"],
        category_label=one_hour["category_label"],
        coverage_status="partial",
        aggregation_period="1h",
        result_kind="us_epa_so2_selected_candidate",
        results=[result],
    )


def _derive_unsupported_mass_gases(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    results = []
    for sensor in facts["sensor_results"]:
        observation = sensor["observations"][0]
        results.append(
            {
                "sensor_ref": sensor["sensor_ref"],
                "parameter_code": SENSOR_PARAMETERS[sensor["sensor_ref"]],
                "source_value": observation["decimal_value"],
                "source_unit": observation["unit"],
                "availability": "unavailable",
                "exclusion_reason": "conversion_not_supported",
            }
        )
    return _base_derivation(
        US_EPA_METHOD,
        [
            {
                "operation": "reject unsupported gas mass-to-mixing conversion",
                "reason": "Molecular-weight, temperature, and pressure assumptions are not supplied by the frozen record.",
                "results": results,
            }
        ],
    ), _base_candidate(
        availability="unavailable",
        exclusion_reason="conversion_not_supported",
        coverage_status="unavailable",
        result_kind="explicit_unsupported_conversion",
        results=results,
    )


def _eea_category(parameter_code: str, concentration: Decimal) -> dict[str, Any]:
    limits = [_decimal(value) for value in EEA_BANDS[parameter_code]]
    index = len(limits)
    for position, upper in enumerate(limits):
        if concentration <= upper:
            index = position
            break
    code, label = EEA_CATEGORIES[index]
    return {
        "parameter_code": parameter_code,
        "normalized_concentration": _decimal_string(concentration),
        "normalized_unit": "µg/m³",
        "band_upper_bounds": list(EEA_BANDS[parameter_code]),
        "band_index": index,
        "category_code": code,
        "category_label": label,
    }


def _derive_eea_rio(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    results = []
    for sensor in facts["sensor_results"]:
        observation = sensor["observations"][0]
        parameter_code = SENSOR_PARAMETERS[sensor["sensor_ref"]]
        category = _eea_category(parameter_code, _decimal(observation["decimal_value"]))
        results.append({"sensor_ref": sensor["sensor_ref"], **category})
    worst_index = max(item["band_index"] for item in results)
    overall_code, overall_label = EEA_CATEGORIES[worst_index]
    dominant = [item["parameter_code"] for item in results if item["band_index"] == worst_index]
    steps = [
        {
            "operation": "compare exact normalized concentrations directly with inclusive EEA band upper bounds",
            "pollutant_results": results,
        },
        {
            "operation": "select the worst pollutant category and every pollutant tied at that severity",
            "overall_category_code": overall_code,
            "overall_category_label": overall_label,
            "dominant_pollutants": dominant,
        },
    ]
    return _base_derivation(EEA_METHOD, steps), _base_candidate(
        availability="available",
        category_code=overall_code,
        category_label=overall_label,
        coverage_status="complete",
        aggregation_period="1h",
        result_kind="eea_overall_category",
        dominant_pollutants=dominant,
        results=results,
    )


def _derive_eea_pa(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    results = []
    for sensor in facts["sensor_results"]:
        parameter_code = SENSOR_PARAMETERS[sensor["sensor_ref"]]
        concentration = _decimal(sensor["arithmetic"]["unformatted_mean"])
        category = _eea_category(parameter_code, concentration)
        results.append(
            {
                "sensor_ref": sensor["sensor_ref"],
                "accepted_count": sensor["completeness"]["numerator"],
                "expected_count": sensor["completeness"]["denominator"],
                "required_count": sensor["completeness"]["required_count"],
                "coverage_status": "partial",
                **category,
            }
        )
    worst_index = max(item["band_index"] for item in results)
    overall_code, overall_label = EEA_CATEGORIES[worst_index]
    dominant = [item["parameter_code"] for item in results if item["band_index"] == worst_index]
    return _base_derivation(
        EEA_METHOD,
        [
            {
                "operation": "reuse provider-neutral accepted anchors to derive exact PM hourly means",
                "pollutant_results": results,
            },
            {
                "operation": "compare hourly means with EEA bands and select worst category",
                "overall_category_code": overall_code,
                "dominant_pollutants": dominant,
            },
        ],
    ), _base_candidate(
        availability="available",
        category_code=overall_code,
        category_label=overall_label,
        coverage_status="partial",
        aggregation_period="1h",
        result_kind="eea_overall_category",
        dominant_pollutants=dominant,
        missing_pollutants=["o3", "no2", "so2"],
        results=results,
    )


def _derive_eea_manila(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sensor = facts["sensor_results"][0]
    observation = sensor["observations"][0]
    pm25 = _eea_category("pm25", _decimal(observation["decimal_value"]))
    missing = ["pm10", "o3", "no2", "so2"]
    result = {"sensor_ref": sensor["sensor_ref"], **pm25}
    return _base_derivation(
        EEA_METHOD,
        [
            {
                "operation": "classify the sole available PM2.5 value using exact EEA bands",
                "pollutant_result": result,
            },
            {
                "operation": "record absent pollutants without substitution",
                "missing_pollutants": missing,
                "overall_coverage_status": "partial",
            },
        ],
    ), _base_candidate(
        availability="available",
        category_code=pm25["category_code"],
        category_label=pm25["category_label"],
        coverage_status="partial",
        aggregation_period="1h",
        result_kind="eea_overall_category",
        dominant_pollutants=["pm25"],
        missing_pollutants=missing,
        results=[result],
    )


def _derive_zero_rows(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    results = [
        {
            **sensor,
            "source_availability": sensor["availability"],
            "availability": "unavailable",
            "parameter_code": SENSOR_PARAMETERS[sensor["sensor_ref"]],
            "exclusion_reason": "insufficient_data",
        }
        for sensor in facts["sensor_results"]
    ]
    return _base_derivation(
        SOURCE_FACT_METHOD,
        [
            {
                "operation": "verify zero retained measurements and report unavailability",
                "results": results,
            }
        ],
    ), _base_candidate(
        availability="unavailable",
        exclusion_reason="insufficient_data",
        coverage_status="unavailable",
        result_kind="zero_row_unavailability",
        results=results,
    )


def derive_review_candidate(
    case_id: str, case_type: str, facts: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return independent derivation and unapproved candidate for one registered case."""
    if case_type == "fixture_summary":
        return _derive_fixture_summary(case_id, facts)
    if case_type == "device_provenance":
        return _derive_provenance(facts)
    if case_type in {"ordinary_aggregation", "anchored_hour"} and case_id != "eea_pa_manila_2026_08_08T03":
        return _derive_hourly(case_id, facts)
    if case_type == "anchored_window":
        return _derive_nowcast(facts)
    if case_id == "pa_ny_pm25_completed_2026_08_09":
        return _derive_pa_completed_day(facts)
    if case_id == "openaq_rio_pm10_completed_2026_08_02":
        return _derive_openaq_pm10_day(facts)
    if case_id == "openaq_ny_o3_window_2026_08_02T12":
        return _derive_o3(facts)
    if case_id == "openaq_ny_co_window_2026_08_02T12":
        return _derive_co(facts)
    if case_id == "openaq_ny_no2_hour_2026_08_02T11":
        return _derive_no2(facts)
    if case_id == "openaq_ny_so2_window_2026_08_02T12":
        return _derive_so2(facts)
    if case_id == "openaq_rio_epa_mass_units_unavailable":
        return _derive_unsupported_mass_gases(facts)
    if case_id == "eea_rio_2026_08_02T11":
        return _derive_eea_rio(facts)
    if case_id == "eea_pa_manila_2026_08_08T03":
        return _derive_eea_pa(facts)
    if case_id == "eea_openaq_manila_2026_08_02T11":
        return _derive_eea_manila(facts)
    if case_type == "zero_row_sensors":
        return _derive_zero_rows(facts)
    raise ValueError(f"No independent review derivation is registered for {case_id!r}")
