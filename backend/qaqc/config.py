from __future__ import annotations

from typing import Dict, List


def default_config() -> Dict[str, List[str]]:
    """Return the default plugin order per stage.

    Ingest pipeline now runs min_value and max_value checks (order: min then max).
    Post-ingest left empty for future aggregation or anomaly checks.
    """
    return {
        "ingest": ["min_value", "max_value"],
        "post_ingest": [],
    }
