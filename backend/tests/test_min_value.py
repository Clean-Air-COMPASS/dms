from __future__ import annotations

from qaqc.plugins import MinValuePlugin
from qaqc.policy import EffectiveQCPolicy
from qaqc.rules import min_value as qc_min
from qaqc.types import QCRecord


def _policy(minimum: float) -> EffectiveQCPolicy:
    return EffectiveQCPolicy(
        check_code="min_value",
        status="ready",
        enabled=True,
        failure_action="flag_for_review",
        configured_settings={"min": minimum},
        evaluation_settings={"min": minimum},
        configured_unit_code="ug_m3",
        evaluation_unit_code="ug_m3",
    )


def test_min_value_rule_requires_explicit_threshold():
    assert qc_min.evaluate(-10.0, threshold=-10.0) is True
    assert qc_min.evaluate(-10.001, threshold=-10.0) is False
    assert qc_min.evaluate(None, threshold=-10.0) is None


def test_min_value_plugin_uses_resolved_policy_only():
    plugin = MinValuePlugin()
    records = [
        QCRecord(None, None, -10.0, None, None),
        QCRecord(None, None, -10.001, None, None),
    ]
    decisions = plugin.apply(
        records,
        {"effective_policies": [_policy(-10.0), _policy(-10.0)]},
    )
    assert decisions[0].is_valid is True
    assert decisions[1].is_valid is False
    assert decisions[1].flags == ["range_fail"]


def test_min_value_plugin_has_no_hidden_fallback():
    plugin = MinValuePlugin()
    record = QCRecord(None, None, -999.0, None, None)
    decision = plugin.apply([record], {"effective_policies": []})[0]
    assert decision.is_valid is None
    assert decision.patch == {"reason_code": "missing_required_setting"}
