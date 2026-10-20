"""Pure minimum-value evaluation.

Threshold selection belongs to :mod:`qaqc.policy`; this module deliberately
contains no database access or fallback threshold.
"""

from __future__ import annotations

from typing import Any


CHECK_CODE = "min_value"


def evaluate(value: Any, threshold: float) -> bool | None:
    """Return pass/fail, or ``None`` when the measurement is not numeric."""
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    return numeric_value >= float(threshold)
