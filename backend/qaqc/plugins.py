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
    required_access = "api-only"
    unit_settings = ("min",)
    overview = {
        "visible": True,
        "label": "Minimum",
        "order": 10,
        "summary_setting": "min",
    }
                                                 
    param_schema = {
        "min": {
            "type": "number",
            "label": "Min threshold",
            "required": True,
            "help": "Minimum acceptable value in the resolved evaluation unit",
        }
    }

    def apply(self, records: List[QCRecord], context: dict) -> List[QCDecision]:
        policies = context.get("effective_policies") or []
        out: List[QCDecision] = []
        for index, record in enumerate(records):
            policy = policies[index] if index < len(policies) else None
            if policy is None or "min" not in policy.evaluation_settings:
                out.append(
                    QCDecision(
                        is_valid=None,
                        flags=[],
                        severity="warn",
                        message="min_value requires a resolved 'min' setting",
                        patch={"reason_code": "missing_required_setting"},
                    )
                )
                continue
            threshold = float(policy.evaluation_settings["min"])
            passed = qc_min.evaluate(record.value, threshold)
            if passed is None:
                out.append(
                    QCDecision(
                        is_valid=None,
                        flags=[],
                        severity="warn",
                        message="min_value requires a numeric measurement",
                        patch={"reason_code": "invalid_measurement_value"},
                    )
                )
            elif passed:
                out.append(
                    QCDecision(
                        is_valid=True,
                        flags=[],
                        severity="info",
                        patch={"threshold": threshold},
                    )
                )
            else:
                out.append(
                    QCDecision(
                        is_valid=False,
                        flags=["range_fail"],
                        severity="error",
                        message=f"value {record.value} < min {threshold}",
                        patch={"threshold": threshold},
                    )
                )
        return out


MIN_VALUE_PLUGIN = MinValuePlugin()

# These checks are CompassAQ built-ins and remain available when ingest helpers
# run outside FastAPI's startup lifecycle. ``max_value`` deliberately is not in
# this list: it is the reference deployment-installed entry-point plugin.
from .builtin_plugins.baseline_drift import plugin as BASELINE_DRIFT_PLUGIN

BUILT_IN_PLUGINS = (
    MIN_VALUE_PLUGIN,
    BASELINE_DRIFT_PLUGIN,
)


def register_builtin_plugins() -> None:
    """Validate and register the immutable CompassAQ built-in plugins."""
    for built_in_plugin in BUILT_IN_PLUGINS:
        register(built_in_plugin, origin="built_in")


register_builtin_plugins()
