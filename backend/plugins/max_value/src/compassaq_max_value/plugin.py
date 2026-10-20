"""Maximum-value QC check implemented through CompassAQ's public plugin path."""

from __future__ import annotations

import math

from qaqc.sdk import effective_policy_for_record, indeterminate_decision
from qaqc.types import QCDecision, QCRecord


class MaxValuePlugin:
    """Fail measurements above the resolver-supplied maximum threshold."""

    name = "max_value"
    version = "1.0.0"
    qc_api = 1
    required_access = "api-only"
    author = "CompassAQ maintainers"
    display_name = "Maximum Value QC Check"
    description = "Fails values above the configured maximum threshold"
    long_description = (
        "This QC check fails any measurement value above the configured maximum "
        "threshold for its parameter or aggregate. CompassAQ resolves inherited "
        "settings, units, and the failure action before calling the plugin."
    )
    param_schema = {
        "max": {
            "type": "number",
            "label": "Max threshold",
            "help": "Maximum acceptable value in the resolved evaluation unit",
            "required": True,
        }
    }
    unit_settings = ("max",)
    overview = {
        "visible": True,
        "label": "Maximum",
        "order": 20,
        "summary_setting": "max",
    }

    def apply(self, records: list[QCRecord], context: dict) -> list[QCDecision]:
        decisions: list[QCDecision] = []
        for record_index, record in enumerate(records):
            policy = effective_policy_for_record(context, record_index)
            if policy is None:
                decisions.append(
                    indeterminate_decision(
                        "missing_effective_policy",
                        "max_value requires a resolver-supplied effective policy",
                    )
                )
                continue

            if "max" not in policy.evaluation_settings:
                decisions.append(
                    indeterminate_decision(
                        "missing_required_setting",
                        "max_value requires a resolved 'max' setting",
                    )
                )
                continue

            try:
                maximum = float(policy.evaluation_settings["max"])
            except (TypeError, ValueError):
                decisions.append(
                    indeterminate_decision(
                        "invalid_policy_setting",
                        "max_value requires a finite numeric 'max' setting",
                    )
                )
                continue

            if not math.isfinite(maximum):
                decisions.append(
                    indeterminate_decision(
                        "invalid_policy_setting",
                        "max_value requires a finite numeric 'max' setting",
                    )
                )
                continue

            try:
                measurement_value = float(record.value)
            except (TypeError, ValueError):
                decisions.append(
                    indeterminate_decision(
                        "invalid_measurement_value",
                        "max_value requires a numeric measurement",
                    )
                )
                continue

            if not math.isfinite(measurement_value):
                decisions.append(
                    indeterminate_decision(
                        "invalid_measurement_value",
                        "max_value requires a finite numeric measurement",
                    )
                )
                continue

            if measurement_value <= maximum:
                decisions.append(
                    QCDecision(
                        is_valid=True,
                        flags=[],
                        severity="info",
                        patch={"threshold": maximum},
                    )
                )
                continue

            decisions.append(
                QCDecision(
                    is_valid=False,
                    flags=["range_fail"],
                    severity="error",
                    message=f"value {record.value} > max {maximum}",
                    patch={"threshold": maximum},
                )
            )
        return decisions


plugin = MaxValuePlugin()
