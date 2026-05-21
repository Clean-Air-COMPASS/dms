from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Any, Dict, Literal

                                         
Severity = Literal["info", "warn", "error"]


@dataclass
class QCRecord:
    sensor_id: Optional[int]
    parameter_id: Optional[int]
    value: Optional[float]
    unit_id: Optional[int]
    observed_at: Optional[Any]                              
    device_latitude: Optional[float] = None
    device_longitude: Optional[float] = None
    meta: Optional[Dict[str, Any]] = None


@dataclass
class QCDecision:
    is_valid: Optional[bool]                                     
    flags: List[str]
    severity: Severity
    message: str = ""
    patch: Optional[Dict[str, Any]] = None
    plugin_error: Optional[Dict[str, Any]] = None


@dataclass
class PluginMeta:
    """Runtime metadata for discovered plugins."""
    name: str
    version: Optional[str] = None
    author: Optional[str] = None
    api_version: Optional[str] = None
    description: Optional[str] = None
    module: Optional[str] = None
    entrypoint: Optional[str] = None
    required_access: str = "api-only"                                 
    raw: Optional[Dict[str, Any]] = None
