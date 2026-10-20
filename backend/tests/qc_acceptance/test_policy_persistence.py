from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import models
from qaqc.admin_policy import (
    OverrideValue,
    PolicyScope,
    build_policy_response,
    replace_generic_scope_overrides,
    reset_scope_overrides,
)
from qaqc.policy import resolve_effective_qc_policy
from qaqc.registry import get_registration
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed
from services.measurement_aggregation import execute_measurement_aggregation
from .support import (
    ensure_catalog,
    ensure_source,
    measurement_qc_rows,
)


def _device_sensor(
    session,
    source: models.ExternalAPI,
    parameter: models.Parameter,
    unit: models.Unit,
    label: str,
    period: models.AggregationPeriod | None = None,
):
    device = models.Device(
        name=label,
        external_id=label.lower().replace(" ", "-"),
        external_api_id=source.external_api_id,
    )
    session.add(device)
    session.flush()
    sensor = models.Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=(period.aggregation_period_id if period else None),
        external_sensor_id=f"{device.external_id}:{parameter.code}",
    )
    session.add(sensor)
    session.flush()
    return device, sensor


def _ingest(session, device, sensor, value: float, observed_at: datetime):
    measurement = models.Measurement(
        sensor_id=sensor.sensor_id,
        value=value,
        observed_at=observed_at,
    )
    result = upsert_measurement_with_policy_detailed(
        session,
        measurement,
        device=device,
        sensor=sensor,
    )
    session.flush()
    return measurement, result


def _override(
    check_code: str,
    *,
    enabled: bool | None = None,
    action: str | None = None,
    settings: dict | None = None,
    unit: str | None = None,
) -> OverrideValue:
    return OverrideValue(
        check_code=check_code,
        enabled_override=enabled,
        failure_action_override=action,
        settings=settings or {},
        policy_unit_code=unit,
    )


@pytest.mark.qc_acceptance(
    id="policy-sparse-inheritance-history",
    source="OpenAQ and PurpleAir test sources",
    parameter="pm25",
    qc_layer="compassaq_default,source_override,sensor_override",
    expected="Sparse property precedence, resets, source isolation, and historical stability are preserved",
)
def test_sparse_inheritance_resets_and_history_are_end_to_end(
    acceptance_session_factory, acceptance_evidence
):
    Session = acceptance_session_factory
    with Session() as session:
        units, parameters, _ = ensure_catalog(session)
        openaq = ensure_source(session, "openaq", "OpenAQ")
        purpleair = ensure_source(session, "purpleair", "PurpleAir")
        custom_device, custom_sensor = _device_sensor(
            session, openaq, parameters["pm25"], units["ug_m3"], "Custom sensor"
        )
        sibling_device, sibling_sensor = _device_sensor(
            session, openaq, parameters["pm25"], units["ug_m3"], "Sibling sensor"
        )
        other_device, other_sensor = _device_sensor(
            session, purpleair, parameters["pm25"], units["ug_m3"], "Other source sensor"
        )

        source_scope = PolicyScope(
            "source_parameter",
            parameter_id=parameters["pm25"].parameter_id,
            external_api_id=openaq.external_api_id,
        )
        sensor_scope = PolicyScope("sensor", sensor_id=custom_sensor.sensor_id)
        replace_generic_scope_overrides(
            session,
            source_scope,
            [_override("max_value", settings={"max": 100.0}, unit="ug_m3")],
        )
        # Start with two sensor-owned properties, then reset just the threshold
        # by saving the remaining sparse action override.
        replace_generic_scope_overrides(
            session,
            sensor_scope,
            [
                _override(
                    "max_value",
                    action="mark_invalid",
                    settings={"max": 80.0},
                    unit="ug_m3",
                )
            ],
        )
        replace_generic_scope_overrides(
            session,
            sensor_scope,
            [_override("max_value", action="mark_invalid", unit="ug_m3")],
        )
        session.commit()

        effective = resolve_effective_qc_policy(
            session, custom_sensor.sensor_id, "max_value"
        )
        assert effective.evaluation_settings == {"max": 100.0}
        assert effective.property_provenance["settings.max"].layer == "source_override"
        assert effective.property_provenance["failure_action"].layer == "sensor_override"

        observed_at = datetime(2026, 8, 19, 13, tzinfo=timezone.utc)
        historical, _ = _ingest(
            session, custom_device, custom_sensor, 150.0, observed_at
        )
        sibling, _ = _ingest(
            session,
            sibling_device,
            sibling_sensor,
            150.0,
            observed_at,
        )
        other, _ = _ingest(
            session,
            other_device,
            other_sensor,
            150.0,
            observed_at,
        )
        historical_result = measurement_qc_rows(
            session, historical.measurement_id
        )[0]
        historical_snapshot = dict(historical_result.policy_snapshot)
        assert historical.is_valid is False
        assert sibling.is_valid is True and sibling.qc_flags == ["max_value"]
        assert other.is_valid is True and other.qc_flags is None

        reset_scope_overrides(session, sensor_scope, "max_value", "ug_m3")
        after_sensor_reset, _ = _ingest(
            session,
            custom_device,
            custom_sensor,
            150.0,
            observed_at + timedelta(minutes=1),
        )
        assert after_sensor_reset.is_valid is True
        assert after_sensor_reset.qc_flags == ["max_value"]

        reset_scope_overrides(session, source_scope)
        after_source_reset, _ = _ingest(
            session,
            custom_device,
            custom_sensor,
            150.0,
            observed_at + timedelta(minutes=2),
        )
        session.commit()
        assert after_source_reset.is_valid is True
        assert after_source_reset.qc_flags is None

        session.refresh(historical)
        session.refresh(historical_result)
        assert historical.is_valid is False
        assert historical_result.policy_snapshot == historical_snapshot
        response = build_policy_response(session, sensor_scope)
        assert response["overrides"] == []
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "historical_measurement_id": historical.measurement_id,
                "historical_unchanged": True,
                "source_isolation_sensor_id": other_sensor.sensor_id,
                "final_override_count": 0,
            }
        )


@pytest.mark.qc_acceptance(
    id="policy-disabled-and-reenabled",
    source="OpenAQ test source",
    parameter="pm25",
    qc_layer="source_override,sensor_override",
    expected="A source-disabled check creates no outcome while a sensor can explicitly re-enable it",
)
def test_disabled_check_is_absent_and_sensor_can_reenable(
    acceptance_session_factory, acceptance_evidence
):
    Session = acceptance_session_factory
    with Session() as session:
        units, parameters, _ = ensure_catalog(session)
        source = ensure_source(session, "openaq", "OpenAQ")
        reenabled_device, reenabled_sensor = _device_sensor(
            session, source, parameters["pm25"], units["ug_m3"], "Reenabled sensor"
        )
        disabled_device, disabled_sensor = _device_sensor(
            session, source, parameters["pm25"], units["ug_m3"], "Disabled sensor"
        )
        source_scope = PolicyScope(
            "source_parameter",
            parameter_id=parameters["pm25"].parameter_id,
            external_api_id=source.external_api_id,
        )
        replace_generic_scope_overrides(
            session, source_scope, [_override("max_value", enabled=False, unit="ug_m3")]
        )
        replace_generic_scope_overrides(
            session,
            PolicyScope("sensor", sensor_id=reenabled_sensor.sensor_id),
            [_override("max_value", enabled=True, unit="ug_m3")],
        )
        session.commit()

        disabled, disabled_result = _ingest(
            session,
            disabled_device,
            disabled_sensor,
            20_000.0,
            datetime(2026, 8, 19, 14, tzinfo=timezone.utc),
        )
        reenabled, reenabled_result = _ingest(
            session,
            reenabled_device,
            reenabled_sensor,
            20_000.0,
            datetime(2026, 8, 19, 14, tzinfo=timezone.utc),
        )
        disabled_rows = measurement_qc_rows(session, disabled.measurement_id)
        reenabled_rows = measurement_qc_rows(session, reenabled.measurement_id)
        assert disabled_result.qc == {
            "evaluated": 1,
            "passed": 1,
            "flagged": 0,
            "indeterminate": 0,
        }
        assert disabled_rows == []
        assert disabled.is_valid is True
        assert reenabled_result.qc["flagged"] == 1
        assert [row.check_code for row in reenabled_rows] == ["max_value"]
        assert reenabled.is_valid is True
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "disabled_max_result_rows": 0,
                "reenabled_max_result_rows": 1,
            }
        )


@pytest.mark.qc_acceptance(
    id="policy-units-and-provenance",
    source="OpenAQ-shaped ozone sensors",
    parameter="o3",
    qc_layer="sensor_override,compassaq_default",
    expected="Safe conversion is executed and persisted; a unit with no matching rule creates no result",
)
def test_unit_conversion_and_unsupported_conversion_is_not_persisted(
    acceptance_session_factory, acceptance_evidence
):
    Session = acceptance_session_factory
    with Session() as session:
        units, parameters, periods = ensure_catalog(session)
        source = ensure_source(session, "openaq", "OpenAQ")
        converted_device, converted_sensor = _device_sensor(
            session,
            source,
            parameters["o3"],
            units["ppb"],
            "Ozone ppb sensor",
            periods["1h"],
        )
        unsupported_device, unsupported_sensor = _device_sensor(
            session,
            source,
            parameters["o3"],
            units["ug_m3"],
            "Ozone mass sensor",
            periods["1h"],
        )
        session.commit()

        session.add(
            models.QCRule(
                check_code="baseline_drift",
                sensor_id=converted_sensor.sensor_id,
                enabled_override=True,
                policy_unit_id=units["ppm"].unit_id,
            )
        )
        session.commit()

        converted, _ = _ingest(
            session,
            converted_device,
            converted_sensor,
            600.0,
            datetime(2026, 8, 19, 15, tzinfo=timezone.utc),
        )
        unsupported, _ = _ingest(
            session,
            unsupported_device,
            unsupported_sensor,
            100.0,
            datetime(2026, 8, 19, 15, tzinfo=timezone.utc),
        )
        converted_results = measurement_qc_rows(session, converted.measurement_id)
        converted_result = next(
            row for row in converted_results if row.check_code == "max_value"
        )
        converted_baseline = next(
            row for row in converted_results if row.check_code == "baseline_drift"
        )
        unsupported_results = measurement_qc_rows(session, unsupported.measurement_id)
        conversion = converted_result.policy_snapshot["unit_conversion"]
        assert converted.is_valid is True
        assert converted_result.params_snapshot == {"max": 500.0}
        assert converted_result.policy_snapshot["configured_unit_code"] == "ppm"
        assert converted_result.policy_snapshot["evaluation_unit_code"] == "ppb"
        assert conversion["status"] == "converted"
        assert conversion["factor"] == 1000.0
        assert converted_baseline.params_snapshot["max_drift_per_day"] == 3.0
        assert converted_baseline.reason_code == "insufficient_history"
        assert unsupported.is_valid is True
        assert unsupported.qc_flags is None
        assert unsupported_results == []
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "configured_unit": "ppm",
                "evaluation_unit": "ppb",
                "conversion_factor": 1000.0,
                "unsupported_result_rows": len(unsupported_results),
            }
        )


@pytest.mark.qc_acceptance(
    id="baseline-drift-operational",
    source="Deterministic historical sensor fixture",
    parameter="pm25",
    qc_layer="sensor_override",
    expected="The PM2.5 screening preset is disabled until an explicit rule enables it; flag-only drift remains aggregated and mark-invalid drift is excluded",
)
def test_baseline_drift_default_and_failure_actions_control_aggregation(
    acceptance_session_factory, acceptance_evidence
):
    Session = acceptance_session_factory
    with Session() as session:
        units, parameters, periods = ensure_catalog(session)
        source = ensure_source(session, "openaq", "OpenAQ")
        device, sensor = _device_sensor(
            session,
            source,
            parameters["pm25"],
            units["ug_m3"],
            "Baseline drift sensor",
            periods["2m"],
        )
        default_policy = resolve_effective_qc_policy(
            session, sensor.sensor_id, "baseline_drift", "1h"
        )
        assert default_policy.status == "disabled"
        assert default_policy.enabled is False
        assert default_policy.failure_action == "flag_for_review"
        assert default_policy.configured_unit_code == "ug_m3"
        assert default_policy.configured_settings == {
            "lookback_hours": 168,
            "min_samples": 72,
            "baseline_quantile": 0.1,
            "max_drift_per_day": 5.0,
            "direction": "both",
        }

        now = datetime(2026, 8, 19, 16, tzinfo=timezone.utc)
        history = []
        for index in range(12):
            history.append(
                models.Measurement(
                    sensor_id=sensor.sensor_id,
                    observed_at=now - timedelta(hours=46 - index),
                    value=0.05 * index,
                    is_valid=True,
                )
            )
        for index in range(12):
            history.append(
                models.Measurement(
                    sensor_id=sensor.sensor_id,
                    observed_at=now - timedelta(hours=22 - index),
                    value=5.0 + 0.05 * index,
                    is_valid=True,
                )
            )
        session.add_all(history)
        session.add(
            models.QCRule(
                check_code="baseline_drift",
                sensor_id=sensor.sensor_id,
                enabled_override=True,
                failure_action_override="flag_for_review",
                policy_unit_id=units["ug_m3"].unit_id,
                settings={
                    "lookback_hours": 48,
                    "min_samples": 8,
                    "baseline_quantile": 0.1,
                    "max_drift_per_day": 1.0,
                    "direction": "both",
                },
            )
        )
        existing_rollup = session.scalar(
            select(models.ParameterAggregationRollup).where(
                models.ParameterAggregationRollup.parameter_id
                == parameters["pm25"].parameter_id,
                models.ParameterAggregationRollup.from_aggregation_period_id
                == periods["2m"].aggregation_period_id,
                models.ParameterAggregationRollup.to_aggregation_period_id
                == periods["1h"].aggregation_period_id,
            )
        )
        if existing_rollup is None:
            session.add(
                models.ParameterAggregationRollup(
                    parameter_id=parameters["pm25"].parameter_id,
                    from_aggregation_period_id=periods["2m"].aggregation_period_id,
                    to_aggregation_period_id=periods["1h"].aggregation_period_id,
                )
            )
        session.commit()

        registration = get_registration("baseline_drift")
        assert registration is not None
        assert registration.metadata.required_access == "db-read"
        flagged, _ = _ingest(session, device, sensor, 5.7, now)
        flagged_rows = measurement_qc_rows(session, flagged.measurement_id)
        flagged_drift = next(row for row in flagged_rows if row.check_code == "baseline_drift")
        assert flagged.is_valid is True
        assert flagged_drift.failure_action == "flag_for_review"
        assert flagged_drift.details["drift_per_day"] > 1.0
        assert flagged_drift.details["samples"] >= 24

        drift_rule = session.scalar(
            select(models.QCRule).where(
                models.QCRule.sensor_id == sensor.sensor_id,
                models.QCRule.check_code == "baseline_drift",
            )
        )
        drift_rule.failure_action_override = "mark_invalid"
        session.flush()
        invalid_at = now + timedelta(minutes=10)
        invalid, _ = _ingest(session, device, sensor, 5.8, invalid_at)
        invalid_rows = measurement_qc_rows(session, invalid.measurement_id)
        invalid_drift = next(row for row in invalid_rows if row.check_code == "baseline_drift")
        assert invalid.is_valid is False
        assert invalid_drift.failure_action == "mark_invalid"

        valid_only = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code="pm25",
            native_aggregation_code="2m",
            result_aggregation_code="1h",
            since=now,
            until=invalid_at,
        )[0]
        diagnostic = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code="pm25",
            native_aggregation_code="2m",
            result_aggregation_code="1h",
            since=now,
            until=invalid_at,
            include_invalid=True,
        )[0]
        assert valid_only.sample_count == 1
        assert valid_only.valid_sample_count == 1
        assert valid_only.value == pytest.approx(flagged.value)
        assert diagnostic.sample_count == 2
        assert diagnostic.valid_sample_count == 1
        assert diagnostic.invalid_sample_count == 1
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "default_status": "ready",
                "required_access": registration.metadata.required_access,
                "historical_samples": flagged_drift.details["samples"],
                "flagged_measurement_valid": flagged.is_valid,
                "invalid_measurement_valid": invalid.is_valid,
                "valid_aggregate_sample_count": valid_only.sample_count,
                "diagnostic_aggregate_sample_count": diagnostic.sample_count,
            }
        )
