from __future__ import annotations

from typing import List, Literal, Protocol

from .types import QCRecord, QCDecision


QC_PLUGIN_API_VERSION = 1
PluginAccess = Literal["api-only", "db-read", "db-write"]


class QCPlugin(Protocol):
    name: str
    version: str
    description: str
    display_name: str
    long_description: str
    qc_api: int
    required_access: PluginAccess
                                                               
                                                                                                                                    
    param_schema: dict | None
    unit_settings: tuple[str, ...]
    overview: dict | None

    def apply(self, records: List[QCRecord], context: dict) -> List[QCDecision]:
        ...
