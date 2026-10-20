from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import List, Optional

from sqlalchemy import select

import models
from qaqc.plugin import QCPlugin
from qaqc.types import QCDecision, QCRecord


CHECK_CODE = "baseline_drift"


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


def _evaluate_record(session, record: QCRecord, params: dict) -> QCDecision:
    if record.sensor_id is None:
        return QCDecision(is_valid=None, flags=[], severity="info", message="baseline_drift requires sensor_id")
    observed_at = _coerce_datetime(record.observed_at)
    if observed_at is None:
        return QCDecision(is_valid=None, flags=[], severity="info", message="baseline_drift requires observed_at")

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
            models.Measurement.is_valid.is_(True),
            models.Measurement.observed_at.is_not(None),
            models.Measurement.observed_at >= start_time,
            # (sensor_id, observed_at) uniquely identifies an observation.
            # Exclude the candidate on insert and update, whether flushed or not.
            models.Measurement.observed_at < observed_at,
        ).order_by(models.Measurement.observed_at)
    ).all()

    if not rows:
        return QCDecision(
            is_valid=None,
            flags=[],
            severity="info",
            message="baseline_drift is waiting for historical samples",
            patch={
                "reason_code": "insufficient_history",
                "samples": 0,
                "required_samples": min_samples,
            },
        )

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
        return QCDecision(
            is_valid=None,
            flags=[],
            severity="info",
            message="baseline_drift is waiting for enough historical samples",
            patch={
                "reason_code": "insufficient_history",
                "samples": len(all_values),
                "required_samples": min_samples,
                "older_samples": len(older_values),
                "recent_samples": len(recent_values),
            },
        )

    # A quantile based on only one or two points in either half is not a
    # defensible baseline estimate. ``min_samples`` applies to the full window,
    # so require half of it (rounded up) in each half as well. This also stops a
    # newly created high-frequency sensor from appearing evaluable before it
    # has covered both halves of the lookback window.
    minimum_split_samples = math.ceil(min_samples / 2)
    if (
        len(older_values) < minimum_split_samples
        or len(recent_values) < minimum_split_samples
    ):
        return QCDecision(
            is_valid=None,
            flags=[],
            severity="info",
            message="baseline_drift is waiting for enough samples in both halves of the lookback",
            patch={
                "reason_code": "insufficient_history",
                "samples": len(all_values),
                "required_samples": min_samples,
                "older_samples": len(older_values),
                "recent_samples": len(recent_values),
                "required_samples_per_half": minimum_split_samples,
            },
        )

    baseline_old = _quantile(older_values, baseline_quantile)
    baseline_recent = _quantile(recent_values, baseline_quantile)
    if baseline_old is None or baseline_recent is None:
        return QCDecision(is_valid=None, flags=[], severity="info", message="baseline quantile unavailable")

    elapsed_days = (observed_at - start_time).total_seconds() / 86400.0
    if elapsed_days <= 0:
        return QCDecision(is_valid=None, flags=[], severity="info", message="baseline_drift elapsed window invalid")

    # Normalize by the full lookback, not the separation between half-windows.
    # This is a screening indicator, not an estimate of physical slope.
    baseline_shift_indicator = (baseline_recent - baseline_old) / elapsed_days

    fail = False
    if direction == "up":
        fail = baseline_shift_indicator > max_drift_per_day
    elif direction == "down":
        fail = baseline_shift_indicator < -max_drift_per_day
    else:
        fail = abs(baseline_shift_indicator) > max_drift_per_day

    patch = {
        "baseline_old": baseline_old,
        "baseline_recent": baseline_recent,
        # Retain the persisted/API key for compatibility with existing results.
        "drift_per_day": baseline_shift_indicator,
        "samples": len(all_values),
        "older_samples": len(older_values),
        "recent_samples": len(recent_values),
    }

    if fail:
        direction_label = "upward" if baseline_shift_indicator > 0 else "downward"
        msg = (
            f"{direction_label} baseline shift indicator {baseline_shift_indicator:.6g}/day "
            f"(normalized by full lookback) exceeds screening threshold {max_drift_per_day:.6g}/day"
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
    version = "1.1.0"
    description = "Screens for changes in a sensor's low-end baseline"
    display_name = "Baseline Drift"
    long_description = (
        "Compares low-end quantiles of valid history in two half-windows and "
        "normalizes their difference by the full lookback in days. "
        "This baseline shift indicator is not a validated physical slope estimator."
    )
    qc_api = 1
    required_access = "db-read"
    unit_settings = ("max_drift_per_day",)
    overview = {
        "visible": True,
        "label": "Baseline Drift",
        "order": 30,
    }
    param_schema = {
        "lookback_hours": {
            "type": "integer",
            "label": "Lookback hours",
            "required": True,
            "help": "Number of hours to scan for baseline drift",
            "minimum": 1,
        },
        "min_samples": {
            "type": "integer",
            "label": "Minimum samples",
            "required": True,
            "help": "Minimum valid historical samples, excluding the candidate; each half requires half this count rounded up",
            "minimum": 1,
        },
        "baseline_quantile": {
            "type": "number",
            "label": "Baseline quantile",
            "required": True,
            "help": "Quantile used to estimate the baseline (e.g. 0.1)",
            "minimum": 0,
            "maximum": 1,
        },
        "max_drift_per_day": {
            "type": "number",
            "label": "Maximum baseline shift indicator (per day)",
            "required": True,
            "help": "Low-quantile shift divided by the full lookback in days; a screening threshold, not a physical slope limit",
            "minimum": 0,
        },
        "direction": {
            "type": "string",
            "label": "Direction",
            "required": True,
            "help": "Drift direction: up, down, or both",
            "choices": ["up", "down", "both"],
        },
    }

    def apply(self, records: List[QCRecord], context: dict) -> List[QCDecision]:
        session = context.get("session")
        policies = context.get("effective_policies") or []
        if session is None:
            return [
                QCDecision(is_valid=None, flags=[], severity="warn", message="baseline_drift requires db session")
                for _ in records
            ]
        out: List[QCDecision] = []
        for index, record in enumerate(records):
            policy = policies[index] if index < len(policies) else None
            if policy is None:
                out.append(
                    QCDecision(
                        is_valid=None,
                        flags=[],
                        severity="warn",
                        message="baseline_drift requires a resolved policy",
                        patch={"reason_code": "missing_required_setting"},
                    )
                )
                continue
            out.append(_evaluate_record(session, record, policy.evaluation_settings))
        return out


plugin = BaselineDriftPlugin()
