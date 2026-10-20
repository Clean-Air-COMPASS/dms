from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

import models
from sources.purpleair import importer
from services.provider_safety import ProviderSafetyDenied


@pytest.fixture
def purpleair(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'purpleair.sqlite'}")
    models.Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, autoflush=False)

    class Clock(datetime):
        current = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    with sessions() as session:
        unit = models.Unit(code="ug_m3", symbol="µg/m³", name="PM unit")
        session.add(unit)
        session.flush()
        session.add_all([
            models.Parameter(code=code, display_name=code, default_unit_id=unit.unit_id)
            for code in ("pm25", "pm10")
        ])
        source = models.ExternalAPI(provider_code="purpleair", name="PurpleAir",
                                    base_url=importer.DEFAULT_BASE_URL, enabled=True,
                                    api_key="test-key", params={})
        session.add(source)
        session.flush()
        session.add(models.Device(name="Test device", external_id="123",
                                  external_api_id=source.external_api_id))
        session.commit()

    requests = []
    response = {"fields": ["time_stamp", *importer.MEASUREMENT_FIELDS], "data": []}

    def metadata(base, sensor, fields, api_key=None):
        requests.append({"kind": "metadata", "sensor": sensor, "fields": list(fields)})
        return {"sensor": {"name": "Provider name"}}

    def history(base, sensor, fields, start, end, api_key=None):
        requests.append({"kind": "history", "sensor": sensor, "start": start, "end": end,
                         "fields": list(fields)})
        return response

    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "false")
    monkeypatch.delenv("PURPLEAIR_API_KEY", raising=False)
    monkeypatch.delenv("PURPLEAIR_TARGET_SENSOR_ID", raising=False)
    monkeypatch.setattr(importer, "_utcnow", lambda: Clock.current)
    monkeypatch.setattr(importer, "SessionLocal", sessions)
    monkeypatch.setattr(importer, "_api_get", metadata)
    monkeypatch.setattr(importer, "_api_get_history", history)
    yield sessions, Clock, requests, response
    engine.dispose()


def test_hourly_windows_preserve_two_minute_values_and_replay_only_boundary(purpleair):
    sessions, clock, requests, response = purpleair
    start = clock.current - timedelta(hours=1)
    stamp = int(start.timestamp())
    response["data"] = [[stamp + i * 120, 12.5, 45.6] for i in range(30)]
    first = importer.run_import()
    clock.current += timedelta(hours=1)
    response["data"] = [[stamp + i * 120, 12.5, 45.6] for i in range(29, 60)]
    second = importer.run_import()
    histories = [r for r in requests if r["kind"] == "history"]
    assert histories[0]["end"] - histories[0]["start"] == 86400
    assert histories[1]["start"] == stamp + 29 * 120
    assert histories[1]["end"] - histories[1]["start"] == 3720
    assert first["measurements_inserted"] == 60
    assert second["measurements_inserted"] == 60
    assert second["measurements_skipped"] == 2
    assert second["provider_results"][0]["api_usage"]["rows_returned"] == 31
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(models.Measurement)) == 120
        for measurement in session.scalars(select(models.Measurement)):
            assert measurement.value == {"pm25": 12.5, "pm10": 45.6}[session.get(models.Parameter, measurement.sensor.parameter_id).code]
            assert measurement.sensor.expected_frequency_seconds == 120
            assert measurement.is_valid


def test_poll_and_metadata_caches_survive_sessions_and_expire_at_boundary(purpleair):
    _, clock, requests, _ = purpleair
    importer.run_import()
    clock.current += timedelta(seconds=119)
    assert importer.run_import()["provider_results"][0]["skip_reason"] == "polled_within_two_minutes"
    assert len(requests) == 2
    clock.current += timedelta(seconds=1)
    importer.run_import()
    assert len(requests) == 3
    clock.current += timedelta(seconds=86400 - 120)
    importer.run_import()
    assert [r["kind"] for r in requests] == ["metadata", "history", "history", "metadata", "history"]


@pytest.mark.parametrize("payload", [
    {"error": "DataInitializingError"},
    {"fields": ["time_stamp", "pm2.5_atm"], "data": []},
    {"fields": ["time_stamp", *importer.MEASUREMENT_FIELDS], "data": [[1, 2]]},
    {"fields": ["time_stamp", *importer.MEASUREMENT_FIELDS], "data": [[1, float("nan"), 3]]},
])
def test_invalid_history_rolls_back_cache_and_measurements(purpleair, payload):
    sessions, _, requests, response = purpleair
    response.clear()
    response.update(payload)
    with pytest.raises(importer.PurpleAirImporterError):
        importer.run_import()
    with sessions() as session:
        assert session.scalar(select(models.PurpleAirImportState)) is None
        assert session.scalar(select(models.Measurement)) is None
    assert len(requests) == 2  # No automatic retry.


@pytest.mark.parametrize("disabled,missing_key", [(True, False), (False, True)])
def test_disabled_or_unconfigured_source_makes_no_requests(purpleair, disabled, missing_key):
    sessions, _, requests, _ = purpleair
    with sessions() as session:
        source = session.scalar(select(models.ExternalAPI))
        source.enabled = not disabled
        if missing_key:
            source.api_key = None
        session.commit()
    with pytest.raises(ProviderSafetyDenied):
        importer.run_import()
    assert requests == []


def test_no_devices_never_infers_sensor_one_from_v1_url(purpleair, monkeypatch):
    sessions, _, requests, _ = purpleair
    with sessions() as session:
        session.delete(session.scalar(select(models.Device)))
        session.commit()
    monkeypatch.setenv("PURPLEAIR_SENSOR_INDEX", "456")
    assert importer.run_import()["devices_processed"] == 0
    assert requests == []


def test_unknown_target_does_not_create_or_fetch_device(purpleair, monkeypatch):
    _, _, requests, _ = purpleair
    monkeypatch.setenv("PURPLEAIR_TARGET_SENSOR_ID", "456")
    assert importer.run_import()["devices_processed"] == 0
    assert requests == []


def test_empty_response_does_not_move_measurement_watermark(purpleair):
    _, clock, requests, response = purpleair
    stamp = int((clock.current - timedelta(minutes=4)).timestamp())
    response["data"] = [[stamp, 12.5, 45.6]]
    importer.run_import()
    response["data"] = []
    clock.current += timedelta(hours=1)
    importer.run_import()
    clock.current += timedelta(hours=1)
    response["data"] = [[stamp + 120, 13.5, 46.6]]
    assert importer.run_import()["measurements_inserted"] == 2
    histories = [r for r in requests if r["kind"] == "history"]
    assert histories[1]["start"] == histories[2]["start"] == stamp


@pytest.mark.parametrize("columns,row", [
    (["pm10.0_atm", "time_stamp", "pm2.5_atm"], [45.6, 1788609480, 12.5]),
    (["pm2.5_atm", "pm10.0_atm"], [1788609480, 12.5, 45.6]),
])
def test_response_column_order_never_changes_parameter_values(purpleair, columns, row):
    sessions, _, _, response = purpleair
    response.update(fields=columns, data=[row])
    assert importer.run_import()["measurements_inserted"] == 2
    with sessions() as session:
        values = {session.get(models.Parameter, m.sensor.parameter_id).code: m.value for m in session.scalars(select(models.Measurement))}
        assert values == {"pm25": 12.5, "pm10": 45.6}
