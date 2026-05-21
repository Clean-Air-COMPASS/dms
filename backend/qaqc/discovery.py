"""Plugin discovery and safe loader for QA/QC plugins.

This module implements discovery from two sources:
- setuptools entry_points group `aq_platform.qaqc_plugins`
- local development directory `backend/qaqc/plugins_local/`

It validates minimal metadata and registers instantiated plugins using
`backend.qaqc.registry.register(plugin_instance)`.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import pathlib
from typing import Any, Dict, List, Optional

try:
                            
    from importlib.metadata import entry_points, EntryPoint
except Exception:                               
    from importlib.metadata import entry_points, EntryPoint

from . import registry
from .types import PluginMeta

LOGGER = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "aq_platform.qaqc_plugins"
LOCAL_PLUGINS_DIR = pathlib.Path(__file__).parent / "plugins_local"


def _instantiate(obj: Any) -> Optional[Any]:
    """Instantiate a loaded entry_point or plugin factory/object.

    - If obj is a class, instantiate it with no args.
    - If obj is a callable factory, call it with no args.
    - If obj looks like an already-instantiated plugin (has `apply`), return it.
    """
    try:
        if hasattr(obj, "apply"):
            return obj
        if isinstance(obj, type):
            return obj()
        if callable(obj):
            inst = obj()
            return inst
    except Exception:
        LOGGER.exception("Failed to instantiate plugin object %r", obj)
    return None


def _meta_from_instance(inst: Any, entrypoint: Optional[EntryPoint] = None) -> PluginMeta:
    name = getattr(inst, "name", None) or (entrypoint.name if entrypoint is not None else None) or getattr(inst, "__class__", None)
    return PluginMeta(
        name=str(name),
        version=getattr(inst, "version", None),
        author=getattr(inst, "author", None),
        api_version=getattr(inst, "api_version", None),
        description=getattr(inst, "description", None),
        module=getattr(inst, "__module__", None),
        entrypoint=str(entrypoint) if entrypoint is not None else None,
        required_access=getattr(inst, "required_access", "api-only"),
        raw=None,
    )


def load_entry_point_plugins() -> List[Dict[str, Any]]:
    """Discover and instantiate plugins exposed via entry_points.

    Returns a list of result dicts with keys: success(bool), meta(PluginMeta|None), error(str|None).
    """
    results: List[Dict[str, Any]] = []
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
                                                                               
        eps = entry_points().get(ENTRY_POINT_GROUP, [])
    except Exception:
        LOGGER.exception("Failed to enumerate entry points for %s", ENTRY_POINT_GROUP)
        eps = []

    for ep in eps:
        try:
            loaded = ep.load()
            inst = _instantiate(loaded)
            if inst is None:
                raise RuntimeError("Could not instantiate plugin from entry point %s" % ep)
            meta = _meta_from_instance(inst, entrypoint=ep)
            registry.register(inst)
            results.append({"success": True, "meta": meta, "error": None})
            LOGGER.info("Loaded plugin %s from entry point %s", meta.name, ep)
        except Exception as exc:                                
            LOGGER.exception("Failed to load plugin entry point %s: %s", ep, exc)
            results.append({"success": False, "meta": None, "error": str(exc)})
    return results


def load_local_plugins(path: pathlib.Path = LOCAL_PLUGINS_DIR) -> List[Dict[str, Any]]:
    """Discover and instantiate plugins from a local directory.

    A plugin file should expose either a module-level `plugin` object or a `get_plugin()` callable.
    """
    results: List[Dict[str, Any]] = []
    if not path.exists():
        return results

    for p in sorted(path.glob("*.py")):
                                   
        if p.name == "__init__.py":
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"qaqc.plugins_local.{p.stem}", str(p))
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Could not create spec for {p}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)                          

            plugin_obj = getattr(module, "plugin", None)
            if plugin_obj is None:
                factory = getattr(module, "get_plugin", None)
                if factory is not None and callable(factory):
                    plugin_obj = factory()

            inst = _instantiate(plugin_obj) if plugin_obj is not None else None
            if inst is None:
                                                        
                LOGGER.debug("No plugin object found in %s; skipping", p.name)
                continue

            meta = _meta_from_instance(inst)
            registry.register(inst)
            results.append({"success": True, "meta": meta, "path": str(p), "error": None})
            LOGGER.info("Loaded local plugin %s from %s", meta.name, p)
        except Exception as exc:                                
            LOGGER.exception("Failed to load local plugin %s: %s", p, exc)
            results.append({"success": False, "meta": None, "path": str(p), "error": str(exc)})
    return results


def load_plugins(approve_write: bool = False) -> Dict[str, Any]:
    """Load plugins from entry points and local dir. Returns a report dict.

    - `approve_write`: if False, plugins declaring `db-write` will not be registered and will be reported.
    """
    report: Dict[str, Any] = {"entry_points": [], "local": [], "skipped_write": []}

    ep_results = load_entry_point_plugins()
    for r in ep_results:
        if r.get("meta") and r["meta"].required_access == "db-write" and not approve_write:
                                                                                                       
            LOGGER.warning("Discovered db-write plugin %s but write approval not given", r["meta"].name)
            report["skipped_write"].append(r.get("meta"))
        else:
            report["entry_points"].append(r)

    local_results = load_local_plugins()
    for r in local_results:
        if r.get("meta") and r["meta"].required_access == "db-write" and not approve_write:
            LOGGER.warning("Discovered local db-write plugin %s but write approval not given", r["meta"].name)
            report["skipped_write"].append(r.get("meta"))
        else:
            report["local"].append(r)

    return report
