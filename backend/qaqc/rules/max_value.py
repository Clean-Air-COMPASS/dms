from __future__ import annotations

from typing import Optional, Tuple
from sqlalchemy import select

import models


DEFAULT_MAX_VALUE = 1_000_000.0
CHECK_CODE = "max_value"


def resolve_max_threshold(session, sensor_id: Optional[int], parameter_id: Optional[int], aggregate_code: Optional[str] = None) -> float:
    """Return the configured max threshold for (sensor, parameter, aggregate), or default.

    Resolution preference: sensor(+param+agg) → sensor-only → param+agg → param-only → global (None) → default.
    Mirrors min_value.resolve_min_threshold.
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
            v = float(best.params.get("max", DEFAULT_MAX_VALUE))
            return v
        except Exception:
            return DEFAULT_MAX_VALUE
    return DEFAULT_MAX_VALUE


def evaluate(session, value: Optional[float], sensor_id: Optional[int], parameter_id: Optional[int], aggregate_code: Optional[str] = None) -> Tuple[bool, float]:
    """Evaluate max-value QC for the given value, returning (passed, threshold)."""
    threshold = resolve_max_threshold(session, sensor_id, parameter_id, aggregate_code)
    try:
        v = float(value) if value is not None else None
    except Exception:
        v = None
    if v is None:
        return False, threshold
    return (v <= threshold), threshold


def resolve_max_threshold_meta(session, sensor_id: Optional[int], parameter_id: Optional[int], aggregate_code: Optional[str] = None) -> tuple[float, str, Optional[models.QCRule]]:
    """Like resolve_max_threshold but returns (threshold, source, rule). Source: 'sensor'|'parameter'|'global'|'default'."""
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
    threshold = DEFAULT_MAX_VALUE
    if best and best.params and isinstance(best.params, dict):
        try:
            threshold = float(best.params.get("max", DEFAULT_MAX_VALUE))
        except Exception:
            threshold = DEFAULT_MAX_VALUE
    return threshold, source, best


def evaluate_meta(session, value: Optional[float], sensor_id: Optional[int], parameter_id: Optional[int], aggregate_code: Optional[str] = None) -> tuple[bool, float, dict]:
    thr, src, rule = resolve_max_threshold_meta(session, sensor_id, parameter_id, aggregate_code)
    try:
        v = float(value) if value is not None else None
    except Exception:
        v = None
    passed = (v is not None) and (v <= thr)
    meta = {"source": src, "params": {"max": thr}, "rule_id": getattr(rule, "qc_rule_id", None)}
    return passed, thr, meta
