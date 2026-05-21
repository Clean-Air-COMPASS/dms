from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import List, Optional

from sqlalchemy import select

import models
from qaqc.plugin import QCPlugin
from qaqc.registry import register
from qaqc.types import QCDecision, QCRecord


CHECK_CODE = "baseline_drift"

DEFAULT_LOOKBACK_HOURS = 72
DEFAULT_MIN_SAMPLES = 24
DEFAULT_BASELINE_QUANTILE = 0.1
DEFAULT_MAX_DRIFT_PER_DAY = 1.0
DEFAULT_DIRECTION = "both"


def _coerce_datetime(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _quantile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    if q <= 0:
        return min(values)
    if q >= 1:
        return max(values)
    vals = sorted(values)
    pos = (len(vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    frac = pos - lo
    return vals[lo] + (vals[hi] - vals[lo]) * frac


def _to_int(value: object, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_float(value: object, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_params(raw: object) -> tuple[Optional[dict], Optional[str]]:
    params = raw if isinstance(raw, dict) else {}
    lookback_hours = _to_int(params.get("lookback_hours", DEFAULT_LOOKBACK_HOURS), DEFAULT_LOOKBACK_HOURS)
    min_samples = _to_int(params.get("min_samples", DEFAULT_MIN_SAMPLES), DEFAULT_MIN_SAMPLES)
    baseline_quantile = _to_float(params.get("baseline_quantile", DEFAULT_BASELINE_QUANTILE), DEFAULT_BASELINE_QUANTILE)
    max_drift_per_day = _to_float(params.get("max_drift_per_day", DEFAULT_MAX_DRIFT_PER_DAY), DEFAULT_MAX_DRIFT_PER_DAY)
    direction = str(params.get("direction", DEFAULT_DIRECTION) or DEFAULT_DIRECTION).lower()
    if lookback_hours <= 0:
        return None, "lookback_hours must be positive"
    if min_samples <= 0:
        return None, "min_samples must be positive"
    if baseline_quantile < 0 or baseline_quantile > 1:
        return None, "baseline_quantile must be between 0 and 1"
    if max_drift_per_day < 0:
        return None, "max_drift_per_day must be non-negative"
    if direction not in ("up", "down", "both"):
        direction = "both"
    return {
        "lookback_hours": lookback_hours,
        "min_samples": min_samples,
        "baseline_quantile": baseline_quantile,
        "max_drift_per_day": max_drift_per_day,
        "direction": direction,
    }, None


def _resolve_rule(session, sensor_id: Optional[int], parameter_id: Optional[int], aggregate_code: Optional[str]):
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
        eff_agg = (aggregate_code or "1h")
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
    return best, source


def _evaluate_record(session, record: QCRecord, aggregate_code: Optional[str]) -> QCDecision:
    if record.sensor_id is None:
        return QCDecision(is_valid=None, flags=[], severity="info", message="baseline_drift requires sensor_id")
    observed_at = _coerce_datetime(record.observed_at)
    if observed_at is None:
        return QCDecision(is_valid=None, flags=[], severity="info", message="baseline_drift requires observed_at")

    rule, source = _resolve_rule(session, record.sensor_id, record.parameter_id, aggregate_code)
    if rule is None:
        return QCDecision(is_valid=None, flags=[], severity="info", message="no baseline_drift rule configured")

    params, err = _normalize_params(rule.params)
    if err:
        return QCDecision(is_valid=None, flags=[], severity="warn", message=f"invalid baseline_drift params: {err}")
    if params is None:
        return QCDecision(is_valid=None, flags=[], severity="warn", message="invalid baseline_drift params")

    lookback_hours = params["lookback_hours"]
    min_samples = params["min_samples"]
    baseline_quantile = params["baseline_quantile"]
    max_drift_per_day = params["max_drift_per_day"]
    direction = params["direction"]

    start_time = observed_at - timedelta(hours=lookback_hours)
    if start_time >= observed_at:
        return QCDecision(is_valid=None, flags=[], severity="info", message="baseline_drift window is invalid")

    rows = session.execute(
        select(models.Measurement.value, models.Measurement.observed_at).where(
            models.Measurement.sensor_id == record.sensor_id,
            models.Measurement.observed_at.is_not(None),
            models.Measurement.observed_at >= start_time,
            models.Measurement.observed_at <= observed_at,
        ).order_by(models.Measurement.observed_at)
    ).all()

    if not rows:
        return QCDecision(is_valid=None, flags=[], severity="info", message="no history for baseline_drift")

    mid_time = start_time + (observed_at - start_time) / 2
    all_values: List[float] = []
    older_values: List[float] = []
    recent_values: List[float] = []
    for v, ts in rows:
        try:
            val = float(v)
        except Exception:
            continue
        ts_dt = _coerce_datetime(ts)
        if ts_dt is None:
            continue
        all_values.append(val)
        if ts_dt < mid_time:
            older_values.append(val)
        else:
            recent_values.append(val)

    if len(all_values) < min_samples:
        return QCDecision(is_valid=None, flags=[], severity="info", message="insufficient samples for baseline_drift")
    if not older_values or not recent_values:
        return QCDecision(is_valid=None, flags=[], severity="info", message="insufficient split samples for baseline_drift")

    baseline_old = _quantile(older_values, baseline_quantile)
    baseline_recent = _quantile(recent_values, baseline_quantile)
    if baseline_old is None or baseline_recent is None:
        return QCDecision(is_valid=None, flags=[], severity="info", message="baseline quantile unavailable")

    elapsed_days = (observed_at - start_time).total_seconds() / 86400.0
    if elapsed_days <= 0:
        return QCDecision(is_valid=None, flags=[], severity="info", message="baseline_drift elapsed window invalid")

    drift_per_day = (baseline_recent - baseline_old) / elapsed_days

    fail = False
    if direction == "up":
        fail = drift_per_day > max_drift_per_day
    elif direction == "down":
        fail = drift_per_day < -max_drift_per_day
    else:
        fail = abs(drift_per_day) > max_drift_per_day

    patch = {
        "source": source,
        "params": params,
        "rule_id": getattr(rule, "qc_rule_id", None),
        "baseline_old": baseline_old,
        "baseline_recent": baseline_recent,
        "drift_per_day": drift_per_day,
        "samples": len(all_values),
        "older_samples": len(older_values),
        "recent_samples": len(recent_values),
    }

    if fail:
        direction_label = "upward" if drift_per_day > 0 else "downward"
        msg = (
            f"{direction_label} drift {drift_per_day:.6g}/day exceeds "
            f"limit {max_drift_per_day:.6g}/day"
        )
        return QCDecision(
            is_valid=False,
            flags=["baseline_drift"],
            severity="warn",
            message=msg,
            patch=patch,
            plugin_error=None,
        )

    return QCDecision(
        is_valid=True,
        flags=[],
        severity="info",
        message="",
        patch=patch,
        plugin_error=None,
    )


class BaselineDriftPlugin(QCPlugin):
    name = CHECK_CODE
    version = "1.0.0"
    description = "Detects slow upward or downward baseline drift"
    display_name = "Baseline Drift"
    long_description = (
        "Detects slow baseline (zero) drift by comparing low-end quantiles across "
        "the lookback window for a sensor."
    )
    qc_api = 1
    param_schema = {
        "lookback_hours": {
            "type": "integer",
            "label": "Lookback hours",
            "required": True,
            "help": "Number of hours to scan for baseline drift",
        },
        "min_samples": {
            "type": "integer",
            "label": "Minimum samples",
            "required": True,
            "help": "Minimum historical samples required to evaluate drift",
        },
        "baseline_quantile": {
            "type": "number",
            "label": "Baseline quantile",
            "required": True,
            "help": "Quantile used to estimate the baseline (e.g. 0.1)",
        },
        "max_drift_per_day": {
            "type": "number",
            "label": "Max drift per day",
            "required": True,
            "help": "Maximum acceptable baseline drift rate per day",
        },
        "direction": {
            "type": "string",
            "label": "Direction",
            "required": False,
            "help": "Drift direction: up, down, or both",
        },
    }

    def apply(self, records: List[QCRecord], context: dict) -> List[QCDecision]:
        session = context.get("session")
        aggregate = context.get("aggregate_code")
        if session is None:
            return [
                QCDecision(is_valid=None, flags=[], severity="warn", message="baseline_drift requires db session")
                for _ in records
            ]
        out: List[QCDecision] = []
        for r in records:
            out.append(_evaluate_record(session, r, aggregate))
        return out


plugin = BaselineDriftPlugin()
register(plugin)
