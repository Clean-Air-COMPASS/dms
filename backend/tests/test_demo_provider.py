from datetime import datetime, timedelta, timezone

import pytest

import models
from services.external_sources import derive_external_source_state, source_requires_credential
from sources.demo.fixture import SAMPLES
from sources.demo.importer import aligned_slot, values_for_slot


def test_credential_free_sources_are_ready_but_protected_providers_require_keys():
    for code in ("demo", "openaq", "purpleair", "airgradient"):
        source = models.ExternalAPI(provider_code=code, name=code, enabled=True, params={})
        state = derive_external_source_state(source, {})
        assert state.is_configured is (code in {"demo", "airgradient"})
        assert state.is_runnable is (code in {"demo", "airgradient"})
        assert source_requires_credential(source) is (code not in {"demo", "airgradient"})


def test_clock_alignment_and_fixture_loop_are_independent_of_startup():
    now = datetime(2026, 9, 6, 12, 7, 59, tzinfo=timezone.utc)
    slot = aligned_slot(now)
    assert slot == now.replace(minute=5, second=0)
    assert aligned_slot(now.astimezone(timezone(timedelta(hours=8)))) == slot
    values = [values_for_slot(slot + timedelta(minutes=5 * i)) for i in range(len(SAMPLES))]
    assert len(set(values)) == len(SAMPLES)
    assert values_for_slot(slot + timedelta(minutes=5 * len(SAMPLES))) == values[0]
    with pytest.raises(ValueError, match="timezone-aware"):
        aligned_slot(now.replace(tzinfo=None))


def test_demo_process_loads_installed_qc_plugins(monkeypatch):
    import sys
    from sources.demo import importer
    calls = []
    monkeypatch.setattr(importer.discovery, "load_plugins", lambda: calls.append("loaded"))
    monkeypatch.setattr(importer, "run_import", lambda: {})
    monkeypatch.setattr(sys, "argv", ["demo-importer"])
    importer.main()
    assert calls == ["loaded"]
