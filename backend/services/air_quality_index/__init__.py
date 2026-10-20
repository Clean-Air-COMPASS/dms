"""Multi-standard air-quality index domain models and implementations."""

from .domain import (
    AirQualityIndexResult,
    AirQualityIndexStandard,
    CoverageInformation,
    CoverageState,
    DisplayQualification,
    EligibilityStatus,
    ExclusionReason,
    IndexCategory,
    MethodologyReference,
    PollutantIndexResult,
    ResultKind,
)
from .eea_european import (
    EEA_EUROPEAN_STANDARD,
    classify_hourly_concentration,
    combine_pollutant_results,
    ineligible_pollutant_result,
)
from .philippines_denr import PHILIPPINES_DENR_STANDARD

__all__ = [
    "AirQualityIndexResult",
    "AirQualityIndexStandard",
    "CoverageInformation",
    "CoverageState",
    "DisplayQualification",
    "EEA_EUROPEAN_STANDARD",
    "EligibilityStatus",
    "ExclusionReason",
    "IndexCategory",
    "MethodologyReference",
    "PollutantIndexResult",
    "PHILIPPINES_DENR_STANDARD",
    "ResultKind",
    "classify_hourly_concentration",
    "combine_pollutant_results",
    "ineligible_pollutant_result",
]
