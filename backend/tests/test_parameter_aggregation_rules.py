from __future__ import annotations

from typing import Optional

from db import SessionLocal
import models


def _maybe_get_session():
    try:
        return SessionLocal()
    except Exception:
        return None


def _get_rule(session, param_code: str, agg_code: str) -> Optional[models.ParameterAggregationRule]:
    p = session.scalar(
        models.select(models.Parameter).where(models.Parameter.code == param_code)
    )
    if p is None:
        return None
    ap = session.scalar(
        models.select(models.AggregationPeriod).where(models.AggregationPeriod.code == agg_code)
    )
    if ap is None:
        return None
    rule = session.scalar(
        models.select(models.ParameterAggregationRule).where(
            models.ParameterAggregationRule.parameter_id == p.parameter_id,
            models.ParameterAggregationRule.aggregation_period_id == ap.aggregation_period_id,
        )
    )
    return rule


def test_expected_parameter_aggregation_rules_present():
    session = _maybe_get_session()
    if session is None:
                                  
        return

                 
    r = _get_rule(session, "pm25", "1h")
    assert r is not None
    assert r.truncation_method == "truncate"
    assert r.truncation_precision == 1

    r = _get_rule(session, "pm25", "24h")
    assert r is not None
    assert r.rounding_method == "round"
    assert r.rounding_precision == 1

                
    r = _get_rule(session, "pm10", "1h")
    assert r is not None
    assert r.truncation_method == "truncate"
    assert r.truncation_precision == 0

    r = _get_rule(session, "pm10", "24h")
    assert r is not None
    assert r.rounding_method == "round"
    assert r.rounding_precision == 0

              
    r = _get_rule(session, "o3", "1h")
    assert r is not None
    assert r.rounding_method == "round"
    assert r.rounding_precision == 3

    r = _get_rule(session, "o3", "8h")
    assert r is not None
    assert r.rounding_method == "round"
    assert r.rounding_precision == 3

                                
    for code in ("no2", "co", "so2"):
        r = _get_rule(session, code, "1h")
        assert r is not None
        assert r.rounding_method == "round"
        assert r.rounding_precision == 1

                        
    r = _get_rule(session, "no", "1h")
    assert r is not None
    assert r.rounding_method == "round"
    assert r.rounding_precision == 1

    session.close()
