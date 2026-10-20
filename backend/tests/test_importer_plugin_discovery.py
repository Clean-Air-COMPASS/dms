from __future__ import annotations

import sys

from sources.airgradient import importer as airgradient_importer
from sources.openaq import importer as openaq_importer
from sources.purpleair import importer as purpleair_importer


def _empty_report():
    return {
        "built_in": [],
        "entry_points": [],
        "rejected": [],
        "failed": [],
        "db_write_plugins_allowed": False,
    }


def test_openaq_process_loads_installed_qc_plugins(monkeypatch):
    calls = []
    monkeypatch.setattr(
        openaq_importer.discovery,
        "load_plugins",
        lambda: calls.append("loaded") or _empty_report(),
    )
    monkeypatch.setattr(openaq_importer, "sync_catalogs_from_sensors", lambda: None)
    monkeypatch.setattr(sys, "argv", ["openaq-importer", "--sync-catalogs"])

    openaq_importer.main()

    assert calls == ["loaded"]


def test_purpleair_process_loads_installed_qc_plugins(monkeypatch):
    calls = []
    monkeypatch.setattr(
        purpleair_importer.discovery,
        "load_plugins",
        lambda: calls.append("loaded") or _empty_report(),
    )
    monkeypatch.setattr(purpleair_importer, "run_import", lambda **kwargs: {})
    monkeypatch.setattr(sys, "argv", ["purpleair-importer"])

    purpleair_importer.main()

    assert calls == ["loaded"]


def test_airgradient_process_loads_installed_qc_plugins(monkeypatch):
    calls = []
    monkeypatch.setattr(
        airgradient_importer.discovery,
        "load_plugins",
        lambda: calls.append("loaded") or _empty_report(),
    )
    monkeypatch.setattr(
        airgradient_importer,
        "run_import",
        lambda **kwargs: {"acquisition_outcome": "success"},
    )
    monkeypatch.setattr(sys, "argv", ["airgradient-importer"])

    airgradient_importer.main()

    assert calls == ["loaded"]
