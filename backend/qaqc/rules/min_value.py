from __future__ import annotations

from typing import Optional, Tuple
from sqlalchemy import select

import models


DEFAULT_MIN_VALUE = -5.0
CHECK_CODE = "min_value"


def resolve_min_threshold(session, sensor_id: Optional[int], parameter_id: Optional[int], aggregate_code: Optional[str] = None) -> float:
    """Return the configured min threshold for (sensor, parameter, aggregate), or default.

    Resolution preference: sensor(+param+agg) → sensor-only → param+agg → param-only → global (None) → default.
    """
                                                                                  
    rules = session.scalars(
        select(models.QCRule).where(
            models.QCRule.enabled == True,              
            models.QCRule.check_code == CHECK_CODE,
        )
    ).all()

    best = None
    best_score = -1
    for r in rules:
        score = 0
                                                
        if getattr(r, "sensor_id", None) is not None and sensor_id is not None and r.sensor_id == sensor_id:
            score += 4
        elif getattr(r, "sensor_id", None) is None:
            score += 1
        else:
                             
            continue
        if r.parameter_id is not None and parameter_id is not None and r.parameter_id == parameter_id:
            score += 2
        elif r.parameter_id is None:
            score += 1
        else:
                                
            continue

        eff_agg = (aggregate_code or '1h')
        if r.aggregate_code is not None and r.aggregate_code == eff_agg:
            score += 2
        elif r.aggregate_code is None:
            score += 1
        else:
                                
            continue

        if score > best_score:
            best_score = score
            best = r

    if best and best.params and isinstance(best.params, dict):
        try:
            v = float(best.params.get("min", DEFAULT_MIN_VALUE))
            return v
        except Exception:
            return DEFAULT_MIN_VALUE
    return DEFAULT_MIN_VALUE


def evaluate(session, value: Optional[float], sensor_id: Optional[int], parameter_id: Optional[int], aggregate_code: Optional[str] = None) -> Tuple[bool, float]:
    """Evaluate min-value QC for the given value, returning (passed, threshold)."""
    threshold = resolve_min_threshold(session, sensor_id, parameter_id, aggregate_code)
    try:
        v = float(value) if value is not None else None
    except Exception:
        v = None
    if v is None:
        return False, threshold
    return (v >= threshold), threshold


def resolve_min_threshold_meta(session, sensor_id: Optional[int], parameter_id: Optional[int], aggregate_code: Optional[str] = None) -> tuple[float, str, Optional[models.QCRule]]:
    """Like resolve_min_threshold but returns (threshold, source, rule). Source is one of 'sensor','parameter','global','default'."""
    rules = session.scalars(
        select(models.QCRule).where(
            models.QCRule.enabled == True,              
            models.QCRule.check_code == CHECK_CODE,
        )
    ).all()

    best = None
    best_score = -1
    for r in rules:
        score = 0
        if getattr(r, "sensor_id", None) is not None and sensor_id is not None and r.sensor_id == sensor_id:
            score += 4
        elif getattr(r, "sensor_id", None) is None:
            score += 1
        else:
            continue
        if r.parameter_id is not None and parameter_id is not None and r.parameter_id == parameter_id:
            score += 2
        elif r.parameter_id is None:
            score += 1
        else:
            continue
        eff_agg = (aggregate_code or '1h')
        if r.aggregate_code is not None and r.aggregate_code == eff_agg:
            score += 2
        elif r.aggregate_code is None:
            score += 1
        else:
            continue
        if score > best_score:
            best_score = score
            best = r

    source = "default"
    if best is not None:
        if getattr(best, "sensor_id", None) is not None:
            source = "sensor"
        elif getattr(best, "parameter_id", None) is not None:
            source = "parameter"
        else:
            source = "global"
    threshold = DEFAULT_MIN_VALUE
    if best and best.params and isinstance(best.params, dict):
        try:
            threshold = float(best.params.get("min", DEFAULT_MIN_VALUE))
        except Exception:
            threshold = DEFAULT_MIN_VALUE
    return threshold, source, best


def evaluate_meta(session, value: Optional[float], sensor_id: Optional[int], parameter_id: Optional[int], aggregate_code: Optional[str] = None) -> tuple[bool, float, dict]:
    """Evaluate and return (passed, threshold, meta). Meta includes source and params snapshot."""
    thr, src, rule = resolve_min_threshold_meta(session, sensor_id, parameter_id, aggregate_code)
    try:
        v = float(value) if value is not None else None
    except Exception:
        v = None
    passed = (v is not None) and (v >= thr)
    meta = {"source": src, "params": {"min": thr}, "rule_id": getattr(rule, "qc_rule_id", None)}
    return passed, thr, meta
