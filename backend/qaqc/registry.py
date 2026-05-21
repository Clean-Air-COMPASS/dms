from __future__ import annotations

from typing import Dict

from .plugin import QCPlugin


_REGISTRY: Dict[str, QCPlugin] = {}


def register(plugin: QCPlugin) -> None:
    _REGISTRY[plugin.name] = plugin


def get(name: str) -> QCPlugin | None:
    return _REGISTRY.get(name)


def all_plugins() -> Dict[str, QCPlugin]:
    return dict(_REGISTRY)


def clear() -> None:
    """Remove all registered plugins (used before reload)."""
    _REGISTRY.clear()
