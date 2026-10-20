"""Deterministic discovery for deployment-installed QC plugins.

CompassAQ built-ins are code-owned. Third-party checks must be installed as
Python package entry points in ``aq_platform.qaqc_plugins``. The web API never
writes or executes uploaded Python source.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from importlib.metadata import EntryPoint, entry_points
import logging
import os
from threading import RLock
from typing import Any

from . import registry
from .registry import PluginRegistrationError, RegisteredPlugin


LOGGER = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "aq_platform.qaqc_plugins"
ALLOW_DB_WRITE_ENV = "QC_ALLOW_DB_WRITE_PLUGINS"

_DISCOVERY_LOCK = RLock()
_LAST_REPORT: dict[str, Any] = {
    "built_in": [],
    "entry_points": [],
    "rejected": [],
    "failed": [],
}


def _instantiate(loaded_object: Any) -> Any:
    """Return a plugin instance from an instance, class, or zero-arg factory."""
    if isinstance(loaded_object, type):
        return loaded_object()
    if hasattr(loaded_object, "apply"):
        return loaded_object
    if callable(loaded_object):
        return loaded_object()
    raise PluginRegistrationError(
        "invalid_plugin_contract",
        "Entry point must expose a plugin instance, class, or zero-argument factory",
    )


def _installed_entry_points() -> list[EntryPoint]:
    try:
        discovered = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        discovered = entry_points().select(group=ENTRY_POINT_GROUP)
    return sorted(discovered, key=lambda entry_point: entry_point.name)


def _distribution_name(entry_point: EntryPoint) -> str | None:
    distribution = getattr(entry_point, "dist", None)
    if distribution is None:
        return None
    return getattr(distribution, "name", None) or str(distribution)


def _entry_point_label(entry_point: EntryPoint) -> str:
    return f"{entry_point.name}={entry_point.value}"


def _db_write_is_approved(approve_write: bool | None) -> bool:
    if approve_write is not None:
        return approve_write
    return os.environ.get(ALLOW_DB_WRITE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _report_item(registration: RegisteredPlugin) -> dict[str, Any]:
    return asdict(registration.metadata)


def load_plugins(approve_write: bool | None = None) -> dict[str, Any]:
    """Validate all installed plugins and atomically publish the usable set.

    A failed or rejected third-party plugin cannot remove the built-ins or
    partially replace the active registry. Duplicate check codes are rejected;
    discovery order never decides which implementation wins.
    """
    from .plugins import BUILT_IN_PLUGINS

    allow_db_write = _db_write_is_approved(approve_write)
    with _DISCOVERY_LOCK:
        report: dict[str, Any] = {
            "built_in": [],
            "entry_points": [],
            "rejected": [],
            "failed": [],
            "db_write_plugins_allowed": allow_db_write,
        }
        registrations: list[RegisteredPlugin] = []
        names: set[str] = set()

        # Invalid built-in metadata is a deployment error. Do not publish a
        # partial registry if CompassAQ's own checks violate the contract.
        for plugin in BUILT_IN_PLUGINS:
            registration = registry.validate_plugin(plugin, origin="built_in")
            if registration.metadata.name in names:
                raise PluginRegistrationError(
                    "duplicate_plugin",
                    f"Built-in plugin '{registration.metadata.name}' is duplicated",
                )
            registrations.append(registration)
            names.add(registration.metadata.name)
            report["built_in"].append(_report_item(registration))

        try:
            installed_entry_points = _installed_entry_points()
        except Exception as error:
            LOGGER.exception("Failed to enumerate QC plugin entry points")
            installed_entry_points = []
            report["failed"].append(
                {
                    "reason_code": "entry_point_discovery_failed",
                    "message": str(error),
                    "entrypoint": None,
                }
            )

        for entry_point in installed_entry_points:
            label = _entry_point_label(entry_point)
            try:
                with registry.block_registration_side_effects():
                    plugin = _instantiate(entry_point.load())
                registration = registry.validate_plugin(
                    plugin,
                    origin="entry_point",
                    entrypoint=label,
                    distribution=_distribution_name(entry_point),
                )
                metadata = registration.metadata
                if metadata.required_access == "db-write" and not allow_db_write:
                    report["rejected"].append(
                        {
                            "reason_code": "db_write_not_approved",
                            "message": (
                                f"Plugin '{metadata.name}' requires database write access"
                            ),
                            "entrypoint": label,
                            "plugin": _report_item(registration),
                        }
                    )
                    continue
                if metadata.name in names:
                    report["rejected"].append(
                        {
                            "reason_code": "duplicate_plugin",
                            "message": (
                                f"Plugin check code '{metadata.name}' is already installed"
                            ),
                            "entrypoint": label,
                            "plugin": _report_item(registration),
                        }
                    )
                    continue
                registrations.append(registration)
                names.add(metadata.name)
                report["entry_points"].append(_report_item(registration))
            except PluginRegistrationError as error:
                LOGGER.warning("Rejected QC plugin %s: %s", label, error)
                report["rejected"].append(
                    {
                        "reason_code": error.reason_code,
                        "message": str(error),
                        "entrypoint": label,
                    }
                )
            except Exception as error:
                LOGGER.exception("Failed to load QC plugin %s", label)
                report["failed"].append(
                    {
                        "reason_code": "plugin_load_failed",
                        "message": str(error),
                        "entrypoint": label,
                    }
                )

        registry.replace_all(registrations)
        global _LAST_REPORT
        _LAST_REPORT = report
        return get_last_report()


def get_last_report() -> dict[str, Any]:
    """Return a copy of the most recent discovery diagnostics."""
    with _DISCOVERY_LOCK:
        return deepcopy(_LAST_REPORT)
