from __future__ import annotations

"""U.S. EPA ozone AQI rules for CompassAQ's latest completed UTC window.

The AQI breakpoints, concentration truncation, interpolation, and selection of
the higher applicable one-hour or eight-hour AQI follow 40 CFR Part 58,
Appendix G and EPA-403/B-26-003 (May 2026). Eight-hour input precision and
coverage follow 40 CFR Part 50, Appendix U.

This module deliberately does not implement EPA O3 NowCast or a completed-day
AQI. Choosing the maximum eligible one-hour concentration inside CompassAQ's
represented eight-hour window is an explicit application policy.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from enum import Enum
from typing import Optional, Sequence, Tuple

from services.air_quality_index.domain import ExclusionReason, MethodologyReference
from services.air_quality_index.hourly_measurements import normalize_utc
from services.air_quality_index.us_epa import (
    AqiScaleStatus,
    CoverageStatus,
    OZONE_8_HOUR_COMPLETENESS_REFERENCE,
    calculate_component_aqi,
    normalize_concentration_unit,
)
from services.air_quality_index.us_epa_hourly_completeness import (
    CompletenessApplicationProvenance,
    EligibleHourlyConcentration,
    EXPECTED_POSITION_ASSIGNMENT_PROVENANCE,
    HourlyCompletenessAuditFlag,
    RawHourlyObservation,
    assign_observations_to_expected_positions,
)


OZONE_WINDOW_HOUR_COUNT = 8
HOURLY_TARGET_DURATION_SECONDS = 3600
REQUIRED_HOURLY_COMPLETENESS_FRACTION = Decimal("0.75")
APPENDIX_U_MINIMUM_ORDINARY_HOURS = 6
APPENDIX_U_ZERO_SUBSTITUTION_EXCEEDANCE_SUM = Decimal("0.567")
OZONE_HOURLY_RULE_CODE = "compass_aq.us_epa_input.o3.hourly_75_percent"
OZONE_PROVIDER_HOURLY_RULE_CODE = "us_epa.o3.hourly_provider_reported"

EPA_OZONE_SENSOR_COMPLETENESS_REFERENCE = MethodologyReference(
    reference_code="epa_air_sensor_performance_testing_protocols_ozone",
    title="Air Sensor Performance Testing Protocols, Metrics, and Target Values",
    document_number="EPA/600/R-20/279",
    publication_date="2021-02",
    section="Hourly data completeness recommendation",
    url="https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P1012RA8.txt",
)

OZONE_HOURLY_APPLICATION_PROVENANCE = CompletenessApplicationProvenance(
    provenance_code="compass_aq.ozone_hourly_input_qualification",
    description=(
        "CompassAQ requires at least 75 percent of the documented regular "
        "sub-hourly observations to construct an hourly ozone concentration; "
        "this does not qualify a sensor as a regulatory monitor."
    ),
)

OZONE_PROVIDER_HOURLY_APPLICATION_PROVENANCE = (
    CompletenessApplicationProvenance(
        provenance_code="compass_aq.verified_provider_hourly_ozone_input",
        description=(
            "CompassAQ accepts exactly one explicitly verified provider-reported "
            "hourly ozone concentration at its documented hour boundary."
        ),
    ),
)


class OzoneCandidateStatus(str, Enum):
    CALCULATED = "calculated"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class OzoneAqiCandidate:
    candidate_status: OzoneCandidateStatus
    aggregation_period: str
    interval_started_at: datetime
    interval_ended_at: datetime
    normalized_concentration: Optional[float]
    normalized_unit: Optional[str]
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
    zero_substitution_used: bool
    reference_basis: Tuple[MethodologyReference, ...]

    @property
    def is_calculated(self) -> bool:
        return self.candidate_status is OzoneCandidateStatus.CALCULATED


@dataclass(frozen=True)
class OzoneWindowCalculation:
    eight_hour_candidate: OzoneAqiCandidate
    one_hour_candidate: OzoneAqiCandidate
    selected_candidate: Optional[OzoneAqiCandidate]
    selected_aggregation_period: Optional[str]
    calculation_status: str
    coverage_status: CoverageStatus
    exclusion_reason: Optional[ExclusionReason]


def _truncate_ozone_ppm(concentration: object) -> Decimal:
    decimal_concentration = Decimal(str(concentration))
    return decimal_concentration.quantize(Decimal("0.001"), rounding=ROUND_DOWN)


def construct_subhourly_ozone_hour(
    observations: Sequence[RawHourlyObservation],
    *,
    interval_started_at: datetime,
    input_unit: object,
    expected_frequency_seconds: int,
    measurement_duration_seconds: int,
    source_aggregation_duration_seconds: int,
    timestamp_semantics: str,
) -> EligibleHourlyConcentration:
    """Construct one hourly O3 value from a documented regular input stream."""
    if (
        expected_frequency_seconds < 60
        or expected_frequency_seconds > 900
        or HOURLY_TARGET_DURATION_SECONDS % expected_frequency_seconds != 0
    ):
        raise ValueError("No supported U.S. EPA ozone sub-hourly completeness rule")

    expected_count = HOURLY_TARGET_DURATION_SECONDS // expected_frequency_seconds
    required_count = int(
        (Decimal(expected_count) * REQUIRED_HOURLY_COMPLETENESS_FRACTION)
        .to_integral_value(rounding=ROUND_CEILING)
    )
    assignment = assign_observations_to_expected_positions(
        observations,
        interval_started_at=interval_started_at,
        target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        expected_frequency_seconds=expected_frequency_seconds,
        expected_observation_count=expected_count,
        timestamp_semantics=timestamp_semantics,
        parameter_code="o3",
        input_unit=input_unit,
    )
    accepted = assignment.accepted_observations
    valid_count = len(accepted)
    exclusion_reasons: list[ExclusionReason] = []
    if valid_count == 0:
        exclusion_reasons.append(ExclusionReason.NO_VALID_OBSERVATIONS)
    if valid_count < required_count:
        exclusion_reasons.append(ExclusionReason.HOURLY_COMPLETENESS_NOT_MET)
    audit_flags: list[HourlyCompletenessAuditFlag] = []
    if assignment.duplicate_measurement_ids:
        audit_flags.append(HourlyCompletenessAuditFlag.DUPLICATE_OBSERVATION_INTERVAL)
    if assignment.off_frequency_measurement_ids:
        audit_flags.append(HourlyCompletenessAuditFlag.OFF_FREQUENCY_OBSERVATIONS)
    if assignment.rejected_measurement_ids:
        audit_flags.append(HourlyCompletenessAuditFlag.INVALID_OBSERVATIONS_REJECTED)

    is_eligible = valid_count >= required_count
    concentration = None
    if is_eligible:
        concentration = float(
            sum(item.normalized_concentration for item in accepted)
            / Decimal(valid_count)
        )
    unit_check = normalize_concentration_unit("o3", 0, input_unit)
    interval_start = normalize_utc(interval_started_at)
    return EligibleHourlyConcentration(
        interval_started_at=interval_start,
        interval_ended_at=interval_start + timedelta(hours=1),
        hourly_concentration=concentration,
        normalized_unit=unit_check.normalized_unit,
        eligibility_status="eligible" if is_eligible else "ineligible",
        exclusion_reason=exclusion_reasons[0] if exclusion_reasons else None,
        exclusion_reasons=tuple(exclusion_reasons),
        audit_flags=tuple(audit_flags),
        input_frequency_seconds=expected_frequency_seconds,
        measurement_duration_seconds=measurement_duration_seconds,
        source_aggregation_duration_seconds=source_aggregation_duration_seconds,
        target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        expected_observation_count=expected_count,
        valid_observation_count=valid_count,
        required_valid_observation_count=required_count,
        required_completeness_fraction=float(REQUIRED_HOURLY_COMPLETENESS_FRACTION),
        achieved_completeness_fraction=valid_count / expected_count,
        measurement_ids=tuple(item.measurement_id for item in accepted),
        duplicate_measurement_ids=assignment.duplicate_measurement_ids,
        rejected_measurement_ids=assignment.rejected_measurement_ids,
        off_frequency_measurement_ids=assignment.off_frequency_measurement_ids,
        missing_position_count=assignment.missing_position_count,
        completeness_rule_code=OZONE_HOURLY_RULE_CODE,
        completeness_reference_basis=(EPA_OZONE_SENSOR_COMPLETENESS_REFERENCE,),
        application_provenance=(
            OZONE_HOURLY_APPLICATION_PROVENANCE,
            EXPECTED_POSITION_ASSIGNMENT_PROVENANCE,
        ),
    )


def construct_provider_hourly_ozone_hour(
    observations: Sequence[RawHourlyObservation],
    *,
    interval_started_at: datetime,
    input_unit: object,
    timestamp_semantics: str,
) -> EligibleHourlyConcentration:
    """Accept exactly one valid provider-hourly O3 value at its boundary."""
    interval_start = normalize_utc(interval_started_at)
    interval_end = interval_start + timedelta(hours=1)
    expected_timestamp = interval_start if timestamp_semantics == "hour_start" else interval_end
    valid_candidates: list[tuple[datetime, int, Decimal]] = []
    rejected_ids: list[int] = []
    for observation in observations:
        normalized = normalize_concentration_unit(
            "o3", observation.concentration, input_unit
        )
        if (
            not observation.is_valid
            or not normalized.is_supported
            or normalized.normalized_concentration is None
        ):
            rejected_ids.append(observation.measurement_id)
            continue
        valid_candidates.append(
            (
                normalize_utc(observation.observed_at),
                observation.measurement_id,
                normalized.normalized_concentration,
            )
        )
    valid_candidates.sort()
    exact = [item for item in valid_candidates if item[0] == expected_timestamp]
    duplicate_ids = tuple(sorted(item[1] for item in valid_candidates[1:]))
    off_frequency_ids = tuple(
        sorted(item[1] for item in valid_candidates if item[0] != expected_timestamp)
    )
    is_eligible = len(valid_candidates) == 1 and len(exact) == 1
    exclusion_reasons: list[ExclusionReason] = []
    if not valid_candidates:
        exclusion_reasons.append(ExclusionReason.NO_VALID_OBSERVATIONS)
    if len(valid_candidates) > 1:
        exclusion_reasons.append(ExclusionReason.DUPLICATE_OBSERVATION_INTERVAL)
    if off_frequency_ids:
        exclusion_reasons.append(ExclusionReason.OFF_FREQUENCY_OBSERVATIONS)
    audit_flags: list[HourlyCompletenessAuditFlag] = []
    if duplicate_ids:
        audit_flags.append(HourlyCompletenessAuditFlag.DUPLICATE_OBSERVATION_INTERVAL)
    if off_frequency_ids:
        audit_flags.append(HourlyCompletenessAuditFlag.OFF_FREQUENCY_OBSERVATIONS)
    if rejected_ids:
        audit_flags.append(HourlyCompletenessAuditFlag.INVALID_OBSERVATIONS_REJECTED)
    unit_check = normalize_concentration_unit("o3", 0, input_unit)
    winner = valid_candidates[0] if is_eligible else None
    return EligibleHourlyConcentration(
        interval_started_at=interval_start,
        interval_ended_at=interval_end,
        hourly_concentration=float(winner[2]) if winner else None,
        normalized_unit=unit_check.normalized_unit,
        eligibility_status="eligible" if is_eligible else "ineligible",
        exclusion_reason=exclusion_reasons[0] if exclusion_reasons else None,
        exclusion_reasons=tuple(exclusion_reasons),
        audit_flags=tuple(audit_flags),
        input_frequency_seconds=HOURLY_TARGET_DURATION_SECONDS,
        measurement_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        source_aggregation_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        expected_observation_count=1,
        valid_observation_count=1 if is_eligible else 0,
        required_valid_observation_count=1,
        required_completeness_fraction=1.0,
        achieved_completeness_fraction=1.0 if is_eligible else 0.0,
        measurement_ids=(winner[1],) if winner else (),
        duplicate_measurement_ids=duplicate_ids,
        rejected_measurement_ids=tuple(sorted(rejected_ids)),
        off_frequency_measurement_ids=off_frequency_ids,
        missing_position_count=0 if is_eligible else 1,
        completeness_rule_code=OZONE_PROVIDER_HOURLY_RULE_CODE,
        completeness_reference_basis=(OZONE_8_HOUR_COMPLETENESS_REFERENCE,),
        application_provenance=OZONE_PROVIDER_HOURLY_APPLICATION_PROVENANCE,
    )


def _candidate_from_component(
    *,
    aggregation_period: str,
    interval_started_at: datetime,
    interval_ended_at: datetime,
    concentration: Decimal,
    coverage_status: CoverageStatus,
    valid_hour_count: int,
    zero_substitution_used: bool = False,
) -> OzoneAqiCandidate:
    component_code = "o3_8_hour" if aggregation_period == "8h" else "o3_1_hour"
    calculation = calculate_component_aqi(
        "o3",
        component_code,
        concentration,
        "ppm",
        coverage_status=coverage_status,
        expected_observation_count=(OZONE_WINDOW_HOUR_COUNT if aggregation_period == "8h" else 1),
        valid_observation_count=valid_hour_count,
    )
    if calculation.is_calculated:
        status = OzoneCandidateStatus.CALCULATED
    elif calculation.exclusion_reason in {
        ExclusionReason.OZONE_1_HOUR_NOT_APPLICABLE,
        ExclusionReason.OZONE_8_HOUR_NOT_APPLICABLE,
    }:
        status = OzoneCandidateStatus.NOT_APPLICABLE
    else:
        status = OzoneCandidateStatus.UNAVAILABLE
    return OzoneAqiCandidate(
        candidate_status=status,
        aggregation_period=aggregation_period,
        interval_started_at=interval_started_at,
        interval_ended_at=interval_ended_at,
        normalized_concentration=float(concentration),
        normalized_unit="ppm",
        preprocessed_concentration=calculation.preprocessed_concentration,
        numeric_value=calculation.numeric_value,
        category_code=calculation.category_code,
        category_label=calculation.category_label,
        internal_severity_rank=calculation.internal_severity_rank,
        aqi_scale_status=calculation.aqi_scale_status,
        coverage_status=coverage_status,
        expected_hour_count=(OZONE_WINDOW_HOUR_COUNT if aggregation_period == "8h" else 1),
        valid_hour_count=valid_hour_count,
        exclusion_reason=calculation.exclusion_reason,
        zero_substitution_used=zero_substitution_used,
        reference_basis=(OZONE_8_HOUR_COMPLETENESS_REFERENCE,),
    )


def _unavailable_candidate(
    aggregation_period: str,
    interval_started_at: datetime,
    interval_ended_at: datetime,
    valid_hour_count: int,
    reason: ExclusionReason,
) -> OzoneAqiCandidate:
    return OzoneAqiCandidate(
        candidate_status=OzoneCandidateStatus.UNAVAILABLE,
        aggregation_period=aggregation_period,
        interval_started_at=interval_started_at,
        interval_ended_at=interval_ended_at,
        normalized_concentration=None,
        normalized_unit="ppm",
        preprocessed_concentration=None,
        numeric_value=None,
        category_code=None,
        category_label=None,
        internal_severity_rank=None,
        aqi_scale_status=None,
        coverage_status=CoverageStatus.PARTIAL if valid_hour_count else CoverageStatus.NONE,
        expected_hour_count=OZONE_WINDOW_HOUR_COUNT if aggregation_period == "8h" else 1,
        valid_hour_count=valid_hour_count,
        exclusion_reason=reason,
        zero_substitution_used=False,
        reference_basis=(OZONE_8_HOUR_COMPLETENESS_REFERENCE,),
    )


def calculate_latest_ozone_window(
    hourly_inputs: Sequence[EligibleHourlyConcentration],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> OzoneWindowCalculation:
    """Calculate and select O3 candidates for one sensor and fixed UTC window."""
    eligible_inputs = [
        hourly_input
        for hourly_input in hourly_inputs
        if hourly_input.is_eligible and hourly_input.hourly_concentration is not None
    ]
    truncated_hours = [
        (hourly_input, _truncate_ozone_ppm(hourly_input.hourly_concentration))
        for hourly_input in eligible_inputs
    ]
    valid_hour_count = len(truncated_hours)
    window_coverage = (
        CoverageStatus.COMPLETE
        if valid_hour_count == OZONE_WINDOW_HOUR_COUNT
        else CoverageStatus.PARTIAL if valid_hour_count else CoverageStatus.NONE
    )

    if valid_hour_count >= APPENDIX_U_MINIMUM_ORDINARY_HOURS:
        eight_hour_concentration = sum(value for _, value in truncated_hours) / Decimal(valid_hour_count)
        eight_hour_candidate = _candidate_from_component(
            aggregation_period="8h",
            interval_started_at=window_started_at,
            interval_ended_at=window_ended_at,
            concentration=eight_hour_concentration,
            coverage_status=window_coverage,
            valid_hour_count=valid_hour_count,
        )
    else:
        available_sum = sum((value for _, value in truncated_hours), Decimal("0"))
        if available_sum > APPENDIX_U_ZERO_SUBSTITUTION_EXCEEDANCE_SUM:
            eight_hour_candidate = _candidate_from_component(
                aggregation_period="8h",
                interval_started_at=window_started_at,
                interval_ended_at=window_ended_at,
                concentration=available_sum / Decimal(OZONE_WINDOW_HOUR_COUNT),
                coverage_status=CoverageStatus.PARTIAL,
                valid_hour_count=valid_hour_count,
                zero_substitution_used=True,
            )
        else:
            eight_hour_candidate = _unavailable_candidate(
                "8h",
                window_started_at,
                window_ended_at,
                valid_hour_count,
                ExclusionReason.ROLLING_8_HOUR_COMPLETENESS_NOT_MET,
            )

    if truncated_hours:
        one_hour_input, one_hour_concentration = max(
            truncated_hours,
            key=lambda item: (item[1], item[0].interval_ended_at),
        )
        one_hour_candidate = _candidate_from_component(
            aggregation_period="1h",
            interval_started_at=one_hour_input.interval_started_at,
            interval_ended_at=one_hour_input.interval_ended_at,
            concentration=one_hour_concentration,
            coverage_status=CoverageStatus.COMPLETE,
            valid_hour_count=1,
        )
    else:
        one_hour_candidate = _unavailable_candidate(
            "1h",
            window_started_at,
            window_ended_at,
            0,
            ExclusionReason.NO_VALID_HOURLY_CONCENTRATIONS,
        )

    calculated_candidates = [
        candidate
        for candidate in (eight_hour_candidate, one_hour_candidate)
        if candidate.is_calculated
    ]
    selected_candidate: Optional[OzoneAqiCandidate]
    if calculated_candidates:
        selected_candidate = max(
            calculated_candidates,
            key=lambda candidate: (
                candidate.numeric_value if candidate.numeric_value is not None else -1,
                int(candidate.aggregation_period == "8h"),
            ),
        )
        exclusion_reason = None
        calculation_status = "calculated"
    else:
        selected_candidate = None
        exclusion_reason = ExclusionReason.NO_APPLICABLE_OZONE_CANDIDATE
        calculation_status = "unavailable"

    return OzoneWindowCalculation(
        eight_hour_candidate=eight_hour_candidate,
        one_hour_candidate=one_hour_candidate,
        selected_candidate=selected_candidate,
        selected_aggregation_period=(
            selected_candidate.aggregation_period if selected_candidate else None
        ),
        calculation_status=calculation_status,
        coverage_status=window_coverage,
        exclusion_reason=exclusion_reason,
    )
