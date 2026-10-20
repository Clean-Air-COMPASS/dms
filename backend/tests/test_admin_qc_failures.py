from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

import models
from api.main import app
from db import SessionLocal
from services import auth


client = TestClient(app)


def _create_qc_failure_context() -> tuple[str, list[int]]:
    suffix = uuid.uuid4().hex
    provider_code = f"qc-failure-test-{suffix}"
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        parameter = session.scalar(
            select(models.Parameter).where(models.Parameter.code == "pm25")
        )
        assert parameter is not None

        source = models.ExternalAPI(
            provider_code=provider_code,
            name=f"QC failure test source {suffix}",
            params={},
        )
        session.add(source)
        session.flush()
        device = models.Device(
            name=f"QC failure test device {suffix}",
            friendly_name=f"Review station {suffix[:8]}",
            external_id=f"device-{suffix}",
            external_api_id=source.external_api_id,
        )
        session.add(device)
        session.flush()
        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=parameter.default_unit_id,
            external_sensor_id=f"sensor-{suffix}",
        )
        session.add(sensor)
        session.flush()

        measurements = [
            models.Measurement(
                sensor_id=sensor.sensor_id,
                value=value,
                observed_at=now + timedelta(minutes=index),
                is_valid=is_valid,
            )
            for index, (value, is_valid) in enumerate(
                [(11.5, True), (12.5, False), (13.5, True), (14.5, True)]
            )
        ]
        session.add_all(measurements)
        session.flush()

        results = [
            models.MeasurementQCResult(
                measurement_id=measurements[0].measurement_id,
                parameter_id=parameter.parameter_id,
                aggregate_code="raw",
                check_code="min_value",
                passed=False,
                evaluation_status="failed",
                failure_action="flag_for_review",
                message="Value is below the configured minimum",
                reason_code="below_minimum",
                rule_source="sensor_override",
                params_snapshot={"min": 20},
                policy_snapshot={"check_code": "min_value"},
                policy_provenance={
                    "settings.min": {
                        "layer": "sensor_override",
                        "qc_rule_id": 901,
                    }
                },
                created_at=now + timedelta(seconds=1),
            ),
            models.MeasurementQCResult(
                measurement_id=measurements[1].measurement_id,
                parameter_id=parameter.parameter_id,
                aggregate_code="raw",
                check_code="max_value",
                passed=False,
                evaluation_status="failed",
                failure_action="mark_invalid",
                message="Value is above the configured maximum",
                reason_code="above_maximum",
                rule_source="sensor_override",
                created_at=now + timedelta(seconds=2),
            ),
            models.MeasurementQCResult(
                measurement_id=measurements[2].measurement_id,
                parameter_id=parameter.parameter_id,
                aggregate_code="raw",
                check_code="min_value",
                passed=None,
                evaluation_status="indeterminate",
                failure_action="flag_for_review",
                message="The check could not evaluate this measurement",
                reason_code="conversion_not_supported",
                rule_source="compassaq_default",
                policy_snapshot={"check_code": "min_value", "status": "unavailable"},
                created_at=now + timedelta(seconds=3),
            ),
            models.MeasurementQCResult(
                measurement_id=measurements[3].measurement_id,
                parameter_id=parameter.parameter_id,
                aggregate_code="raw",
                check_code="max_value",
                passed=True,
                evaluation_status="failed",
                failure_action=None,
                message="A historical normal pass must remain excluded",
                reason_code=None,
                created_at=now + timedelta(seconds=4),
            ),
        ]
        session.add_all(results)
        session.commit()
        return provider_code, [result.measurement_qc_result_id for result in results]


def _viewer_auth_headers() -> dict[str, str]:
    settings = auth.get_auth_settings()
    with SessionLocal() as session:
        user = models.User(
            user_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            email=f"qc-failure-viewer-{uuid.uuid4()}@example.com",
            password_hash=auth.hash_password("strong-password-123"),
            is_active=True,
        )
        session.add(user)
        session.commit()
        token, _ = auth.create_access_token(
            settings=settings,
            user_id=user.user_id,
            org_id=user.org_id,
            roles=["viewer"],
            scopes=auth.scopes_from_roles(["viewer"]),
        )
    return {"Authorization": f"Bearer {token}"}


def test_qc_failures_include_indeterminate_and_return_issues_newest_first(
    admin_auth_headers,
):
    provider_code, result_ids = _create_qc_failure_context()

    response = client.get(
        "/admin/events/qc-failures",
        params={"data_source": provider_code},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert [item["measurement_qc_result_id"] for item in body["items"]] == [
        result_ids[2],
        result_ids[1],
        result_ids[0],
    ]
    assert result_ids[3] not in {
        item["measurement_qc_result_id"] for item in body["items"]
    }
    assert {item["evaluation_status"] for item in body["items"]} == {
        "failed",
        "indeterminate",
    }

    flagged = next(
        item
        for item in body["items"]
        if item["evaluation_status"] == "failed"
        and item["failure_action"] == "flag_for_review"
    )
    assert flagged["device_name"].startswith("Review station")
    assert flagged["external_sensor_id"].startswith("sensor-")
    assert flagged["data_source_name"].startswith("QC failure test source")
    assert flagged["provider_code"] == provider_code
    assert flagged["parameter_code"] == "pm25"
    assert flagged["parameter_name"] == "PM2.5"
    assert flagged["unit_symbol"] == "µg/m³"
    assert flagged["measurement_value"] == 11.5
    assert flagged["measurement_is_valid"] is True
    assert flagged["failure_action"] == "flag_for_review"
    assert flagged["check_name"] == "Minimum Value QC Check"
    assert flagged["rule_source"] == "sensor_override"
    assert flagged["policy_provenance"]["settings.min"]["layer"] == "sensor_override"

    invalid = next(
        item for item in body["items"] if item["failure_action"] == "mark_invalid"
    )
    assert invalid["failure_action"] == "mark_invalid"
    assert invalid["measurement_is_valid"] is False

    indeterminate = next(
        item for item in body["items"] if item["evaluation_status"] == "indeterminate"
    )
    assert indeterminate["reason_code"] == "conversion_not_supported"
    assert indeterminate["failure_action"] == "flag_for_review"


def test_qc_failures_status_and_effect_filters_keep_indeterminate_distinct(
    admin_auth_headers,
):
    provider_code, result_ids = _create_qc_failure_context()
    endpoint = "/admin/events/qc-failures"

    failed_response = client.get(
        endpoint,
        params={"data_source": provider_code, "status": "failed"},
        headers=admin_auth_headers,
    )
    assert failed_response.status_code == 200, failed_response.text
    assert failed_response.json()["total"] == 2
    assert all(
        item["evaluation_status"] == "failed"
        for item in failed_response.json()["items"]
    )

    indeterminate_response = client.get(
        endpoint,
        params={"data_source": provider_code, "status": "indeterminate"},
        headers=admin_auth_headers,
    )
    assert indeterminate_response.status_code == 200, indeterminate_response.text
    assert indeterminate_response.json()["total"] == 1
    assert indeterminate_response.json()["items"][0]["measurement_qc_result_id"] == result_ids[2]

    effect_response = client.get(
        endpoint,
        params={"data_source": provider_code, "outcome": "flag_for_review"},
        headers=admin_auth_headers,
    )
    assert effect_response.status_code == 200, effect_response.text
    assert effect_response.json()["total"] == 1
    assert effect_response.json()["items"][0]["evaluation_status"] == "failed"


def test_qc_failures_support_pagination_and_filters(admin_auth_headers):
    provider_code, result_ids = _create_qc_failure_context()
    endpoint = "/admin/events/qc-failures"

    page_response = client.get(
        endpoint,
        params={"data_source": provider_code, "limit": 1, "offset": 1},
        headers=admin_auth_headers,
    )
    assert page_response.status_code == 200, page_response.text
    assert page_response.json()["total"] == 3
    assert page_response.json()["items"][0]["measurement_qc_result_id"] == result_ids[1]

    outcome_response = client.get(
        endpoint,
        params={"data_source": provider_code, "outcome": "mark_invalid"},
        headers=admin_auth_headers,
    )
    assert outcome_response.json()["total"] == 1
    assert outcome_response.json()["items"][0]["failure_action"] == "mark_invalid"

    parameter_response = client.get(
        endpoint,
        params={"data_source": provider_code, "parameter": "pm10"},
        headers=admin_auth_headers,
    )
    assert parameter_response.json()["total"] == 0

    search_response = client.get(
        endpoint,
        params={"data_source": provider_code, "search": "below the configured"},
        headers=admin_auth_headers,
    )
    assert search_response.json()["total"] == 1
    assert search_response.json()["items"][0]["reason_code"] == "below_minimum"


def test_qc_failures_require_admin_permissions(admin_auth_headers):
    unauthenticated = client.get("/admin/events/qc-failures")
    assert unauthenticated.status_code == 401

    forbidden = client.get(
        "/admin/events/qc-failures",
        headers=_viewer_auth_headers(),
    )
    assert forbidden.status_code == 403

    authorized = client.get(
        "/admin/events/qc-failures",
        params={"limit": 1},
        headers=admin_auth_headers,
    )
    assert authorized.status_code == 200

def test_manual_qc_event_source_matches_custom_label_without_changing_policy(admin_auth_headers):
    provider_code, _ = _create_qc_failure_context()
    with SessionLocal() as session:
        source = session.scalar(select(models.ExternalAPI).where(models.ExternalAPI.provider_code == provider_code))
        device = session.scalar(select(models.Device).where(models.Device.external_api_id == source.external_api_id))
        device.manual_data_source_name = "Independent acceptance station"
        device.external_id = None
        session.commit()
    response = client.get('/admin/events/qc-failures', params={'data_source': 'Independent acceptance station'}, headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()['total'] == 3
    for item in response.json()['items']:
        assert item['data_source_name'] == 'Independent acceptance station'
        assert item['provider_code'] is None
    managed = client.get('/admin/events/qc-failures', params={'data_source': provider_code}, headers=admin_auth_headers)
    assert managed.json()['total'] == 0
