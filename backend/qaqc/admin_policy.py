"""High-level QC administration services used by the Phase 1B API.

This module translates human policy scopes into sparse ``QCRule`` overrides.
It deliberately does not expose raw database-row editing as the primary API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

import models
from qaqc.policy import (
    EffectiveQCPolicy,
    PolicyRuleReplacement,
    get_qc_check_codes_for_parameter,
    get_qc_check_codes_for_sensor,
    get_qc_check_codes_for_source_parameter,
    is_unit_scoped_check,
    order_qc_check_codes,
    qc_check_order_key,
    qc_unit_match_rank,
    resolve_effective_qc_policy,
    resolve_parameter_qc_policy,
    resolve_source_parameter_qc_policy,
)
from qaqc.policy_defaults import (
    DEFAULT_POLICY_PROFILE_VERSION,
    FAILURE_ACTIONS,
    get_all_default_check_codes,
    get_default_check_codes,
    get_default_qc_policies,
    get_default_unit_settings,
)
from qaqc.pipeline import run_ingest_detailed
from qaqc.registry import all_registrations
from qaqc.types import QCRecord


ScopeType = Literal["parameter", "source_parameter", "sensor"]


@dataclass(frozen=True)
class PolicyScope:
    scope_type: ScopeType
    parameter_id: int | None = None
    external_api_id: int | None = None
    sensor_id: int | None = None


@dataclass(frozen=True)
class OverrideValue:
    check_code: str
    enabled_override: bool | None
    failure_action_override: str | None
    settings: dict[str, Any]
    policy_unit_code: str | None

    @property
    def has_override(self) -> bool:
        return (
            self.enabled_override is not None
            or self.failure_action_override is not None
            or bool(self.settings)
        )


class InvalidPolicyOverride(ValueError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


def _unit_dict(unit: models.Unit | None) -> dict[str, Any] | None:
    if unit is None:
        return None
    return {
        "unit_id": unit.unit_id,
        "unit_code": unit.code,
        "symbol": unit.symbol,
        "name": unit.name,
    }


def _parameter_dict(
    parameter: models.Parameter,
    default_unit: models.Unit | None,
) -> dict[str, Any]:
    supported_units = sorted(
        (
            association.unit
            for association in parameter.supported_units
            if association.unit is not None
        ),
        key=lambda unit: (unit.symbol.lower(), unit.code),
    )
    return {
        "parameter_id": parameter.parameter_id,
        "parameter_code": parameter.code,
        "display_name": parameter.display_name,
        "default_unit": _unit_dict(default_unit),
        "supported_units": [_unit_dict(unit) for unit in supported_units],
    }


def _source_dict(source: models.ExternalAPI) -> dict[str, Any]:
    return {
        "external_api_id": source.external_api_id,
        "provider_code": source.provider_code,
        "name": source.name,
    }


def _sensor_dict(
    sensor: models.Sensor,
    device: models.Device,
    source: models.ExternalAPI,
    parameter: models.Parameter,
    parameter_default_unit: models.Unit | None,
    sensor_unit: models.Unit | None,
    aggregation: models.AggregationPeriod | None,
) -> dict[str, Any]:
    device_name = device.friendly_name or device.name
    return {
        "sensor_id": sensor.sensor_id,
        "external_sensor_id": sensor.external_sensor_id,
        "device_id": device.device_id,
        "device_name": device_name,
        "manual_data_source_name": device.manual_data_source_name,
        "display_label": f"{device_name} · {parameter.display_name} · {device.manual_data_source_name or source.name}",
        "parameter": _parameter_dict(parameter, parameter_default_unit),
        "unit": _unit_dict(sensor_unit),
        "data_source": _source_dict(source),
        "aggregation_code": aggregation.code if aggregation is not None else None,
    }


def get_check_metadata() -> list[dict[str, Any]]:
    registrations = all_registrations()
    check_codes = set(get_all_default_check_codes())
    check_codes.update(registrations)

    result: list[dict[str, Any]] = []
    for check_code in order_qc_check_codes(check_codes):
        registration = registrations.get(check_code)
        metadata = registration.metadata if registration is not None else None
        raw_schema = metadata.param_schema if metadata is not None else None
        settings: list[dict[str, Any]] = []
        if isinstance(raw_schema, dict):
            for setting_code, raw_setting in raw_schema.items():
                setting = raw_setting if isinstance(raw_setting, dict) else {}
                setting_metadata = {
                    "setting_code": setting_code,
                    "value_type": setting.get("type", "string"),
                    "label": setting.get("label", setting_code),
                    "help_text": setting.get("help", ""),
                    "required": bool(setting.get("required", False)),
                    "choices": setting.get("choices"),
                }
                if "minimum" in setting:
                    setting_metadata["minimum"] = setting["minimum"]
                if "maximum" in setting:
                    setting_metadata["maximum"] = setting["maximum"]
                settings.append(setting_metadata)
        result.append(
            {
                "check_code": check_code,
                "display_name": metadata.display_name if metadata else check_code,
                "description": metadata.long_description if metadata else "",
                "available": registration is not None,
                "plugin_version": metadata.version if metadata else None,
                "qc_api": metadata.qc_api if metadata else None,
                "origin": metadata.origin if metadata else None,
                "required_access": metadata.required_access if metadata else None,
                "unit_settings": (
                    metadata.unit_settings
                    if metadata
                    else list(get_default_unit_settings(check_code))
                ),
                "overview": (
                    {
                        "visible": metadata.overview.visible,
                        "label": metadata.overview.label,
                        "order": metadata.overview.order,
                        "summary_setting": metadata.overview.summary_setting,
                    }
                    if metadata
                    else {
                        "visible": True,
                        "label": check_code,
                        "order": qc_check_order_key(check_code)[0],
                        "summary_setting": None,
                    }
                ),
                "settings": settings,
                "failure_actions": ["flag_for_review", "mark_invalid"],
            }
        )
    return result


def _scope_entities(
    session: Session,
    scope: PolicyScope,
) -> tuple[
    models.Parameter,
    models.Unit | None,
    models.ExternalAPI | None,
    models.Sensor | None,
    models.Device | None,
    models.Unit | None,
    models.AggregationPeriod | None,
]:
    source: models.ExternalAPI | None = None
    sensor: models.Sensor | None = None
    device: models.Device | None = None
    sensor_unit: models.Unit | None = None
    aggregation: models.AggregationPeriod | None = None

    if scope.scope_type == "sensor":
        if scope.sensor_id is None:
            raise InvalidPolicyOverride("sensor_required", "sensor_id is required")
        sensor = session.get(models.Sensor, scope.sensor_id)
        if sensor is None:
            raise InvalidPolicyOverride("sensor_not_found", "Sensor not found")
        if sensor.parameter_id is None:
            raise InvalidPolicyOverride(
                "sensor_parameter_missing", "Sensor has no parameter"
            )
        parameter = session.get(models.Parameter, sensor.parameter_id)
        device = session.get(models.Device, sensor.device_id)
        if parameter is None or device is None:
            raise InvalidPolicyOverride(
                "sensor_context_incomplete", "Sensor parameter or device is unavailable"
            )
        source = session.get(models.ExternalAPI, device.external_api_id)
        if source is None:
            raise InvalidPolicyOverride(
                "data_source_not_found", "Sensor data source is unavailable"
            )
        sensor_unit = (
            session.get(models.Unit, sensor.unit_id)
            if sensor.unit_id is not None
            else None
        )
        aggregation = (
            session.get(models.AggregationPeriod, sensor.aggregation_period_id)
            if sensor.aggregation_period_id is not None
            else None
        )
    else:
        if scope.parameter_id is None:
            raise InvalidPolicyOverride("parameter_required", "parameter_id is required")
        parameter = session.get(models.Parameter, scope.parameter_id)
        if parameter is None:
            raise InvalidPolicyOverride("parameter_not_found", "Parameter not found")
        if scope.scope_type == "source_parameter":
            if scope.external_api_id is None:
                raise InvalidPolicyOverride(
                    "data_source_required", "external_api_id is required"
                )
            source = session.get(models.ExternalAPI, scope.external_api_id)
            if source is None:
                raise InvalidPolicyOverride(
                    "data_source_not_found", "Data source not found"
                )

    default_unit = session.get(models.Unit, parameter.default_unit_id)
    return (
        parameter,
        default_unit,
        source,
        sensor,
        device,
        sensor_unit,
        aggregation,
    )


def _scope_rule_conditions(scope: PolicyScope) -> list[Any]:
    conditions: list[Any] = [models.QCRule.aggregate_code.is_(None)]
    if scope.scope_type == "parameter":
        conditions.extend(
            [
                models.QCRule.parameter_id == scope.parameter_id,
                models.QCRule.external_api_id.is_(None),
                models.QCRule.sensor_id.is_(None),
            ]
        )
    elif scope.scope_type == "source_parameter":
        conditions.extend(
            [
                models.QCRule.parameter_id == scope.parameter_id,
                models.QCRule.external_api_id == scope.external_api_id,
                models.QCRule.sensor_id.is_(None),
            ]
        )
    else:
        conditions.extend(
            [
                models.QCRule.sensor_id == scope.sensor_id,
                models.QCRule.parameter_id.is_(None),
                models.QCRule.external_api_id.is_(None),
            ]
        )
    return conditions


def get_generic_scope_rules(
    session: Session,
    scope: PolicyScope,
) -> list[models.QCRule]:
    return list(
        session.scalars(
            select(models.QCRule)
            .where(*_scope_rule_conditions(scope))
            .order_by(models.QCRule.check_code, models.QCRule.qc_rule_id)
        ).all()
    )


def _serialize_override(session: Session, rule: models.QCRule) -> dict[str, Any]:
    policy_unit = (
        session.get(models.Unit, rule.policy_unit_id)
        if rule.policy_unit_id is not None
        else None
    )
    overridden_properties: list[str] = []
    if rule.enabled_override is not None:
        overridden_properties.append("enabled")
    if rule.failure_action_override is not None:
        overridden_properties.append("failure_action")
    if rule.policy_unit_id is not None:
        overridden_properties.append("unit")
    overridden_properties.extend(f"settings.{name}" for name in sorted(rule.settings or {}))
    return {
        "qc_rule_id": rule.qc_rule_id,
        "check_code": rule.check_code,
        "enabled_override": rule.enabled_override,
        "failure_action_override": rule.failure_action_override,
        "settings": dict(rule.settings or {}),
        "policy_unit": _unit_dict(policy_unit),
        "version": rule.version,
        "overridden_properties": overridden_properties,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def _policy_for_scope(
    session: Session,
    scope: PolicyScope,
    check_code: str,
    evaluation_unit_code: str | None,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> EffectiveQCPolicy:
    if scope.scope_type == "parameter":
        return resolve_parameter_qc_policy(
            session,
            scope.parameter_id or 0,
            check_code,
            evaluation_unit_code,
            rule_replacement=rule_replacement,
        )
    if scope.scope_type == "source_parameter":
        return resolve_source_parameter_qc_policy(
            session,
            scope.external_api_id or 0,
            scope.parameter_id or 0,
            check_code,
            evaluation_unit_code,
            rule_replacement=rule_replacement,
        )
    return resolve_effective_qc_policy(
        session,
        scope.sensor_id or 0,
        check_code,
        rule_replacement=rule_replacement,
    )


def _check_codes_for_scope(
    session: Session,
    scope: PolicyScope,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> tuple[str, ...]:
    if scope.scope_type == "parameter":
        return get_qc_check_codes_for_parameter(
            session,
            scope.parameter_id or 0,
            rule_replacement=rule_replacement,
        )
    if scope.scope_type == "source_parameter":
        return get_qc_check_codes_for_source_parameter(
            session,
            scope.external_api_id or 0,
            scope.parameter_id or 0,
            rule_replacement=rule_replacement,
        )
    return get_qc_check_codes_for_sensor(
        session,
        scope.sensor_id or 0,
        rule_replacement=rule_replacement,
    )


def build_policy_response(
    session: Session,
    scope: PolicyScope,
    rule_replacement: PolicyRuleReplacement | None = None,
) -> dict[str, Any]:
    (
        parameter,
        default_unit,
        source,
        sensor,
        device,
        sensor_unit,
        aggregation,
    ) = _scope_entities(session, scope)
    rules = get_generic_scope_rules(session, scope)
    if rule_replacement is not None:
        rules = list(rule_replacement.rules)

    check_codes = set(_check_codes_for_scope(session, scope, rule_replacement))
    # Editors expose every installed plugin even before policy is configured.
    # The overview summary path stays sparse so an unconfigured plugin does not
    # add one resolver query per parameter.
    check_codes.update(all_registrations())
    ordered_check_codes = order_qc_check_codes(check_codes)
    unit_scoped_check_codes = {
        check_code for check_code in check_codes if is_unit_scoped_check(check_code)
    }
    # Resolve the policy that would remain after removing this exact generic
    # scope. The administration UI uses this read-only result to explain reset
    # behavior without duplicating defaults or precedence rules in React.
    inherited_replacement = PolicyRuleReplacement(
        scope_type=scope.scope_type,
        parameter_id=scope.parameter_id,
        external_api_id=scope.external_api_id,
        sensor_id=scope.sensor_id,
        rules=(),
    )
    checks: list[dict[str, Any]] = []

    if sensor is not None:
        unit_scoped_policy_units = [sensor_unit] if sensor_unit is not None else []
    else:
        unit_scoped_policy_units = sorted(
            (
                association.unit
                for association in parameter.supported_units
                if association.unit is not None
            ),
            key=lambda unit: (unit.symbol.lower(), unit.code),
        )

    def append_resolved_check(
        check_code: str,
        evaluation_unit_code: str | None,
    ) -> None:
        check = _policy_for_scope(
            session,
            scope,
            check_code,
            evaluation_unit_code,
            rule_replacement,
        ).to_dict()
        check["inherited_policy"] = _policy_for_scope(
            session,
            scope,
            check_code,
            evaluation_unit_code,
            inherited_replacement,
        ).to_dict()
        checks.append(check)

    for unit in unit_scoped_policy_units:
        for check_code in ordered_check_codes:
            if check_code not in unit_scoped_check_codes:
                continue
            append_resolved_check(check_code, unit.code)
    for check_code in ordered_check_codes:
        if check_code in unit_scoped_check_codes:
            continue
        append_resolved_check(
            check_code,
            sensor_unit.code if sensor_unit is not None else default_unit.code,
        )
    response: dict[str, Any] = {
        "scope": {
            "scope_type": scope.scope_type,
            "parameter_id": parameter.parameter_id,
            "external_api_id": source.external_api_id if source is not None else None,
            "sensor_id": sensor.sensor_id if sensor is not None else None,
        },
        "parameter": _parameter_dict(parameter, default_unit),
        "data_source": _source_dict(source) if source is not None else None,
        "sensor": (
            _sensor_dict(
                sensor,
                device,
                source,
                parameter,
                default_unit,
                sensor_unit,
                aggregation,
            )
            if sensor is not None and device is not None and source is not None
            else None
        ),
        "default_profile_version": DEFAULT_POLICY_PROFILE_VERSION,
        "overrides": [_serialize_override(session, rule) for rule in rules],
        "checks": checks,
    }

    advanced_conditions = _scope_rule_conditions(scope)[1:]
    response["advanced_aggregation_override_count"] = int(
        session.scalar(
            select(func.count())
            .select_from(models.QCRule)
            .where(
                *advanced_conditions,
                models.QCRule.aggregate_code.is_not(None),
            )
        )
        or 0
    )
    return response


def _transient_rule(
    session: Session,
    scope: PolicyScope,
    override: OverrideValue,
) -> models.QCRule:
    if override.failure_action_override not in FAILURE_ACTIONS | {None}:
        raise InvalidPolicyOverride(
            "invalid_failure_action",
            "failure_action_override must be flag_for_review, mark_invalid, or null",
        )
    (
        parameter,
        _default_unit,
        _source,
        sensor,
        _device,
        sensor_unit,
        _aggregation,
    ) = _scope_entities(session, scope)
    if is_unit_scoped_check(override.check_code) and override.policy_unit_code is None:
        raise InvalidPolicyOverride(
            "missing_policy_unit",
            "Every unit-scoped QC rule requires an explicit unit",
        )

    policy_unit_id = None
    if override.policy_unit_code is not None:
        policy_unit = session.scalar(
            select(models.Unit).where(models.Unit.code == override.policy_unit_code)
        )
        if policy_unit is None:
            raise InvalidPolicyOverride(
                "unknown_unit",
                f"Unknown policy unit '{override.policy_unit_code}'",
            )
        supported_unit_ids = {
            association.unit_id for association in parameter.supported_units
        }
        if policy_unit.unit_id not in supported_unit_ids:
            raise InvalidPolicyOverride(
                "unsupported_unit",
                f"Unit '{override.policy_unit_code}' is not supported for {parameter.code}",
            )
        if (
            sensor is not None
            and is_unit_scoped_check(override.check_code)
            and (
                sensor_unit is None
                or sensor_unit.unit_id != policy_unit.unit_id
            )
        ):
            raise InvalidPolicyOverride(
                "sensor_unit_mismatch",
                "A sensor range rule must use the sensor's measurement unit",
            )
        policy_unit_id = policy_unit.unit_id

    return models.QCRule(
        check_code=override.check_code,
        parameter_id=(
            scope.parameter_id if scope.scope_type != "sensor" else None
        ),
        external_api_id=(
            scope.external_api_id
            if scope.scope_type == "source_parameter"
            else None
        ),
        sensor_id=scope.sensor_id if scope.scope_type == "sensor" else None,
        aggregate_code=None,
        enabled_override=override.enabled_override,
        failure_action_override=override.failure_action_override,
        settings=dict(override.settings),
        policy_unit_id=policy_unit_id,
        version=1,
        state="active",
    )


def build_rule_replacement(
    session: Session,
    scope: PolicyScope,
    overrides: list[OverrideValue],
) -> PolicyRuleReplacement:
    _scope_entities(session, scope)
    seen: set[tuple[str, str | None]] = set()
    rules: list[models.QCRule] = []
    for override in overrides:
        if not override.check_code or len(override.check_code) > 64:
            raise InvalidPolicyOverride(
                "invalid_check_code", "check_code must be between 1 and 64 characters"
            )
        override_key = (
            override.check_code,
            override.policy_unit_code
            if is_unit_scoped_check(override.check_code)
            else None,
        )
        if override_key in seen:
            raise InvalidPolicyOverride(
                "duplicate_check_code",
                "Duplicate override for "
                f"'{override.check_code}' and unit '{override.policy_unit_code}'",
            )
        seen.add(override_key)
        if override.has_override:
            rules.append(_transient_rule(session, scope, override))
    return PolicyRuleReplacement(
        scope_type=scope.scope_type,
        parameter_id=scope.parameter_id,
        external_api_id=scope.external_api_id,
        sensor_id=scope.sensor_id,
        rules=tuple(rules),
    )


def validate_rule_replacement(
    session: Session,
    scope: PolicyScope,
    replacement: PolicyRuleReplacement,
) -> None:
    (
        parameter,
        default_unit,
        _source,
        sensor,
        _device,
        sensor_unit,
        _aggregation,
    ) = _scope_entities(session, scope)
    units = (
        [sensor_unit]
        if sensor is not None and sensor_unit is not None
        else [
            association.unit
            for association in parameter.supported_units
            if association.unit is not None
        ]
    )
    check_codes = set(_check_codes_for_scope(session, scope, replacement))
    unit_scoped_check_codes = {
        check_code for check_code in check_codes if is_unit_scoped_check(check_code)
    }
    contexts = [
        (check_code, unit.code)
        for check_code in unit_scoped_check_codes
        for unit in units
    ]
    contexts.extend(
        (check_code, sensor_unit.code if sensor_unit is not None else default_unit.code)
        for check_code in check_codes - unit_scoped_check_codes
    )
    for check_code, evaluation_unit_code in contexts:
        policy = _policy_for_scope(
            session,
            scope,
            check_code,
            evaluation_unit_code,
            replacement,
        )
        if policy.status == "unavailable" and policy.enabled:
            raise InvalidPolicyOverride(
                policy.reason_code or "policy_unavailable",
                policy.message or f"Invalid effective policy for '{check_code}'",
            )


def _rule_identity(rule: models.QCRule) -> tuple[str, int | None]:
    return (
        rule.check_code,
        rule.policy_unit_id if is_unit_scoped_check(rule.check_code) else None,
    )


def replace_generic_scope_overrides(
    session: Session,
    scope: PolicyScope,
    overrides: list[OverrideValue],
) -> dict[str, Any]:
    replacement = build_rule_replacement(session, scope, overrides)
    validate_rule_replacement(session, scope, replacement)

    existing_by_check = {
        _rule_identity(rule): rule for rule in get_generic_scope_rules(session, scope)
    }
    replacement_by_check = {
        _rule_identity(rule): rule for rule in replacement.rules
    }

    for rule_key, existing in existing_by_check.items():
        if rule_key not in replacement_by_check:
            session.delete(existing)

    for rule_key, candidate in replacement_by_check.items():
        existing = existing_by_check.get(rule_key)
        if existing is None:
            session.add(candidate)
            continue
        changed = any(
            (
                existing.enabled_override != candidate.enabled_override,
                existing.failure_action_override
                != candidate.failure_action_override,
                dict(existing.settings or {}) != dict(candidate.settings or {}),
                existing.policy_unit_id != candidate.policy_unit_id,
            )
        )
        if changed:
            existing.enabled_override = candidate.enabled_override
            existing.failure_action_override = candidate.failure_action_override
            existing.settings = dict(candidate.settings or {})
            existing.policy_unit_id = candidate.policy_unit_id
            existing.version = int(existing.version or 1) + 1
            existing.state = "active"
            existing.draft_settings = None
            session.add(existing)

    session.flush()
    return build_policy_response(session, scope)


def reset_scope_overrides(
    session: Session,
    scope: PolicyScope,
    check_code: str | None = None,
    policy_unit_code: str | None = None,
) -> dict[str, Any]:
    _scope_entities(session, scope)
    if check_code is not None and is_unit_scoped_check(check_code) and policy_unit_code is None:
        raise InvalidPolicyOverride(
            "missing_policy_unit",
            "Resetting a unit-scoped rule requires an explicit unit",
        )
    rules = get_generic_scope_rules(session, scope)
    for rule in rules:
        if check_code is not None and rule.check_code != check_code:
            continue
        if policy_unit_code is not None:
            policy_unit = (
                session.get(models.Unit, rule.policy_unit_id)
                if rule.policy_unit_id is not None
                else None
            )
            if policy_unit is None or policy_unit.code != policy_unit_code:
                continue
        session.delete(rule)
    session.flush()
    return build_policy_response(session, scope)


def _baseline_drift_override_counts(
    session: Session,
    parameters: list[models.Parameter],
    units: dict[int, models.Unit],
) -> dict[int, dict[str, int]]:
    """Summarize effective lower-scope Baseline Drift state in fixed queries."""
    counts = {
        parameter.parameter_id: {
            "source_override_count": 0,
            "sensor_override_count": 0,
            "enabled_source_count": 0,
            "enabled_sensor_count": 0,
        }
        for parameter in parameters
    }
    parameter_by_id = {
        parameter.parameter_id: parameter for parameter in parameters
    }
    rules = list(
        session.scalars(
            select(models.QCRule).where(
                models.QCRule.check_code == "baseline_drift",
                models.QCRule.aggregate_code.is_(None),
            )
        ).all()
    )
    if not rules:
        return counts

    sensor_ids = {
        rule.sensor_id for rule in rules if rule.sensor_id is not None
    }
    sensor_contexts = {}
    if sensor_ids:
        sensor_contexts = {
            sensor_id: (parameter_id, unit_id, external_api_id)
            for sensor_id, parameter_id, unit_id, external_api_id in session.execute(
                select(
                    models.Sensor.sensor_id,
                    models.Sensor.parameter_id,
                    models.Sensor.unit_id,
                    models.Device.external_api_id,
                )
                .join(models.Device, models.Device.device_id == models.Sensor.device_id)
                .where(models.Sensor.sensor_id.in_(sensor_ids))
            ).all()
        }

    parameter_rules: dict[int, list[models.QCRule]] = {}
    source_rules: dict[tuple[int, int], list[models.QCRule]] = {}
    sensor_rules: dict[int, list[models.QCRule]] = {}
    for rule in rules:
        if rule.sensor_id is not None:
            sensor_rules.setdefault(rule.sensor_id, []).append(rule)
        elif rule.external_api_id is not None and rule.parameter_id is not None:
            source_rules.setdefault(
                (rule.parameter_id, rule.external_api_id), []
            ).append(rule)
        elif rule.parameter_id is not None:
            parameter_rules.setdefault(rule.parameter_id, []).append(rule)

    def matching_rule(
        candidate_rules: list[models.QCRule],
        evaluation_unit_code: str,
    ) -> tuple[models.QCRule | None, bool]:
        ranked_rules = []
        for rule in candidate_rules:
            policy_unit = units.get(rule.policy_unit_id)
            if policy_unit is None:
                continue
            rank = qc_unit_match_rank(policy_unit.code, evaluation_unit_code)
            if rank is not None:
                ranked_rules.append((rank, rule))
        if not ranked_rules:
            return None, False
        best_rank = min(rank for rank, _rule in ranked_rules)
        best_rules = [rule for rank, rule in ranked_rules if rank == best_rank]
        if len(best_rules) != 1:
            return None, True
        return best_rules[0], False

    def effective_enabled(
        parameter_id: int,
        evaluation_unit_code: str,
        external_api_id: int | None = None,
        sensor_id: int | None = None,
    ) -> bool:
        parameter = parameter_by_id.get(parameter_id)
        if parameter is None:
            return False
        matching_defaults = []
        for default_policy in get_default_qc_policies(
            parameter.code, "baseline_drift"
        ):
            rank = qc_unit_match_rank(
                default_policy.policy_unit_code or "",
                evaluation_unit_code,
            )
            if rank is not None:
                matching_defaults.append((rank, default_policy.enabled))
        enabled: bool | None = None
        if matching_defaults:
            best_rank = min(rank for rank, _enabled in matching_defaults)
            best_defaults = [
                default_enabled
                for rank, default_enabled in matching_defaults
                if rank == best_rank
            ]
            if len(best_defaults) != 1:
                return False
            enabled = best_defaults[0]

        scope_rule_groups = [parameter_rules.get(parameter_id, [])]
        if external_api_id is not None:
            scope_rule_groups.append(
                source_rules.get((parameter_id, external_api_id), [])
            )
        if sensor_id is not None:
            scope_rule_groups.append(sensor_rules.get(sensor_id, []))
        for scope_rules in scope_rule_groups:
            rule, ambiguous = matching_rule(scope_rules, evaluation_unit_code)
            if ambiguous:
                return False
            if rule is not None and rule.enabled_override is not None:
                enabled = rule.enabled_override
        return enabled is True

    for (parameter_id, external_api_id), scoped_rules in source_rules.items():
        if parameter_id not in counts:
            continue
        counts[parameter_id]["source_override_count"] += 1
        evaluation_unit_codes = {
            units[rule.policy_unit_id].code
            for rule in scoped_rules
            if rule.policy_unit_id in units
        }
        if any(
            effective_enabled(
                parameter_id,
                unit_code,
                external_api_id=external_api_id,
            )
            for unit_code in evaluation_unit_codes
        ):
            counts[parameter_id]["enabled_source_count"] += 1

    for sensor_id in sensor_rules:
        context = sensor_contexts.get(sensor_id)
        if context is None:
            continue
        parameter_id, unit_id, external_api_id = context
        unit = units.get(unit_id)
        if parameter_id not in counts or unit is None:
            continue
        counts[parameter_id]["sensor_override_count"] += 1
        if effective_enabled(
            parameter_id,
            unit.code,
            external_api_id=external_api_id,
            sensor_id=sensor_id,
        ):
            counts[parameter_id]["enabled_sensor_count"] += 1

    return counts


def list_parameter_policy_summaries(session: Session) -> dict[str, Any]:
    parameters = list(
        session.scalars(
            select(models.Parameter).order_by(
                models.Parameter.display_name,
                models.Parameter.code,
            )
        ).all()
    )
    units = {
        unit.unit_id: unit
        for unit in session.scalars(select(models.Unit)).all()
    }
    sensor_counts = dict(
        session.execute(
            select(models.Sensor.parameter_id, func.count(models.Sensor.sensor_id))
            .where(models.Sensor.parameter_id.is_not(None))
            .group_by(models.Sensor.parameter_id)
        ).all()
    )
    parameter_override_counts = dict(
        session.execute(
            select(models.QCRule.parameter_id, func.count(models.QCRule.qc_rule_id))
            .where(
                models.QCRule.parameter_id.is_not(None),
                models.QCRule.external_api_id.is_(None),
                models.QCRule.sensor_id.is_(None),
                models.QCRule.aggregate_code.is_(None),
            )
            .group_by(models.QCRule.parameter_id)
        ).all()
    )
    source_override_counts = dict(
        session.execute(
            select(models.QCRule.parameter_id, func.count(models.QCRule.qc_rule_id))
            .where(
                models.QCRule.parameter_id.is_not(None),
                models.QCRule.external_api_id.is_not(None),
                models.QCRule.sensor_id.is_(None),
                models.QCRule.aggregate_code.is_(None),
            )
            .group_by(models.QCRule.parameter_id)
        ).all()
    )
    sensor_override_counts = dict(
        session.execute(
            select(models.Sensor.parameter_id, func.count(models.QCRule.qc_rule_id))
            .join(models.QCRule, models.QCRule.sensor_id == models.Sensor.sensor_id)
            .where(models.QCRule.aggregate_code.is_(None))
            .group_by(models.Sensor.parameter_id)
        ).all()
    )
    source_exception_counts = dict(
        session.execute(
            select(
                models.QCRule.parameter_id,
                func.count(func.distinct(models.QCRule.external_api_id)),
            )
            .where(
                models.QCRule.parameter_id.is_not(None),
                models.QCRule.external_api_id.is_not(None),
                models.QCRule.sensor_id.is_(None),
                models.QCRule.aggregate_code.is_(None),
            )
            .group_by(models.QCRule.parameter_id)
        ).all()
    )
    sensor_exception_counts = dict(
        session.execute(
            select(
                models.Sensor.parameter_id,
                func.count(func.distinct(models.QCRule.sensor_id)),
            )
            .join(models.QCRule, models.QCRule.sensor_id == models.Sensor.sensor_id)
            .where(models.QCRule.aggregate_code.is_(None))
            .group_by(models.Sensor.parameter_id)
        ).all()
    )
    baseline_drift_counts = _baseline_drift_override_counts(
        session,
        parameters,
        units,
    )

    items: list[dict[str, Any]] = []
    for parameter in parameters:
        check_codes = get_qc_check_codes_for_parameter(
            session, parameter.parameter_id
        )
        checks = [
            resolve_parameter_qc_policy(
                session,
                parameter.parameter_id,
                check_code,
                units[parameter.default_unit_id].code,
            ).to_dict()
            for check_code in check_codes
        ]
        items.append(
            {
                **_parameter_dict(parameter, units.get(parameter.default_unit_id)),
                "supported": bool(get_default_check_codes(parameter.code)),
                "sensor_count": int(sensor_counts.get(parameter.parameter_id, 0)),
                "parameter_override_count": int(
                    parameter_override_counts.get(parameter.parameter_id, 0)
                ),
                "source_override_count": int(
                    source_override_counts.get(parameter.parameter_id, 0)
                ),
                "sensor_override_count": int(
                    sensor_override_counts.get(parameter.parameter_id, 0)
                ),
                "source_exception_count": int(
                    source_exception_counts.get(parameter.parameter_id, 0)
                ),
                "sensor_exception_count": int(
                    sensor_exception_counts.get(parameter.parameter_id, 0)
                ),
                "baseline_drift_source_override_count": baseline_drift_counts[
                    parameter.parameter_id
                ]["source_override_count"],
                "baseline_drift_sensor_override_count": baseline_drift_counts[
                    parameter.parameter_id
                ]["sensor_override_count"],
                "baseline_drift_enabled_source_count": baseline_drift_counts[
                    parameter.parameter_id
                ]["enabled_source_count"],
                "baseline_drift_enabled_sensor_count": baseline_drift_counts[
                    parameter.parameter_id
                ]["enabled_sensor_count"],
                "checks": checks,
            }
        )
    return {
        "default_profile_version": DEFAULT_POLICY_PROFILE_VERSION,
        "items": items,
        "total": len(items),
    }


def search_sensors(
    session: Session,
    *,
    query: str | None,
    parameter_id: int | None,
    external_api_id: int | None,
    has_overrides: bool | None,
    has_sensor_specific_qc: bool | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    base_conditions: list[Any] = []
    if parameter_id is not None:
        base_conditions.append(models.Sensor.parameter_id == parameter_id)
    if external_api_id is not None:
        base_conditions.append(models.Device.external_api_id == external_api_id)
    if has_overrides is not None:
        override_exists = exists(
            select(models.QCRule.qc_rule_id).where(
                models.QCRule.sensor_id == models.Sensor.sensor_id,
                models.QCRule.aggregate_code.is_(None),
            )
        )
        base_conditions.append(override_exists if has_overrides else ~override_exists)
    if has_sensor_specific_qc is not None:
        sensor_specific_qc_exists = exists(
            select(models.QCRule.qc_rule_id).where(
                models.QCRule.sensor_id == models.Sensor.sensor_id,
            )
        )
        base_conditions.append(
            sensor_specific_qc_exists
            if has_sensor_specific_qc
            else ~sensor_specific_qc_exists
        )
    if query:
        search_text = query.strip()
        search_conditions = [
            models.Sensor.external_sensor_id.ilike(f"%{search_text}%"),
            models.Device.name.ilike(f"%{search_text}%"),
            models.Device.friendly_name.ilike(f"%{search_text}%"),
            models.Device.manual_data_source_name.ilike(f"%{search_text}%"),
            models.Device.external_id.ilike(f"%{search_text}%"),
            models.ExternalAPI.name.ilike(f"%{search_text}%"),
            models.Parameter.code.ilike(f"%{search_text}%"),
            models.Parameter.display_name.ilike(f"%{search_text}%"),
        ]
        if search_text.isdigit():
            search_conditions.append(models.Sensor.sensor_id == int(search_text))
        base_conditions.append(or_(*search_conditions))

    joins = (
        select(
            models.Sensor,
            models.Device,
            models.ExternalAPI,
            models.Parameter,
            models.Unit,
            models.AggregationPeriod,
        )
        .join(models.Device, models.Device.device_id == models.Sensor.device_id)
        .join(
            models.ExternalAPI,
            models.ExternalAPI.external_api_id == models.Device.external_api_id,
        )
        .join(
            models.Parameter,
            models.Parameter.parameter_id == models.Sensor.parameter_id,
        )
        .outerjoin(models.Unit, models.Unit.unit_id == models.Sensor.unit_id)
        .outerjoin(
            models.AggregationPeriod,
            models.AggregationPeriod.aggregation_period_id
            == models.Sensor.aggregation_period_id,
        )
        .where(*base_conditions)
    )
    total = int(
        session.scalar(
            select(func.count())
            .select_from(models.Sensor)
            .join(models.Device, models.Device.device_id == models.Sensor.device_id)
            .join(
                models.ExternalAPI,
                models.ExternalAPI.external_api_id == models.Device.external_api_id,
            )
            .join(
                models.Parameter,
                models.Parameter.parameter_id == models.Sensor.parameter_id,
            )
            .where(*base_conditions)
        )
        or 0
    )
    rows = session.execute(
        joins.order_by(
            models.Device.name,
            models.Parameter.display_name,
            models.Sensor.external_sensor_id,
            models.Sensor.sensor_id,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    sensor_ids = [row[0].sensor_id for row in rows]
    override_counts: dict[int, int] = {}
    advanced_override_counts: dict[int, int] = {}
    if sensor_ids:
        override_counts = dict(
            session.execute(
                select(models.QCRule.sensor_id, func.count(models.QCRule.qc_rule_id))
                .where(
                    models.QCRule.sensor_id.in_(sensor_ids),
                    models.QCRule.aggregate_code.is_(None),
                )
                .group_by(models.QCRule.sensor_id)
            ).all()
        )
        advanced_override_counts = dict(
            session.execute(
                select(models.QCRule.sensor_id, func.count(models.QCRule.qc_rule_id))
                .where(
                    models.QCRule.sensor_id.in_(sensor_ids),
                    models.QCRule.aggregate_code.is_not(None),
                )
                .group_by(models.QCRule.sensor_id)
            ).all()
        )
    items = []
    for sensor, device, source, parameter, unit, aggregation in rows:
        item = _sensor_dict(
            sensor,
            device,
            source,
            parameter,
            session.get(models.Unit, parameter.default_unit_id),
            unit,
            aggregation,
        )
        item["override_check_count"] = int(
            override_counts.get(sensor.sensor_id, 0)
        )
        item["has_overrides"] = item["override_check_count"] > 0
        item["advanced_override_count"] = int(
            advanced_override_counts.get(sensor.sensor_id, 0)
        )
        item["has_sensor_specific_qc"] = bool(
            item["has_overrides"] or item["advanced_override_count"] > 0
        )
        items.append(item)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def preview_policy_overrides(
    session: Session,
    scope: PolicyScope,
    overrides: list[OverrideValue],
    *,
    hours: int,
    check_codes: list[str] | None,
    sample_limit: int = 2_000,
) -> dict[str, Any]:
    """Evaluate an unsaved generic override set against recent measurements.

    Preview uses the ordinary resolver and plugin pipeline. It never calls the
    persistence helper and therefore cannot alter measurements or QC results.
    """
    replacement = build_rule_replacement(session, scope, overrides)
    validate_rule_replacement(session, scope, replacement)
    available_check_codes = set(
        _check_codes_for_scope(session, scope, replacement)
    )
    requested_check_codes = (
        list(dict.fromkeys(check_codes))
        if check_codes is not None
        else sorted(available_check_codes)
    )
    unknown_check_codes = sorted(
        set(requested_check_codes) - available_check_codes
    )
    if unknown_check_codes:
        raise InvalidPolicyOverride(
            "unconfigured_check",
            "No effective policy exists for: " + ", ".join(unknown_check_codes),
        )

    preview_until = datetime.now(timezone.utc)
    preview_since = preview_until - timedelta(hours=hours)
    measurement_conditions = [models.Measurement.observed_at >= preview_since]
    statement = (
        select(
            models.Measurement,
            models.Sensor,
            models.AggregationPeriod,
        )
        .join(models.Sensor, models.Sensor.sensor_id == models.Measurement.sensor_id)
        .outerjoin(
            models.AggregationPeriod,
            models.AggregationPeriod.aggregation_period_id
            == models.Sensor.aggregation_period_id,
        )
    )
    count_statement = (
        select(func.count())
        .select_from(models.Measurement)
        .join(models.Sensor, models.Sensor.sensor_id == models.Measurement.sensor_id)
    )
    if scope.scope_type == "sensor":
        measurement_conditions.append(models.Sensor.sensor_id == scope.sensor_id)
    else:
        measurement_conditions.append(
            models.Sensor.parameter_id == scope.parameter_id
        )
        if scope.scope_type == "source_parameter":
            statement = statement.join(
                models.Device,
                models.Device.device_id == models.Sensor.device_id,
            )
            count_statement = count_statement.join(
                models.Device,
                models.Device.device_id == models.Sensor.device_id,
            )
            measurement_conditions.append(
                models.Device.external_api_id == scope.external_api_id
            )

    total_available = int(
        session.scalar(count_statement.where(*measurement_conditions)) or 0
    )
    rows = session.execute(
        statement.where(*measurement_conditions)
        .order_by(
            models.Measurement.observed_at.desc(),
            models.Measurement.measurement_id.desc(),
        )
        .limit(sample_limit)
    ).all()

    grouped_records: dict[str | None, list[QCRecord]] = {}
    for measurement, sensor, aggregation in rows:
        aggregate_code = aggregation.code if aggregation is not None else None
        grouped_records.setdefault(aggregate_code, []).append(
            QCRecord(
                sensor_id=sensor.sensor_id,
                parameter_id=sensor.parameter_id,
                value=measurement.value,
                unit_id=sensor.unit_id,
                observed_at=measurement.observed_at,
            )
        )

    check_summaries = {
        check_code: {
            "check_code": check_code,
            "samples_evaluated": 0,
            "passed": 0,
            "failed": 0,
            "indeterminate": 0,
            "disabled_or_not_applicable": len(rows),
            "would_flag": 0,
            "would_invalidate": 0,
            "reason_counts": {},
        }
        for check_code in requested_check_codes
    }
    for aggregate_code, records in grouped_records.items():
        detailed = run_ingest_detailed(
            records,
            {
                "session": session,
                "aggregate_code": aggregate_code,
                "rule_replacement": replacement,
                "check_codes": requested_check_codes,
            },
        )
        for check_code in requested_check_codes:
            policies = detailed["policies"].get(check_code, [None] * len(records))
            decisions = detailed["per_plugin"].get(
                check_code, [None] * len(records)
            )
            summary = check_summaries[check_code]
            for policy, decision in zip(policies, decisions):
                if policy is None or decision is None:
                    continue
                summary["samples_evaluated"] += 1
                summary["disabled_or_not_applicable"] -= 1
                if decision.is_valid is True:
                    summary["passed"] += 1
                elif decision.is_valid is False:
                    summary["failed"] += 1
                    summary["would_flag"] += 1
                    if policy.failure_action == "mark_invalid":
                        summary["would_invalidate"] += 1
                else:
                    summary["indeterminate"] += 1
                    reason_code = (
                        (decision.patch or {}).get("reason_code")
                        or policy.reason_code
                        or "indeterminate"
                    )
                    reason_counts = summary["reason_counts"]
                    reason_counts[reason_code] = reason_counts.get(reason_code, 0) + 1

    return {
        "scope": {
            "scope_type": scope.scope_type,
            "parameter_id": scope.parameter_id,
            "external_api_id": scope.external_api_id,
            "sensor_id": scope.sensor_id,
        },
        "preview_since": preview_since.isoformat(),
        "preview_until": preview_until.isoformat(),
        "hours": hours,
        "sample_limit": sample_limit,
        "samples_available": total_available,
        "samples_evaluated": len(rows),
        "truncated": total_available > len(rows),
        "checks": [check_summaries[code] for code in requested_check_codes],
        "candidate_policy": build_policy_response(session, scope, replacement),
    }
