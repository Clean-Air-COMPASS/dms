from __future__ import annotations

"""Independent U.S. EPA AQI conformance vectors.

Expected values are literal review fixtures. They are not generated from
production breakpoint tables.

Sources:
* 40 CFR Part 58, Appendix G, section 3.4 and Table 2.
* EPA-454/B-24-002, May 2024, section IV and Table 6.
* 89 FR 16202, March 6, 2024, section IV.B.3; revised PM2.5
  breakpoints effective May 6, 2024.
Concentration units are µg/m³ for PM, ppm for ozone and CO, and ppb for
SO2 and NO2.
"""

from decimal import Decimal

import pytest

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.us_epa import (
    AqiScaleStatus,
    CalculationStatus,
    CoverageStatus,
    DEFAULT_PRODUCT_CODE,
    METHODOLOGY_REVISION,
    PM25_BREAKPOINT_EFFECTIVE_DATE,
    US_EPA_PRODUCTS,
    calculate_component_aqi,
    calculate_pm_nowcast,
    normalize_concentration_unit,
    round_aqi_to_nearest_integer,
)


PM25_LITERAL_VECTORS = (
    (0.0, 0),
    (9.0, 50),
    (9.1, 51),
    (12.0, 56),
    (35.4, 100),
    (35.5, 101),
    (55.4, 150),
    (55.5, 151),
    (125.4, 200),
    (125.5, 201),
    (225.4, 300),
    (225.5, 301),
    (325.4, 500),
)


@pytest.mark.parametrize(("concentration", "expected_aqi"), PM25_LITERAL_VECTORS)
def test_pm25_2024_breakpoint_vectors(
    concentration: float,
    expected_aqi: int,
) -> None:
    result = calculate_component_aqi(
        "pm25",
        "pm25_24_hour",
        concentration,
        "ug_m3",
    )
    assert result.numeric_value == expected_aqi


def test_pm25_obsolete_twelve_microgram_good_boundary_is_rejected() -> None:
    result = calculate_component_aqi(
        "pm25",
        "pm25_24_hour",
        12.0,
        "ug_m3",
    )
    assert result.numeric_value == 56
    assert result.numeric_value != 50


@pytest.mark.parametrize(
    ("concentration", "expected_aqi"),
    (
        (9.099, 50),
        (9.100, 51),
        (35.499, 100),
        (35.500, 101),
        (55.499, 150),
        (55.500, 151),
        (125.499, 200),
        (125.500, 201),
        (225.499, 300),
        (225.500, 301),
        (325.499, 500),
    ),
)
def test_pm25_values_immediately_around_boundaries(
    concentration: float,
    expected_aqi: int,
) -> None:
    result = calculate_component_aqi(
        "pm25",
        "pm25_24_hour",
        concentration,
        "ug_m3",
    )
    assert result.numeric_value == expected_aqi


@pytest.mark.parametrize(
    ("parameter_code", "component_code", "unit", "vectors"),
    (
        (
            "pm10",
            "pm10_24_hour",
            "ug_m3",
            (
                (0, 0), (54, 50), (55, 51), (154, 100),
                (155, 101), (254, 150), (255, 151), (354, 200),
                (355, 201), (424, 300), (425, 301), (604, 500),
            ),
        ),
        (
            "o3",
            "o3_8_hour",
            "ppm",
            (
                (0.000, 0), (0.054, 50), (0.055, 51), (0.070, 100),
                (0.071, 101), (0.085, 150), (0.086, 151),
                (0.105, 200), (0.106, 201), (0.200, 300),
            ),
        ),
        (
            "o3",
            "o3_1_hour",
            "ppm",
            (
                (0.125, 101), (0.164, 150), (0.165, 151),
                (0.204, 200), (0.205, 201), (0.404, 300),
                (0.405, 301), (0.604, 500),
            ),
        ),
        (
            "co",
            "co_8_hour",
            "ppm",
            (
                (0.0, 0), (4.4, 50), (4.5, 51), (9.4, 100),
                (9.5, 101), (12.4, 150), (12.5, 151), (15.4, 200),
                (15.5, 201), (30.4, 300), (30.5, 301), (50.4, 500),
            ),
        ),
        (
            "so2",
            "so2_1_hour_low",
            "ppb",
            (
                (0, 0), (35, 50), (36, 51), (75, 100),
                (76, 101), (185, 150), (186, 151), (304, 200),
            ),
        ),
        (
            "no2",
            "no2_1_hour",
            "ppb",
            (
                (0, 0), (53, 50), (54, 51), (100, 100),
                (101, 101), (360, 150), (361, 151), (649, 200),
                (650, 201), (1249, 300), (1250, 301), (2049, 500),
            ),
        ),
        (
            "so2",
            "so2_24_hour_high",
            "ppb",
            (
                (305, 201),
                (604.999, 300),
                (605, 301),
                (1004.999, 500),
            ),
        ),
    ),
)
def test_every_retained_component_has_literal_exact_endpoints(
    parameter_code: str,
    component_code: str,
    unit: str,
    vectors: tuple[tuple[float, int], ...],
) -> None:
    for concentration, expected_aqi in vectors:
        result = calculate_component_aqi(
            parameter_code,
            component_code,
            concentration,
            unit,
        )
        assert result.numeric_value == expected_aqi


@pytest.mark.parametrize(
    ("parameter_code", "component_code", "unit", "vectors"),
    (
        (
            "pm10",
            "pm10_24_hour",
            "ug_m3",
            (
                (54.999, 50),
                (55, 51),
                (154.999, 100),
                (155, 101),
                (254.999, 150),
                (255, 151),
                (354.999, 200),
                (355, 201),
                (424.999, 300),
                (425, 301),
                (604.999, 500),
            ),
        ),
        (
            "o3",
            "o3_8_hour",
            "ppm",
            (
                (0.054999, 50),
                (0.055, 51),
                (0.070999, 100),
                (0.071, 101),
                (0.085999, 150),
                (0.086, 151),
                (0.105999, 200),
                (0.106, 201),
                (0.200999, 300),
            ),
        ),
        (
            "o3",
            "o3_1_hour",
            "ppm",
            (
                (0.125, 101),
                (0.164999, 150),
                (0.165, 151),
                (0.204999, 200),
                (0.205, 201),
                (0.404999, 300),
                (0.405, 301),
                (0.604999, 500),
            ),
        ),
        (
            "co",
            "co_8_hour",
            "ppm",
            (
                (4.499, 50),
                (4.5, 51),
                (9.499, 100),
                (9.5, 101),
                (12.499, 150),
                (12.5, 151),
                (15.499, 200),
                (15.5, 201),
                (30.499, 300),
                (30.5, 301),
                (50.499, 500),
            ),
        ),
        (
            "so2",
            "so2_1_hour_low",
            "ppb",
            (
                (35.999, 50),
                (36, 51),
                (75.999, 100),
                (76, 101),
                (185.999, 150),
                (186, 151),
                (304.999, 200),
            ),
        ),
        (
            "no2",
            "no2_1_hour",
            "ppb",
            (
                (53.999, 50),
                (54, 51),
                (100.999, 100),
                (101, 101),
                (360.999, 150),
                (361, 151),
                (649.999, 200),
                (650, 201),
                (1249.999, 300),
                (1250, 301),
                (2049.999, 500),
            ),
        ),
    ),
)
def test_other_epa_component_boundaries_and_truncation(
    parameter_code: str,
    component_code: str,
    unit: str,
    vectors: tuple[tuple[float, int], ...],
) -> None:
    for concentration, expected_aqi in vectors:
        result = calculate_component_aqi(
            parameter_code,
            component_code,
            concentration,
            unit,
        )
        assert result.numeric_value == expected_aqi


def test_corrected_epa_ozone_example_uses_point_zero_seven_eight_ppm() -> None:
    # EPA-454/B-24-002, section IV worked example. RFC 26004 identifies the
    # printed 0.78 term as a typo; 0.078 ppm retains the published AQI 126.
    result = calculate_component_aqi(
        "o3",
        "o3_8_hour",
        0.07853333,
        "ppm",
    )
    assert result.preprocessed_concentration == 0.078
    assert result.numeric_value == 126


def test_ozone_blank_table_regions_are_not_interpolated() -> None:
    low_one_hour = calculate_component_aqi(
        "o3",
        "o3_1_hour",
        0.104,
        "ppm",
    )
    high_eight_hour = calculate_component_aqi(
        "o3",
        "o3_8_hour",
        0.201,
        "ppm",
    )
    assert low_one_hour.calculation_status is CalculationStatus.UNAVAILABLE
    assert high_eight_hour.calculation_status is CalculationStatus.UNAVAILABLE


def test_so2_high_range_is_not_applicable_to_the_one_hour_low_table() -> None:
    result = calculate_component_aqi(
        "so2",
        "so2_1_hour_low",
        305,
        "ppb",
    )
    assert result.calculation_status is CalculationStatus.UNAVAILABLE
    assert (
        result.exclusion_reason
        is ExclusionReason.SO2_1_HOUR_NOT_APPLICABLE
    )


def test_epa_half_up_aqi_rounding_is_explicit() -> None:
    assert round_aqi_to_nearest_integer(Decimal("125.4999")) == 125
    assert round_aqi_to_nearest_integer(Decimal("125.5")) == 126
    assert round_aqi_to_nearest_integer(Decimal("125.5001")) == 126


@pytest.mark.parametrize(
    "invalid_concentration",
    (-1.0, float("nan"), float("inf"), float("-inf")),
)
def test_invalid_concentrations_are_explicitly_unavailable(
    invalid_concentration: float,
) -> None:
    result = calculate_component_aqi(
        "pm25",
        "pm25_24_hour",
        invalid_concentration,
        "ug_m3",
    )
    assert result.calculation_status is CalculationStatus.UNAVAILABLE
    assert result.exclusion_reason is ExclusionReason.INVALID_CONCENTRATION


def test_exact_supported_unit_conversions() -> None:
    pm = normalize_concentration_unit("pm25", 0.012, "mg_m3")
    ozone = normalize_concentration_unit("o3", 78, "ppb")
    no2 = normalize_concentration_unit("no2", 0.053, "ppm")
    assert pm.normalized_concentration == Decimal("12.000")
    assert ozone.normalized_concentration == Decimal("0.078")
    assert no2.normalized_concentration == Decimal("53.000")


def test_unknown_and_gas_mass_units_are_not_silently_accepted() -> None:
    unknown = normalize_concentration_unit("pm25", 12, "mystery")
    gas_mass = normalize_concentration_unit("o3", 120, "ug_m3")
    assert unknown.exclusion_reason is ExclusionReason.UNSUPPORTED_UNIT
    assert (
        gas_mass.exclusion_reason
        is ExclusionReason.CONVERSION_NOT_SUPPORTED
    )


def test_above_500_uses_upper_hazardous_slope_without_new_category() -> None:
    result = calculate_component_aqi(
        "pm25",
        "pm25_24_hour",
        400.0,
        "ug_m3",
    )
    assert result.numeric_value == 649
    assert result.category_code == "hazardous"
    assert result.aqi_scale_status is AqiScaleStatus.ABOVE_500


@pytest.mark.parametrize(
    ("parameter_code", "component_code", "concentration", "unit", "expected"),
    (
        ("pm10", "pm10_24_hour", 700, "ug_m3", 607),
        ("o3", "o3_1_hour", 0.700, "ppm", 596),
        ("co", "co_8_hour", 60.0, "ppm", 596),
        ("no2", "no2_1_hour", 2500, "ppb", 612),
        ("so2", "so2_24_hour_high", 1200, "ppb", 598),
    ),
)
def test_other_defined_upper_intervals_extrapolate_above_500(
    parameter_code: str,
    component_code: str,
    concentration: float,
    unit: str,
    expected: int,
) -> None:
    result = calculate_component_aqi(
        parameter_code,
        component_code,
        concentration,
        unit,
    )
    assert result.numeric_value == expected
    assert result.category_code == "hazardous"
    assert result.aqi_scale_status is AqiScaleStatus.ABOVE_500


def test_product_catalog_keeps_nowcast_and_completed_day_products_distinct() -> None:
    assert DEFAULT_PRODUCT_CODE == "us_epa.pm25.nowcast"
    assert METHODOLOGY_REVISION == "2024-05"
    assert PM25_BREAKPOINT_EFFECTIVE_DATE == "2024-05-06"
    assert [product.product_code for product in US_EPA_PRODUCTS] == [
        "us_epa.pm25.nowcast",
        "us_epa.pm10.nowcast",
        "us_epa.o3.latest",
        "us_epa.co.latest",
        "us_epa.no2.latest",
        "us_epa.so2.latest",
        "us_epa.pm25.completed_day",
        "us_epa.pm10.completed_day",
    ]
    assert [product.is_parameter_default for product in US_EPA_PRODUCTS] == [
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
    ]
    completed_day_products = [
        product for product in US_EPA_PRODUCTS
        if product.product_kind == "completed_day"
    ]
    assert {product.aggregation_display_name for product in completed_day_products} == {
        "Completed Day"
    }
    assert all("NowCast" not in product.display_name for product in completed_day_products)
    ozone_product = next(
        product for product in US_EPA_PRODUCTS
        if product.product_code == "us_epa.o3.latest"
    )
    assert ozone_product.product_kind == "latest_window"
    assert ozone_product.methodology_revision == "2015-12"
    assert any(
        "precautionary CompassAQ informational policy" in limitation
        for limitation in ozone_product.limitations
    )
    assert any(
        "never by AQI magnitude" in limitation
        for limitation in ozone_product.limitations
    )
    carbon_monoxide_product = next(
        product for product in US_EPA_PRODUCTS
        if product.product_code == "us_epa.co.latest"
    )
    assert carbon_monoxide_product.calculation_code == (
        "co_latest_completed_8_hour_window"
    )
    assert carbon_monoxide_product.aggregation_period == (
        "latest_completed_8_hour_window"
    )
    assert carbon_monoxide_product.methodology_revision == "1999-08"
    assert carbon_monoxide_product.methodology_effective_date == "1999-10-04"
    nitrogen_dioxide_product = next(
        product for product in US_EPA_PRODUCTS
        if product.product_code == "us_epa.no2.latest"
    )
    assert nitrogen_dioxide_product.calculation_code == "no2_latest_completed_hour"
    assert nitrogen_dioxide_product.aggregation_period == "latest_completed_hour"
    assert nitrogen_dioxide_product.methodology_revision == "2010-02"
    assert nitrogen_dioxide_product.methodology_effective_date == "2010-04-12"
    sulfur_dioxide_product = next(
        product for product in US_EPA_PRODUCTS
        if product.product_code == "us_epa.so2.latest"
    )
    assert sulfur_dioxide_product.calculation_code == (
        "so2_latest_completed_24_hour_window"
    )
    assert sulfur_dioxide_product.methodology_revision == "2010-06"
    assert sulfur_dioxide_product.methodology_effective_date == "2010-08-23"


def test_pm25_nowcast_complete_sequence_uses_literal_epa_formula_result() -> None:
    result = calculate_pm_nowcast(
        "pm25",
        (35, 30, 25, 20, 15, 10, 10, 10, 10, 10, 10, 10),
        "ug_m3",
    )
    assert result.coverage_status is CoverageStatus.COMPLETE
    assert result.nowcast_weight_factor == 0.5
    assert result.normalized_concentration == pytest.approx(
        30.16117216117216
    )


def test_pm10_nowcast_uses_pm10_breakpoints() -> None:
    result = calculate_pm_nowcast(
        "pm10",
        (100,) * 12,
        "ug_m3",
    )
    assert result.numeric_value == 73


def test_nowcast_missing_slots_keep_actual_hours_ago_exponents() -> None:
    result = calculate_pm_nowcast(
        "pm25",
        (10, None, 20, None, None, None, 30, None, None, None, None, None),
        "ug_m3",
    )
    assert result.valid_observation_count == 3
    assert result.normalized_concentration == pytest.approx(
        12.22222222222222
    )


def test_nowcast_requires_two_valid_values_in_latest_three_slots() -> None:
    result = calculate_pm_nowcast(
        "pm25",
        (10, None, None, 20, 30, 40),
        "ug_m3",
    )
    assert result.calculation_status is CalculationStatus.UNAVAILABLE
    assert (
        result.exclusion_reason
        is ExclusionReason.INSUFFICIENT_RECENT_HOURS
    )


def test_nowcast_all_zero_values_are_valid() -> None:
    result = calculate_pm_nowcast("pm25", (0,) * 12, "ug_m3")
    assert result.nowcast_weight_factor == 1.0
    assert result.numeric_value == 0


def test_nowcast_weight_uses_ratio_when_ratio_exceeds_minimum() -> None:
    result = calculate_pm_nowcast(
        "pm25",
        (10, 8, 10, 8, 10, 8, 10, 8, 10, 8, 10, 8),
        "ug_m3",
    )
    assert result.nowcast_weight_factor == 0.8


def test_nowcast_rejects_invalid_value_instead_of_discarding_it() -> None:
    result = calculate_pm_nowcast(
        "pm25",
        (10, 12, float("nan")),
        "ug_m3",
    )
    assert result.calculation_status is CalculationStatus.UNAVAILABLE
    assert result.exclusion_reason is ExclusionReason.INVALID_CONCENTRATION
