from __future__ import annotations

import services.system_settings as system_settings


def test_detect_initial_system_timezone_prefers_environment(monkeypatch):
    monkeypatch.setenv("SYSTEM_TIMEZONE", "America/Los_Angeles")
    monkeypatch.setattr(system_settings, "get_localzone_name", lambda: "Asia/Manila")

    assert system_settings.detect_initial_system_timezone() == "America/Los_Angeles"


def test_detect_initial_system_timezone_uses_detected_local_timezone(monkeypatch):
    monkeypatch.delenv("SYSTEM_TIMEZONE", raising=False)
    monkeypatch.setattr(system_settings, "get_localzone_name", lambda: "Asia/Manila")

    assert system_settings.detect_initial_system_timezone() == "Asia/Manila"


def test_detect_initial_system_timezone_falls_back_to_utc_when_detection_fails(monkeypatch):
    monkeypatch.delenv("SYSTEM_TIMEZONE", raising=False)

    def _raise():
        raise RuntimeError("timezone unavailable")

    monkeypatch.setattr(system_settings, "get_localzone_name", _raise)

    assert system_settings.detect_initial_system_timezone() == "UTC"


def test_invalid_environment_timezone_does_not_override_detection(monkeypatch):
    monkeypatch.setenv("SYSTEM_TIMEZONE", "Pacific Standard Time")
    monkeypatch.setattr(system_settings, "get_localzone_name", lambda: "America/New_York")

    assert system_settings.detect_initial_system_timezone() == "America/New_York"
