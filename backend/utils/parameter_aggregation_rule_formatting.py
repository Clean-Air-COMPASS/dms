from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set
import math

from sqlalchemy import select, cast, String, func, or_
from sqlalchemy.orm import Session

from models import AggregationPeriod, Parameter, ParameterAggregationRule


@dataclass
class ParameterAggregationRuleFormatting:
    rounding_method: Optional[str]
    rounding_precision: Optional[int]
    truncation_method: Optional[str]
    truncation_precision: Optional[int]


def parameter_aggregation_display_precision(
    rule: Optional[ParameterAggregationRuleFormatting],
) -> Optional[int]:
    """Return the decimal precision clients may use to present a formatted value."""

    if rule is None:
        return None
    if (rule.rounding_method or "").lower() != "none" and rule.rounding_precision is not None:
        return max(rule.rounding_precision, 0)
    if (rule.truncation_method or "").lower() != "none" and rule.truncation_precision is not None:
        return max(rule.truncation_precision, 0)
    return None


def _round_half_up_from_scaled(scaled_value: float, factor: float) -> float:
    """Mirror JavaScript Math.round behavior for consistency with existing UI logic."""
    return math.floor(scaled_value + 0.5) / factor


def apply_parameter_aggregation_rule(
    value: Optional[float],
    rounding_method: Optional[str],
    rounding_precision: Optional[int],
    truncation_method: Optional[str],
    truncation_precision: Optional[int],
) -> Optional[float]:
    """Apply truncation then rounding based on configured rule; returns None when value is None."""
    if value is None:
        return None

    processed = value

    normalized_truncation_method = (truncation_method or "").lower()
    if normalized_truncation_method and normalized_truncation_method != "none":
        precision = max(truncation_precision if truncation_precision is not None else 0, 0)
        factor = math.pow(10, precision)
        if math.isfinite(factor) and factor != 0:
            scaled = processed * factor
            if normalized_truncation_method == "truncate":
                processed = math.trunc(scaled) / factor
            elif normalized_truncation_method == "floor":
                processed = math.floor(scaled) / factor
            elif normalized_truncation_method == "ceil":
                processed = math.ceil(scaled) / factor

    normalized_rounding_method = (rounding_method or "").lower()
    if normalized_rounding_method and normalized_rounding_method != "none" and rounding_precision is not None:
        precision = max(rounding_precision, 0)
        factor = math.pow(10, precision)
        if math.isfinite(factor) and factor != 0:
            scaled_value = processed * factor
            if normalized_rounding_method == "round":
                processed = _round_half_up_from_scaled(scaled_value, factor)
            elif normalized_rounding_method == "floor":
                processed = math.floor(scaled_value) / factor
            elif normalized_rounding_method == "ceil":
                processed = math.ceil(scaled_value) / factor

    if processed == 0:
        return 0.0
    return processed


def load_parameter_aggregation_rules(
    session: Session, parameter_code: str, aggregation_codes: Iterable[str]
) -> Dict[str, ParameterAggregationRuleFormatting]:
    """Load currently effective rules for the requested aggregation codes.

    Ordinary measurement formatting is period-specific.  A missing rule means
    that the calculated value is returned unchanged; another period's rule is
    never substituted.
    """
    normalized_parameter_code = (parameter_code or "").lower()
    if not normalized_parameter_code:
        return {}

    requested_codes: Set[str] = {code.lower() for code in aggregation_codes if code}
    if not requested_codes:
        return {}

    active_truthy_values = {"true", "True", "TRUE", "t", "T", "1"}

    stmt = (
        select(
            AggregationPeriod.code.label("aggregation_code"),
            ParameterAggregationRule.rounding_method,
            ParameterAggregationRule.rounding_precision,
            ParameterAggregationRule.truncation_method,
            ParameterAggregationRule.truncation_precision,
        )
        .select_from(ParameterAggregationRule)
        .join(Parameter, Parameter.parameter_id == ParameterAggregationRule.parameter_id)
        .join(
            AggregationPeriod,
            AggregationPeriod.aggregation_period_id == ParameterAggregationRule.aggregation_period_id,
        )
        .where(Parameter.code == normalized_parameter_code)
        .where(AggregationPeriod.code.in_(requested_codes))
        .where(cast(ParameterAggregationRule.active, String).in_(active_truthy_values))
        .where(
            or_(
                ParameterAggregationRule.valid_from.is_(None),
                ParameterAggregationRule.valid_from <= func.now(),
            )
        )
        .where(
            or_(
                ParameterAggregationRule.valid_to.is_(None),
                ParameterAggregationRule.valid_to > func.now(),
            )
        )
    )
    rows = session.execute(stmt).all()

    rules_by_aggregation_code: Dict[str, ParameterAggregationRuleFormatting] = {}
    for row in rows:
        rules_by_aggregation_code[(row.aggregation_code or "").lower()] = ParameterAggregationRuleFormatting(
            rounding_method=row.rounding_method,
            rounding_precision=row.rounding_precision,
            truncation_method=row.truncation_method,
            truncation_precision=row.truncation_precision,
        )
    return rules_by_aggregation_code


def resolve_parameter_aggregation_rule(
    rules_by_aggregation_code: Dict[str, ParameterAggregationRuleFormatting],
    aggregation_code: Optional[str],
) -> Optional[ParameterAggregationRuleFormatting]:
    """Return only the exact rule for the produced aggregation period."""
    normalized_code = (aggregation_code or "").lower()
    if normalized_code and normalized_code in rules_by_aggregation_code:
        return rules_by_aggregation_code[normalized_code]
    return None
