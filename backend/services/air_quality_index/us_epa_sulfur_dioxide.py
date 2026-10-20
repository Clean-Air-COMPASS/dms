from __future__ import annotations

"""U.S. EPA sulfur-dioxide AQI candidate applicability and selection.

The low one-hour table, high 24-hour table, and exceptional AQI-200 case
follow 40 CFR Part 58, Appendix G and EPA-403/B-26-003 (May 2026). CompassAQ
applies those rules to the latest 24 completed UTC hours with an 18-hour
minimum. That trailing-window basis is informational and is not EPA's local
standard-time completed day.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Optional, Sequence, Tuple

from services.air_quality_index.domain import ExclusionReason, MethodologyReference
from services.air_quality_index.us_epa import (
    AqiScaleStatus,
    CoverageStatus,
    SULFUR_DIOXIDE_METHODOLOGY_REFERENCES,
    calculate_component_aqi,
)
from services.air_quality_index.us_epa_hourly_completeness import (
    EligibleHourlyConcentration,
)


SULFUR_DIOXIDE_WINDOW_HOUR_COUNT = 24
SULFUR_DIOXIDE_MINIMUM_VALID_HOURS = 18


class SulfurDioxideCandidateStatus(str, Enum):
    CALCULATED = "calculated"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SulfurDioxideAqiCandidate:
    candidate_status: SulfurDioxideCandidateStatus
    calculation_code: str
    aggregation_period: str
    interval_started_at: datetime
    interval_ended_at: datetime
    evaluation_interval_started_at: datetime
    evaluation_interval_ended_at: datetime
    normalized_concentration: Optional[float]
    normalized_unit: str
    preprocessed_concentration: Optional[float]
    numeric_value: Optional[int]
    category_code: Optional[str]
    category_label: Optional[str]
    internal_severity_rank: Optional[int]
    aqi_scale_status: Optional[AqiScaleStatus]
    coverage_status: CoverageStatus
    expected_hour_count: int
    valid_hour_count: int
    exclusion_reason: Optional[ExclusionReason]
    measurement_ids: Tuple[int, ...]
    reference_basis: Tuple[MethodologyReference, ...]

    @property
    def is_calculated(self) -> bool:
        return self.candidate_status is SulfurDioxideCandidateStatus.CALCULATED


@dataclass(frozen=True)
class SulfurDioxideWindowCalculation:
    one_hour_candidate: SulfurDioxideAqiCandidate
    twenty_four_hour_candidate: SulfurDioxideAqiCandidate
    selected_candidate: Optional[SulfurDioxideAqiCandidate]
    selected_aggregation_period: Optional[str]
    selected_calculation_code: Optional[str]
    calculation_status: str
    coverage_status: CoverageStatus
    expected_hour_count: int
    valid_hour_count: int
    interval_started_at: datetime
    interval_ended_at: datetime
    exclusion_reason: Optional[ExclusionReason]

    @property
    def is_calculated(self) -> bool:
        return self.selected_candidate is not None


def _truncate_integer_ppb(concentration: Decimal) -> Decimal:
    return concentration.quantize(Decimal("1"), rounding=ROUND_DOWN)


def _candidate_from_component(
    *,
    calculation_code: str,
    component_code: str,
    aggregation_period: str,
    interval_started_at: datetime,
    interval_ended_at: datetime,
    evaluation_interval_started_at: datetime,
    evaluation_interval_ended_at: datetime,
    concentration: Decimal,
    coverage_status: CoverageStatus,
    valid_hour_count: int,
    measurement_ids: Tuple[int, ...],
) -> SulfurDioxideAqiCandidate:
    calculation = calculate_component_aqi(
        "so2",
        component_code,
        concentration,
        "ppb",
        coverage_status=coverage_status,
        expected_observation_count=SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
        valid_observation_count=valid_hour_count,
    )
    status = (
        SulfurDioxideCandidateStatus.CALCULATED
        if calculation.is_calculated
        else SulfurDioxideCandidateStatus.NOT_APPLICABLE
        if calculation.exclusion_reason
        in {
            ExclusionReason.SO2_1_HOUR_NOT_APPLICABLE,
            ExclusionReason.SO2_24_HOUR_NOT_APPLICABLE,
        }
        else SulfurDioxideCandidateStatus.UNAVAILABLE
    )
    return SulfurDioxideAqiCandidate(
        candidate_status=status,
        calculation_code=calculation_code,
        aggregation_period=aggregation_period,
        interval_started_at=interval_started_at,
        interval_ended_at=interval_ended_at,
        evaluation_interval_started_at=evaluation_interval_started_at,
        evaluation_interval_ended_at=evaluation_interval_ended_at,
        normalized_concentration=float(concentration),
        normalized_unit="ppb",
        preprocessed_concentration=calculation.preprocessed_concentration,
        numeric_value=calculation.numeric_value,
        category_code=calculation.category_code,
        category_label=calculation.category_label,
        internal_severity_rank=calculation.internal_severity_rank,
        aqi_scale_status=calculation.aqi_scale_status,
        coverage_status=coverage_status,
        expected_hour_count=SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
        valid_hour_count=valid_hour_count,
        exclusion_reason=calculation.exclusion_reason,
        measurement_ids=measurement_ids,
        reference_basis=SULFUR_DIOXIDE_METHODOLOGY_REFERENCES,
    )


def _status_only_candidate(
    *,
    status: SulfurDioxideCandidateStatus,
    calculation_code: str,
    aggregation_period: str,
    interval_started_at: datetime,
    interval_ended_at: datetime,
    evaluation_interval_started_at: datetime,
    evaluation_interval_ended_at: datetime,
    concentration: Optional[Decimal],
    coverage_status: CoverageStatus,
    valid_hour_count: int,
    reason: ExclusionReason,
    measurement_ids: Tuple[int, ...] = (),
) -> SulfurDioxideAqiCandidate:
    return SulfurDioxideAqiCandidate(
        candidate_status=status,
        calculation_code=calculation_code,
        aggregation_period=aggregation_period,
        interval_started_at=interval_started_at,
        interval_ended_at=interval_ended_at,
        evaluation_interval_started_at=evaluation_interval_started_at,
        evaluation_interval_ended_at=evaluation_interval_ended_at,
        normalized_concentration=(float(concentration) if concentration is not None else None),
        normalized_unit="ppb",
        preprocessed_concentration=(
            float(_truncate_integer_ppb(concentration))
            if concentration is not None
            else None
        ),
        numeric_value=None,
        category_code=None,
        category_label=None,
        internal_severity_rank=None,
        aqi_scale_status=None,
        coverage_status=coverage_status,
        expected_hour_count=SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
        valid_hour_count=valid_hour_count,
        exclusion_reason=reason,
        measurement_ids=measurement_ids,
        reference_basis=SULFUR_DIOXIDE_METHODOLOGY_REFERENCES,
    )


def _capped_one_hour_candidate(
    *,
    hourly_input: EligibleHourlyConcentration,
    concentration: Decimal,
    evaluation_interval_started_at: datetime,
    evaluation_interval_ended_at: datetime,
    coverage_status: CoverageStatus,
    valid_hour_count: int,
) -> SulfurDioxideAqiCandidate:
    # Appendix G assigns AQI 200 rather than extending the one-hour table when
    # the maximum hour is high but the 24-hour concentration is below 305 ppb.
    category_source = calculate_component_aqi(
        "so2", "so2_1_hour_low", Decimal("304"), "ppb"
    )
    return SulfurDioxideAqiCandidate(
        candidate_status=SulfurDioxideCandidateStatus.CALCULATED,
        calculation_code="so2_1_hour_capped_at_200",
        aggregation_period="1h",
        interval_started_at=hourly_input.interval_started_at,
        interval_ended_at=hourly_input.interval_ended_at,
        evaluation_interval_started_at=evaluation_interval_started_at,
        evaluation_interval_ended_at=evaluation_interval_ended_at,
        normalized_concentration=float(concentration),
        normalized_unit="ppb",
        preprocessed_concentration=float(_truncate_integer_ppb(concentration)),
        numeric_value=200,
        category_code=category_source.category_code,
        category_label=category_source.category_label,
        internal_severity_rank=category_source.internal_severity_rank,
        aqi_scale_status=AqiScaleStatus.WITHIN_0_TO_500,
        coverage_status=coverage_status,
        expected_hour_count=SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
        valid_hour_count=valid_hour_count,
        exclusion_reason=None,
        measurement_ids=hourly_input.measurement_ids,
        reference_basis=SULFUR_DIOXIDE_METHODOLOGY_REFERENCES,
    )


def calculate_latest_sulfur_dioxide_window(
    hourly_inputs: Sequence[EligibleHourlyConcentration],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> SulfurDioxideWindowCalculation:
    """Evaluate SO2 candidates for one sensor and one fixed 24-hour window."""
    eligible = [
        (hourly_input, Decimal(str(hourly_input.hourly_concentration)))
        for hourly_input in hourly_inputs
        if hourly_input.is_eligible and hourly_input.hourly_concentration is not None
    ]
    valid_hour_count = len(eligible)
    coverage_status = (
        CoverageStatus.COMPLETE
        if valid_hour_count == SULFUR_DIOXIDE_WINDOW_HOUR_COUNT
        else CoverageStatus.PARTIAL
        if valid_hour_count
        else CoverageStatus.NONE
    )
    if valid_hour_count < SULFUR_DIOXIDE_MINIMUM_VALID_HOURS:
        one_hour = _status_only_candidate(
            status=SulfurDioxideCandidateStatus.UNAVAILABLE,
            calculation_code="so2_1_hour_low",
            aggregation_period="1h",
            interval_started_at=window_started_at,
            interval_ended_at=window_ended_at,
            evaluation_interval_started_at=window_started_at,
            evaluation_interval_ended_at=window_ended_at,
            concentration=None,
            coverage_status=coverage_status,
            valid_hour_count=valid_hour_count,
            reason=ExclusionReason.ROLLING_24_HOUR_COMPLETENESS_NOT_MET,
        )
        twenty_four_hour = _status_only_candidate(
            status=SulfurDioxideCandidateStatus.UNAVAILABLE,
            calculation_code="so2_24_hour_high",
            aggregation_period="24h",
            interval_started_at=window_started_at,
            interval_ended_at=window_ended_at,
            evaluation_interval_started_at=window_started_at,
            evaluation_interval_ended_at=window_ended_at,
            concentration=None,
            coverage_status=coverage_status,
            valid_hour_count=valid_hour_count,
            reason=ExclusionReason.ROLLING_24_HOUR_COMPLETENESS_NOT_MET,
        )
        return SulfurDioxideWindowCalculation(
            one_hour_candidate=one_hour,
            twenty_four_hour_candidate=twenty_four_hour,
            selected_candidate=None,
            selected_aggregation_period=None,
            selected_calculation_code=None,
            calculation_status="unavailable",
            coverage_status=coverage_status,
            expected_hour_count=SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
            valid_hour_count=valid_hour_count,
            interval_started_at=window_started_at,
            interval_ended_at=window_ended_at,
            exclusion_reason=ExclusionReason.NO_APPLICABLE_SO2_CANDIDATE,
        )

    maximum_hour, maximum_concentration = max(
        eligible,
        key=lambda item: (item[1], item[0].interval_ended_at),
    )
    mean_concentration = sum(
        (concentration for _, concentration in eligible), Decimal("0")
    ) / Decimal(valid_hour_count)
    preprocessed_maximum = _truncate_integer_ppb(maximum_concentration)
    preprocessed_mean = _truncate_integer_ppb(mean_concentration)
    all_measurement_ids = tuple(
        sorted(
            measurement_id
            for hourly_input, _ in eligible
            for measurement_id in hourly_input.measurement_ids
        )
    )

    if preprocessed_maximum <= Decimal("304"):
        one_hour = _candidate_from_component(
            calculation_code="so2_1_hour_low",
            component_code="so2_1_hour_low",
            aggregation_period="1h",
            interval_started_at=maximum_hour.interval_started_at,
            interval_ended_at=maximum_hour.interval_ended_at,
            evaluation_interval_started_at=window_started_at,
            evaluation_interval_ended_at=window_ended_at,
            concentration=maximum_concentration,
            coverage_status=coverage_status,
            valid_hour_count=valid_hour_count,
            measurement_ids=maximum_hour.measurement_ids,
        )
        twenty_four_hour = _status_only_candidate(
            status=SulfurDioxideCandidateStatus.NOT_APPLICABLE,
            calculation_code="so2_24_hour_high",
            aggregation_period="24h",
            interval_started_at=window_started_at,
            interval_ended_at=window_ended_at,
            evaluation_interval_started_at=window_started_at,
            evaluation_interval_ended_at=window_ended_at,
            concentration=mean_concentration,
            coverage_status=coverage_status,
            valid_hour_count=valid_hour_count,
            reason=ExclusionReason.SO2_24_HOUR_NOT_APPLICABLE,
            measurement_ids=all_measurement_ids,
        )
        selected = one_hour
    elif preprocessed_mean >= Decimal("305"):
        one_hour = _status_only_candidate(
            status=SulfurDioxideCandidateStatus.NOT_APPLICABLE,
            calculation_code="so2_1_hour_low",
            aggregation_period="1h",
            interval_started_at=maximum_hour.interval_started_at,
            interval_ended_at=maximum_hour.interval_ended_at,
            evaluation_interval_started_at=window_started_at,
            evaluation_interval_ended_at=window_ended_at,
            concentration=maximum_concentration,
            coverage_status=coverage_status,
            valid_hour_count=valid_hour_count,
            reason=ExclusionReason.SO2_1_HOUR_NOT_APPLICABLE,
            measurement_ids=maximum_hour.measurement_ids,
        )
        twenty_four_hour = _candidate_from_component(
            calculation_code="so2_24_hour_high",
            component_code="so2_24_hour_high",
            aggregation_period="24h",
            interval_started_at=window_started_at,
            interval_ended_at=window_ended_at,
            evaluation_interval_started_at=window_started_at,
            evaluation_interval_ended_at=window_ended_at,
            concentration=mean_concentration,
            coverage_status=coverage_status,
            valid_hour_count=valid_hour_count,
            measurement_ids=all_measurement_ids,
        )
        selected = twenty_four_hour
    else:
        one_hour = _capped_one_hour_candidate(
            hourly_input=maximum_hour,
            concentration=maximum_concentration,
            evaluation_interval_started_at=window_started_at,
            evaluation_interval_ended_at=window_ended_at,
            coverage_status=coverage_status,
            valid_hour_count=valid_hour_count,
        )
        twenty_four_hour = _status_only_candidate(
            status=SulfurDioxideCandidateStatus.NOT_APPLICABLE,
            calculation_code="so2_24_hour_high",
            aggregation_period="24h",
            interval_started_at=window_started_at,
            interval_ended_at=window_ended_at,
            evaluation_interval_started_at=window_started_at,
            evaluation_interval_ended_at=window_ended_at,
            concentration=mean_concentration,
            coverage_status=coverage_status,
            valid_hour_count=valid_hour_count,
            reason=ExclusionReason.SO2_24_HOUR_NOT_APPLICABLE,
            measurement_ids=all_measurement_ids,
        )
        selected = one_hour

    return SulfurDioxideWindowCalculation(
        one_hour_candidate=one_hour,
        twenty_four_hour_candidate=twenty_four_hour,
        selected_candidate=selected,
        selected_aggregation_period=selected.aggregation_period,
        selected_calculation_code=selected.calculation_code,
        calculation_status="calculated",
        coverage_status=coverage_status,
        expected_hour_count=SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
        valid_hour_count=valid_hour_count,
        interval_started_at=selected.interval_started_at,
        interval_ended_at=selected.interval_ended_at,
        exclusion_reason=None,
    )
