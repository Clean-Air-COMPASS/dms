"""A deliberately small third-party-style QC plugin used by acceptance tests."""

from __future__ import annotations

import math

from qaqc.sdk import effective_policy_for_record, indeterminate_decision
from qaqc.types import QCDecision, QCRecord


class ReferenceThresholdPlugin:
    name = "reference_threshold"
    version = "1.0.0"
    qc_api = 1
    required_access = "api-only"
    author = "CompassAQ test suite"
    display_name = "Reference Threshold QC Check"
    description = "Flags values above a test threshold"
    long_description = (
        "A test-only check that proves an independently packaged plugin can use "
        "the complete published CompassAQ QC path."
    )
    param_schema = {
        "limit": {
            "type": "number",
            "label": "Threshold",
            "help": "Test-only value above which a measurement fails",
            "required": True,
        }
    }
    unit_settings = ()
    overview = {
        "visible": True,
        "label": "Reference Threshold",
        "order": 40,
        "summary_setting": "limit",
    }

    def apply(self, records: list[QCRecord], context: dict) -> list[QCDecision]:
        decisions: list[QCDecision] = []
        for record_index, record in enumerate(records):
            policy = effective_policy_for_record(context, record_index)
            if policy is None:
                decisions.append(
                    indeterminate_decision(
                        "missing_effective_policy",
                        "reference_threshold requires an effective policy",
                    )
                )
                continue
            try:
                limit = float(policy.evaluation_settings["limit"])
                measurement_value = float(record.value)
            except (KeyError, TypeError, ValueError):
                decisions.append(
                    indeterminate_decision(
                        "invalid_measurement_value",
                        "reference_threshold requires numeric values and settings",
                    )
                )
                continue
            if not math.isfinite(limit) or not math.isfinite(measurement_value):
                decisions.append(
                    indeterminate_decision(
                        "invalid_measurement_value",
                        "reference_threshold requires finite values and settings",
                    )
                )
                continue
            passed = measurement_value <= limit
            decisions.append(
                QCDecision(
                    is_valid=passed,
                    flags=[] if passed else ["reference_threshold_fail"],
                    severity="info" if passed else "warn",
                    message="" if passed else f"value {record.value} exceeded limit {limit}",
                    patch={"threshold": limit},
                )
            )
        return decisions


plugin = ReferenceThresholdPlugin()
