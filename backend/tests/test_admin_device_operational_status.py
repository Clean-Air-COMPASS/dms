from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
import models
from services.device_operational_status import (
    derive_device_operational_status,
    device_freshness_threshold_seconds,
)


client = TestClient(app)


@pytest.fixture(scope="module")
def operational_devices() -> dict[str, object]:
    evaluated_at = datetime.now(timezone.utc).replace(microsecond=0)

    with SessionLocal() as session:
        source = models.ExternalAPI(
            name="Operational Status Test Source",
            base_url="https://operational-status.example.test",
            params={},
        )
        session.add(source)
        session.flush()

        recent_device = models.Device(
            name="Operational Status Recent Device",
            external_id="operational-recent",
            external_api_id=source.external_api_id,
        )
        stale_device = models.Device(
            name="Operational Status Stale Device",
            external_id="operational-stale",
            external_api_id=source.external_api_id,
        )
        unknown_device = models.Device(
            name="Operational Status Unknown Device",
            external_id="operational-unknown",
            external_api_id=source.external_api_id,
        )
        fallback_device = models.Device(
            name="Operational Status Fallback Device",
            external_id="operational-fallback",
            external_api_id=source.external_api_id,
        )
        session.add_all([
            recent_device,
            stale_device,
            unknown_device,
            fallback_device,
        ])
        session.flush()

        latest_sensor = models.Sensor(
            device_id=recent_device.device_id,
            external_sensor_id="operational-latest-sensor",
            expected_frequency_seconds=3600,
        )
        older_sensor = models.Sensor(
            device_id=recent_device.device_id,
            external_sensor_id="operational-older-sensor",
            expected_frequency_seconds=120,
        )
        stale_sensor = models.Sensor(
            device_id=stale_device.device_id,
            external_sensor_id="operational-stale-sensor",
            expected_frequency_seconds=120,
        )
        unknown_sensor = models.Sensor(
            device_id=unknown_device.device_id,
            external_sensor_id="operational-unknown-sensor",
            expected_frequency_seconds=3600,
        )
        fallback_sensor = models.Sensor(
            device_id=fallback_device.device_id,
            external_sensor_id="operational-fallback-sensor",
            expected_frequency_seconds=None,
        )
        session.add_all([
            latest_sensor,
            older_sensor,
            stale_sensor,
            unknown_sensor,
            fallback_sensor,
        ])
        session.flush()

        newest_observation = evaluated_at - timedelta(hours=1)
        session.add_all([
            models.Measurement(
                sensor_id=latest_sensor.sensor_id,
                value=10.0,
                observed_at=newest_observation,
                created_at=evaluated_at,
            ),
            models.Measurement(
                sensor_id=latest_sensor.sensor_id,
                value=9.0,
                observed_at=evaluated_at - timedelta(days=2),
                created_at=evaluated_at,
            ),
            models.Measurement(
                sensor_id=older_sensor.sensor_id,
                value=8.0,
                observed_at=evaluated_at - timedelta(hours=2),
                created_at=evaluated_at,
            ),
            models.Measurement(
                sensor_id=stale_sensor.sensor_id,
                value=7.0,
                observed_at=evaluated_at - timedelta(hours=7),
                # A recent insert time must not make an old observation active.
                created_at=evaluated_at,
            ),
            models.Measurement(
                sensor_id=fallback_sensor.sensor_id,
                value=6.0,
                observed_at=evaluated_at - timedelta(hours=47),
                created_at=evaluated_at,
            ),
        ])
        session.commit()

        return {
            "evaluated_at": evaluated_at,
            "newest_observation": newest_observation,
            "source_name": source.name,
            "recent_device_id": recent_device.device_id,
            "stale_device_id": stale_device.device_id,
            "unknown_device_id": unknown_device.device_id,
            "fallback_device_id": fallback_device.device_id,
            "latest_sensor_id": latest_sensor.sensor_id,
        }


def _records_by_id(response) -> dict[int, dict]:
    assert response.status_code == 200, response.text
    return {record["device_id"]: record for record in response.json()}


def _parse_api_datetime(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def test_frequency_aware_status_threshold_and_fallback_are_explicit():
    evaluated_at = datetime(2026, 8, 26, 12, tzinfo=timezone.utc)

    assert device_freshness_threshold_seconds(120) == 6 * 60 * 60
    assert device_freshness_threshold_seconds(3600) == 6 * 60 * 60
    assert device_freshness_threshold_seconds(24 * 60 * 60) == 72 * 60 * 60
    assert device_freshness_threshold_seconds(None) == 48 * 60 * 60
    assert derive_device_operational_status(None, 3600, evaluated_at=evaluated_at) == "unknown"
    assert derive_device_operational_status(
        evaluated_at - timedelta(hours=6), 120, evaluated_at=evaluated_at
    ) == "active"
    assert derive_device_operational_status(
        evaluated_at - timedelta(hours=6, seconds=1),
        120,
        evaluated_at=evaluated_at,
    ) == "inactive"
    assert derive_device_operational_status(
        evaluated_at - timedelta(hours=47), None, evaluated_at=evaluated_at
    ) == "active"
    assert derive_device_operational_status(
        evaluated_at - timedelta(hours=49), None, evaluated_at=evaluated_at
    ) == "inactive"


def test_list_returns_recent_stale_unknown_and_frequency_fallback_statuses(
    admin_auth_headers,
    operational_devices,
):
    response = client.get(
        "/admin/devices?name=Operational%20Status",
        headers=admin_auth_headers,
    )
    records = _records_by_id(response)

    assert records[operational_devices["recent_device_id"]]["status"] == "active"
    assert records[operational_devices["stale_device_id"]]["status"] == "inactive"
    assert records[operational_devices["unknown_device_id"]]["status"] == "unknown"
    assert records[operational_devices["unknown_device_id"]]["last_seen_at"] is None
    assert records[operational_devices["fallback_device_id"]]["status"] == "active"


def test_last_seen_is_newest_observation_across_sensors_without_duplicate_devices(
    admin_auth_headers,
    operational_devices,
):
    response = client.get(
        "/admin/devices?name=Operational%20Status%20Recent%20Device",
        headers=admin_auth_headers,
    )
    records = response.json()

    assert response.status_code == 200, response.text
    assert len(records) == 1
    assert _parse_api_datetime(records[0]["last_seen_at"]) == operational_devices["newest_observation"]


def test_old_observation_is_inactive_even_when_measurement_was_created_recently(
    admin_auth_headers,
    operational_devices,
):
    response = client.get(
        "/admin/devices?name=Operational%20Status%20Stale%20Device",
        headers=admin_auth_headers,
    )
    record = response.json()[0]

    assert response.status_code == 200, response.text
    assert record["status"] == "inactive"
    assert _parse_api_datetime(record["last_seen_at"]) < operational_devices["evaluated_at"] - timedelta(hours=6)


@pytest.mark.parametrize(
    ("status", "included_key", "excluded_keys"),
    [
        ("active", "recent_device_id", ("stale_device_id", "unknown_device_id")),
        ("inactive", "stale_device_id", ("recent_device_id", "unknown_device_id")),
        ("unknown", "unknown_device_id", ("recent_device_id", "stale_device_id")),
    ],
)
def test_status_filters_use_returned_status_semantics(
    admin_auth_headers,
    operational_devices,
    status,
    included_key,
    excluded_keys,
):
    response = client.get(
        f"/admin/devices?name=Operational%20Status&status={status}",
        headers=admin_auth_headers,
    )
    records = _records_by_id(response)

    assert operational_devices[included_key] in records
    for excluded_key in excluded_keys:
        assert operational_devices[excluded_key] not in records
    assert all(record["status"] == status for record in records.values())


def test_invalid_status_filter_is_rejected_cleanly(admin_auth_headers):
    response = client.get(
        "/admin/devices?status=error",
        headers=admin_auth_headers,
    )

    assert response.status_code == 422


def test_device_detail_uses_same_status_and_last_seen_contract(
    admin_auth_headers,
    operational_devices,
):
    device_id = operational_devices["recent_device_id"]
    list_record = _records_by_id(client.get(
        "/admin/devices?name=Operational%20Status%20Recent%20Device",
        headers=admin_auth_headers,
    ))[device_id]
    detail_response = client.get(
        f"/admin/devices/{device_id}",
        headers=admin_auth_headers,
    )

    assert detail_response.status_code == 200, detail_response.text
    detail_record = detail_response.json()
    assert detail_record["status"] == list_record["status"]
    assert detail_record["last_seen_at"] == list_record["last_seen_at"]


def test_update_preserves_derived_status_and_last_seen_in_response(
    admin_auth_headers,
    operational_devices,
):
    device_id = operational_devices["recent_device_id"]
    detail_url = f"/admin/devices/{device_id}"

    before_update_response = client.get(detail_url, headers=admin_auth_headers)
    assert before_update_response.status_code == 200, before_update_response.text
    before_update = before_update_response.json()
    assert before_update["status"] == "active"
    assert before_update["last_seen_at"] is not None

    update_response = client.put(
        detail_url,
        json={"friendly_name": "Operational Status Friendly Name"},
        headers=admin_auth_headers,
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["friendly_name"] == "Operational Status Friendly Name"
    assert updated["status"] == before_update["status"]
    assert updated["last_seen_at"] == before_update["last_seen_at"]

    after_update_response = client.get(detail_url, headers=admin_auth_headers)
    assert after_update_response.status_code == 200, after_update_response.text
    after_update = after_update_response.json()
    assert after_update["status"] == updated["status"]
    assert after_update["last_seen_at"] == updated["last_seen_at"]


def test_existing_device_and_sensor_filters_still_work(
    admin_auth_headers,
    operational_devices,
):
    recent_device_id = operational_devices["recent_device_id"]
    filters = (
        "name=Operational%20Status%20Recent",
        f"network={operational_devices['source_name'].replace(' ', '%20')}",
        "external_device_id=operational-recent",
        f"sensor_id={operational_devices['latest_sensor_id']}",
        "external_sensor_id=operational-latest-sensor",
    )

    for query in filters:
        records = _records_by_id(client.get(
            f"/admin/devices?{query}",
            headers=admin_auth_headers,
        ))
        assert recent_device_id in records
