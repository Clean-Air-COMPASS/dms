from __future__ import annotations

from typing import List

from .plugin import QCPlugin
from .types import QCRecord, QCDecision
from .registry import register
from .rules import min_value as qc_min


class MinValuePlugin:
    name = "min_value"
    version = "1.0.0"
    description = "Fails values below configured minimum per parameter/aggregate"
    display_name = "Minimum Value QC Check"
    long_description = "This QC check fails any measurement value that is below the configured minimum threshold for its parameter or aggregate. The threshold can be set globally or overridden per sensor."
    qc_api = 1
                                                 
    param_schema = {
        "min": {
            "type": "number",
            "label": "Min threshold",
            "required": False,
            "help": "Minimum acceptable value; measurements below this are marked invalid",
        }
    }

    def apply(self, records: List[QCRecord], context: dict) -> List[QCDecision]:
        session = context.get("session")
        aggregate = context.get("aggregate_code", "1h")
        out: List[QCDecision] = []
        for r in records:
            passed, threshold, meta = qc_min.evaluate_meta(session, r.value, r.sensor_id, r.parameter_id, aggregate_code=aggregate)
            if passed:
                out.append(QCDecision(is_valid=True, flags=[], severity="info", message="", patch={"threshold": threshold, **meta}))
            else:
                msg = f"value {r.value} < min {threshold}"
                out.append(QCDecision(is_valid=False, flags=["range_fail"], severity="error", message=msg, patch={"threshold": threshold, **meta}))
        return out


                                     
register(MinValuePlugin())
