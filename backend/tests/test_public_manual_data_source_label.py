from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
from models import Device, ExternalAPI, Measurement, Parameter, Sensor, Unit


def _ensure(session, model, code_field: str, code: str, **fields):
    row = session.scalar(select(model).where(getattr(model, code_field) == code))
    if row:
        return row
    obj = model(**{code_field: code}, **fields)
    session.add(obj)
    session.flush()
    return obj


def test_public_endpoints_return_other_for_manual_data_sources():
    session = SessionLocal()
    try:
        unit = _ensure(session, Unit, "code", "ug_m3", symbol="ug/m3", name="Micrograms per cubic meter")
        pm25 = _ensure(session, Parameter, "code", "pm25", display_name="PM2.5", default_unit_id=unit.unit_id)
        openaq = _ensure(
            session,
            ExternalAPI,
            "name",
            f"OpenAQ-{uuid.uuid4()}",
            base_url="https://api.openaq.org",
            params={},
            enabled=True,
        )

        device = Device(
            name=f"manual-device-{uuid.uuid4()}",
            external_api_id=openaq.external_api_id,
            manual_data_source_name="Neighborhood Lab",
            timezone="America/Los_Angeles",
        )
        session.add(device)
        from services.device_locations import set_device_location

        set_device_location(
            session, device, latitude=38.44, longitude=-122.71
        )

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=pm25.parameter_id,
            unit_id=unit.unit_id,
        )
        session.add(sensor)
        session.flush()

        # The unbounded latest endpoint applies its default result limit after
        # ordering by observation time. Use the same current-time convention as
        # the other latest-endpoint tests so this row cannot age out behind
        # unrelated measurements in the shared test database.
        observed_at = datetime.now(timezone.utc)
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=12.3,
                observed_at=observed_at,
                is_valid=True,
            )
        )
        session.commit()

        client = TestClient(app)

        devices_response = client.get("/devices")
        assert devices_response.status_code == 200, devices_response.text
        devices_payload = devices_response.json()
        matching_device = next(row for row in devices_payload if row["device_id"] == device.device_id)
        assert matching_device["network"] == "Other"

        latest_param_response = client.get("/measurements/pm25/latest", params={"device_id": device.device_id})
        assert latest_param_response.status_code == 200, latest_param_response.text
        latest_param_payload = latest_param_response.json()
        assert latest_param_payload[0]["device"]["network"] == "Other"
        assert latest_param_payload[0]["device"]["external_api"]["name"] == "Other"

        other_filter_response = client.get(
            "/measurements/pm25/latest",
            params={"external_api_name": "other"},
        )
        assert other_filter_response.status_code == 200, other_filter_response.text
        other_filter_payload = [
            row for row in other_filter_response.json()
            if row["device"] and row["device"]["device_id"] == device.device_id
        ]
        assert other_filter_payload
        assert other_filter_payload[0]["device"]["external_api"]["name"] == "Other"

        latest_all_response = client.get("/measurements/latest")
        assert latest_all_response.status_code == 200, latest_all_response.text
        latest_all_payload = [
            row for row in latest_all_response.json()
            if row["device"] and row["device"]["device_id"] == device.device_id
        ]
        assert latest_all_payload
        assert latest_all_payload[0]["device"]["network"] == "Other"
        assert latest_all_payload[0]["device"]["external_api"]["name"] == "Other"

        history_response = client.get(f"/sensors/{sensor.sensor_id}/history", params={"aggregate": "raw"})
        assert history_response.status_code == 200, history_response.text
        history_payload = history_response.json()
        assert history_payload["external_api"]["name"] == "Other"

        sources_response = client.get("/data-sources")
        assert sources_response.status_code == 200, sources_response.text
        source_filter_values = {row["filter_value"] for row in sources_response.json()}
        assert "other" in source_filter_values
        assert openaq.name.lower() in source_filter_values
    finally:
        session.rollback()
        session.close()

def test_disabled_source_with_existing_managed_devices_remains_filterable():
    client = TestClient(app)
    from db import SessionLocal
    from models import ExternalAPI, Device
    import uuid
    with SessionLocal() as session:
        name = f'Historical source {uuid.uuid4().hex}'
        source = ExternalAPI(name=name, provider_code=name, enabled=False, params={})
        empty = ExternalAPI(name=f'Empty {name}', provider_code=f'empty-{name}', enabled=False, params={})
        session.add_all([source, empty])
        session.flush()
        session.add(Device(name='Historical station', external_api_id=source.external_api_id, external_id='historic'))
        session.commit()
    names = {row['name'] for row in client.get('/data-sources').json()}
    assert name in names
    assert f'Empty {name}' not in names
