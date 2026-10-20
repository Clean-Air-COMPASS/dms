from __future__ import annotations

"""U.S. EPA nitrogen-dioxide AQI for the latest completed UTC hour.

The one-hour concentration, integer-ppb truncation, and AQI table follow
40 CFR Part 58, Appendix G. Presenting the latest completed UTC hour is a
CompassAQ site-level informational policy, not the regulatory daily maximum.
"""

from dataclasses import dataclass
from datetime import datetime
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


NITROGEN_DIOXIDE_HOUR_COUNT = 1


@dataclass(frozen=True)
class NitrogenDioxideHourCalculation:
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


def calculate_latest_nitrogen_dioxide_hour(
    hourly_inputs: Sequence[EligibleHourlyConcentration],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> NitrogenDioxideHourCalculation:
    """Calculate NO2 only when the fixed latest completed hour is qualified."""
    eligible_input = next(
        (
            hourly_input
            for hourly_input in hourly_inputs
            if hourly_input.is_eligible
            and hourly_input.hourly_concentration is not None
        ),
        None,
    )
    if eligible_input is None:
        return NitrogenDioxideHourCalculation(
            interval_started_at=window_started_at,
            interval_ended_at=window_ended_at,
            calculation=None,
            coverage_status=CoverageStatus.NONE,
            expected_hour_count=NITROGEN_DIOXIDE_HOUR_COUNT,
            valid_hour_count=0,
            exclusion_reason=ExclusionReason.INCOMPLETE_HOUR,
        )

    calculation = calculate_component_aqi(
        "no2",
        "no2_1_hour",
        eligible_input.hourly_concentration,
        eligible_input.normalized_unit or "ppb",
        coverage_status=CoverageStatus.COMPLETE,
        expected_observation_count=NITROGEN_DIOXIDE_HOUR_COUNT,
        valid_observation_count=1,
    )
    return NitrogenDioxideHourCalculation(
        interval_started_at=window_started_at,
        interval_ended_at=window_ended_at,
        calculation=calculation if calculation.is_calculated else None,
        coverage_status=(
            CoverageStatus.COMPLETE if calculation.is_calculated else CoverageStatus.NONE
        ),
        expected_hour_count=NITROGEN_DIOXIDE_HOUR_COUNT,
        valid_hour_count=1,
        exclusion_reason=(None if calculation.is_calculated else calculation.exclusion_reason),
    )
