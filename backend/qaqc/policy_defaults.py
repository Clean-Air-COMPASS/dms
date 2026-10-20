"""CompassAQ's explicit, versioned QC defaults and screening presets.

These values are plausibility and documented method/instrument envelopes. They
are not AQI breakpoints, regulatory exceedance levels, or calibration limits.

Scientific references reviewed for profile 2026.2:

* US EPA AQS criteria-pollutant method ranges:
  https://aqs.epa.gov/aqsweb/documents/codetables/methods_criteria.html
* US EPA guidance for reporting small negative gaseous measurements:
  https://www.epa.gov/sites/default/files/2017-02/documents/negative_values_reporting_to_aqs_10_6_16.pdf
* US EPA ambient-air QA Handbook Volume II and its 24-hour zero-drift
  acceptance guidance for O3, SO2, NO2, and CO:
  https://www.epa.gov/amtic/ambient-air-monitoring-quality-assurance-guidance-documents
* WMO world temperature records (used only as context for the broad
  temperature plausibility envelope):
  https://wmo.int/sites/default/files/2024-07/Table_Records_02Jul2024.pdf

Disabled entries are intentional. A check that still needs domain-owner or
instrument-specific confirmation must remain visibly disabled rather than run
against a plausible-looking hidden fallback. Baseline Drift settings may be
retained on a disabled row so an administrator can deliberately enable the
documented CompassAQ screening preset without reconstructing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


ACTIVE_DEFAULT_POLICY_PROFILE_VERSION = "2026.2"
# Compatibility name used by result snapshots and existing Phase 1A tests.
DEFAULT_POLICY_PROFILE_VERSION = ACTIVE_DEFAULT_POLICY_PROFILE_VERSION

FLAG_FOR_REVIEW = "flag_for_review"
MARK_INVALID = "mark_invalid"
FAILURE_ACTIONS = frozenset({FLAG_FOR_REVIEW, MARK_INVALID})

MIN_VALUE_CHECK = "min_value"
MAX_VALUE_CHECK = "max_value"
RANGE_CHECK_CODES = frozenset({MIN_VALUE_CHECK, MAX_VALUE_CHECK})
BASELINE_DRIFT_CHECK = "baseline_drift"
# This order describes CompassAQ's supplied policy rows when a plugin is
# unavailable. Installed plugins publish their own deterministic overview
# order and are not ordered by this fallback.
BUILT_IN_CHECK_ORDER = (
    MIN_VALUE_CHECK,
    MAX_VALUE_CHECK,
    BASELINE_DRIFT_CHECK,
)


@dataclass(frozen=True)
class DefaultQCPolicy:
    parameter_code: str
    check_code: str
    enabled: bool
    failure_action: str
    settings: Mapping[str, Any]
    policy_unit_code: str | None
    rationale: str
    source_reference: str
    unit_settings: tuple[str, ...] = ()
    profile_version: str = DEFAULT_POLICY_PROFILE_VERSION


PARAMETER_CODE_ALIASES = MappingProxyType(
    {
        "temp": "temperature",
        "temperature": "temperature",
        "rh": "relative_humidity",
        "relativehumidity": "relative_humidity",
        "relative_humidity": "relative_humidity",
    }
)


def canonicalize_qc_parameter_code(parameter_code: str) -> str:
    normalized = parameter_code.strip().lower()
    return PARAMETER_CODE_ALIASES.get(normalized, normalized)


def _range_policies(
    parameter_code: str,
    minimum: float,
    maximum: float,
    unit_code: str,
    failure_action: str,
    rationale: str,
    source_reference: str,
) -> tuple[DefaultQCPolicy, DefaultQCPolicy]:
    return (
        DefaultQCPolicy(
            parameter_code=parameter_code,
            check_code=MIN_VALUE_CHECK,
            enabled=True,
            failure_action=failure_action,
            settings=MappingProxyType({"min": minimum}),
            policy_unit_code=unit_code,
            rationale=rationale,
            source_reference=source_reference,
            unit_settings=("min",),
        ),
        DefaultQCPolicy(
            parameter_code=parameter_code,
            check_code=MAX_VALUE_CHECK,
            enabled=True,
            failure_action=failure_action,
            settings=MappingProxyType({"max": maximum}),
            policy_unit_code=unit_code,
            rationale=rationale,
            source_reference=source_reference,
            unit_settings=("max",),
        ),
    )


def _baseline_drift_policy(
    parameter_code: str,
    unit_code: str,
    *,
    enabled: bool,
    max_drift_per_day: float | None = None,
    rationale: str,
    source_reference: str,
) -> tuple[DefaultQCPolicy, ...]:
    """Create one explicit parameter + unit Baseline Drift policy or preset."""

    settings: Mapping[str, Any]
    if max_drift_per_day is not None:
        settings = MappingProxyType(
            {
                "lookback_hours": 168,
                "min_samples": 72,
                "baseline_quantile": 0.1,
                "max_drift_per_day": max_drift_per_day,
                "direction": "both",
            }
        )
    else:
        if enabled:
            raise ValueError("An enabled baseline-drift default requires a maximum")
        settings = MappingProxyType({})

    return (
        DefaultQCPolicy(
            parameter_code=parameter_code,
            check_code=BASELINE_DRIFT_CHECK,
            enabled=enabled,
            failure_action=FLAG_FOR_REVIEW,
            settings=settings,
            policy_unit_code=unit_code,
            rationale=rationale,
            source_reference=source_reference,
            unit_settings=("max_drift_per_day",),
        ),
    )


_AQS_METHOD_RANGES = "US EPA AQS criteria-pollutant method ranges"
_EPA_NEGATIVE_GUIDANCE = "US EPA 2016 negative-value reporting guidance"
_EPA_ZERO_DRIFT_GUIDANCE = (
    "US EPA QA Handbook Volume II 24-hour zero-drift acceptance guidance"
)
_LIVE_BASELINE_REVIEW = (
    "CompassAQ OpenAQ, PurpleAir, and AirGradient seven-day baseline review, "
    "2026-08-27"
)

_DEFAULT_POLICY_ROWS = (
    *_range_policies(
        "pm25", -10.0, 10_000.0, "ug_m3", FLAG_FOR_REVIEW,
        "Broad PM2.5 method-range envelope; small negative readings can be analytically valid.",
        _AQS_METHOD_RANGES,
    ),
    *_range_policies(
        "pm10", -50.0, 17_000.0, "ug_m3", FLAG_FOR_REVIEW,
        "Broad PM10 method-range envelope; small negative readings can be analytically valid.",
        _AQS_METHOD_RANGES,
    ),
    *_range_policies(
        "o3", -0.004, 0.5, "ppm", FLAG_FOR_REVIEW,
        "AQS method-range envelope, including the EPA negative reporting allowance.",
        f"{_AQS_METHOD_RANGES}; {_EPA_NEGATIVE_GUIDANCE}",
    ),
    *_range_policies(
        "no2", -0.005, 4.0, "ppm", FLAG_FOR_REVIEW,
        "AQS method-range envelope, including the EPA negative reporting allowance.",
        f"{_AQS_METHOD_RANGES}; {_EPA_NEGATIVE_GUIDANCE}",
    ),
    *_range_policies(
        "so2", -0.004, 10.0, "ppm", FLAG_FOR_REVIEW,
        "AQS method-range envelope, including the EPA negative reporting allowance.",
        f"{_AQS_METHOD_RANGES}; {_EPA_NEGATIVE_GUIDANCE}",
    ),
    *_range_policies(
        "co", -0.4, 50.0, "ppm", FLAG_FOR_REVIEW,
        "AQS method-range envelope, including the EPA negative reporting allowance.",
        f"{_AQS_METHOD_RANGES}; {_EPA_NEGATIVE_GUIDANCE}",
    ),
    *_range_policies(
        "temperature", -90.0, 60.0, "celsius", FLAG_FOR_REVIEW,
        "Broad ambient-temperature plausibility envelope beyond documented WMO extremes.",
        "WMO world weather and climate extremes table, reviewed July 2024",
    ),
    *_range_policies(
        "relative_humidity", 0.0, 100.0, "percent", MARK_INVALID,
        "Relative humidity outside 0–100 percent is physically invalid.",
        "Definition of relative humidity as a percentage of saturation",
    ),
    *_range_policies(
        "tvoc_index", 0.0, 500.0, "index", MARK_INVALID,
        "Documented Sensirion gas-index output domain.",
        "Sensirion SGP41 data sheet and Gas Index Algorithm documentation",
    ),
    *_range_policies(
        "nox_index", 0.0, 500.0, "index", MARK_INVALID,
        "Documented Sensirion gas-index output domain.",
        "Sensirion SGP41 data sheet and Gas Index Algorithm documentation",
    ),
    *_baseline_drift_policy(
        "pm1", "ug_m3", enabled=False, max_drift_per_day=5.0,
        rationale=(
            "A seven-day low-quantile shift above 5 ug/m3/day is a candidate "
            "screening signal for an optical particulate baseline, not a "
            "universally validated limit or proof that a measurement is invalid."
        ),
        source_reference=_LIVE_BASELINE_REVIEW,
    ),
    *_baseline_drift_policy(
        "pm25", "ug_m3", enabled=False, max_drift_per_day=5.0,
        rationale=(
            "The limit exceeds the largest absolute PM2.5 drift observed across "
            "the limited reviewed live provider streams. It is retained as a "
            "disabled CompassAQ screening preset pending broader validation."
        ),
        source_reference=_LIVE_BASELINE_REVIEW,
    ),
    *_baseline_drift_policy(
        "pm10", "ug_m3", enabled=False, max_drift_per_day=10.0,
        rationale=(
            "PM10 has a more variable natural low end than PM2.5; the higher "
            "candidate limit remains above every reviewed live seven-day drift."
        ),
        source_reference=_LIVE_BASELINE_REVIEW,
    ),
    *_baseline_drift_policy(
        "o3", "ppm", enabled=False, max_drift_per_day=0.003,
        rationale=(
            "The review threshold uses EPA's 24-hour gaseous-analyzer zero-drift "
            "criterion only as a candidate screening reference. The ambient low "
            "quantile is not a zero-air calibration check."
        ),
        source_reference=_EPA_ZERO_DRIFT_GUIDANCE,
    ),
    *_baseline_drift_policy(
        "no2", "ppm", enabled=False, max_drift_per_day=0.003,
        rationale=(
            "The review threshold uses EPA's 24-hour gaseous-analyzer zero-drift "
            "criterion only as a candidate screening reference. Gas mass units "
            "intentionally receive no implicit preset."
        ),
        source_reference=_EPA_ZERO_DRIFT_GUIDANCE,
    ),
    *_baseline_drift_policy(
        "so2", "ppm", enabled=False, max_drift_per_day=0.003,
        rationale=(
            "The review threshold uses EPA's 24-hour gaseous-analyzer zero-drift "
            "criterion only as a candidate screening reference. Gas mass units "
            "intentionally receive no implicit preset."
        ),
        source_reference=_EPA_ZERO_DRIFT_GUIDANCE,
    ),
    *_baseline_drift_policy(
        "co", "ppm", enabled=False, max_drift_per_day=0.4,
        rationale=(
            "The review threshold uses EPA's 24-hour CO-analyzer zero-drift "
            "criterion only as a candidate screening reference. Gas mass units "
            "intentionally receive no implicit preset."
        ),
        source_reference=_EPA_ZERO_DRIFT_GUIDANCE,
    ),
    *_baseline_drift_policy(
        "no", "ppb", enabled=False,
        rationale="Instrument- and channel-specific review is needed before recommending a NO threshold.",
        source_reference="No provider-neutral CompassAQ recommendation",
    ),
    *_baseline_drift_policy(
        "nox", "ppm", enabled=False,
        rationale="Instrument- and channel-specific review is needed before recommending a NOx threshold.",
        source_reference="No provider-neutral CompassAQ recommendation",
    ),
    *_baseline_drift_policy(
        "co2", "ppm", enabled=False,
        rationale="A provider-neutral outdoor CO2 low-quantile drift threshold is not established.",
        source_reference="No provider-neutral CompassAQ recommendation",
    ),
    *_baseline_drift_policy(
        "temperature", "celsius", enabled=False,
        rationale="The low-end quantile follows weather and seasons rather than an instrument zero baseline.",
        source_reference="Baseline-drift check is not appropriate as a default",
    ),
    *_baseline_drift_policy(
        "relative_humidity", "percent", enabled=False,
        rationale="The low-end quantile follows weather and seasons rather than an instrument zero baseline.",
        source_reference="Baseline-drift check is not appropriate as a default",
    ),
    *_baseline_drift_policy(
        "pressure", "hpa", enabled=False,
        rationale="The low-end quantile follows synoptic weather changes rather than an instrument zero baseline.",
        source_reference="Baseline-drift check is not appropriate as a default",
    ),
    *_baseline_drift_policy(
        "tvoc", "ug_m3", enabled=False,
        rationale="TVOC response and baselines are instrument-specific, so a universal mass threshold is not defensible.",
        source_reference="No provider-neutral CompassAQ recommendation",
    ),
    *_baseline_drift_policy(
        "tvoc_index", "index", enabled=False,
        rationale="The VOC index has an adaptive baseline; its low quantile is not an absolute sensor zero.",
        source_reference="Sensirion VOC Index algorithm documentation",
    ),
    *_baseline_drift_policy(
        "nox_index", "index", enabled=False,
        rationale="The NOx index has an adaptive baseline; its low quantile is not an absolute sensor zero.",
        source_reference="Sensirion Gas Index algorithm documentation",
    ),
)

_POLICY_PROFILE_2026_2 = MappingProxyType(
    {
        (row.parameter_code, row.policy_unit_code, row.check_code): row
        for row in _DEFAULT_POLICY_ROWS
    }
)

# New profiles can be installed beside 2026.2 without changing live behavior.
# Activating a future profile requires an explicit edit to the active-version
# constant above and therefore cannot happen merely by adding reference data.
DEFAULT_QC_POLICY_PROFILES = MappingProxyType(
    {"2026.2": _POLICY_PROFILE_2026_2}
)
DEFAULT_QC_POLICIES = DEFAULT_QC_POLICY_PROFILES[
    ACTIVE_DEFAULT_POLICY_PROFILE_VERSION
]


def get_default_qc_policy(
    parameter_code: str,
    policy_unit_code: str | None,
    check_code: str,
) -> DefaultQCPolicy | None:
    canonical_code = canonicalize_qc_parameter_code(parameter_code)
    return DEFAULT_QC_POLICIES.get(
        (canonical_code, policy_unit_code, check_code)
    )


def get_default_qc_policies(
    parameter_code: str,
    check_code: str,
) -> tuple[DefaultQCPolicy, ...]:
    """Return every explicitly unit-scoped default for one check."""

    canonical_code = canonicalize_qc_parameter_code(parameter_code)
    return tuple(
        policy
        for (policy_parameter_code, _unit_code, policy_check_code), policy
        in DEFAULT_QC_POLICIES.items()
        if policy_parameter_code == canonical_code
        and policy_check_code == check_code
    )


def get_default_check_codes(parameter_code: str) -> tuple[str, ...]:
    canonical_code = canonicalize_qc_parameter_code(parameter_code)
    available = {
        check_code
        for (policy_parameter_code, _unit_code, check_code) in DEFAULT_QC_POLICIES
        if policy_parameter_code == canonical_code
    }
    return tuple(code for code in BUILT_IN_CHECK_ORDER if code in available)


def get_all_default_check_codes() -> tuple[str, ...]:
    """Return every check code referenced by CompassAQ's policy data."""

    available = {check_code for _parameter, _unit, check_code in DEFAULT_QC_POLICIES}
    ordered = [code for code in BUILT_IN_CHECK_ORDER if code in available]
    ordered.extend(sorted(available - set(ordered)))
    return tuple(ordered)


def get_default_unit_settings(check_code: str) -> tuple[str, ...]:
    """Return unit-aware settings declared by CompassAQ policy rows.

    This fallback keeps configured policy explicit when its executable plugin
    is unavailable. Installed plugin metadata remains authoritative.
    """

    declarations = {
        policy.unit_settings
        for (_parameter, _unit, policy_check_code), policy in DEFAULT_QC_POLICIES.items()
        if policy_check_code == check_code
    }
    if not declarations:
        return ()
    if len(declarations) != 1:
        raise ValueError(f"CompassAQ defaults disagree on unit settings for {check_code}")
    return next(iter(declarations))
