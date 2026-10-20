"""Run ingest QC from effective policies.

Plugins report whether their check passed. This pipeline applies the resolved
failure action to decide whether a failed check invalidates the measurement.
"""

from __future__ import annotations

from typing import Any

from .policy import (
    EffectiveQCPolicy,
    get_qc_check_codes_for_sensor,
    is_no_matching_rule,
    resolve_effective_qc_policy,
)
from .policy_defaults import MARK_INVALID
from .registry import get_registration
from .types import QCDecision, QCRecord


_SEVERITY_ORDER = {"info": 0, "warn": 1, "error": 2}


def _indeterminate_decision(
    check_code: str,
    reason_code: str,
    message: str,
    *,
    plugin_error: dict[str, Any] | None = None,
) -> QCDecision:
    return QCDecision(
        is_valid=None,
        flags=[],
        severity="warn",
        message=message,
        patch={"reason_code": reason_code},
        plugin_error=plugin_error,
    )


def _overall_decision(
    decisions: list[tuple[QCDecision, EffectiveQCPolicy]],
) -> QCDecision:
    if not decisions:
        return QCDecision(is_valid=None, flags=[], severity="info", message="")

    invalidating_failure = any(
        decision.is_valid is False and policy.failure_action == MARK_INVALID
        for decision, policy in decisions
    )
    has_completed_check = any(decision.is_valid is not None for decision, _ in decisions)
    measurement_is_valid: bool | None
    if invalidating_failure:
        measurement_is_valid = False
    elif has_completed_check:
        measurement_is_valid = True
    else:
        measurement_is_valid = None

    flags: list[str] = []
    for decision, _ in decisions:
        if decision.is_valid is not False:
            continue
        for flag in decision.flags:
            if flag not in flags:
                flags.append(flag)

    severity = max(
        (decision.severity for decision, _ in decisions),
        key=lambda value: _SEVERITY_ORDER.get(value, 0),
        default="info",
    )
    message = next(
        (
            decision.message
            for decision, _ in decisions
            if decision.severity == "error" and decision.message
        ),
        next(
            (
                decision.message
                for decision, _ in decisions
                if decision.severity == "warn" and decision.message
            ),
            "",
        ),
    )
    return QCDecision(
        is_valid=measurement_is_valid,
        flags=flags,
        severity=severity,
        message=message,
    )


def _validate_plugin_decisions(
    check_code: str,
    plugin_results: Any,
    expected_count: int,
) -> list[QCDecision]:
    """Make malformed third-party output explicit and safe for persistence."""
    if not isinstance(plugin_results, list) or len(plugin_results) != expected_count:
        return [
            _indeterminate_decision(
                check_code,
                "invalid_plugin_result",
                f"QC plugin '{check_code}' returned an invalid result count",
                plugin_error={
                    "plugin": check_code,
                    "error": "result must be a list aligned to input records",
                },
            )
            for _ in range(expected_count)
        ]

    validated: list[QCDecision] = []
    for result in plugin_results:
        is_valid_decision = (
            isinstance(result, QCDecision)
            and (result.is_valid is None or isinstance(result.is_valid, bool))
            and result.severity in _SEVERITY_ORDER
            and isinstance(result.flags, list)
            and all(isinstance(flag, str) and flag for flag in result.flags)
            and isinstance(result.message, str)
            and (result.patch is None or isinstance(result.patch, dict))
            and (
                result.plugin_error is None
                or isinstance(result.plugin_error, dict)
            )
        )
        if is_valid_decision:
            validated.append(result)
        else:
            validated.append(
                _indeterminate_decision(
                    check_code,
                    "invalid_plugin_result",
                    f"QC plugin '{check_code}' returned an invalid decision",
                    plugin_error={
                        "plugin": check_code,
                        "error": "result does not satisfy the QCDecision contract",
                    },
                )
            )
    return validated


def run_ingest_detailed(records: list[QCRecord], context: dict[str, Any]) -> dict[str, Any]:
    """Resolve and run checks, returning aligned decisions and policies.

    ``per_plugin`` and ``policies`` contain lists aligned to ``records``.
    Disabled checks are absent. A ``None`` list entry means that check did not
    apply to that record.
    """
    session = context.get("session")
    if session is None:
        unavailable = [
            _indeterminate_decision(
                "policy_resolver",
                "missing_session",
                "QC policy resolution requires a database session",
            )
            for _ in records
        ]
        return {
            "overall": unavailable,
            "per_plugin": {},
            "policies": {},
        }

    aggregate_code = context.get("aggregate_code")
    rule_replacement = context.get("rule_replacement")
    requested_check_codes = context.get("check_codes")
    requested_check_code_set = (
        set(requested_check_codes) if requested_check_codes is not None else None
    )
    policies_by_check: dict[str, list[EffectiveQCPolicy | None]] = {}
    for record_index, record in enumerate(records):
        if record.sensor_id is None:
            continue
        for check_code in get_qc_check_codes_for_sensor(
            session,
            record.sensor_id,
            aggregate_code,
            rule_replacement=rule_replacement,
        ):
            if (
                requested_check_code_set is not None
                and check_code not in requested_check_code_set
            ):
                continue
            policy = resolve_effective_qc_policy(
                session,
                record.sensor_id,
                check_code,
                aggregate_code,
                rule_replacement=rule_replacement,
            )
            if policy.status == "disabled" or is_no_matching_rule(policy):
                continue
            aligned = policies_by_check.setdefault(check_code, [None] * len(records))
            aligned[record_index] = policy

    decisions_by_check: dict[str, list[QCDecision | None]] = {}
    for check_code, aligned_policies in policies_by_check.items():
        aligned_decisions: list[QCDecision | None] = [None] * len(records)
        ready_indexes: list[int] = []
        ready_records: list[QCRecord] = []
        ready_policies: list[EffectiveQCPolicy] = []

        for record_index, policy in enumerate(aligned_policies):
            if policy is None:
                continue
            if policy.status == "unavailable":
                aligned_decisions[record_index] = _indeterminate_decision(
                    check_code,
                    policy.reason_code or "policy_unavailable",
                    policy.message or "The effective QC policy is unavailable",
                )
                continue
            ready_indexes.append(record_index)
            ready_records.append(records[record_index])
            ready_policies.append(policy)

        if ready_records:
            registration = get_registration(check_code)
            if registration is None:
                for record_index in ready_indexes:
                    aligned_decisions[record_index] = _indeterminate_decision(
                        check_code,
                        "plugin_unavailable",
                        f"QC plugin '{check_code}' is unavailable",
                        plugin_error={"plugin": check_code, "error": "plugin unavailable"},
                    )
            else:
                plugin = registration.plugin
                plugin_context = {
                    key: context[key]
                    for key in ("aggregate_code", "stage")
                    if key in context
                }
                if registration.metadata.required_access in {"db-read", "db-write"}:
                    plugin_context["session"] = session
                plugin_context["effective_policies"] = ready_policies
                try:
                    raw_plugin_decisions = plugin.apply(ready_records, plugin_context)
                    plugin_decisions = _validate_plugin_decisions(
                        check_code,
                        raw_plugin_decisions,
                        len(ready_records),
                    )
                except Exception as exc:
                    plugin_decisions = [
                        _indeterminate_decision(
                            check_code,
                            "plugin_error",
                            f"QC plugin '{check_code}' failed",
                            plugin_error={"plugin": check_code, "error": str(exc)},
                        )
                        for _ in ready_records
                    ]
                for subset_index, record_index in enumerate(ready_indexes):
                    if subset_index < len(plugin_decisions):
                        aligned_decisions[record_index] = plugin_decisions[subset_index]
                    else:
                        aligned_decisions[record_index] = _indeterminate_decision(
                            check_code,
                            "plugin_result_missing",
                            f"QC plugin '{check_code}' returned no result for a measurement",
                        )
        decisions_by_check[check_code] = aligned_decisions

    overall: list[QCDecision] = []
    for record_index in range(len(records)):
        record_decisions: list[tuple[QCDecision, EffectiveQCPolicy]] = []
        for check_code, aligned_decisions in decisions_by_check.items():
            decision = aligned_decisions[record_index]
            policy = policies_by_check[check_code][record_index]
            if decision is not None and policy is not None:
                record_decisions.append((decision, policy))
        overall.append(_overall_decision(record_decisions))

    return {
        "overall": overall,
        "per_plugin": decisions_by_check,
        "policies": policies_by_check,
    }


def run_ingest(records: list[QCRecord], context: dict[str, Any]) -> list[QCDecision]:
    return run_ingest_detailed(records, context)["overall"]
