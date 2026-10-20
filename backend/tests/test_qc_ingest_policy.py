from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select

import models
from db import SessionLocal
from qaqc import discovery, registry
from qaqc.admin_policy import get_check_metadata
from qaqc.plugins import BUILT_IN_PLUGINS
from qaqc.policy import resolve_effective_qc_policy
from qaqc.policy_defaults import FLAG_FOR_REVIEW, MARK_INVALID
from qaqc.registry import all_registrations, register, replace_all
from qaqc.types import QCDecision
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed


def _unit(session, code: str) -> models.Unit:
    unit = session.scalar(select(models.Unit).where(models.Unit.code == code))
    if unit:
        return unit
    unit = models.Unit(code=code, symbol=code, name=code)
    session.add(unit)
    session.flush()
    return unit


def _parameter(session, code: str, unit: models.Unit) -> models.Parameter:
    parameter = session.scalar(
        select(models.Parameter).where(models.Parameter.code == code)
    )
    if parameter:
        return parameter
    parameter = models.Parameter(
        code=code,
        display_name=code,
        default_unit_id=unit.unit_id,
    )
    session.add(parameter)
    session.flush()
    return parameter


def _context(
    session,
    parameter_code: str = "pm25",
    unit_code: str = "ug_m3",
    provider_code: str = "test",
    *,
    allow_updates: models.UpdatePolicy = models.UpdatePolicy.INHERIT,
):
    suffix = uuid.uuid4().hex
    unit = _unit(session, unit_code)
    parameter = _parameter(session, parameter_code, unit)
    source = models.ExternalAPI(
        provider_code=f"{provider_code}-{suffix}",
        name=f"{provider_code} {suffix}",
        params={},
    )
    session.add(source)
    session.flush()
    device = models.Device(
        name=f"device {suffix}",
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
        allow_updates=allow_updates,
    )
    session.add(sensor)
    session.flush()
    # Baseline Drift ships disabled. Tests that exercise it add an explicit
    # rule, matching the administrator opt-in required in production.
    return source, device, sensor, parameter, unit


def _insert(session, device, sensor, value: float, observed_at: datetime):
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


def _qc_results(session, measurement_id: int):
    return list(
        session.scalars(
            select(models.MeasurementQCResult)
            .where(models.MeasurementQCResult.measurement_id == measurement_id)
            .order_by(models.MeasurementQCResult.check_code)
        ).all()
    )


@pytest.mark.parametrize("provider_code", ["openaq", "purpleair", "airgradient"])
def test_shared_ingest_policy_path_flags_without_invalidating(provider_code):
    with SessionLocal() as session:
        _, device, sensor, _, _ = _context(
            session, provider_code=provider_code
        )
        measurement, result = _insert(
            session,
            device,
            sensor,
            -20.0,
            datetime.now(timezone.utc),
        )

        assert result.action == "insert"
        assert result.qc == {
            "evaluated": 1,
            "passed": 0,
            "flagged": 1,
            "indeterminate": 0,
        }
        assert measurement.value == -20.0
        assert measurement.is_valid is True
        assert measurement.qc_flags == ["min_value"]
        stored = _qc_results(session, measurement.measurement_id)
        assert len(stored) == 1
        assert stored[0].check_code == "min_value"
        assert stored[0].evaluation_status == "failed"
        assert stored[0].failure_action == FLAG_FOR_REVIEW
        assert stored[0].qc_version == "2026.2"
        assert stored[0].params_snapshot == {"min": -10.0}
        assert stored[0].policy_provenance["settings.min"]["layer"] == "compassaq_default"


def test_gas_mass_unit_without_a_rule_is_not_configured_and_not_persisted():
    with SessionLocal() as session:
        _, device, sensor, _, _ = _context(
            session,
            parameter_code="o3",
            unit_code="ug_m3",
            provider_code="openaq",
        )

        for check_code in ("min_value", "max_value"):
            policy = resolve_effective_qc_policy(
                session, sensor.sensor_id, check_code
            )
            assert policy.status == "not_configured"
            assert policy.applicability == "not_applicable"
            assert policy.reason_code == "no_matching_rule"

        measurement, result = _insert(
            session,
            device,
            sensor,
            100.0,
            datetime.now(timezone.utc),
        )

        assert result.qc is None
        assert measurement.is_valid is True
        assert measurement.qc_flags is None
        assert _qc_results(session, measurement.measurement_id) == []


def test_gas_measurement_in_ppm_evaluates_ppm_rules_normally():
    with SessionLocal() as session:
        _, device, sensor, _, _ = _context(
            session,
            parameter_code="o3",
            unit_code="ppm",
            provider_code="openaq",
        )
        measurement, result = _insert(
            session,
            device,
            sensor,
            0.1,
            datetime.now(timezone.utc),
        )

        assert result.qc == {
            "evaluated": 1,
            "passed": 1,
            "flagged": 0,
            "indeterminate": 0,
        }
        assert measurement.is_valid is True
        assert measurement.qc_flags is None
        assert _qc_results(session, measurement.measurement_id) == []


def test_mark_invalid_failure_preserves_original_measurement():
    with SessionLocal() as session:
        _, device, sensor, _, _ = _context(
            session, parameter_code="relativehumidity", unit_code="percent"
        )
        measurement, _ = _insert(
            session,
            device,
            sensor,
            101.0,
            datetime.now(timezone.utc),
        )

        assert measurement.value == 101.0
        assert measurement.is_valid is False
        assert measurement.qc_flags == ["max_value"]
        stored = _qc_results(session, measurement.measurement_id)
        assert len(stored) == 1
        assert stored[0].failure_action == MARK_INVALID


def test_reference_max_value_plugin_runs_through_shared_ingest_and_policy_actions():
    registration = registry.get_registration("max_value")
    assert registration is not None
    assert registration.metadata.origin == "entry_point"

    with SessionLocal() as session:
        _, device, sensor, _, unit = _context(session)
        maximum_rule = models.QCRule(
            check_code="max_value",
            sensor_id=sensor.sensor_id,
            settings={"max": 100.0},
            failure_action_override=FLAG_FOR_REVIEW,
            policy_unit_id=unit.unit_id,
        )
        session.add(maximum_rule)
        session.flush()
        observed_at = datetime.now(timezone.utc)

        below_limit, below_result = _insert(
            session, device, sensor, 99.0, observed_at
        )
        assert below_result.qc == {
            "evaluated": 1,
            "passed": 1,
            "flagged": 0,
            "indeterminate": 0,
        }
        assert below_limit.is_valid is True
        assert below_limit.qc_flags is None
        assert _qc_results(session, below_limit.measurement_id) == []

        flagged, _ = _insert(
            session,
            device,
            sensor,
            101.0,
            observed_at + timedelta(seconds=1),
        )
        assert flagged.is_valid is True
        assert flagged.qc_flags == ["max_value"]
        flagged_result = _qc_results(session, flagged.measurement_id)[0]
        assert flagged_result.evaluation_status == "failed"
        assert flagged_result.failure_action == FLAG_FOR_REVIEW
        assert flagged_result.plugin_version == "1.0.0"
        assert flagged_result.params_snapshot == {"max": 100.0}
        assert (
            flagged_result.policy_provenance["settings.max"]["layer"]
            == "sensor_override"
        )

        maximum_rule.failure_action_override = MARK_INVALID
        session.flush()
        invalid, _ = _insert(
            session,
            device,
            sensor,
            102.0,
            observed_at + timedelta(seconds=2),
        )
        assert invalid.is_valid is False
        assert invalid.qc_flags == ["max_value"]
        invalid_result = _qc_results(session, invalid.measurement_id)[0]
        assert invalid_result.failure_action == MARK_INVALID
        assert invalid_result.plugin_version == "1.0.0"


def test_missing_reference_plugin_is_indeterminate_until_discovery_restores_it():
    previous_registry = tuple(registry.all_registrations().values())
    built_in_registrations = [
        registry.validate_plugin(plugin, origin="built_in")
        for plugin in BUILT_IN_PLUGINS
    ]
    try:
        registry.replace_all(built_in_registrations)
        assert registry.get_registration("max_value") is None
        maximum_metadata = next(
            item for item in get_check_metadata() if item["check_code"] == "max_value"
        )
        assert maximum_metadata["available"] is False
        assert maximum_metadata["origin"] is None

        with SessionLocal() as session:
            _, device, sensor, _, _ = _context(
                session,
                parameter_code="relativehumidity",
                unit_code="percent",
            )
            observed_at = datetime.now(timezone.utc)
            unavailable, unavailable_result = _insert(
                session, device, sensor, 101.0, observed_at
            )

            assert unavailable_result.qc == {
                "evaluated": 1,
                "passed": 0,
                "flagged": 0,
                "indeterminate": 1,
            }
            assert unavailable.is_valid is True
            assert unavailable.qc_flags is None
            unavailable_qc = _qc_results(session, unavailable.measurement_id)[0]
            assert unavailable_qc.check_code == "max_value"
            assert unavailable_qc.evaluation_status == "indeterminate"
            assert unavailable_qc.reason_code == "plugin_unavailable"
            assert unavailable_qc.plugin_version is None

            discovery.load_plugins()
            restored_registration = registry.get_registration("max_value")
            assert restored_registration is not None
            assert restored_registration.metadata.origin == "entry_point"

            evaluated, _ = _insert(
                session,
                device,
                sensor,
                101.0,
                observed_at + timedelta(seconds=1),
            )
            assert evaluated.is_valid is False
            assert evaluated.qc_flags == ["max_value"]
            evaluated_qc = _qc_results(session, evaluated.measurement_id)[0]
            assert evaluated_qc.evaluation_status == "failed"
            assert evaluated_qc.plugin_version == "1.0.0"
    finally:
        registry.replace_all(previous_registry)


def test_invalidating_and_flag_only_failures_result_in_invalid_measurement():
    with SessionLocal() as session:
        _, device, sensor, _, unit = _context(session)
        session.add_all(
            [
                models.QCRule(
                    check_code="min_value",
                    sensor_id=sensor.sensor_id,
                    settings={"min": 100.0},
                    failure_action_override=MARK_INVALID,
                    policy_unit_id=unit.unit_id,
                ),
                models.QCRule(
                    check_code="max_value",
                    sensor_id=sensor.sensor_id,
                    settings={"max": 0.0},
                    failure_action_override=FLAG_FOR_REVIEW,
                    policy_unit_id=unit.unit_id,
                ),
            ]
        )
        session.flush()
        measurement, _ = _insert(
            session,
            device,
            sensor,
            50.0,
            datetime.now(timezone.utc),
        )

        assert measurement.is_valid is False
        assert measurement.qc_flags == ["min_value", "max_value"]
        actions = {
            row.check_code: row.failure_action
            for row in _qc_results(session, measurement.measurement_id)
        }
        assert actions == {
            "max_value": FLAG_FOR_REVIEW,
            "min_value": MARK_INVALID,
        }


def test_disabled_check_is_not_invoked_or_stored():
    class DisabledCheckPlugin:
        name = f"disabled_{uuid.uuid4().hex}"
        version = "test"
        qc_api = 1
        required_access = "api-only"
        display_name = "Disabled test check"
        description = "Records whether a disabled test check was called"
        long_description = "Test plugin that must never run while disabled."
        param_schema = {}
        unit_settings = ()

        def __init__(self):
            self.calls = 0

        def apply(self, records, context):
            self.calls += 1
            return [QCDecision(False, ["unexpected"], "error") for _ in records]

    previous_registry = tuple(all_registrations().values())
    try:
        plugin = DisabledCheckPlugin()
        register(plugin)
        with SessionLocal() as session:
            _, device, sensor, parameter, _ = _context(session)
            session.add(
                models.QCRule(
                    check_code=plugin.name,
                    parameter_id=parameter.parameter_id,
                    enabled_override=False,
                    failure_action_override=FLAG_FOR_REVIEW,
                )
            )
            session.flush()
            measurement, _ = _insert(
                session,
                device,
                sensor,
                10.0,
                datetime.now(timezone.utc),
            )

            assert plugin.calls == 0
            assert all(
                row.check_code != plugin.name
                for row in _qc_results(session, measurement.measurement_id)
            )
    finally:
        replace_all(previous_registry)


def test_incomplete_policy_and_unavailable_plugin_are_stored_as_indeterminate():
    with SessionLocal() as session:
        _, device, sensor, _, unit = _context(
            session,
            parameter_code="no",
            unit_code="ppb",
        )
        unavailable_check = f"unavailable_{uuid.uuid4().hex}"
        session.add_all(
            [
                models.QCRule(
                    check_code="baseline_drift",
                    sensor_id=sensor.sensor_id,
                    enabled_override=True,
                    settings={"lookback_hours": 24},
                    policy_unit_id=unit.unit_id,
                ),
                models.QCRule(
                    check_code=unavailable_check,
                    sensor_id=sensor.sensor_id,
                    enabled_override=True,
                    failure_action_override=FLAG_FOR_REVIEW,
                    settings={"limit": 1},
                ),
            ]
        )
        session.flush()
        measurement, _ = _insert(
            session,
            device,
            sensor,
            10.0,
            datetime.now(timezone.utc),
        )

        assert measurement.is_valid is True
        assert measurement.qc_flags is None
        outcomes = {
            row.check_code: row
            for row in _qc_results(session, measurement.measurement_id)
        }
        assert outcomes["baseline_drift"].passed is None
        assert outcomes["baseline_drift"].reason_code == "missing_required_setting"
        assert outcomes[unavailable_check].passed is None
        assert outcomes[unavailable_check].reason_code == "plugin_unavailable"


def test_baseline_drift_warmup_keeps_one_trace_row_per_sensor():
    with SessionLocal() as session:
        _, device, sensor, _, unit = _context(session)
        session.add(
            models.QCRule(
                check_code="baseline_drift",
                sensor_id=sensor.sensor_id,
                enabled_override=True,
                policy_unit_id=unit.unit_id,
            )
        )
        session.flush()
        first_observed_at = datetime.now(timezone.utc) - timedelta(hours=1)
        first, first_result = _insert(
            session,
            device,
            sensor,
            10.0,
            first_observed_at,
        )
        second, second_result = _insert(
            session,
            device,
            sensor,
            11.0,
            first_observed_at + timedelta(hours=1),
        )

        first_rows = _qc_results(session, first.measurement_id)
        second_rows = _qc_results(session, second.measurement_id)
        assert first_result.qc["indeterminate"] == 1
        assert second_result.qc["indeterminate"] == 1
        assert len(first_rows) == 1
        assert first_rows[0].check_code == "baseline_drift"
        assert first_rows[0].reason_code == "insufficient_history"
        assert second_rows == []
        assert first.is_valid is True
        assert second.is_valid is True


def test_allowed_update_replaces_qc_state_but_skipped_duplicate_does_not():
    with SessionLocal() as session:
        _, device, sensor, _, _ = _context(
            session, allow_updates=models.UpdatePolicy.ALLOW
        )
        observed_at = datetime.now(timezone.utc)
        original, first = _insert(session, device, sensor, -20.0, observed_at)
        assert first.action == "insert"
        assert len(_qc_results(session, original.measurement_id)) == 1

        replacement = models.Measurement(
            sensor_id=sensor.sensor_id,
            value=10.0,
            observed_at=observed_at,
        )
        updated = upsert_measurement_with_policy_detailed(
            session, replacement, device=device, sensor=sensor
        )
        session.flush()
        assert updated.action == "update"
        session.refresh(original)
        assert original.value == 10.0
        assert original.is_valid is True
        assert original.qc_flags is None
        assert _qc_results(session, original.measurement_id) == []

        sensor.allow_updates = models.UpdatePolicy.DENY
        session.flush()
        skipped_value = models.Measurement(
            sensor_id=sensor.sensor_id,
            value=-30.0,
            observed_at=observed_at,
        )
        skipped = upsert_measurement_with_policy_detailed(
            session, skipped_value, device=device, sensor=sensor
        )
        assert skipped.action == "skip"
        session.refresh(original)
        assert original.value == 10.0
        assert _qc_results(session, original.measurement_id) == []


def test_policy_edit_does_not_reprocess_historical_measurement():
    with SessionLocal() as session:
        _, device, sensor, _, _ = _context(session)
        measurement, _ = _insert(
            session,
            device,
            sensor,
            -20.0,
            datetime.now(timezone.utc) - timedelta(days=1),
        )
        original_result_ids = [
            row.measurement_qc_result_id
            for row in _qc_results(session, measurement.measurement_id)
        ]
        session.add(
            models.QCRule(
                check_code="min_value",
                sensor_id=sensor.sensor_id,
                enabled_override=False,
                policy_unit_id=sensor.unit_id,
            )
        )
        session.flush()

        session.refresh(measurement)
        assert measurement.is_valid is True
        assert measurement.qc_flags == ["min_value"]
        assert [
            row.measurement_qc_result_id
            for row in _qc_results(session, measurement.measurement_id)
        ] == original_result_ids


def test_all_three_importers_reference_the_shared_qc_upsert():
    from sources.airgradient import importer as airgradient_importer
    from sources.openaq import importer as openaq_importer
    from sources.purpleair import importer as purpleair_importer

    assert (
        openaq_importer.upsert_measurement_with_policy_detailed
        is upsert_measurement_with_policy_detailed
    )
    assert (
        purpleair_importer.upsert_measurement_with_policy_detailed
        is upsert_measurement_with_policy_detailed
    )
    assert (
        airgradient_importer.upsert_measurement_with_policy_detailed
        is upsert_measurement_with_policy_detailed
    )
