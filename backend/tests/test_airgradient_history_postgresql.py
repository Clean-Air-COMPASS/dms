"""Migration, real PostgreSQL locking and legacy-average isolation checks."""
import os
from datetime import datetime, timezone
import time

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

import models
from postgresql_test_support import temporary_postgres_database, upgrade, downgrade
from sources.airgradient.importer import _airgradient_run_lock, AirGradientImporterError
from sources.airgradient.history_ingestion import ensure_history_sensor
from sources.airgradient.history_ingestion import import_location_history
from sources.airgradient import map_history
from services.import_summaries import new_import_summary
from utils.aggregations import get_pm25_rolling_24h_avg, get_pm25_daily_24h_avg

pytestmark = pytest.mark.skipif(not os.getenv("COMPASSAQ_POSTGRES_TEST_URL"), reason="Isolated PostgreSQL required")


def test_history_migration_preserves_existing_rows_and_is_reversible():
    with temporary_postgres_database("history_migration") as (url, engine):
        upgrade(url, "20260907_0025")
        with engine.begin() as connection:
            device_id = connection.scalar(text(
                "INSERT INTO device(name,external_api_id,timezone) VALUES ('Synthetic migration device',"
                "(SELECT external_api_id FROM external_api WHERE provider_code='airgradient'),'UTC') RETURNING device_id"
            ))
            parameter_id = connection.scalar(text("SELECT parameter_id FROM parameter WHERE code='pm25'"))
            sensor_id = connection.scalar(text(
                "INSERT INTO sensor(device_id,parameter_id,external_sensor_id) VALUES (:device,:parameter,'migration-snapshot') RETURNING sensor_id"
            ), {"device": device_id, "parameter": parameter_id})
            connection.execute(text(
                "INSERT INTO measurement(sensor_id,value,observed_at,is_valid) VALUES (:sensor,7,'2026-10-10T00:00:00Z',true)"
            ), {"sensor": sensor_id})
        upgrade(url)
        with engine.connect() as connection:
            row = connection.execute(text(
                "SELECT s.external_sensor_id,s.acquisition_metadata,s.acquisition_examined_until,m.value FROM sensor s "
                "JOIN measurement m USING(sensor_id) WHERE s.sensor_id=:sensor"
            ), {"sensor": sensor_id}).one()
            assert tuple(row) == ("migration-snapshot", None, None, 7.0)
        downgrade(url, "20260907_0025")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT value FROM measurement WHERE sensor_id=:sensor"), {"sensor": sensor_id}) == 7.0


def test_manual_and_scheduled_importers_share_one_postgres_lock():
    with temporary_postgres_database("history_lock") as (_, engine):
        with Session(engine) as first, Session(engine) as second:
            with _airgradient_run_lock(first):
                with pytest.raises(AirGradientImporterError, match="already running"):
                    with _airgradient_run_lock(second):
                        pytest.fail("concurrent importer was admitted")
            with _airgradient_run_lock(second):
                pass


def test_legacy_device_averages_do_not_mix_processed_history():
    with temporary_postgres_database("history_average") as (url, engine):
        upgrade(url)
        with Session(engine) as session:
            source = session.scalar(select(models.ExternalAPI).where(models.ExternalAPI.provider_code == "airgradient"))
            parameter = session.scalar(select(models.Parameter).where(models.Parameter.code == "pm25"))
            device = models.Device(name="Synthetic history isolation", external_api_id=source.external_api_id,
                                   external_id="175911", acquisition_path="airgradient_public_reference", timezone="UTC")
            session.add(device)
            session.flush()
            snapshot = models.Sensor(device_id=device.device_id, parameter_id=parameter.parameter_id, external_sensor_id="snapshot")
            history, created = ensure_history_sensor(session, device, "pm25", {"ownerName": "Synthetic contributor"})
            assert created and history.measurement_duration_seconds is None
            assert history.source_aggregation_duration_seconds == 900
            session.add(snapshot)
            session.flush()
            observed = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
            session.add_all([
                models.Measurement(sensor_id=snapshot.sensor_id, value=2, observed_at=observed, is_valid=True),
                models.Measurement(sensor_id=history.sensor_id, value=100, observed_at=observed, is_valid=True),
            ])
            session.commit()
            assert get_pm25_rolling_24h_avg(session, device.device_id, datetime(2026, 10, 11, tzinfo=timezone.utc)) == 2.0
            assert get_pm25_daily_24h_avg(session, device.device_id, observed) == 2.0
            with pytest.raises(RuntimeError, match="processed history streams exist"):
                downgrade(url, "20260907_0025")
            session.expire_all()
            assert session.get(models.Sensor, history.sensor_id).acquisition_metadata["acquisition_method"] == "map_processed_history"
            assert session.scalar(select(models.Measurement.value).where(models.Measurement.sensor_id == history.sensor_id)) == 100.0


def test_non_utc_database_timezone_cannot_move_checkpoint_forward(monkeypatch):
    from tests.test_airgradient_map_history import DASHBOARD, METADATA, END, NOW
    with temporary_postgres_database("history_timezone") as (url, engine):
        upgrade(url)
        with Session(engine) as session:
            session.execute(text("SET TIME ZONE 'Asia/Karachi'"))
            source = session.scalar(select(models.ExternalAPI).where(models.ExternalAPI.provider_code == "airgradient"))
            device = models.Device(name="Synthetic timezone isolation", external_api_id=source.external_api_id,
                                   external_id="175911", acquisition_path="airgradient_public_reference", timezone="UTC")
            session.add(device)
            session.flush()
            sensor, _ = ensure_history_sensor(session, device, "pm25", METADATA)
            sensor.acquisition_examined_until = END
            session.commit()
            assert sensor.acquisition_examined_until.utcoffset().total_seconds() == 5 * 3600
            monkeypatch.setattr(map_history, "PARAMETERS", {"pm25": map_history.PARAMETERS["pm25"]})
            monkeypatch.setattr(map_history, "public_get", lambda path, params=None:
                                METADATA if params is None else {"data": [], "total": 0})
            result = new_import_summary()
            result["per_parameter"] = {}
            import_location_history(session, device, DASHBOARD, result, deadline=time.monotonic() + 30, now=NOW)
            assert sensor.acquisition_examined_until.astimezone(timezone.utc) == END
            assert result["history_progress"][0]["examined_until"] == END.isoformat()
