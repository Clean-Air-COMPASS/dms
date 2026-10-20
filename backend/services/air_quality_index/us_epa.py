from __future__ import annotations

"""Pure U.S. EPA AQI calculations used by CompassAQ current conditions.

Authoritative methodology:

* 40 CFR Part 58, Appendix G, section 3.4 and Table 2.
* U.S. EPA, "Technical Assistance Document for the Reporting of Daily Air
  Quality – the Air Quality Index (AQI)", EPA-403/B-26-003, May 2026,
  section IV and Table 6. The archived EPA-454/B-24-002, May 2024 edition
  established the revised PM2.5 table implemented here.
* 89 FR 16202, March 6, 2024, section IV.B.3. The revised PM2.5 AQI
  breakpoints became effective May 6, 2024.

The May 2026 TAD preserves the implemented PM breakpoints and NowCast method,
corrects the ozone worked example, and explicitly confirms the upper Hazardous
slope for AQI values above 500. The calculation methodology revision remains
2024-05 because that is the effective revision of the breakpoints.

This module contains no database, API, or display-formatting behavior.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from enum import Enum
import math
from numbers import Real
from typing import Optional, Sequence, Tuple

from .domain import (
    AirQualityIndexProduct,
    AirQualityIndexStandard,
    ExclusionReason,
    IndexCategory,
    MethodologyReference,
    ResultKind,
)


STANDARD_CODE = "us_epa"
DISPLAY_NAME = "U.S. EPA AQI"
METHODOLOGY_CODE = "us_epa_aqi_40_cfr_58_appendix_g"
METHODOLOGY_VERSION = "us_epa_aqi_2024"
METHODOLOGY_REVISION = "2024-05"
PM25_BREAKPOINT_EFFECTIVE_DATE = "2024-05-06"
OZONE_BREAKPOINT_EFFECTIVE_DATE = "2015-12-28"
DEFAULT_PRODUCT_CODE = "us_epa.pm25.nowcast"


class CalculationStatus(str, Enum):
    CALCULATED = "calculated"
    UNAVAILABLE = "unavailable"


class CoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NONE = "none"


class AqiScaleStatus(str, Enum):
    WITHIN_0_TO_500 = "within_0_to_500"
    ABOVE_500 = "above_500"


class DataQualificationStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class Breakpoint:
    concentration_low: Decimal
    concentration_high: Decimal
    aqi_low: int
    aqi_high: int


@dataclass(frozen=True)
class ComponentDefinition:
    component_code: str
    parameter_code: str
    normalized_unit: str
    truncation_decimal_places: int
    breakpoints: Tuple[Breakpoint, ...]
    allow_above_500: bool = True
    below_first_breakpoint_reason: Optional[ExclusionReason] = None
    above_last_breakpoint_reason: Optional[ExclusionReason] = None


@dataclass(frozen=True)
class UnitNormalizationResult:
    normalized_concentration: Optional[Decimal]
    normalized_unit: Optional[str]
    exclusion_reason: Optional[ExclusionReason]

    @property
    def is_supported(self) -> bool:
        return self.exclusion_reason is None


@dataclass(frozen=True)
class UsEpaCalculationResult:
    parameter_code: str
    component_code: str
    calculation_status: CalculationStatus
    coverage_status: CoverageStatus
    exclusion_reason: Optional[ExclusionReason]
    normalized_concentration: Optional[float]
    normalized_unit: Optional[str]
    preprocessed_concentration: Optional[float]
    numeric_value: Optional[int]
    category_code: Optional[str]
    category_label: Optional[str]
    internal_severity_rank: Optional[int]
    aqi_scale_status: Optional[AqiScaleStatus]
    expected_observation_count: int
    valid_observation_count: int
    nowcast_weight_factor: Optional[float] = None

    @property
    def is_calculated(self) -> bool:
        return self.calculation_status is CalculationStatus.CALCULATED


METHODOLOGY_REFERENCES = (
    MethodologyReference(
        reference_code="40_cfr_58_appendix_g",
        title="Uniform Air Quality Index (AQI) and Daily Reporting",
        document_number="40 CFR Part 58, Appendix G",
        publication_date=None,
        section="Section 3.4 and Table 2",
        url=(
            "https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/"
            "part-58/appendix-Appendix%20G%20to%20Part%2058"
        ),
    ),
    MethodologyReference(
        reference_code="epa_aqi_tad_2026",
        title=(
            "Technical Assistance Document for the Reporting of Daily Air "
            "Quality – the Air Quality Index (AQI)"
        ),
        document_number="EPA-403/B-26-003",
        publication_date="2026-05",
        section="Section IV and Table 6",
        url=(
            "https://document.airnow.gov/"
            "technical-assistance-document-for-the-reporting-of-daily-air-quailty.pdf"
        ),
    ),
    MethodologyReference(
        reference_code="epa_aqi_tad_2024",
        title=(
            "Technical Assistance Document for the Reporting of Daily Air "
            "Quality – the Air Quality Index (AQI)"
        ),
        document_number="EPA-454/B-24-002",
        publication_date="2024-05",
        section="Section IV and Table 6",
        url=(
            "https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P101AP0Q.txt"
        ),
    ),
    MethodologyReference(
        reference_code="2024_pm_naaqs_final_rule",
        title=(
            "Reconsideration of the National Ambient Air Quality Standards "
            "for Particulate Matter"
        ),
        document_number="89 FR 16202",
        publication_date="2024-03-06",
        section="Section IV.B.3",
        url=(
            "https://www.epa.gov/system/files/documents/2024-04/"
            "2024-pm-naaqs-fr-published.pdf"
        ),
    ),
)

PM25_DAILY_COMPLETENESS_REFERENCE = MethodologyReference(
    reference_code="40_cfr_50_appendix_n",
    title=(
        "Interpretation of the National Ambient Air Quality Standards for PM2.5"
    ),
    document_number="40 CFR Part 50, Appendix N",
    publication_date=None,
    section="Sections 1.0 and 3.0(b)-(c)",
    url=(
        "https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/"
        "part-50/appendix-Appendix%20N%20to%20Part%2050"
    ),
)

PM10_DAILY_COMPLETENESS_REFERENCE = MethodologyReference(
    reference_code="40_cfr_50_appendix_k",
    title=(
        "Interpretation of the National Ambient Air Quality Standards for PM10"
    ),
    document_number="40 CFR Part 50, Appendix K",
    publication_date=None,
    section="Sections 1.0 and 2.3(d)",
    url=(
        "https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/"
        "part-50/appendix-Appendix%20K%20to%20Part%2050"
    ),
)

OZONE_8_HOUR_COMPLETENESS_REFERENCE = MethodologyReference(
    reference_code="40_cfr_50_appendix_u",
    title=(
        "Interpretation of the Primary and Secondary National Ambient Air "
        "Quality Standards for Ozone"
    ),
    document_number="40 CFR Part 50, Appendix U",
    publication_date=None,
    section="Sections 2.1, 2.2, and 3",
    url=(
        "https://www.govinfo.gov/content/pkg/CFR-2025-title40-vol2/pdf/"
        "CFR-2025-title40-vol2.pdf"
    ),
)

CARBON_MONOXIDE_METHODOLOGY_REFERENCES = (
    METHODOLOGY_REFERENCES[0],
    METHODOLOGY_REFERENCES[1],
    MethodologyReference(
        reference_code="40_cfr_50_8",
        title="National Primary Ambient Air Quality Standards for Carbon Monoxide",
        document_number="40 CFR 50.8",
        publication_date=None,
        section="Paragraph (a)(1)",
        url=(
            "https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/"
            "part-50/section-50.8"
        ),
    ),
    MethodologyReference(
        reference_code="1999_aqi_final_rule",
        title="Reporting of Daily Air Quality—Air Quality Index (AQI)",
        document_number="64 FR 42530",
        publication_date="1999-08-04",
        section="Final rule",
        url="https://www.govinfo.gov/app/details/FR-1999-08-04/99-19433",
    ),
)

NITROGEN_DIOXIDE_METHODOLOGY_REFERENCES = (
    METHODOLOGY_REFERENCES[0],
    METHODOLOGY_REFERENCES[1],
    MethodologyReference(
        reference_code="40_cfr_50_appendix_s",
        title=(
            "Interpretation of the Primary National Ambient Air Quality "
            "Standards for Oxides of Nitrogen"
        ),
        document_number="40 CFR Part 50, Appendix S",
        publication_date=None,
        section="Sections 2 and 3",
        url=(
            "https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/"
            "part-50/appendix-Appendix%20S%20to%20Part%2050"
        ),
    ),
    MethodologyReference(
        reference_code="2010_no2_naaqs_final_rule",
        title="Primary National Ambient Air Quality Standards for Nitrogen Dioxide",
        document_number="75 FR 6474",
        publication_date="2010-02-09",
        section="Final rule",
        url=(
            "https://www.govinfo.gov/content/pkg/FR-2010-02-09/"
            "pdf/2010-1990.pdf"
        ),
    ),
)

SULFUR_DIOXIDE_METHODOLOGY_REFERENCES = (
    METHODOLOGY_REFERENCES[0],
    METHODOLOGY_REFERENCES[1],
    MethodologyReference(
        reference_code="40_cfr_50_appendix_t",
        title=(
            "Interpretation of the Primary National Ambient Air Quality "
            "Standards for Oxides of Sulfur"
        ),
        document_number="40 CFR Part 50, Appendix T",
        publication_date=None,
        section="Sections 2 and 3",
        url=(
            "https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/"
            "part-50/appendix-Appendix%20T%20to%20Part%2050"
        ),
    ),
    MethodologyReference(
        reference_code="2010_so2_naaqs_final_rule",
        title="Primary National Ambient Air Quality Standard for Sulfur Dioxide",
        document_number="75 FR 35520",
        publication_date="2010-06-22",
        section="Final rule",
        url=(
            "https://www.govinfo.gov/content/pkg/FR-2010-06-22/"
            "pdf/2010-13947.pdf"
        ),
    ),
)

OZONE_2015_STANDARD_REFERENCE = MethodologyReference(
    reference_code="2015_ozone_naaqs_final_rule",
    title=(
        "National Ambient Air Quality Standards for Ozone; Final Rule"
    ),
    document_number="80 FR 65292",
    publication_date="2015-10-26",
    section="AQI breakpoint revisions effective December 28, 2015",
    url=(
        "https://www.epa.gov/ground-level-ozone-pollution/"
        "2015-revision-2008-ozone-national-ambient-air-quality-standards-naaqs"
    ),
)

OZONE_METHODOLOGY_REFERENCES = (
    METHODOLOGY_REFERENCES[0],
    METHODOLOGY_REFERENCES[1],
    OZONE_2015_STANDARD_REFERENCE,
    OZONE_8_HOUR_COMPLETENESS_REFERENCE,
)

PM25_COMPLETED_DAY_METHODOLOGY_REFERENCES = (
    *METHODOLOGY_REFERENCES,
    PM25_DAILY_COMPLETENESS_REFERENCE,
)

PM10_COMPLETED_DAY_METHODOLOGY_REFERENCES = (
    *METHODOLOGY_REFERENCES,
    PM10_DAILY_COMPLETENESS_REFERENCE,
)


CATEGORIES = (
    IndexCategory("good", "Good", 1, "#00E400", 0, 50),
    IndexCategory("moderate", "Moderate", 2, "#FFFF00", 51, 100),
    IndexCategory(
        "unhealthy_for_sensitive_groups",
        "Unhealthy for Sensitive Groups",
        3,
        "#FF7E00",
        101,
        150,
    ),
    IndexCategory("unhealthy", "Unhealthy", 4, "#FF0000", 151, 200),
    IndexCategory("very_unhealthy", "Very Unhealthy", 5, "#8F3F97", 201, 300),
    IndexCategory("hazardous", "Hazardous", 6, "#7E0023", 301, 500),
)


def _breakpoint(
    concentration_low: str,
    concentration_high: str,
    aqi_low: int,
    aqi_high: int,
) -> Breakpoint:
    return Breakpoint(
        Decimal(concentration_low),
        Decimal(concentration_high),
        aqi_low,
        aqi_high,
    )


PM25_24_HOUR_BREAKPOINTS = (
    _breakpoint("0.0", "9.0", 0, 50),
    _breakpoint("9.1", "35.4", 51, 100),
    _breakpoint("35.5", "55.4", 101, 150),
    _breakpoint("55.5", "125.4", 151, 200),
    _breakpoint("125.5", "225.4", 201, 300),
    _breakpoint("225.5", "325.4", 301, 500),
)

PM10_24_HOUR_BREAKPOINTS = (
    _breakpoint("0", "54", 0, 50),
    _breakpoint("55", "154", 51, 100),
    _breakpoint("155", "254", 101, 150),
    _breakpoint("255", "354", 151, 200),
    _breakpoint("355", "424", 201, 300),
    _breakpoint("425", "604", 301, 500),
)

OZONE_8_HOUR_BREAKPOINTS = (
    _breakpoint("0.000", "0.054", 0, 50),
    _breakpoint("0.055", "0.070", 51, 100),
    _breakpoint("0.071", "0.085", 101, 150),
    _breakpoint("0.086", "0.105", 151, 200),
    _breakpoint("0.106", "0.200", 201, 300),
)

OZONE_1_HOUR_BREAKPOINTS = (
    _breakpoint("0.125", "0.164", 101, 150),
    _breakpoint("0.165", "0.204", 151, 200),
    _breakpoint("0.205", "0.404", 201, 300),
    _breakpoint("0.405", "0.604", 301, 500),
)

CO_8_HOUR_BREAKPOINTS = (
    _breakpoint("0.0", "4.4", 0, 50),
    _breakpoint("4.5", "9.4", 51, 100),
    _breakpoint("9.5", "12.4", 101, 150),
    _breakpoint("12.5", "15.4", 151, 200),
    _breakpoint("15.5", "30.4", 201, 300),
    _breakpoint("30.5", "50.4", 301, 500),
)

SO2_1_HOUR_LOW_BREAKPOINTS = (
    _breakpoint("0", "35", 0, 50),
    _breakpoint("36", "75", 51, 100),
    _breakpoint("76", "185", 101, 150),
    _breakpoint("186", "304", 151, 200),
)

SO2_24_HOUR_HIGH_BREAKPOINTS = (
    _breakpoint("305", "604", 201, 300),
    _breakpoint("605", "1004", 301, 500),
)

NO2_1_HOUR_BREAKPOINTS = (
    _breakpoint("0", "53", 0, 50),
    _breakpoint("54", "100", 51, 100),
    _breakpoint("101", "360", 101, 150),
    _breakpoint("361", "649", 151, 200),
    _breakpoint("650", "1249", 201, 300),
    _breakpoint("1250", "2049", 301, 500),
)


COMPONENT_DEFINITIONS = {
    "pm25_24_hour": ComponentDefinition(
        "pm25_24_hour",
        "pm25",
        "µg/m³",
        1,
        PM25_24_HOUR_BREAKPOINTS,
    ),
    "pm10_24_hour": ComponentDefinition(
        "pm10_24_hour",
        "pm10",
        "µg/m³",
        0,
        PM10_24_HOUR_BREAKPOINTS,
    ),
    "o3_8_hour": ComponentDefinition(
        "o3_8_hour",
        "o3",
        "ppm",
        3,
        OZONE_8_HOUR_BREAKPOINTS,
        allow_above_500=False,
        above_last_breakpoint_reason=(
            ExclusionReason.OZONE_8_HOUR_NOT_APPLICABLE
        ),
    ),
    "o3_1_hour": ComponentDefinition(
        "o3_1_hour",
        "o3",
        "ppm",
        3,
        OZONE_1_HOUR_BREAKPOINTS,
        below_first_breakpoint_reason=(
            ExclusionReason.OZONE_1_HOUR_NOT_APPLICABLE
        ),
    ),
    "co_8_hour": ComponentDefinition(
        "co_8_hour",
        "co",
        "ppm",
        1,
        CO_8_HOUR_BREAKPOINTS,
    ),
    "so2_1_hour_low": ComponentDefinition(
        "so2_1_hour_low",
        "so2",
        "ppb",
        0,
        SO2_1_HOUR_LOW_BREAKPOINTS,
        allow_above_500=False,
        above_last_breakpoint_reason=(
            ExclusionReason.SO2_1_HOUR_NOT_APPLICABLE
        ),
    ),
    "so2_24_hour_high": ComponentDefinition(
        "so2_24_hour_high",
        "so2",
        "ppb",
        0,
        SO2_24_HOUR_HIGH_BREAKPOINTS,
        below_first_breakpoint_reason=ExclusionReason.SO2_24_HOUR_NOT_APPLICABLE,
    ),
    "no2_1_hour": ComponentDefinition(
        "no2_1_hour",
        "no2",
        "ppb",
        0,
        NO2_1_HOUR_BREAKPOINTS,
    ),
}


US_EPA_PRODUCTS = (
    AirQualityIndexProduct(
        product_code=DEFAULT_PRODUCT_CODE,
        display_name="PM2.5 NowCast AQI",
        parameter_code="pm25",
        calculation_code="pm_nowcast",
        aggregation_period="12h_nowcast",
        aggregation_display_name="NowCast from 12 completed hourly slots",
        result_scope="pollutant",
        is_parameter_default=True,
        product_kind="nowcast",
        methodology_code=METHODOLOGY_CODE,
        methodology_revision=METHODOLOGY_REVISION,
        methodology_effective_date=PM25_BREAKPOINT_EFFECTIVE_DATE,
        methodology_references=METHODOLOGY_REFERENCES,
        limitations=(
            "Regulatory-monitor qualification is not evaluated.",
            "Hourly inputs require verified frequency/duration metadata or "
            "verified provider-hourly provenance and known timestamp semantics.",
            "Provider-receipt expected-position assignment is CompassAQ "
            "application provenance, not an EPA-prescribed method.",
        ),
    ),
    AirQualityIndexProduct(
        product_code="us_epa.pm10.nowcast",
        display_name="PM10 NowCast AQI",
        parameter_code="pm10",
        calculation_code="pm_nowcast",
        aggregation_period="12h_nowcast",
        aggregation_display_name="NowCast from 12 completed hourly slots",
        result_scope="pollutant",
        is_parameter_default=True,
        product_kind="nowcast",
        methodology_code=METHODOLOGY_CODE,
        methodology_revision=METHODOLOGY_REVISION,
        methodology_effective_date="2014-12-09",
        methodology_references=METHODOLOGY_REFERENCES,
        limitations=(
            "Regulatory-monitor qualification is not evaluated.",
            "Hourly inputs require verified frequency/duration metadata or "
            "verified provider-hourly provenance and known timestamp semantics.",
            "Provider-receipt expected-position assignment is CompassAQ "
            "application provenance, not an EPA-prescribed method.",
        ),
    ),
    AirQualityIndexProduct(
        product_code="us_epa.o3.latest",
        display_name="Ozone AQI",
        parameter_code="o3",
        calculation_code="ozone_latest_completed_window",
        aggregation_period="latest_completed_window",
        aggregation_display_name="Latest completed window",
        result_scope="pollutant",
        is_parameter_default=True,
        product_kind="latest_window",
        methodology_code=METHODOLOGY_CODE,
        methodology_revision="2015-12",
        methodology_effective_date=OZONE_BREAKPOINT_EFFECTIVE_DATE,
        methodology_references=OZONE_METHODOLOGY_REFERENCES,
        limitations=(
            "This is a site-level informational AQI for the latest completed "
            "eight-hour UTC window.",
            "CompassAQ evaluates both the applicable eight-hour AQI and the "
            "maximum eligible one-hour concentration within that same window, "
            "then selects the higher applicable AQI.",
            "Evaluating the one-hour candidate at every site is a precautionary "
            "CompassAQ informational policy; it does not claim that official "
            "EPA reporting areas universally use one-hour ozone AQI.",
            "This is not EPA O3 NowCast, a completed-day or reporting-area "
            "AQI, a regulatory design value, or a compliance determination.",
            "Sensors are selected by metadata quality, candidate availability, "
            "coverage, valid-hour count, and stable sensor ID, never by AQI "
            "magnitude.",
            "Regulatory-monitor qualification is not evaluated.",
        ),
    ),
    AirQualityIndexProduct(
        product_code="us_epa.co.latest",
        display_name="Carbon Monoxide AQI",
        parameter_code="co",
        calculation_code="co_latest_completed_8_hour_window",
        aggregation_period="latest_completed_8_hour_window",
        aggregation_display_name="Latest completed 8-hour window",
        result_scope="pollutant",
        is_parameter_default=True,
        product_kind="latest_window",
        methodology_code=METHODOLOGY_CODE,
        methodology_revision="1999-08",
        methodology_effective_date="1999-10-04",
        methodology_references=CARBON_MONOXIDE_METHODOLOGY_REFERENCES,
        limitations=(
            "This is a site-level informational AQI for the latest completed "
            "eight-hour UTC window.",
            "This is not the daily maximum eight-hour or reporting-area AQI, "
            "a regulatory design value, or a compliance determination.",
            "Six, seven, or eight eligible hourly concentrations are averaged "
            "without zero substitution.",
            "Sensors are selected by metadata quality and coverage, never by "
            "AQI magnitude.",
            "Regulatory-monitor qualification is not evaluated.",
        ),
    ),
    AirQualityIndexProduct(
        product_code="us_epa.no2.latest",
        display_name="Nitrogen Dioxide AQI",
        parameter_code="no2",
        calculation_code="no2_latest_completed_hour",
        aggregation_period="latest_completed_hour",
        aggregation_display_name="Latest completed hour",
        result_scope="pollutant",
        is_parameter_default=True,
        product_kind="latest_window",
        methodology_code=METHODOLOGY_CODE,
        methodology_revision="2010-02",
        methodology_effective_date="2010-04-12",
        methodology_references=NITROGEN_DIOXIDE_METHODOLOGY_REFERENCES,
        limitations=(
            "This is a site-level informational AQI for the latest completed "
            "UTC hour.",
            "This is not the daily maximum one-hour or reporting-area AQI, a "
            "regulatory design value, or a compliance determination.",
            "The current incomplete hour is excluded and CompassAQ does not "
            "search backward for an older eligible hour.",
            "Sensors are selected by metadata quality and coverage, never by "
            "AQI magnitude.",
            "Regulatory-monitor qualification is not evaluated.",
        ),
    ),
    AirQualityIndexProduct(
        product_code="us_epa.so2.latest",
        display_name="Sulfur Dioxide AQI",
        parameter_code="so2",
        calculation_code="so2_latest_completed_24_hour_window",
        aggregation_period="latest_completed_24_hour_window",
        aggregation_display_name="Latest completed 24-hour evaluation window",
        result_scope="pollutant",
        is_parameter_default=True,
        product_kind="latest_window",
        methodology_code=METHODOLOGY_CODE,
        methodology_revision="2010-06",
        methodology_effective_date="2010-08-23",
        methodology_references=SULFUR_DIOXIDE_METHODOLOGY_REFERENCES,
        limitations=(
            "This is a site-level informational AQI evaluated over the latest "
            "24 completed UTC hours.",
            "The trailing UTC window is a CompassAQ application policy and is "
            "not EPA's completed local-standard-time day.",
            "CompassAQ requires at least 18 eligible hourly concentrations "
            "before selecting the applicable one-hour, 24-hour, or capped "
            "AQI 200 basis.",
            "This is not a reporting-area AQI, regulatory design value, or "
            "compliance determination.",
            "Sensors are selected by metadata quality and coverage, never by "
            "AQI magnitude.",
            "Regulatory-monitor qualification is not evaluated.",
        ),
    ),
    AirQualityIndexProduct(
        product_code="us_epa.pm25.completed_day",
        display_name="U.S. EPA PM2.5 Completed-Day AQI",
        parameter_code="pm25",
        calculation_code="pm_completed_local_day",
        aggregation_period="completed_local_day",
        aggregation_display_name="Completed Day",
        result_scope="pollutant",
        product_kind="completed_day",
        history_interval="represented_device_local_date",
        maximum_history_interval_count=366,
        methodology_code=METHODOLOGY_CODE,
        methodology_revision=METHODOLOGY_REVISION,
        methodology_effective_date=PM25_BREAKPOINT_EFFECTIVE_DATE,
        methodology_references=PM25_COMPLETED_DAY_METHODOLOGY_REFERENCES,
        limitations=(
            "Requires a valid device IANA timezone.",
            "CompassAQ applies the 75-percent daily rule to the actual 23-, "
            "24-, or 25-hour local day; this does not qualify a low-cost "
            "sensor as a regulatory monitor.",
            "Regulatory exceptional-event, zero-substitution, and collocated-"
            "monitor rules are not evaluated.",
        ),
    ),
    AirQualityIndexProduct(
        product_code="us_epa.pm10.completed_day",
        display_name="U.S. EPA PM10 Completed-Day AQI",
        parameter_code="pm10",
        calculation_code="pm_completed_local_day",
        aggregation_period="completed_local_day",
        aggregation_display_name="Completed Day",
        result_scope="pollutant",
        product_kind="completed_day",
        history_interval="represented_device_local_date",
        maximum_history_interval_count=366,
        methodology_code=METHODOLOGY_CODE,
        methodology_revision=METHODOLOGY_REVISION,
        methodology_effective_date="2014-12-09",
        methodology_references=PM10_COMPLETED_DAY_METHODOLOGY_REFERENCES,
        limitations=(
            "Requires a valid device IANA timezone.",
            "CompassAQ applies the 75-percent daily rule to the actual 23-, "
            "24-, or 25-hour local day; this does not qualify a low-cost "
            "sensor as a regulatory monitor.",
            "Regulatory exceptional-event, zero-substitution, and collocated-"
            "monitor rules are not evaluated.",
        ),
    ),
)


US_EPA_STANDARD = AirQualityIndexStandard(
    code=STANDARD_CODE,
    display_name=DISPLAY_NAME,
    methodology_version=METHODOLOGY_VERSION,
    result_kind=ResultKind.NUMERIC,
    averaging_minutes=60,
    pollutants=("pm25", "pm10", "o3", "co", "no2", "so2"),
    categories=CATEGORIES,
    products=US_EPA_PRODUCTS,
    default_product_code=DEFAULT_PRODUCT_CODE,
    is_default=True,
    methodology_code=METHODOLOGY_CODE,
    methodology_revision=METHODOLOGY_REVISION,
    methodology_effective_date=PM25_BREAKPOINT_EFFECTIVE_DATE,
    methodology_references=METHODOLOGY_REFERENCES,
    limitations=(
        "PM NowCast, completed-local-day PM, latest-window ozone, and "
        "latest-window gas products are separate calculations.",
        "Reporting-area AQI is not implemented.",
        "Regulatory-monitor qualification is not evaluated.",
    ),
)


def get_product(product_code: str) -> Optional[AirQualityIndexProduct]:
    normalized_code = str(product_code or "").strip().lower()
    return next(
        (
            product
            for product in US_EPA_PRODUCTS
            if product.product_code == normalized_code
        ),
        None,
    )


def _decimal_from_concentration(concentration: object) -> Optional[Decimal]:
    if isinstance(concentration, bool):
        return None
    if isinstance(concentration, Decimal):
        numeric_value = concentration
    elif isinstance(concentration, Real):
        numeric_float = float(concentration)
        if not math.isfinite(numeric_float):
            return None
        numeric_value = Decimal(str(concentration))
    else:
        return None
    if not numeric_value.is_finite() or numeric_value < 0:
        return None
    return numeric_value


def _canonical_unit(unit: object) -> Optional[str]:
    if unit is None:
        return None
    value = str(unit).strip().lower()
    if not value:
        return None
    value = value.replace("μ", "u").replace("µ", "u")
    value = value.replace("³", "3").replace("^3", "3")
    value = value.replace(" ", "").replace("/", "_")
    aliases = {
        "ug_m3": "ug_m3",
        "ugm3": "ug_m3",
        "mg_m3": "mg_m3",
        "mgm3": "mg_m3",
        "ppm": "ppm",
        "ppb": "ppb",
    }
    return aliases.get(value)


def normalize_concentration_unit(
    parameter_code: str,
    concentration: object,
    input_unit: object,
) -> UnitNormalizationResult:
    """Normalize exact supported units without physical-condition assumptions."""
    parameter = str(parameter_code or "").strip().lower()
    decimal_concentration = _decimal_from_concentration(concentration)
    if decimal_concentration is None:
        return UnitNormalizationResult(
            None,
            None,
            ExclusionReason.INVALID_CONCENTRATION,
        )

    unit = _canonical_unit(input_unit)
    if unit is None:
        return UnitNormalizationResult(
            None,
            None,
            ExclusionReason.UNSUPPORTED_UNIT,
        )

    if parameter in {"pm25", "pm10"}:
        if unit == "ug_m3":
            return UnitNormalizationResult(decimal_concentration, "µg/m³", None)
        if unit == "mg_m3":
            return UnitNormalizationResult(
                decimal_concentration * Decimal("1000"),
                "µg/m³",
                None,
            )
        return UnitNormalizationResult(
            None,
            None,
            ExclusionReason.CONVERSION_NOT_SUPPORTED,
        )

    if parameter in {"o3", "co"}:
        if unit == "ppm":
            return UnitNormalizationResult(decimal_concentration, "ppm", None)
        if unit == "ppb":
            return UnitNormalizationResult(
                decimal_concentration / Decimal("1000"),
                "ppm",
                None,
            )
        if unit in {"ug_m3", "mg_m3"}:
            return UnitNormalizationResult(
                None,
                None,
                ExclusionReason.CONVERSION_NOT_SUPPORTED,
            )

    if parameter in {"no2", "so2"}:
        if unit == "ppb":
            return UnitNormalizationResult(decimal_concentration, "ppb", None)
        if unit == "ppm":
            return UnitNormalizationResult(
                decimal_concentration * Decimal("1000"),
                "ppb",
                None,
            )
        if unit in {"ug_m3", "mg_m3"}:
            return UnitNormalizationResult(
                None,
                None,
                ExclusionReason.CONVERSION_NOT_SUPPORTED,
            )

    return UnitNormalizationResult(
        None,
        None,
        ExclusionReason.UNSUPPORTED_POLLUTANT,
    )


def truncate_concentration(
    concentration: Decimal,
    decimal_places: int,
) -> Decimal:
    """Truncate a validated non-negative concentration toward zero."""
    quantum = Decimal("1").scaleb(-decimal_places)
    return concentration.quantize(quantum, rounding=ROUND_DOWN)


def round_aqi_to_nearest_integer(aqi_value: Decimal) -> int:
    """Apply EPA nearest-integer rounding with half values rounded upward."""
    return int(aqi_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def interpolate_aqi(
    preprocessed_concentration: Decimal,
    breakpoint: Breakpoint,
) -> int:
    concentration_span = (
        breakpoint.concentration_high - breakpoint.concentration_low
    )
    aqi_span = Decimal(breakpoint.aqi_high - breakpoint.aqi_low)
    interpolated = (
        aqi_span
        / concentration_span
        * (preprocessed_concentration - breakpoint.concentration_low)
        + Decimal(breakpoint.aqi_low)
    )
    return round_aqi_to_nearest_integer(interpolated)


def category_for_aqi(aqi_value: int) -> IndexCategory:
    if aqi_value <= 50:
        return CATEGORIES[0]
    if aqi_value <= 100:
        return CATEGORIES[1]
    if aqi_value <= 150:
        return CATEGORIES[2]
    if aqi_value <= 200:
        return CATEGORIES[3]
    if aqi_value <= 300:
        return CATEGORIES[4]
    return CATEGORIES[5]


def _unavailable_result(
    parameter_code: str,
    component_code: str,
    reason: ExclusionReason,
    *,
    coverage_status: CoverageStatus = CoverageStatus.NONE,
    normalized_concentration: Optional[Decimal] = None,
    normalized_unit: Optional[str] = None,
    expected_observation_count: int = 1,
    valid_observation_count: int = 0,
) -> UsEpaCalculationResult:
    return UsEpaCalculationResult(
        parameter_code=parameter_code,
        component_code=component_code,
        calculation_status=CalculationStatus.UNAVAILABLE,
        coverage_status=coverage_status,
        exclusion_reason=reason,
        normalized_concentration=(
            float(normalized_concentration)
            if normalized_concentration is not None
            else None
        ),
        normalized_unit=normalized_unit,
        preprocessed_concentration=None,
        numeric_value=None,
        category_code=None,
        category_label=None,
        internal_severity_rank=None,
        aqi_scale_status=None,
        expected_observation_count=expected_observation_count,
        valid_observation_count=valid_observation_count,
    )


def calculate_component_aqi(
    parameter_code: str,
    component_code: str,
    concentration: object,
    input_unit: object,
    *,
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
    expected_observation_count: int = 1,
    valid_observation_count: int = 1,
) -> UsEpaCalculationResult:
    """Calculate one EPA pollutant component from an averaged concentration."""
    definition = COMPONENT_DEFINITIONS.get(component_code)
    normalized_parameter = str(parameter_code or "").strip().lower()
    if definition is None or definition.parameter_code != normalized_parameter:
        return _unavailable_result(
            normalized_parameter,
            component_code,
            ExclusionReason.UNSUPPORTED_PRODUCT,
            expected_observation_count=expected_observation_count,
            valid_observation_count=valid_observation_count,
        )

    normalization = normalize_concentration_unit(
        normalized_parameter,
        concentration,
        input_unit,
    )
    if not normalization.is_supported:
        return _unavailable_result(
            normalized_parameter,
            component_code,
            normalization.exclusion_reason or ExclusionReason.UNSUPPORTED_UNIT,
            coverage_status=coverage_status,
            expected_observation_count=expected_observation_count,
            valid_observation_count=valid_observation_count,
        )

    normalized_concentration = normalization.normalized_concentration
    if normalized_concentration is None:
        return _unavailable_result(
            normalized_parameter,
            component_code,
            ExclusionReason.INVALID_CONCENTRATION,
            coverage_status=coverage_status,
            expected_observation_count=expected_observation_count,
            valid_observation_count=valid_observation_count,
        )

    preprocessed = truncate_concentration(
        normalized_concentration,
        definition.truncation_decimal_places,
    )
    breakpoint = next(
        (
            candidate
            for candidate in definition.breakpoints
            if (
                candidate.concentration_low
                <= preprocessed
                <= candidate.concentration_high
            )
        ),
        None,
    )
    if breakpoint is None:
        first = definition.breakpoints[0]
        last = definition.breakpoints[-1]
        if preprocessed < first.concentration_low:
            return _unavailable_result(
                normalized_parameter,
                component_code,
                definition.below_first_breakpoint_reason
                or ExclusionReason.INVALID_CONCENTRATION,
                coverage_status=coverage_status,
                normalized_concentration=normalized_concentration,
                normalized_unit=normalization.normalized_unit,
                expected_observation_count=expected_observation_count,
                valid_observation_count=valid_observation_count,
            )
        if preprocessed > last.concentration_high:
            if not definition.allow_above_500:
                return _unavailable_result(
                    normalized_parameter,
                    component_code,
                    definition.above_last_breakpoint_reason
                    or ExclusionReason.COMPLETED_DAY_METHODOLOGY_NOT_IMPLEMENTED,
                    coverage_status=coverage_status,
                    normalized_concentration=normalized_concentration,
                    normalized_unit=normalization.normalized_unit,
                    expected_observation_count=expected_observation_count,
                    valid_observation_count=valid_observation_count,
                )
            breakpoint = last

    if breakpoint is None:
        return _unavailable_result(
            normalized_parameter,
            component_code,
            ExclusionReason.INVALID_CONCENTRATION,
            coverage_status=coverage_status,
            normalized_concentration=normalized_concentration,
            normalized_unit=normalization.normalized_unit,
            expected_observation_count=expected_observation_count,
            valid_observation_count=valid_observation_count,
        )

    numeric_value = interpolate_aqi(preprocessed, breakpoint)
    category = category_for_aqi(numeric_value)
    scale_status = (
        AqiScaleStatus.ABOVE_500
        if numeric_value > 500
        else AqiScaleStatus.WITHIN_0_TO_500
    )
    return UsEpaCalculationResult(
        parameter_code=normalized_parameter,
        component_code=component_code,
        calculation_status=CalculationStatus.CALCULATED,
        coverage_status=coverage_status,
        exclusion_reason=None,
        normalized_concentration=float(normalized_concentration),
        normalized_unit=normalization.normalized_unit,
        preprocessed_concentration=float(preprocessed),
        numeric_value=numeric_value,
        category_code=category.code,
        category_label=category.label,
        internal_severity_rank=category.internal_severity_rank,
        aqi_scale_status=scale_status,
        expected_observation_count=expected_observation_count,
        valid_observation_count=valid_observation_count,
    )


def calculate_pm_nowcast(
    parameter_code: str,
    hourly_concentrations: Sequence[object | None],
    input_unit: object,
) -> UsEpaCalculationResult:
    """Calculate PM NowCast from 12 most-recent-first positional hour slots."""
    parameter = str(parameter_code or "").strip().lower()
    component_code = {
        "pm25": "pm25_24_hour",
        "pm10": "pm10_24_hour",
    }.get(parameter)
    if component_code is None:
        return _unavailable_result(
            parameter,
            "pm_nowcast",
            ExclusionReason.UNSUPPORTED_POLLUTANT,
            expected_observation_count=12,
        )

    slots = list(hourly_concentrations[:12])
    if len(slots) < 12:
        slots.extend([None] * (12 - len(slots)))

    normalized_slots: list[Optional[Decimal]] = []
    normalized_unit: Optional[str] = None
    for concentration in slots:
        if concentration is None:
            normalized_slots.append(None)
            continue
        normalization = normalize_concentration_unit(
            parameter,
            concentration,
            input_unit,
        )
        if not normalization.is_supported:
            return _unavailable_result(
                parameter,
                component_code,
                normalization.exclusion_reason
                or ExclusionReason.UNSUPPORTED_UNIT,
                coverage_status=CoverageStatus.PARTIAL,
                expected_observation_count=12,
                valid_observation_count=sum(
                    value is not None for value in normalized_slots
                ),
            )
        normalized_slots.append(normalization.normalized_concentration)
        normalized_unit = normalization.normalized_unit

    valid_count = sum(value is not None for value in normalized_slots)
    recent_valid_count = sum(
        value is not None for value in normalized_slots[:3]
    )
    coverage_status = (
        CoverageStatus.COMPLETE
        if valid_count == 12
        else CoverageStatus.PARTIAL if valid_count else CoverageStatus.NONE
    )
    if valid_count == 0:
        return _unavailable_result(
            parameter,
            component_code,
            ExclusionReason.MISSING_MEASUREMENTS,
            expected_observation_count=12,
        )
    if recent_valid_count < 2:
        return _unavailable_result(
            parameter,
            component_code,
            ExclusionReason.INSUFFICIENT_RECENT_HOURS,
            coverage_status=coverage_status,
            expected_observation_count=12,
            valid_observation_count=valid_count,
        )

    valid_values = tuple(
        value for value in normalized_slots if value is not None
    )
    maximum = max(valid_values)
    minimum = min(valid_values)
    weight_factor = (
        Decimal("1")
        if maximum == 0
        else max(Decimal("0.5"), minimum / maximum)
    )

    weighted_sum = Decimal("0")
    weight_sum = Decimal("0")
    for hours_ago, concentration in enumerate(normalized_slots):
        if concentration is None:
            continue
        positional_weight = weight_factor ** hours_ago
        weighted_sum += concentration * positional_weight
        weight_sum += positional_weight
    nowcast_concentration = weighted_sum / weight_sum

    result = calculate_component_aqi(
        parameter,
        component_code,
        nowcast_concentration,
        normalized_unit,
        coverage_status=coverage_status,
        expected_observation_count=12,
        valid_observation_count=valid_count,
    )
    return UsEpaCalculationResult(
        parameter_code=result.parameter_code,
        component_code=result.component_code,
        calculation_status=result.calculation_status,
        coverage_status=result.coverage_status,
        exclusion_reason=result.exclusion_reason,
        normalized_concentration=result.normalized_concentration,
        normalized_unit=result.normalized_unit,
        preprocessed_concentration=result.preprocessed_concentration,
        numeric_value=result.numeric_value,
        category_code=result.category_code,
        category_label=result.category_label,
        internal_severity_rank=result.internal_severity_rank,
        aqi_scale_status=result.aqi_scale_status,
        expected_observation_count=result.expected_observation_count,
        valid_observation_count=result.valid_observation_count,
        nowcast_weight_factor=float(weight_factor),
    )
