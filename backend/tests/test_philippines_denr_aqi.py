from decimal import Decimal
import math

import pytest

from services.air_quality_index.domain import ExclusionReason, ResultKind
from services.air_quality_index.philippines_denr import (
    AqiScaleStatus,
    CAUTIONARY_STATEMENTS_BY_POLLUTANT,
    CalculationStatus,
    CATEGORIES,
    COMPONENT_DEFINITIONS,
    PHILIPPINES_DENR_STANDARD,
    calculate_component_aqi,
    calculate_ozone_aqi,
)


def test_standard_metadata_identifies_the_national_calculation_basis():
    standard = PHILIPPINES_DENR_STANDARD
    assert standard.code == "philippines_denr"
    assert standard.display_name == "Philippines Air Quality Index"
    assert standard.methodology_version == "denr_emb_aqi_2021"
    assert standard.methodology_code == "philippines_denr_aqi"
    assert standard.result_kind is ResultKind.NUMERIC
    assert standard.is_default is False
    assert standard.default_product_code == "philippines_denr.pm25.completed_day"
    assert standard.pollutants == ("pm25", "pm10", "so2", "o3", "co", "no2")
    assert all(product.result_scope == "pollutant" for product in standard.products)
    assert all("overall" not in product.product_code for product in standard.products)


def test_category_metadata_uses_official_labels_colors_and_numeric_bounds():
    assert [
        (category.code, category.label, category.color, category.index_min, category.index_max)
        for category in CATEGORIES
    ] == [
        ("good", "Good", "#00E400", 0, 50),
        ("fair", "Fair", "#FFFF00", 51, 100),
        (
            "unhealthy_for_sensitive_groups",
            "Unhealthy for Sensitive Groups",
            "#FF7E00",
            101,
            150,
        ),
        ("very_unhealthy", "Very Unhealthy", "#FF0000", 151, 200),
        ("acutely_unhealthy", "Acutely Unhealthy", "#8F3F97", 201, 300),
        ("emergency", "Emergency", "#7E0023", 301, 500),
    ]


def test_cautionary_statements_are_stored_for_every_supported_pollutant_and_band():
    assert set(CAUTIONARY_STATEMENTS_BY_POLLUTANT) == set(
        PHILIPPINES_DENR_STANDARD.pollutants
    )
    expected_category_codes = {category.code for category in CATEGORIES}
    assert all(
        set(statements) == expected_category_codes
        for statements in CAUTIONARY_STATEMENTS_BY_POLLUTANT.values()
    )


@pytest.mark.parametrize(
    ("parameter", "component", "unit"),
    [
        ("pm25", "pm25_24_hour", "ug_m3"),
        ("pm10", "pm10_24_hour", "ug_m3"),
        ("so2", "so2_24_hour", "ppm"),
        ("o3", "o3_8_hour", "ppm"),
        ("o3", "o3_1_hour", "ppm"),
        ("co", "co_8_hour", "ppm"),
        ("no2", "no2_1_hour", "ppm"),
    ],
)
def test_every_published_numeric_boundary_is_inclusive(parameter, component, unit):
    definition = COMPONENT_DEFINITIONS[component]
    for breakpoint in definition.breakpoints:
        lower = calculate_component_aqi(parameter, component, breakpoint.concentration_low, unit)
        expected_status = (
            CalculationStatus.CATEGORY_ONLY
            if breakpoint.concentration_high is None
            else CalculationStatus.CALCULATED
        )
        assert lower.calculation_status is expected_status
        assert lower.category_code == breakpoint.category_code
        if breakpoint.concentration_high is not None:
            upper = calculate_component_aqi(parameter, component, breakpoint.concentration_high, unit)
            assert upper.calculation_status is CalculationStatus.CALCULATED
            assert upper.category_code == breakpoint.category_code


@pytest.mark.parametrize(
    ("parameter", "component", "unit", "step"),
    [
        ("pm25", "pm25_24_hour", "ug_m3", Decimal("0.1")),
        ("pm10", "pm10_24_hour", "ug_m3", Decimal("1")),
        ("so2", "so2_24_hour", "ppm", Decimal("0.001")),
        ("o3", "o3_8_hour", "ppm", Decimal("0.001")),
        ("o3", "o3_1_hour", "ppm", Decimal("0.001")),
        ("co", "co_8_hour", "ppm", Decimal("0.1")),
        ("no2", "no2_1_hour", "ppm", Decimal("0.01")),
    ],
)
def test_values_immediately_outside_each_published_band_do_not_stay_in_that_band(
    parameter,
    component,
    unit,
    step,
):
    for breakpoint in COMPONENT_DEFINITIONS[component].breakpoints:
        if breakpoint.concentration_low > 0:
            below = calculate_component_aqi(
                parameter,
                component,
                breakpoint.concentration_low - step,
                unit,
            )
            assert below.category_code != breakpoint.category_code
        if breakpoint.concentration_high is not None:
            above = calculate_component_aqi(
                parameter,
                component,
                breakpoint.concentration_high + step,
                unit,
            )
            if above.category_code == breakpoint.category_code:
                assert breakpoint is COMPONENT_DEFINITIONS[component].breakpoints[-1]
                assert above.calculation_status is CalculationStatus.CATEGORY_ONLY


@pytest.mark.parametrize(
    ("parameter", "component", "unit", "zero_reason"),
    [
        ("pm25", "pm25_24_hour", "ug_m3", None),
        ("pm10", "pm10_24_hour", "ug_m3", None),
        ("so2", "so2_24_hour", "ppm", None),
        ("o3", "o3_8_hour", "ppm", None),
        ("o3", "o3_1_hour", "ppm", ExclusionReason.PUBLISHED_BREAKPOINT_GAP),
        ("co", "co_8_hour", "ppm", None),
        (
            "no2",
            "no2_1_hour",
            "ppm",
            ExclusionReason.SUBINDEX_NOT_DEFINED_FOR_CONCENTRATION,
        ),
    ],
)
def test_every_component_handles_zero_invalid_and_unsupported_unit_explicitly(
    parameter,
    component,
    unit,
    zero_reason,
):
    zero = calculate_component_aqi(parameter, component, 0, unit)
    assert zero.exclusion_reason is zero_reason
    assert calculate_component_aqi(
        parameter, component, -1, unit
    ).exclusion_reason is ExclusionReason.INVALID_CONCENTRATION
    assert calculate_component_aqi(
        parameter, component, math.nan, unit
    ).exclusion_reason is ExclusionReason.INVALID_CONCENTRATION
    assert calculate_component_aqi(
        parameter, component, 0, "unsupported_unit"
    ).exclusion_reason is ExclusionReason.UNSUPPORTED_UNIT


@pytest.mark.parametrize(
    ("parameter", "component", "concentration", "unit"),
    [
        ("pm25", "pm25_24_hour", -0.1, "ug_m3"),
        ("pm10", "pm10_24_hour", math.nan, "ug_m3"),
        ("so2", "so2_24_hour", math.inf, "ppm"),
        ("o3", "o3_8_hour", "malformed", "ppm"),
        ("co", "co_8_hour", True, "ppm"),
    ],
)
def test_invalid_concentrations_are_explicit(parameter, component, concentration, unit):
    result = calculate_component_aqi(parameter, component, concentration, unit)
    assert result.calculation_status is CalculationStatus.UNAVAILABLE
    assert result.exclusion_reason is ExclusionReason.INVALID_CONCENTRATION


def test_unsupported_pollutant_is_explicit():
    result = calculate_component_aqi("tsp", "pm10_24_hour", 50, "ug_m3")
    assert result.calculation_status is CalculationStatus.UNAVAILABLE
    assert result.exclusion_reason is ExclusionReason.UNSUPPORTED_POLLUTANT


def test_particulate_units_convert_exactly_and_normal_condition_units_do_not_alias():
    converted = calculate_component_aqi("pm25", "pm25_24_hour", "0.025", "mg_m3")
    assert converted.normalized_concentration == Decimal("25.000")
    assert converted.normalized_unit == "µg/m³"
    unsupported = calculate_component_aqi("pm25", "pm25_24_hour", 25, "ug_ncm")
    assert unsupported.exclusion_reason is ExclusionReason.CONVERSION_NOT_SUPPORTED


@pytest.mark.parametrize("parameter,component", [("so2", "so2_24_hour"), ("o3", "o3_8_hour"), ("co", "co_8_hour"), ("no2", "no2_1_hour")])
def test_gas_units_convert_ppb_exactly_and_reject_mass_units(parameter, component):
    ppm = calculate_component_aqi(parameter, component, 125, "ppb")
    assert ppm.normalized_concentration == Decimal("0.125")
    mass = calculate_component_aqi(parameter, component, 125, "ug_m3")
    assert mass.exclusion_reason is ExclusionReason.CONVERSION_NOT_SUPPORTED


def test_pm_preprocessing_occurs_before_breakpoint_selection():
    pm25 = calculate_component_aqi("pm25", "pm25_24_hour", Decimal("25.099"), "ug_m3")
    assert pm25.preprocessed_concentration == Decimal("25.0")
    assert pm25.category_code == "good"
    pm10 = calculate_component_aqi("pm10", "pm10_24_hour", Decimal("54.999"), "ug_m3")
    assert pm10.preprocessed_concentration == Decimal("54")
    assert pm10.category_code == "good"


@pytest.mark.parametrize(
    ("parameter", "component", "concentration"),
    [
        ("pm25", "pm25_24_hour", Decimal("90.9")),
        ("so2", "so2_24_hour", Decimal("0.0345")),
        ("o3", "o3_8_hour", Decimal("0.0645")),
        ("co", "co_8_hour", Decimal("4.45")),
    ],
)
def test_nominal_published_gaps_are_unavailable(parameter, component, concentration):
    unit = "ug_m3" if parameter.startswith("pm") else "ppm"
    result = calculate_component_aqi(parameter, component, concentration, unit)
    assert result.calculation_status is CalculationStatus.UNAVAILABLE
    assert result.exclusion_reason is ExclusionReason.PUBLISHED_BREAKPOINT_GAP


@pytest.mark.parametrize(
    ("parameter", "component", "concentration", "unit"),
    [
        ("pm25", "pm25_24_hour", 91, "ug_m3"),
        ("pm10", "pm10_24_hour", 505, "ug_m3"),
        ("so2", "so2_24_hour", Decimal("0.805"), "ppm"),
        ("co", "co_8_hour", Decimal("40.5"), "ppm"),
        ("no2", "no2_1_hour", Decimal("1.65"), "ppm"),
        ("o3", "o3_1_hour", Decimal("0.505"), "ppm"),
    ],
)
def test_open_ended_emergency_is_category_only(parameter, component, concentration, unit):
    result = calculate_component_aqi(parameter, component, concentration, unit)
    assert result.is_eligible
    assert result.calculation_status is CalculationStatus.CATEGORY_ONLY
    assert result.numeric_value is None
    assert result.category_code == "emergency"
    assert result.aqi_scale_status is AqiScaleStatus.ABOVE_PUBLISHED_NUMERIC_RANGE


def test_no2_has_no_subindex_below_its_first_published_band():
    result = calculate_component_aqi("no2", "no2_1_hour", Decimal("0.649"), "ppm")
    assert result.calculation_status is CalculationStatus.UNAVAILABLE
    assert result.exclusion_reason is ExclusionReason.SUBINDEX_NOT_DEFINED_FOR_CONCENTRATION


def test_high_eight_hour_ozone_requires_the_corresponding_one_hour_candidate():
    missing = calculate_ozone_aqi(Decimal("0.375"), "ppm")
    assert missing.exclusion_reason is ExclusionReason.NO_APPLICABLE_OZONE_CANDIDATE
    selected = calculate_ozone_aqi(
        Decimal("0.375"),
        "ppm",
        corresponding_one_hour_concentration=Decimal("0.405"),
    )
    assert selected.calculation_status is CalculationStatus.CALCULATED
    assert selected.component_code == "o3_1_hour"
    assert selected.category_code == "emergency"
    assert selected.numeric_value == Decimal("301.00")


def test_interpolation_preserves_two_decimal_places_with_half_up_rounding():
    # EMB MC 2021-07, sample problems 2 and 3.
    pm10 = calculate_component_aqi("pm10", "pm10_24_hour", 210, "ug_m3")
    assert pm10.numeric_value == Decimal("128.22")
    ozone = calculate_component_aqi("o3", "o3_8_hour", Decimal("0.14"), "ppm")
    assert ozone.numeric_value == Decimal("206.96")
    half_cent = calculate_component_aqi(
        "co", "co_8_hour", Decimal("0.00132"), "ppm"
    )
    assert half_cent.numeric_value == Decimal("0.02")
