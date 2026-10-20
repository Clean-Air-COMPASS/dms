"""Built-in external-source definitions and derived execution state.

`ExternalAPI.enabled` records administrator intent. Configuration and runtime
eligibility are derived here so API, scheduler, and manual import paths apply
the same rules without storing redundant status fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

import models


@dataclass(frozen=True)
class BuiltInExternalSource:
    provider_code: str
    name: str
    base_url: str
    description: str
    default_params: dict
    task: str
    credential_environment_variable: str
    requires_credential: bool = True


BUILT_IN_EXTERNAL_SOURCES = (
    BuiltInExternalSource(
        provider_code="demo",
        name="Demo Data",
        base_url="",
        description="Clearly fake air-quality observations from an offline demonstration fixture. Not a real monitoring location.",
        default_params={},
        task="demo_import",
        credential_environment_variable="",
        requires_credential=False,
    ),
    BuiltInExternalSource(
        provider_code="openaq",
        name="OpenAQ",
        base_url="https://api.openaq.org",
        description="Built-in source: OpenAQ",
        default_params={},
        task="openaq_import",
        credential_environment_variable="OPENAQ_API_KEY",
    ),
    BuiltInExternalSource(
        provider_code="purpleair",
        name="PurpleAir",
        base_url="https://api.purpleair.com/v1/sensors",
        description="Built-in source: PurpleAir",
        default_params={"max_lookback_hours": 24},
        task="purpleair_import",
        credential_environment_variable="PURPLEAIR_API_KEY",
    ),
    BuiltInExternalSource(
        provider_code="airgradient",
        name="AirGradient",
        base_url="https://api.airgradient.com/public/api",
        description="Built-in source: AirGradient",
        default_params={},
        task="airgradient_import",
        credential_environment_variable="AIRGRADIENT_API_KEY",
        requires_credential=False,
    ),
)

_BUILT_IN_BY_CODE = {
    definition.provider_code: definition for definition in BUILT_IN_EXTERNAL_SOURCES
}
_BUILT_IN_BY_TASK = {
    definition.task: definition for definition in BUILT_IN_EXTERNAL_SOURCES
}


class RunnableReason(str, Enum):
    DISABLED = "disabled"
    CONFIGURATION_REQUIRED = "configuration_required"
    PAID_PROVIDER_REQUESTS_DISABLED = "paid_provider_requests_disabled"
    READY = "ready"
    UNSUPPORTED_PROVIDER = "unsupported_provider"


@dataclass(frozen=True)
class ExternalSourceState:
    is_configured: bool
    is_runnable: bool
    runnable_reason: RunnableReason


class ExternalSourceNotRunnable(RuntimeError):
    def __init__(self, state: ExternalSourceState):
        self.state = state
        super().__init__(state.runnable_reason.value)


def _environment_flag(
    environment: Mapping[str, str], name: str, *, default: bool = False
) -> bool:
    raw_value = environment.get(name, "true" if default else "false")
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def credential_for_source(
    source: models.ExternalAPI,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Return the stored credential or the provider's configured environment value."""
    if source.api_key and source.api_key.strip():
        return source.api_key.strip()

    definition = _BUILT_IN_BY_CODE.get(source.provider_code or "")
    if definition is None:
        return None

    environment_values = environment if environment is not None else os.environ
    environment_credential = environment_values.get(
        definition.credential_environment_variable, ""
    ).strip()
    return environment_credential or None


def derive_external_source_state(
    source: models.ExternalAPI,
    environment: Mapping[str, str] | None = None,
) -> ExternalSourceState:
    """Derive configured and runnable state from authoritative source fields."""
    environment_values = environment if environment is not None else os.environ
    definition = _BUILT_IN_BY_CODE.get(source.provider_code or "")

    if definition is None:
        if not source.enabled:
            return ExternalSourceState(
                is_configured=False,
                is_runnable=False,
                runnable_reason=RunnableReason.DISABLED,
            )
        return ExternalSourceState(
            is_configured=False,
            is_runnable=False,
            runnable_reason=RunnableReason.UNSUPPORTED_PROVIDER,
        )

    return derive_builtin_external_source_state(
        provider_code=definition.provider_code,
        enabled=bool(source.enabled),
        stored_credential_configured=bool(source.api_key and source.api_key.strip()),
        environment=environment_values,
        authenticated_locations_requested=(
            source.provider_code == "airgradient"
            and (source.params or {}).get("import_authenticated_locations") is True
        ),
    )


def derive_builtin_external_source_state(
    *,
    provider_code: str,
    enabled: bool,
    stored_credential_configured: bool,
    environment: Mapping[str, str] | None = None,
    authenticated_locations_requested: bool = False,
) -> ExternalSourceState:
    """Derive built-in state without requiring the credential value itself."""
    environment_values = environment if environment is not None else os.environ
    definition = _BUILT_IN_BY_CODE.get(provider_code)
    if definition is None:
        return ExternalSourceState(
            is_configured=False,
            is_runnable=False,
            runnable_reason=(
                RunnableReason.UNSUPPORTED_PROVIDER
                if enabled
                else RunnableReason.DISABLED
            ),
        )
    environment_credential_configured = bool(
        environment_values.get(definition.credential_environment_variable, "").strip()
    )
    is_configured = (
        (not definition.requires_credential and not authenticated_locations_requested)
        or stored_credential_configured or environment_credential_configured
    )
    if not enabled:
        return ExternalSourceState(
            is_configured=is_configured,
            is_runnable=False,
            runnable_reason=RunnableReason.DISABLED,
        )
    if not is_configured:
        return ExternalSourceState(
            is_configured=False,
            is_runnable=False,
            runnable_reason=RunnableReason.CONFIGURATION_REQUIRED,
        )
    if provider_code == "purpleair" and (
        environment_values.get("COMPASSAQ_ENV", "").strip().lower() == "test"
        or _environment_flag(environment_values, "DISABLE_PAID_API_REQUESTS")
    ):
        return ExternalSourceState(
            is_configured=True,
            is_runnable=False,
            runnable_reason=RunnableReason.PAID_PROVIDER_REQUESTS_DISABLED,
        )
    return ExternalSourceState(
        is_configured=True,
        is_runnable=True,
        runnable_reason=RunnableReason.READY,
    )


def built_in_definition_for_task(task: str) -> BuiltInExternalSource | None:
    return _BUILT_IN_BY_TASK.get(task)


def is_builtin_external_source(source: models.ExternalAPI) -> bool:
    """Return whether a source is one of CompassAQ's required definitions."""
    return (source.provider_code or "") in _BUILT_IN_BY_CODE


def source_requires_credential(source: models.ExternalAPI) -> bool:
    definition = _BUILT_IN_BY_CODE.get(source.provider_code or "")
    return definition.requires_credential if definition else True


def source_for_task(
    session: Session, task: str, *, for_update: bool = False
) -> models.ExternalAPI | None:
    definition = built_in_definition_for_task(task)
    if definition is None:
        return None
    statement = select(models.ExternalAPI).where(
        models.ExternalAPI.provider_code == definition.provider_code
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def require_task_source_runnable(
    session: Session,
    task: str,
    environment: Mapping[str, str] | None = None,
    *,
    for_update: bool = False,
) -> models.ExternalAPI:
    source = source_for_task(session, task, for_update=for_update)
    if source is None:
        raise ExternalSourceNotRunnable(
            ExternalSourceState(
                is_configured=False,
                is_runnable=False,
                runnable_reason=RunnableReason.UNSUPPORTED_PROVIDER,
            )
        )
    state = derive_external_source_state(source, environment)
    if not state.is_runnable:
        raise ExternalSourceNotRunnable(state)
    return source


def ensure_builtin_external_apis(session: Session) -> list[models.ExternalAPI]:
    """Create missing required provider definitions without overwriting edits."""
    ensured_sources: list[models.ExternalAPI] = []
    for definition in BUILT_IN_EXTERNAL_SOURCES:
        source = session.scalar(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == definition.provider_code
            )
        )
        if source is None:
            source = models.ExternalAPI(
                provider_code=definition.provider_code,
                name=definition.name,
                base_url=definition.base_url,
                description=definition.description,
                api_key=None,
                params=dict(definition.default_params),
                enabled=False,
            )
            session.add(source)
        ensured_sources.append(source)
    session.flush()
    return ensured_sources
