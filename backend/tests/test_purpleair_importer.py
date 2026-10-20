from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Tuple

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import models
from sources.purpleair import importer


def test_run_import_creates_device_sensors_and_measurements(monkeypatch, tmp_path, capsys):
    """Exercise purpleair importer without hitting the real API."""
    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    monkeypatch.setenv("DISABLE_PAID_API_REQUESTS", "false")
    monkeypatch.setenv("PURPLEAIR_EXECUTION_MODE", "manual")
    monkeypatch.setenv("PURPLEAIR_MANUAL_AUTHORIZED", "true")
    db_path = tmp_path / "purpleair.sqlite"
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

                                                  
    monkeypatch.setattr(importer, "SessionLocal", SessionLocal)

    models.Base.metadata.create_all(bind=engine)

    base_obs_ts = 1_700_000_000
    with SessionLocal() as session:
                                                   
        unit = models.Unit(code="ug_m3", symbol="ug/m3", name="Micrograms per cubic meter")
        session.add(unit)
        session.flush()

        unit_id = unit.unit_id
        pm25 = models.Parameter(code="pm25", display_name="PM2.5", default_unit_id=unit_id)
        pm10 = models.Parameter(code="pm10", display_name="PM10", default_unit_id=unit_id)
        session.add_all([pm25, pm10])
        session.flush()
        pm25_id = pm25.parameter_id
        pm10_id = pm10.parameter_id

        api_row = models.ExternalAPI(
            provider_code="purpleair",
            name="PurpleAir",
            base_url="https://api.purpleair.com/v1/sensors",
            description="",
            api_key="test-key",
            params={},
            enabled=True,
        )
        session.add(api_row)
        session.flush()
        api_id = api_row.external_api_id

                                                                   
        agg = models.AggregationPeriod(
            code="1m",
            display_name="1 Minute",
            duration_minutes=1,
            is_rolling=False,
            expected_interval="00:01:00",
        )
        session.add(agg)
        session.flush()

                                                               
        device = models.Device(
            name="Seeded PurpleAir name",
            friendly_name="Administrator-friendly name",
            external_api_id=api_id,
            external_id="123",
            allow_updates=models.UpdatePolicy.ALLOW,
        )
        session.add(device)
        session.flush()

                                                                                
        pm25_sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=pm25_id,
            external_sensor_id="123:pm2.5_atm",
            aggregation_period_id=agg.aggregation_period_id,
            unit_id=unit_id,
        )
        # The canonical PurpleAir stream may still carry stale measurement
        # metadata, which the importer reconciles without recognizing old IDs.
        session.add(pm25_sensor)
        session.flush()

        base_dt = datetime.fromtimestamp(base_obs_ts, tz=timezone.utc)
        session.add(
            models.Measurement(
                sensor_id=pm25_sensor.sensor_id,
                value=10.0,
                observed_at=base_dt,
            )
        )

        other_api = models.ExternalAPI(
            name="Other Source",
            base_url="https://example.test",
            description="",
            params={},
        )
        session.add(other_api)
        session.flush()
        other_device = models.Device(
            name="Other",
            external_api_id=other_api.external_api_id,
        )
        session.add(other_device)
        session.flush()
        unrelated_sensor = models.Sensor(
            device_id=other_device.device_id,
            parameter_id=pm25_id,
            aggregation_period_id=agg.aggregation_period_id,
            unit_id=unit_id,
            expected_frequency_seconds=30,
            measurement_duration_seconds=5,
            source_aggregation_duration_seconds=10,
            measurement_timestamp_semantics="observation_instant",
        )
        session.add(unrelated_sensor)
        session.commit()
        unrelated_sensor_id = unrelated_sensor.sensor_id

    calls: List[Tuple[str, str]] = []

    def fake_api_get(base_url: str, sensor_index: str, fields, api_key=None):
        calls.append((base_url, ",".join(fields)))
        if set(fields) == set(importer.DEVICE_FIELDS):
            return {
                "sensor": {
                    "name": "PurpleTest",
                    "latitude": 35.0,
                    "longitude": -120.0,
                }
            }
        if importer.SENSOR_FIELDS and set(fields) == set(importer.SENSOR_FIELDS):
            return {"sensor": {"sensor_index": sensor_index}}
        raise AssertionError(f"Unexpected fields: {fields}")

    monkeypatch.setattr(importer, "_api_get", fake_api_get)
    new_obs_ts = base_obs_ts + 120

    def fake_api_get_history(base_url: str, sensor_index: str, fields, start_timestamp, end_timestamp, api_key=None):
        calls.append(("history", f"{start_timestamp}-{end_timestamp}"))
        return {
            "fields": list(fields),
            "data": [
                [new_obs_ts, 12.5, 45.6],
            ],
        }

    monkeypatch.setattr(importer, "_api_get_history", fake_api_get_history)

    class Clock(datetime):
        current = datetime.fromtimestamp(base_obs_ts + 3600, tz=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(importer, "_utcnow", lambda: Clock.current)
    first_summary = importer.run_import()
    immediate_summary = importer.run_import()
    assert immediate_summary["measurements_received"] == 0
    assert immediate_summary["provider_results"][0]["skip_reason"] == "polled_within_two_minutes"
    Clock.current += timedelta(minutes=2)
    second_summary = importer.run_import()
    assert len([call for call in calls if call[0] != "history"]) == 1
    assert len([call for call in calls if call[0] == "history"]) == 2
    assert second_summary["provider_results"][0]["api_usage"]["start_timestamp"] == new_obs_ts

    assert first_summary["devices_processed"] == 1
    assert first_summary["devices_created"] == 0
    assert first_summary["sensors_processed"] == 2
    assert first_summary["sensors_created"] == 1
    assert first_summary["measurements_received"] == 2
    assert first_summary["measurements_inserted"] == 2
    assert first_summary["measurements_updated"] == 0
    assert first_summary["measurements_skipped"] == 0
    assert first_summary["qc"] == {
        "evaluated": 2,
        "passed": 2,
        "flagged": 0,
        "indeterminate": 0,
    }
    assert second_summary["measurements_received"] == 2
    assert second_summary["measurements_inserted"] == 0
    assert second_summary["measurements_updated"] == 2
    assert second_summary["measurements_skipped"] == 0
    assert second_summary["qc"] == {
        "evaluated": 2,
        "passed": 2,
        "flagged": 0,
        "indeterminate": 0,
    }

    with SessionLocal() as session:
        device = session.scalars(
            select(models.Device).where(models.Device.external_id == "123")
        ).one()
        assert device.external_id == "123"
        assert device.external_api_id == api_id
        assert device.name == "PurpleTest"
        assert device.friendly_name == "Administrator-friendly name"
        assert device.latitude == 35.0
        assert device.longitude == -120.0
        if importer.TimezoneFinder is not None:
            assert device.timezone and "America" in device.timezone

        sensors = session.scalars(
            select(models.Sensor).where(models.Sensor.device_id == device.device_id)
        ).all()
        assert len(sensors) == 2
                                                             
        pm25_sensor = session.scalars(
            select(models.Sensor).where(
                models.Sensor.device_id == device.device_id,
                models.Sensor.parameter_id == pm25_id,
            )
        ).one()
        pm10_sensor = session.scalars(
            select(models.Sensor).where(
                models.Sensor.device_id == device.device_id,
                models.Sensor.parameter_id == pm10_id,
            )
        ).one()
        assert pm25_sensor.device_id == device.device_id
        assert pm10_sensor.device_id == device.device_id
                                                             
        agg_code = session.scalars(
            select(models.AggregationPeriod.code).where(
                models.AggregationPeriod.aggregation_period_id == pm25_sensor.aggregation_period_id
            )
        ).one()
        assert agg_code == "2m"
        assert pm25_sensor.unit_id == unit_id
        assert pm10_sensor.unit_id == unit_id
        for sensor in (pm25_sensor, pm10_sensor):
            assert sensor.expected_frequency_seconds == 120
            assert sensor.measurement_duration_seconds == 120
            assert sensor.source_aggregation_duration_seconds == 120
            assert sensor.measurement_timestamp_semantics == "provider_received_at"
            assert sensor.measurement_metadata_status == "provider_documented"
            assert sensor.measurement_metadata_managed_by == "purpleair_importer"

        measurements = session.scalars(
            select(models.Measurement).where(
                models.Measurement.sensor_id.in_(
                    [pm25_sensor.sensor_id, pm10_sensor.sensor_id]
                )
            )
        ).all()
                                                
        assert len(measurements) == 3
        expected_ts = datetime.fromtimestamp(new_obs_ts, tz=timezone.utc)
        new_values = sorted(
            m.value for m in measurements if (m.observed_at.replace(tzinfo=timezone.utc) if m.observed_at.tzinfo is None else m.observed_at) == expected_ts
        )
        assert new_values == [12.5, 45.6]

        unrelated_sensor = session.get(models.Sensor, unrelated_sensor_id)
        assert unrelated_sensor is not None
        assert unrelated_sensor.expected_frequency_seconds == 30
        assert unrelated_sensor.measurement_duration_seconds == 5
        assert unrelated_sensor.source_aggregation_duration_seconds == 10
        assert unrelated_sensor.measurement_timestamp_semantics == "observation_instant"

        # The repeated run reuses the same two PurpleAir sensor records.
        assert session.scalar(
            select(models.Sensor.sensor_id)
            .where(models.Sensor.device_id == device.device_id)
            .where(models.Sensor.parameter_id == pm25_id)
        ) == pm25_sensor.sensor_id

                                                                             
        out = capsys.readouterr().out
        assert 'overall={"insert": 2' in out
        assert '"insert": 0' in out
