from __future__ import annotations

"""Qualified hourly inputs shared by the U.S. EPA CO, NO2, and SO2 products.

Appendix G defines AQI concentrations but does not define how CompassAQ's
non-regulatory sensor observations become an hourly concentration. CompassAQ
therefore requires 75 percent of the documented, regular expected positions.
This is an explicit application policy and does not qualify a sensor as a
regulatory monitor.
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING
from typing import Sequence

from services.air_quality_index.domain import ExclusionReason, MethodologyReference
from services.air_quality_index.hourly_measurements import normalize_utc
from services.air_quality_index.us_epa import normalize_concentration_unit
from services.air_quality_index.us_epa_hourly_completeness import (
    CompletenessApplicationProvenance,
    EligibleHourlyConcentration,
    EXPECTED_POSITION_ASSIGNMENT_PROVENANCE,
    HourlyCompletenessAuditFlag,
    RawHourlyObservation,
    assign_observations_to_expected_positions,
)


SUPPORTED_GAS_PARAMETER_CODES = frozenset({"co", "no2", "so2"})
HOURLY_TARGET_DURATION_SECONDS = 3600
REQUIRED_HOURLY_COMPLETENESS_FRACTION = Decimal("0.75")

EPA_GAS_SENSOR_COMPLETENESS_REFERENCE = MethodologyReference(
    reference_code="epa_air_sensor_performance_testing_protocols_gases",
    title="Air Sensor Performance Testing Protocols, Metrics, and Target Values",
    document_number="EPA/600/R-20/279",
    publication_date="2021-02",
    section="Hourly data completeness recommendation",
    url="https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P1012RA8.txt",
)


def _require_supported_parameter(parameter_code: str) -> str:
    normalized_code = str(parameter_code or "").strip().lower()
    if normalized_code not in SUPPORTED_GAS_PARAMETER_CODES:
        raise ValueError(f"Unsupported U.S. EPA gas hourly parameter: {parameter_code}")
    return normalized_code


def _hourly_rule_code(parameter_code: str) -> str:
    return f"compass_aq.us_epa_input.{parameter_code}.hourly_75_percent"


def _provider_hourly_rule_code(parameter_code: str) -> str:
    return f"us_epa.{parameter_code}.hourly_provider_reported"


def _subhourly_application_provenance(
    parameter_code: str,
) -> CompletenessApplicationProvenance:
    return CompletenessApplicationProvenance(
        provenance_code=f"compass_aq.{parameter_code}_hourly_input_qualification",
        description=(
            "CompassAQ requires at least 75 percent of the documented regular "
            f"sub-hourly observations to construct an hourly {parameter_code.upper()} "
            "concentration; this does not qualify a sensor as a regulatory monitor."
        ),
    )


def _provider_application_provenance(
    parameter_code: str,
) -> CompletenessApplicationProvenance:
    return CompletenessApplicationProvenance(
        provenance_code=f"compass_aq.verified_provider_hourly_{parameter_code}_input",
        description=(
            "CompassAQ accepts exactly one explicitly verified provider-reported "
            f"hourly {parameter_code.upper()} concentration at its documented hour "
            "boundary."
        ),
    )


def construct_subhourly_gas_hour(
    observations: Sequence[RawHourlyObservation],
    *,
    interval_started_at: datetime,
    parameter_code: str,
    input_unit: object,
    expected_frequency_seconds: int,
    measurement_duration_seconds: int,
    source_aggregation_duration_seconds: int,
    timestamp_semantics: str,
) -> EligibleHourlyConcentration:
    """Construct one hourly gas value from a verified regular input stream."""
    pollutant_code = _require_supported_parameter(parameter_code)
    if (
        expected_frequency_seconds < 60
        or expected_frequency_seconds > 900
        or HOURLY_TARGET_DURATION_SECONDS % expected_frequency_seconds != 0
    ):
        raise ValueError(
            f"No supported U.S. EPA {pollutant_code} sub-hourly completeness rule"
        )

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
        parameter_code=pollutant_code,
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
    unit_check = normalize_concentration_unit(pollutant_code, 0, input_unit)
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
        completeness_rule_code=_hourly_rule_code(pollutant_code),
        completeness_reference_basis=(EPA_GAS_SENSOR_COMPLETENESS_REFERENCE,),
        application_provenance=(
            _subhourly_application_provenance(pollutant_code),
            EXPECTED_POSITION_ASSIGNMENT_PROVENANCE,
        ),
    )


def construct_provider_hourly_gas_hour(
    observations: Sequence[RawHourlyObservation],
    *,
    interval_started_at: datetime,
    parameter_code: str,
    input_unit: object,
    timestamp_semantics: str,
) -> EligibleHourlyConcentration:
    """Accept exactly one valid provider hour at its documented boundary."""
    pollutant_code = _require_supported_parameter(parameter_code)
    interval_start = normalize_utc(interval_started_at)
    interval_end = interval_start + timedelta(hours=1)
    expected_timestamp = (
        interval_start if timestamp_semantics == "hour_start" else interval_end
    )
    valid_candidates: list[tuple[datetime, int, Decimal]] = []
    rejected_ids: list[int] = []
    for observation in observations:
        normalized = normalize_concentration_unit(
            pollutant_code, observation.concentration, input_unit
        )
        if (
            not observation.is_valid
            or not normalized.is_supported
            or normalized.normalized_concentration is None
            or normalized.normalized_concentration < 0
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
    exact = [candidate for candidate in valid_candidates if candidate[0] == expected_timestamp]
    duplicate_ids = tuple(sorted(candidate[1] for candidate in valid_candidates[1:]))
    off_frequency_ids = tuple(
        sorted(
            candidate[1]
            for candidate in valid_candidates
            if candidate[0] != expected_timestamp
        )
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

    unit_check = normalize_concentration_unit(pollutant_code, 0, input_unit)
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
        completeness_rule_code=_provider_hourly_rule_code(pollutant_code),
        completeness_reference_basis=(EPA_GAS_SENSOR_COMPLETENESS_REFERENCE,),
        application_provenance=(
            _provider_application_provenance(pollutant_code),
        ),
    )
