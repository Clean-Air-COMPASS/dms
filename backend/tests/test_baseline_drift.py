from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import models
from db import SessionLocal
from qaqc.builtin_plugins.baseline_drift import BaselineDriftPlugin, _evaluate_record, _quantile
from qaqc.policy import resolve_effective_qc_policy
from qaqc.policy_defaults import FLAG_FOR_REVIEW
from qaqc.types import QCRecord


def _create_sensor(session, parameter_code: str = "pm25"):
    api = models.ExternalAPI(name=f"test_api_{uuid.uuid4()}", params={})
    session.add(api)
    session.flush()
    device = models.Device(name=f"Test Device {uuid.uuid4()}", external_api_id=api.external_api_id)
    session.add(device)
    session.flush()
    param = session.scalar(
        select(models.Parameter).where(models.Parameter.code == parameter_code)
    )
    if param is None:
        unit = session.scalar(select(models.Unit).where(models.Unit.code == "ug_m3"))
        param = models.Parameter(
            code=parameter_code,
            display_name=parameter_code,
            default_unit_id=unit.unit_id,
        )
        session.add(param)
        session.flush()
        session.add(
            models.ParameterSupportedUnit(
                parameter_id=param.parameter_id,
                unit_id=unit.unit_id,
            )
        )
        session.flush()
    sensor = models.Sensor(
        device_id=device.device_id,
        parameter_id=param.parameter_id,
        unit_id=param.default_unit_id,
    )
    session.add(sensor)
    session.flush()
    return sensor, param


def _insert_measurements(session, sensor_id: int, points: list[tuple[datetime, float]]) -> None:
    for ts, val in points:
        session.add(models.Measurement(sensor_id=sensor_id, value=val, observed_at=ts, is_valid=True))
    session.commit()


def test_quantile_basic():
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert _quantile(values, 0.0) == 0.0
    assert _quantile(values, 1.0) == 4.0
    assert _quantile(values, 0.5) == 2.0


def test_baseline_drift_detects_upward_baseline_shift():
    with SessionLocal() as session:
        sensor, param = _create_sensor(
            session, f"baseline_direction_{uuid.uuid4().hex[:12]}"
        )
        now = datetime(2025, 1, 3, tzinfo=timezone.utc)

        points: list[tuple[datetime, float]] = []
        for i in range(12):
            ts = now - timedelta(hours=46 - i)
            points.append((ts, 0.05 * i))
        for i in range(12):
            ts = now - timedelta(hours=10 - i)
            points.append((ts, 5.0 + 0.05 * i))
        _insert_measurements(session, sensor.sensor_id, points)

        rule = models.QCRule(
            check_code="baseline_drift",
            sensor_id=sensor.sensor_id,
            aggregate_code="1h",
            enabled_override=True,
            failure_action_override=FLAG_FOR_REVIEW,
            policy_unit_id=param.default_unit_id,
            settings={
                "lookback_hours": 48,
                "min_samples": 8,
                "baseline_quantile": 0.1,
                "max_drift_per_day": 1.0,
                "direction": "both",
            },
        )
        session.add(rule)
        session.commit()

        plugin = BaselineDriftPlugin()
        record = QCRecord(
            sensor_id=sensor.sensor_id,
            parameter_id=param.parameter_id,
            value=5.1,
            unit_id=param.default_unit_id,
            observed_at=now,
        )
        policy = resolve_effective_qc_policy(
            session, sensor.sensor_id, "baseline_drift", "1h"
        )
        out = plugin.apply(
            [record],
            {"session": session, "effective_policies": [policy]},
        )
        assert len(out) == 1
        dec = out[0]
        assert dec.is_valid is False
        assert "baseline_drift" in dec.flags
        assert dec.patch is not None
        assert policy.most_specific_source.qc_rule_id == rule.qc_rule_id
        assert dec.patch.get("drift_per_day", 0) > policy.evaluation_settings["max_drift_per_day"]


def test_baseline_drift_insufficient_samples():
    with SessionLocal() as session:
        sensor, param = _create_sensor(
            session, f"baseline_split_{uuid.uuid4().hex[:12]}"
        )
        now = datetime(2025, 1, 5, tzinfo=timezone.utc)

        points = [
            (now - timedelta(hours=10), 0.1),
            (now - timedelta(hours=5), 0.2),
            (now - timedelta(hours=1), 0.3),
        ]
        _insert_measurements(session, sensor.sensor_id, points)

        rule = models.QCRule(
            check_code="baseline_drift",
            sensor_id=sensor.sensor_id,
            aggregate_code="1h",
            enabled_override=True,
            failure_action_override=FLAG_FOR_REVIEW,
            policy_unit_id=param.default_unit_id,
            settings={
                "lookback_hours": 24,
                "min_samples": 10,
                "baseline_quantile": 0.1,
                "max_drift_per_day": 1.0,
                "direction": "both",
            },
        )
        session.add(rule)
        session.commit()

        plugin = BaselineDriftPlugin()
        record = QCRecord(
            sensor_id=sensor.sensor_id,
            parameter_id=param.parameter_id,
            value=0.3,
            unit_id=param.default_unit_id,
            observed_at=now,
        )
        policy = resolve_effective_qc_policy(
            session, sensor.sensor_id, "baseline_drift", "1h"
        )
        out = plugin.apply(
            [record],
            {"session": session, "effective_policies": [policy]},
        )
        assert len(out) == 1
        assert out[0].is_valid is None


@pytest.mark.parametrize(
    "direction,older_value,recent_value,expected_valid",
    [
        ("up", 0.0, 4.0, False),
        ("down", 4.0, 0.0, False),
        ("both", 0.0, 4.0, False),
        ("both", 4.0, 0.0, False),
        ("up", 4.0, 0.0, True),
        ("down", 0.0, 4.0, True),
        ("both", 0.0, 1.0, True),
    ],
)
def test_baseline_drift_direction_and_pass_behavior(
    direction, older_value, recent_value, expected_valid
):
    with SessionLocal() as session:
        sensor, param = _create_sensor(
            session, f"baseline_direction_{uuid.uuid4().hex[:12]}"
        )
        now = datetime(2025, 2, 3, tzinfo=timezone.utc)
        points = [
            (now - timedelta(hours=46 - index), older_value)
            for index in range(4)
        ] + [
            (now - timedelta(hours=10 - index), recent_value)
            for index in range(4)
        ]
        _insert_measurements(session, sensor.sensor_id, points)
        session.add(
            models.QCRule(
                check_code="baseline_drift",
                sensor_id=sensor.sensor_id,
                enabled_override=True,
                failure_action_override=FLAG_FOR_REVIEW,
                policy_unit_id=param.default_unit_id,
                settings={
                    "lookback_hours": 48,
                    "min_samples": 8,
                    "baseline_quantile": 0.1,
                    "max_drift_per_day": 1.0,
                    "direction": direction,
                },
            )
        )
        session.commit()
        policy = resolve_effective_qc_policy(
            session, sensor.sensor_id, "baseline_drift", "1h"
        )
        decision = BaselineDriftPlugin().apply(
            [
                QCRecord(
                    sensor_id=sensor.sensor_id,
                    parameter_id=param.parameter_id,
                    value=recent_value,
                    unit_id=param.default_unit_id,
                    observed_at=now,
                )
            ],
            {"session": session, "effective_policies": [policy]},
        )[0]
        assert decision.is_valid is expected_valid


def test_baseline_drift_requires_enough_samples_in_each_half():
    with SessionLocal() as session:
        sensor, param = _create_sensor(
            session, f"baseline_split_{uuid.uuid4().hex[:12]}"
        )
        now = datetime(2025, 3, 3, tzinfo=timezone.utc)
        points = [(now - timedelta(hours=40), 1.0)] + [
            (now - timedelta(hours=9 - index), 5.0)
            for index in range(9)
        ]
        _insert_measurements(session, sensor.sensor_id, points)
        session.add(
            models.QCRule(
                check_code="baseline_drift",
                sensor_id=sensor.sensor_id,
                enabled_override=True,
                failure_action_override=FLAG_FOR_REVIEW,
                policy_unit_id=param.default_unit_id,
                settings={
                    "lookback_hours": 48,
                    "min_samples": 8,
                    "baseline_quantile": 0.1,
                    "max_drift_per_day": 1.0,
                    "direction": "both",
                },
            )
        )
        session.commit()
        policy = resolve_effective_qc_policy(
            session, sensor.sensor_id, "baseline_drift", "1h"
        )
        decision = BaselineDriftPlugin().apply(
            [
                QCRecord(
                    sensor_id=sensor.sensor_id,
                    parameter_id=param.parameter_id,
                    value=5.0,
                    unit_id=param.default_unit_id,
                    observed_at=now,
                )
            ],
            {"session": session, "effective_policies": [policy]},
        )[0]
        assert decision.is_valid is None
        assert decision.patch["reason_code"] == "insufficient_history"
        assert decision.patch["older_samples"] == 1
        assert decision.patch["required_samples_per_half"] == 4


@pytest.fixture
def indicator_context():
    """Eight days with a four-sample minimum in each half."""
    with SessionLocal() as session:
        sensor, parameter = _create_sensor(session, f"baseline_history_{uuid.uuid4().hex[:12]}")
        start = datetime(2025, 4, 1, tzinfo=timezone.utc)
        record = QCRecord(sensor.sensor_id, parameter.parameter_id, 1000.0,
                          parameter.default_unit_id, start + timedelta(days=8))
        settings = dict(lookback_hours=192, min_samples=8, baseline_quantile=0.1,
                        max_drift_per_day=0.5, direction="both")
        yield session, sensor, start, record, settings


def _daily_history(session, sensor, start, values, *, is_valid=True, flags=None):
    for day, value in enumerate(values):
        session.add(models.Measurement(
            sensor_id=sensor.sensor_id, observed_at=start + timedelta(days=day),
            value=value, is_valid=is_valid, qc_flags=flags,
        ))
    session.flush()


def test_linear_trend_returns_normalized_shift_not_physical_slope(indicator_context):
    session, sensor, start, record, settings = indicator_context
    # Physical slope is 2 units/day. Independently interpolated 10th percentiles
    # are 0 + .3*(2-0) = .6 and 8 + .3*(10-8) = 8.6; (8.6-.6)/8 = 1.
    _daily_history(session, sensor, start, [0, 2, 4, 6, 8, 10, 12, 14])
    decision = _evaluate_record(session, record, settings)
    assert decision.patch["baseline_old"] == pytest.approx(0.6)
    assert decision.patch["baseline_recent"] == pytest.approx(8.6)
    assert decision.patch["drift_per_day"] == pytest.approx(1.0)
    assert decision.patch["drift_per_day"] != pytest.approx(2.0)
    assert "baseline shift indicator" in decision.message


def test_step_change_reports_shift_without_continuing_slope(indicator_context):
    session, sensor, start, record, settings = indicator_context
    # Both plateaus have zero slope; the 8-unit step still gives 8/8 = 1.
    _daily_history(session, sensor, start, [0, 0, 0, 0, 8, 8, 8, 8])
    decision = _evaluate_record(session, record, settings)
    assert decision.patch["drift_per_day"] == pytest.approx(1.0)
    assert decision.is_valid is False


@pytest.mark.parametrize("recent_value,expected_valid", [(3.999, True), (4, True), (4.001, False)])
def test_normalized_shift_retains_strict_threshold_boundary(indicator_context, recent_value, expected_valid):
    session, sensor, start, record, settings = indicator_context
    _daily_history(session, sensor, start, [0]*4 + [recent_value]*4)
    decision = _evaluate_record(session, record, settings)
    assert decision.patch["drift_per_day"] == pytest.approx(recent_value / 8)
    assert decision.is_valid is expected_valid


@pytest.mark.parametrize("failure_check", ["min_value", "baseline_drift"])
@pytest.mark.parametrize("recent_value,invalid_day,invalid_value,expected_valid", [
    (10, 0, -100, True),  # Rejected low older values cannot create a false positive.
    (18, 4, 10, False),  # Rejected low recent values cannot hide a real shift.
])
def test_invalid_history_cannot_create_or_mask_shift(
    indicator_context, failure_check, recent_value, invalid_day, invalid_value, expected_valid,
):
    session, sensor, start, record, settings = indicator_context
    _daily_history(session, sensor, start, [10]*4 + [recent_value]*4)
    before = _evaluate_record(session, record, settings)
    for hour in range(1, 11):
        session.add(models.Measurement(
            sensor_id=sensor.sensor_id,
            observed_at=start + timedelta(days=invalid_day, hours=hour),
            value=invalid_value, is_valid=False, qc_flags=[failure_check],
        ))
    session.flush()
    after = _evaluate_record(session, record, settings)
    assert after == before
    assert after.is_valid is expected_valid
    assert after.patch["samples"] == 8
    assert after.patch["older_samples"] == after.patch["recent_samples"] == 4


@pytest.mark.parametrize("invalid_days,minimum,expected_samples", [
    (range(8), 8, 0),  # No qualifying history.
    ([0], 8, 7),  # Total minimum no longer met.
    ([0, 1], 6, 6),  # Total met, but older-half minimum no longer met.
])
def test_invalid_exclusion_can_leave_insufficient_history(indicator_context, invalid_days, minimum, expected_samples):
    session, sensor, start, record, settings = indicator_context
    _daily_history(session, sensor, start, [0]*4 + [8]*4)
    for row in session.scalars(select(models.Measurement).where(models.Measurement.sensor_id == sensor.sensor_id)):
        if (row.observed_at.date() - start.date()).days in invalid_days:
            row.is_valid = False
            row.qc_flags = ["min_value"]
    session.flush()
    decision = _evaluate_record(session, record, {**settings, "min_samples": minimum})
    assert decision.is_valid is None
    assert decision.flags == []
    assert decision.patch["reason_code"] == "insufficient_history"
    assert decision.patch["samples"] == expected_samples


def test_flag_for_review_history_remains_eligible(indicator_context):
    session, sensor, start, record, settings = indicator_context
    _daily_history(session, sensor, start, [0]*4 + [8]*4, flags=["min_value"])
    decision = _evaluate_record(session, record, settings)
    assert decision.patch["samples"] == 8
    assert decision.patch["baseline_old"] == 0
    assert decision.patch["baseline_recent"] == 8
    assert decision.patch["drift_per_day"] == 1
    assert decision.is_valid is False


@pytest.mark.parametrize("operation", ["insert", "update"])
@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("flush_candidate", [False, True])
def test_candidate_is_excluded_independently_of_flush_timing(
    indicator_context, operation, autoflush, flush_candidate,
):
    session, sensor, start, record, settings = indicator_context
    _daily_history(session, sensor, start, [0]*4 + [8]*4)
    expected = _evaluate_record(session, record, settings)
    candidate = models.Measurement(sensor_id=sensor.sensor_id, observed_at=record.observed_at,
                                   value=-1000, is_valid=True)
    session.add(candidate)
    if operation == "update":
        session.flush()  # Persist the old candidate before changing its value.
        candidate.value = record.value
    session.autoflush = autoflush
    if flush_candidate:
        session.flush()
    assert _evaluate_record(session, record, settings) == expected
    # Nor may the candidate make an otherwise insufficient history evaluable.
    short = _evaluate_record(session, record, {**settings, "min_samples": 9})
    assert short.patch["reason_code"] == "insufficient_history"
    assert short.patch["samples"] == 8


def test_history_window_includes_start_excludes_future_and_other_sensors(indicator_context):
    session, sensor, start, record, settings = indicator_context
    _daily_history(session, sensor, start, [0]*4 + [8]*4)
    other, _ = _create_sensor(session, f"other_history_{uuid.uuid4().hex[:12]}")
    _daily_history(session, other, start, [-1000]*8)
    _daily_history(session, sensor, start - timedelta(seconds=1), [-1000])
    _daily_history(session, sensor, record.observed_at + timedelta(seconds=1), [-1000])
    decision = _evaluate_record(session, record, settings)
    assert decision.patch["samples"] == 8
    assert decision.patch["drift_per_day"] == 1


@pytest.mark.parametrize("action,expected_samples,expected_reason", [
    ("mark_invalid", 4, "insufficient_history"),
    ("flag_for_review", 8, None),
])
def test_ingested_failure_action_controls_later_baseline_history(
    indicator_context, action, expected_samples, expected_reason,
):
    from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed

    session, sensor, start, record, settings = indicator_context
    session.add(models.QCRule(
        check_code="min_value", sensor_id=sensor.sensor_id, enabled_override=True,
        failure_action_override=action, policy_unit_id=sensor.unit_id, settings={"min": 0},
    ))
    session.flush()
    for day, value in enumerate([-100]*4 + [10]*4):
        history = models.Measurement(sensor_id=sensor.sensor_id, value=value,
                                     observed_at=start + timedelta(days=day))
        upsert_measurement_with_policy_detailed(session, history, sensor=sensor)
        assert history.is_valid is (value >= 0 or action == "flag_for_review")
        if value < 0:
            assert history.qc_flags == ["min_value"]
    session.add(models.QCRule(
        check_code="baseline_drift", sensor_id=sensor.sensor_id, enabled_override=True,
        failure_action_override="flag_for_review", policy_unit_id=sensor.unit_id, settings=settings,
    ))
    session.flush()
    candidate = models.Measurement(sensor_id=sensor.sensor_id, value=10, observed_at=record.observed_at)
    upsert_measurement_with_policy_detailed(session, candidate, sensor=sensor)
    session.flush()
    result = session.scalar(select(models.MeasurementQCResult).where(
        models.MeasurementQCResult.measurement_id == candidate.measurement_id,
        models.MeasurementQCResult.check_code == "baseline_drift",
    ))
    assert result is not None
    assert result.details["samples"] == expected_samples
    assert result.reason_code == expected_reason
    assert candidate.is_valid is True
    assert result.plugin_version == "1.1.0"
    if action == "flag_for_review":
        assert result.passed is False
        assert result.details["drift_per_day"] == pytest.approx(13.75)
    else:
        assert result.passed is None
