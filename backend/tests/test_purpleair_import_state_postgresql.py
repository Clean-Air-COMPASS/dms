from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import sessionmaker

import models
from postgresql_test_support import temporary_postgres_database, upgrade, downgrade
from sources.purpleair import importer


def test_purpleair_migration_round_trip_preserves_existing_observations():
    # Exercise only this reversible revision. Later migrations intentionally
    # refuse downgrade when durable provider activation/provenance would be lost.
    # Use SQL so this older schema does not depend on today's ORM columns.
    with temporary_postgres_database("purpleair_round_trip") as (url, engine):
        upgrade(url, "20260903_0019")
        with engine.begin() as connection:
            device_id = connection.scalar(text(
                "INSERT INTO device (name, external_id, external_api_id) "
                "SELECT 'Existing device', '123', external_api_id FROM external_api "
                "WHERE provider_code = 'purpleair' RETURNING device_id"
            ))
            sensor_id = connection.scalar(text(
                "INSERT INTO sensor (device_id, external_sensor_id) "
                "VALUES (:device_id, 'pm25') RETURNING sensor_id"
            ), {"device_id": device_id})
            connection.execute(text(
                "INSERT INTO measurement (sensor_id, value, observed_at) "
                "VALUES (:sensor_id, 12.5, '2026-09-05T11:58:00Z')"
            ), {"sensor_id": sensor_id})
            original = connection.execute(text(
                "SELECT d.device_id, d.name, d.external_id, s.sensor_id, "
                "s.external_sensor_id, m.measurement_id, m.value, m.observed_at "
                "FROM device d JOIN sensor s USING (device_id) "
                "JOIN measurement m USING (sensor_id)"
            )).all()

        for revision in ("20260905_0020", "20260903_0019", "20260905_0020"):
            if revision == "20260903_0019":
                downgrade(url, revision)
            else:
                upgrade(url, revision)
            has_state = revision == "20260905_0020"
            assert ("purpleair_import_state" in inspect(engine).get_table_names()) == has_state
            with engine.begin() as connection:
                assert connection.execute(text(
                    "SELECT d.device_id, d.name, d.external_id, s.sensor_id, "
                    "s.external_sensor_id, m.measurement_id, m.value, m.observed_at "
                    "FROM device d JOIN sensor s USING (device_id) "
                    "JOIN measurement m USING (sensor_id)"
                )).all() == original
                if has_state:
                    assert connection.scalar(text("SELECT count(*) FROM purpleair_import_state")) == 0
                    connection.execute(text(
                        "INSERT INTO purpleair_import_state (device_id, history_polled_at) "
                        "VALUES (:device_id, '2026-09-05T12:00:00Z')"
                    ), {"device_id": device_id})

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM device WHERE device_id = :device_id"),
                               {"device_id": device_id})
            assert connection.scalar(text("SELECT count(*) FROM purpleair_import_state")) == 0


def test_concurrent_imports_preserve_data_and_share_poll_state(monkeypatch):
    with temporary_postgres_database("purpleair_state") as (url, engine):
        upgrade(url, "20260903_0019")
        with engine.begin() as connection:
            source_id = connection.scalar(text(
                "SELECT external_api_id FROM external_api WHERE provider_code = 'purpleair'"
            ))
            device_id = connection.scalar(text(
                "INSERT INTO device (name, external_id, external_api_id) "
                "VALUES ('Existing device', '123', :source_id) RETURNING device_id"
            ), {"source_id": source_id})
        upgrade(url)
        sessions = sessionmaker(engine, autoflush=False)
        with sessions() as session:
            source = session.get(models.ExternalAPI, source_id)
            source.enabled = True
            source.api_key = "test-key"
            session.commit()
            assert session.get(models.Device, device_id).name == "Existing device"
            assert session.get(models.PurpleAirImportState, device_id) is None

        calls = []

        def metadata(*args, **kwargs):
            calls.append("metadata")
            return {"sensor": {"name": "Provider name"}}

        def history(*args, **kwargs):
            calls.append("history")
            return {"fields": ["time_stamp", *importer.MEASUREMENT_FIELDS],
                    "data": [[1788609480, 12.5, 45.6]]}

        monkeypatch.setenv("COMPASSAQ_ENV", "development")
        monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "false")
        monkeypatch.delenv("PURPLEAIR_TARGET_SENSOR_ID", raising=False)
        monkeypatch.setattr(importer, "SessionLocal", sessions)
        monkeypatch.setattr(importer, "_api_get", metadata)
        monkeypatch.setattr(importer, "_api_get_history", history)
        monkeypatch.setattr(importer, "_utcnow", lambda: datetime(2026, 9, 5, 12, tzinfo=timezone.utc))
        barrier = Barrier(2)

        def run():
            barrier.wait(timeout=10)
            return importer.run_import()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run)
            second = pool.submit(run)
            results = [first.result(timeout=30), second.result(timeout=30)]
        assert calls == ["metadata", "history"]
        assert sum(result["measurements_inserted"] for result in results) == 2
        assert any(result["provider_results"][0].get("skip_reason") == "polled_within_two_minutes"
                   for result in results)
        with sessions() as session:
            assert session.get(models.PurpleAirImportState, device_id).history_polled_at is not None
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM measurement")) == 2
        with sessions() as session:
            session.delete(session.get(models.Device, device_id))
            session.commit()
            assert session.scalar(select(models.PurpleAirImportState)) is None
