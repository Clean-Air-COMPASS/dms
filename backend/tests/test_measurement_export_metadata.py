from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
from models import Device, ExternalAPI, Measurement, Parameter, Sensor, Unit
from services.device_locations import set_device_location


def test_measurement_download_metadata_exposes_export_fields_and_ids():
    session = SessionLocal()
    try:
        unit = session.scalar(select(Unit).where(Unit.code == "ug_m3"))
        parameter = session.scalar(select(Parameter).where(Parameter.code == "pm25"))
        assert unit is not None
        assert parameter is not None

        source = ExternalAPI(
            name=f"Export Test Source {uuid.uuid4()}",
            provider_code=f"export-test-{uuid.uuid4()}",
            base_url="https://provider.example",
            params={},
            enabled=True,
        )
        session.add(source)
        session.flush()

        device = Device(
            name=f"Internal Device {uuid.uuid4()}",
            friendly_name='Friendly "Export, Station"',
            external_api_id=source.external_api_id,
            acquisition_path="export_test",
            hardware_provider_name="Reference Hardware",
            provider_url="https://provider.example/device/1",
            contributor_name="Monitoring Team",
            contributor_url="https://example.org/monitoring-team",
            license_code="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            timezone="UTC",
        )
        session.add(device)
        session.flush()
        set_device_location(session, device, latitude=38.5, longitude=-122.8)

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            external_sensor_id="provider-sensor-1",
        )
        session.add(sensor)
        session.flush()
        observed_at = datetime.now(timezone.utc)
        measurement = Measurement(
            sensor_id=sensor.sensor_id,
            value=12.5,
            observed_at=observed_at,
            is_valid=True,
        )
        session.add(measurement)
        session.commit()

        client = TestClient(app)
        latest_response = client.get(
            "/measurements/pm25/latest",
            params={"device_id": device.device_id, "since": (observed_at - timedelta(minutes=1)).isoformat()},
        )
        assert latest_response.status_code == 200, latest_response.text
        latest = latest_response.json()[0]
        assert latest["measurement_id"] == measurement.measurement_id
        assert latest["sensor_id"] == sensor.sensor_id
        assert latest["external_sensor_id"] == "provider-sensor-1"
        assert latest["parameter"] == "pm25"
        assert latest["parameter_name"] == "PM2.5"
        assert latest["unit"] == unit.symbol
        assert latest["device"] == {
            "device_id": device.device_id,
            "name": device.name,
            "friendly_name": device.friendly_name,
            "latitude": 38.5,
            "longitude": -122.8,
            "network": source.name,
            "timezone": "UTC",
            "external_api": {"name": source.name},
            "data_attribution": {
                "acquisition_path": "export_test",
                "data_provider_name": source.name,
                "hardware_provider_name": "Reference Hardware",
                "provider_url": "https://provider.example/device/1",
                "contributor_name": "Monitoring Team",
                "contributor_url": "https://example.org/monitoring-team",
                "license_code": "CC-BY-4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "license_share_alike": None,
            },
        }

        history_response = client.get(
            f"/sensors/{sensor.sensor_id}/history",
            params={
                "aggregation": "raw",
                "start": (observed_at - timedelta(minutes=1)).isoformat(),
                "end": (observed_at + timedelta(minutes=1)).isoformat(),
            },
        )
        assert history_response.status_code == 200, history_response.text
        history = history_response.json()
        assert history["device_id"] == device.device_id
        assert history["device_friendly_name"] == device.friendly_name
        assert history["latitude"] == 38.5
        assert history["longitude"] == -122.8
        assert history["data"][0]["measurement_id"] == measurement.measurement_id
        assert history["data_attribution"]["data_provider_name"] == source.name
    finally:
        session.rollback()
        session.close()
