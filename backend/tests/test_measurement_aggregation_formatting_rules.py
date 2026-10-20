from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from db import SessionLocal
from models import AggregationPeriod, Parameter, ParameterAggregationRule, Unit
from utils.parameter_aggregation_rule_formatting import load_parameter_aggregation_rules


def test_only_active_current_exact_period_formatting_rules_are_loaded() -> None:
    session = SessionLocal()
    suffix = uuid4().hex[:12]
    try:
        unit = Unit(code=f"unit_{suffix}", symbol="test", name="Formatting test unit")
        session.add(unit)
        session.flush()
        parameter = Parameter(
            code=f"format_{suffix}",
            display_name="Formatting test",
            default_unit_id=unit.unit_id,
        )
        periods = {
            status: AggregationPeriod(
                code=f"{status}_{suffix}",
                display_name=status,
                duration_minutes=index + 1,
                is_rolling=False,
            )
            for index, status in enumerate(("current", "inactive", "future", "expired"))
        }
        session.add(parameter)
        session.add_all(periods.values())
        session.flush()
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                ParameterAggregationRule(
                    parameter_id=parameter.parameter_id,
                    aggregation_period_id=periods["current"].aggregation_period_id,
                    rounding_method="round",
                    rounding_precision=2,
                    truncation_method="none",
                    active=True,
                    valid_from=now - timedelta(days=1),
                    valid_to=now + timedelta(days=1),
                ),
                ParameterAggregationRule(
                    parameter_id=parameter.parameter_id,
                    aggregation_period_id=periods["inactive"].aggregation_period_id,
                    rounding_method="round",
                    rounding_precision=1,
                    truncation_method="none",
                    active=False,
                ),
                ParameterAggregationRule(
                    parameter_id=parameter.parameter_id,
                    aggregation_period_id=periods["future"].aggregation_period_id,
                    rounding_method="round",
                    rounding_precision=1,
                    truncation_method="none",
                    active=True,
                    valid_from=now + timedelta(days=1),
                ),
                ParameterAggregationRule(
                    parameter_id=parameter.parameter_id,
                    aggregation_period_id=periods["expired"].aggregation_period_id,
                    rounding_method="round",
                    rounding_precision=1,
                    truncation_method="none",
                    active=True,
                    valid_to=now - timedelta(days=1),
                ),
            ]
        )
        session.flush()

        rules = load_parameter_aggregation_rules(
            session, parameter.code, {period.code for period in periods.values()}
        )
        assert set(rules) == {periods["current"].code}
        assert rules[periods["current"].code].rounding_precision == 2
    finally:
        session.rollback()
        session.close()
