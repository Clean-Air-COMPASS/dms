from __future__ import annotations

from typing import List, Dict, Any

from .types import QCRecord, QCDecision
from .registry import get, all_plugins
from .config import default_config


_SEVERITY_ORDER = {"info": 0, "warn": 1, "error": 2}


def _resolve_ingest_plugin_names(context: Dict[str, Any]) -> List[str]:
    """Resolve ingest plugin names from config and enabled DB rules.

    Default config provides stable ordering for built-ins. Enabled QC rules
    add additional plugin names for Jenkins-style uploadable plugins.
    """
    base = default_config().get("ingest", [])
    names: List[str] = list(base)

    session = context.get("session")
    if session is not None:
        try:
            from sqlalchemy import select
            import models

            enabled = session.scalars(
                select(models.QCRule.check_code).where(models.QCRule.enabled == True)              
            ).all()
            for code in enabled:
                if code and code not in names:
                    names.append(code)
        except Exception:
            pass

    available = set(all_plugins().keys())
    filtered = [n for n in names if n in available]

    primary: List[str] = []
    for p in ("min_value", "max_value"):
        if p in filtered and p not in primary:
            primary.append(p)
    remaining = sorted({n for n in filtered if n not in primary})
    return primary + remaining


def _reduce(decisions: List[QCDecision]) -> QCDecision:
    """Aggregate multiple plugin decisions into a single decision."""
    if not decisions:
        return QCDecision(is_valid=None, flags=[], severity="info", message="")
                          
    overall: Any = True
    for d in decisions:
        if d.is_valid is False:
            overall = False
            break
        if overall is True and d.is_valid is None:
            overall = None
                 
    flags: List[str] = []
    for d in decisions:
        for f in d.flags:
            if f not in flags:
                flags.append(f)
                  
    sev = max((d.severity for d in decisions), key=lambda s: _SEVERITY_ORDER.get(s, 0), default="info")
                                                              
    msg = next((d.message for d in decisions if d.severity == "error" and d.message),
               next((d.message for d in decisions if d.severity == "warn" and d.message), ""))
    return QCDecision(is_valid=overall, flags=flags, severity=sev, message=msg)


def run_ingest(records: List[QCRecord], context: Dict[str, Any]) -> List[QCDecision]:
    names = _resolve_ingest_plugin_names(context)
    out: List[QCDecision] = []
                                               
                                              
    all_results: List[List[QCDecision]] = []
    for name in names:
        plugin = get(name)
        if not plugin:
            continue
        try:
            res = plugin.apply(records, context)
        except Exception as e:
                                                                     
            res = [QCDecision(is_valid=None, flags=[], severity="warn", message="",
                              plugin_error={"plugin": name, "error": str(e)}) for _ in records]
        all_results.append(res)

                                                        
    if not all_results:
        return [QCDecision(is_valid=None, flags=[], severity="info", message="")] * len(records)

                          
    for i in range(len(records)):
        decisions = [res[i] for res in all_results if i < len(res)]
        out.append(_reduce(decisions))
    return out


def run_ingest_detailed(records: List[QCRecord], context: Dict[str, Any]) -> Dict[str, Any]:
    """Run ingest plugins and return both overall and per-plugin decisions.

    Returns: { 'overall': List[QCDecision], 'per_plugin': Dict[name, List[QCDecision]] }
    """
    names = _resolve_ingest_plugin_names(context)
    per_plugin: Dict[str, List[QCDecision]] = {}
                                             
    for name in names:
        plugin = get(name)
        if not plugin:
            continue
        try:
            per_plugin[name] = plugin.apply(records, context)
        except Exception as e:
            per_plugin[name] = [QCDecision(is_valid=None, flags=[], severity="warn", message="",
                                           plugin_error={"plugin": name, "error": str(e)}) for _ in records]

                                 
    overall: List[QCDecision] = []
    if not per_plugin:
        overall = [QCDecision(is_valid=None, flags=[], severity="info", message="")] * len(records)
    else:
                   
        keys = list(per_plugin.keys())
        for i in range(len(records)):
            decisions = [per_plugin[k][i] for k in keys if i < len(per_plugin[k])]
            overall.append(_reduce(decisions))

    return {"overall": overall, "per_plugin": per_plugin}
