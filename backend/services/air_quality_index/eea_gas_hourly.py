"""EEA gas input qualification, separate from EEA category bands.

The EU hourly aggregation criterion supports 75% temporal coverage. CompassAQ
applies it to documented regular one-minute gas streams as 45 of 60 distinct
positions. Verified provider-hourly means use their own one-hour input rule.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from .domain import ExclusionReason, MethodologyReference
from .eea_european import classify_hourly_concentration
from .hourly_measurements import HourlySensorStreamMetadata
from .hourly_pm_completeness import (
    CompletenessApplicationProvenance,
    CompletenessRule,
    CompletenessRuleResolution,
    EligibleHourlyConcentration,
    EXPECTED_POSITION_ASSIGNMENT_PROVENANCE,
    PROVIDER_HOURLY_INPUT_PROVENANCE,
    RawHourlyObservation,
    SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS,
    VERIFIED_HOURLY_PROVENANCE,
    VERIFIED_MEASUREMENT_METADATA_STATUS,
    construct_provider_hourly_concentration,
    construct_subhourly_concentration,
)


GAS_PARAMETER_CODES = ("o3", "no2", "so2")
EU_HOURLY_AGGREGATION_REFERENCE = MethodologyReference(
    reference_code="eu_2008_50_ec_hourly_aggregation",
    title="Directive 2008/50/EC on ambient air quality and cleaner air for Europe",
    document_number="2008/50/EC",
    publication_date="2008-05-21",
    section="Annex XI A and Annex VII A: one-hour values, 75% (45 minutes)",
    url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32008L0050",
)
NATIVE_MINUTE_POLICY = CompletenessApplicationProvenance(
    provenance_code="compass_aq.eea_gas_one_minute_input_qualification",
    description=(
        "CompassAQ requires 45 distinct valid positions out of 60 in a completed "
        "UTC hour for documented regular one-minute O3, NO2 and SO2 input. "
        "This applies the EU hourly aggregation basis; it is not an EEA index "
        "breakpoint rule or a regulatory-monitor qualification."
    ),
)


def gas_metadata_exclusion_reason(
    sensor: HourlySensorStreamMetadata,
) -> ExclusionReason | None:
    """A period label alone cannot establish measurement interval provenance."""
    period = (sensor.aggregation_period or "").strip().lower()
    if period not in {"1m", "1h"}:
        return ExclusionReason.UNSUPPORTED_AGGREGATION_PERIOD
    verified = (
        sensor.measurement_metadata_status == VERIFIED_MEASUREMENT_METADATA_STATUS
        and bool(sensor.measurement_metadata_managed_by)
    )
    if period == "1h":
        if (
            not verified
            or sensor.hourly_concentration_provenance != VERIFIED_HOURLY_PROVENANCE
        ):
            return ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING
        if (
            sensor.hourly_timestamp_semantics
            not in SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS
        ):
            return ExclusionReason.TIMESTAMP_SEMANTICS_UNKNOWN
        # Explicitly contradictory metadata cannot be overridden by a 1h label.
        if any(
            value is not None and value != 3600
            for value in (
                sensor.expected_frequency_seconds,
                sensor.measurement_duration_seconds,
                sensor.source_aggregation_duration_seconds,
            )
        ):
            return ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION
        return None
    if sensor.expected_frequency_seconds is None:
        return ExclusionReason.EXPECTED_FREQUENCY_MISSING
    if not verified or any(
        value != 60
        for value in (
            sensor.expected_frequency_seconds,
            sensor.measurement_duration_seconds,
            sensor.source_aggregation_duration_seconds,
        )
    ):
        return ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION
    if sensor.measurement_timestamp_semantics not in {"interval_start", "interval_end"}:
        return ExclusionReason.TIMESTAMP_SEMANTICS_UNKNOWN
    return None


@dataclass(frozen=True)
class _NormalizedEeaConcentration:
    normalized_concentration: Decimal | None
    normalized_unit: str | None
    is_supported: bool


def _normalize_eea_concentration(
    parameter: str, value: object, unit: object,
) -> _NormalizedEeaConcentration:
    # Reuse the EEA mass-unit/finite-value contract. Intermediate categories are
    # discarded; the service may classify the hourly mean only after eligibility.
    result = classify_hourly_concentration(parameter, value, unit)
    return _NormalizedEeaConcentration(
        (
            Decimal(str(result.normalized_concentration))
            if result.normalized_concentration is not None
            else None
        ),
        result.normalized_unit,
        result.exclusion_reason is None,
    )


def construct_eea_gas_hour(
    sensor: HourlySensorStreamMetadata,
    observations: Sequence[RawHourlyObservation],
    *,
    hour_started_at: datetime,
) -> EligibleHourlyConcentration:
    """Construct an explicitly qualified gas input, retaining partial means."""
    if (
        sensor.parameter_code not in GAS_PARAMETER_CODES
        or gas_metadata_exclusion_reason(sensor) is not None
    ):
        raise ValueError("EEA gas interval metadata must be qualified first")
    provider_hourly = (sensor.aggregation_period or "").strip().lower() == "1h"
    frequency = 3600 if provider_hourly else 60
    rule = CompletenessRule(
        standard_code="eea_european",
        pollutant_codes=GAS_PARAMETER_CODES,
        calculation_code="hourly_category",
        target_duration_seconds=3600,
        required_completeness_fraction=(
            Decimal("1") if provider_hourly else Decimal("0.75")
        ),
        explicit_required_count=1 if provider_hourly else 45,
        applicable_frequency_minimum_seconds=frequency,
        applicable_frequency_maximum_seconds=frequency,
        rule_code=(
            "compass_aq.eea_gas.hourly_provider_reported"
            if provider_hourly
            else "compass_aq.eea_gas.hourly_45_of_60_minutes"
        ),
        completeness_reference_basis=(
            () if provider_hourly else (EU_HOURLY_AGGREGATION_REFERENCE,)
        ),
        application_provenance=(
            (PROVIDER_HOURLY_INPUT_PROVENANCE,)
            if provider_hourly
            else (NATIVE_MINUTE_POLICY, EXPECTED_POSITION_ASSIGNMENT_PROVENANCE)
        ),
        effective_date="2026-10-06",
    )
    resolution = CompletenessRuleResolution(
        rule=rule,
        expected_observation_count=1 if provider_hourly else 60,
        required_valid_observation_count=rule.explicit_required_count,
        required_completeness_fraction=rule.required_completeness_fraction,
        exclusion_reason=None,
    )
    if provider_hourly:
        return construct_provider_hourly_concentration(
            observations,
            interval_started_at=hour_started_at,
            parameter_code=sensor.parameter_code,
            input_unit=sensor.input_unit_code or sensor.input_unit_symbol,
            timestamp_semantics=sensor.hourly_timestamp_semantics,
            resolution=resolution,
            concentration_normalizer=_normalize_eea_concentration,
        )
    return construct_subhourly_concentration(
        observations,
        interval_started_at=hour_started_at,
        parameter_code=sensor.parameter_code,
        input_unit=sensor.input_unit_code or sensor.input_unit_symbol,
        expected_frequency_seconds=60,
        measurement_duration_seconds=60,
        source_aggregation_duration_seconds=60,
        timestamp_semantics=sensor.measurement_timestamp_semantics,
        resolution=resolution,
        concentration_normalizer=_normalize_eea_concentration,
        preserve_partial_concentration=True,
    )
