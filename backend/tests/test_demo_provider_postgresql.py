"""Offline acceptance on isolated, fully migrated PostgreSQL/PostGIS databases."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session, sessionmaker

import models
from api.main import app
from api.routes import setup
from api.routes.admin.external_apis import get_external_api, update_external_api, ExternalAPIUpdateIn
from db import get_session
from jobs.source_activation import initial_source_import_is_due
from postgresql_test_support import POSTGRES_TEST_URL_ENV, temporary_postgres_database, upgrade, downgrade
from services.external_sources import ExternalSourceNotRunnable, ensure_builtin_external_apis
from sources.demo.importer import (
    CADENCE_SECONDS, INITIAL_SEED_SLOTS, SENSOR_DEFINITIONS,
    DEMO_LATITUDE, DEMO_LONGITUDE, aligned_slot, values_for_slot, import_current_slot,
)
from services.device_locations import set_device_location

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def database():
    if not os.getenv(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} for PostgreSQL acceptance")
    with temporary_postgres_database("demo") as (url, engine):
        yield url, engine


def source(session):
    return session.scalars(select(models.ExternalAPI).where(models.ExternalAPI.provider_code == "demo")).one()


def count(session):
    return session.scalar(select(func.count()).select_from(models.Measurement))


def activate(engine):
    with Session(engine) as session, session.begin():
        session.scalars(select(models.SystemSettings)).one().is_system_setup_complete = True


def run(engine, now=NOW):
    with Session(engine) as session, session.begin():
        return import_current_slot(session, now=now)


def seed_historical_demo(engine):
    """Seed the old schema with the backend's synthetic values, without today's ORM."""
    slot = aligned_slot(NOW)
    slots = [slot - timedelta(seconds=CADENCE_SECONDS * i)
             for i in reversed(range(INITIAL_SEED_SLOTS))]
    with engine.begin() as connection:
        source_id = connection.scalar(text(
            "SELECT external_api_id FROM external_api WHERE provider_code = 'demo'"
        ))
        connection.execute(text("UPDATE system_settings SET is_system_setup_complete = true"))
        device_id = connection.scalar(text(
            "INSERT INTO device (external_api_id, external_id, acquisition_path, name, "
            "hardware_provider_name, timezone, allow_updates, location) "
            "VALUES (:source_id, 'compassaq-sample-station', 'demo_fixture', "
            "'DEMO — CompassAQ Sample Station', 'Demo Data — synthetic fixture', 'UTC', 'deny', "
            "ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)) RETURNING device_id"
        ), {"source_id": source_id, "latitude": DEMO_LATITUDE, "longitude": DEMO_LONGITUDE})
        connection.execute(text(
            "INSERT INTO device_location_history (device_id, location, effective_from) "
            "SELECT device_id, location, :started_at FROM device WHERE device_id = :device_id"
        ), {"device_id": device_id, "started_at": slots[0] - timedelta(seconds=CADENCE_SECONDS)})
        for index, (parameter_code, unit_code, sensor_name) in enumerate(SENSOR_DEFINITIONS):
            sensor_id = connection.scalar(text(
                "INSERT INTO sensor (device_id, external_sensor_id, parameter_id, unit_id, "
                "aggregation_period_id, allow_updates, expected_frequency_seconds, "
                "measurement_duration_seconds, source_aggregation_duration_seconds, "
                "measurement_timestamp_semantics, measurement_metadata_status, measurement_metadata_managed_by) "
                "SELECT :device_id, :sensor_name, p.parameter_id, u.unit_id, a.aggregation_period_id, "
                "'deny', :cadence, :cadence, :cadence, 'interval_end', 'provider_documented', 'demo_importer' "
                "FROM parameter p CROSS JOIN unit u CROSS JOIN aggregation_period a "
                "WHERE p.code = :parameter AND u.code = :unit AND a.code = '5m' RETURNING sensor_id"
            ), {"device_id": device_id, "sensor_name": sensor_name, "cadence": CADENCE_SECONDS,
                "parameter": parameter_code, "unit": unit_code})
            assert sensor_id is not None
            connection.execute(text(
                "INSERT INTO measurement (sensor_id, observed_at, value, is_valid) "
                "VALUES (:sensor_id, :observed_at, :value, true)"
            ), [{"sensor_id": sensor_id, "observed_at": observed_at,
                 "value": values_for_slot(observed_at)[index]} for observed_at in slots])
        connection.execute(text(
            "UPDATE demo_import_state SET initial_seed_pending = false, activated_at = :slot "
            "WHERE external_api_id = :source_id"
        ), {"slot": slot, "source_id": source_id})
        assert connection.scalar(text("SELECT count(*) FROM sensor")) == 3
        assert connection.scalar(text("SELECT count(*) FROM measurement")) == 54


def test_demo_downgrade_refuses_to_discard_durable_activation_state(database):
    url, engine = database
    upgrade(url, "20260906_0023")
    with engine.connect() as connection:
        before = connection.execute(text("SELECT * FROM demo_import_state ORDER BY external_api_id")).all()
    with pytest.raises(RuntimeError, match="Demo migration cannot be downgraded"):
        downgrade(url, "20260905_0022")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260906_0023"
        assert connection.execute(text("SELECT * FROM demo_import_state ORDER BY external_api_id")).all() == before


def test_clean_setup_persists_opt_out_and_gates_first_seed(database):
    url, engine = database
    upgrade(url)
    with Session(engine) as session:
        demo = source(session)
        assert demo.enabled is True
        state = get_external_api(demo.external_api_id, session)
        assert state.name == "Demo Data"
        assert state.provider_code == "demo"
        assert state.requires_credential is False
        assert state.is_configured and state.is_runnable and not state.has_api_key
        assert state.description and not state.can_delete
        assert import_current_slot(session, now=NOW)["skip_reason"] == "setup_incomplete"
        assert count(session) == 0
        assert session.scalar(select(func.count()).select_from(models.Device)) == 0
        setup.configure_data_source(setup.ConfigureDataSourceRequest(
            external_api_id=demo.external_api_id, enabled=False), session)
    with Session(engine) as session:
        ensure_builtin_external_apis(session)
        assert source(session).enabled is False
        available = setup.list_data_sources(session)
        item = next(s for s in available.data_sources if s.provider_code == "demo")
        assert item.requires_credential is False and item.is_configured and not item.enabled
        source(session).enabled = True
        session.commit()
    activate(engine)
    with Session(engine) as session:
        job = session.scalars(select(models.JobSchedule).where(models.JobSchedule.task == "demo_import")).one()
        assert job.cron_expr == "*/5 * * * *" and job.enabled
        assert initial_source_import_is_due(session, job)
    summary = run(engine)
    assert summary["initial_seed"] and summary["measurements_inserted"] == 54
    assert summary["devices_created"] == 1 and summary["sensors_created"] == 3
    assert summary["qc"]["evaluated"] == 54
    with Session(engine) as session:
        device = session.scalars(select(models.Device)).one()
        assert device.name == "DEMO — CompassAQ Sample Station"
        assert "Not a real monitoring location" in device.friendly_name
        assert device.latitude == DEMO_LATITUDE == 52.0907
        assert device.longitude == DEMO_LONGITUDE == 5.1214
        assert device.external_api.provider_code == "demo"
        sensors = session.scalars(select(models.Sensor)).all()
        assert {s.external_sensor_id for s in sensors} == {"DEMO PM2.5", "DEMO PM10", "DEMO Ozone"}
        assert {session.get(models.Parameter, s.parameter_id).code for s in sensors} == {"pm25", "pm10", "o3"}
        for sensor in sensors:
            assert sensor.expected_frequency_seconds == 300
            assert session.get(models.Unit, sensor.unit_id).code == ("ppm" if sensor.external_sensor_id == "DEMO Ozone" else "ug_m3")
        rows = session.scalars(select(models.Measurement)).all()
        assert {r.sensor.device.external_api.provider_code for r in rows} == {"demo"}
        assert min(r.observed_at for r in rows) == NOW - timedelta(minutes=85)
        assert max(r.observed_at for r in rows) == NOW
        assert all(r.observed_at.minute % 5 == 0 and r.observed_at.second == 0 for r in rows)


@pytest.mark.parametrize("setup_complete", [False, True])
def test_upgrade_never_enables_or_seeds_demo_even_with_unfinished_setup(database, setup_complete):
    url, engine = database
    upgrade(url, "20260905_0022")
    with engine.begin() as connection:
        connection.execute(text("UPDATE system_settings SET is_system_setup_complete = :complete"), {"complete": setup_complete})
        before = connection.execute(text("SELECT provider_code, enabled, api_key, params::text FROM external_api ORDER BY provider_code")).all()
    upgrade(url)
    with Session(engine) as session:
        assert not source(session).enabled
        assert count(session) == 0
        after = session.execute(text("SELECT provider_code, enabled, api_key, params::text FROM external_api WHERE provider_code != 'demo' ORDER BY provider_code")).all()
        assert after == before
        assert not session.get(models.DemoImportState, source(session).external_api_id).initial_seed_pending
        source(session).enabled = True
        session.commit()
    activate(engine)
    assert run(engine)["measurements_inserted"] == 3


def test_disable_reenable_restart_and_concurrent_runs_preserve_history(database):
    url, engine = database
    upgrade(url)
    activate(engine)
    # Concurrent first activations must share exactly one seed and one device.
    with ThreadPoolExecutor(max_workers=2) as pool:
        summaries = list(pool.map(lambda _: run(engine), range(2)))
    assert sorted(s["measurements_inserted"] for s in summaries) == [0, 54]
    assert run(engine)["measurements_skipped"] == 3
    assert run(engine, NOW + timedelta(minutes=5))["measurements_inserted"] == 3
    with Session(engine) as session:
        update_external_api(source(session).external_api_id, ExternalAPIUpdateIn(enabled=False), session)
    with pytest.raises(ExternalSourceNotRunnable):
        run(engine, NOW + timedelta(days=3))
    with Session(engine) as session:
        assert count(session) == 57
        update_external_api(source(session).external_api_id, ExternalAPIUpdateIn(enabled=True, params={}), session)
    later = NOW + timedelta(days=3, minutes=7)
    assert run(engine, later)["measurements_inserted"] == 3
    engine.dispose()  # Recreate connections/process-local state, retain database.
    assert run(engine, later)["measurements_skipped"] == 3
    assert run(engine, later + timedelta(days=5))["measurements_inserted"] == 3
    with Session(engine) as session:
        assert count(session) == 63
        assert session.scalar(select(func.count()).select_from(models.Device)) == 1


def test_seed_failure_rolls_back_activation_with_measurements(database):
    url, engine = database
    upgrade(url)
    activate(engine)
    with Session(engine) as session:
        import_current_slot(session, now=NOW)
        session.rollback()
        assert count(session) == 0
        assert session.get(models.DemoImportState, source(session).external_api_id).initial_seed_pending
    assert run(engine)["measurements_inserted"] == 54


def test_normal_qc_hourly_aqi_and_public_api_provenance(database):
    url, engine = database
    upgrade(url)
    activate(engine)
    run(engine)
    # Advance the injected clock, never fabricate hourly/AQI rows or sleep.
    for i in range(1, 109):
        summary = run(engine, NOW + timedelta(minutes=5 * i))
        assert summary["qc"]["evaluated"] == 3
        assert summary["qc"]["passed"] == 3
    end = NOW + timedelta(hours=9)
    with Session(engine) as session:
        device = session.scalars(select(models.Device)).one()
        device_id = device.device_id
        sensor_ids = session.scalars(select(models.Sensor.sensor_id)).all()
        assert session.scalar(select(func.count()).select_from(models.Measurement).where(models.Measurement.is_valid.is_(False))) == 0

    def api_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = api_session
    try:
        client = TestClient(app)
        devices = client.get("/devices", params={"external_api_name": "Demo Data"})
        assert devices.status_code == 200, devices.text
        assert "DEMO — CompassAQ Sample Station" in devices.text
        assert "Demo Data" in devices.text
        for parameter in ("pm25", "pm10", "o3"):
            latest = client.get(f"/measurements/{parameter}/latest", params={
                "external_api_name": "Demo Data", "until": end.isoformat()})
            assert latest.status_code == 200, latest.text
            assert latest.json()
            assert latest.json()[0]["device"]["external_api"]["name"] == "Demo Data"
            assert latest.json()[0]["device"]["data_attribution"]["acquisition_path"] == "demo_fixture"
            hourly = client.get(f"/measurements/{parameter}/aggregate", params={
                "from": "5m", "to": "1h", "external_api_name": "Demo Data",
                "since": NOW.isoformat(), "until": end.isoformat()})
            assert hourly.status_code == 200, hourly.text
            assert hourly.json()
            assert hourly.json()[0]["device"]["external_api"]["name"] == "Demo Data"
        for sensor_id in sensor_ids:
            history = client.get(f"/sensors/{sensor_id}/history", params={
                "start": NOW.isoformat(), "end": end.isoformat(), "aggregation": "1h"})
            assert history.status_code == 200, history.text
            assert "Demo Data" in history.text
        for product in ("us_epa.pm25.nowcast", "us_epa.pm10.nowcast", "us_epa.o3.latest"):
            aqi = client.get("/air-quality-index/us_epa/latest", params={
                "product_code": product, "device_id": device_id, "until": end.isoformat()})
            assert aqi.status_code == 200, aqi.text
            result = aqi.json()["results"][0]
            assert result["calculation_status"] == "calculated", result
            assert "Demo Data" in aqi.text
            if "nowcast" in product:
                assert result["latest_completed_hour_valid_observation_count"] == 12
                assert result["latest_completed_hour_required_observation_count"] == 9
        analytics = client.post("/air-quality-index/analytics-history", json={
            "range_started_at": NOW.isoformat(),
            "range_ended_at": end.isoformat(),
            "series": [{"standard_code": "us_epa", "product_code": "us_epa.pm25.nowcast",
                        "device_id": device_id}],
        })
        assert analytics.status_code == 200, analytics.text
        assert analytics.json()["series"][0]["source_name"] == "Demo Data"
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_real_scheduler_dispatch_obeys_setup_gate_and_records_demo_job(database, monkeypatch):
    """Exercise the real subprocess in Docker, with no external provider enabled."""
    from jobs import scheduler, import_runner

    url, engine = database
    upgrade(url)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    monkeypatch.setattr(import_runner, "SessionLocal", factory)
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    monkeypatch.setenv("COMPASSAQ_TMP_DIR", "/tmp/demo-scheduler-acceptance")

    class StopAfterTick(BaseException):
        pass

    def finish_tick(_seconds):
        raise StopAfterTick()

    monkeypatch.setattr(scheduler.time, "sleep", finish_tick)
    with pytest.raises(StopAfterTick):
        scheduler.main()
    with Session(engine) as session:
        assert count(session) == 0
        assert session.scalar(select(func.count()).select_from(models.JobRun)) == 0
    activate(engine)
    with pytest.raises(StopAfterTick):
        scheduler.main()
    with Session(engine) as session:
        assert count(session) == 54
        job_run = session.scalars(select(models.JobRun)).one()
        assert job_run.status == "success", job_run.error_message
        assert job_run.execution_trigger == "scheduled"
        assert job_run.summary["measurements_inserted"] == 54
        assert job_run.summary["qc"]["evaluated"] == 54
        state = get_external_api(source(session).external_api_id, session)
        assert state.latest_import.task == "demo_import"
        assert state.latest_import.summary["initial_seed"] is True


@pytest.mark.parametrize("enabled", [True, False])
def test_setup_completion_initializes_demo_before_return(database, monkeypatch, enabled):
    url, engine = database
    upgrade(url)
    real_import = setup.import_current_slot
    calls = []

    def initialize(session, *, now):
        # A separate connection must already see committed setup authority.
        with Session(engine) as observer:
            assert observer.scalar(select(models.SystemSettings)).is_system_setup_complete
        calls.append(now)
        return real_import(session, now=NOW)

    monkeypatch.setattr(setup, "import_current_slot", initialize)
    with Session(engine) as session:
        source(session).enabled = enabled
        session.commit()
        setup.create_initial_admin(setup.CreateAdminRequest(
            email="demo-setup@example.org", password="SampleReview2026!Strong",
            confirm_password="SampleReview2026!Strong"), session)
        assert setup.complete_setup(setup.CompleteSetupRequest(default_language_code="en"), session).success
        assert count(session) == (54 if enabled else 0)
        assert session.scalar(select(func.count()).select_from(models.Device)) == (1 if enabled else 0)
        state = session.get(models.DemoImportState, source(session).external_api_id)
        assert state.initial_seed_pending is (not enabled)
        assert len(calls) == (1 if enabled else 0)
        if not enabled:
            update_external_api(source(session).external_api_id, ExternalAPIUpdateIn(enabled=True), session)
    if enabled:
        assert run(engine)["measurements_skipped"] == 3
        assert run(engine, NOW + timedelta(minutes=5))["measurements_inserted"] == 3
        with Session(engine) as session:
            assert count(session) == 57
    else:
        assert run(engine)["measurements_inserted"] == 54


def test_setup_demo_failure_preserves_completion_and_scheduler_retry(database, monkeypatch, caplog):
    url, engine = database
    upgrade(url)

    def fail_after_ingestion(session, *, now):
        import_current_slot(session, now=NOW)
        raise RuntimeError("injected Demo initialization failure")

    monkeypatch.setattr(setup, "import_current_slot", fail_after_ingestion)
    with Session(engine) as session:
        setup.create_initial_admin(setup.CreateAdminRequest(
            email="demo-failure@example.org", password="SampleReview2026!Strong",
            confirm_password="SampleReview2026!Strong"), session)
        assert setup.complete_setup(setup.CompleteSetupRequest(default_language_code="es"), session).success
    with Session(engine) as session:
        settings = session.scalar(select(models.SystemSettings))
        assert settings.is_system_setup_complete and settings.default_language_code == "es"
        assert count(session) == 0
        assert session.scalar(select(func.count()).select_from(models.Device)) == 0
        state = session.get(models.DemoImportState, source(session).external_api_id)
        assert state.initial_seed_pending and state.activated_at is None
        job = session.scalar(select(models.JobSchedule).where(models.JobSchedule.task == "demo_import"))
        assert initial_source_import_is_due(session, job)
    assert "Demo initialization failed after setup completion" in caplog.text
    assert "injected Demo initialization failure" in caplog.text
    assert run(engine)["measurements_inserted"] == 54
    assert run(engine)["measurements_skipped"] == 3


@pytest.mark.parametrize("enabled", [True, False])
def test_upgrade_repairs_only_original_canonical_demo_and_preserves_history(database, enabled):
    url, engine = database
    upgrade(url, "20260906_0023")
    seed_historical_demo(engine)
    old_location_time = NOW + timedelta(minutes=1)
    with Session(engine) as session, session.begin():
        demo = source(session)
        demo.enabled = enabled
        canonical = session.scalar(select(models.Device))
        canonical_id = canonical.device_id
        set_device_location(session, canonical, latitude=0, longitude=-140, effective_at=old_location_time)
        sensor_ids = session.scalars(select(models.Sensor.sensor_id)).all()
        measurement_ids = session.scalars(select(models.Measurement.measurement_id)).all()
        # Similar names/coordinates and even external IDs cannot select real or user devices.
        real = session.scalar(select(models.ExternalAPI).where(models.ExternalAPI.provider_code == "openaq"))
        other_ids = []
        for provider_id, external_id, path in [
            (demo.external_api_id, "user-sample-station", "demo_fixture"),
            (demo.external_api_id, "compassaq-sample-station", "csv"),
            (real.external_api_id, "compassaq-sample-station", "demo_fixture"),
            (real.external_api_id, "user-created", "csv"),
        ]:
            device = models.Device(external_api_id=provider_id, external_id=external_id,
                acquisition_path=path, name=canonical.name)
            session.add(device)
            session.flush()
            set_device_location(session, device, latitude=0, longitude=-140, effective_at=old_location_time)
            other_ids.append(device.device_id)
    upgrade(url)
    upgrade(url)  # Running migrations again must not append another history row.
    with Session(engine) as session:
        canonical = session.get(models.Device, canonical_id)
        assert (canonical.latitude, canonical.longitude) == (52.0907, 5.1214)
        assert canonical.external_api.provider_code == "demo"
        assert canonical.acquisition_path == "demo_fixture"
        assert canonical.hardware_provider_name == "Demo Data — synthetic fixture"
        assert source(session).enabled is enabled
        assert session.scalars(select(models.Sensor.sensor_id)).all() == sensor_ids
        assert session.scalars(select(models.Measurement.measurement_id)).all() == measurement_ids
        history = session.scalars(select(models.DeviceLocationHistory).where(
            models.DeviceLocationHistory.device_id == canonical_id).order_by(models.DeviceLocationHistory.effective_from)).all()
        assert len(history) == 3
        assert (history[-2].latitude, history[-2].longitude) == (0, -140)
        assert history[-2].effective_to == history[-1].effective_from
        assert history[-1].effective_from > old_location_time
        assert history[-1].effective_to is None
        for device_id in other_ids:
            device = session.get(models.Device, device_id)
            assert (device.latitude, device.longitude) == (0, -140)
            assert len(device.location_history) == 1


def test_upgrade_preserves_a_manually_relocated_canonical_demo(database):
    url, engine = database
    upgrade(url, "20260906_0024")
    seed_historical_demo(engine)
    with Session(engine) as session, session.begin():
        device = session.scalar(select(models.Device))
        set_device_location(session, device, latitude=51.5, longitude=4.5,
                            effective_at=NOW + timedelta(minutes=1))
    upgrade(url)
    with Session(engine) as session:
        device = session.scalar(select(models.Device))
        assert (device.latitude, device.longitude) == (51.5, 4.5)
        assert len(device.location_history) == 2
        assert count(session) == 54
