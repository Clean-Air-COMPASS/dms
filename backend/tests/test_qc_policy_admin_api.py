from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select

import models
from api.main import app
from db import SessionLocal
from qaqc.admin_policy import list_parameter_policy_summaries


client = TestClient(app)


def _unit(session, code: str) -> models.Unit:
    unit = session.scalar(select(models.Unit).where(models.Unit.code == code))
    if unit is None:
        unit = models.Unit(code=code, symbol=code, name=f"Test {code}")
        session.add(unit)
        session.flush()
    return unit


def _parameter(session, code: str) -> models.Parameter:
    parameter = session.scalar(
        select(models.Parameter).where(models.Parameter.code == code)
    )
    assert parameter is not None
    return parameter


def _sensor_context(
    *,
    parameter_code: str = "pm25",
    sensor_unit_code: str | None = None,
) -> tuple[int, int, int]:
    with SessionLocal() as session:
        suffix = uuid.uuid4().hex
        parameter = _parameter(session, parameter_code)
        unit_id = parameter.default_unit_id
        if sensor_unit_code is not None:
            unit_id = _unit(session, sensor_unit_code).unit_id
        source = models.ExternalAPI(
            provider_code=f"phase1b-{suffix}",
            name=f"Phase 1B source {suffix}",
            params={},
        )
        session.add(source)
        session.flush()
        device = models.Device(
            name=f"Phase 1B device {suffix}",
            friendly_name=f"Policy station {suffix[:8]}",
            external_id=f"device-{suffix}",
            external_api_id=source.external_api_id,
        )
        session.add(device)
        session.flush()
        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit_id,
            external_sensor_id=f"sensor-{suffix}",
        )
        session.add(sensor)
        session.commit()
        return source.external_api_id, sensor.sensor_id, parameter.parameter_id


def _check(response_body: dict, check_code: str) -> dict:
    return next(
        check for check in response_body["checks"] if check["check_code"] == check_code
    )


def test_metadata_and_parameter_summary_are_policy_centered(admin_auth_headers):
    checks_response = client.get("/admin/qc/checks", headers=admin_auth_headers)
    assert checks_response.status_code == 200, checks_response.text
    checks = {item["check_code"]: item for item in checks_response.json()["items"]}
    assert checks["min_value"]["available"] is True
    assert checks["min_value"]["settings"] == [
        {
            "setting_code": "min",
            "value_type": "number",
            "label": "Min threshold",
            "help_text": "Minimum acceptable value in the resolved evaluation unit",
            "required": True,
            "choices": None,
        }
    ]
    assert "module" not in checks["min_value"]

    parameters_response = client.get(
        "/admin/qc/parameters", headers=admin_auth_headers
    )
    assert parameters_response.status_code == 200, parameters_response.text
    body = parameters_response.json()
    assert body["default_profile_version"] == "2026.2"
    pm25 = next(item for item in body["items"] if item["parameter_code"] == "pm25")
    assert pm25["supported"] is True
    assert _check(pm25, "min_value")["configured_settings"] == {"min": -10.0}
    baseline_drift = _check(pm25, "baseline_drift")
    assert baseline_drift["status"] == "disabled"
    assert baseline_drift["enabled"] is False
    assert baseline_drift["configured_settings"] == {
        "lookback_hours": 168,
        "min_samples": 72,
        "baseline_quantile": 0.1,
        "max_drift_per_day": 5.0,
        "direction": "both",
    }
    assert baseline_drift["evaluation_settings"] == {}


def test_administrator_can_deliberately_enable_baseline_drift_preset(
    admin_auth_headers,
):
    _, _, parameter_id = _sensor_context()
    policy_url = f"/admin/qc/parameters/{parameter_id}/policy"

    response = client.put(
        policy_url,
        json={
            "overrides": [
                {
                    "check_code": "baseline_drift",
                    "enabled_override": True,
                    "settings": {},
                    "policy_unit_code": "ug_m3",
                }
            ]
        },
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    baseline_drift = _check(response.json(), "baseline_drift")
    assert baseline_drift["status"] == "ready"
    assert baseline_drift["enabled"] is True
    assert baseline_drift["evaluation_settings"]["max_drift_per_day"] == 5.0
    explicit_override = next(
        override
        for override in response.json()["overrides"]
        if override["check_code"] == "baseline_drift"
    )
    assert explicit_override["enabled_override"] is True

    reset = client.delete(
        f"{policy_url}/checks/baseline_drift?unit_code=ug_m3",
        headers=admin_auth_headers,
    )
    assert reset.status_code == 200, reset.text


def test_parameter_ranges_are_resolved_independently_for_each_supported_unit(
    admin_auth_headers,
):
    _, sensor_id, parameter_id = _sensor_context(
        parameter_code="o3",
        sensor_unit_code="ug_m3",
    )
    policy_url = f"/admin/qc/parameters/{parameter_id}/policy"
    response = client.get(policy_url, headers=admin_auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {unit["unit_code"] for unit in body["parameter"]["supported_units"]} >= {
        "ppm",
        "ppb",
        "ug_m3",
    }
    maximum_by_unit = {
        check["applicable_unit_code"]: check
        for check in body["checks"]
        if check["check_code"] == "max_value"
    }
    assert maximum_by_unit["ppm"]["evaluation_settings"] == {"max": 0.5}
    assert maximum_by_unit["ppb"]["evaluation_settings"] == {"max": 500.0}
    assert maximum_by_unit["ug_m3"]["status"] == "not_configured"
    assert maximum_by_unit["ug_m3"]["reason_code"] == "no_matching_rule"

    updated = client.put(
        policy_url,
        json={
            "overrides": [
                {
                    "check_code": "max_value",
                    "settings": {"max": 0.4},
                    "policy_unit_code": "ppm",
                },
                {
                    "check_code": "max_value",
                    "enabled_override": True,
                    "failure_action_override": "flag_for_review",
                    "settings": {"max": 400},
                    "policy_unit_code": "ug_m3",
                },
            ]
        },
        headers=admin_auth_headers,
    )
    assert updated.status_code == 200, updated.text
    updated_maximum_by_unit = {
        check["applicable_unit_code"]: check
        for check in updated.json()["checks"]
        if check["check_code"] == "max_value"
    }
    assert updated_maximum_by_unit["ppm"]["evaluation_settings"] == {"max": 0.4}
    assert updated_maximum_by_unit["ppb"]["evaluation_settings"] == {"max": 400.0}
    assert updated_maximum_by_unit["ug_m3"]["evaluation_settings"] == {"max": 400.0}

    sensor_override = client.put(
        f"/admin/qc/sensors/{sensor_id}/policy",
        json={
            "overrides": [
                {
                    "check_code": "max_value",
                    "settings": {"max": 0.3},
                    "policy_unit_code": "ppm",
                }
            ]
        },
        headers=admin_auth_headers,
    )
    assert sensor_override.status_code == 422
    assert sensor_override.json()["detail"]["reason_code"] == "sensor_unit_mismatch"
    client.delete(policy_url, headers=admin_auth_headers)


def test_sparse_hierarchy_reset_and_versions(admin_auth_headers):
    source_id, sensor_id, parameter_id = _sensor_context()
    parameter_url = f"/admin/qc/parameters/{parameter_id}/policy"
    source_url = (
        f"/admin/qc/sources/{source_id}/parameters/{parameter_id}/policy"
    )
    sensor_url = f"/admin/qc/sensors/{sensor_id}/policy"

    parameter_payload = {
        "overrides": [
            {
                "check_code": "min_value",
                "failure_action_override": "mark_invalid",
                "settings": {"min": -5},
                "policy_unit_code": "ug_m3",
            }
        ]
    }
    parameter_response = client.put(
        parameter_url, json=parameter_payload, headers=admin_auth_headers
    )
    assert parameter_response.status_code == 200, parameter_response.text
    first_version = parameter_response.json()["overrides"][0]["version"]
    same_response = client.put(
        parameter_url, json=parameter_payload, headers=admin_auth_headers
    )
    assert same_response.json()["overrides"][0]["version"] == first_version

    source_response = client.put(
        source_url,
        json={
            "overrides": [
                {"check_code": "min_value", "settings": {"min": -3}, "policy_unit_code": "ug_m3"}
            ]
        },
        headers=admin_auth_headers,
    )
    assert source_response.status_code == 200, source_response.text
    source_check = _check(source_response.json(), "min_value")
    assert source_check["configured_settings"] == {"min": -3}
    assert source_check["failure_action"] == "mark_invalid"
    assert source_check["property_provenance"]["settings.min"]["layer"] == "source_override"
    assert source_check["property_provenance"]["failure_action"]["layer"] == "parameter_override"
    assert source_check["inherited_policy"]["configured_settings"] == {"min": -5}
    assert source_check["inherited_policy"]["failure_action"] == "mark_invalid"
    assert (
        source_check["inherited_policy"]["property_provenance"]["settings.min"]["layer"]
        == "parameter_override"
    )

    sensor_response = client.put(
        sensor_url,
        json={
            "overrides": [
                {
                    "check_code": "min_value",
                    "enabled_override": True,
                    "settings": {"min": -1},
                    "policy_unit_code": "ug_m3",
                }
            ]
        },
        headers=admin_auth_headers,
    )
    assert sensor_response.status_code == 200, sensor_response.text
    sensor_check = _check(sensor_response.json(), "min_value")
    assert sensor_check["evaluation_settings"] == {"min": -1.0}
    assert sensor_check["failure_action"] == "mark_invalid"
    assert sensor_check["property_provenance"]["settings.min"]["layer"] == "sensor_override"
    assert sensor_check["inherited_policy"]["configured_settings"] == {"min": -3}
    assert (
        sensor_check["inherited_policy"]["property_provenance"]["settings.min"]["layer"]
        == "source_override"
    )

    reset_sensor = client.delete(
        f"{sensor_url}/checks/min_value?unit_code=ug_m3", headers=admin_auth_headers
    )
    assert _check(reset_sensor.json(), "min_value")["evaluation_settings"] == {
        "min": -3.0
    }
    reset_source = client.delete(source_url, headers=admin_auth_headers)
    assert _check(reset_source.json(), "min_value")["configured_settings"] == {
        "min": -5
    }
    reset_parameter = client.delete(parameter_url, headers=admin_auth_headers)
    assert _check(reset_parameter.json(), "min_value")["configured_settings"] == {
        "min": -10.0
    }


def test_parameter_summary_counts_distinct_exception_scopes(admin_auth_headers):
    initial_response = client.get(
        "/admin/qc/parameters", headers=admin_auth_headers
    )
    assert initial_response.status_code == 200, initial_response.text
    source_id, first_sensor_id, parameter_id = _sensor_context()
    initial_parameter = next(
        item for item in initial_response.json()["items"]
        if item["parameter_id"] == parameter_id
    )
    with SessionLocal() as session:
        first_sensor = session.get(models.Sensor, first_sensor_id)
        unit_id = first_sensor.unit_id
        second_sensor = models.Sensor(
            device_id=first_sensor.device_id,
            parameter_id=parameter_id,
            unit_id=first_sensor.unit_id,
            external_sensor_id=f"second-{uuid.uuid4().hex}",
        )
        session.add(second_sensor)
        session.flush()
        session.add_all(
            [
                models.QCRule(
                    check_code="min_value",
                    parameter_id=parameter_id,
                    external_api_id=source_id,
                    settings={"min": -8},
                    policy_unit_id=unit_id,
                ),
                models.QCRule(
                    check_code="max_value",
                    parameter_id=parameter_id,
                    external_api_id=source_id,
                    settings={"max": 8_000},
                    policy_unit_id=unit_id,
                ),
                models.QCRule(
                    check_code="min_value",
                    sensor_id=first_sensor_id,
                    enabled_override=False,
                    policy_unit_id=unit_id,
                ),
                models.QCRule(
                    check_code="max_value",
                    sensor_id=first_sensor_id,
                    enabled_override=False,
                    policy_unit_id=unit_id,
                ),
                models.QCRule(
                    check_code="min_value",
                    sensor_id=second_sensor.sensor_id,
                    enabled_override=False,
                    policy_unit_id=unit_id,
                ),
            ]
        )
        session.commit()

    response = client.get("/admin/qc/parameters", headers=admin_auth_headers)
    assert response.status_code == 200, response.text
    parameter = next(
        item for item in response.json()["items"]
        if item["parameter_id"] == parameter_id
    )
    assert parameter["source_override_count"] == (
        initial_parameter["source_override_count"] + 2
    )
    assert parameter["source_exception_count"] == (
        initial_parameter["source_exception_count"] + 1
    )
    assert parameter["sensor_override_count"] == (
        initial_parameter["sensor_override_count"] + 3
    )
    assert parameter["sensor_exception_count"] == (
        initial_parameter["sensor_exception_count"] + 2
    )


def test_parameter_summary_counts_only_effectively_enabled_baseline_drift_scopes(
    admin_auth_headers,
):
    initial_response = client.get(
        "/admin/qc/parameters", headers=admin_auth_headers
    )
    assert initial_response.status_code == 200, initial_response.text
    initial_pm25 = next(
        item for item in initial_response.json()["items"]
        if item["parameter_code"] == "pm25"
    )

    enabled_source_id, enabled_sensor_id, parameter_id = _sensor_context()
    _disabled_source_id, sparse_sensor_id, _ = _sensor_context()
    with SessionLocal() as session:
        enabled_sensor = session.get(models.Sensor, enabled_sensor_id)
        unit_id = enabled_sensor.unit_id
        explicitly_disabled_sensor = models.Sensor(
            device_id=enabled_sensor.device_id,
            parameter_id=parameter_id,
            unit_id=unit_id,
            external_sensor_id=f"disabled-{uuid.uuid4().hex}",
        )
        session.add(explicitly_disabled_sensor)
        session.flush()
        session.add_all(
            [
                models.QCRule(
                    check_code="baseline_drift",
                    parameter_id=parameter_id,
                    external_api_id=enabled_source_id,
                    enabled_override=True,
                    policy_unit_id=unit_id,
                ),
                models.QCRule(
                    check_code="baseline_drift",
                    sensor_id=enabled_sensor_id,
                    enabled_override=True,
                    policy_unit_id=unit_id,
                ),
                models.QCRule(
                    check_code="baseline_drift",
                    sensor_id=explicitly_disabled_sensor.sensor_id,
                    enabled_override=False,
                    policy_unit_id=unit_id,
                ),
                models.QCRule(
                    check_code="baseline_drift",
                    sensor_id=sparse_sensor_id,
                    settings={"direction": "up"},
                    policy_unit_id=unit_id,
                ),
            ]
        )
        session.commit()

    response = client.get("/admin/qc/parameters", headers=admin_auth_headers)
    assert response.status_code == 200, response.text
    pm25 = next(
        item for item in response.json()["items"]
        if item["parameter_id"] == parameter_id
    )
    assert _check(pm25, "baseline_drift")["enabled"] is False
    assert pm25["baseline_drift_source_override_count"] == (
        initial_pm25["baseline_drift_source_override_count"] + 1
    )
    assert pm25["baseline_drift_sensor_override_count"] == (
        initial_pm25["baseline_drift_sensor_override_count"] + 3
    )
    assert pm25["baseline_drift_enabled_source_count"] == (
        initial_pm25["baseline_drift_enabled_source_count"] + 1
    )
    assert pm25["baseline_drift_enabled_sensor_count"] == (
        initial_pm25["baseline_drift_enabled_sensor_count"] + 1
    )
    assert pm25["source_exception_count"] == (
        initial_pm25["source_exception_count"] + 1
    )
    assert pm25["sensor_exception_count"] == (
        initial_pm25["sensor_exception_count"] + 3
    )


def test_parameter_summary_query_count_does_not_scale_with_drift_override_rows():
    def select_statement_count() -> int:
        count = 0

        def count_selects(_connection, _cursor, statement, *_args):
            nonlocal count
            if statement.lstrip().upper().startswith("SELECT"):
                count += 1

        event.listen(SessionLocal.kw["bind"], "before_cursor_execute", count_selects)
        try:
            with SessionLocal() as session:
                list_parameter_policy_summaries(session)
        finally:
            event.remove(
                SessionLocal.kw["bind"], "before_cursor_execute", count_selects
            )
        return count

    before_count = select_statement_count()
    _source_id, first_sensor_id, parameter_id = _sensor_context()
    with SessionLocal() as session:
        first_sensor = session.get(models.Sensor, first_sensor_id)
        for index in range(12):
            sensor = models.Sensor(
                device_id=first_sensor.device_id,
                parameter_id=parameter_id,
                unit_id=first_sensor.unit_id,
                external_sensor_id=f"query-count-{index}-{uuid.uuid4().hex}",
            )
            session.add(sensor)
            session.flush()
            session.add(
                models.QCRule(
                    check_code="baseline_drift",
                    sensor_id=sensor.sensor_id,
                    enabled_override=bool(index % 2),
                    policy_unit_id=first_sensor.unit_id,
                )
            )
        session.commit()

    assert select_statement_count() == before_count


def test_parameter_policy_exposes_compassaq_reset_target(admin_auth_headers):
    _, _, parameter_id = _sensor_context()
    response = client.put(
        f"/admin/qc/parameters/{parameter_id}/policy",
        json={
            "overrides": [
                {
                    "check_code": "min_value",
                    "settings": {"min": -2},
                    "failure_action_override": "mark_invalid",
                    "policy_unit_code": "ug_m3",
                }
            ]
        },
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    minimum = _check(response.json(), "min_value")
    assert minimum["configured_settings"] == {"min": -2}
    assert minimum["inherited_policy"]["configured_settings"] == {"min": -10.0}
    assert minimum["inherited_policy"]["failure_action"] == "flag_for_review"
    assert (
        minimum["inherited_policy"]["most_specific_source"]["layer"]
        == "compassaq_default"
    )
    client.delete(
        f"/admin/qc/parameters/{parameter_id}/policy",
        headers=admin_auth_headers,
    )


def test_generic_replacement_does_not_delete_advanced_aggregation_rule(
    admin_auth_headers,
):
    _, _, parameter_id = _sensor_context()
    with SessionLocal() as session:
        parameter = session.get(models.Parameter, parameter_id)
        session.add(
            models.QCRule(
                check_code="max_value",
                parameter_id=parameter_id,
                aggregate_code="1h",
                settings={"max": 900},
                policy_unit_id=parameter.default_unit_id,
            )
        )
        session.commit()

    response = client.put(
        f"/admin/qc/parameters/{parameter_id}/policy",
        json={
            "overrides": [
                {"check_code": "max_value", "settings": {"max": 800}, "policy_unit_code": "ug_m3"}
            ]
        },
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["advanced_aggregation_override_count"] == 1

    client.delete(
        f"/admin/qc/parameters/{parameter_id}/policy",
        headers=admin_auth_headers,
    )
    with SessionLocal() as session:
        advanced_count = session.scalar(
            select(func.count())
            .select_from(models.QCRule)
            .where(
                models.QCRule.parameter_id == parameter_id,
                models.QCRule.aggregate_code == "1h",
            )
        )
        assert advanced_count == 1
        session.execute(
            delete(models.QCRule).where(
                models.QCRule.parameter_id == parameter_id,
                models.QCRule.aggregate_code == "1h",
            )
        )
        session.commit()


def test_invalid_reenable_and_unknown_unit_are_explicit(admin_auth_headers):
    _, _, no_parameter_id = _sensor_context(parameter_code="no")
    reenable = client.put(
        f"/admin/qc/parameters/{no_parameter_id}/policy",
        json={
            "overrides": [
                {"check_code": "min_value", "enabled_override": True}
            ]
        },
        headers=admin_auth_headers,
    )
    assert reenable.status_code == 422
    assert reenable.json()["detail"]["reason_code"] == "missing_policy_unit"

    _, sensor_id, _ = _sensor_context()
    unknown_unit = client.put(
        f"/admin/qc/sensors/{sensor_id}/policy",
        json={
            "overrides": [
                {
                    "check_code": "min_value",
                    "settings": {"min": 0},
                    "policy_unit_code": "made_up_unit",
                }
            ]
        },
        headers=admin_auth_headers,
    )
    assert unknown_unit.status_code == 422
    assert unknown_unit.json()["detail"]["reason_code"] == "unknown_unit"

    unsupported_conversion = client.put(
        f"/admin/qc/sensors/{sensor_id}/policy",
        json={
            "overrides": [
                {
                    "check_code": "min_value",
                    "settings": {"min": 0},
                    "policy_unit_code": "ppm",
                }
            ]
        },
        headers=admin_auth_headers,
    )
    assert unsupported_conversion.status_code == 422
    assert (
        unsupported_conversion.json()["detail"]["reason_code"]
        == "unsupported_unit"
    )

    duplicate = client.put(
        f"/admin/qc/sensors/{sensor_id}/policy",
        json={
            "overrides": [
                {"check_code": "min_value", "enabled_override": False, "policy_unit_code": "ug_m3"},
                {"check_code": "min_value", "settings": {"min": 0}, "policy_unit_code": "ug_m3"},
            ]
        },
        headers=admin_auth_headers,
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"]["reason_code"] == "duplicate_check_code"

    disabled_incomplete = client.put(
        f"/admin/qc/sensors/{sensor_id}/policy",
        json={
            "overrides": [
                {
                    "check_code": "baseline_drift",
                    "enabled_override": False,
                    "policy_unit_code": "ug_m3",
                }
            ]
        },
        headers=admin_auth_headers,
    )
    assert disabled_incomplete.status_code == 200, disabled_incomplete.text
    assert _check(disabled_incomplete.json(), "baseline_drift")["status"] == "disabled"
    client.delete(
        f"/admin/qc/sensors/{sensor_id}/policy", headers=admin_auth_headers
    )


def test_sensor_search_includes_sensors_without_measurements(admin_auth_headers):
    source_id, sensor_id, parameter_id = _sensor_context()
    with SessionLocal() as session:
        sensor = session.get(models.Sensor, sensor_id)
        search_fragment = sensor.external_sensor_id[-12:]
        device = session.get(models.Device, sensor.device_id)
        source = session.get(models.ExternalAPI, source_id)
        parameter = session.get(models.Parameter, parameter_id)
        human_search_values = [
            device.friendly_name,
            device.name,
            source.name,
            parameter.display_name,
        ]

    for human_search_value in human_search_values:
        human_search = client.get(
            "/admin/qc/sensors/search",
            params={
                "query": human_search_value,
                "external_api_id": source_id,
            },
            headers=admin_auth_headers,
        )
        assert human_search.status_code == 200, human_search.text
        assert human_search.json()["total"] == 1
        assert human_search.json()["items"][0]["sensor_id"] == sensor_id

    response = client.get(
        "/admin/qc/sensors/search",
        params={
            "query": search_fragment,
            "parameter_id": parameter_id,
            "external_api_id": source_id,
        },
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["sensor_id"] == sensor_id
    assert response.json()["items"][0]["has_overrides"] is False

    client.put(
        f"/admin/qc/sensors/{sensor_id}/policy",
        json={
            "overrides": [
                {"check_code": "min_value", "enabled_override": False, "policy_unit_code": "ug_m3"}
            ]
        },
        headers=admin_auth_headers,
    )
    with_overrides = client.get(
        "/admin/qc/sensors/search",
        params={"query": search_fragment, "has_overrides": True},
        headers=admin_auth_headers,
    )
    assert with_overrides.status_code == 200, with_overrides.text
    assert with_overrides.json()["total"] == 1
    assert with_overrides.json()["items"][0]["has_overrides"] is True
    client.delete(
        f"/admin/qc/sensors/{sensor_id}/policy", headers=admin_auth_headers
    )

    with SessionLocal() as session:
        sensor = session.get(models.Sensor, sensor_id)
        session.add(
            models.QCRule(
                check_code="min_value",
                sensor_id=sensor_id,
                aggregate_code="1h",
                settings={"min": -4},
                policy_unit_id=sensor.unit_id,
            )
        )
        session.commit()

    advanced_only = client.get(
        "/admin/qc/sensors/search",
        params={"query": search_fragment, "has_sensor_specific_qc": True},
        headers=admin_auth_headers,
    )
    assert advanced_only.status_code == 200, advanced_only.text
    advanced_item = advanced_only.json()["items"][0]
    assert advanced_item["has_overrides"] is False
    assert advanced_item["advanced_override_count"] == 1
    assert advanced_item["has_sensor_specific_qc"] is True

    without_sensor_qc = client.get(
        "/admin/qc/sensors/search",
        params={"query": search_fragment, "has_sensor_specific_qc": False},
        headers=admin_auth_headers,
    )
    assert without_sensor_qc.status_code == 200, without_sensor_qc.text
    assert without_sensor_qc.json()["total"] == 0

    with SessionLocal() as session:
        session.execute(
            delete(models.QCRule).where(
                models.QCRule.sensor_id == sensor_id,
                models.QCRule.aggregate_code == "1h",
            )
        )
        session.commit()


def test_sensor_full_reset_preserves_advanced_aggregation_rules(admin_auth_headers):
    _, sensor_id, _ = _sensor_context()
    with SessionLocal() as session:
        sensor = session.get(models.Sensor, sensor_id)
        session.add(
            models.QCRule(
                check_code="max_value",
                sensor_id=sensor_id,
                aggregate_code="1h",
                settings={"max": 900},
                policy_unit_id=sensor.unit_id,
            )
        )
        session.commit()

    created = client.put(
        f"/admin/qc/sensors/{sensor_id}/policy",
        json={
            "overrides": [
                {"check_code": "min_value", "settings": {"min": -4}, "policy_unit_code": "ug_m3"}
            ]
        },
        headers=admin_auth_headers,
    )
    assert created.status_code == 200, created.text
    assert created.json()["advanced_aggregation_override_count"] == 1

    reset = client.delete(
        f"/admin/qc/sensors/{sensor_id}/policy",
        headers=admin_auth_headers,
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["overrides"] == []
    assert reset.json()["advanced_aggregation_override_count"] == 1

    with SessionLocal() as session:
        advanced_count = session.scalar(
            select(func.count())
            .select_from(models.QCRule)
            .where(
                models.QCRule.sensor_id == sensor_id,
                models.QCRule.aggregate_code == "1h",
            )
        )
        assert advanced_count == 1
        session.execute(
            delete(models.QCRule).where(models.QCRule.sensor_id == sensor_id)
        )
        session.commit()

def test_preview_uses_pipeline_and_never_mutates_history(admin_auth_headers):
    _, sensor_id, _ = _sensor_context()
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        measurements = [
            models.Measurement(
                sensor_id=sensor_id,
                value=value,
                observed_at=now - timedelta(minutes=index),
            )
            for index, value in enumerate((-20.0, 5.0, 20_000.0))
        ]
        session.add_all(measurements)
        session.commit()
        measurement_ids = [row.measurement_id for row in measurements]

    response = client.post(
        "/admin/qc/preview",
        json={
            "scope_type": "sensor",
            "sensor_id": sensor_id,
            "hours": 1,
            "overrides": [
                {
                    "check_code": "min_value",
                    "settings": {"min": -15},
                    "failure_action_override": "flag_for_review",
                    "policy_unit_code": "ug_m3",
                },
                {
                    "check_code": "max_value",
                    "settings": {"max": 100},
                    "failure_action_override": "mark_invalid",
                    "policy_unit_code": "ug_m3",
                },
            ],
        },
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["samples_evaluated"] == 3
    minimum = _check(body, "min_value")
    maximum = _check(body, "max_value")
    assert (minimum["passed"], minimum["failed"]) == (2, 1)
    assert minimum["would_flag"] == 1
    assert minimum["would_invalidate"] == 0
    assert (maximum["passed"], maximum["failed"]) == (2, 1)
    assert maximum["would_invalidate"] == 1
    assert response.headers["cache-control"] == "no-store"

    with SessionLocal() as session:
        stored = list(
            session.scalars(
                select(models.Measurement).where(
                    models.Measurement.measurement_id.in_(measurement_ids)
                )
            ).all()
        )
        assert all(row.is_valid for row in stored)
        assert all(row.qc_flags is None for row in stored)
        result_count = session.scalar(
            select(func.count())
            .select_from(models.MeasurementQCResult)
            .where(models.MeasurementQCResult.measurement_id.in_(measurement_ids))
        )
        rule_count = session.scalar(
            select(func.count())
            .select_from(models.QCRule)
            .where(models.QCRule.sensor_id == sensor_id)
        )
        assert result_count == 0
        assert rule_count == 0


def test_preview_applies_safe_mass_unit_conversion(admin_auth_headers):
    _, sensor_id, _ = _sensor_context(sensor_unit_code="mg_m3")
    with SessionLocal() as session:
        session.add(
            models.Measurement(
                sensor_id=sensor_id,
                value=-0.02,
                observed_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    response = client.post(
        "/admin/qc/preview",
        json={
            "scope_type": "sensor",
            "sensor_id": sensor_id,
            "hours": 1,
            "check_codes": ["min_value"],
            "overrides": [],
        },
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    minimum = response.json()["checks"][0]
    assert minimum["failed"] == 1
    candidate_minimum = _check(response.json()["candidate_policy"], "min_value")
    assert candidate_minimum["evaluation_settings"] == {"min": -0.01}
    assert candidate_minimum["unit_conversion"]["status"] == "converted"

def test_manual_sensor_context_separates_location_source_from_inherited_policy(admin_auth_headers):
    source_id, sensor_id, _ = _sensor_context()
    with SessionLocal() as session:
        sensor = session.get(models.Sensor, sensor_id)
        device = session.get(models.Device, sensor.device_id)
        device.manual_data_source_name = 'Independent acceptance station'
        device.external_id = None
        session.commit()
    response = client.get(f'/admin/qc/sensors/{sensor_id}/policy', headers=admin_auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['sensor']['manual_data_source_name'] == 'Independent acceptance station'
    assert body['sensor']['display_label'].endswith('Independent acceptance station')
    assert body['data_source']['external_api_id'] == source_id
    assert body['overrides'] == []
