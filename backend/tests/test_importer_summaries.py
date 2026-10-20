from __future__ import annotations

import json
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from qaqc.types import QCDecision
from services.import_summaries import merge_qc_counts
from sources.airgradient import importer as airgradient_importer
from sources.openaq import importer as openaq_importer
from sources.openaq import openaq_upserts
from sources.purpleair import importer as purpleair_importer


@pytest.fixture(autouse=True)
def isolate_airgradient_snapshot_summary(monkeypatch):
    monkeypatch.setattr(airgradient_importer, "import_location_history", lambda *args, **kwargs: None)


COMMON_SUMMARY = {
    "devices_processed": 0,
    "devices_created": 0,
    "sensors_processed": 0,
    "sensors_created": 0,
    "measurements_received": 0,
    "measurements_inserted": 0,
    "measurements_updated": 0,
    "measurements_skipped": 0,
}


def _session_factory(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'summaries.sqlite'}")
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_pm25_catalog(session):
    unit = models.Unit(
        code="ug_m3",
        symbol="µg/m³",
        name="Micrograms per cubic meter",
    )
    session.add(unit)
    session.flush()
    parameter = models.Parameter(
        code="pm25",
        display_name="PM2.5",
        default_unit_id=unit.unit_id,
    )
    session.add(parameter)
    session.flush()
    return unit, parameter


def _seed_airgradient_catalog(session):
    """Seed the complete canonical catalog required by AirGradient ingestion."""
    units_by_code = {}
    for code, symbol, name in (
        ("ug_m3", "µg/m³", "Micrograms per cubic meter"),
        ("ppm", "ppm", "Parts per million"),
        ("ppb", "ppb", "Parts per billion"),
        ("index", "index", "Index"),
        ("celsius", "°C", "Degrees Celsius"),
        ("percent", "%", "Percent"),
        ("hpa", "hPa", "Hectopascals"),
    ):
        unit = models.Unit(code=code, symbol=symbol, name=name)
        session.add(unit)
        units_by_code[code] = unit
    session.flush()

    parameters_by_code = {}
    for parameter_code, unit_code in (
        ("pm1", "ug_m3"),
        ("pm25", "ug_m3"),
        ("pm10", "ug_m3"),
        ("co2", "ppm"),
        ("tvoc", "ppb"),
        ("tvoc_index", "index"),
        ("nox_index", "index"),
        ("temperature", "celsius"),
        ("relative_humidity", "percent"),
        ("pressure", "hpa"),
    ):
        parameter = models.Parameter(
            code=parameter_code,
            display_name=parameter_code,
            default_unit_id=units_by_code[unit_code].unit_id,
        )
        session.add(parameter)
        session.flush()
        session.add(models.ParameterSupportedUnit(
            parameter_id=parameter.parameter_id,
            unit_id=units_by_code[unit_code].unit_id,
        ))
        parameters_by_code[parameter_code] = parameter

    return units_by_code["ug_m3"], parameters_by_code["pm25"]


def test_openaq_zero_device_run_writes_common_summary(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(openaq_importer, "SessionLocal", Session)
    summary_path = tmp_path / "openaq.json"

    summary = openaq_importer.import_measurements_from_locations(
        summary_json=str(summary_path), summary_csv=None
    )

    assert summary == COMMON_SUMMARY
    assert json.loads(summary_path.read_text(encoding="utf-8")) == COMMON_SUMMARY


def test_purpleair_zero_device_run_writes_common_summary(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    with Session() as session:
        session.add(
            models.ExternalAPI(
                provider_code="purpleair",
                name="PurpleAir",
                api_key="stored-key",
                params={},
                enabled=True,
            )
        )
        session.commit()
    monkeypatch.setattr(purpleair_importer, "SessionLocal", Session)
    summary_path = tmp_path / "purpleair.json"

    summary = purpleair_importer._run_authorized_import(str(summary_path))

    assert summary == COMMON_SUMMARY
    assert json.loads(summary_path.read_text(encoding="utf-8")) == COMMON_SUMMARY


def test_airgradient_completed_reference_initialization_still_runs_authenticated_discovery(
    tmp_path, monkeypatch
):
    Session = _session_factory(tmp_path)
    with Session() as session:
        session.add(
            models.ExternalAPI(
                provider_code="airgradient",
                name="AirGradient",
                base_url=airgradient_importer.DEFAULT_BASE_URL,
                api_key="stored-key",
                params={
                    "reference_locations_version": (
                        airgradient_importer.AIRGRADIENT_REFERENCE_LOCATIONS_VERSION
                    ),
                    "reference_discovery_version": (
                        "legacy-version"
                    ),
                    "reference_regions_selected": [],
                    "reference_regions_missing": ["metro_manila"],
                },
                enabled=True,
            )
        )
        session.commit()
    monkeypatch.setattr(airgradient_importer, "SessionLocal", Session)
    requested_paths: list[str] = []

    def fake_api_get(path, *args, **kwargs):
        requested_paths.append(path)
        if path.endswith("/place"):
            return {"id": 10, "name": "Fixture place", "timezoneId": "UTC"}
        if path.endswith("/locations/measures/current"):
            return []
        raise AssertionError("completed reference initialization must not call world endpoints")

    monkeypatch.setattr(airgradient_importer, "_api_get", fake_api_get)
    summary_path = tmp_path / "airgradient.json"

    summary = airgradient_importer.run_import(str(summary_path))

    assert {key: summary[key] for key in COMMON_SUMMARY} == COMMON_SUMMARY
    assert summary["per_parameter"] == {}
    assert "reference_discovery_attempted" not in summary
    assert "reference_regions_missing" not in summary
    assert "reference_locations_failed" not in summary
    assert [path.rsplit("/", 1)[-1] for path in requested_paths] == [
        "place",
        "current",
    ]
    assert summary["authenticated_locations_discovered"] == 0
    written = json.loads(summary_path.read_text(encoding="utf-8"))
    assert written["devices_processed"] == 0
    assert written["measurements_received"] == 0
    with Session() as session:
        source = session.query(models.ExternalAPI).one()
        assert source.params == {
            "reference_locations_version": (
                airgradient_importer.AIRGRADIENT_REFERENCE_LOCATIONS_VERSION
            ),
            "reference_locations_initialized_ids": [
                "58376",
                "175911",
                "160791",
            ],
        }


def test_measurement_upsert_returns_existing_qc_outcome_without_rerunning_qc(
    tmp_path, monkeypatch
):
    Session = _session_factory(tmp_path)
    with Session() as session:
        unit, parameter = _seed_pm25_catalog(session)
        source = models.ExternalAPI(
            provider_code="openaq",
            name="OpenAQ",
            enabled=True,
        )
        session.add(source)
        session.flush()
        device = models.Device(
            name="QC test device",
            external_api_id=source.external_api_id,
        )
        session.add(device)
        session.flush()
        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
        )
        session.add(sensor)
        session.flush()

        qc_call_count = 0

        def fake_run_ingest_detailed(records, context):
            nonlocal qc_call_count
            qc_call_count += 1
            decision = QCDecision(
                is_valid=False,
                flags=["max_value"],
                severity="warn",
            )
            return {
                "overall": [decision],
                "per_plugin": {"max_value": [decision]},
            }

        monkeypatch.setattr(
            openaq_upserts,
            "run_ingest_detailed",
            fake_run_ingest_detailed,
        )
        measurement = models.Measurement(
            sensor_id=sensor.sensor_id,
            value=1_000_001,
            observed_at="2026-08-16T12:00:00Z",
        )

        result = openaq_upserts.upsert_measurement_with_policy_detailed(
            session,
            measurement,
            device=device,
            sensor=sensor,
        )

        assert qc_call_count == 1
        assert result.action == "insert"
        assert result.qc == {
            "evaluated": 1,
            "passed": 0,
            "flagged": 1,
            "indeterminate": 0,
        }
        summary = COMMON_SUMMARY.copy()
        merge_qc_counts(summary, result.qc)
        assert summary["qc"] == result.qc


def test_openaq_common_summary_includes_actions_creation_and_qc(
    tmp_path, monkeypatch
):
    Session = _session_factory(tmp_path)
    with Session() as session:
        _seed_pm25_catalog(session)
        source = models.ExternalAPI(
            provider_code="openaq",
            name="OpenAQ",
            api_key="stored-key",
            enabled=True,
        )
        session.add(source)
        session.flush()
        session.add(
            models.Device(
                name="OpenAQ fixture",
                external_api_id=source.external_api_id,
                external_id="location-1",
            )
        )
        session.commit()

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get_metrics(self):
            return {}

    def fake_fetch_json(client, url, **kwargs):
        if url.endswith("/location-1/sensors"):
            return {"results": []}
        if url.endswith("/location-1/latest"):
            return {
                "coordinates": {"latitude": 40.7, "longitude": -74.0},
                "measurements": [
                    {
                        "parameter": "pm25",
                        "value": 12.5,
                        "unit": "µg/m³",
                        "lastUpdated": "2026-08-16T12:00:00Z",
                    }
                ],
            }
        raise AssertionError(f"Unexpected OpenAQ URL: {url}")

    monkeypatch.setattr(openaq_importer, "SessionLocal", Session)
    monkeypatch.setattr(openaq_importer, "get_api_client", lambda name: FakeClient())
    monkeypatch.setattr(openaq_importer, "fetch_json", fake_fetch_json)

    first_summary = openaq_importer.import_measurements_from_locations()
    second_summary = openaq_importer.import_measurements_from_locations()

    assert {key: first_summary[key] for key in COMMON_SUMMARY} == {
        **COMMON_SUMMARY,
        "devices_processed": 1,
        "sensors_processed": 1,
        "sensors_created": 1,
        "measurements_received": 1,
        "measurements_inserted": 1,
    }
    assert first_summary["qc"] == {
        "evaluated": 1,
        "passed": 1,
        "flagged": 0,
        "indeterminate": 0,
    }
    assert second_summary["measurements_received"] == 1
    assert second_summary["measurements_skipped"] == 1
    assert "qc" not in second_summary


def test_airgradient_common_summary_includes_actions_and_qc(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    with Session() as session:
        unit, parameter = _seed_airgradient_catalog(session)
        source = models.ExternalAPI(
            provider_code="airgradient",
            name="AirGradient",
            base_url=airgradient_importer.DEFAULT_BASE_URL,
            api_key="stored-key",
            params={
                "reference_locations_version": (
                    airgradient_importer.AIRGRADIENT_REFERENCE_LOCATIONS_VERSION
                )
            },
            enabled=True,
        )
        session.add(source)
        session.flush()
        device = models.Device(
            name="AirGradient fixture",
            external_api_id=source.external_api_id,
            external_id="101",
        )
        session.add(device)
        session.flush()
        session.add(
            models.Sensor(
                device_id=device.device_id,
                parameter_id=parameter.parameter_id,
                unit_id=unit.unit_id,
                external_sensor_id="101:pm02",
            )
        )
        session.commit()

    monkeypatch.setattr(airgradient_importer, "SessionLocal", Session)
    measurement_payload = {
        "locationId": 101,
        "locationName": "AirGradient fixture",
        "timestamp": "2026-08-16T12:00:00Z",
        "pm02": 8.5,
    }

    def fake_api_get(path, *args, **kwargs):
        if path.endswith("/place"):
            return {"id": 10, "name": "Fixture place", "timezoneId": "UTC"}
        if path.endswith("/locations/measures/current"):
            return [measurement_payload]
        return measurement_payload

    monkeypatch.setattr(
        airgradient_importer,
        "_api_get",
        fake_api_get,
    )

    summary = airgradient_importer.run_import()

    assert {key: summary[key] for key in COMMON_SUMMARY} == {
        **COMMON_SUMMARY,
        "devices_processed": 1,
        "sensors_processed": 1,
        "measurements_received": 1,
        "measurements_inserted": 1,
    }
    assert summary["qc"] == {
        "evaluated": 1,
        "passed": 1,
        "flagged": 0,
        "indeterminate": 0,
    }
    assert summary["per_parameter"] == {
        "pm25": {"insert": 1, "update": 0, "skip": 0}
    }


def test_airgradient_reference_failure_is_reported_only_on_initialization_run(
    tmp_path, monkeypatch
):
    Session = _session_factory(tmp_path)
    with Session() as session:
        _seed_airgradient_catalog(session)
        session.add(
            models.ExternalAPI(
                provider_code="airgradient",
                name="AirGradient",
                base_url=airgradient_importer.DEFAULT_BASE_URL,
                api_key="stored-key",
                params={
                    "reference_discovery_version": "legacy-version",
                    "reference_regions_missing": ["rio_de_janeiro"],
                },
                enabled=True,
            )
        )
        session.commit()

    payloads = {
        "58376": {
            "locationId": 58376,
            "locationName": "Provider New York",
            "latitude": 40.940119,
            "longitude": -73.7561704,
            "timezone": "America/New_York",
            "timestamp": "2026-08-17T04:00:00Z",
            "pm02": 8.5,
        },
        "160791": {
            "locationId": 160791,
            "locationName": "Provider Manila",
            "latitude": 14.6354,
            "longitude": 121.0779,
            "timezone": "Asia/Taipei",
            "timestamp": "2026-08-17T04:00:00Z",
            "pm02": 6.5,
        },

    }
    payloads["175911"] = {
        "locationId": 175911, "locationName": "São Paulo", "latitude": -23.6473149,
        "longitude": -46.6643635, "timezone": "America/Sao_Paulo",
        "timestamp": "2026-08-17T04:00:00Z", "pm02": 8.0,
    }
    requested_ids: list[str] = []
    manila_failures_remaining = 1

    def fake_api_get(path, *args, **kwargs):
        nonlocal manila_failures_remaining
        if path.endswith("/place"):
            return {"id": 10, "name": "Fixture place", "timezoneId": "UTC"}
        if path.endswith("/locations/measures/current"):
            return []
        location_id = path.split("/world/locations/")[1].split("/")[0]
        requested_ids.append(location_id)
        if location_id == "160791" and manila_failures_remaining > 0:
            manila_failures_remaining -= 1
            raise airgradient_importer.AirGradientImporterError("HTTP 404")
        return payloads[location_id]

    monkeypatch.setattr(airgradient_importer, "SessionLocal", Session)
    monkeypatch.setattr(airgradient_importer, "_api_get", fake_api_get)
    monkeypatch.setattr(airgradient_importer, "_emit_event", lambda *args, **kwargs: None)

    first_summary = airgradient_importer.run_import()

    assert requested_ids == ["58376", "175911", "160791"]
    assert first_summary["reference_locations_failed"] == [
        {"region": "metro_manila", "location_id": "160791", "reason": "HTTP 404"}
    ]
    assert {
        location["location_id"]
        for location in first_summary["reference_locations_initialized"]
    } == {"58376", "175911"}
    assert "reference_regions_missing" not in first_summary

    requested_ids.clear()
    second_summary = airgradient_importer.run_import()

    assert requested_ids == ["160791", "58376", "175911"]
    assert "reference_locations_failed" not in second_summary
    assert second_summary["reference_locations_initialized"] == [
        {"region": "metro_manila", "location_id": "160791"}
    ]
    assert "reference_regions_missing" not in second_summary

    requested_ids.clear()
    third_summary = airgradient_importer.run_import()

    assert requested_ids == ["58376", "175911", "160791"]
    assert "reference_locations_failed" not in third_summary
    assert "reference_locations_initialized" not in third_summary
    assert "reference_regions_missing" not in third_summary
