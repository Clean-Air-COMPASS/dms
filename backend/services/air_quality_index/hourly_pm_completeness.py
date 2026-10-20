from __future__ import annotations

"""Provider-neutral hourly completeness for PM inputs used by AQI standards.

EPA recommends 45 one-minute values for a valid continuous-monitor hour and
generally describes summary completeness as 75 percent of expected
observations. The frequency-aware count below applies that fraction to regular
sub-hourly PM streams. EPA does not define assignment rules for arbitrary
provider receipt timestamps; the expected-position assignment in this module
is therefore explicit CompassAQ application provenance, not an EPA method.

This module owns hourly PM input qualification and concentration construction.
AQI-standard services consume its result and apply only their downstream AQI
methodology (for example, U.S. NowCast or European hourly category bands).
The generic constructors and position assignment also serve EEA gas inputs;
those callers supply separate rules and concentration normalization explicitly.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING
from enum import Enum
from typing import Callable, Optional, Sequence, Tuple

from services.air_quality_index.domain import ExclusionReason, MethodologyReference
from services.air_quality_index.hourly_measurements import RawMeasurementInput, normalize_utc
from services.air_quality_index.us_epa import normalize_concentration_unit


US_EPA_STANDARD_CODE = "us_epa"
PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE = "pm_nowcast_hourly_input"
HOURLY_TARGET_DURATION_SECONDS = 3600
REQUIRED_COMPLETENESS_FRACTION = Decimal("0.75")

SUBHOURLY_COMPLETENESS_RULE_CODE = (
    "compass_aq.us_epa_input.pm.hourly_75_percent"
)
ONE_MINUTE_COMPLETENESS_RULE_CODE = (
    "us_epa.pm.hourly_from_one_minute_continuous"
)
PROVIDER_HOURLY_COMPLETENESS_RULE_CODE = "us_epa.pm.hourly_provider_reported"

SUPPORTED_SUBHOURLY_TIMESTAMP_SEMANTICS = (
    "interval_start",
    "interval_end",
    "provider_received_at",
)
SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS = ("hour_start", "hour_end")
VERIFIED_HOURLY_PROVENANCE = "provider_reported_hourly_average"
VERIFIED_MEASUREMENT_METADATA_STATUS = "provider_documented"


EPA_ONE_MINUTE_COMPLETENESS_REFERENCE = MethodologyReference(
    reference_code="epa_qa_handbook_volume_ii_section_6",
    title="Quality Assurance Handbook for Air Pollution Measurement Systems, Volume II",
    document_number="EPA-454/B-17-001",
    publication_date="2017-01",
    section="Section 6.4.1 and Table 6-4, pages 14-15",
    url=(
        "https://www.epa.gov/sites/default/files/2020-10/documents/"
        "final_handbook_document_1_17.pdf"
    ),
)

EPA_GENERAL_COMPLETENESS_REFERENCE = MethodologyReference(
    reference_code="epa_aqs_about_data_completeness",
    title="About AQS Data",
    document_number=None,
    publication_date=None,
    section="Section 4.2, Data Handling, paragraphs 198-199",
    url="https://aqs.epa.gov/aqsweb/documents/about_aqs_data.html",
)

EPA_HOURLY_SAMPLE_REFERENCE = MethodologyReference(
    reference_code="epa_aqs_hourly_sample_duration",
    title="About AQS Data",
    document_number=None,
    publication_date=None,
    section="Sections 4.3.1 and 5.1, continuous hourly sample values",
    url="https://aqs.epa.gov/aqsweb/documents/about_aqs_data.html",
)


class HourlyCompletenessAuditFlag(str, Enum):
    """Non-blocking conditions retained for completeness auditing."""

    DUPLICATE_OBSERVATION_INTERVAL = "duplicate_observation_interval"
    OFF_FREQUENCY_OBSERVATIONS = "off_frequency_observations"
    INVALID_OBSERVATIONS_REJECTED = "invalid_observations_rejected"


@dataclass(frozen=True)
class CompletenessApplicationProvenance:
    """CompassAQ-owned behavior used to operationalize a reference basis."""

    provenance_code: str
    description: str


FREQUENCY_DERIVED_REQUIRED_COUNT_PROVENANCE = CompletenessApplicationProvenance(
    provenance_code="compass_aq.frequency_derived_required_count",
    description=(
        "CompassAQ derives the expected count from the regular input frequency "
        "and rounds expected count multiplied by 75 percent upward."
    ),
)

ONE_MINUTE_INPUT_QUALIFICATION_PROVENANCE = CompletenessApplicationProvenance(
    provenance_code="compass_aq.one_minute_input_qualification",
    description=(
        "CompassAQ applies the 45-value continuous-monitor recommendation as "
        "hourly input qualification; this does not qualify a sensor as a "
        "regulatory monitor."
    ),
)

EXPECTED_POSITION_ASSIGNMENT_PROVENANCE = CompletenessApplicationProvenance(
    provenance_code="compass_aq.expected_position_assignment",
    description=(
        "CompassAQ generates regular expected positions, assigns each reading "
        "to the nearest anchor within one-half of the input frequency, resolves ties "
        "deterministically, and counts no more than one reading per position."
    ),
)

PROVIDER_HOURLY_INPUT_PROVENANCE = CompletenessApplicationProvenance(
    provenance_code="compass_aq.verified_provider_hourly_input",
    description=(
        "CompassAQ accepts exactly one explicitly verified provider-reported "
        "hourly concentration at the documented hour boundary."
    ),
)


@dataclass(frozen=True)
class CompletenessRule:
    standard_code: str
    pollutant_codes: Tuple[str, ...]
    calculation_code: str
    target_duration_seconds: int
    required_completeness_fraction: Optional[Decimal]
    explicit_required_count: Optional[int]
    applicable_frequency_minimum_seconds: int
    applicable_frequency_maximum_seconds: int
    rule_code: str
    completeness_reference_basis: Tuple[MethodologyReference, ...]
    application_provenance: Tuple[CompletenessApplicationProvenance, ...]
    effective_date: str


ONE_MINUTE_PM_RULE = CompletenessRule(
    standard_code=US_EPA_STANDARD_CODE,
    pollutant_codes=("pm25", "pm10"),
    calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
    target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
    required_completeness_fraction=REQUIRED_COMPLETENESS_FRACTION,
    explicit_required_count=45,
    applicable_frequency_minimum_seconds=60,
    applicable_frequency_maximum_seconds=60,
    rule_code=ONE_MINUTE_COMPLETENESS_RULE_CODE,
    completeness_reference_basis=(EPA_ONE_MINUTE_COMPLETENESS_REFERENCE,),
    application_provenance=(
        ONE_MINUTE_INPUT_QUALIFICATION_PROVENANCE,
        EXPECTED_POSITION_ASSIGNMENT_PROVENANCE,
    ),
    effective_date="2017-01",
)

SUBHOURLY_PM_RULE = CompletenessRule(
    standard_code=US_EPA_STANDARD_CODE,
    pollutant_codes=("pm25", "pm10"),
    calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
    target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
    required_completeness_fraction=REQUIRED_COMPLETENESS_FRACTION,
    explicit_required_count=None,
    applicable_frequency_minimum_seconds=60,
    applicable_frequency_maximum_seconds=900,
    rule_code=SUBHOURLY_COMPLETENESS_RULE_CODE,
    completeness_reference_basis=(EPA_GENERAL_COMPLETENESS_REFERENCE,),
    application_provenance=(
        FREQUENCY_DERIVED_REQUIRED_COUNT_PROVENANCE,
        EXPECTED_POSITION_ASSIGNMENT_PROVENANCE,
    ),
    effective_date="2026-07-31",
)

PROVIDER_HOURLY_PM_RULE = CompletenessRule(
    standard_code=US_EPA_STANDARD_CODE,
    pollutant_codes=("pm25", "pm10"),
    calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
    target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
    required_completeness_fraction=Decimal("1"),
    explicit_required_count=1,
    applicable_frequency_minimum_seconds=HOURLY_TARGET_DURATION_SECONDS,
    applicable_frequency_maximum_seconds=HOURLY_TARGET_DURATION_SECONDS,
    rule_code=PROVIDER_HOURLY_COMPLETENESS_RULE_CODE,
    completeness_reference_basis=(EPA_HOURLY_SAMPLE_REFERENCE,),
    application_provenance=(PROVIDER_HOURLY_INPUT_PROVENANCE,),
    effective_date="2026-07-31",
)

COMPLETENESS_RULES = (
    ONE_MINUTE_PM_RULE,
    SUBHOURLY_PM_RULE,
    PROVIDER_HOURLY_PM_RULE,
)


@dataclass(frozen=True)
class ObservationRequirements:
    expected_observation_count: Optional[int]
    required_valid_observation_count: Optional[int]
    required_completeness_fraction: Optional[Decimal]
    exclusion_reason: Optional[ExclusionReason]

    @property
    def is_supported(self) -> bool:
        return self.exclusion_reason is None


@dataclass(frozen=True)
class CompletenessRuleResolution:
    """One resolved rule and its frequency-aware observation counts."""

    rule: Optional[CompletenessRule]
    expected_observation_count: Optional[int]
    required_valid_observation_count: Optional[int]
    required_completeness_fraction: Optional[Decimal]
    exclusion_reason: Optional[ExclusionReason]

    @property
    def is_supported(self) -> bool:
        return self.exclusion_reason is None and self.rule is not None


@dataclass(frozen=True)
class PmHourlySensorMetadataResolution:
    """Whether sensor metadata can drive the shared hourly PM calculation."""

    exclusion_reason: Optional[ExclusionReason]
    provider_reported_hourly: bool
    metadata_is_verified_and_complete: bool

    @property
    def is_supported(self) -> bool:
        return self.exclusion_reason is None


@dataclass(frozen=True)
class RawHourlyObservation:
    measurement_id: int
    observed_at: datetime
    concentration: object
    is_valid: bool


@dataclass(frozen=True)
class AssignedObservation:
    position_index: int
    measurement_id: int
    observed_at: datetime
    normalized_concentration: Decimal


@dataclass(frozen=True)
class ExpectedPositionAssignment:
    accepted_observations: Tuple[AssignedObservation, ...]
    duplicate_measurement_ids: Tuple[int, ...]
    rejected_measurement_ids: Tuple[int, ...]
    off_frequency_measurement_ids: Tuple[int, ...]
    missing_position_count: int


@dataclass(frozen=True)
class EligibleHourlyConcentration:
    interval_started_at: datetime
    interval_ended_at: datetime
    hourly_concentration: Optional[float]
    normalized_unit: Optional[str]
    eligibility_status: str
    exclusion_reason: Optional[ExclusionReason]
    exclusion_reasons: Tuple[ExclusionReason, ...]
    audit_flags: Tuple[HourlyCompletenessAuditFlag, ...]
    input_frequency_seconds: int
    measurement_duration_seconds: int
    source_aggregation_duration_seconds: int
    target_duration_seconds: int
    expected_observation_count: int
    valid_observation_count: int
    required_valid_observation_count: int
    required_completeness_fraction: Optional[float]
    achieved_completeness_fraction: float
    measurement_ids: Tuple[int, ...]
    duplicate_measurement_ids: Tuple[int, ...]
    rejected_measurement_ids: Tuple[int, ...]
    off_frequency_measurement_ids: Tuple[int, ...]
    missing_position_count: int
    completeness_rule_code: str
    completeness_reference_basis: Tuple[MethodologyReference, ...]
    application_provenance: Tuple[CompletenessApplicationProvenance, ...]

    @property
    def is_eligible(self) -> bool:
        return self.eligibility_status == "eligible"


def calculate_observation_requirements(
    *,
    target_duration_seconds: int,
    expected_frequency_seconds: int,
    required_completeness_fraction: Optional[Decimal],
    explicit_required_count: Optional[int] = None,
) -> ObservationRequirements:
    """Calculate expected and required counts without source-specific logic."""
    if target_duration_seconds <= 0 or expected_frequency_seconds <= 0:
        return ObservationRequirements(
            None,
            None,
            required_completeness_fraction,
            ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION,
        )
    if target_duration_seconds % expected_frequency_seconds != 0:
        return ObservationRequirements(
            None,
            None,
            required_completeness_fraction,
            ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION,
        )
    expected_count = target_duration_seconds // expected_frequency_seconds
    if expected_count <= 0:
        return ObservationRequirements(
            None,
            None,
            required_completeness_fraction,
            ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION,
        )
    if explicit_required_count is not None:
        if explicit_required_count <= 0 or explicit_required_count > expected_count:
            return ObservationRequirements(
                expected_count,
                None,
                required_completeness_fraction,
                ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION,
            )
        required_count = explicit_required_count
    elif (
        required_completeness_fraction is not None
        and Decimal("0") < required_completeness_fraction <= Decimal("1")
    ):
        required_count = int(
            (Decimal(expected_count) * required_completeness_fraction).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
    else:
        return ObservationRequirements(
            expected_count,
            None,
            required_completeness_fraction,
            ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION,
        )
    return ObservationRequirements(
        expected_count,
        required_count,
        required_completeness_fraction,
        None,
    )


def resolve_completeness_requirement(
    *,
    standard_code: str,
    pollutant_code: str,
    calculation_code: str,
    target_duration_seconds: int,
    input_frequency_seconds: int,
    provider_reported_hourly: bool,
) -> CompletenessRuleResolution:
    """Resolve the most specific applicable rule and calculate its counts.

    Provider identity is deliberately absent. A rule with an explicit count
    and a narrower frequency range takes precedence over a generic percentage
    rule, so the EPA's specific one-minute recommendation overrides the
    CompassAQ-owned 75-percent sub-hourly rule.
    """
    applicable_rules: list[CompletenessRule] = []
    for rule in COMPLETENESS_RULES:
        is_provider_hourly_rule = (
            rule.rule_code == PROVIDER_HOURLY_COMPLETENESS_RULE_CODE
        )
        if is_provider_hourly_rule != provider_reported_hourly:
            continue
        if (
            rule.standard_code == standard_code
            and pollutant_code in rule.pollutant_codes
            and rule.calculation_code == calculation_code
            and rule.target_duration_seconds == target_duration_seconds
            and rule.applicable_frequency_minimum_seconds
            <= input_frequency_seconds
            <= rule.applicable_frequency_maximum_seconds
            and input_frequency_seconds > 0
            and target_duration_seconds % input_frequency_seconds == 0
        ):
            applicable_rules.append(rule)

    if not applicable_rules:
        return CompletenessRuleResolution(
            rule=None,
            expected_observation_count=None,
            required_valid_observation_count=None,
            required_completeness_fraction=None,
            exclusion_reason=(
                ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION
            ),
        )

    rule = sorted(
        applicable_rules,
        key=lambda candidate: (
            -int(candidate.explicit_required_count is not None),
            (
                candidate.applicable_frequency_maximum_seconds
                - candidate.applicable_frequency_minimum_seconds
            ),
            candidate.rule_code,
        ),
    )[0]
    requirements = calculate_observation_requirements(
        target_duration_seconds=target_duration_seconds,
        expected_frequency_seconds=input_frequency_seconds,
        required_completeness_fraction=rule.required_completeness_fraction,
        explicit_required_count=rule.explicit_required_count,
    )
    return CompletenessRuleResolution(
        rule=rule,
        expected_observation_count=requirements.expected_observation_count,
        required_valid_observation_count=(
            requirements.required_valid_observation_count
        ),
        required_completeness_fraction=(
            requirements.required_completeness_fraction
        ),
        exclusion_reason=requirements.exclusion_reason,
    )


def resolve_pm_hourly_sensor_metadata(
    *,
    aggregation_period: Optional[str],
    hourly_concentration_provenance: Optional[str],
    hourly_timestamp_semantics: Optional[str],
    expected_frequency_seconds: Optional[int],
    measurement_duration_seconds: Optional[int],
    source_aggregation_duration_seconds: Optional[int],
    measurement_timestamp_semantics: Optional[str],
    measurement_metadata_status: Optional[str],
    measurement_metadata_managed_by: Optional[str],
    parameter_code: str,
) -> PmHourlySensorMetadataResolution:
    """Resolve PM duration, frequency, and timestamp metadata without provider identity."""
    normalized_aggregation_period = (aggregation_period or "").strip().lower()
    provider_reported_hourly = (
        normalized_aggregation_period == "1h"
        and hourly_concentration_provenance == VERIFIED_HOURLY_PROVENANCE
    )

    if normalized_aggregation_period == "1h":
        if not provider_reported_hourly:
            return PmHourlySensorMetadataResolution(
                ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING,
                False,
                False,
            )
        if (
            measurement_metadata_status != VERIFIED_MEASUREMENT_METADATA_STATUS
            or not measurement_metadata_managed_by
        ):
            return PmHourlySensorMetadataResolution(
                ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING,
                True,
                False,
            )
        if hourly_timestamp_semantics not in SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS:
            return PmHourlySensorMetadataResolution(
                ExclusionReason.TIMESTAMP_SEMANTICS_UNKNOWN,
                True,
                False,
            )
        return PmHourlySensorMetadataResolution(None, True, True)

    if expected_frequency_seconds is None:
        return PmHourlySensorMetadataResolution(
            ExclusionReason.EXPECTED_FREQUENCY_MISSING,
            False,
            False,
        )
    if (
        measurement_duration_seconds is None
        or measurement_duration_seconds <= 0
        or measurement_duration_seconds > expected_frequency_seconds
        or source_aggregation_duration_seconds is None
        or source_aggregation_duration_seconds <= 0
        or source_aggregation_duration_seconds > expected_frequency_seconds
        or measurement_metadata_status != VERIFIED_MEASUREMENT_METADATA_STATUS
        or not measurement_metadata_managed_by
    ):
        return PmHourlySensorMetadataResolution(
            ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION,
            False,
            False,
        )
    if measurement_timestamp_semantics not in SUPPORTED_SUBHOURLY_TIMESTAMP_SEMANTICS:
        return PmHourlySensorMetadataResolution(
            ExclusionReason.TIMESTAMP_SEMANTICS_UNKNOWN,
            False,
            False,
        )
    resolution = resolve_completeness_requirement(
        standard_code=US_EPA_STANDARD_CODE,
        pollutant_code=parameter_code,
        calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
        target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        input_frequency_seconds=expected_frequency_seconds,
        provider_reported_hourly=False,
    )
    if not resolution.is_supported:
        return PmHourlySensorMetadataResolution(
            ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION,
            False,
            False,
        )
    return PmHourlySensorMetadataResolution(None, False, True)


def select_raw_observations_for_hour(
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    interval_started_at: datetime,
    timestamp_semantics: str,
) -> tuple[RawHourlyObservation, ...]:
    """Select observations represented by one UTC hour under explicit semantics."""
    interval_start = normalize_utc(interval_started_at)
    interval_end = interval_start + timedelta(hours=1)
    if timestamp_semantics in {"interval_end", "provider_received_at", "hour_end"}:
        represented = (
            item
            for item in raw_inputs
            if interval_start < normalize_utc(item.observed_at) <= interval_end
        )
    else:
        represented = (
            item
            for item in raw_inputs
            if interval_start <= normalize_utc(item.observed_at) < interval_end
        )
    return tuple(
        RawHourlyObservation(
            measurement_id=item.measurement_id,
            observed_at=item.observed_at,
            concentration=item.concentration,
            is_valid=item.is_valid,
        )
        for item in represented
    )


def _position_anchors(
    *,
    interval_started_at: datetime,
    expected_frequency_seconds: int,
    expected_observation_count: int,
    timestamp_semantics: str,
) -> tuple[datetime, ...]:
    frequency = timedelta(seconds=expected_frequency_seconds)
    first_offset = (
        frequency
        if timestamp_semantics in {"interval_end", "provider_received_at"}
        else timedelta(0)
    )
    return tuple(
        interval_started_at + first_offset + position_index * frequency
        for position_index in range(expected_observation_count)
    )


def assign_observations_to_expected_positions(
    observations: Sequence[RawHourlyObservation],
    *,
    interval_started_at: datetime,
    target_duration_seconds: int,
    expected_frequency_seconds: int,
    expected_observation_count: int,
    timestamp_semantics: str,
    parameter_code: str,
    input_unit: object,
    concentration_normalizer: Callable[[str, object, object], object] = (
        normalize_concentration_unit
    ),
) -> ExpectedPositionAssignment:
    """Assign at most one valid observation to each nearest expected position.

    An observation must be no farther than half one expected frequency from an
    anchor. Exact midpoint ties go to the earlier position. Candidate winners
    are chosen by distance, UTC timestamp, then measurement ID, making results
    independent of database row order.
    """
    interval_start = normalize_utc(interval_started_at)
    interval_end = interval_start + timedelta(seconds=target_duration_seconds)
    anchors = _position_anchors(
        interval_started_at=interval_start,
        expected_frequency_seconds=expected_frequency_seconds,
        expected_observation_count=expected_observation_count,
        timestamp_semantics=timestamp_semantics,
    )
    maximum_distance_seconds = Decimal(expected_frequency_seconds) / Decimal(2)
    candidates_by_position: dict[
        int, list[tuple[Decimal, datetime, int, Decimal]]
    ] = {}
    rejected_ids: list[int] = []
    off_frequency_ids: list[int] = []

    for observation in observations:
        observed_at = normalize_utc(observation.observed_at)
        if observed_at < interval_start or observed_at > interval_end:
            off_frequency_ids.append(observation.measurement_id)
            continue
        if not observation.is_valid:
            rejected_ids.append(observation.measurement_id)
            continue
        normalized = concentration_normalizer(
            parameter_code,
            observation.concentration,
            input_unit,
        )
        if (
            not normalized.is_supported
            or normalized.normalized_concentration is None
            or normalized.normalized_concentration < 0
        ):
            rejected_ids.append(observation.measurement_id)
            continue

        distances = tuple(
            Decimal(str(abs((observed_at - anchor).total_seconds())))
            for anchor in anchors
        )
        nearest_position = min(
            range(len(anchors)),
            key=lambda position_index: (distances[position_index], position_index),
        )
        distance = distances[nearest_position]
        if distance > maximum_distance_seconds:
            off_frequency_ids.append(observation.measurement_id)
            continue
        candidates_by_position.setdefault(nearest_position, []).append(
            (
                distance,
                observed_at,
                observation.measurement_id,
                normalized.normalized_concentration,
            )
        )

    accepted: list[AssignedObservation] = []
    duplicate_ids: list[int] = []
    for position_index in sorted(candidates_by_position):
        candidates = sorted(candidates_by_position[position_index])
        winner = candidates[0]
        accepted.append(
            AssignedObservation(
                position_index=position_index,
                measurement_id=winner[2],
                observed_at=winner[1],
                normalized_concentration=winner[3],
            )
        )
        duplicate_ids.extend(candidate[2] for candidate in candidates[1:])

    return ExpectedPositionAssignment(
        accepted_observations=tuple(accepted),
        duplicate_measurement_ids=tuple(sorted(duplicate_ids)),
        rejected_measurement_ids=tuple(sorted(rejected_ids)),
        off_frequency_measurement_ids=tuple(sorted(off_frequency_ids)),
        missing_position_count=expected_observation_count - len(accepted),
    )


def construct_subhourly_pm_hour(
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
    resolution = resolve_completeness_requirement(
        standard_code=US_EPA_STANDARD_CODE,
        pollutant_code=parameter_code,
        calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
        target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        input_frequency_seconds=expected_frequency_seconds,
        provider_reported_hourly=False,
    )
    if not resolution.is_supported or resolution.rule is None:
        raise ValueError("No supported U.S. EPA sub-hourly completeness rule")
    return construct_subhourly_concentration(
        observations,
        interval_started_at=interval_started_at,
        parameter_code=parameter_code,
        input_unit=input_unit,
        expected_frequency_seconds=expected_frequency_seconds,
        measurement_duration_seconds=measurement_duration_seconds,
        source_aggregation_duration_seconds=source_aggregation_duration_seconds,
        timestamp_semantics=timestamp_semantics,
        resolution=resolution,
        concentration_normalizer=normalize_concentration_unit,
    )


def construct_subhourly_concentration(
    observations: Sequence[RawHourlyObservation],
    *,
    interval_started_at: datetime,
    parameter_code: str,
    input_unit: object,
    expected_frequency_seconds: int,
    measurement_duration_seconds: int,
    source_aggregation_duration_seconds: int,
    timestamp_semantics: str,
    resolution: CompletenessRuleResolution,
    concentration_normalizer: Callable[[str, object, object], object],
    preserve_partial_concentration: bool = False,
) -> EligibleHourlyConcentration:
    """Apply an explicit domain rule using pollutant-independent interval mechanics.

    Callers qualify frequency, duration and timestamp metadata first and supply
    their own unit normalization. Partial means, when requested, are diagnostic;
    they never change the eligibility decision.
    """
    if not resolution.is_supported or resolution.rule is None:
        raise ValueError("A supported hourly completeness rule is required")
    rule = resolution.rule
    expected_count = resolution.expected_observation_count or 0
    required_count = resolution.required_valid_observation_count or 0
    assignment = assign_observations_to_expected_positions(
        observations,
        interval_started_at=interval_started_at,
        target_duration_seconds=rule.target_duration_seconds,
        expected_frequency_seconds=expected_frequency_seconds,
        expected_observation_count=expected_count,
        timestamp_semantics=timestamp_semantics,
        parameter_code=parameter_code,
        input_unit=input_unit,
        concentration_normalizer=concentration_normalizer,
    )
    accepted = assignment.accepted_observations
    valid_count = len(accepted)
    achieved_fraction = valid_count / expected_count
    exclusion_reasons: list[ExclusionReason] = []
    if valid_count == 0:
        exclusion_reasons.append(ExclusionReason.NO_VALID_OBSERVATIONS)
    if valid_count < required_count:
        exclusion_reasons.append(ExclusionReason.HOURLY_COMPLETENESS_NOT_MET)
    audit_flags: list[HourlyCompletenessAuditFlag] = []
    if assignment.duplicate_measurement_ids:
        audit_flags.append(
            HourlyCompletenessAuditFlag.DUPLICATE_OBSERVATION_INTERVAL
        )
    if assignment.off_frequency_measurement_ids:
        audit_flags.append(
            HourlyCompletenessAuditFlag.OFF_FREQUENCY_OBSERVATIONS
        )
    if assignment.rejected_measurement_ids:
        audit_flags.append(
            HourlyCompletenessAuditFlag.INVALID_OBSERVATIONS_REJECTED
        )
    is_eligible = valid_count >= required_count
    concentration = (
        float(
            sum(
                observation.normalized_concentration for observation in accepted
            )
            / Decimal(valid_count)
        )
        if valid_count and (is_eligible or preserve_partial_concentration)
        else None
    )
    unit_check = concentration_normalizer(parameter_code, 0, input_unit)
    return EligibleHourlyConcentration(
        interval_started_at=normalize_utc(interval_started_at),
        interval_ended_at=normalize_utc(interval_started_at)
        + timedelta(seconds=rule.target_duration_seconds),
        hourly_concentration=concentration,
        normalized_unit=unit_check.normalized_unit,
        eligibility_status="eligible" if is_eligible else "ineligible",
        exclusion_reason=exclusion_reasons[0] if exclusion_reasons else None,
        exclusion_reasons=tuple(exclusion_reasons),
        audit_flags=tuple(audit_flags),
        input_frequency_seconds=expected_frequency_seconds,
        measurement_duration_seconds=measurement_duration_seconds,
        source_aggregation_duration_seconds=(
            source_aggregation_duration_seconds
        ),
        target_duration_seconds=rule.target_duration_seconds,
        expected_observation_count=expected_count,
        valid_observation_count=valid_count,
        required_valid_observation_count=required_count,
        required_completeness_fraction=(
            float(resolution.required_completeness_fraction)
            if resolution.required_completeness_fraction is not None
            else None
        ),
        achieved_completeness_fraction=achieved_fraction,
        measurement_ids=tuple(
            observation.measurement_id for observation in accepted
        ),
        duplicate_measurement_ids=assignment.duplicate_measurement_ids,
        rejected_measurement_ids=assignment.rejected_measurement_ids,
        off_frequency_measurement_ids=assignment.off_frequency_measurement_ids,
        missing_position_count=assignment.missing_position_count,
        completeness_rule_code=rule.rule_code,
        completeness_reference_basis=rule.completeness_reference_basis,
        application_provenance=rule.application_provenance,
    )


def construct_provider_hourly_pm_hour(
    observations: Sequence[RawHourlyObservation],
    *,
    interval_started_at: datetime,
    parameter_code: str,
    input_unit: object,
    timestamp_semantics: str,
) -> EligibleHourlyConcentration:
    resolution = resolve_completeness_requirement(
        standard_code=US_EPA_STANDARD_CODE,
        pollutant_code=parameter_code,
        calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
        target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        input_frequency_seconds=HOURLY_TARGET_DURATION_SECONDS,
        provider_reported_hourly=True,
    )
    if not resolution.is_supported or resolution.rule is None:
        raise ValueError("No supported U.S. EPA provider-hourly completeness rule")
    return construct_provider_hourly_concentration(
        observations,
        interval_started_at=interval_started_at,
        parameter_code=parameter_code,
        input_unit=input_unit,
        timestamp_semantics=timestamp_semantics,
        resolution=resolution,
        concentration_normalizer=normalize_concentration_unit,
    )


def construct_provider_hourly_concentration(
    observations: Sequence[RawHourlyObservation],
    *,
    interval_started_at: datetime,
    parameter_code: str,
    input_unit: object,
    timestamp_semantics: str,
    resolution: CompletenessRuleResolution,
    concentration_normalizer: Callable[[str, object, object], object],
) -> EligibleHourlyConcentration:
    """Qualify one documented provider hour; counts refer to hourly rows only."""
    if not resolution.is_supported or resolution.rule is None:
        raise ValueError("A supported provider-hourly rule is required")
    if timestamp_semantics not in SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS:
        raise ValueError("Provider-hourly timestamp semantics must be explicit")
    rule = resolution.rule
    expected_count = resolution.expected_observation_count or 0
    required_count = resolution.required_valid_observation_count or 0
    interval_start = normalize_utc(interval_started_at)
    interval_end = interval_start + timedelta(hours=1)
    expected_timestamp = (
        interval_start if timestamp_semantics == "hour_start" else interval_end
    )
    rejected_ids: list[int] = []
    valid_candidates: list[tuple[float, datetime, int, Decimal]] = []
    for observation in observations:
        observed_at = normalize_utc(observation.observed_at)
        normalized = concentration_normalizer(
            parameter_code,
            observation.concentration,
            input_unit,
        )
        if (
            not observation.is_valid
            or not normalized.is_supported
            or normalized.normalized_concentration is None
            or normalized.normalized_concentration < 0
        ):
            rejected_ids.append(observation.measurement_id)
        else:
            valid_candidates.append(
                (
                    abs((observed_at - expected_timestamp).total_seconds()),
                    observed_at,
                    observation.measurement_id,
                    normalized.normalized_concentration,
                )
            )
    valid_candidates.sort()
    winner = valid_candidates[0] if valid_candidates else None
    duplicate_ids = tuple(
        sorted(candidate[2] for candidate in valid_candidates[1:])
    )
    off_frequency_ids = tuple(
        sorted(
            candidate[2]
            for candidate in valid_candidates
            if candidate[1] != expected_timestamp
        )
    )
    has_exact_winner = winner is not None and winner[1] == expected_timestamp
    is_eligible = (
        len(valid_candidates) == 1
        and has_exact_winner
    )
    exclusion_reasons: list[ExclusionReason] = []
    if not valid_candidates:
        exclusion_reasons.append(ExclusionReason.NO_VALID_OBSERVATIONS)
    if len(valid_candidates) > 1:
        exclusion_reasons.append(
            ExclusionReason.DUPLICATE_OBSERVATION_INTERVAL
        )
    if off_frequency_ids:
        exclusion_reasons.append(ExclusionReason.OFF_FREQUENCY_OBSERVATIONS)
    audit_flags: list[HourlyCompletenessAuditFlag] = []
    if duplicate_ids:
        audit_flags.append(
            HourlyCompletenessAuditFlag.DUPLICATE_OBSERVATION_INTERVAL
        )
    if off_frequency_ids:
        audit_flags.append(
            HourlyCompletenessAuditFlag.OFF_FREQUENCY_OBSERVATIONS
        )
    if rejected_ids:
        audit_flags.append(
            HourlyCompletenessAuditFlag.INVALID_OBSERVATIONS_REJECTED
        )
    accepted_position_count = 1 if has_exact_winner else 0
    unit_check = concentration_normalizer(parameter_code, 0, input_unit)
    return EligibleHourlyConcentration(
        interval_started_at=interval_start,
        interval_ended_at=interval_end,
        hourly_concentration=float(winner[3]) if is_eligible and winner else None,
        normalized_unit=unit_check.normalized_unit,
        eligibility_status="eligible" if is_eligible else "ineligible",
        exclusion_reason=(
            exclusion_reasons[0] if exclusion_reasons else None
        ),
        exclusion_reasons=tuple(exclusion_reasons),
        audit_flags=tuple(audit_flags),
        input_frequency_seconds=HOURLY_TARGET_DURATION_SECONDS,
        measurement_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        source_aggregation_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        target_duration_seconds=HOURLY_TARGET_DURATION_SECONDS,
        expected_observation_count=expected_count,
        valid_observation_count=accepted_position_count,
        required_valid_observation_count=required_count,
        required_completeness_fraction=(
            float(resolution.required_completeness_fraction)
            if resolution.required_completeness_fraction is not None
            else None
        ),
        achieved_completeness_fraction=float(accepted_position_count),
        measurement_ids=(winner[2],) if is_eligible and winner else (),
        duplicate_measurement_ids=duplicate_ids,
        rejected_measurement_ids=tuple(sorted(rejected_ids)),
        off_frequency_measurement_ids=off_frequency_ids,
        missing_position_count=expected_count - accepted_position_count,
        completeness_rule_code=rule.rule_code,
        completeness_reference_basis=rule.completeness_reference_basis,
        application_provenance=rule.application_provenance,
    )
