"""Authoritative QC policy resolution.

The resolver is the only place where CompassAQ defaults and administrator
overrides are combined. Plugins receive the resulting policy and never query
``QCRule`` themselves.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

import models
from qaqc.policy_defaults import (
    BUILT_IN_CHECK_ORDER,
    DEFAULT_POLICY_PROFILE_VERSION,
    FAILURE_ACTIONS,
    canonicalize_qc_parameter_code,
    get_default_check_codes,
    get_default_qc_policies,
    get_default_unit_settings,
)
from qaqc.registry import all_registrations, get_registration


PolicyStatus = Literal["ready", "disabled", "not_configured", "unavailable"]
PolicyApplicability = Literal["applicable", "not_applicable"]


@dataclass(frozen=True)
class PolicyLayer:
    layer: str
    label: str
    qc_rule_id: int | None = None
    rule_version: int | None = None
    default_profile_version: str | None = None
    policy_unit_code: str | None = None


@dataclass
class EffectiveQCPolicy:
    check_code: str
    status: PolicyStatus
    enabled: bool
    failure_action: str | None
    configured_settings: dict[str, Any] = field(default_factory=dict)
    evaluation_settings: dict[str, Any] = field(default_factory=dict)
    configured_unit_code: str | None = None
    evaluation_unit_code: str | None = None
    applicable_unit_code: str | None = None
    unit_conversion: dict[str, Any] | None = None
    reason_code: str | None = None
    message: str = ""
    # ``not_applicable`` is reserved for deterministic resolver decisions
    # where the rule cannot be used for this stream. It is different from an
    # applicable rule that later becomes indeterminate during evaluation.
    applicability: PolicyApplicability = "applicable"
    default_profile_version: str = DEFAULT_POLICY_PROFILE_VERSION
    applied_layers: list[PolicyLayer] = field(default_factory=list)
    most_specific_source: PolicyLayer | None = None
    property_provenance: dict[str, PolicyLayer] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_no_matching_rule(policy: EffectiveQCPolicy) -> bool:
    """Return whether no configured rule applies to this measurement unit."""

    return policy.status == "not_configured"


@dataclass(frozen=True)
class PolicyRuleReplacement:
    """Unsaved generic overrides used for policy preview.

    The replacement affects one exact scope while all lower and higher layers
    continue to come from the database. Aggregation-specific rules are never
    replaced by the ordinary administration API.
    """

    scope_type: Literal["parameter", "source_parameter", "sensor"]
    parameter_id: int | None = None
    external_api_id: int | None = None
    sensor_id: int | None = None
    rules: tuple[models.QCRule, ...] = ()


_UNIT_ALIASES = {
    "ppm": "ppm",
    "ppb": "ppb",
    "mg_m3": "mg_m3",
    "mg/m3": "mg_m3",
    "mg/m³": "mg_m3",
    "ug_m3": "ug_m3",
    "ug/m3": "ug_m3",
    "ug/m³": "ug_m3",
    "µg/m3": "ug_m3",
    "µg/m³": "ug_m3",
    "c": "c",
    "celsius": "c",
    "°c": "c",
    "%": "percent",
    "percent": "percent",
    "index": "index",
}

_CONVERSION_FACTORS = {
    ("ppm", "ppb"): 1_000.0,
    ("ppb", "ppm"): 0.001,
    ("mg_m3", "ug_m3"): 1_000.0,
    ("ug_m3", "mg_m3"): 0.001,
}

def normalize_qc_unit_code(unit_code: str) -> str | None:
    return _UNIT_ALIASES.get(unit_code.strip().lower())


def get_unit_settings_for_check(check_code: str) -> tuple[str, ...]:
    """Return the installed contract, or policy metadata while unavailable."""

    registration = get_registration(check_code)
    if registration is not None:
        return tuple(registration.metadata.unit_settings)
    return get_default_unit_settings(check_code)


def is_unit_scoped_check(check_code: str) -> bool:
    return bool(get_unit_settings_for_check(check_code))


def qc_check_order_key(check_code: str) -> tuple[int, str]:
    registration = get_registration(check_code)
    if registration is not None:
        return registration.metadata.overview.order, check_code
    try:
        fallback_order = BUILT_IN_CHECK_ORDER.index(check_code) * 10 + 10
    except ValueError:
        fallback_order = 1_000
    return fallback_order, check_code


def order_qc_check_codes(check_codes: set[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(check_codes, key=qc_check_order_key))


def qc_unit_match_rank(
    configured_unit_code: str,
    evaluation_unit_code: str,
) -> int | None:
    """Rank literal equality above aliases and approved conversions."""

    # Unit.code is the canonical identifier stored by the catalog. Exact
    # equality is safe even when a future parameter-specific unit is not in
    # this small registry of aliases and conversions.
    if configured_unit_code == evaluation_unit_code:
        return 0

    normalized_configured = normalize_qc_unit_code(configured_unit_code)
    normalized_evaluation = normalize_qc_unit_code(evaluation_unit_code)
    if normalized_configured is None or normalized_evaluation is None:
        return None
    if normalized_configured == normalized_evaluation:
        return 1
    if (normalized_configured, normalized_evaluation) in _CONVERSION_FACTORS:
        return 2
    return None


def _matching_default_policy(
    parameter_code: str,
    check_code: str,
    evaluation_unit_code: str | None,
) -> tuple[Any | None, str | None]:
    policies = get_default_qc_policies(parameter_code, check_code)
    if not is_unit_scoped_check(check_code):
        if len(policies) > 1:
            return None, "Multiple CompassAQ defaults match this check"
        return (policies[0] if policies else None), None
    if evaluation_unit_code is None:
        return None, None

    ranked = [
        (rank, policy)
        for policy in policies
        if policy.policy_unit_code is not None
        and (
            rank := qc_unit_match_rank(
                policy.policy_unit_code,
                evaluation_unit_code,
            )
        )
        is not None
    ]
    if not ranked:
        return None, None
    best_rank = min(rank for rank, _policy in ranked)
    best = [policy for rank, policy in ranked if rank == best_rank]
    if len(best) > 1:
        return None, "Multiple CompassAQ defaults match this policy unit"
    return best[0], None


def _unavailable_policy(
    check_code: str,
    reason_code: str,
    message: str,
    *,
    enabled: bool = False,
    applicability: PolicyApplicability = "applicable",
) -> EffectiveQCPolicy:
    return EffectiveQCPolicy(
        check_code=check_code,
        status="unavailable",
        enabled=enabled,
        failure_action=None,
        reason_code=reason_code,
        message=message,
        applicability=applicability,
    )


def _not_configured_policy(
    check_code: str,
    evaluation_unit_code: str | None,
    message: str,
) -> EffectiveQCPolicy:
    return EffectiveQCPolicy(
        check_code=check_code,
        status="not_configured",
        enabled=False,
        failure_action=None,
        evaluation_unit_code=evaluation_unit_code,
        applicable_unit_code=evaluation_unit_code,
        reason_code="no_matching_rule",
        message=message,
        applicability="not_applicable",
    )


def _rule_layer(
    rule: models.QCRule,
    layer: str,
    label: str,
    policy_unit_code: str | None = None,
) -> PolicyLayer:
    return PolicyLayer(
        layer=layer,
        label=label,
        qc_rule_id=rule.qc_rule_id,
        rule_version=rule.version,
        policy_unit_code=policy_unit_code,
    )


def _matching_rules(
    session: Session,
    parameter: models.Parameter,
    check_code: str,
    aggregate_code: str | None,
    source: models.ExternalAPI | None = None,
    sensor: models.Sensor | None = None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> list[models.QCRule]:
    aggregation_match = models.QCRule.aggregate_code.is_(None)
    if aggregate_code is not None:
        aggregation_match = or_(
            models.QCRule.aggregate_code.is_(None),
            models.QCRule.aggregate_code == aggregate_code,
        )

    scope_conditions = [
        and_(
            models.QCRule.sensor_id.is_(None),
            models.QCRule.parameter_id == parameter.parameter_id,
            models.QCRule.external_api_id.is_(None),
        )
    ]
    if source is not None:
        scope_conditions.append(
            and_(
                models.QCRule.sensor_id.is_(None),
                models.QCRule.parameter_id == parameter.parameter_id,
                models.QCRule.external_api_id == source.external_api_id,
            )
        )
    if sensor is not None:
        scope_conditions.append(
            and_(
                models.QCRule.sensor_id == sensor.sensor_id,
                models.QCRule.parameter_id.is_(None),
                models.QCRule.external_api_id.is_(None),
            )
        )
    rules = list(
        session.scalars(
            select(models.QCRule).where(
                models.QCRule.check_code == check_code,
                aggregation_match,
                or_(*scope_conditions),
            )
        ).all()
    )

    if rule_replacement is None:
        return rules

    replacement_applies = (
        rule_replacement.scope_type == "parameter"
        and rule_replacement.parameter_id == parameter.parameter_id
    ) or (
        rule_replacement.scope_type == "source_parameter"
        and source is not None
        and rule_replacement.parameter_id == parameter.parameter_id
        and rule_replacement.external_api_id == source.external_api_id
    ) or (
        rule_replacement.scope_type == "sensor"
        and sensor is not None
        and rule_replacement.sensor_id == sensor.sensor_id
    )
    if not replacement_applies:
        return rules

    def is_replaced_generic_scope(rule: models.QCRule) -> bool:
        if rule.aggregate_code is not None:
            return False
        if rule_replacement.scope_type == "parameter":
            return rule.sensor_id is None and rule.external_api_id is None
        if rule_replacement.scope_type == "source_parameter":
            return (
                rule.sensor_id is None
                and rule.external_api_id == rule_replacement.external_api_id
            )
        return rule.sensor_id == rule_replacement.sensor_id

    retained = [rule for rule in rules if not is_replaced_generic_scope(rule)]
    retained.extend(
        rule
        for rule in rule_replacement.rules
        if rule.check_code == check_code and rule.aggregate_code is None
    )
    return retained


def _ordered_rule_layers(
    session: Session,
    rules: list[models.QCRule],
    check_code: str,
    evaluation_unit_code: str | None,
    aggregate_code: str | None,
    parameter: models.Parameter,
    source: models.ExternalAPI | None,
    sensor: models.Sensor | None,
) -> tuple[list[tuple[PolicyLayer, models.QCRule]], str | None]:
    slots: dict[str, list[models.QCRule]] = {
        "parameter_override": [],
        "parameter_aggregate_override": [],
        "source_override": [],
        "source_aggregate_override": [],
        "sensor_override": [],
        "sensor_aggregate_override": [],
    }
    for rule in rules:
        is_aggregate = rule.aggregate_code is not None
        if is_aggregate and rule.aggregate_code != aggregate_code:
            continue
        if rule.sensor_id is not None:
            key = "sensor_aggregate_override" if is_aggregate else "sensor_override"
        elif rule.external_api_id is not None:
            key = "source_aggregate_override" if is_aggregate else "source_override"
        else:
            key = "parameter_aggregate_override" if is_aggregate else "parameter_override"
        slots[key].append(rule)

    selected_units: dict[str, str | None] = {}
    for layer_name, matching in slots.items():
        if is_unit_scoped_check(check_code):
            ranked: list[tuple[int, models.QCRule, str]] = []
            for rule in matching:
                if rule.policy_unit_id is None or evaluation_unit_code is None:
                    continue
                policy_unit = session.get(models.Unit, rule.policy_unit_id)
                if policy_unit is None:
                    continue
                rank = qc_unit_match_rank(policy_unit.code, evaluation_unit_code)
                if rank is not None:
                    ranked.append((rank, rule, policy_unit.code))
            if not ranked:
                slots[layer_name] = []
                continue
            best_rank = min(rank for rank, _rule, _unit_code in ranked)
            best = [entry for entry in ranked if entry[0] == best_rank]
            if len(best) > 1:
                return [], f"Multiple {layer_name} rows match this policy unit"
            _, selected_rule, selected_unit_code = best[0]
            slots[layer_name] = [selected_rule]
            selected_units[layer_name] = selected_unit_code
        elif len(matching) > 1:
            return [], f"Multiple {layer_name} rows match this policy context"

    labels = {
        "parameter_override": f"Administrator override for {parameter.display_name}",
        "parameter_aggregate_override": (
            f"Administrator override for {parameter.display_name} ({aggregate_code})"
        ),
        "source_override": (
            f"{source.name} {parameter.display_name} override"
            if source is not None
            else "Data source override"
        ),
        "source_aggregate_override": (
            f"{source.name} {parameter.display_name} override ({aggregate_code})"
            if source is not None
            else f"Data source override ({aggregate_code})"
        ),
        "sensor_override": (
            f"Custom for sensor {sensor.sensor_id}"
            if sensor is not None
            else "Sensor override"
        ),
        "sensor_aggregate_override": (
            f"Custom for sensor {sensor.sensor_id} ({aggregate_code})"
            if sensor is not None
            else f"Sensor override ({aggregate_code})"
        ),
    }
    ordered: list[tuple[PolicyLayer, models.QCRule]] = []
    for layer_name in slots:
        if slots[layer_name]:
            rule = slots[layer_name][0]
            policy_unit_code = selected_units.get(layer_name)
            if policy_unit_code is None and rule.policy_unit_id is not None:
                policy_unit = session.get(models.Unit, rule.policy_unit_id)
                policy_unit_code = policy_unit.code if policy_unit is not None else None
            ordered.append(
                (
                    _rule_layer(
                        rule,
                        layer_name,
                        labels[layer_name],
                        policy_unit_code,
                    ),
                    rule,
                )
            )
    return ordered, None


def _validate_settings(check_code: str, settings: dict[str, Any]) -> tuple[str | None, str]:
    registration = get_registration(check_code)
    parameter_schema = (
        registration.metadata.param_schema if registration is not None else {}
    )
    required_settings = (
        tuple(
            setting_name
            for setting_name, setting_schema in parameter_schema.items()
            if setting_schema.get("required") is True
        )
        if parameter_schema
        else ()
    )
    for setting_name in required_settings:
        if setting_name not in settings:
            return "missing_required_setting", f"{check_code} requires '{setting_name}'"

    if parameter_schema:
        unknown_settings = sorted(set(settings) - set(parameter_schema))
        if unknown_settings:
            return (
                "invalid_policy_setting",
                f"{check_code} does not define setting '{unknown_settings[0]}'",
            )
        for setting_name, raw_value in settings.items():
            setting_schema = parameter_schema[setting_name]
            setting_type = setting_schema["type"]
            if setting_type == "boolean" and not isinstance(raw_value, bool):
                return "invalid_policy_setting", f"'{setting_name}' must be boolean"
            if setting_type == "string" and not isinstance(raw_value, str):
                return "invalid_policy_setting", f"'{setting_name}' must be a string"
            if setting_type in {"integer", "number"}:
                if isinstance(raw_value, bool):
                    return "invalid_policy_setting", f"'{setting_name}' must be numeric"
                try:
                    numeric_value = float(raw_value)
                except (TypeError, ValueError):
                    return "invalid_policy_setting", f"'{setting_name}' must be numeric"
                if not math.isfinite(numeric_value):
                    return "invalid_policy_setting", f"'{setting_name}' must be finite"
                if setting_type == "integer" and numeric_value != int(numeric_value):
                    return "invalid_policy_setting", f"'{setting_name}' must be an integer"
            choices = setting_schema.get("choices")
            if choices is not None and raw_value not in choices:
                return (
                    "invalid_policy_setting",
                    f"'{setting_name}' must be one of {', '.join(map(str, choices))}",
                )
            if setting_type in {"integer", "number"}:
                minimum = setting_schema.get("minimum")
                maximum = setting_schema.get("maximum")
                numeric_value = float(raw_value)
                if minimum is not None and numeric_value < float(minimum):
                    return (
                        "invalid_policy_setting",
                        f"'{setting_name}' must be at least {minimum}",
                    )
                if maximum is not None and numeric_value > float(maximum):
                    return (
                        "invalid_policy_setting",
                        f"'{setting_name}' must be at most {maximum}",
                    )

    return None, ""


def _convert_settings(
    check_code: str,
    settings: dict[str, Any],
    configured_unit_code: str,
    sensor_unit_code: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None, str]:
    normalized_configured = normalize_qc_unit_code(configured_unit_code)
    normalized_sensor = normalize_qc_unit_code(sensor_unit_code)
    if configured_unit_code == sensor_unit_code:
        # Exact catalog-code equality does not depend on the global alias
        # registry. This keeps parameter-specific supported units usable.
        normalized_configured = normalized_configured or configured_unit_code
        normalized_sensor = normalized_sensor or sensor_unit_code
        factor = 1.0
        conversion_status = "exact"
    elif normalized_configured is None or normalized_sensor is None:
        return None, None, "unknown_unit", "Policy or sensor unit is not recognized"
    elif normalized_configured == normalized_sensor:
        factor = 1.0
        conversion_status = "exact"
    else:
        factor = _CONVERSION_FACTORS.get((normalized_configured, normalized_sensor))
        if factor is None:
            return (
                None,
                None,
                "conversion_not_supported",
                f"Cannot safely convert {configured_unit_code} to {sensor_unit_code}",
            )
        conversion_status = "converted"

    evaluation_settings = dict(settings)
    registration = get_registration(check_code)
    convertible_names = (
        tuple(registration.metadata.unit_settings)
        if registration is not None
        else get_default_unit_settings(check_code)
    )
    for setting_name in convertible_names:
        if setting_name in evaluation_settings:
            evaluation_settings[setting_name] = float(evaluation_settings[setting_name]) * factor

    conversion = {
        "status": conversion_status,
        "configured_unit_code": configured_unit_code,
        "normalized_configured_unit_code": normalized_configured,
        "evaluation_unit_code": sensor_unit_code,
        "normalized_evaluation_unit_code": normalized_sensor,
        "factor": factor,
    }
    return evaluation_settings, conversion, None, ""


def _resolve_qc_policy_for_context(
    session: Session,
    parameter: models.Parameter,
    check_code: str,
    evaluation_unit_code: str | None,
    *,
    source: models.ExternalAPI | None = None,
    sensor: models.Sensor | None = None,
    aggregate_code: str | None = None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> EffectiveQCPolicy:
    canonical_parameter_code = canonicalize_qc_parameter_code(parameter.code)
    default_policy, default_ambiguity = _matching_default_policy(
        canonical_parameter_code,
        check_code,
        evaluation_unit_code,
    )
    if default_ambiguity:
        return _unavailable_policy(
            check_code,
            "ambiguous_policy",
            default_ambiguity,
            enabled=True,
        )
    rules = _matching_rules(
        session,
        parameter,
        check_code,
        aggregate_code,
        source=source,
        sensor=sensor,
        rule_replacement=rule_replacement,
    )
    ordered_rules, ambiguity = _ordered_rule_layers(
        session,
        rules,
        check_code,
        evaluation_unit_code,
        aggregate_code,
        parameter,
        source,
        sensor,
    )
    if ambiguity:
        return _unavailable_policy(check_code, "ambiguous_policy", ambiguity)
    if default_policy is None and not ordered_rules:
        unit_suffix = (
            f" in {evaluation_unit_code}" if evaluation_unit_code is not None else ""
        )
        return _not_configured_policy(
            check_code,
            evaluation_unit_code,
            f"No {check_code} rule is configured for {parameter.display_name}{unit_suffix}",
        )

    registration = get_registration(check_code)
    unit_setting_names = (
        tuple(registration.metadata.unit_settings)
        if registration is not None
        else get_default_unit_settings(check_code)
    )

    enabled: bool | None = None
    failure_action: str | None = None
    configured_settings: dict[str, Any] = {}
    configured_unit_code: str | None = None
    property_provenance: dict[str, PolicyLayer] = {}
    applied_layers: list[PolicyLayer] = []

    if default_policy is not None:
        default_layer = PolicyLayer(
            layer="compassaq_default",
            label=f"CompassAQ {parameter.display_name} default",
            default_profile_version=default_policy.profile_version,
            policy_unit_code=default_policy.policy_unit_code,
        )
        applied_layers.append(default_layer)
        enabled = default_policy.enabled
        failure_action = default_policy.failure_action
        configured_settings.update(dict(default_policy.settings))
        configured_unit_code = default_policy.policy_unit_code
        property_provenance["enabled"] = default_layer
        property_provenance["failure_action"] = default_layer
        if configured_unit_code is not None:
            property_provenance["unit"] = default_layer
        for setting_name in configured_settings:
            property_provenance[f"settings.{setting_name}"] = default_layer

    for layer, rule in ordered_rules:
        applied_layers.append(layer)
        if rule.enabled_override is not None:
            enabled = rule.enabled_override
            property_provenance["enabled"] = layer
        if rule.failure_action_override is not None:
            failure_action = rule.failure_action_override
            property_provenance["failure_action"] = layer
        if rule.policy_unit_id is not None:
            policy_unit = session.get(models.Unit, rule.policy_unit_id)
            if policy_unit is None:
                return _unavailable_policy(
                    check_code,
                    "unknown_unit",
                    f"QC rule {rule.qc_rule_id} references an unknown policy unit",
                    enabled=bool(enabled),
                )
            if not is_unit_scoped_check(check_code) or any(
                setting_name in (rule.settings or {})
                for setting_name in unit_setting_names
            ):
                configured_unit_code = policy_unit.code
                property_provenance["unit"] = layer
        if rule.settings is not None:
            if not isinstance(rule.settings, dict):
                return _unavailable_policy(
                    check_code,
                    "invalid_policy_setting",
                    f"QC rule {rule.qc_rule_id} settings must be an object",
                    enabled=bool(enabled),
                )
            for setting_name, setting_value in rule.settings.items():
                configured_settings[setting_name] = setting_value
                property_provenance[f"settings.{setting_name}"] = layer

    most_specific_source = applied_layers[-1] if applied_layers else None
    if enabled is not True:
        if enabled is False:
            return EffectiveQCPolicy(
                check_code=check_code,
                status="disabled",
                enabled=False,
                failure_action=failure_action,
                configured_settings=configured_settings,
                configured_unit_code=configured_unit_code,
                evaluation_unit_code=evaluation_unit_code,
                applicable_unit_code=evaluation_unit_code,
                reason_code="disabled",
                message="The effective QC policy is disabled",
                applied_layers=applied_layers,
                most_specific_source=most_specific_source,
                property_provenance=property_provenance,
            )
        return EffectiveQCPolicy(
            check_code=check_code,
            status="unavailable",
            enabled=False,
            failure_action=failure_action,
            configured_settings=configured_settings,
            configured_unit_code=configured_unit_code,
            evaluation_unit_code=evaluation_unit_code,
            applicable_unit_code=evaluation_unit_code,
            reason_code="missing_enabled_state",
            message="The QC policy does not resolve an enabled state",
            applied_layers=applied_layers,
            most_specific_source=most_specific_source,
            property_provenance=property_provenance,
        )

    if failure_action not in FAILURE_ACTIONS:
        return EffectiveQCPolicy(
            check_code=check_code,
            status="unavailable",
            enabled=True,
            failure_action=failure_action,
            configured_settings=configured_settings,
            configured_unit_code=configured_unit_code,
            evaluation_unit_code=evaluation_unit_code,
            applicable_unit_code=evaluation_unit_code,
            reason_code="missing_failure_action",
            message="The enabled QC policy has no valid failure action",
            applied_layers=applied_layers,
            most_specific_source=most_specific_source,
            property_provenance=property_provenance,
        )

    settings_reason, settings_message = _validate_settings(check_code, configured_settings)
    if settings_reason:
        return EffectiveQCPolicy(
            check_code=check_code,
            status="unavailable",
            enabled=True,
            failure_action=failure_action,
            configured_settings=configured_settings,
            configured_unit_code=configured_unit_code,
            evaluation_unit_code=evaluation_unit_code,
            applicable_unit_code=evaluation_unit_code,
            reason_code=settings_reason,
            message=settings_message,
            applied_layers=applied_layers,
            most_specific_source=most_specific_source,
            property_provenance=property_provenance,
        )

    requires_unit = bool(unit_setting_names)
    if requires_unit and configured_unit_code is None:
        return EffectiveQCPolicy(
            check_code=check_code,
            status="unavailable",
            enabled=True,
            failure_action=failure_action,
            configured_settings=configured_settings,
            evaluation_unit_code=evaluation_unit_code,
            applicable_unit_code=evaluation_unit_code,
            reason_code="missing_policy_unit",
            message="The enabled QC policy has no policy unit",
            applied_layers=applied_layers,
            most_specific_source=most_specific_source,
            property_provenance=property_provenance,
        )
    if requires_unit:
        if evaluation_unit_code is None:
            return EffectiveQCPolicy(
                check_code=check_code,
                status="unavailable",
                enabled=True,
                failure_action=failure_action,
                configured_settings=configured_settings,
                configured_unit_code=configured_unit_code,
                evaluation_unit_code=evaluation_unit_code,
                applicable_unit_code=evaluation_unit_code,
                reason_code="unknown_unit",
                message="The policy evaluation context has no unit",
                applied_layers=applied_layers,
                most_specific_source=most_specific_source,
                property_provenance=property_provenance,
            )
        evaluation_settings, conversion, unit_reason, unit_message = _convert_settings(
            check_code,
            configured_settings,
            configured_unit_code or "",
            evaluation_unit_code,
        )
        if unit_reason:
            return EffectiveQCPolicy(
                check_code=check_code,
                status="unavailable",
                enabled=True,
                failure_action=failure_action,
                configured_settings=configured_settings,
                configured_unit_code=configured_unit_code,
                evaluation_unit_code=evaluation_unit_code,
                applicable_unit_code=evaluation_unit_code,
                reason_code=unit_reason,
                message=unit_message,
                applied_layers=applied_layers,
                most_specific_source=most_specific_source,
                property_provenance=property_provenance,
            )
    else:
        evaluation_settings = dict(configured_settings)
        conversion = None

    return EffectiveQCPolicy(
        check_code=check_code,
        status="ready",
        enabled=True,
        failure_action=failure_action,
        configured_settings=configured_settings,
        evaluation_settings=evaluation_settings or {},
        configured_unit_code=configured_unit_code,
        evaluation_unit_code=evaluation_unit_code,
        applicable_unit_code=evaluation_unit_code,
        unit_conversion=conversion,
        applied_layers=applied_layers,
        most_specific_source=most_specific_source,
        property_provenance=property_provenance,
    )


def resolve_parameter_qc_policy(
    session: Session,
    parameter_id: int,
    check_code: str,
    evaluation_unit_code: str | None,
    aggregate_code: str | None = None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> EffectiveQCPolicy:
    parameter = session.get(models.Parameter, parameter_id)
    if parameter is None:
        return _unavailable_policy(
            check_code,
            "parameter_not_found",
            f"Parameter {parameter_id} was not found",
        )
    return _resolve_qc_policy_for_context(
        session,
        parameter,
        check_code,
        evaluation_unit_code,
        aggregate_code=aggregate_code,
        rule_replacement=rule_replacement,
    )


def resolve_source_parameter_qc_policy(
    session: Session,
    external_api_id: int,
    parameter_id: int,
    check_code: str,
    evaluation_unit_code: str | None,
    aggregate_code: str | None = None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> EffectiveQCPolicy:
    parameter = session.get(models.Parameter, parameter_id)
    if parameter is None:
        return _unavailable_policy(
            check_code,
            "parameter_not_found",
            f"Parameter {parameter_id} was not found",
        )
    source = session.get(models.ExternalAPI, external_api_id)
    if source is None:
        return _unavailable_policy(
            check_code,
            "data_source_not_found",
            f"Data source {external_api_id} was not found",
        )
    return _resolve_qc_policy_for_context(
        session,
        parameter,
        check_code,
        evaluation_unit_code,
        source=source,
        aggregate_code=aggregate_code,
        rule_replacement=rule_replacement,
    )


def resolve_effective_qc_policy(
    session: Session,
    sensor_id: int,
    check_code: str,
    aggregate_code: str | None = None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> EffectiveQCPolicy:
    sensor = session.get(models.Sensor, sensor_id)
    if sensor is None:
        return _unavailable_policy(
            check_code,
            "sensor_not_found",
            f"Sensor {sensor_id} was not found",
        )
    if sensor.parameter_id is None:
        return _unavailable_policy(
            check_code,
            "sensor_parameter_missing",
            f"Sensor {sensor_id} has no parameter",
        )
    parameter = session.get(models.Parameter, sensor.parameter_id)
    if parameter is None:
        return _unavailable_policy(
            check_code,
            "unsupported_parameter",
            "Sensor parameter was not found",
        )
    device = session.get(models.Device, sensor.device_id)
    if device is None:
        return _unavailable_policy(
            check_code,
            "sensor_device_missing",
            "Sensor device was not found",
        )
    source = session.get(models.ExternalAPI, device.external_api_id)
    if source is None:
        return _unavailable_policy(
            check_code,
            "data_source_missing",
            "Sensor data source was not found",
        )
    sensor_unit = (
        session.get(models.Unit, sensor.unit_id)
        if sensor.unit_id is not None
        else None
    )
    return _resolve_qc_policy_for_context(
        session,
        parameter,
        check_code,
        sensor_unit.code if sensor_unit is not None else None,
        source=source,
        sensor=sensor,
        aggregate_code=aggregate_code,
        rule_replacement=rule_replacement,
    )


def _get_qc_check_codes_for_context(
    session: Session,
    parameter: models.Parameter,
    *,
    source: models.ExternalAPI | None = None,
    sensor: models.Sensor | None = None,
    aggregate_code: str | None = None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> tuple[str, ...]:
    registrations = all_registrations()
    candidate_codes = set(get_default_check_codes(parameter.code))
    aggregation_match = models.QCRule.aggregate_code.is_(None)
    if aggregate_code is not None:
        aggregation_match = or_(
            models.QCRule.aggregate_code.is_(None),
            models.QCRule.aggregate_code == aggregate_code,
        )
    scope_conditions = [
        and_(
            models.QCRule.sensor_id.is_(None),
            models.QCRule.parameter_id == parameter.parameter_id,
            models.QCRule.external_api_id.is_(None),
        )
    ]
    if source is not None:
        scope_conditions.append(
            and_(
                models.QCRule.sensor_id.is_(None),
                models.QCRule.parameter_id == parameter.parameter_id,
                models.QCRule.external_api_id == source.external_api_id,
            )
        )
    if sensor is not None:
        scope_conditions.append(models.QCRule.sensor_id == sensor.sensor_id)
    candidate_codes.update(
        session.scalars(
            select(models.QCRule.check_code).where(
                aggregation_match,
                or_(*scope_conditions),
            )
        ).all()
    )
    if rule_replacement is not None:
        candidate_codes.update(rule.check_code for rule in rule_replacement.rules)

    codes = {
        check_code
        for check_code in candidate_codes
        if check_code in registrations
        or get_default_qc_policies(parameter.code, check_code)
        or _matching_rules(
            session,
            parameter,
            check_code,
            aggregate_code,
            source=source,
            sensor=sensor,
            rule_replacement=rule_replacement,
        )
    }
    return order_qc_check_codes(codes)


def get_qc_check_codes_for_parameter(
    session: Session,
    parameter_id: int,
    aggregate_code: str | None = None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> tuple[str, ...]:
    parameter = session.get(models.Parameter, parameter_id)
    if parameter is None:
        return ()
    return _get_qc_check_codes_for_context(
        session,
        parameter,
        aggregate_code=aggregate_code,
        rule_replacement=rule_replacement,
    )


def get_qc_check_codes_for_source_parameter(
    session: Session,
    external_api_id: int,
    parameter_id: int,
    aggregate_code: str | None = None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> tuple[str, ...]:
    parameter = session.get(models.Parameter, parameter_id)
    source = session.get(models.ExternalAPI, external_api_id)
    if parameter is None or source is None:
        return ()
    return _get_qc_check_codes_for_context(
        session,
        parameter,
        source=source,
        aggregate_code=aggregate_code,
        rule_replacement=rule_replacement,
    )


def get_qc_check_codes_for_sensor(
    session: Session,
    sensor_id: int,
    aggregate_code: str | None = None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> tuple[str, ...]:
    sensor = session.get(models.Sensor, sensor_id)
    if sensor is None or sensor.parameter_id is None:
        return ()
    parameter = session.get(models.Parameter, sensor.parameter_id)
    device = session.get(models.Device, sensor.device_id)
    source = (
        session.get(models.ExternalAPI, device.external_api_id)
        if device is not None
        else None
    )
    if parameter is None or source is None:
        return ()
    return _get_qc_check_codes_for_context(
        session,
        parameter,
        source=source,
        sensor=sensor,
        aggregate_code=aggregate_code,
        rule_replacement=rule_replacement,
    )
