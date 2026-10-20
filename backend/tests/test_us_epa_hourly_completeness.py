from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from services.air_quality_index.domain import ExclusionReason
from services.air_quality_index.hourly_pm_completeness import (
    COMPLETENESS_RULES,
    ONE_MINUTE_COMPLETENESS_RULE_CODE,
    PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
    PROVIDER_HOURLY_COMPLETENESS_RULE_CODE,
    REQUIRED_COMPLETENESS_FRACTION,
    SUBHOURLY_COMPLETENESS_RULE_CODE,
    US_EPA_STANDARD_CODE,
    HourlyCompletenessAuditFlag,
    RawHourlyObservation,
    assign_observations_to_expected_positions,
    calculate_observation_requirements,
    construct_provider_hourly_pm_hour,
    construct_subhourly_pm_hour,
    resolve_completeness_requirement,
)


HOUR_START = datetime(2026, 7, 30, 17, tzinfo=timezone.utc)


def _observations(
    frequency_seconds: int,
    count: int,
    *,
    value: float = 10.0,
    timestamp_drift_seconds: int = 0,
    first_id: int = 1,
) -> tuple[RawHourlyObservation, ...]:
    return tuple(
        RawHourlyObservation(
            measurement_id=first_id + position,
            observed_at=HOUR_START
            + timedelta(
                seconds=(position + 1) * frequency_seconds
                + timestamp_drift_seconds
            ),
            concentration=value + position,
            is_valid=True,
        )
        for position in range(count)
    )


@pytest.mark.parametrize(
    ("frequency_seconds", "expected_count", "required_count"),
    (
        (60, 60, 45),
        (120, 30, 23),
        (300, 12, 9),
        (600, 6, 5),
        (900, 4, 3),
        (3600, 1, 1),
    ),
)
def test_percentage_requirement_uses_ceiling(
    frequency_seconds: int,
    expected_count: int,
    required_count: int,
) -> None:
    requirements = calculate_observation_requirements(
        target_duration_seconds=3600,
        expected_frequency_seconds=frequency_seconds,
        required_completeness_fraction=REQUIRED_COMPLETENESS_FRACTION,
    )

    assert requirements.expected_observation_count == expected_count
    assert requirements.required_valid_observation_count == required_count
    assert requirements.exclusion_reason is None


@pytest.mark.parametrize("frequency_seconds", (0, -60, 700))
def test_invalid_or_non_dividing_frequency_is_explicit(
    frequency_seconds: int,
) -> None:
    requirements = calculate_observation_requirements(
        target_duration_seconds=3600,
        expected_frequency_seconds=frequency_seconds,
        required_completeness_fraction=REQUIRED_COMPLETENESS_FRACTION,
    )

    assert not requirements.is_supported
    assert requirements.exclusion_reason is (
        ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION
    )


def test_specific_one_minute_rule_overrides_compass_aq_percentage_rule() -> None:
    one_minute = resolve_completeness_requirement(
        standard_code=US_EPA_STANDARD_CODE,
        pollutant_code="pm25",
        calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
        target_duration_seconds=3600,
        input_frequency_seconds=60,
        provider_reported_hourly=False,
    )
    two_minute = resolve_completeness_requirement(
        standard_code=US_EPA_STANDARD_CODE,
        pollutant_code="pm25",
        calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
        target_duration_seconds=3600,
        input_frequency_seconds=120,
        provider_reported_hourly=False,
    )

    assert one_minute.is_supported
    assert one_minute.rule is not None
    assert one_minute.rule.rule_code == ONE_MINUTE_COMPLETENESS_RULE_CODE
    assert one_minute.rule.explicit_required_count == 45
    assert one_minute.expected_observation_count == 60
    assert one_minute.required_valid_observation_count == 45
    assert two_minute.is_supported
    assert two_minute.rule is not None
    assert two_minute.rule.rule_code == SUBHOURLY_COMPLETENESS_RULE_CODE
    assert two_minute.expected_observation_count == 30
    assert two_minute.required_valid_observation_count == 23


def test_rule_resolver_returns_explicit_unsupported_result() -> None:
    unsupported = resolve_completeness_requirement(
        standard_code=US_EPA_STANDARD_CODE,
        pollutant_code="pm25",
        calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
        target_duration_seconds=3600,
        input_frequency_seconds=700,
        provider_reported_hourly=False,
    )

    assert not unsupported.is_supported
    assert unsupported.rule is None
    assert unsupported.exclusion_reason is (
        ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION
    )


def test_rule_resolver_returns_verified_provider_hourly_requirement() -> None:
    provider_hourly = resolve_completeness_requirement(
        standard_code=US_EPA_STANDARD_CODE,
        pollutant_code="pm10",
        calculation_code=PM_NOWCAST_HOURLY_INPUT_CALCULATION_CODE,
        target_duration_seconds=3600,
        input_frequency_seconds=3600,
        provider_reported_hourly=True,
    )

    assert provider_hourly.is_supported
    assert provider_hourly.rule is not None
    assert (
        provider_hourly.rule.rule_code
        == PROVIDER_HOURLY_COMPLETENESS_RULE_CODE
    )
    assert provider_hourly.expected_observation_count == 1
    assert provider_hourly.required_valid_observation_count == 1
    assert provider_hourly.required_completeness_fraction == Decimal("1")


def test_every_completeness_rule_has_auditable_methodology_metadata() -> None:
    for rule in COMPLETENESS_RULES:
        assert rule.standard_code == "us_epa"
        assert rule.pollutant_codes == ("pm25", "pm10")
        assert rule.target_duration_seconds == 3600
        assert rule.rule_code
        assert rule.effective_date
        assert rule.completeness_reference_basis
        assert all(
            reference.section for reference in rule.completeness_reference_basis
        )
        assert rule.application_provenance


def test_compass_aq_rule_exposes_reference_basis_and_application_provenance() -> None:
    compass_aq_rule = next(
        rule
        for rule in COMPLETENESS_RULES
        if rule.rule_code == SUBHOURLY_COMPLETENESS_RULE_CODE
    )

    assert compass_aq_rule.rule_code == (
        "compass_aq.us_epa_input.pm.hourly_75_percent"
    )
    assert {
        item.provenance_code
        for item in compass_aq_rule.application_provenance
    } == {
        "compass_aq.frequency_derived_required_count",
        "compass_aq.expected_position_assignment",
    }
    assert {
        reference.reference_code
        for reference in compass_aq_rule.completeness_reference_basis
    } == {"epa_aqs_about_data_completeness"}


def test_two_minute_23_of_30_qualifies_and_mean_uses_accepted_values() -> None:
    result = construct_subhourly_pm_hour(
        _observations(120, 23),
        interval_started_at=HOUR_START,
        parameter_code="pm25",
        input_unit="ug_m3",
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        timestamp_semantics="provider_received_at",
    )

    assert result.is_eligible
    assert result.expected_observation_count == 30
    assert result.required_valid_observation_count == 23
    assert result.valid_observation_count == 23
    assert result.missing_position_count == 7
    assert result.source_aggregation_duration_seconds == 120
    assert result.hourly_concentration == pytest.approx(sum(range(10, 33)) / 23)


def test_two_minute_30_of_30_qualifies() -> None:
    result = construct_subhourly_pm_hour(
        _observations(120, 30, value=10),
        interval_started_at=HOUR_START,
        parameter_code="pm25",
        input_unit="ug_m3",
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        timestamp_semantics="provider_received_at",
    )

    assert result.is_eligible
    assert result.valid_observation_count == 30
    assert result.missing_position_count == 0


@pytest.mark.parametrize("valid_count", (22, 1))
def test_two_minute_below_23_of_30_does_not_qualify(
    valid_count: int,
) -> None:
    result = construct_subhourly_pm_hour(
        _observations(120, valid_count),
        interval_started_at=HOUR_START,
        parameter_code="pm25",
        input_unit="ug_m3",
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        timestamp_semantics="provider_received_at",
    )

    assert not result.is_eligible
    assert result.exclusion_reason is ExclusionReason.HOURLY_COMPLETENESS_NOT_MET
    assert result.hourly_concentration is None


def test_invalid_and_duplicate_observations_do_not_inflate_completeness() -> None:
    observations = list(_observations(120, 22))
    observations.extend(
        (
            RawHourlyObservation(
                measurement_id=100,
                observed_at=HOUR_START + timedelta(seconds=120),
                concentration=999,
                is_valid=True,
            ),
            RawHourlyObservation(
                measurement_id=101,
                observed_at=HOUR_START + timedelta(seconds=24 * 120),
                concentration=999,
                is_valid=False,
            ),
        )
    )
    result = construct_subhourly_pm_hour(
        observations,
        interval_started_at=HOUR_START,
        parameter_code="pm25",
        input_unit="ug_m3",
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        timestamp_semantics="provider_received_at",
    )

    assert not result.is_eligible
    assert result.valid_observation_count == 22
    assert result.duplicate_measurement_ids == (100,)
    assert result.rejected_measurement_ids == (101,)
    assert result.exclusion_reasons == (
        ExclusionReason.HOURLY_COMPLETENESS_NOT_MET,
    )
    assert result.audit_flags == (
        HourlyCompletenessAuditFlag.DUPLICATE_OBSERVATION_INTERVAL,
        HourlyCompletenessAuditFlag.INVALID_OBSERVATIONS_REJECTED,
    )


def test_duplicate_and_invalid_extras_are_non_blocking_audit_flags() -> None:
    observations = list(_observations(120, 23))
    observations.extend(
        (
            RawHourlyObservation(
                measurement_id=100,
                observed_at=HOUR_START + timedelta(seconds=120),
                concentration=999,
                is_valid=True,
            ),
            RawHourlyObservation(
                measurement_id=101,
                observed_at=HOUR_START + timedelta(seconds=24 * 120),
                concentration=999,
                is_valid=False,
            ),
        )
    )

    result = construct_subhourly_pm_hour(
        observations,
        interval_started_at=HOUR_START,
        parameter_code="pm25",
        input_unit="ug_m3",
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        timestamp_semantics="provider_received_at",
    )

    assert result.is_eligible
    assert result.exclusion_reason is None
    assert result.exclusion_reasons == ()
    assert result.audit_flags == (
        HourlyCompletenessAuditFlag.DUPLICATE_OBSERVATION_INTERVAL,
        HourlyCompletenessAuditFlag.INVALID_OBSERVATIONS_REJECTED,
    )


def test_off_frequency_extra_is_a_non_blocking_audit_flag() -> None:
    observations = _observations(120, 23) + (
        RawHourlyObservation(
            measurement_id=100,
            observed_at=HOUR_START - timedelta(seconds=1),
            concentration=999,
            is_valid=True,
        ),
    )

    result = construct_subhourly_pm_hour(
        observations,
        interval_started_at=HOUR_START,
        parameter_code="pm10",
        input_unit="ug_m3",
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        timestamp_semantics="provider_received_at",
    )

    assert result.is_eligible
    assert result.exclusion_reasons == ()
    assert result.audit_flags == (
        HourlyCompletenessAuditFlag.OFF_FREQUENCY_OBSERVATIONS,
    )


def test_zero_valid_observations_has_only_blocking_reasons() -> None:
    result = construct_subhourly_pm_hour(
        (),
        interval_started_at=HOUR_START,
        parameter_code="pm25",
        input_unit="ug_m3",
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        timestamp_semantics="provider_received_at",
    )

    assert not result.is_eligible
    assert result.exclusion_reasons == (
        ExclusionReason.NO_VALID_OBSERVATIONS,
        ExclusionReason.HOURLY_COMPLETENESS_NOT_MET,
    )
    assert result.audit_flags == ()


def test_slight_drift_and_input_order_produce_stable_assignments() -> None:
    observations = _observations(120, 23, timestamp_drift_seconds=12)
    forward = assign_observations_to_expected_positions(
        observations,
        interval_started_at=HOUR_START,
        target_duration_seconds=3600,
        expected_frequency_seconds=120,
        expected_observation_count=30,
        timestamp_semantics="provider_received_at",
        parameter_code="pm25",
        input_unit="ug_m3",
    )
    reverse = assign_observations_to_expected_positions(
        tuple(reversed(observations)),
        interval_started_at=HOUR_START,
        target_duration_seconds=3600,
        expected_frequency_seconds=120,
        expected_observation_count=30,
        timestamp_semantics="provider_received_at",
        parameter_code="pm25",
        input_unit="ug_m3",
    )

    assert forward == reverse
    assert len(forward.accepted_observations) == 23


def test_clustered_and_outside_observations_do_not_fill_distinct_positions() -> None:
    observations = tuple(
        RawHourlyObservation(
            measurement_id=index,
            observed_at=HOUR_START + timedelta(seconds=120 + index),
            concentration=10,
            is_valid=True,
        )
        for index in range(1, 24)
    ) + (
        RawHourlyObservation(
            measurement_id=99,
            observed_at=HOUR_START - timedelta(seconds=1),
            concentration=10,
            is_valid=True,
        ),
    )
    assignment = assign_observations_to_expected_positions(
        observations,
        interval_started_at=HOUR_START,
        target_duration_seconds=3600,
        expected_frequency_seconds=120,
        expected_observation_count=30,
        timestamp_semantics="provider_received_at",
        parameter_code="pm25",
        input_unit="ug_m3",
    )

    assert len(assignment.accepted_observations) == 1
    assert len(assignment.duplicate_measurement_ids) == 22
    assert assignment.off_frequency_measurement_ids == (99,)
    assert assignment.missing_position_count == 29


@pytest.mark.parametrize(
    ("frequency_seconds", "valid_count", "expected_count", "required_count"),
    (
        (60, 45, 60, 45),
        (300, 9, 12, 9),
        (600, 5, 6, 5),
        (900, 3, 4, 3),
    ),
)
def test_supported_subhourly_frequencies_qualify_at_required_count(
    frequency_seconds: int,
    valid_count: int,
    expected_count: int,
    required_count: int,
) -> None:
    result = construct_subhourly_pm_hour(
        _observations(frequency_seconds, valid_count),
        interval_started_at=HOUR_START,
        parameter_code="pm10",
        input_unit="ug_m3",
        expected_frequency_seconds=frequency_seconds,
        measurement_duration_seconds=frequency_seconds,
        source_aggregation_duration_seconds=frequency_seconds,
        timestamp_semantics="interval_end",
    )

    assert result.is_eligible
    assert result.expected_observation_count == expected_count
    assert result.required_valid_observation_count == required_count


def test_one_minute_44_and_one_of_60_fail() -> None:
    for valid_count in (44, 1):
        result = construct_subhourly_pm_hour(
            _observations(60, valid_count),
            interval_started_at=HOUR_START,
            parameter_code="pm25",
            input_unit="ug_m3",
            expected_frequency_seconds=60,
            measurement_duration_seconds=60,
            source_aggregation_duration_seconds=60,
            timestamp_semantics="interval_end",
        )
        assert not result.is_eligible
        assert result.required_valid_observation_count == 45


def test_one_minute_duplicate_does_not_turn_44_positions_into_45() -> None:
    observations = _observations(60, 44) + (
        RawHourlyObservation(
            measurement_id=100,
            observed_at=HOUR_START + timedelta(seconds=65),
            concentration=999,
            is_valid=True,
        ),
    )
    result = construct_subhourly_pm_hour(
        observations,
        interval_started_at=HOUR_START,
        parameter_code="pm25",
        input_unit="ug_m3",
        expected_frequency_seconds=60,
        measurement_duration_seconds=60,
        source_aggregation_duration_seconds=60,
        timestamp_semantics="interval_end",
    )

    assert not result.is_eligible
    assert result.valid_observation_count == 44
    assert len(result.duplicate_measurement_ids) == 1


def test_verified_provider_hourly_requires_exactly_one_value() -> None:
    one = construct_provider_hourly_pm_hour(
        (
            RawHourlyObservation(
                measurement_id=1,
                observed_at=HOUR_START + timedelta(hours=1),
                concentration=12,
                is_valid=True,
            ),
        ),
        interval_started_at=HOUR_START,
        parameter_code="pm25",
        input_unit="ug_m3",
        timestamp_semantics="hour_end",
    )
    duplicate = construct_provider_hourly_pm_hour(
        (
            RawHourlyObservation(1, HOUR_START, 12, True),
            RawHourlyObservation(
                2,
                HOUR_START + timedelta(minutes=5),
                13,
                True,
            ),
        ),
        interval_started_at=HOUR_START,
        parameter_code="pm25",
        input_unit="ug_m3",
        timestamp_semantics="hour_start",
    )

    assert one.is_eligible
    assert one.expected_observation_count == 1
    assert one.required_valid_observation_count == 1
    assert not duplicate.is_eligible
    assert duplicate.exclusion_reason is (
        ExclusionReason.DUPLICATE_OBSERVATION_INTERVAL
    )
    assert duplicate.duplicate_measurement_ids == (2,)
    assert duplicate.off_frequency_measurement_ids == (2,)
