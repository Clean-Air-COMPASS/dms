"""Acceptance coverage for the shipped deployment-installed QC plugin."""

from __future__ import annotations

from importlib.metadata import distribution

import pytest

from qaqc import discovery, registry
from qaqc.admin_policy import get_check_metadata
from qaqc.plugins import BUILT_IN_PLUGINS


@pytest.fixture()
def preserved_plugin_registry():
    previous = tuple(registry.all_registrations().values())
    try:
        yield
    finally:
        registry.replace_all(previous)


def _built_in_registrations():
    return [
        registry.validate_plugin(plugin, origin="built_in")
        for plugin in BUILT_IN_PLUGINS
    ]


def test_real_max_value_entry_point_is_the_only_registration_path(
    preserved_plugin_registry,
):
    registry.replace_all(_built_in_registrations())
    assert {plugin.name for plugin in BUILT_IN_PLUGINS} == {
        "min_value",
        "baseline_drift",
    }
    assert registry.get_registration("max_value") is None
    unavailable_metadata = next(
        item for item in get_check_metadata() if item["check_code"] == "max_value"
    )
    assert unavailable_metadata["available"] is False
    assert unavailable_metadata["unit_settings"] == ["max"]
    assert unavailable_metadata["overview"]["order"] == 20

    installed_distribution = distribution("compassaq-max-value")
    maximum_entry_points = [
        entry_point
        for entry_point in installed_distribution.entry_points
        if entry_point.group == discovery.ENTRY_POINT_GROUP
        and entry_point.name == "max_value"
    ]
    assert len(maximum_entry_points) == 1
    assert maximum_entry_points[0].value == "compassaq_max_value.plugin:plugin"

    first_report = discovery.load_plugins()
    registration = registry.get_registration("max_value")
    assert registration is not None
    assert registration.metadata.origin == "entry_point"
    assert registration.metadata.entrypoint == (
        "max_value=compassaq_max_value.plugin:plugin"
    )
    assert registration.metadata.distribution == "compassaq-max-value"
    assert {item["name"] for item in first_report["entry_points"]} >= {
        "max_value"
    }

    second_report = discovery.load_plugins()
    reloaded = registry.get_registration("max_value")
    assert reloaded is not None
    assert reloaded.metadata == registration.metadata
    assert {item["name"] for item in second_report["entry_points"]} >= {
        "max_value"
    }

    check_metadata = {
        item["check_code"]: item for item in get_check_metadata()
    }
    maximum_metadata = check_metadata["max_value"]
    assert maximum_metadata["available"] is True
    assert maximum_metadata["origin"] == "entry_point"
    assert maximum_metadata["plugin_version"] == "1.0.0"
    assert maximum_metadata["settings"][0]["setting_code"] == "max"
    assert maximum_metadata["overview"] == {
        "visible": True,
        "label": "Maximum",
        "order": 20,
        "summary_setting": "max",
    }
