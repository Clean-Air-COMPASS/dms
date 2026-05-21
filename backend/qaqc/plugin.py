from __future__ import annotations

from typing import List, Protocol

from .types import QCRecord, QCDecision


class QCPlugin(Protocol):
    name: str
    version: str
    description: str
    display_name: str
    long_description: str
    qc_api: int
                                                               
                                                                                                                                    
    param_schema: dict | None

    def apply(self, records: List[QCRecord], context: dict) -> List[QCDecision]:
        ...
