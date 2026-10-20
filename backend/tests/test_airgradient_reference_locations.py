from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import models
from api.main import app
from db import get_session
from sources.airgradient import importer


@pytest.fixture(autouse=True)
def isolate_dashboard_snapshot_contract(monkeypatch):
    """This suite exercises Dashboard snapshots; Map history has its own suite."""
    monkeypatch.setattr(importer, "import_location_history", lambda *args, **kwargs: None)


def _provider_location(
    location_id: str,
    name: str,
    latitude: float,
    longitude: float,
    timezone: str,
    **measurements,
) -> dict:
    return {
        "locationId": int(location_id),
        "locationName": name,
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "timestamp": "2026-08-17T04:00:00Z",
        **measurements,
    }


def _provider_payloads() -> dict[str, dict]:
    return {
        "58376": _provider_location(
            "58376",
            "Provider New York",
            40.940119,
            -73.7561704,
            "America/New_York",
            pm02_corrected=8.2,
            pm02=8.0,
            pm10=12.0,
            publicContributorName="Clean Air Neighbors",
            publicPlaceUrl="https://example.org/clean-air-neighbors",
            unsupported_field=99,
        ),
        "175911": _provider_location(
            "175911", "São Paulo", -23.6473149, -46.6643635,
            "America/Sao_Paulo", pm02=8.0,
        ),
        "160791": _provider_location(
            "160791",
            "Provider Manila",
            14.6354,
            121.0779,
            "Asia/Taipei",
            pm01=3.0,
            rhum=71,
            tvoc=None,
        ),
    }


def _reference_session(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'airgradient.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

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

    parameter_units = {
        "pm1": "ug_m3",
        "pm25": "ug_m3",
        "pm10": "ug_m3",
        "co2": "ppm",
        "tvoc": "ppb",
        "tvoc_index": "index",
        "nox_index": "index",
        "temperature": "celsius",
        "relative_humidity": "percent",
        "pressure": "hpa",
    }
    for parameter_code, unit_code in parameter_units.items():
        parameter = models.Parameter(
            code=parameter_code,
            display_name=parameter_code,
            default_unit_id=units_by_code[unit_code].unit_id,
        )
        session.add(parameter)
        session.flush()
        session.add(
            models.ParameterSupportedUnit(
                parameter_id=parameter.parameter_id,
                unit_id=units_by_code[unit_code].unit_id,
            )
        )

    source = models.ExternalAPI(
        provider_code="airgradient",
        name="AirGradient",
        base_url=importer.DEFAULT_BASE_URL,
        api_key="stored-key",
        params={
            "unrelated_setting": "preserved",
            "reference_discovery_version": "legacy-version",
            "reference_regions_selected": [{"region_code": "new_york"}],
            "reference_regions_missing": ["rio_de_janeiro"],
        },
        enabled=True,
    )
    session.add(source)
    session.commit()
    return session, source


def _mock_direct_location_requests(monkeypatch, payloads, requested_paths):
    def fake_api_get(path, api_key, params=None, include_token=True):
        requested_paths.append(path)
        if path.endswith("/place"):
            return {"id": 42, "name": "Fixture place", "timezoneId": "UTC"}
        if path.endswith("/locations/measures/current"):
            return []
        location_id = path.split("/world/locations/")[1].split("/")[0]
        response = payloads[location_id]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(importer, "_api_get", fake_api_get)


def test_fixed_reference_configuration_contains_only_approved_location_ids():
    assert {
        location["code"]: location["location_id"]
        for location in importer.AIRGRADIENT_REFERENCE_LOCATIONS
    } == {
        "new_york": "58376",
        "south_america_rio_reference": "175911",
        "metro_manila": "160791",
    }


def test_provider_field_preference_uses_present_corrected_field_even_when_null():
    assert importer._preferred_present_supported_fields(
        {"pm02_corrected": None, "pm02": 8.0}
    ) == {"pm25": "pm02_corrected"}


def test_expected_frequency_uses_documented_wifi_and_cellular_model_identity():
    assert importer._expected_frequency_seconds({"model": "O-1PST"}) == 60
    assert importer._expected_frequency_seconds({"model": "I-9PSL-DE"}) == 60
    assert importer._expected_frequency_seconds({"model": "O-1PST-CE"}) == 180
    assert importer._expected_frequency_seconds({"model": "I-9PSL-DE-CE"}) == 180


def test_every_supported_field_uses_canonical_parameter_and_unit_codes():
    expected_pairs = {
        "pm1": "ug_m3",
        "pm25": "ug_m3",
        "pm10": "ug_m3",
        "co2": "ppm",
        "temperature": "celsius",
        "relative_humidity": "percent",
        "pressure": "hpa",
        "tvoc": "ppb",
        "tvoc_index": "index",
        "nox_index": "index",
    }

    assert {
        definition.parameter_code: definition.unit_code
        for definition in importer.AIRGRADIENT_FIELD_DEFINITIONS.values()
    } == expected_pairs
    assert importer._normalize_param("temp") == ("temperature", "celsius")
    assert importer._normalize_param("rhum") == ("relative_humidity", "percent")
    assert importer._normalize_param("atmpCompensated") == (
        "temperature",
        "celsius",
    )
    assert importer._normalize_param("rhumCompensated") == (
        "relative_humidity",
        "percent",
    )
    assert importer._normalize_param("tvocIndex") == ("tvoc_index", "index")
    assert importer._normalize_param("noxIndex") == ("nox_index", "index")
    assert "nox" not in importer.AIRGRADIENT_FIELD_DEFINITIONS
    assert "voc" not in importer.AIRGRADIENT_FIELD_DEFINITIONS


def test_sensor_creation_rejects_an_unregistered_canonical_pair(tmp_path):
    session, source = _reference_session(tmp_path)
    try:
        temperature = session.scalar(
            select(models.Parameter).where(models.Parameter.code == "temperature")
        )
        session.execute(
            models.ParameterSupportedUnit.__table__.delete().where(
                models.ParameterSupportedUnit.parameter_id
                == temperature.parameter_id
            )
        )
        session.flush()
        device = models.Device(
            name="Invariant test",
            external_id="900001",
            external_api_id=source.external_api_id,
        )
        session.add(device)
        session.flush()

        with pytest.raises(
            importer.AirGradientImporterError,
            match="supported_pairs=temperature/celsius",
        ):
            importer._ensure_airgradient_sensors(
                session,
                device,
                {"locationId": 900001, "atmp": 21.5},
            )
    finally:
        session.close()


def test_initialization_fetches_only_fixed_locations_and_uses_provider_metadata(
    tmp_path, monkeypatch
):
    session, source = _reference_session(tmp_path)
    requested_paths: list[str] = []
    _mock_direct_location_requests(
        monkeypatch, _provider_payloads(), requested_paths
    )

    try:
        result = importer._initialize_reference_locations(
            session,
            source,
            "stored-key",
            importer.DEFAULT_BASE_URL,
        )
        session.commit()

        expected_paths = [
            f"{importer.DEFAULT_BASE_URL}/world/locations/"
            f"{reference['location_id']}/measures/current"
            for reference in importer.AIRGRADIENT_REFERENCE_LOCATIONS
        ]
        assert requested_paths == expected_paths
        assert all(
            not path.endswith("/world/locations/measures/current")
            for path in requested_paths
        )
        assert result["devices_created"] == 3
        assert result["sensors_created"] == 6
        assert result["locations_failed"] == []

        devices = {
            device.external_id: device
            for device in session.scalars(select(models.Device)).all()
        }
        assert set(devices) == {"58376", "175911", "160791"}
        assert devices["58376"].name == "Provider New York"
        assert devices["58376"].latitude == 40.940119
        assert devices["58376"].longitude == -73.7561704
        assert devices["160791"].name == "Provider Manila"
        assert devices["58376"].timezone == "America/New_York"
        assert devices["58376"].acquisition_path == "airgradient_public_reference"
        assert devices["58376"].contributor_name == "Clean Air Neighbors"
        assert devices["58376"].contributor_url == "https://example.org/clean-air-neighbors"
        assert devices["58376"].license_code == "CC-BY-SA-4.0"
        assert devices["58376"].license_share_alike is True
        # The approved reference location owns site timezone identity even when
        # the provider returns a same-offset but geographically wrong IANA name.
        assert devices["160791"].timezone == "Asia/Manila"

        sensor_ids = set(
            session.scalars(select(models.Sensor.external_sensor_id)).all()
        )
        assert sensor_ids == {
            "58376:pm02_corrected",
            "58376:pm10",
            "175911:pm02",
            "160791:pm01",
            "160791:rhum",
            "160791:tvoc",
        }
        aggregation_codes = dict(
            session.execute(
                select(
                    models.AggregationPeriod.aggregation_period_id,
                    models.AggregationPeriod.code,
                )
            ).all()
        )
        for sensor in session.scalars(select(models.Sensor)).all():
            assert aggregation_codes[sensor.aggregation_period_id] == "1m"
            assert sensor.expected_frequency_seconds == 60
            assert sensor.measurement_duration_seconds == 12
            assert sensor.source_aggregation_duration_seconds == 12
            assert sensor.measurement_timestamp_semantics == "observation_instant"
        assert source.params == {
            "unrelated_setting": "preserved",
            "reference_locations_version": (
                importer.AIRGRADIENT_REFERENCE_LOCATIONS_VERSION
            ),
            "reference_locations_initialized_ids": [
                "58376",
                "175911",
                "160791",
            ],
        }
    finally:
        session.close()


def test_normal_imports_respect_deletion_and_explicit_restore_uses_fixed_ids(
    tmp_path, monkeypatch
):
    session, source = _reference_session(tmp_path)
    Session = sessionmaker(bind=session.get_bind())
    payloads = _provider_payloads()
    requested_paths: list[str] = []
    _mock_direct_location_requests(monkeypatch, payloads, requested_paths)

    try:
        importer._initialize_reference_locations(
            session, source, "stored-key", importer.DEFAULT_BASE_URL
        )
        session.commit()
        deleted_device = session.scalar(
            select(models.Device).where(models.Device.external_id == "58376")
        )
        session.delete(deleted_device)
        session.commit()

        requested_paths.clear()
        _mock_direct_location_requests(
            monkeypatch, payloads, requested_paths
        )
        monkeypatch.setattr(importer, "SessionLocal", Session)
        normal_summary = importer.run_import()

        assert normal_summary["devices_created"] == 0
        assert "reference_locations_initialized" not in normal_summary
        assert "reference_locations_failed" not in normal_summary
        assert {
            path.split("/world/locations/")[1].split("/")[0]
            for path in requested_paths
            if "/world/locations/" in path
        } == {"175911", "160791"}
        assert session.scalar(select(func.count()).select_from(models.Device)) == 2

        requested_paths.clear()
        _mock_direct_location_requests(monkeypatch, payloads, requested_paths)
        restored = importer.restore_airgradient_reference_locations(session)
        session.commit()

        assert restored["devices_created"] == 1
        assert set(
            session.scalars(select(models.Device.external_id)).all()
        ) == {"58376", "175911", "160791"}
        assert [path for path in requested_paths if "/world/locations/" in path] == [
            f"{importer.DEFAULT_BASE_URL}/world/locations/"
            f"{reference['location_id']}/measures/current"
            for reference in importer.AIRGRADIENT_REFERENCE_LOCATIONS
        ]
    finally:
        session.close()


def test_unavailable_or_mismatched_location_fails_without_a_substitute(
    tmp_path, monkeypatch
):
    session, source = _reference_session(tmp_path)
    payloads = _provider_payloads()
    payloads["160791"] = {
        **payloads["160791"],
        "locationId": 999999,
        "locationName": "Nearby alternative",
    }
    requested_paths: list[str] = []
    emitted_events: list[dict] = []
    _mock_direct_location_requests(monkeypatch, payloads, requested_paths)
    monkeypatch.setattr(
        importer,
        "_emit_event",
        lambda *args, **kwargs: emitted_events.append(kwargs),
    )

    try:
        result = importer._initialize_reference_locations(
            session, source, "stored-key", importer.DEFAULT_BASE_URL
        )
        session.commit()

        assert result["locations_failed"][0]["region"] == "metro_manila"
        assert result["locations_failed"][0]["location_id"] == "160791"
        assert "unexpected location IDs" in result["locations_failed"][0]["reason"]
        assert {
            location["location_id"] for location in result["locations_initialized"]
        } == {"58376", "175911"}
        assert set(
            session.scalars(select(models.Device.external_id)).all()
        ) == {"58376", "175911"}
        assert "999999" not in set(
            session.scalars(select(models.Device.external_id)).all()
        )
        failure_event = next(event for event in emitted_events if "location_id" in event.get("payload", {}))
        assert failure_event["payload"] == result["locations_failed"][0]
        assert source.params["reference_locations_initialized_ids"] == [
            "58376",
            "175911",
        ]

        payloads["160791"] = _provider_payloads()["160791"]
        requested_paths.clear()
        _mock_direct_location_requests(
            monkeypatch, payloads, requested_paths
        )
        retried = importer._initialize_reference_locations(
            session, source, "stored-key", importer.DEFAULT_BASE_URL
        )
        session.commit()

        assert requested_paths == [
            f"{importer.DEFAULT_BASE_URL}/world/locations/160791/measures/current"
        ]
        assert retried["locations_initialized"] == [
            {"region": "metro_manila", "location_id": "160791"}
        ]
        assert retried["locations_failed"] == []
        assert source.params["reference_locations_initialized_ids"] == [
            "58376",
            "175911",
            "160791",
        ]

        monkeypatch.setattr(
            importer,
            "_api_get",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("successful locations must not be reinitialized")
            ),
        )
        completed = importer._initialize_reference_locations(
            session, source, "stored-key", importer.DEFAULT_BASE_URL
        )
        assert completed["attempted"] is False
    finally:
        session.close()


def test_prior_global_marker_uses_job_summary_to_preserve_deleted_success(
    tmp_path, monkeypatch
):
    session, source = _reference_session(tmp_path)
    requested_paths: list[str] = []
    _mock_direct_location_requests(
        monkeypatch, _provider_payloads(), requested_paths
    )

    try:
        initialized = importer._initialize_reference_locations(
            session, source, "stored-key", importer.DEFAULT_BASE_URL
        )
        session.commit()
        source.params = {
            "reference_locations_version": (
                importer.AIRGRADIENT_REFERENCE_LOCATIONS_VERSION
            )
        }
        deleted_device = session.scalar(
            select(models.Device).where(models.Device.external_id == "58376")
        )
        session.delete(deleted_device)
        schedule = models.JobSchedule(
            task="airgradient_import",
            cron_expr="0 * * * *",
        )
        session.add(schedule)
        session.flush()
        session.add(
            models.JobRun(
                job_schedule_id=schedule.job_schedule_id,
                status="success",
                summary={
                    "reference_locations_initialized": initialized[
                        "locations_initialized"
                    ]
                },
            )
        )
        session.commit()

        monkeypatch.setattr(
            importer,
            "_api_get",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("a deleted successful location must not be retried")
            ),
        )
        migrated = importer._initialize_reference_locations(
            session, source, "stored-key", importer.DEFAULT_BASE_URL
        )
        session.commit()

        assert migrated["attempted"] is False
        assert source.params["reference_locations_initialized_ids"] == [
            "58376",
            "175911",
            "160791",
        ]
        assert session.scalar(select(func.count()).select_from(models.Device)) == 2
    finally:
        session.close()


def test_null_supported_field_creates_sensor_then_later_numeric_value_imports(
    tmp_path, monkeypatch
):
    setup_session, _source = _reference_session(tmp_path)
    Session = sessionmaker(bind=setup_session.get_bind())
    setup_session.close()
    payloads = _provider_payloads()
    requested_paths: list[str] = []
    _mock_direct_location_requests(monkeypatch, payloads, requested_paths)
    monkeypatch.setattr(importer, "SessionLocal", Session)

    first_summary = importer.run_import(location_ids=[160791])

    assert first_summary["sensors_created"] == 6
    assert first_summary["measurements_received"] == 3
    assert first_summary["measurements_inserted"] == 2
    assert first_summary["measurements_skipped"] == 1
    assert first_summary["per_parameter"]["tvoc"] == {
        "insert": 0,
        "update": 0,
        "skip": 1,
    }
    with Session() as session:
        tvoc_sensor = session.scalar(
            select(models.Sensor).where(
                models.Sensor.external_sensor_id == "160791:tvoc"
            )
        )
        assert tvoc_sensor is not None
        assert session.scalar(
            select(func.count())
            .select_from(models.Measurement)
            .where(models.Measurement.sensor_id == tvoc_sensor.sensor_id)
        ) == 0

    payloads["160791"] = {
        **payloads["160791"],
        "timestamp": "2026-08-17T04:05:00Z",
        "tvoc": 35,
    }
    requested_paths.clear()
    second_summary = importer.run_import(location_ids=[160791])

    assert [path for path in requested_paths if "/world/locations/" in path] == [
        f"{importer.DEFAULT_BASE_URL}/world/locations/160791/measures/current"
    ]
    assert second_summary["sensors_created"] == 0
    assert second_summary["measurements_received"] == 3
    assert second_summary["measurements_inserted"] == 3
    assert second_summary["measurements_skipped"] == 0
    with Session() as session:
        tvoc_sensors = session.scalars(
            select(models.Sensor).where(
                models.Sensor.external_sensor_id == "160791:tvoc"
            )
        ).all()
        assert len(tvoc_sensors) == 1
        assert session.scalar(
            select(func.count())
            .select_from(models.Measurement)
            .where(models.Measurement.sensor_id == tvoc_sensors[0].sensor_id)
        ) == 1


def test_all_verified_fields_create_stable_canonical_streams_and_ingest(
    tmp_path, monkeypatch
):
    setup_session, source = _reference_session(tmp_path)
    source.params = {
        "reference_locations_version": importer.AIRGRADIENT_REFERENCE_LOCATIONS_VERSION,
        "reference_locations_initialized_ids": [
            location["location_id"]
            for location in importer.AIRGRADIENT_REFERENCE_LOCATIONS
        ],
    }
    device = models.Device(
        name="AirGradient complete fixture",
        external_id="58376",
        external_api_id=source.external_api_id,
        timezone="America/New_York",
    )
    setup_session.add(device)
    setup_session.commit()
    device_id = device.device_id
    Session = sessionmaker(bind=setup_session.get_bind())
    setup_session.close()

    payload = _provider_location(
        "58376",
        "AirGradient complete fixture",
        40.940119,
        -73.7561704,
        "America/New_York",
        pm01=3.1,
        pm02=7.2,
        pm10=9.3,
        rco2=430.0,
        atmp=21.5,
        rhum=45.0,
        pres=1013.25,
        tvoc=35.2,
        tvocIndex=110.0,
        noxIndex=2.0,
    )
    monkeypatch.setattr(importer, "SessionLocal", Session)
    def fake_api_get(path, api_key, params=None, include_token=True):
        if path.endswith("/place"):
            return {"id": 42, "name": "Fixture place", "timezoneId": "UTC"}
        if path.endswith("/locations/measures/current"):
            return []
        return payload

    monkeypatch.setattr(importer, "_api_get", fake_api_get)

    first_summary = importer.run_import(location_ids=[58376])
    second_summary = importer.run_import(location_ids=[58376])

    assert first_summary["sensors_created"] == 10
    assert first_summary["measurements_received"] == 10
    assert first_summary["measurements_inserted"] == 10
    assert first_summary["qc"] == {
        "evaluated": 6,
        "passed": 6,
        "flagged": 0,
        "indeterminate": 0,
    }
    assert second_summary["sensors_created"] == 0
    with Session() as session:
        rows = session.execute(
            select(
                models.Sensor.external_sensor_id,
                models.Parameter.code,
                models.Unit.code,
                models.Measurement.value,
            )
            .join(models.Parameter, models.Parameter.parameter_id == models.Sensor.parameter_id)
            .join(models.Unit, models.Unit.unit_id == models.Sensor.unit_id)
            .join(models.Measurement, models.Measurement.sensor_id == models.Sensor.sensor_id)
            .order_by(models.Parameter.code)
        ).all()

        assert len(rows) == 10
        identity_by_parameter = {
            parameter_code: (external_sensor_id, unit_code, value)
            for external_sensor_id, parameter_code, unit_code, value in rows
        }
        assert identity_by_parameter == {
            "co2": ("58376:rco2", "ppm", 430.0),
            "nox_index": ("58376:noxIndex", "index", 2.0),
            "pm1": ("58376:pm01", "ug_m3", 3.1),
            "pm10": ("58376:pm10", "ug_m3", 9.3),
            "pm25": ("58376:pm02", "ug_m3", 7.2),
            "pressure": ("58376:pres", "hpa", 1013.25),
            "relative_humidity": ("58376:rhum", "percent", 45.0),
            "temperature": ("58376:atmp", "celsius", 21.5),
            "tvoc": ("58376:tvoc", "ppb", 35.2),
            "tvoc_index": ("58376:tvocIndex", "index", 110.0),
        }

    def override_session():
        with Session() as api_session:
            yield api_session

    app.dependency_overrides[get_session] = override_session
    try:
        response = TestClient(app).get(
            "/measurements/temperature/latest",
            params={"device_id": device_id},
        )
        assert response.status_code == 200, response.text
        api_rows = response.json()
        assert len(api_rows) == 1
        assert {
            "external_sensor_id": api_rows[0]["external_sensor_id"],
            "parameter": api_rows[0]["parameter"],
            "parameter_name": api_rows[0]["parameter_name"],
            "value": api_rows[0]["value"],
            "unit": api_rows[0]["unit"],
            "source": api_rows[0]["device"]["network"],
        } == {
            "external_sensor_id": "58376:atmp",
            "parameter": "temperature",
            "parameter_name": "temperature",
            "value": 21.5,
            "unit": "°C",
            "source": "AirGradient",
        }
        assert api_rows[0]["device"]["data_attribution"] == {
            "acquisition_path": "airgradient_public_reference",
            "data_provider_name": "AirGradient",
            "hardware_provider_name": "AirGradient",
            "provider_url": "https://www.airgradient.com",
            "contributor_name": None,
            "contributor_url": None,
            "license_code": "CC-BY-SA-4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "license_share_alike": True,
        }
    finally:
        app.dependency_overrides.pop(get_session, None)
