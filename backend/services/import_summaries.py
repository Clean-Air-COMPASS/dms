"""Provider-neutral JobRun summary helpers for external-source importers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def new_import_summary() -> dict[str, Any]:
    """Return the common counters every importer reports.

    The flat names are intentionally explicit so administrators and maintainers
    can compare providers without interpreting provider-specific nested data.
    Importers may add provider-specific fields when they carry useful context.
    """
    return {
        "devices_processed": 0,
        "devices_created": 0,
        "sensors_processed": 0,
        "sensors_created": 0,
        "measurements_received": 0,
        "measurements_inserted": 0,
        "measurements_updated": 0,
        "measurements_skipped": 0,
    }


def merge_qc_counts(
    summary: dict[str, Any],
    qc_counts: dict[str, int] | None,
) -> None:
    """Add already-computed ingest QC outcomes to an importer summary.

    QC remains optional because duplicate/skipped measurements do not run the
    ingest checks. When present, ``evaluated`` counts measurements submitted to
    at least one configured check. Each evaluated measurement is then counted
    once as passed, flagged, or indeterminate. Flagged measurements are retained
    with ``is_valid=False``; the current ingest pipeline does not reject them.
    """
    if not qc_counts or qc_counts.get("evaluated", 0) <= 0:
        return

    summary_qc = summary.setdefault(
        "qc",
        {
            "evaluated": 0,
            "passed": 0,
            "flagged": 0,
            "indeterminate": 0,
        },
    )
    for counter_name in ("evaluated", "passed", "flagged", "indeterminate"):
        summary_qc[counter_name] = (
            int(summary_qc.get(counter_name, 0))
            + int(qc_counts.get(counter_name, 0))
        )


def write_import_summary(summary: dict[str, Any], summary_json: str | None) -> None:
    """Write an importer summary when invoked by the JobRun subprocess path."""
    if not summary_json:
        return
    output_path = Path(summary_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
