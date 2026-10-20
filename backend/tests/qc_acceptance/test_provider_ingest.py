from __future__ import annotations

import pytest
from sqlalchemy import select

import models
from sources.airgradient import importer as airgradient_importer
from sources.openaq import importer as openaq_importer
from sources.purpleair import importer as purpleair_importer
from .support import (
    ensure_catalog,
    ensure_source,
    measurement_qc_rows,
)


@pytest.mark.qc_acceptance(
    id="provider-openaq-ingest-qc",
    source="OpenAQ location latest fixture",
    parameter="pm25",
    qc_layer="compassaq_default",
    expected="Fresh-install Baseline Drift stays Off while Min QC persists and a skipped duplicate does not rerun QC",
)
def test_openaq_provider_payload_reaches_qc_persistence(
    acceptance_session_factory, monkeypatch, acceptance_evidence
):
    Session = acceptance_session_factory
    with Session() as session:
        ensure_catalog(session)
        source = ensure_source(session, "openaq", "OpenAQ")
        device = models.Device(
            name="QC acceptance OpenAQ",
            external_api_id=source.external_api_id,
            external_id="qc-acceptance-location",
        )
        session.add(device)
        session.commit()

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get_metrics(self):
            return {}

    def fake_fetch_json(client, url, **kwargs):
        if url.endswith("/qc-acceptance-location/sensors"):
            return {"results": []}
        if url.endswith("/qc-acceptance-location/latest"):
            return {
                "coordinates": {"latitude": 40.641441, "longitude": -74.208366},
                "measurements": [
                    {
                        "parameter": "pm25",
                        "value": -20.0,
                        "unit": "µg/m³",
                        "lastUpdated": "2026-08-19T12:00:00Z",
                    }
                ],
            }
        raise AssertionError(f"Unexpected OpenAQ URL: {url}")

    monkeypatch.setattr(openaq_importer, "SessionLocal", Session)
    monkeypatch.setattr(openaq_importer, "get_api_client", lambda name: FakeClient())
    monkeypatch.setattr(openaq_importer, "fetch_json", fake_fetch_json)

    first = openaq_importer.import_measurements_from_locations()
    duplicate = openaq_importer.import_measurements_from_locations()

    with Session() as session:
        measurement = session.scalar(select(models.Measurement))
        rows = measurement_qc_rows(session, measurement.measurement_id)
        assert first["measurements_inserted"] == 1
        assert first["qc"] == {
            "evaluated": 1,
            "passed": 0,
            "flagged": 1,
            "indeterminate": 0,
        }
        assert duplicate["measurements_skipped"] == 1
        assert "qc" not in duplicate
        assert measurement.value == -20.0
        assert measurement.is_valid is True
        assert measurement.qc_flags == ["min_value"]
        assert [row.check_code for row in rows] == ["min_value"]
        minimum_result = rows[0]
        assert minimum_result.evaluation_status == "failed"
        assert minimum_result.failure_action == "flag_for_review"
        assert minimum_result.policy_provenance["settings.min"]["layer"] == "compassaq_default"
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "measurement_id": measurement.measurement_id,
                "check_code": minimum_result.check_code,
                "duplicate_action": "skip",
            }
        )


@pytest.mark.qc_acceptance(
    id="provider-purpleair-ingest-qc",
    source="PurpleAir sensor 159361-shaped history fixture",
    parameter="pm25,pm10",
    qc_layer="compassaq_default",
    expected="Two-minute atmospheric fields execute QC and allowed updates replace failure rows",
)
def test_purpleair_provider_payload_reaches_qc_and_update_replacement(
    acceptance_session_factory, monkeypatch, acceptance_evidence
):
    Session = acceptance_session_factory
    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "false")
    monkeypatch.setenv("PURPLEAIR_EXECUTION_MODE", "manual")
    monkeypatch.setenv("PURPLEAIR_MANUAL_AUTHORIZED", "true")

    with Session() as session:
        units, parameters, periods = ensure_catalog(session)
        two_minutes = periods["2m"]
        source = ensure_source(session, "purpleair", "PurpleAir")
        source.base_url = purpleair_importer.DEFAULT_BASE_URL
        source.params = {"sensor_index": "159361"}
        device = models.Device(
            name="UAlbany - Queens College(DEC)",
            external_id="159361",
            external_api_id=source.external_api_id,
            allow_updates=models.UpdatePolicy.ALLOW,
        )
        session.add(device)
        session.flush()
        for parameter_code, field_name in (
            ("pm25", "pm2.5_atm"),
            ("pm10", "pm10.0_atm"),
        ):
            session.add(
                models.Sensor(
                    device_id=device.device_id,
                    parameter_id=parameters[parameter_code].parameter_id,
                    unit_id=units["ug_m3"].unit_id,
                    aggregation_period_id=two_minutes.aggregation_period_id,
                    external_sensor_id=f"159361:{field_name}",
                )
            )
        session.commit()

    def fake_api_get(base_url, sensor_index, fields, api_key=None):
        return {
            "sensor": {
                "name": "UAlbany - Queens College(DEC)",
                "latitude": 40.736748,
                "longitude": -73.82209,
            }
        }

    history_values = {"pm25": -20.0, "pm10": 18_000.0}

    def fake_history(base_url, sensor_index, fields, start_timestamp, end_timestamp, api_key=None):
        return {
            "fields": list(fields),
            "data": [[1_787_137_200, history_values["pm25"], history_values["pm10"]]],
        }

    monkeypatch.setattr(purpleair_importer, "SessionLocal", Session)
    monkeypatch.setattr(purpleair_importer, "_api_get", fake_api_get)
    monkeypatch.setattr(purpleair_importer, "_api_get_history", fake_history)

    first = purpleair_importer.run_import()
    # Simulate the next hourly poll while retaining the real update/QC path.
    with Session() as session:
        state = session.scalar(select(models.PurpleAirImportState))
        state.history_polled_at = None
        session.commit()
    history_values.update(pm25=12.5, pm10=45.6)
    updated = purpleair_importer.run_import()

    with Session() as session:
        measurements = list(
            session.scalars(select(models.Measurement).order_by(models.Measurement.sensor_id))
        )
        assert first["measurements_inserted"] == 2
        assert first["qc"]["flagged"] == 2
        assert first["qc"]["indeterminate"] == 0
        assert updated["measurements_updated"] == 2
        assert updated["qc"]["passed"] == 2
        assert updated["qc"]["indeterminate"] == 0
        assert [measurement.value for measurement in measurements] == [12.5, 45.6]
        assert all(measurement.is_valid for measurement in measurements)
        assert all(measurement.qc_flags is None for measurement in measurements)
        remaining_rows = list(session.scalars(select(models.MeasurementQCResult)))
        assert remaining_rows == []
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "sensor_external_id": "159361",
                "inserted": 2,
                "updated": 2,
                "remaining_failure_rows": 0,
                "remaining_qc_result_rows": len(remaining_rows),
            }
        )


@pytest.mark.qc_acceptance(
    id="provider-airgradient-null-and-invalid-qc",
    source="AirGradient fixed location 58376-shaped fixture",
    parameter="pm25,relative_humidity",
    qc_layer="compassaq_default",
    expected="Null preferred corrected PM is skipped and numeric invalid humidity is retained but invalidated",
)
def test_airgradient_null_field_skips_and_numeric_field_executes_qc(
    acceptance_session_factory, monkeypatch, acceptance_evidence
):
    monkeypatch.setattr(airgradient_importer, "import_location_history", lambda *args, **kwargs: None)
    Session = acceptance_session_factory
    with Session() as session:
        units, parameters, _ = ensure_catalog(session)
        source = ensure_source(session, "airgradient", "AirGradient")
        source.base_url = airgradient_importer.DEFAULT_BASE_URL
        source.params = {
            "reference_locations_version": (
                airgradient_importer.AIRGRADIENT_REFERENCE_LOCATIONS_VERSION
            ),
            "reference_locations_initialized_ids": ["58376"],
        }
        device = models.Device(
            name="Provider New York",
            external_id="58376",
            external_api_id=source.external_api_id,
            timezone="America/New_York",
        )
        session.add(device)
        session.flush()
        for parameter_code, unit_code, field_name in (
            ("pm25", "ug_m3", "pm02_corrected"),
            ("relative_humidity", "percent", "rhum"),
        ):
            session.add(
                models.Sensor(
                    device_id=device.device_id,
                    parameter_id=parameters[parameter_code].parameter_id,
                    unit_id=units[unit_code].unit_id,
                    external_sensor_id=f"58376:{field_name}",
                )
            )
        session.commit()

    payload = {
        "locationId": 58376,
        "locationName": "Provider New York",
        "latitude": 40.940119,
        "longitude": -73.7561704,
        "timezone": "America/New_York",
        "timestamp": "2026-08-19T12:00:00Z",
        "pm02_corrected": None,
        "pm02": -20.0,
        "rhum": 101.0,
    }
    monkeypatch.setattr(airgradient_importer, "SessionLocal", Session)
    def fake_api_get(path, *args, **kwargs):
        if path.endswith("/place"):
            return {"id": 10, "name": "Fixture place", "timezoneId": "UTC"}
        if path.endswith("/locations/measures/current"):
            return []
        return payload

    monkeypatch.setattr(airgradient_importer, "_api_get", fake_api_get)

    summary = airgradient_importer.run_import(location_ids=[58376])

    with Session() as session:
        measurement = session.scalar(select(models.Measurement))
        sensor = session.get(models.Sensor, measurement.sensor_id)
        rows = measurement_qc_rows(session, measurement.measurement_id)
        assert summary["measurements_received"] == 2
        assert summary["measurements_inserted"] == 1
        assert summary["measurements_skipped"] == 1
        assert summary["qc"]["flagged"] == 1
        assert sensor.external_sensor_id == "58376:rhum"
        assert measurement.value == 101.0
        assert measurement.is_valid is False
        assert measurement.qc_flags == ["max_value"]
        assert len(rows) == 1
        assert rows[0].failure_action == "mark_invalid"
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "location_id": "58376",
                "stored_parameter": "relative_humidity",
                "preferred_null_pm_skipped": True,
                "check_code": rows[0].check_code,
            }
        )
