from __future__ import annotations

"""U.S. EPA carbon-monoxide AQI for a fixed completed eight-hour UTC window.

The 8-hour concentration, 0.1 ppm truncation, and AQI table follow 40 CFR
Part 58, Appendix G. The six-of-eight completeness rule follows 40 CFR 50.8.
Using the latest completed UTC window is a CompassAQ site-level informational
policy; it is not the official daily maximum reporting-area AQI.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.us_epa import (
    CoverageStatus,
    UsEpaCalculationResult,
    calculate_component_aqi,
)
from services.air_quality_index.us_epa_hourly_completeness import (
    EligibleHourlyConcentration,
)


CARBON_MONOXIDE_WINDOW_HOUR_COUNT = 8
CARBON_MONOXIDE_MINIMUM_VALID_HOURS = 6


@dataclass(frozen=True)
class CarbonMonoxideWindowCalculation:
    interval_started_at: datetime
    interval_ended_at: datetime
    calculation: Optional[UsEpaCalculationResult]
    coverage_status: CoverageStatus
    expected_hour_count: int
    valid_hour_count: int
    exclusion_reason: Optional[ExclusionReason]

    @property
    def is_calculated(self) -> bool:
        return self.calculation is not None and self.calculation.is_calculated


def calculate_latest_carbon_monoxide_window(
    hourly_inputs: Sequence[EligibleHourlyConcentration],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> CarbonMonoxideWindowCalculation:
    """Average the available six, seven, or eight qualified hourly values."""
    eligible_concentrations = [
        Decimal(str(hourly_input.hourly_concentration))
        for hourly_input in hourly_inputs
        if hourly_input.is_eligible and hourly_input.hourly_concentration is not None
    ]
    valid_hour_count = len(eligible_concentrations)
    coverage_status = (
        CoverageStatus.COMPLETE
        if valid_hour_count == CARBON_MONOXIDE_WINDOW_HOUR_COUNT
        else CoverageStatus.PARTIAL
        if valid_hour_count
        else CoverageStatus.NONE
    )
    if valid_hour_count < CARBON_MONOXIDE_MINIMUM_VALID_HOURS:
        return CarbonMonoxideWindowCalculation(
            interval_started_at=window_started_at,
            interval_ended_at=window_ended_at,
            calculation=None,
            coverage_status=coverage_status,
            expected_hour_count=CARBON_MONOXIDE_WINDOW_HOUR_COUNT,
            valid_hour_count=valid_hour_count,
            exclusion_reason=ExclusionReason.ROLLING_8_HOUR_COMPLETENESS_NOT_MET,
        )

    eight_hour_concentration = sum(
        eligible_concentrations, Decimal("0")
    ) / Decimal(valid_hour_count)
    calculation = calculate_component_aqi(
        "co",
        "co_8_hour",
        eight_hour_concentration,
        "ppm",
        coverage_status=coverage_status,
        expected_observation_count=CARBON_MONOXIDE_WINDOW_HOUR_COUNT,
        valid_observation_count=valid_hour_count,
    )
    return CarbonMonoxideWindowCalculation(
        interval_started_at=window_started_at,
        interval_ended_at=window_ended_at,
        calculation=calculation if calculation.is_calculated else None,
        coverage_status=coverage_status,
        expected_hour_count=CARBON_MONOXIDE_WINDOW_HOUR_COUNT,
        valid_hour_count=valid_hour_count,
        exclusion_reason=(None if calculation.is_calculated else calculation.exclusion_reason),
    )
