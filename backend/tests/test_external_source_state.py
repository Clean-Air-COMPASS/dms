from __future__ import annotations

import models
from services.external_sources import (
    RunnableReason,
    derive_external_source_state,
)


def _source(provider_code: str, *, enabled: bool, api_key: str | None = None):
    return models.ExternalAPI(
        provider_code=provider_code,
        name=provider_code,
        params={},
        enabled=enabled,
        api_key=api_key,
    )


def test_disabled_source_reports_configuration_separately_from_runtime_intent():
    without_key = derive_external_source_state(
        _source("openaq", enabled=False), {}
    )
    assert without_key.is_configured is False
    assert without_key.is_runnable is False
    assert without_key.runnable_reason == RunnableReason.DISABLED

    with_key = derive_external_source_state(
        _source("openaq", enabled=False, api_key="stored-key"), {}
    )
    assert with_key.is_configured is True
    assert with_key.is_runnable is False
    assert with_key.runnable_reason == RunnableReason.DISABLED


def test_enabled_intent_persists_when_credential_is_added_or_cleared():
    source = _source("openaq", enabled=True)
    missing = derive_external_source_state(source, {})
    assert missing.runnable_reason == RunnableReason.CONFIGURATION_REQUIRED

    source.api_key = "stored-key"
    ready = derive_external_source_state(source, {})
    assert source.enabled is True
    assert ready.is_configured is True
    assert ready.is_runnable is True
    assert ready.runnable_reason == RunnableReason.READY

    source.api_key = None
    cleared = derive_external_source_state(source, {})
    assert source.enabled is True
    assert cleared.is_configured is False
    assert cleared.is_runnable is False
    assert cleared.runnable_reason == RunnableReason.CONFIGURATION_REQUIRED


def test_environment_credential_is_authoritative_configuration():
    source = _source("airgradient", enabled=True)
    state = derive_external_source_state(
        source, {"AIRGRADIENT_API_KEY": "environment-key"}
    )
    assert state.is_configured is True
    assert state.is_runnable is True


def test_purpleair_is_ready_without_a_normal_production_opt_in():
    source = _source("purpleair", enabled=True, api_key="stored-key")
    ready = derive_external_source_state(
        source,
        {"COMPASSAQ_ENV": "development", "ENABLE_PAID_API_IMPORTS": "false"},
    )
    assert ready.is_configured is True
    assert ready.is_runnable is True
    assert ready.runnable_reason == RunnableReason.READY

    operator_disabled = derive_external_source_state(
        source,
        {"COMPASSAQ_ENV": "development", "DISABLE_PAID_API_REQUESTS": "true"},
    )
    assert operator_disabled.is_runnable is False
    assert (
        operator_disabled.runnable_reason
        == RunnableReason.PAID_PROVIDER_REQUESTS_DISABLED
    )

    test_environment = derive_external_source_state(
        source,
        {"COMPASSAQ_ENV": "test", "ENABLE_PAID_API_IMPORTS": "true"},
    )
    assert test_environment.is_runnable is False
    assert (
        test_environment.runnable_reason
        == RunnableReason.PAID_PROVIDER_REQUESTS_DISABLED
    )


def test_unknown_provider_is_explicitly_unsupported_only_when_enabled():
    disabled = models.ExternalAPI(name="Custom", params={}, enabled=False)
    assert (
        derive_external_source_state(disabled, {}).runnable_reason
        == RunnableReason.DISABLED
    )
    disabled.enabled = True
    assert (
        derive_external_source_state(disabled, {}).runnable_reason
        == RunnableReason.UNSUPPORTED_PROVIDER
    )
