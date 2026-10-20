"""Public, historical QC presentation. Never resolves today's effective policy.

History carries small summaries; one observation's recorded provenance is loaded
on demand. Public fields are allowlisted because plugin snapshots are extensible
and the measurement-history routes do not require administrator authorization.
"""
from models import MeasurementQCResult


PUBLIC_SETTINGS = {
    "min_value": {"min"},
    "max_value": {"max"},
    "baseline_drift": {"lookback_hours", "min_samples", "baseline_quantile", "max_drift_per_day", "direction"},
}
LAYER_FIELDS = {"layer", "qc_rule_id", "rule_version", "default_profile_version", "policy_unit_code"}
POLICY_FIELDS = {"check_code", "status", "enabled", "failure_action", "default_profile_version",
                 "configured_unit_code", "evaluation_unit_code", "applicable_unit_code", "applicability"}


def qc_summary(result):
    return {key: getattr(result, key) for key in (
        "check_code", "evaluation_status", "passed", "failure_action", "reason_code", "severity",
    )}


def public_qc_detail(result: MeasurementQCResult) -> dict:
    setting_keys = PUBLIC_SETTINGS.get(result.check_code, set())

    def settings(value):
        return {key: item for key, item in (value or {}).items()
                if key in setting_keys and isinstance(item, (str, int, float, bool, type(None)))}

    snapshot = result.policy_snapshot
    policy = None
    if snapshot is not None:
        policy = {key: value for key, value in snapshot.items() if key in POLICY_FIELDS}
        for key in ("configured_settings", "evaluation_settings"):
            if key in snapshot:
                policy[key] = settings(snapshot[key])
        if isinstance(snapshot.get("unit_conversion"), dict):
            policy["unit_conversion"] = {key: value for key, value in snapshot["unit_conversion"].items()
                if key in {"status", "configured_unit_code", "normalized_configured_unit_code",
                           "evaluation_unit_code", "normalized_evaluation_unit_code", "factor"}}
        if "applied_layers" in snapshot:
            policy["applied_layers"] = [
                {key: value for key, value in layer.items() if key in LAYER_FIELDS}
                for layer in snapshot["applied_layers"]
            ]
    property_keys = {"enabled", "failure_action"} | {f"settings.{key}" for key in setting_keys}
    provenance = None if result.policy_provenance is None else {
        prop: {key: value for key, value in layer.items() if key in LAYER_FIELDS}
        for prop, layer in result.policy_provenance.items() if prop in property_keys
    }
    return {
        **qc_summary(result), "message": result.message, "rule_source": result.rule_source,
        "plugin_version": result.plugin_version, "qc_version": result.qc_version,
        "stage": result.stage, "recorded_at": result.created_at,
        "params_snapshot": None if result.params_snapshot is None else settings(result.params_snapshot),
        "policy_snapshot": policy, "policy_provenance": provenance,
        "settings_disclosure": "supported" if result.check_code in PUBLIC_SETTINGS else "unavailable",
    }
