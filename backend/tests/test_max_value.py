from __future__ import annotations

import math

from compassaq_max_value import MaxValuePlugin
from qaqc.policy import EffectiveQCPolicy
from qaqc.types import QCRecord


def _policy(maximum: float) -> EffectiveQCPolicy:
    return EffectiveQCPolicy(
        check_code="max_value",
        status="ready",
        enabled=True,
        failure_action="flag_for_review",
        configured_settings={"max": maximum},
        evaluation_settings={"max": maximum},
        configured_unit_code="ug_m3",
        evaluation_unit_code="ug_m3",
    )


def test_max_value_plugin_uses_resolved_policy_only():
    plugin = MaxValuePlugin()
    records = [
        QCRecord(None, None, 10.0, None, None),
        QCRecord(None, None, 10.001, None, None),
    ]
    out = plugin.apply(
        records,
        {"effective_policies": [_policy(10.0), _policy(10.0)]},
    )
    assert out[0].is_valid is True
    assert out[1].is_valid is False
    assert out[1].flags == ["range_fail"]


def test_max_value_plugin_has_no_hidden_fallback():
    plugin = MaxValuePlugin()
    record = QCRecord(None, None, 1_000_500.0, None, None)
    decision = plugin.apply([record], {"effective_policies": []})[0]
    assert decision.is_valid is None
    assert decision.patch == {"reason_code": "missing_effective_policy"}


def test_max_value_plugin_returns_indeterminate_for_invalid_measurements():
    plugin = MaxValuePlugin()
    invalid_values = [None, "not-a-number", math.nan, math.inf]
    records = [QCRecord(None, None, value, None, None) for value in invalid_values]
    decisions = plugin.apply(
        records,
        {"effective_policies": [_policy(10.0) for _ in records]},
    )

    assert len(decisions) == len(records)
    assert all(decision.is_valid is None for decision in decisions)
    assert all(
        decision.patch == {"reason_code": "invalid_measurement_value"}
        for decision in decisions
    )


def test_max_value_plugin_rejects_invalid_resolved_setting_explicitly():
    plugin = MaxValuePlugin()
    decision = plugin.apply(
        [QCRecord(None, None, 10.0, None, None)],
        {"effective_policies": [_policy(math.nan)]},
    )[0]

    assert decision.is_valid is None
    assert decision.patch == {"reason_code": "invalid_policy_setting"}
