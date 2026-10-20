"""Public Map attribution uses stored facts, including provider-only devices."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.main import app
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db import get_session
from models import Base, Device, ExternalAPI
from services.data_attribution import serialize_device_data_attribution


@pytest.mark.parametrize("provider", ["PurpleAir", "OpenAQ"])
def test_public_devices_preserve_provider_without_optional_attribution(provider, tmp_path):
    # Independent fixture: prior tests may already have seeded built-in names.
    engine = create_engine(f"sqlite:///{tmp_path / 'attribution.sqlite'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        source = ExternalAPI(name=provider, provider_code=f"map-test-{provider}", base_url="https://example.org")
        session.add(source)
        session.flush()
        device = Device(name=f"Synthetic {provider} attribution", external_api_id=source.external_api_id)
        session.add(device)
        session.commit()
        app.dependency_overrides[get_session] = lambda: session
        try:
            response = TestClient(app).get("/devices")
        finally:
            app.dependency_overrides.pop(get_session, None)
        assert response.status_code == 200
        result = next(item for item in response.json() if item["device_id"] == device.device_id)
        assert result["data_attribution"]["data_provider_name"] == provider
        for field in ("contributor_name", "contributor_url", "provider_url", "license_code", "license_url"):
            assert result["data_attribution"][field] is None
    engine.dispose()


@pytest.mark.parametrize("provider", ["PurpleAir", "OpenAQ"])
def test_serialization_preserves_optional_stored_facts(provider):
    device = SimpleNamespace(
        acquisition_path="openaq" if provider == "OpenAQ" else "unspecified",
        contributor_name="Synthetic Monitoring Organization",
        contributor_url="https://example.org/contributor",
        provider_url="https://example.org/device/123",
        license_code="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        api_key="synthetic-secret-not-public",
    )
    result = serialize_device_data_attribution(device, provider)
    assert result["data_provider_name"] == provider
    for field in ("contributor_name", "contributor_url", "provider_url", "license_code", "license_url"):
        assert result[field] == getattr(device, field)
    assert "synthetic-secret-not-public" not in str(result)


def test_no_attribution_is_invented_for_an_unknown_source():
    assert serialize_device_data_attribution(SimpleNamespace(), None) is None
