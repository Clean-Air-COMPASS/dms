"""Persist current ingest QC state for a measurement."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import models
from qaqc.policy import EffectiveQCPolicy
from qaqc.registry import get as get_plugin
from qaqc.types import QCDecision


def _aligned_value(values: list[Any] | None, index: int) -> Any | None:
    if not values or index >= len(values):
        return None
    return values[index]


def _baseline_warmup_already_recorded(
    session: Session,
    measurement: models.Measurement,
) -> bool:
    """Keep one durable warm-up outcome per sensor without event/email noise."""

    return session.scalar(
        select(models.MeasurementQCResult.measurement_qc_result_id)
        .join(
            models.Measurement,
            models.Measurement.measurement_id
            == models.MeasurementQCResult.measurement_id,
        )
        .where(
            models.Measurement.sensor_id == measurement.sensor_id,
            models.MeasurementQCResult.check_code == "baseline_drift",
            models.MeasurementQCResult.evaluation_status == "indeterminate",
            models.MeasurementQCResult.reason_code == "insufficient_history",
            models.MeasurementQCResult.measurement_id != measurement.measurement_id,
        )
        .limit(1)
    ) is not None


def apply_ingest_qc_result(
    session: Session,
    measurement: models.Measurement,
    parameter_id: int | None,
    aggregate_code: str,
    detailed_result: dict[str, Any],
    *,
    replace_existing: bool,
    record_index: int = 0,
) -> None:
    """Apply one aligned pipeline result and persist only non-pass outcomes."""
    overall: QCDecision | None = _aligned_value(
        detailed_result.get("overall"), record_index
    )
    policies: dict[str, list[EffectiveQCPolicy | None]] = detailed_result.get(
        "policies", {}
    )
    decisions: dict[str, list[QCDecision | None]] = detailed_result.get(
        "per_plugin", {}
    )

    has_applicable_policy = False
    for aligned_policies in policies.values():
        policy = _aligned_value(aligned_policies, record_index)
        if policy is not None:
            has_applicable_policy = True
            break
    if overall is not None and has_applicable_policy:
        # Indeterminate evaluations do not invalidate a stored measurement.
        measurement.is_valid = overall.is_valid is not False

    failed_checks = [
        check_code
        for check_code, aligned_decisions in decisions.items()
        if (
            (decision := _aligned_value(aligned_decisions, record_index))
            is not None
            and decision.is_valid is False
        )
    ]
    measurement.qc_flags = failed_checks or None
    session.add(measurement)
    session.flush()

    if replace_existing:
        session.execute(
            delete(models.MeasurementQCResult).where(
                models.MeasurementQCResult.measurement_id
                == measurement.measurement_id,
                models.MeasurementQCResult.stage == "ingest",
            )
        )

    for check_code, aligned_decisions in decisions.items():
        decision = _aligned_value(aligned_decisions, record_index)
        policy = _aligned_value(policies.get(check_code), record_index)
        if decision is None or policy is None or decision.is_valid is True:
            continue

        evaluation_status = (
            "failed" if decision.is_valid is False else "indeterminate"
        )
        reason_code = None
        if decision.patch:
            reason_code = decision.patch.get("reason_code")
        if reason_code is None:
            reason_code = policy.reason_code
        if reason_code is None and decision.plugin_error:
            reason_code = "plugin_error"

        # Baseline drift is expected to be indeterminate while a new sensor
        # accumulates history. Preserve the first durable outcome for
        # traceability, but do not create an Events/email issue for every
        # measurement during the warm-up period.
        if (
            check_code == "baseline_drift"
            and evaluation_status == "indeterminate"
            and reason_code == "insufficient_history"
            and _baseline_warmup_already_recorded(session, measurement)
        ):
            continue

        plugin = get_plugin(check_code)
        plugin_version = getattr(plugin, "version", None) if plugin else None
        rule_source = (
            policy.most_specific_source.layer
            if policy.most_specific_source is not None
            else None
        )
        policy_dict = policy.to_dict()
        session.add(
            models.MeasurementQCResult(
                measurement_id=measurement.measurement_id,
                parameter_id=parameter_id,
                aggregate_code=aggregate_code,
                check_code=check_code,
                passed=False if evaluation_status == "failed" else None,
                details={"value": measurement.value, **(decision.patch or {})},
                severity=decision.severity,
                message=decision.message or "",
                rule_source=rule_source,
                params_snapshot=policy.evaluation_settings,
                evaluation_status=evaluation_status,
                failure_action=policy.failure_action,
                reason_code=reason_code,
                policy_snapshot={
                    "check_code": policy.check_code,
                    "status": policy.status,
                    "enabled": policy.enabled,
                    "failure_action": policy.failure_action,
                    "default_profile_version": policy.default_profile_version,
                    "configured_settings": policy.configured_settings,
                    "evaluation_settings": policy.evaluation_settings,
                    "configured_unit_code": policy.configured_unit_code,
                    "evaluation_unit_code": policy.evaluation_unit_code,
                    "applicable_unit_code": policy.applicable_unit_code,
                    "unit_conversion": policy.unit_conversion,
                    "applicability": policy.applicability,
                    "applied_layers": policy_dict["applied_layers"],
                },
                policy_provenance=policy_dict["property_provenance"],
                plugin_version=plugin_version,
                stage="ingest",
                qc_version=policy.default_profile_version,
            )
        )
