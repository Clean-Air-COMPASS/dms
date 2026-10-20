from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import models
from db import SessionLocal
from qaqc.admin_policy import (
    InvalidPolicyOverride,
    OverrideValue,
    PolicyScope,
    build_rule_replacement,
)
from qaqc.policy import (
    _ordered_rule_layers,
    get_qc_check_codes_for_sensor,
    resolve_effective_qc_policy,
)
from qaqc.policy_defaults import (
    ACTIVE_DEFAULT_POLICY_PROFILE_VERSION,
    DEFAULT_QC_POLICY_PROFILES,
    DEFAULT_QC_POLICIES,
    DEFAULT_POLICY_PROFILE_VERSION,
    FLAG_FOR_REVIEW,
    MARK_INVALID,
    canonicalize_qc_parameter_code,
    get_default_qc_policy,
)
from qaqc.rules import min_value as qc_min


def _unit(session, code: str, symbol: str | None = None) -> models.Unit:
    existing = session.scalar(select(models.Unit).where(models.Unit.code == code))
    if existing:
        return existing
    row = models.Unit(code=code, symbol=symbol or code, name=f"Test {code}")
    session.add(row)
    session.flush()
    return row


def _parameter(
    session,
    code: str,
    unit: models.Unit,
    display_name: str | None = None,
) -> models.Parameter:
    existing = session.scalar(
        select(models.Parameter).where(models.Parameter.code == code)
    )
    if existing:
        return existing
    row = models.Parameter(
        code=code,
        display_name=display_name or code,
        default_unit_id=unit.unit_id,
    )
    session.add(row)
    session.flush()
    session.add(
        models.ParameterSupportedUnit(
            parameter_id=row.parameter_id,
            unit_id=unit.unit_id,
        )
    )
    session.flush()
    return row


def _sensor_context(
    session,
    parameter_code: str = "pm25",
    unit_code: str = "ug_m3",
    source_name: str | None = None,
) -> tuple[models.ExternalAPI, models.Device, models.Sensor, models.Parameter, models.Unit]:
    suffix = uuid.uuid4().hex
    unit = _unit(session, unit_code)
    parameter = _parameter(session, parameter_code, unit)
    source = models.ExternalAPI(
        provider_code=f"qc-{suffix}",
        name=source_name or f"QC source {suffix}",
        params={},
    )
    session.add(source)
    session.flush()
    device = models.Device(
        name=f"QC device {suffix}",
        external_id=f"device-{suffix}",
        external_api_id=source.external_api_id,
    )
    session.add(device)
    session.flush()
    sensor = models.Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        external_sensor_id=f"sensor-{suffix}",
    )
    session.add(sensor)
    session.flush()
    return source, device, sensor, parameter, unit


def test_explicit_defaults_and_aliases_are_versioned():
    pm25_min = get_default_qc_policy("pm25", "ug_m3", "min_value")
    assert pm25_min is not None
    assert pm25_min.enabled is True
    assert pm25_min.settings == {"min": -10.0}
    assert pm25_min.policy_unit_code == "ug_m3"
    assert pm25_min.profile_version == DEFAULT_POLICY_PROFILE_VERSION
    assert canonicalize_qc_parameter_code("temp") == "temperature"
    assert canonicalize_qc_parameter_code("relativehumidity") == "relative_humidity"

    no_min = get_default_qc_policy("no", "ppb", "min_value")
    assert no_min is None
    assert ACTIVE_DEFAULT_POLICY_PROFILE_VERSION == "2026.2"
    assert tuple(DEFAULT_QC_POLICY_PROFILES) == ("2026.2",)


@pytest.mark.parametrize(
    "parameter_code,unit_code,minimum,maximum",
    [
        ("pm25", "ug_m3", -10.0, 10_000.0),
        ("pm10", "ug_m3", -50.0, 17_000.0),
        ("o3", "ppm", -0.004, 0.5),
        ("no2", "ppm", -0.005, 4.0),
        ("so2", "ppm", -0.004, 10.0),
        ("co", "ppm", -0.4, 50.0),
        ("temperature", "celsius", -90.0, 60.0),
        ("relative_humidity", "percent", 0.0, 100.0),
        ("tvoc_index", "index", 0.0, 500.0),
        ("nox_index", "index", 0.0, 500.0),
    ],
)
def test_every_enabled_default_has_explicit_boundaries(
    parameter_code, unit_code, minimum, maximum
):
    minimum_policy = DEFAULT_QC_POLICIES[(parameter_code, unit_code, "min_value")]
    maximum_policy = DEFAULT_QC_POLICIES[(parameter_code, unit_code, "max_value")]
    assert minimum_policy.enabled is True
    assert maximum_policy.enabled is True
    assert minimum_policy.settings == {"min": minimum}
    assert maximum_policy.settings == {"max": maximum}
    assert qc_min.evaluate(minimum, minimum) is True
    assert qc_min.evaluate(minimum - 0.000001, minimum) is False


@pytest.mark.parametrize(
    "parameter_code,unit_code,max_drift_per_day",
    [
        ("pm1", "ug_m3", 5.0),
        ("pm25", "ug_m3", 5.0),
        ("pm10", "ug_m3", 10.0),
        ("o3", "ppm", 0.003),
        ("no2", "ppm", 0.003),
        ("so2", "ppm", 0.003),
        ("co", "ppm", 0.4),
    ],
)
def test_baseline_drift_screening_presets_are_disabled_and_unit_specific(
    parameter_code, unit_code, max_drift_per_day
):
    policy = get_default_qc_policy(
        parameter_code, unit_code, "baseline_drift"
    )
    assert policy is not None
    assert policy.enabled is False
    assert policy.failure_action == FLAG_FOR_REVIEW
    assert policy.policy_unit_code == unit_code
    assert policy.settings == {
        "lookback_hours": 168,
        "min_samples": 72,
        "baseline_quantile": 0.1,
        "max_drift_per_day": max_drift_per_day,
        "direction": "both",
    }


@pytest.mark.parametrize(
    "parameter_code,unit_code",
    [
        ("no", "ppb"),
        ("nox", "ppm"),
        ("temperature", "celsius"),
        ("relative_humidity", "percent"),
        ("pressure", "hpa"),
        ("tvoc", "ug_m3"),
        ("tvoc_index", "index"),
        ("nox_index", "index"),
    ],
)
def test_unapproved_baseline_drift_defaults_remain_disabled(
    parameter_code, unit_code
):
    policy = get_default_qc_policy(
        parameter_code, unit_code, "baseline_drift"
    )
    assert policy is not None
    assert policy.enabled is False
    assert policy.settings == {}


def test_default_policy_resolves_without_qc_rule_rows():
    with SessionLocal() as session:
        _, _, sensor, _, _ = _sensor_context(session)
        policy = resolve_effective_qc_policy(session, sensor.sensor_id, "min_value")

        assert policy.status == "ready"
        assert policy.enabled is True
        assert policy.failure_action == FLAG_FOR_REVIEW
        assert policy.configured_settings == {"min": -10.0}
        assert policy.evaluation_settings == {"min": -10.0}
        assert policy.unit_conversion["status"] == "exact"
        assert policy.property_provenance["settings.min"].layer == "compassaq_default"
        assert policy.default_profile_version == "2026.2"


@pytest.mark.parametrize(
    "unit_code",
    ["kelvin", "hpa", "arbitrary_test_unit"],
)
def test_exact_supported_unit_codes_resolve_min_and_max_rules(unit_code):
    with SessionLocal() as session:
        _, _, sensor, parameter, unit = _sensor_context(
            session,
            parameter_code=f"exact_unit_{unit_code}_{uuid.uuid4().hex}",
            unit_code=unit_code,
        )
        session.add_all(
            [
                models.QCRule(
                    check_code="min_value",
                    parameter_id=parameter.parameter_id,
                    enabled_override=True,
                    failure_action_override=FLAG_FOR_REVIEW,
                    settings={"min": 0.0},
                    policy_unit_id=unit.unit_id,
                ),
                models.QCRule(
                    check_code="max_value",
                    parameter_id=parameter.parameter_id,
                    enabled_override=True,
                    failure_action_override=FLAG_FOR_REVIEW,
                    settings={"max": 100.0},
                    policy_unit_id=unit.unit_id,
                ),
            ]
        )
        session.flush()

        for check_code, expected_settings in (
            ("min_value", {"min": 0.0}),
            ("max_value", {"max": 100.0}),
        ):
            policy = resolve_effective_qc_policy(
                session, sensor.sensor_id, check_code
            )
            assert policy.status == "ready"
            assert policy.configured_settings == expected_settings
            assert policy.evaluation_settings == expected_settings
            assert policy.configured_unit_code == unit_code
            assert policy.unit_conversion["status"] == "exact"
            assert policy.unit_conversion["factor"] == 1.0
            assert policy.unit_conversion["normalized_configured_unit_code"] == unit_code
            assert policy.unit_conversion["normalized_evaluation_unit_code"] == unit_code


def test_different_unknown_unit_codes_do_not_match():
    with SessionLocal() as session:
        sensor_unit_code = f"sensor_unit_{uuid.uuid4().hex}"
        policy_unit_code = f"policy_unit_{uuid.uuid4().hex}"
        _, _, sensor, parameter, _ = _sensor_context(
            session,
            parameter_code=f"unknown_units_{uuid.uuid4().hex}",
            unit_code=sensor_unit_code,
        )
        policy_unit = _unit(session, policy_unit_code)
        session.add(
            models.ParameterSupportedUnit(
                parameter_id=parameter.parameter_id,
                unit_id=policy_unit.unit_id,
            )
        )
        session.add(
            models.QCRule(
                check_code="max_value",
                parameter_id=parameter.parameter_id,
                enabled_override=True,
                failure_action_override=FLAG_FOR_REVIEW,
                settings={"max": 100.0},
                policy_unit_id=policy_unit.unit_id,
            )
        )
        session.flush()

        policy = resolve_effective_qc_policy(session, sensor.sensor_id, "max_value")

        assert policy.status == "not_configured"
        assert policy.reason_code == "no_matching_rule"


def test_partial_overrides_follow_exact_deterministic_precedence():
    with SessionLocal() as session:
        source, _, sensor, parameter, unit = _sensor_context(session)
        session.add_all(
            [
                models.QCRule(
                    check_code="min_value",
                    parameter_id=parameter.parameter_id,
                    failure_action_override=MARK_INVALID,
                    policy_unit_id=unit.unit_id,
                ),
                models.QCRule(
                    check_code="min_value",
                    parameter_id=parameter.parameter_id,
                    external_api_id=source.external_api_id,
                    settings={"min": -5.0},
                    policy_unit_id=unit.unit_id,
                ),
                models.QCRule(
                    check_code="min_value",
                    sensor_id=sensor.sensor_id,
                    settings={"min": -2.0},
                    policy_unit_id=unit.unit_id,
                ),
                models.QCRule(
                    check_code="min_value",
                    sensor_id=sensor.sensor_id,
                    aggregate_code="1h",
                    settings={"min": -1.0},
                    policy_unit_id=unit.unit_id,
                ),
            ]
        )
        session.flush()

        generic = resolve_effective_qc_policy(
            session, sensor.sensor_id, "min_value", "24h"
        )
        hourly = resolve_effective_qc_policy(
            session, sensor.sensor_id, "min_value", "1h"
        )

        assert generic.evaluation_settings["min"] == -2.0
        assert generic.failure_action == MARK_INVALID
        assert generic.property_provenance["settings.min"].layer == "sensor_override"
        assert generic.property_provenance["failure_action"].layer == "parameter_override"
        assert hourly.evaluation_settings["min"] == -1.0
        assert hourly.property_provenance["settings.min"].layer == "sensor_aggregate_override"
        assert [layer.layer for layer in hourly.applied_layers] == [
            "compassaq_default",
            "parameter_override",
            "source_override",
            "sensor_override",
            "sensor_aggregate_override",
        ]


def test_disable_reenable_and_removal_restore_inherited_state():
    with SessionLocal() as session:
        _, _, sensor, parameter, ppb = _sensor_context(
            session, parameter_code="no", unit_code="ppb"
        )
        missing_default = resolve_effective_qc_policy(
            session, sensor.sensor_id, "min_value"
        )
        assert missing_default.status == "not_configured"

        parameter_rule = models.QCRule(
            check_code="min_value",
            parameter_id=parameter.parameter_id,
            enabled_override=True,
            failure_action_override=FLAG_FOR_REVIEW,
            settings={"min": 0.0},
            policy_unit_id=ppb.unit_id,
        )
        session.add(parameter_rule)
        session.flush()
        reenabled = resolve_effective_qc_policy(
            session, sensor.sensor_id, "min_value"
        )
        assert reenabled.status == "ready"
        assert reenabled.enabled is True

        sensor_rule = models.QCRule(
            check_code="min_value",
            sensor_id=sensor.sensor_id,
            enabled_override=False,
            policy_unit_id=ppb.unit_id,
        )
        session.add(sensor_rule)
        session.flush()
        explicitly_disabled = resolve_effective_qc_policy(
            session, sensor.sensor_id, "min_value"
        )
        assert explicitly_disabled.status == "disabled"
        assert explicitly_disabled.property_provenance["enabled"].layer == "sensor_override"

        session.delete(sensor_rule)
        session.flush()
        inherited_again = resolve_effective_qc_policy(
            session, sensor.sensor_id, "min_value"
        )
        assert inherited_again.status == "ready"
        assert inherited_again.property_provenance["enabled"].layer == "parameter_override"


def test_reenabled_incomplete_policy_is_explicitly_unavailable():
    with SessionLocal() as session:
        _, _, sensor, parameter, ppb = _sensor_context(
            session, parameter_code="no", unit_code="ppb"
        )
        session.add(
            models.QCRule(
                check_code="min_value",
                parameter_id=parameter.parameter_id,
                enabled_override=True,
                failure_action_override=FLAG_FOR_REVIEW,
                policy_unit_id=ppb.unit_id,
            )
        )
        session.flush()
        policy = resolve_effective_qc_policy(session, sensor.sensor_id, "min_value")
        assert policy.status == "unavailable"
        assert policy.reason_code == "missing_required_setting"


def test_safe_unit_conversion_and_unsupported_gas_conversion():
    with SessionLocal() as session:
        _, _, ppb_sensor, _, _ = _sensor_context(
            session, parameter_code="o3", unit_code="ppb"
        )
        converted = resolve_effective_qc_policy(
            session, ppb_sensor.sensor_id, "max_value"
        )
        assert converted.status == "ready"
        assert converted.configured_settings["max"] == 0.5
        assert converted.evaluation_settings["max"] == 500.0
        assert converted.unit_conversion["factor"] == 1000.0

        ppm_source, _, ppm_sensor, ppm_parameter, _ = _sensor_context(
            session, parameter_code="o3", unit_code="ppm"
        )
        ppb_unit = _unit(session, "ppb")
        session.add(
            models.QCRule(
                check_code="max_value",
                parameter_id=ppm_parameter.parameter_id,
                external_api_id=ppm_source.external_api_id,
                settings={"max": 500.0},
                policy_unit_id=ppb_unit.unit_id,
            )
        )
        session.flush()
        to_ppm = resolve_effective_qc_policy(
            session, ppm_sensor.sensor_id, "max_value"
        )
        assert to_ppm.evaluation_settings["max"] == 0.5
        assert to_ppm.unit_conversion["factor"] == 0.001

        _, _, mass_sensor, _, _ = _sensor_context(
            session, parameter_code="o3", unit_code="ug_m3"
        )
        unsupported = resolve_effective_qc_policy(
            session, mass_sensor.sensor_id, "max_value"
        )
        assert unsupported.status == "not_configured"
        assert unsupported.reason_code == "no_matching_rule"
        assert unsupported.applicability == "not_applicable"


def test_baseline_drift_converts_ppm_to_ppb_but_not_to_gas_mass_units():
    with SessionLocal() as session:
        _, _, ppb_sensor, _, _ = _sensor_context(
            session, parameter_code="o3", unit_code="ppb"
        )
        ppm_unit = session.scalar(
            select(models.Unit).where(models.Unit.code == "ppm")
        )
        assert ppm_unit is not None
        session.add(
            models.QCRule(
                check_code="baseline_drift",
                sensor_id=ppb_sensor.sensor_id,
                enabled_override=True,
                policy_unit_id=ppm_unit.unit_id,
            )
        )
        session.flush()
        ppb_policy = resolve_effective_qc_policy(
            session, ppb_sensor.sensor_id, "baseline_drift"
        )
        assert ppb_policy.status == "ready"
        assert ppb_policy.configured_unit_code == "ppm"
        assert ppb_policy.evaluation_unit_code == "ppb"
        assert ppb_policy.evaluation_settings["max_drift_per_day"] == 3.0
        assert ppb_policy.unit_conversion["factor"] == 1000.0

        _, _, mass_sensor, _, _ = _sensor_context(
            session, parameter_code="o3", unit_code="ug_m3"
        )
        mass_policy = resolve_effective_qc_policy(
            session, mass_sensor.sensor_id, "baseline_drift"
        )
        assert mass_policy.status == "not_configured"
        assert mass_policy.reason_code == "no_matching_rule"


def test_mass_conversion_both_directions_and_unit_alias_provenance():
    with SessionLocal() as session:
        _, _, mass_sensor, _, _ = _sensor_context(
            session, parameter_code="pm25", unit_code="mg_m3"
        )
        to_milligrams = resolve_effective_qc_policy(
            session, mass_sensor.sensor_id, "max_value"
        )
        assert to_milligrams.evaluation_settings["max"] == 10.0
        assert to_milligrams.unit_conversion["factor"] == 0.001

        source, _, microgram_sensor, parameter, _ = _sensor_context(
            session, parameter_code="pm25", unit_code="ug_m3"
        )
        milligram_unit = _unit(session, "mg_m3")
        session.add(
            models.QCRule(
                check_code="max_value",
                parameter_id=parameter.parameter_id,
                external_api_id=source.external_api_id,
                settings={"max": 1.0},
                policy_unit_id=milligram_unit.unit_id,
            )
        )
        session.flush()
        to_micrograms = resolve_effective_qc_policy(
            session, microgram_sensor.sensor_id, "max_value"
        )
        assert to_micrograms.evaluation_settings["max"] == 1000.0
        assert to_micrograms.unit_conversion["factor"] == 1000.0
        assert to_micrograms.property_provenance["unit"].layer == "source_override"

        _, _, temperature_sensor, _, _ = _sensor_context(
            session, parameter_code="temp", unit_code="celsius"
        )
        temperature = resolve_effective_qc_policy(
            session, temperature_sensor.sensor_id, "max_value"
        )
        assert temperature.status == "ready"
        assert temperature.unit_conversion["status"] == "exact"
        assert temperature.unit_conversion["normalized_evaluation_unit_code"] == "c"


@pytest.mark.parametrize("check_code", ["min_value", "baseline_drift"])
def test_unit_scoped_policy_without_unit_is_rejected_by_plugin_aware_service(check_code):
    with SessionLocal() as session:
        _, _, sensor, parameter, _ = _sensor_context(
            session, parameter_code="no", unit_code="ppb"
        )
        with pytest.raises(InvalidPolicyOverride) as error:
            build_rule_replacement(
                session,
                PolicyScope("parameter", parameter_id=parameter.parameter_id),
                [
                    OverrideValue(
                        check_code=check_code,
                        enabled_override=True,
                        failure_action_override="flag_for_review",
                        settings={"min": 0.0},
                        policy_unit_code=None,
                    )
                ],
            )
        assert error.value.reason_code == "missing_policy_unit"


def test_unknown_unit_and_unknown_parameter_are_explicit():
    with SessionLocal() as session:
        _, _, unknown_unit_sensor, _, _ = _sensor_context(
            session, parameter_code="pm25", unit_code="furlongs"
        )
        unknown_unit = resolve_effective_qc_policy(
            session, unknown_unit_sensor.sensor_id, "min_value"
        )
        assert unknown_unit.status == "not_configured"
        assert unknown_unit.reason_code == "no_matching_rule"

        _, _, unknown_parameter_sensor, _, _ = _sensor_context(
            session, parameter_code=f"unknown_{uuid.uuid4().hex}", unit_code="ug_m3"
        )
        unknown_parameter = resolve_effective_qc_policy(
            session, unknown_parameter_sensor.sensor_id, "min_value"
        )
        assert unknown_parameter.status == "not_configured"
        assert unknown_parameter.reason_code == "no_matching_rule"


def test_duplicate_override_scope_is_rejected_by_database():
    with SessionLocal() as session:
        _, _, _, parameter, unit = _sensor_context(session)
        session.add(
            models.QCRule(
                check_code="min_value",
                parameter_id=parameter.parameter_id,
                settings={"min": -1},
                policy_unit_id=unit.unit_id,
            )
        )
        session.flush()
        session.add(
            models.QCRule(
                check_code="min_value",
                parameter_id=parameter.parameter_id,
                settings={"min": -2},
                policy_unit_id=unit.unit_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_resolver_detects_ambiguous_unit_rows_even_if_constraints_are_bypassed():
    with SessionLocal() as session:
        source, _, sensor, parameter, unit = _sensor_context(session)
        duplicate_rules = [
            models.QCRule(check_code="min_value", parameter_id=parameter.parameter_id, policy_unit_id=unit.unit_id),
            models.QCRule(check_code="min_value", parameter_id=parameter.parameter_id, policy_unit_id=unit.unit_id),
        ]
        ordered, ambiguity = _ordered_rule_layers(
            session,
            duplicate_rules,
            "min_value",
            unit.code,
            None,
            parameter,
            source,
            sensor,
        )
        assert ordered == []
        assert ambiguity == "Multiple parameter_override rows match this policy unit"


def test_check_discovery_uses_defaults_and_matching_overrides_only():
    with SessionLocal() as session:
        _, _, sensor, _, _ = _sensor_context(session)
        session.add(
            models.QCRule(
                check_code="custom_check",
                sensor_id=sensor.sensor_id,
                enabled_override=True,
                failure_action_override=FLAG_FOR_REVIEW,
                settings={"limit": 1},
            )
        )
        session.flush()
        assert get_qc_check_codes_for_sensor(session, sensor.sensor_id) == (
            "min_value",
            "max_value",
            "baseline_drift",
            "custom_check",
        )
