"""Validated, deterministic registry for executable QC plugins."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import Iterable

from .plugin import QC_PLUGIN_API_VERSION, QCPlugin
from .types import PluginMeta, PluginOverviewMeta


PLUGIN_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SETTING_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ALLOWED_ACCESS = {"api-only", "db-read", "db-write"}
ALLOWED_SETTING_TYPES = {"boolean", "integer", "number", "string"}
OVERVIEW_DEFAULT_ORDER = 1_000


class PluginRegistrationError(ValueError):
    """A plugin cannot be registered under the Phase 1C contract."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class RegisteredPlugin:
    plugin: QCPlugin
    metadata: PluginMeta


_REGISTRY: dict[str, RegisteredPlugin] = {}
_REGISTRY_LOCK = RLock()
_REGISTRATION_BLOCK_DEPTH = 0


def _required_text(plugin: object, field_name: str) -> str:
    value = getattr(plugin, field_name, None)
    if not isinstance(value, str) or not value.strip():
        raise PluginRegistrationError(
            "invalid_plugin_metadata",
            f"Plugin {field_name} must be a non-empty string",
        )
    return value.strip()


def _validated_parameter_schema(plugin_name: str, raw_schema: object) -> dict:
    if raw_schema is None:
        return {}
    if not isinstance(raw_schema, dict):
        raise PluginRegistrationError(
            "invalid_parameter_schema",
            f"Plugin '{plugin_name}' param_schema must be an object",
        )

    schema: dict = {}
    for setting_name, raw_setting in raw_schema.items():
        if not isinstance(setting_name, str) or not SETTING_NAME_PATTERN.fullmatch(
            setting_name
        ):
            raise PluginRegistrationError(
                "invalid_parameter_schema",
                f"Plugin '{plugin_name}' has invalid setting name {setting_name!r}",
            )
        if not isinstance(raw_setting, dict):
            raise PluginRegistrationError(
                "invalid_parameter_schema",
                f"Plugin '{plugin_name}' setting '{setting_name}' must be an object",
            )
        unsupported_keys = sorted(
            set(raw_setting)
            - {"type", "label", "help", "required", "choices", "minimum", "maximum"}
        )
        if unsupported_keys:
            raise PluginRegistrationError(
                "invalid_parameter_schema",
                f"Plugin '{plugin_name}' setting '{setting_name}' has unsupported metadata '{unsupported_keys[0]}'",
            )
        setting_type = raw_setting.get("type")
        if setting_type not in ALLOWED_SETTING_TYPES:
            raise PluginRegistrationError(
                "invalid_parameter_schema",
                f"Plugin '{plugin_name}' setting '{setting_name}' has unsupported type",
            )
        label = raw_setting.get("label")
        help_text = raw_setting.get("help")
        required = raw_setting.get("required", False)
        if not isinstance(label, str) or not label.strip():
            raise PluginRegistrationError(
                "invalid_parameter_schema",
                f"Plugin '{plugin_name}' setting '{setting_name}' requires a label",
            )
        if not isinstance(help_text, str) or not help_text.strip():
            raise PluginRegistrationError(
                "invalid_parameter_schema",
                f"Plugin '{plugin_name}' setting '{setting_name}' requires help text",
            )
        if not isinstance(required, bool):
            raise PluginRegistrationError(
                "invalid_parameter_schema",
                f"Plugin '{plugin_name}' setting '{setting_name}' required must be boolean",
            )
        choices = raw_setting.get("choices")
        if choices is not None and (
            not isinstance(choices, list)
            or not choices
            or any(not isinstance(choice, (str, int, float, bool)) for choice in choices)
        ):
            raise PluginRegistrationError(
                "invalid_parameter_schema",
                f"Plugin '{plugin_name}' setting '{setting_name}' choices are invalid",
            )
        minimum = raw_setting.get("minimum")
        maximum = raw_setting.get("maximum")
        if minimum is not None or maximum is not None:
            if setting_type not in {"integer", "number"}:
                raise PluginRegistrationError(
                    "invalid_parameter_schema",
                    f"Plugin '{plugin_name}' setting '{setting_name}' bounds require a numeric type",
                )
            for bound_name, bound_value in (
                ("minimum", minimum),
                ("maximum", maximum),
            ):
                if bound_value is not None and (
                    isinstance(bound_value, bool)
                    or not isinstance(bound_value, (int, float))
                    or not math.isfinite(float(bound_value))
                ):
                    raise PluginRegistrationError(
                        "invalid_parameter_schema",
                        f"Plugin '{plugin_name}' setting '{setting_name}' {bound_name} must be finite",
                    )
            if (
                minimum is not None
                and maximum is not None
                and float(minimum) > float(maximum)
            ):
                raise PluginRegistrationError(
                    "invalid_parameter_schema",
                    f"Plugin '{plugin_name}' setting '{setting_name}' minimum exceeds maximum",
                )
        schema[setting_name] = {
            "type": setting_type,
            "label": label.strip(),
            "help": help_text.strip(),
            "required": required,
        }
        if choices is not None:
            schema[setting_name]["choices"] = list(choices)
        if minimum is not None:
            schema[setting_name]["minimum"] = minimum
        if maximum is not None:
            schema[setting_name]["maximum"] = maximum
    return schema


def _validated_overview_metadata(
    plugin: QCPlugin,
    plugin_name: str,
    display_name: str,
    parameter_schema: dict,
) -> PluginOverviewMeta:
    raw_overview = getattr(plugin, "overview", None)
    if raw_overview is None:
        raw_overview = {}
    if not isinstance(raw_overview, dict):
        raise PluginRegistrationError(
            "invalid_overview_metadata",
            f"Plugin '{plugin_name}' overview metadata must be an object",
        )
    unsupported_keys = sorted(
        set(raw_overview) - {"visible", "label", "order", "summary_setting"}
    )
    if unsupported_keys:
        raise PluginRegistrationError(
            "invalid_overview_metadata",
            f"Plugin '{plugin_name}' overview metadata has unsupported field '{unsupported_keys[0]}'",
        )

    visible = raw_overview.get("visible", True)
    if not isinstance(visible, bool):
        raise PluginRegistrationError(
            "invalid_overview_metadata",
            f"Plugin '{plugin_name}' overview visible must be boolean",
        )
    label = raw_overview.get("label", display_name)
    if not isinstance(label, str) or not label.strip():
        raise PluginRegistrationError(
            "invalid_overview_metadata",
            f"Plugin '{plugin_name}' overview label must be non-empty text",
        )
    order = raw_overview.get("order", OVERVIEW_DEFAULT_ORDER)
    if isinstance(order, bool) or not isinstance(order, int):
        raise PluginRegistrationError(
            "invalid_overview_metadata",
            f"Plugin '{plugin_name}' overview order must be an integer",
        )
    summary_setting = raw_overview.get("summary_setting")
    if summary_setting is not None:
        if not isinstance(summary_setting, str) or summary_setting not in parameter_schema:
            raise PluginRegistrationError(
                "invalid_overview_metadata",
                f"Plugin '{plugin_name}' overview summary_setting must name a declared setting",
            )
    return PluginOverviewMeta(
        visible=visible,
        label=label.strip(),
        order=order,
        summary_setting=summary_setting,
    )


def validate_plugin(
    plugin: QCPlugin,
    *,
    origin: str,
    entrypoint: str | None = None,
    distribution: str | None = None,
) -> RegisteredPlugin:
    """Validate executable and descriptive metadata before registration."""
    name = _required_text(plugin, "name")
    if not PLUGIN_NAME_PATTERN.fullmatch(name):
        raise PluginRegistrationError(
            "invalid_plugin_name",
            f"Plugin name '{name}' must use lowercase letters, digits, and underscores",
        )
    if not callable(getattr(plugin, "apply", None)):
        raise PluginRegistrationError(
            "invalid_plugin_contract",
            f"Plugin '{name}' must provide an apply(records, context) method",
        )
    qc_api = getattr(plugin, "qc_api", None)
    if qc_api != QC_PLUGIN_API_VERSION:
        raise PluginRegistrationError(
            "unsupported_plugin_api",
            f"Plugin '{name}' requires QC API {qc_api!r}; supported version is {QC_PLUGIN_API_VERSION}",
        )
    required_access = getattr(plugin, "required_access", "api-only")
    if required_access not in ALLOWED_ACCESS:
        raise PluginRegistrationError(
            "invalid_required_access",
            f"Plugin '{name}' required_access must be api-only, db-read, or db-write",
        )
    if origin not in {"built_in", "entry_point", "runtime"}:
        raise PluginRegistrationError(
            "invalid_plugin_origin", f"Plugin '{name}' has invalid origin '{origin}'"
        )

    display_name = _required_text(plugin, "display_name")
    parameter_schema = _validated_parameter_schema(
        name, getattr(plugin, "param_schema", None)
    )
    raw_unit_settings = getattr(plugin, "unit_settings", ())
    if not isinstance(raw_unit_settings, (list, tuple)) or any(
        not isinstance(setting_name, str) for setting_name in raw_unit_settings
    ):
        raise PluginRegistrationError(
            "invalid_unit_settings",
            f"Plugin '{name}' unit_settings must be a list of setting names",
        )
    unit_settings = list(dict.fromkeys(raw_unit_settings))
    for setting_name in unit_settings:
        setting_schema = parameter_schema.get(setting_name)
        if setting_schema is None or setting_schema["type"] not in {
            "integer",
            "number",
        }:
            raise PluginRegistrationError(
                "invalid_unit_settings",
                f"Plugin '{name}' unit setting '{setting_name}' must be a numeric schema setting",
            )

    metadata = PluginMeta(
        name=name,
        display_name=display_name,
        version=_required_text(plugin, "version"),
        qc_api=qc_api,
        origin=origin,
        required_access=required_access,
        description=_required_text(plugin, "description"),
        long_description=_required_text(plugin, "long_description"),
        param_schema=parameter_schema,
        unit_settings=unit_settings,
        overview=_validated_overview_metadata(
            plugin,
            name,
            display_name,
            parameter_schema,
        ),
        author=(
            str(getattr(plugin, "author")).strip()
            if getattr(plugin, "author", None)
            else None
        ),
        module=getattr(plugin, "__module__", None),
        entrypoint=entrypoint,
        distribution=distribution,
    )
    return RegisteredPlugin(plugin=plugin, metadata=metadata)


def register(
    plugin: QCPlugin,
    *,
    origin: str = "runtime",
    entrypoint: str | None = None,
    distribution: str | None = None,
) -> None:
    """Validate and register one plugin without silently replacing a name."""
    with _REGISTRY_LOCK:
        if _REGISTRATION_BLOCK_DEPTH:
            raise PluginRegistrationError(
                "side_effect_registration",
                "Entry-point plugins must return their plugin object without registering it",
            )
    registration = validate_plugin(
        plugin,
        origin=origin,
        entrypoint=entrypoint,
        distribution=distribution,
    )
    with _REGISTRY_LOCK:
        if _REGISTRATION_BLOCK_DEPTH:
            raise PluginRegistrationError(
                "side_effect_registration",
                "Entry-point plugins must return their plugin object without registering it",
            )
        existing = _REGISTRY.get(registration.metadata.name)
        if existing is not None:
            if existing.plugin is plugin and existing.metadata == registration.metadata:
                return
            raise PluginRegistrationError(
                "duplicate_plugin",
                f"Plugin '{registration.metadata.name}' is already registered",
            )
        _REGISTRY[registration.metadata.name] = registration


@contextmanager
def block_registration_side_effects():
    """Prevent entry-point imports from mutating the live registry."""
    global _REGISTRATION_BLOCK_DEPTH
    with _REGISTRY_LOCK:
        _REGISTRATION_BLOCK_DEPTH += 1
    try:
        yield
    finally:
        with _REGISTRY_LOCK:
            _REGISTRATION_BLOCK_DEPTH -= 1


def replace_all(registrations: Iterable[RegisteredPlugin]) -> None:
    """Atomically publish a complete, already validated registry snapshot."""
    replacement: dict[str, RegisteredPlugin] = {}
    for registration in registrations:
        name = registration.metadata.name
        if name in replacement:
            raise PluginRegistrationError(
                "duplicate_plugin", f"Plugin '{name}' appears more than once"
            )
        replacement[name] = registration
    with _REGISTRY_LOCK:
        _REGISTRY.clear()
        _REGISTRY.update(replacement)


def get(name: str) -> QCPlugin | None:
    with _REGISTRY_LOCK:
        registration = _REGISTRY.get(name)
        return registration.plugin if registration is not None else None


def get_registration(name: str) -> RegisteredPlugin | None:
    with _REGISTRY_LOCK:
        return _REGISTRY.get(name)


def all_plugins() -> dict[str, QCPlugin]:
    with _REGISTRY_LOCK:
        return {
            name: registration.plugin
            for name, registration in sorted(_REGISTRY.items())
        }


def all_registrations() -> dict[str, RegisteredPlugin]:
    with _REGISTRY_LOCK:
        return dict(sorted(_REGISTRY.items()))


def clear() -> None:
    """Clear the registry in tests. Production reloads use atomic replacement."""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()
