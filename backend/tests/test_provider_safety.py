from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import models
from jobs import import_runner
from services.external_sources import ExternalSourceNotRunnable
from services.provider_safety import (
    ProviderSafetyDenialCode,
    ProviderSafetyDenied,
    assert_paid_provider_http_authorized,
    paid_provider_request_scope,
    require_paid_provider_authorization,
)


@pytest.fixture()
def safety_session(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'safety.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add_all([
            models.ExternalAPI(provider_code="purpleair", name="PurpleAir", params={}, enabled=True, api_key="test-key"),
            models.SystemSettings(is_system_setup_complete=False),
        ])
        session.commit()
        yield session


def test_test_environment_blocks_before_other_paid_provider_controls(safety_session):
    with pytest.raises(ProviderSafetyDenied) as exc_info:
        require_paid_provider_authorization(
            safety_session, "PurpleAir", explicit_manual_authorization=True
        )
    assert exc_info.value.code == ProviderSafetyDenialCode.TEST_ENVIRONMENT_EXTERNAL_HTTP_BLOCKED


def test_operator_kill_switch_source_state_and_credential_are_required(
    safety_session, monkeypatch
):
    monkeypatch.setenv("COMPASSAQ_ENV", "development")

    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "true")
    with pytest.raises(ProviderSafetyDenied) as disabled:
        require_paid_provider_authorization(
            safety_session, "PurpleAir", explicit_manual_authorization=True
        )
    assert disabled.value.code == ProviderSafetyDenialCode.PAID_API_REQUESTS_DISABLED

    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "false")
    provider = safety_session.scalar(select(models.ExternalAPI))
    provider.enabled = False
    safety_session.commit()
    with pytest.raises(ProviderSafetyDenied) as inactive:
        require_paid_provider_authorization(
            safety_session, "PurpleAir", explicit_manual_authorization=True
        )
    assert inactive.value.code == ProviderSafetyDenialCode.PROVIDER_SOURCE_DISABLED

    provider.enabled = True
    provider.api_key = "stored-key"
    safety_session.commit()
    authorization = require_paid_provider_authorization(
        safety_session, "PurpleAir"
    )
    with paid_provider_request_scope(authorization):
        assert_paid_provider_http_authorized("PurpleAir")


def test_schedule_context_labels_execution_without_adding_an_authorization_gate(
    safety_session, monkeypatch
):
    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "false")
    schedule = models.JobSchedule(
        task="purpleair_import", cron_expr="0 * * * *", enabled=False
    )
    safety_session.add(schedule)
    safety_session.commit()

    authorization = require_paid_provider_authorization(
        safety_session, "PurpleAir", scheduled_job=schedule
    )
    assert authorization.execution_mode == "scheduled"


def test_new_external_source_defaults_disabled(safety_session):
    from api.routes.admin.external_apis import ExternalAPICreateIn, create_external_api

    existing = safety_session.scalar(select(models.ExternalAPI))
    safety_session.delete(existing)
    safety_session.commit()
    created = create_external_api(
        ExternalAPICreateIn(name="PurpleAir", params={}), safety_session
    )
    assert created.enabled is False


def test_scheduler_gate_blocks_before_subprocess(safety_session, monkeypatch):
    Session = sessionmaker(bind=safety_session.bind)
    monkeypatch.setattr(import_runner, "SessionLocal", Session)
    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "true")
    schedule = models.JobSchedule(
        task="purpleair_import", cron_expr="0 * * * *", enabled=True
    )
    safety_session.add(schedule)
    safety_session.commit()

    monkeypatch.setattr(
        import_runner.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("subprocess must not start"),
    )
    with pytest.raises(ExternalSourceNotRunnable) as exc_info:
        import_runner.run_importer(
            1,
            {},
            "purpleair_import",
            job_schedule_id=schedule.job_schedule_id,
        )
    assert exc_info.value.state.runnable_reason.value == "paid_provider_requests_disabled"


def test_purpleair_client_http_boundary_requires_request_scope():
    from sources.purpleair.purpleair_client import APIClient

    class FailIfCalled:
        def get(self, *args, **kwargs):
            pytest.fail("HTTP client must not be reached")

    client = APIClient(FailIfCalled())
    with pytest.raises(ProviderSafetyDenied) as exc_info:
        client.get("https://invalid.example")
    assert exc_info.value.code == ProviderSafetyDenialCode.EXPLICIT_PAID_API_AUTHORIZATION_MISSING


def test_purpleair_api_paths_block_before_http_or_subprocess(safety_session, monkeypatch):
    from fastapi import HTTPException
    from api.routes import setup
    from api.routes.admin import devices, imports
    from sources.purpleair import importer

    Session = sessionmaker(bind=safety_session.bind)

    def fail(*args, **kwargs):
        pytest.fail("provider HTTP or subprocess must not be reached")

    monkeypatch.setattr(devices.requests, "get", fail)
    with pytest.raises(HTTPException) as lookup_error:
        devices.lookup_purpleair_sensor(
            {"sensor_index": "123", "allow_paid_api": True}, safety_session
        )
    assert lookup_error.value.detail["code"] == "test_environment_external_http_blocked"

    assert not hasattr(setup, "verify_data_source_api_key")

    monkeypatch.setattr(imports, "SessionLocal", Session)
    with pytest.raises(HTTPException) as import_error:
        imports.run_import({"source": "purpleair", "allow_paid_api": True})
    assert import_error.value.detail["code"] == "paid_provider_requests_disabled"

    monkeypatch.setattr(importer, "SessionLocal", Session)
    monkeypatch.setattr(importer, "_run_authorized_import", fail)
    with pytest.raises(ProviderSafetyDenied) as importer_error:
        importer.run_import()
    assert importer_error.value.code == ProviderSafetyDenialCode.TEST_ENVIRONMENT_EXTERNAL_HTTP_BLOCKED


def test_autouse_network_guard_blocks_requests_and_httpx():
    import httpx
    import requests

    with pytest.raises(RuntimeError, match="Requests external HTTP"):
        requests.get("https://invalid.example")
    with pytest.raises(RuntimeError, match="HTTPX external HTTP"):
        with httpx.Client() as client:
            client.get("https://invalid.example")


@pytest.mark.parametrize(
    ("url", "provider_seam"),
    (
        ("https://api.purpleair.com/v1/sensors", "PurpleAir"),
        ("https://api.openaq.org/v3/sensors", "OpenAQ"),
        ("https://api.airgradient.com/public/api/v1", "AirGradient"),
        ("https://invalid.example/data", "arbitrary external"),
    ),
)
def test_offline_network_guard_identifies_provider_seams(url, provider_seam):
    import requests

    with pytest.raises(RuntimeError, match=provider_seam):
        requests.get(url)
