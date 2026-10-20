from __future__ import annotations

"""Pure Philippine DENR-EMB Air Quality Index calculations.

DAO 2000-81 defines the pollutant breakpoint tables and special ozone and
nitrogen-dioxide behavior. DAO 2020-14 supplies the current PM2.5 table.
EMB MC 2021-07 adopts the calculation and data-handling manual. This module
contains no database, transport, or presentation behavior.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from enum import Enum
import math
from numbers import Real
from typing import Optional, Tuple

from .domain import (
    AirQualityIndexProduct,
    AirQualityIndexStandard,
    ExclusionReason,
    IndexCategory,
    MethodologyReference,
    ResultKind,
)


STANDARD_CODE = "philippines_denr"
DISPLAY_NAME = "Philippines Air Quality Index"
METHODOLOGY_CODE = "philippines_denr_aqi"
METHODOLOGY_VERSION = "denr_emb_aqi_2021"
METHODOLOGY_REVISION = "2021-05"
METHODOLOGY_EFFECTIVE_DATE = "2021-05-03"
CALCULATION_TIMEZONE = "Asia/Manila"
DEFAULT_PRODUCT_CODE = "philippines_denr.pm25.completed_day"


class CalculationStatus(str, Enum):
    CALCULATED = "calculated"
    CATEGORY_ONLY = "category_only"
    UNAVAILABLE = "unavailable"


class AqiScaleStatus(str, Enum):
    WITHIN_PUBLISHED_NUMERIC_RANGE = "within_published_numeric_range"
    ABOVE_PUBLISHED_NUMERIC_RANGE = "above_published_numeric_range"


@dataclass(frozen=True)
class Breakpoint:
    concentration_low: Decimal
    concentration_high: Optional[Decimal]
    index_low: int
    index_high: int
    category_code: str


@dataclass(frozen=True)
class ComponentDefinition:
    component_code: str
    parameter_code: str
    normalized_unit: str
    truncation_decimal_places: Optional[int]
    breakpoints: Tuple[Breakpoint, ...]
    below_first_reason: ExclusionReason = ExclusionReason.PUBLISHED_BREAKPOINT_GAP


@dataclass(frozen=True)
class UnitNormalizationResult:
    normalized_concentration: Optional[Decimal]
    normalized_unit: Optional[str]
    exclusion_reason: Optional[ExclusionReason]

    @property
    def is_supported(self) -> bool:
        return self.exclusion_reason is None


@dataclass(frozen=True)
class PhilippineAqiCalculationResult:
    parameter_code: str
    component_code: str
    calculation_status: CalculationStatus
    exclusion_reason: Optional[ExclusionReason]
    input_unit: Optional[str]
    normalized_concentration: Optional[Decimal]
    normalized_unit: Optional[str]
    preprocessed_concentration: Optional[Decimal]
    numeric_value: Optional[Decimal]
    category_code: Optional[str]
    category_label: Optional[str]
    internal_severity_rank: Optional[int]
    aqi_scale_status: Optional[AqiScaleStatus]

    @property
    def is_eligible(self) -> bool:
        return self.calculation_status in {
            CalculationStatus.CALCULATED,
            CalculationStatus.CATEGORY_ONLY,
        }


METHODOLOGY_REFERENCES = (
    MethodologyReference(
        reference_code="dao_2000_81",
        title=(
            "Implementing Rules and Regulations for Republic Act No. 8749"
        ),
        document_number="DENR Administrative Order No. 2000-81",
        publication_date="2000-11-07",
        section="Annex A: Air Quality Indices",
        url="https://air.emb.gov.ph/wp-content/uploads/2016/04/DAO-2000-81.pdf",
    ),
    MethodologyReference(
        reference_code="dao_2020_14",
        title=(
            "Establishing the Breakpoints for Particulate Matter 2.5 Air "
            "Quality Index"
        ),
        document_number="DENR Administrative Order No. 2020-14",
        publication_date="2020-10-21",
        section="PM2.5 AQI breakpoint table",
        url=(
            "https://air.emb.gov.ph/wp-content/uploads/2021/01/"
            "DAO-2020-14-PM-2.5-Signed.pdf"
        ),
    ),
    MethodologyReference(
        reference_code="emb_mc_2021_07",
        title=(
            "Procedural Manual on Data Handling Conventions for Criteria "
            "Air Pollutants"
        ),
        document_number="EMB Memorandum Circular No. 2021-07",
        publication_date="2021-05-03",
        section="AQI calculation and data completeness chapters",
        url=(
            "https://www.emb.gov.ph/wp-content/uploads/2022/11/"
            "EMB-MC-2021-07_FINAL-MANUAL-ON-DATA-HANDLING.pdf"
        ),
    ),
)


CATEGORIES = (
    IndexCategory("good", "Good", 1, "#00E400", 0, 50),
    IndexCategory("fair", "Fair", 2, "#FFFF00", 51, 100),
    IndexCategory(
        "unhealthy_for_sensitive_groups",
        "Unhealthy for Sensitive Groups",
        3,
        "#FF7E00",
        101,
        150,
    ),
    IndexCategory("very_unhealthy", "Very Unhealthy", 4, "#FF0000", 151, 200),
    IndexCategory("acutely_unhealthy", "Acutely Unhealthy", 5, "#8F3F97", 201, 300),
    IndexCategory("emergency", "Emergency", 6, "#7E0023", 301, 500),
)
CATEGORY_BY_CODE = {category.code: category for category in CATEGORIES}

# DAO 2000-81 Annex A applies this table to TSP, PM10, SO2, ozone, and NO2.
# DAO 2020-14 publishes the same category-level statements for PM2.5.
GENERAL_CAUTIONARY_STATEMENTS = {
    "good": None,
    "fair": None,
    "unhealthy_for_sensitive_groups": (
        "People with respiratory disease, such as asthma, should limit outdoor exertion."
    ),
    "very_unhealthy": (
        "Pedestrians should avoid heavy traffic areas. People with heart or respiratory "
        "disease, such as asthma, should stay indoors and rest as much as possible. "
        "Unnecessary trips should be postponed. People should voluntarily restrict the "
        "use of vehicles."
    ),
    "acutely_unhealthy": (
        "People should limit outdoor exertion. People with heart or respiratory disease, "
        "such as asthma, should stay indoors and rest as much as possible. Unnecessary "
        "trips should be postponed. Motor vehicle use may be restricted. Industrial "
        "activities may be curtailed."
    ),
    "emergency": (
        "Everyone should remain indoors, keeping windows and doors closed unless heat "
        "stress is possible. Motor vehicle use should be prohibited except for emergency "
        "situations. Industrial activities, except that which is vital for public safety "
        "and health, should be curtailed."
    ),
}
CO_CAUTIONARY_STATEMENTS = {
    "good": None,
    "fair": None,
    "unhealthy_for_sensitive_groups": (
        "People with cardiovascular disease, such as angina, should limit heavy exertion "
        "and avoid sources of carbon monoxide, such as heavy traffic."
    ),
    "very_unhealthy": "Smokers should refrain from smoking.",
    "acutely_unhealthy": (
        "People with cardiovascular disease, such as angina, should limit heavy exertion "
        "and avoid sources of carbon monoxide, such as heavy traffic."
    ),
    "emergency": (
        "Everyone should avoid exertion and sources of carbon monoxide, such as heavy "
        "traffic, and should stay indoors and rest as much as possible."
    ),
}
CAUTIONARY_STATEMENTS_BY_POLLUTANT = {
    parameter_code: dict(GENERAL_CAUTIONARY_STATEMENTS)
    for parameter_code in ("pm25", "pm10", "so2", "o3", "no2")
}
CAUTIONARY_STATEMENTS_BY_POLLUTANT["co"] = CO_CAUTIONARY_STATEMENTS


def _breakpoint(
    low: str,
    high: Optional[str],
    index_low: int,
    index_high: int,
    category_code: str,
) -> Breakpoint:
    return Breakpoint(
        concentration_low=Decimal(low),
        concentration_high=Decimal(high) if high is not None else None,
        index_low=index_low,
        index_high=index_high,
        category_code=category_code,
    )


_CATEGORY_CODES = tuple(category.code for category in CATEGORIES)


def _six_bands(bounds: tuple[tuple[str, Optional[str]], ...]) -> Tuple[Breakpoint, ...]:
    index_ranges = ((0, 50), (51, 100), (101, 150), (151, 200), (201, 300), (301, 500))
    return tuple(
        _breakpoint(low, high, index_low, index_high, category_code)
        for (low, high), (index_low, index_high), category_code in zip(
            bounds, index_ranges, _CATEGORY_CODES
        )
    )


PM25_24_HOUR_BREAKPOINTS = _six_bands(
    (("0", "25"), ("25.1", "35.0"), ("35.1", "45.0"), ("45.1", "55"), ("55.1", "90"), ("91", None))
)
PM10_24_HOUR_BREAKPOINTS = _six_bands(
    (("0", "54"), ("55", "154"), ("155", "254"), ("255", "354"), ("355", "424"), ("425", "504"))
)
SO2_24_HOUR_BREAKPOINTS = _six_bands(
    (("0.000", "0.034"), ("0.035", "0.144"), ("0.145", "0.224"), ("0.225", "0.304"), ("0.305", "0.604"), ("0.605", "0.804"))
)
OZONE_8_HOUR_BREAKPOINTS = (
    _breakpoint("0.000", "0.064", 0, 50, "good"),
    _breakpoint("0.065", "0.084", 51, 100, "fair"),
    _breakpoint(
        "0.085", "0.104", 101, 150, "unhealthy_for_sensitive_groups"
    ),
    _breakpoint("0.105", "0.124", 151, 200, "very_unhealthy"),
    _breakpoint("0.125", "0.374", 201, 300, "acutely_unhealthy"),
)
OZONE_1_HOUR_BREAKPOINTS = (
    _breakpoint("0.125", "0.164", 101, 150, "unhealthy_for_sensitive_groups"),
    _breakpoint("0.165", "0.204", 151, 200, "very_unhealthy"),
    _breakpoint("0.205", "0.404", 201, 300, "acutely_unhealthy"),
    _breakpoint("0.405", "0.504", 301, 500, "emergency"),
)
CO_8_HOUR_BREAKPOINTS = _six_bands(
    (("0.0", "4.4"), ("4.5", "9.4"), ("9.5", "12.4"), ("12.5", "15.4"), ("15.5", "30.4"), ("30.5", "40.4"))
)
NO2_1_HOUR_BREAKPOINTS = (
    _breakpoint("0.65", "1.24", 201, 300, "acutely_unhealthy"),
    _breakpoint("1.25", "1.64", 301, 500, "emergency"),
)


COMPONENT_DEFINITIONS = {
    "pm25_24_hour": ComponentDefinition("pm25_24_hour", "pm25", "µg/m³", 1, PM25_24_HOUR_BREAKPOINTS),
    "pm10_24_hour": ComponentDefinition("pm10_24_hour", "pm10", "µg/m³", 0, PM10_24_HOUR_BREAKPOINTS),
    "so2_24_hour": ComponentDefinition("so2_24_hour", "so2", "ppm", None, SO2_24_HOUR_BREAKPOINTS),
    "o3_8_hour": ComponentDefinition("o3_8_hour", "o3", "ppm", None, OZONE_8_HOUR_BREAKPOINTS),
    "o3_1_hour": ComponentDefinition("o3_1_hour", "o3", "ppm", None, OZONE_1_HOUR_BREAKPOINTS),
    "co_8_hour": ComponentDefinition("co_8_hour", "co", "ppm", None, CO_8_HOUR_BREAKPOINTS),
    "no2_1_hour": ComponentDefinition(
        "no2_1_hour",
        "no2",
        "ppm",
        None,
        NO2_1_HOUR_BREAKPOINTS,
        ExclusionReason.SUBINDEX_NOT_DEFINED_FOR_CONCENTRATION,
    ),
}


def _product(
    product_code: str,
    display_name: str,
    parameter_code: str,
    calculation_code: str,
    aggregation_period: str,
    aggregation_display_name: str,
    history_interval: str,
    maximum_history_interval_count: int,
) -> AirQualityIndexProduct:
    return AirQualityIndexProduct(
        product_code=product_code,
        display_name=display_name,
        parameter_code=parameter_code,
        calculation_code=calculation_code,
        aggregation_period=aggregation_period,
        aggregation_display_name=aggregation_display_name,
        result_scope="pollutant",
        is_parameter_default=True,
        product_kind="completed_day" if history_interval == "represented_local_date" else "latest_window",
        history_interval=history_interval,
        maximum_history_interval_count=maximum_history_interval_count,
        methodology_code=METHODOLOGY_CODE,
        methodology_revision=METHODOLOGY_REVISION,
        methodology_effective_date=METHODOLOGY_EFFECTIVE_DATE,
        methodology_references=METHODOLOGY_REFERENCES,
        limitations=(
            "Uses Asia/Manila regulatory periods regardless of device timezone.",
            "Regulatory-monitor qualification is not evaluated.",
            "No official multi-pollutant overall AQI is claimed.",
        ),
    )


PHILIPPINES_DENR_PRODUCTS = (
    _product(DEFAULT_PRODUCT_CODE, "Philippines PM2.5 Completed-Day AQI", "pm25", "pm25_completed_day", "24h", "Completed Philippine local day", "represented_local_date", 366),
    _product("philippines_denr.pm10.completed_day", "Philippines PM10 Completed-Day AQI", "pm10", "pm10_completed_day", "24h", "Completed Philippine local day", "represented_local_date", 366),
    _product("philippines_denr.so2.completed_day", "Philippines SO2 Completed-Day AQI", "so2", "so2_completed_day", "24h", "Completed Philippine local day", "represented_local_date", 366),
    _product("philippines_denr.o3.latest", "Philippines Ozone AQI", "o3", "ozone_latest_completed_window", "latest_completed_window", "Latest completed 8-hour and corresponding 1-hour windows", "utc_hour", 2160),
    _product("philippines_denr.co.latest", "Philippines CO AQI", "co", "co_latest_completed_8_hour_window", "8h", "Latest completed rolling 8-hour window", "utc_hour", 2160),
    _product("philippines_denr.no2.latest", "Philippines NO2 AQI", "no2", "no2_latest_completed_hour", "1h", "Latest completed Philippine clock hour", "utc_hour", 2160),
)


PHILIPPINES_DENR_STANDARD = AirQualityIndexStandard(
    code=STANDARD_CODE,
    display_name=DISPLAY_NAME,
    methodology_version=METHODOLOGY_VERSION,
    result_kind=ResultKind.NUMERIC,
    averaging_minutes=1440,
    pollutants=("pm25", "pm10", "so2", "o3", "co", "no2"),
    categories=CATEGORIES,
    products=PHILIPPINES_DENR_PRODUCTS,
    default_product_code=DEFAULT_PRODUCT_CODE,
    is_default=False,
    methodology_code=METHODOLOGY_CODE,
    methodology_revision=METHODOLOGY_REVISION,
    methodology_effective_date=METHODOLOGY_EFFECTIVE_DATE,
    methodology_references=METHODOLOGY_REFERENCES,
    limitations=(
        "TSP is deferred because CompassAQ has no canonical TSP parameter.",
        "Undocumented operational hourly-dashboard calculations are excluded.",
        "No official multi-pollutant overall AQI is claimed.",
        "Completeness rules are applied to AQI periods as an explicit CompassAQ policy.",
    ),
)


def _normalized_unit_code(input_unit: object) -> str:
    return str(input_unit or "").strip().lower().replace("μ", "µ")


def _decimal_concentration(concentration: object) -> Optional[Decimal]:
    if isinstance(concentration, bool):
        return None
    if isinstance(concentration, Real) and not math.isfinite(float(concentration)):
        return None
    try:
        value = Decimal(str(concentration))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


def normalize_concentration_unit(
    parameter_code: str,
    concentration: object,
    input_unit: object,
) -> UnitNormalizationResult:
    parameter = str(parameter_code or "").strip().lower()
    value = _decimal_concentration(concentration)
    if value is None:
        return UnitNormalizationResult(None, None, ExclusionReason.INVALID_CONCENTRATION)
    unit = _normalized_unit_code(input_unit)
    if parameter in {"pm25", "pm10"}:
        if unit in {"ug_m3", "µg/m³", "ug/m3", "ug/m^3"}:
            return UnitNormalizationResult(value, "µg/m³", None)
        if unit in {"mg_m3", "mg/m³", "mg/m3", "mg/m^3"}:
            return UnitNormalizationResult(value * Decimal("1000"), "µg/m³", None)
        if unit in {"ug_ncm", "µg/ncm"}:
            return UnitNormalizationResult(None, None, ExclusionReason.CONVERSION_NOT_SUPPORTED)
        return UnitNormalizationResult(None, None, ExclusionReason.UNSUPPORTED_UNIT)
    if parameter in {"so2", "o3", "co", "no2"}:
        if unit == "ppm":
            return UnitNormalizationResult(value, "ppm", None)
        if unit == "ppb":
            return UnitNormalizationResult(value / Decimal("1000"), "ppm", None)
        if unit in {"ug_m3", "µg/m³", "ug/m3", "mg_m3", "mg/m³", "mg/m3"}:
            return UnitNormalizationResult(None, None, ExclusionReason.CONVERSION_NOT_SUPPORTED)
        return UnitNormalizationResult(None, None, ExclusionReason.UNSUPPORTED_UNIT)
    return UnitNormalizationResult(None, None, ExclusionReason.UNSUPPORTED_POLLUTANT)


def _unavailable(
    parameter_code: str,
    component_code: str,
    reason: ExclusionReason,
    *,
    input_unit: object,
    normalized_concentration: Optional[Decimal] = None,
    normalized_unit: Optional[str] = None,
    preprocessed_concentration: Optional[Decimal] = None,
) -> PhilippineAqiCalculationResult:
    return PhilippineAqiCalculationResult(
        parameter_code=parameter_code,
        component_code=component_code,
        calculation_status=CalculationStatus.UNAVAILABLE,
        exclusion_reason=reason,
        input_unit=str(input_unit) if input_unit is not None else None,
        normalized_concentration=normalized_concentration,
        normalized_unit=normalized_unit,
        preprocessed_concentration=preprocessed_concentration,
        numeric_value=None,
        category_code=None,
        category_label=None,
        internal_severity_rank=None,
        aqi_scale_status=None,
    )


def _preprocess(value: Decimal, decimal_places: Optional[int]) -> Decimal:
    if decimal_places is None:
        return value
    quantum = Decimal("1").scaleb(-decimal_places)
    return value.quantize(quantum, rounding=ROUND_DOWN)


def _interpolate(value: Decimal, breakpoint: Breakpoint) -> Decimal:
    assert breakpoint.concentration_high is not None
    concentration_span = breakpoint.concentration_high - breakpoint.concentration_low
    index_span = Decimal(breakpoint.index_high - breakpoint.index_low)
    interpolated = (
        index_span / concentration_span * (value - breakpoint.concentration_low)
        + Decimal(breakpoint.index_low)
    )
    return interpolated.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_component_aqi(
    parameter_code: str,
    component_code: str,
    concentration: object,
    input_unit: object,
) -> PhilippineAqiCalculationResult:
    parameter = str(parameter_code or "").strip().lower()
    if parameter not in PHILIPPINES_DENR_STANDARD.pollutants:
        return _unavailable(
            parameter,
            component_code,
            ExclusionReason.UNSUPPORTED_POLLUTANT,
            input_unit=input_unit,
        )
    definition = COMPONENT_DEFINITIONS.get(component_code)
    if definition is None or definition.parameter_code != parameter:
        return _unavailable(parameter, component_code, ExclusionReason.UNSUPPORTED_PRODUCT, input_unit=input_unit)
    normalization = normalize_concentration_unit(parameter, concentration, input_unit)
    if not normalization.is_supported or normalization.normalized_concentration is None:
        return _unavailable(
            parameter,
            component_code,
            normalization.exclusion_reason or ExclusionReason.UNSUPPORTED_UNIT,
            input_unit=input_unit,
        )
    normalized = normalization.normalized_concentration
    preprocessed = _preprocess(normalized, definition.truncation_decimal_places)
    selected = next(
        (
            breakpoint
            for breakpoint in definition.breakpoints
            if preprocessed >= breakpoint.concentration_low
            and (breakpoint.concentration_high is None or preprocessed <= breakpoint.concentration_high)
        ),
        None,
    )
    if selected is None:
        last = definition.breakpoints[-1]
        if preprocessed < definition.breakpoints[0].concentration_low:
            reason = definition.below_first_reason
        elif last.concentration_high is not None and preprocessed > last.concentration_high:
            category = CATEGORY_BY_CODE["emergency"]
            return PhilippineAqiCalculationResult(
                parameter, component_code, CalculationStatus.CATEGORY_ONLY, None,
                str(input_unit) if input_unit is not None else None,
                normalized, normalization.normalized_unit, preprocessed, None,
                category.code, category.label, category.internal_severity_rank,
                AqiScaleStatus.ABOVE_PUBLISHED_NUMERIC_RANGE,
            )
        else:
            reason = ExclusionReason.PUBLISHED_BREAKPOINT_GAP
        return _unavailable(
            parameter,
            component_code,
            reason,
            input_unit=input_unit,
            normalized_concentration=normalized,
            normalized_unit=normalization.normalized_unit,
            preprocessed_concentration=preprocessed,
        )
    category = CATEGORY_BY_CODE[selected.category_code]
    if selected.concentration_high is None:
        return PhilippineAqiCalculationResult(
            parameter, component_code, CalculationStatus.CATEGORY_ONLY, None,
            str(input_unit) if input_unit is not None else None,
            normalized, normalization.normalized_unit, preprocessed, None,
            category.code, category.label, category.internal_severity_rank,
            AqiScaleStatus.ABOVE_PUBLISHED_NUMERIC_RANGE,
        )
    numeric_value = _interpolate(preprocessed, selected)
    return PhilippineAqiCalculationResult(
        parameter, component_code, CalculationStatus.CALCULATED, None,
        str(input_unit) if input_unit is not None else None,
        normalized, normalization.normalized_unit, preprocessed, numeric_value,
        category.code, category.label, category.internal_severity_rank,
        AqiScaleStatus.WITHIN_PUBLISHED_NUMERIC_RANGE,
    )


def calculate_ozone_aqi(
    eight_hour_concentration: object,
    input_unit: object,
    *,
    corresponding_one_hour_concentration: object | None = None,
    corresponding_one_hour_input_unit: object | None = None,
) -> PhilippineAqiCalculationResult:
    eight_hour = calculate_component_aqi("o3", "o3_8_hour", eight_hour_concentration, input_unit)
    if (
        eight_hour.normalized_concentration is not None
        and eight_hour.normalized_concentration > Decimal("0.374")
    ):
        if corresponding_one_hour_concentration is None:
            return _unavailable(
                "o3",
                "ozone_latest_completed_window",
                ExclusionReason.NO_APPLICABLE_OZONE_CANDIDATE,
                input_unit=input_unit,
                normalized_concentration=eight_hour.normalized_concentration,
                normalized_unit=eight_hour.normalized_unit,
                preprocessed_concentration=eight_hour.preprocessed_concentration,
            )
        one_hour = calculate_component_aqi(
            "o3",
            "o3_1_hour",
            corresponding_one_hour_concentration,
            corresponding_one_hour_input_unit or input_unit,
        )
        if not one_hour.is_eligible:
            return _unavailable(
                "o3",
                "ozone_latest_completed_window",
                ExclusionReason.NO_APPLICABLE_OZONE_CANDIDATE,
                input_unit=input_unit,
                normalized_concentration=eight_hour.normalized_concentration,
                normalized_unit=eight_hour.normalized_unit,
                preprocessed_concentration=eight_hour.preprocessed_concentration,
            )
        return one_hour
    return eight_hour
