"""Independent API expectations against real ingest and persisted historical QC.

Runs on an isolated PostgreSQL database when COMPASSAQ_POSTGRES_TEST_URL is set.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from api.main import app
from db import get_session
import models
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed
from .support import ensure_catalog


def test_history_qc_persisted_truth_and_public_detail(acceptance_session_factory):
    with acceptance_session_factory() as session:
        units, parameters, periods = ensure_catalog(session)
        source = models.ExternalAPI(name="Synthetic history API test", params={}, enabled=False)
        session.add(source)
        session.flush()
        device = models.Device(name="Synthetic QC history", external_api_id=source.external_api_id)
        session.add(device)
        session.flush()
        sensor = models.Sensor(device_id=device.device_id, parameter_id=parameters["pm25"].parameter_id,
                               unit_id=units["ug_m3"].unit_id, aggregation_period_id=periods["2m"].aggregation_period_id)
        session.add(sensor)
        session.flush()
        rule = models.QCRule(check_code="max_value", sensor_id=sensor.sensor_id,
                             policy_unit_id=sensor.unit_id,
                             enabled_override=True, failure_action_override="flag_for_review", settings={"max": 30})
        session.add(rule)
        session.flush()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        observations = []
        for index, value in enumerate([10, 40, 50]):
            if index == 2:
                rule.failure_action_override = "mark_invalid"
                session.flush()
            measurement = models.Measurement(sensor_id=sensor.sensor_id, value=value,
                                             observed_at=start + timedelta(minutes=index*2))
            upsert_measurement_with_policy_detailed(session, measurement, device=device, sensor=sensor)
            session.flush()
            observations.append(measurement)
        # Historical and mixed outcomes are recorded explicitly; ordinary passes
        # were generated through the real ingest path above and have no rows.
        indeterminate = models.Measurement(sensor_id=sensor.sensor_id, value=20, observed_at=start + timedelta(minutes=6), is_valid=True)
        legacy = models.Measurement(sensor_id=sensor.sensor_id, value=25, observed_at=start + timedelta(minutes=8), is_valid=True)
        session.add_all([indeterminate, legacy])
        session.flush()
        for measurement in (indeterminate, observations[2]):
            session.add(models.MeasurementQCResult(measurement_id=measurement.measurement_id, aggregate_code="2m",
                check_code="baseline_drift", passed=None, evaluation_status="indeterminate", failure_action="mark_invalid",
                reason_code="insufficient_history", message="Not enough valid history", severity="info"))
        session.add(models.MeasurementQCResult(measurement_id=observations[2].measurement_id, aggregate_code="2m",
            check_code="min_value", passed=False, evaluation_status="failed", failure_action="mark_invalid",
            reason_code="below_minimum", message="Recorded minimum not reached", severity="warning"))
        recorded = session.scalar(select(models.MeasurementQCResult).where(
            models.MeasurementQCResult.measurement_id == observations[1].measurement_id))
        historical_version = recorded.qc_version
        # A configuration change must not overwrite this observation's explanation.
        rule.settings = {"max": 999}
        recorded.policy_snapshot = {**recorded.policy_snapshot, "api_key": "must-not-leak",
                                    "configured_settings": {"max": 30, "password": "must-not-leak"}}
        recorded.params_snapshot = {"max": 30, "token": "must-not-leak"}
        recorded.policy_provenance = {**recorded.policy_provenance, "secret": {"layer": "must-not-leak"}}
        if not session.scalar(select(models.ParameterAggregationRollup).where(
            models.ParameterAggregationRollup.parameter_id == sensor.parameter_id,
            models.ParameterAggregationRollup.from_aggregation_period_id == periods["2m"].aggregation_period_id,
            models.ParameterAggregationRollup.to_aggregation_period_id == periods["1h"].aggregation_period_id,
        )):
            session.add(models.ParameterAggregationRollup(parameter_id=sensor.parameter_id,
                from_aggregation_period_id=periods["2m"].aggregation_period_id,
                to_aggregation_period_id=periods["1h"].aggregation_period_id))
        session.commit()
        sensor_id = sensor.sensor_id
        ids = [point.measurement_id for point in observations]
        indeterminate_id = indeterminate.measurement_id
        legacy_id = legacy.measurement_id

        def override():
            yield session

        app.dependency_overrides[get_session] = override
        statements = []
        def count(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(session.bind, "before_cursor_execute", count)
        try:
            client = TestClient(app)
            path = f"/sensors/{sensor_id}/history"
            params = {"aggregation": "2m", "include_qc": True, "start": start.isoformat(),
                      "end": (start + timedelta(minutes=59)).isoformat()}
            response = client.get(path, params=params)
            assert response.status_code == 200, response.text
            rows = response.json()["data"]
            assert [row["value"] for row in rows] == [10, 40, 20, 25]
            assert rows[0]["qc_provenance_status"] == "not_recorded"
            assert rows[0]["qc_results"] == []
            assert rows[1]["is_valid"] is True
            assert rows[1]["qc_results"][0]["failure_action"] == "flag_for_review"
            assert rows[2]["qc_results"][0]["evaluation_status"] == "indeterminate"
            assert rows[2]["failed_checks"] == []
            assert "policy_snapshot" not in response.text
            assert sum("measurement_qc_result" in query for query in statements) == 1

            inclusive = client.get(path, params={**params, "include_invalid": True}).json()
            invalid = inclusive["data"][2]
            assert invalid["is_valid"] is False
            assert len(invalid["qc_results"]) == 3
            assert len(invalid["failed_checks"]) == 2
            assert invalid["measurement_id"] == ids[2]

            statements.clear()
            detail = client.get(f"/sensors/{sensor_id}/measurements/{ids[1]}/qc")
            assert detail.status_code == 200
            assert len(statements) == 2
            result = detail.json()["qc_results"][0]
            assert result["params_snapshot"] == {"max": 30}
            assert result["policy_snapshot"]["configured_settings"] == {"max": 30}
            assert result["qc_version"] == historical_version
            assert result["plugin_version"]
            assert result["rule_source"] == "sensor_override"
            assert result["message"]
            assert "must-not-leak" not in detail.text
            assert client.get(f"/sensors/{sensor_id+1}/measurements/{ids[1]}/qc").status_code == 404
            assert client.get(f"/sensors/{sensor_id}/measurements/{legacy_id}/qc").json()["qc_provenance_status"] == "not_recorded"
            uncertain = client.get(f"/sensors/{sensor_id}/measurements/{indeterminate_id}/qc").json()
            assert uncertain["is_valid"] is True
            assert uncertain["qc_results"][0]["policy_snapshot"] is None
            assert uncertain["qc_results"][0]["passed"] is None

            valid_rollup = client.get(path, params={**params, "aggregation": "1h"}).json()
            all_rollup = client.get(path, params={**params, "aggregation": "1h", "include_invalid": True}).json()
            # Independent arithmetic: (10+40+20+25)/4=23.75; (+50)/5=29.
            # Migrated PostgreSQL PM2.5 formatting truncates to one decimal.
            expected_valid = 23.7 if session.bind.dialect.name == "postgresql" else 23.75
            assert valid_rollup["data"][0]["value"] == expected_valid
            assert all_rollup["data"][0]["value"] == 29
            aggregate = all_rollup["data"][0]
            assert aggregate["invalid_sample_count"] == 1
            assert aggregate["measurement_id"] is None
            assert aggregate["qc_results"] == []
            assert aggregate["qc_provenance_status"] == "source_details_unavailable"
            assert all_rollup["includes_invalid"] is True
        finally:
            event.remove(session.bind, "before_cursor_execute", count)
            app.dependency_overrides.pop(get_session, None)
