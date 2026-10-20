"""Small helpers for authors of deployment-installed QC plugins.

Plugins evaluate the effective policies supplied by CompassAQ. They must not
query ``QCRule`` or reproduce inheritance, unit conversion, or failure-action
logic.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from .types import QCDecision


try:
    import pandas as pd
except Exception:
    pd = None


LOGGER = logging.getLogger(__name__)


def effective_policy_for_record(context: dict, record_index: int) -> Any | None:
    """Return the resolver-owned policy aligned with one plugin input record."""
    policies = context.get("effective_policies")
    if not isinstance(policies, list) or record_index >= len(policies):
        return None
    return policies[record_index]


def indeterminate_decision(reason_code: str, message: str) -> QCDecision:
    """Build an explicit result when a plugin cannot evaluate a record."""
    return QCDecision(
        is_valid=None,
        flags=[],
        severity="warn",
        message=message,
        patch={"reason_code": reason_code},
    )


def records_to_dataframe(records: Iterable[Any]):
    """Convert QCRecord objects to a DataFrame when pandas is available."""
    record_list = list(records or [])
    rows = [
        {
            "sensor_id": getattr(record, "sensor_id", None),
            "parameter_id": getattr(record, "parameter_id", None),
            "value": getattr(record, "value", None),
            "unit_id": getattr(record, "unit_id", None),
            "observed_at": getattr(record, "observed_at", None),
        }
        for record in record_list
    ]
    if pd is None:
        return rows
    try:
        return pd.DataFrame.from_records(rows)
    except Exception:
        LOGGER.exception("Failed to convert QC records to a DataFrame")
        return rows


def ensure_numeric(series_or_values, errors: str = "coerce"):
    """Convert values to numbers, using pandas when it is installed."""
    if pd is None:
        converted = []
        for raw_value in series_or_values:
            try:
                converted.append(float(raw_value))
            except (TypeError, ValueError):
                converted.append(None)
        return converted
    return pd.to_numeric(series_or_values, errors=errors)
