from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACT_PATH = (
    REPOSITORY_ROOT / "artifacts" / "qc-phase3" / "backend-acceptance.json"
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "qc_acceptance(id, source, parameter, qc_layer, expected): "
        "Phase 3 operational QC acceptance scenario",
    )
    config._qc_acceptance_results = []


@pytest.fixture()
def acceptance_evidence(request):
    """Collect small, non-sensitive identifiers for the machine report."""
    evidence: dict = {}
    request.node._qc_acceptance_evidence = evidence
    return evidence


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    marker = item.get_closest_marker("qc_acceptance")
    if marker is None:
        return
    result = {
        "scenario_id": marker.kwargs["id"],
        "source": marker.kwargs["source"],
        "parameter": marker.kwargs["parameter"],
        "qc_layer": marker.kwargs["qc_layer"],
        "expected": marker.kwargs["expected"],
        "result": report.outcome,
        "test_node_id": item.nodeid,
        "duration_seconds": round(report.duration, 6),
        "evidence": getattr(item, "_qc_acceptance_evidence", {}),
    }
    if report.failed:
        result["failure"] = str(report.longrepr)
    item.config._qc_acceptance_results.append(result)


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        # The production backend image intentionally does not install Git.
        return None
    return completed.stdout.strip() or None


def pytest_sessionfinish(session, exitstatus):
    results = session.config._qc_acceptance_results
    if not results:
        return
    artifact_path = Path(
        os.environ.get("QC_ACCEPTANCE_ARTIFACT", DEFAULT_ARTIFACT_PATH)
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "exit_status": exitstatus,
        "summary": {
            "total": len(results),
            "passed": sum(result["result"] == "passed" for result in results),
            "failed": sum(result["result"] == "failed" for result in results),
            "skipped": sum(result["result"] == "skipped" for result in results),
        },
        "scenarios": sorted(results, key=lambda result: result["scenario_id"]),
    }
    artifact_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@pytest.fixture()
def acceptance_session_factory(tmp_path):
    """Use PostgreSQL when configured, with a SQLite fallback for local focus runs."""
    postgres_url = os.environ.get("COMPASSAQ_POSTGRES_TEST_URL")
    if postgres_url:
        from postgresql_test_support import temporary_postgres_database, upgrade

        with temporary_postgres_database("qc_acceptance") as (database_url, engine):
            upgrade(database_url)
            yield sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                future=True,
            )
        return

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'qc-acceptance.sqlite'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    models.Base.metadata.create_all(bind=engine)
    try:
        yield sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            future=True,
        )
    finally:
        engine.dispose()
