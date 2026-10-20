from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

                                         
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
class PluginOverviewMeta:
    """Validated metadata for the parameter-centered QC overview."""

    visible: bool
    label: str
    order: int
    summary_setting: Optional[str] = None


@dataclass
class PluginMeta:
    """Validated runtime metadata for an installed QC plugin."""

    name: str
    display_name: str
    version: str
    qc_api: int
    origin: Literal["built_in", "entry_point", "runtime"]
    required_access: Literal["api-only", "db-read", "db-write"]
    description: str
    long_description: str
    param_schema: Dict[str, Any]
    unit_settings: List[str]
    overview: PluginOverviewMeta
    author: Optional[str] = None
    module: Optional[str] = None
    entrypoint: Optional[str] = None
    distribution: Optional[str] = None
