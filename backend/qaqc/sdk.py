"""Small SDK helpers for QC plugin authors.

This module exposes a tiny, well-documented surface intended for data scientists
writing QC plugins. Keep functions small and pandas-friendly. Avoid heavy
opinionated abstractions — the goal is to make common tasks trivial.

Guiding principles:
- Prefer the platform API (ApiClient) for portability.
- If using a DB session, prefer read-only helpers.
- Keep dependencies optional (pandas is used if available).

Example usage (inside a plugin):

from backend.qaqc.sdk import ApiClient, records_to_dataframe

api = ApiClient(base_url="http://localhost:8000")
rules = api.get_json("/admin/qc_rules")

# use pandas when available
df = records_to_dataframe(records)

"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

try:
    import requests
except Exception:                                                                      
    requests = None

try:
    import pandas as pd
except Exception:                                      
    pd = None

LOGGER = logging.getLogger(__name__)


class ApiClient:
    """Tiny HTTP JSON client for backend APIs.

    Designed for plugin authors to call backend endpoints without dealing with
    lower-level session boilerplate. Uses requests if available.

    Example:
        api = ApiClient(base_url="http://localhost:8000")
        data = api.get_json("/parameters")
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 10, session: Optional[Any] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if session is not None:
            self._session = session
        else:
            self._session = requests.Session() if requests is not None else None

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/') }"

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._url(path)
        if self._session is None:
            raise RuntimeError("requests is not available in this environment")
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def post_json(self, path: str, json: Any, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._url(path)
        if self._session is None:
            raise RuntimeError("requests is not available in this environment")
        resp = self._session.post(url, json=json, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()


            
def get_rules_from_db(db: Any) -> List[Dict[str, Any]]:
    """Fetch QCRule rows via a SQLAlchemy session.

    This helper imports models lazily so plugin authors don't need to import
    backend.models at module import time.

    Returns a list of dict-like rule objects (as returned by SQLAlchemy or converted).
    """
    try:
        from backend import models
    except Exception:                                
        LOGGER.exception("Could not import backend.models; get_rules_from_db requires backend context")
        return []

    q = db.query(models.QCRule).filter(models.QCRule.enabled == True)
    out = []
    for r in q:
                                                                  
        cfg = getattr(r, "config", None) or {}
        out.append({
            "rule_id": getattr(r, "rule_id", None),
            "name": getattr(r, "name", None),
            "parameter_id": getattr(r, "parameter_id", None),
            "parameter_code": cfg.get("parameter_code") if isinstance(cfg, dict) else None,
            "config": cfg,
            "enabled": getattr(r, "enabled", True),
        })
    return out


                           
def records_to_dataframe(records: Iterable[Dict[str, Any]]):
    """Convert a list/iterable of mapping records into a pandas.DataFrame when available.

    Falls back to returning the list of dicts if pandas is not installed.
    """
    recs = list(records or [])
    if pd is None:
        return recs
    try:
        return pd.DataFrame.from_records(recs)
    except Exception:
        LOGGER.exception("Failed to convert records to DataFrame; returning raw list")
        return recs


def ensure_numeric(series_or_values, errors: str = "coerce"):
    """Helper to coerce a pandas Series or iterable to numeric values.

    If pandas isn't available, attempts a simple float conversion for each value.
    """
    if pd is None:
        out = []
        for v in series_or_values:
            try:
                out.append(float(v))
            except Exception:
                out.append(None)
        return out

    return pd.to_numeric(series_or_values, errors=errors)


                                              

def find_applicable_rules(rules: List[Dict[str, Any]], parameter_id: Optional[int] = None, parameter_code: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return rules that match the provided parameter_id or parameter_code.

    Simple filter used by many rules (max/min) to find per-parameter rules.
    """
    out = []
    for r in rules:
        cfg = r.get("config") or {}
        if parameter_id is not None and r.get("parameter_id") == parameter_id:
            out.append(r)
            continue
        pc = cfg.get("parameter_code") if isinstance(cfg, dict) else None
        if parameter_code and pc and pc == parameter_code:
            out.append(r)
            continue
                                                   
        if r.get("parameter_id") is None and not pc:
            out.append(r)
    return out
