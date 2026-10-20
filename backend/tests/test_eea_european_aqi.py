from __future__ import annotations

from dataclasses import asdict, replace
from decimal import Decimal
import math

import pytest

from services.air_quality_index import (
    CoverageState,
    DisplayQualification,
    EEA_EUROPEAN_STANDARD,
    EligibilityStatus,
    ExclusionReason,
    ResultKind,
    classify_hourly_concentration,
    combine_pollutant_results,
)
from services.air_quality_index.eea_european import (
    CATEGORIES,
    CONCENTRATION_UPPER_BOUNDS,
    DISPLAY_NAME,
    METHODOLOGY_VERSION,
    NORMALIZED_UNIT,
    POLLUTANTS,
    EEA_EUROPEAN_PRODUCTS,
    STANDARD_CODE,
)


EXPECTED_BOUNDS = {
    "pm25": (5.0, 15.0, 50.0, 90.0, 140.0),
    "pm10": (15.0, 45.0, 120.0, 195.0, 270.0),
    "o3": (60.0, 100.0, 120.0, 160.0, 180.0),
    "no2": (10.0, 25.0, 60.0, 100.0, 150.0),
    "so2": (20.0, 40.0, 125.0, 190.0, 275.0),
}


def _eligible(pollutant: str, concentration: float):
    result = classify_hourly_concentration(pollutant, concentration, "ug_m3")
    assert result.eligibility_status is EligibilityStatus.ELIGIBLE
    return result


def test_standard_metadata_is_stable_and_categorical():
    assert EEA_EUROPEAN_STANDARD.code == STANDARD_CODE == "eea_european"
    assert EEA_EUROPEAN_STANDARD.display_name == DISPLAY_NAME == "European Air Quality Index"
    assert EEA_EUROPEAN_STANDARD.methodology_version == METHODOLOGY_VERSION == "eea_2024_bands"
    assert EEA_EUROPEAN_STANDARD.result_kind is ResultKind.CATEGORICAL
    assert EEA_EUROPEAN_STANDARD.averaging_minutes == 60
    assert EEA_EUROPEAN_STANDARD.pollutants == POLLUTANTS
    assert CONCENTRATION_UPPER_BOUNDS == EXPECTED_BOUNDS
    assert [category.internal_severity_rank for category in CATEGORIES] == [1, 2, 3, 4, 5, 6]
    assert [category.color for category in CATEGORIES] == [
        "#50F0E6",
        "#50CCAA",
        "#F0E641",
        "#FF5050",
        "#960032",
        "#7D2181",
    ]
    assert EEA_EUROPEAN_STANDARD.default_product_code == "eea_european.overall.hourly"
    assert EEA_EUROPEAN_STANDARD.products == EEA_EUROPEAN_PRODUCTS


def test_european_products_include_overall_and_every_supported_pollutant():
    assert EEA_EUROPEAN_PRODUCTS[0].result_scope == "overall"
    pollutant_products = EEA_EUROPEAN_PRODUCTS[1:]
    assert tuple(product.parameter_code for product in pollutant_products) == POLLUTANTS
    assert all(product.calculation_code == "hourly_category" for product in pollutant_products)
    assert all(product.aggregation_period == "1h" for product in EEA_EUROPEAN_PRODUCTS)


@pytest.mark.parametrize("pollutant", POLLUTANTS)
def test_zero_is_good_for_every_pollutant(pollutant: str):
    result = _eligible(pollutant, 0.0)
    assert result.category_code == "good"
    assert result.category_label == "Good"
    assert result.internal_severity_rank == 1


@pytest.mark.parametrize(
    ("pollutant", "boundary", "category_index"),
    [
        (pollutant, boundary, category_index)
        for pollutant, bounds in EXPECTED_BOUNDS.items()
        for category_index, boundary in enumerate(bounds)
    ],
)
def test_every_published_boundary_is_inclusive(
    pollutant: str, boundary: float, category_index: int
):
    result = _eligible(pollutant, boundary)
    expected = CATEGORIES[category_index]
    assert result.normalized_concentration == boundary
    assert result.normalized_unit == NORMALIZED_UNIT
    assert result.category_code == expected.code
    assert result.category_label == expected.label
    assert result.internal_severity_rank == expected.internal_severity_rank
    assert result.numeric_value is None


@pytest.mark.parametrize(
    ("pollutant", "boundary", "category_index"),
    [
        (pollutant, boundary, category_index + 1)
        for pollutant, bounds in EXPECTED_BOUNDS.items()
        for category_index, boundary in enumerate(bounds)
    ],
)
def test_value_immediately_above_every_boundary_enters_next_category(
    pollutant: str, boundary: float, category_index: int
):
    concentration = math.nextafter(boundary, math.inf)
    result = _eligible(pollutant, concentration)
    expected = CATEGORIES[category_index]
    assert result.normalized_concentration == concentration
    assert result.category_code == expected.code
    assert result.internal_severity_rank == expected.internal_severity_rank


@pytest.mark.parametrize(
    ("concentration", "category_code"),
    [
        (5.0, "good"),
        (5.0001, "fair"),
        (14.9999, "fair"),
        (15.0, "fair"),
        (15.0001, "moderate"),
        (49.125, "moderate"),
        (140.0, "very_poor"),
        (140.0001, "extremely_poor"),
    ],
)
def test_pm25_decimal_examples_are_not_rounded(
    concentration: float, category_code: str
):
    result = _eligible("PM2.5", concentration)
    assert result.parameter_code == "pm25"
    assert result.category_code == category_code


def test_decimal_numeric_input_is_supported_without_integer_rounding():
    result = classify_hourly_concentration("pm25", Decimal("5.0001"), "ug_m3")
    assert result.is_eligible
    assert result.normalized_concentration == 5.0001
    assert result.category_code == "fair"


@pytest.mark.parametrize(
    ("pollutant", "concentration", "expected_category"),
    [
        (pollutant, boundary - 0.0001, CATEGORIES[index].code)
        for pollutant, bounds in EXPECTED_BOUNDS.items()
        for index, boundary in enumerate(bounds)
    ],
)
def test_decimal_concentration_is_compared_without_generic_rule_preprocessing(
    pollutant: str, concentration: float, expected_category: str
):
    result = _eligible(pollutant, concentration)
    assert result.preprocessed_concentration == result.normalized_concentration
    assert result.category_code == expected_category


@pytest.mark.parametrize("unit", ["mg/m³", "mg_m3", "mg/m^3", "mg/m3"])
def test_milligrams_are_converted_exactly_to_micrograms(unit: str):
    result = classify_hourly_concentration("pm25", 0.005, unit)
    assert result.is_eligible
    assert result.normalized_concentration == 5.0
    assert result.normalized_unit == NORMALIZED_UNIT
    assert result.category_code == "good"


@pytest.mark.parametrize("unit", ["µg/m³", "μg/m³", "ug_m3", "ug/m3", "ug/m^3"])
def test_repository_and_symbol_microgram_spellings_are_accepted(unit: str):
    result = classify_hourly_concentration("o3", 60.25, unit)
    assert result.is_eligible
    assert result.normalized_concentration == 60.25
    assert result.normalized_unit == NORMALIZED_UNIT
    assert result.category_code == "fair"


@pytest.mark.parametrize("unit", ["ppm", "ppb", "percent", "AQI", "", None, "mystery"])
def test_unsupported_units_are_explicitly_rejected(unit: object):
    result = classify_hourly_concentration("no2", 10.0, unit)
    assert not result.is_eligible
    assert result.exclusion_reason is ExclusionReason.UNSUPPORTED_UNIT
    assert result.normalized_concentration is None
    assert result.normalized_unit is None
    assert result.category_code is None
    assert result.numeric_value is None


@pytest.mark.parametrize("concentration", [-0.0001, math.nan, math.inf, -math.inf, "5", None, True])
def test_invalid_concentrations_are_rejected_without_clamping(concentration: object):
    result = classify_hourly_concentration("pm10", concentration, "µg/m³")
    assert not result.is_eligible
    assert result.exclusion_reason is ExclusionReason.INVALID_CONCENTRATION
    assert result.category_code is None
    assert result.internal_severity_rank is None
    assert result.numeric_value is None


@pytest.mark.parametrize("pollutant", ["co", "nox", "pm1", "", None, "unknown"])
def test_unsupported_pollutants_are_explicitly_rejected(pollutant: object):
    result = classify_hourly_concentration(pollutant, 1.0, "µg/m³")
    assert not result.is_eligible
    assert result.exclusion_reason is ExclusionReason.UNSUPPORTED_POLLUTANT
    assert result.category_code is None


def test_combination_selects_worst_available_category():
    result = combine_pollutant_results(
        [
            _eligible("pm25", 4.0),
            _eligible("pm10", 44.0),
            _eligible("o3", 121.0),
            _eligible("no2", 55.0),
            _eligible("so2", 30.0),
        ]
    )
    assert result.category_code == "poor"
    assert result.category_label == "Poor"
    assert result.internal_severity_rank == 4
    assert result.dominant_pollutants == ("o3",)
    assert result.eligibility_status is EligibilityStatus.ELIGIBLE
    assert result.exclusion_reasons == ()
    assert result.numeric_value is None
    assert result.coverage.coverage_status is CoverageState.COMPLETE


def test_tied_dominant_pollutants_are_retained_in_canonical_order():
    # Deliberately supply results in a different order from the canonical order.
    result = combine_pollutant_results(
        [
            _eligible("so2", 126.0),
            _eligible("no2", 61.0),
            _eligible("o3", 121.0),
            _eligible("pm10", 121.0),
            _eligible("pm25", 51.0),
        ]
    )
    assert result.category_code == "poor"
    assert result.dominant_pollutants == POLLUTANTS
    assert tuple(item.parameter_code for item in result.pollutant_results) == POLLUTANTS


def test_partial_coverage_distinguishes_missing_and_ineligible_pollutants():
    result = combine_pollutant_results(
        [
            _eligible("pm25", 7.0),
            classify_hourly_concentration("o3", 70.0, "ppm"),
            _eligible("so2", 300.0),
        ]
    )
    assert result.coverage.coverage_status is CoverageState.PARTIAL
    assert result.coverage.available_pollutants == ("pm25", "so2")
    assert result.coverage.missing_pollutants == ("pm10", "no2")
    assert result.coverage.ineligible_pollutants == ("o3",)
    assert result.coverage.missing_or_ineligible_pollutants == ("pm10", "o3", "no2")
    assert result.coverage.display_qualification is DisplayQualification.NOT_EVALUATED
    assert result.category_code == "extremely_poor"
    assert result.dominant_pollutants == ("so2",)
    assert result.eligibility_status is EligibilityStatus.ELIGIBLE
    assert result.exclusion_reasons == (ExclusionReason.UNSUPPORTED_UNIT,)
    assert result.numeric_value is None


def test_no_eligible_pollutants_has_no_overall_category():
    result = combine_pollutant_results(
        [
            classify_hourly_concentration("pm25", -1.0, "µg/m³"),
            classify_hourly_concentration("o3", 0.05, "ppm"),
        ]
    )
    assert result.coverage.coverage_status is CoverageState.NONE
    assert result.coverage.available_pollutants == ()
    assert result.coverage.missing_pollutants == ("pm10", "no2", "so2")
    assert result.coverage.ineligible_pollutants == ("pm25", "o3")
    assert result.category_code is None
    assert result.category_label is None
    assert result.internal_severity_rank is None
    assert result.dominant_pollutants == ()
    assert result.numeric_value is None
    assert result.eligibility_status is EligibilityStatus.INELIGIBLE
    assert result.exclusion_reasons == (
        ExclusionReason.INVALID_CONCENTRATION,
        ExclusionReason.UNSUPPORTED_UNIT,
        ExclusionReason.NO_ELIGIBLE_POLLUTANTS,
    )


def test_empty_input_has_none_coverage_and_all_pollutants_missing():
    result = combine_pollutant_results([])
    assert result.coverage.coverage_status is CoverageState.NONE
    assert result.coverage.missing_pollutants == POLLUTANTS
    assert result.coverage.missing_or_ineligible_pollutants == POLLUTANTS
    assert result.pollutant_results == ()
    assert result.numeric_value is None
    assert result.eligibility_status is EligibilityStatus.INELIGIBLE
    assert result.exclusion_reasons == (ExclusionReason.NO_ELIGIBLE_POLLUTANTS,)


def test_internal_rank_is_separate_from_the_official_displayed_category():
    pollutant_result = _eligible("pm25", 55.0)
    overall_result = combine_pollutant_results([pollutant_result])

    assert pollutant_result.category_label == "Poor"
    assert pollutant_result.internal_severity_rank == 4
    assert pollutant_result.numeric_value is None
    assert overall_result.category_label == "Poor"
    assert overall_result.internal_severity_rank == 4
    assert overall_result.numeric_value is None

    serialized = asdict(overall_result)
    assert serialized["category_label"] == "Poor"
    assert serialized["numeric_value"] is None
    assert "value" not in serialized


def test_combination_rejects_results_from_another_methodology():
    other = replace(_eligible("pm25", 5.0), methodology_version="different")
    with pytest.raises(ValueError, match="another AQI standard"):
        combine_pollutant_results([other])


def test_combination_rejects_duplicate_pollutant_results():
    with pytest.raises(ValueError, match="Duplicate pollutant"):
        combine_pollutant_results([_eligible("pm25", 5.0), _eligible("pm25", 6.0)])
