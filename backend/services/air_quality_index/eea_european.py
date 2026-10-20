from __future__ import annotations

"""Pure implementation of the EEA 2024 European Air Quality Index bands.

Source: European Environment Agency, "European Air Quality Index",
methodology section and its 2024 revised hourly concentration bands.
"""

import math
from decimal import Decimal
from numbers import Real
from typing import Iterable, Optional

from .domain import (
    AirQualityIndexResult,
    AirQualityIndexProduct,
    AirQualityIndexStandard,
    CoverageInformation,
    CoverageState,
    DisplayQualification,
    EligibilityStatus,
    ExclusionReason,
    IndexCategory,
    PollutantIndexResult,
    ResultKind,
)


STANDARD_CODE = "eea_european"
DISPLAY_NAME = "European Air Quality Index"
METHODOLOGY_VERSION = "eea_2024_bands"
NORMALIZED_UNIT = "µg/m³"

POLLUTANTS = ("pm25", "pm10", "o3", "no2", "so2")

CATEGORIES = (
    IndexCategory("good", "Good", 1, "#50F0E6"),
    IndexCategory("fair", "Fair", 2, "#50CCAA"),
    IndexCategory("moderate", "Moderate", 3, "#F0E641"),
    IndexCategory("poor", "Poor", 4, "#FF5050"),
    IndexCategory("very_poor", "Very poor", 5, "#960032"),
    IndexCategory("extremely_poor", "Extremely poor", 6, "#7D2181"),
)

EEA_EUROPEAN_PRODUCTS = (
    AirQualityIndexProduct(
        product_code="eea_european.overall.hourly",
        display_name="Overall hourly European AQI",
        parameter_code=None,
        calculation_code="worst_available_category",
        aggregation_period="1h",
        aggregation_display_name="1-hour average",
        result_scope="overall",
    ),
    *(
        AirQualityIndexProduct(
            product_code=f"eea_european.{parameter_code}.hourly",
            display_name=f"{display_name} hourly European AQI",
            parameter_code=parameter_code,
            calculation_code="hourly_category",
            aggregation_period="1h",
            aggregation_display_name="1-hour average",
            result_scope="pollutant",
        )
        for parameter_code, display_name in (
            ("pm25", "PM2.5"),
            ("pm10", "PM10"),
            ("o3", "O₃"),
            ("no2", "NO₂"),
            ("so2", "SO₂"),
        )
    ),
)

# Inclusive upper bounds for the first five categories. Values above the final
# bound are Extremely poor. EEA publishes these bands for hourly concentrations;
# it does not require rounding or truncation before comparison.
CONCENTRATION_UPPER_BOUNDS = {
    "pm25": (5.0, 15.0, 50.0, 90.0, 140.0),
    "pm10": (15.0, 45.0, 120.0, 195.0, 270.0),
    "o3": (60.0, 100.0, 120.0, 160.0, 180.0),
    "no2": (10.0, 25.0, 60.0, 100.0, 150.0),
    "so2": (20.0, 40.0, 125.0, 190.0, 275.0),
}

EEA_EUROPEAN_STANDARD = AirQualityIndexStandard(
    code=STANDARD_CODE,
    display_name=DISPLAY_NAME,
    methodology_version=METHODOLOGY_VERSION,
    result_kind=ResultKind.CATEGORICAL,
    averaging_minutes=60,
    pollutants=POLLUTANTS,
    categories=CATEGORIES,
    products=EEA_EUROPEAN_PRODUCTS,
    default_product_code="eea_european.overall.hourly",
)


def normalize_pollutant(pollutant: object) -> str:
    """Normalize common spellings to a canonical CompassAQ pollutant code."""
    value = str(pollutant or "").strip().lower()
    compact = value.replace(".", "").replace("_", "").replace("-", "").replace(" ", "")
    aliases = {
        "pm25": "pm25",
        "pm10": "pm10",
        "o3": "o3",
        "no2": "no2",
        "so2": "so2",
    }
    return aliases.get(compact, compact)


def _unit_kind(unit: object) -> Optional[str]:
    if unit is None:
        return None
    value = str(unit).strip().lower()
    if not value:
        return None
    value = value.replace("μ", "u").replace("µ", "u")
    value = value.replace("³", "3").replace("^3", "3")
    value = value.replace(" ", "").replace("/", "_")
    if value in {"ug_m3", "ugm3"}:
        return "ug_m3"
    if value in {"mg_m3", "mgm3"}:
        return "mg_m3"
    return None


def ineligible_pollutant_result(
    parameter_code: str,
    reason: ExclusionReason,
    *,
    normalized_concentration: Optional[float] = None,
    normalized_unit: Optional[str] = None,
) -> PollutantIndexResult:
    """Build an explicit EEA pollutant exclusion without classifying a value."""
    canonical_parameter_code = normalize_pollutant(parameter_code)
    return PollutantIndexResult(
        standard_code=STANDARD_CODE,
        methodology_version=METHODOLOGY_VERSION,
        parameter_code=canonical_parameter_code,
        normalized_concentration=normalized_concentration,
        normalized_unit=normalized_unit,
        preprocessed_concentration=None,
        result_kind=ResultKind.CATEGORICAL,
        numeric_value=None,
        category_code=None,
        category_label=None,
        internal_severity_rank=None,
        eligibility_status=EligibilityStatus.INELIGIBLE,
        exclusion_reason=reason,
    )


def classify_hourly_concentration(
    pollutant: object,
    concentration: object,
    unit: object,
) -> PollutantIndexResult:
    """Classify one hourly concentration under the current European AQI.

    Eligible values are normalized to µg/m³. The returned severity rank is an
    internal ordering aid; the official European result remains the category.
    """
    canonical_pollutant = normalize_pollutant(pollutant)
    if canonical_pollutant not in CONCENTRATION_UPPER_BOUNDS:
        return ineligible_pollutant_result(
            canonical_pollutant,
            ExclusionReason.UNSUPPORTED_POLLUTANT,
        )

    if isinstance(concentration, bool) or not isinstance(concentration, (Real, Decimal)):
        return ineligible_pollutant_result(
            canonical_pollutant,
            ExclusionReason.INVALID_CONCENTRATION,
        )
    numeric_concentration = float(concentration)
    if not math.isfinite(numeric_concentration):
        return ineligible_pollutant_result(
            canonical_pollutant,
            ExclusionReason.INVALID_CONCENTRATION,
        )

    unit_kind = _unit_kind(unit)
    if unit_kind is None:
        return ineligible_pollutant_result(
            canonical_pollutant,
            ExclusionReason.UNSUPPORTED_UNIT,
        )

    normalized_concentration = (
        numeric_concentration * 1000.0 if unit_kind == "mg_m3" else numeric_concentration
    )
    if normalized_concentration < 0:
        return ineligible_pollutant_result(
            canonical_pollutant,
            ExclusionReason.INVALID_CONCENTRATION,
            normalized_concentration=normalized_concentration,
            normalized_unit=NORMALIZED_UNIT,
        )

    # EEA has no pollutant-specific preprocessing step. Keep this established
    # API field equal to the normalized concentration; display formatting is a
    # separate presentation concern.
    preprocessed_concentration = normalized_concentration

    bounds = CONCENTRATION_UPPER_BOUNDS[canonical_pollutant]
    category_index = len(bounds)
    for index, upper_bound in enumerate(bounds):
        if normalized_concentration <= upper_bound:
            category_index = index
            break
    category = CATEGORIES[category_index]

    return PollutantIndexResult(
        standard_code=STANDARD_CODE,
        methodology_version=METHODOLOGY_VERSION,
        parameter_code=canonical_pollutant,
        normalized_concentration=normalized_concentration,
        normalized_unit=NORMALIZED_UNIT,
        preprocessed_concentration=preprocessed_concentration,
        result_kind=ResultKind.CATEGORICAL,
        numeric_value=None,
        category_code=category.code,
        category_label=category.label,
        internal_severity_rank=category.internal_severity_rank,
        eligibility_status=EligibilityStatus.ELIGIBLE,
        exclusion_reason=None,
    )


def combine_pollutant_results(
    pollutant_results: Iterable[PollutantIndexResult],
) -> AirQualityIndexResult:
    """Combine European pollutant results into the worst available category."""
    results = tuple(pollutant_results)
    by_pollutant: dict[str, PollutantIndexResult] = {}
    extra_results: list[PollutantIndexResult] = []
    for result in results:
        if result.standard_code != STANDARD_CODE or result.methodology_version != METHODOLOGY_VERSION:
            raise ValueError("Cannot combine results from another AQI standard or methodology version")
        if result.parameter_code in POLLUTANTS:
            if result.parameter_code in by_pollutant:
                raise ValueError(f"Duplicate pollutant result: {result.parameter_code}")
            by_pollutant[result.parameter_code] = result
        else:
            extra_results.append(result)

    ordered_results = tuple(
        [by_pollutant[pollutant] for pollutant in POLLUTANTS if pollutant in by_pollutant]
        + sorted(extra_results, key=lambda result: result.parameter_code)
    )
    eligible_results = tuple(result for result in ordered_results if result.is_eligible)

    available = tuple(
        pollutant
        for pollutant in POLLUTANTS
        if pollutant in by_pollutant and by_pollutant[pollutant].is_eligible
    )
    missing = tuple(pollutant for pollutant in POLLUTANTS if pollutant not in by_pollutant)
    ineligible = tuple(
        pollutant
        for pollutant in POLLUTANTS
        if pollutant in by_pollutant and not by_pollutant[pollutant].is_eligible
    )
    unavailable = tuple(
        pollutant for pollutant in POLLUTANTS if pollutant in set(missing) | set(ineligible)
    )

    if len(available) == len(POLLUTANTS):
        coverage_state = CoverageState.COMPLETE
    elif available:
        coverage_state = CoverageState.PARTIAL
    else:
        coverage_state = CoverageState.NONE

    coverage = CoverageInformation(
        coverage_status=coverage_state,
        available_pollutants=available,
        missing_pollutants=missing,
        ineligible_pollutants=ineligible,
        missing_or_ineligible_pollutants=unavailable,
        display_qualification=DisplayQualification.NOT_EVALUATED,
    )

    input_exclusion_reasons = tuple(
        dict.fromkeys(
            result.exclusion_reason
            for result in ordered_results
            if result.exclusion_reason is not None
        )
    )

    if not eligible_results:
        return AirQualityIndexResult(
            standard_code=STANDARD_CODE,
            methodology_version=METHODOLOGY_VERSION,
            result_kind=ResultKind.CATEGORICAL,
            numeric_value=None,
            category_code=None,
            category_label=None,
            internal_severity_rank=None,
            eligibility_status=EligibilityStatus.INELIGIBLE,
            exclusion_reasons=input_exclusion_reasons + (ExclusionReason.NO_ELIGIBLE_POLLUTANTS,),
            dominant_pollutants=(),
            pollutant_results=ordered_results,
            coverage=coverage,
        )

    worst_rank = max(result.internal_severity_rank or 0 for result in eligible_results)
    worst_results = tuple(
        result for result in eligible_results if result.internal_severity_rank == worst_rank
    )
    worst_category = worst_results[0]
    dominant = tuple(
        pollutant
        for pollutant in POLLUTANTS
        if any(result.parameter_code == pollutant for result in worst_results)
    )

    return AirQualityIndexResult(
        standard_code=STANDARD_CODE,
        methodology_version=METHODOLOGY_VERSION,
        result_kind=ResultKind.CATEGORICAL,
        numeric_value=None,
        category_code=worst_category.category_code,
        category_label=worst_category.category_label,
        internal_severity_rank=worst_category.internal_severity_rank,
        eligibility_status=EligibilityStatus.ELIGIBLE,
        exclusion_reasons=input_exclusion_reasons,
        dominant_pollutants=dominant,
        pollutant_results=ordered_results,
        coverage=coverage,
    )
