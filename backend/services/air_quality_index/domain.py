from __future__ import annotations

"""Shared, transport-independent domain types for air-quality indices."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class ResultKind(str, Enum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class CoverageState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NONE = "none"


class DisplayQualification(str, Enum):
    NOT_EVALUATED = "not_evaluated"


class ExclusionReason(str, Enum):
    UNSUPPORTED_POLLUTANT = "unsupported_pollutant"
    UNSUPPORTED_UNIT = "unsupported_unit"
    UNSUPPORTED_AGGREGATION_PERIOD = "unsupported_aggregation_period"
    UNSUPPORTED_PRODUCT = "unsupported_product"
    CONVERSION_NOT_SUPPORTED = "conversion_not_supported"
    INVALID_CONCENTRATION = "invalid_concentration"
    INSUFFICIENT_RECENT_HOURS = "insufficient_recent_hours"
    INCOMPLETE_HOUR = "incomplete_hour"
    MISSING_MEASUREMENTS = "missing_measurements"
    HOURLY_CONCENTRATION_NOT_AVAILABLE = "hourly_concentration_not_available"
    HOURLY_AGGREGATION_PROVENANCE_MISSING = (
        "hourly_aggregation_provenance_missing"
    )
    HOURLY_COMPLETENESS_NOT_MET = "hourly_completeness_not_met"
    UNSUPPORTED_INPUT_AGGREGATION_PERIOD = (
        "unsupported_input_aggregation_period"
    )
    UNSUPPORTED_INPUT_FREQUENCY = "unsupported_input_frequency"
    EXPECTED_FREQUENCY_MISSING = "expected_frequency_missing"
    UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION = (
        "unsupported_pollutant_duration_frequency_combination"
    )
    TIMESTAMP_SEMANTICS_UNKNOWN = "timestamp_semantics_unknown"
    DUPLICATE_OBSERVATION_INTERVAL = "duplicate_observation_interval"
    OFF_FREQUENCY_OBSERVATIONS = "off_frequency_observations"
    NO_VALID_OBSERVATIONS = "no_valid_observations"
    NO_ELIGIBLE_SENSOR_STREAM = "no_eligible_sensor_stream"
    DEVICE_TIMEZONE_MISSING = "device_timezone_missing"
    DEVICE_TIMEZONE_INVALID = "device_timezone_invalid"
    COMPLETED_LOCAL_DAY_NOT_AVAILABLE = "completed_local_day_not_available"
    DAILY_COMPLETENESS_NOT_MET = "daily_completeness_not_met"
    NO_VALID_HOURLY_CONCENTRATIONS = "no_valid_hourly_concentrations"
    UNSUPPORTED_DAILY_POLLUTANT = "unsupported_daily_pollutant"
    UNSUPPORTED_DAILY_METHODOLOGY = "unsupported_daily_methodology"
    COMPLETED_DAY_METHODOLOGY_NOT_IMPLEMENTED = (
        "completed_day_methodology_not_implemented"
    )
    OZONE_1_HOUR_NOT_APPLICABLE = "ozone_1_hour_not_applicable"
    OZONE_8_HOUR_NOT_APPLICABLE = "ozone_8_hour_not_applicable"
    ROLLING_8_HOUR_COMPLETENESS_NOT_MET = (
        "rolling_8_hour_completeness_not_met"
    )
    ROLLING_24_HOUR_COMPLETENESS_NOT_MET = (
        "rolling_24_hour_completeness_not_met"
    )
    NO_APPLICABLE_OZONE_CANDIDATE = "no_applicable_ozone_candidate"
    SO2_1_HOUR_NOT_APPLICABLE = "so2_1_hour_not_applicable"
    SO2_24_HOUR_NOT_APPLICABLE = "so2_24_hour_not_applicable"
    NO_APPLICABLE_SO2_CANDIDATE = "no_applicable_so2_candidate"
    PUBLISHED_BREAKPOINT_GAP = "published_breakpoint_gap"
    SUBINDEX_NOT_DEFINED_FOR_CONCENTRATION = (
        "subindex_not_defined_for_concentration"
    )
    NO_ELIGIBLE_POLLUTANTS = "no_eligible_pollutants"


@dataclass(frozen=True)
class IndexCategory:
    code: str
    label: str
    internal_severity_rank: int
    color: str
    index_min: Optional[int] = None
    index_max: Optional[int] = None


@dataclass(frozen=True)
class MethodologyReference:
    reference_code: str
    title: str
    document_number: Optional[str]
    publication_date: Optional[str]
    section: str
    url: str


@dataclass(frozen=True)
class AirQualityIndexProduct:
    """One selectable air-quality index calculation."""

    product_code: str
    display_name: str
    parameter_code: Optional[str]
    calculation_code: str
    aggregation_period: str
    aggregation_display_name: str
    result_scope: str
    is_parameter_default: bool = False
    availability_status: str = "available"
    availability_reason: Optional[str] = None
    product_kind: str = "pollutant"
    history_status: str = "available"
    history_interval: str = "utc_hour"
    maximum_history_interval_count: int = 2160
    methodology_code: Optional[str] = None
    methodology_revision: Optional[str] = None
    methodology_effective_date: Optional[str] = None
    methodology_references: Tuple[MethodologyReference, ...] = ()
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AirQualityIndexStandard:
    code: str
    display_name: str
    methodology_version: str
    result_kind: ResultKind
    averaging_minutes: int
    pollutants: Tuple[str, ...]
    categories: Tuple[IndexCategory, ...]
    products: Tuple[AirQualityIndexProduct, ...]
    default_product_code: str
    is_default: bool = False
    methodology_code: Optional[str] = None
    methodology_revision: Optional[str] = None
    methodology_effective_date: Optional[str] = None
    methodology_references: Tuple[MethodologyReference, ...] = ()
    limitations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PollutantIndexResult:
    standard_code: str
    methodology_version: str
    parameter_code: str
    normalized_concentration: Optional[float]
    normalized_unit: Optional[str]
    preprocessed_concentration: Optional[float]
    result_kind: ResultKind
    numeric_value: Optional[float]
    category_code: Optional[str]
    category_label: Optional[str]
    internal_severity_rank: Optional[int]
    eligibility_status: EligibilityStatus
    exclusion_reason: Optional[ExclusionReason]

    @property
    def is_eligible(self) -> bool:
        return self.eligibility_status is EligibilityStatus.ELIGIBLE


@dataclass(frozen=True)
class CoverageInformation:
    coverage_status: CoverageState
    available_pollutants: Tuple[str, ...]
    missing_pollutants: Tuple[str, ...]
    ineligible_pollutants: Tuple[str, ...]
    missing_or_ineligible_pollutants: Tuple[str, ...]
    display_qualification: DisplayQualification


@dataclass(frozen=True)
class AirQualityIndexResult:
    standard_code: str
    methodology_version: str
    result_kind: ResultKind
    numeric_value: Optional[float]
    category_code: Optional[str]
    category_label: Optional[str]
    internal_severity_rank: Optional[int]
    eligibility_status: EligibilityStatus
    exclusion_reasons: Tuple[ExclusionReason, ...]
    dominant_pollutants: Tuple[str, ...]
    pollutant_results: Tuple[PollutantIndexResult, ...]
    coverage: CoverageInformation
