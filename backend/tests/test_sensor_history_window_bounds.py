"""DEV-004: ordinary history uses inclusive input bounds, unlike rolling windows.

Run on private SQLite and an opt-in temporary PostgreSQL database. Expectations
below are specified from fixture membership, never production aggregation code.
"""
import datetime as datetime_module
from datetime import datetime, timedelta, timezone
import os

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from db import get_session
import models
from postgresql_test_support import temporary_postgres_database

UTC = timezone.utc
T = datetime(2026, 10, 19, 14, 30, 54, tzinfo=UTC)
LOWER = datetime(2026, 10, 18, 14, 30, 54, tzinfo=UTC)


@pytest.fixture(scope="module", params=["sqlite", "postgresql"])
def history_engine(request):
    if request.param == "postgresql":
        if not os.environ.get("COMPASSAQ_POSTGRES_TEST_URL"):
            pytest.skip("COMPASSAQ_POSTGRES_TEST_URL is not configured")
        with temporary_postgres_database("dev004_history") as (_, engine):
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            models.Base.metadata.create_all(engine)
            yield engine
        return
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def history(history_engine, monkeypatch):
    factory = sessionmaker(bind=history_engine)
    with factory() as session:
        unit = models.Unit(code="dev004_unit", name="Synthetic concentration", symbol="µg/m³")
        source = models.ExternalAPI(name="SYNTHETIC DEV-004", enabled=False, params={})
        session.add_all([unit, source])
        session.flush()
        parameter = models.Parameter(code="dev004_pm25", display_name="Synthetic PM2.5", default_unit_id=unit.unit_id)
        device = models.Device(name="SYNTHETIC DEV-004 station", external_api_id=source.external_api_id, timezone="UTC")
        periods = {code: models.AggregationPeriod(code=code, display_name=code, duration_minutes=minutes, is_rolling=False)
                   for code, minutes in [("1m", 1), ("1h", 60), ("24h", 1440)]}
        session.add_all([parameter, device, *periods.values()])
        session.flush()
        sensor = models.Sensor(device_id=device.device_id, parameter_id=parameter.parameter_id,
                               unit_id=unit.unit_id, aggregation_period_id=periods["1m"].aggregation_period_id,
                               measurement_timestamp_semantics="instant")
        session.add(sensor)
        for source_code, target in [("1m", "1h"), ("1h", "24h")]:
            session.add(models.ParameterAggregationRollup(parameter_id=parameter.parameter_id,
                from_aggregation_period_id=periods[source_code].aggregation_period_id,
                to_aggregation_period_id=periods[target].aggregation_period_id))
        session.flush()

        class FrozenDatetimeMeta(type):
            def __instancecheck__(cls, instance):
                return isinstance(instance, datetime)

        class FrozenDatetime(datetime, metaclass=FrozenDatetimeMeta):
            @classmethod
            def now(cls, tz=None):
                clock_calls.append(tz)
                return evaluation[0].astimezone(tz) if tz else evaluation[0].replace(tzinfo=None)

        evaluation = [T]
        clock_calls = []
        # Freeze the handler's local import while preserving datetime type checks.
        monkeypatch.setattr(datetime_module, "datetime", FrozenDatetime)
        previous = app.dependency_overrides.copy()
        app.dependency_overrides[get_session] = lambda: session
        client = TestClient(app)

        def add(when, value, valid=True, recorded=False):
            measurement = models.Measurement(sensor_id=sensor.sensor_id, observed_at=when, value=value, is_valid=valid)
            session.add(measurement)
            session.flush()
            if recorded:
                session.add(models.MeasurementQCResult(measurement_id=measurement.measurement_id,
                    aggregate_code="1m", check_code="max_value", passed=False,
                    evaluation_status="failed", failure_action="flag_for_review" if valid else "mark_invalid",
                    reason_code="above_maximum", severity="warning", message="Synthetic historical outcome"))
                session.flush()
            return measurement.measurement_id

        def get(**params):
            clock_calls.clear()
            response = client.get(f"/sensors/{sensor.sensor_id}/history", params={"aggregation": "raw", **params})
            assert response.status_code == 200, response.text
            assert clock_calls == [UTC], "Resolve the history evaluation instant once"
            return response.json()

        try:
            yield session, sensor, add, get, evaluation
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
            session.rollback()


def timestamps(payload):
    return [datetime.fromisoformat(row["timestamp"]) for row in payload["data"]]


@pytest.mark.parametrize("hours", [24, 48])
@pytest.mark.parametrize("aggregation", ["raw", "latest", "1m", "1h", "24h"])
def test_relative_native_boundaries_precision_and_identity(history, hours, aggregation):
    session, sensor, add, get, _ = history
    if aggregation in {"1h", "24h"}:
        sensor.aggregation_period_id = session.scalar(select(models.AggregationPeriod.aggregation_period_id).where(models.AggregationPeriod.code == aggregation))
        session.flush()
    lower = T - timedelta(hours=hours)
    add(lower - timedelta(microseconds=1), 999)
    first_id = add(lower, 10.123456789, recorded=True)
    last_id = add(T, 20.987654321)
    add(T + timedelta(microseconds=1), 888)
    add(T + timedelta(days=12), 777)
    # latest is the established legacy aggregate alias; canonical requests use
    # raw or the sensor's period code.
    request = {"aggregate": "latest", "aggregation": ""} if aggregation == "latest" else {"aggregation": aggregation}
    payload = get(hours=hours, include_qc=True, **request)
    assert timestamps(payload) == [lower, T]
    assert [row["value"] for row in payload["data"]] == [10.123456789, 20.987654321]
    assert [row["measurement_id"] for row in payload["data"]] == [first_id, last_id]
    assert payload["data"][0]["qc_provenance_status"] == "recorded"
    assert payload["data"][0]["qc_results"][0]["reason_code"] == "above_maximum"
    assert payload["unit"] == "µg/m³"
    assert session.scalar(select(models.Measurement.value).where(models.Measurement.measurement_id == first_id)) == 10.123456789
    assert len(session.scalars(select(models.Measurement).where(models.Measurement.sensor_id == sensor.sensor_id)).all()) == 5


@pytest.mark.parametrize("aggregation,expected_times,expected_values,counts", [
    ("1h", [datetime(2026, 10, 18, 14, tzinfo=UTC), datetime(2026, 10, 18, 15, tzinfo=UTC), datetime(2026, 10, 19, 14, tzinfo=UTC)], [12, 30, 50], [2, 1, 1]),
    ("24h", [datetime(2026, 10, 18, tzinfo=UTC), datetime(2026, 10, 19, tzinfo=UTC)], [21, 50], [3, 1]),
])
def test_fixed_buckets_contain_only_window_inputs(history, aggregation, expected_times, expected_values, counts):
    _, _, add, get, _ = history
    add(LOWER - timedelta(microseconds=1), 1000)  # Same first bucket, excluded.
    add(LOWER, 10)
    add(datetime(2026, 10, 18, 14, 45, tzinfo=UTC), 14)
    add(datetime(2026, 10, 18, 15, tzinfo=UTC), 30)
    add(T, 50)
    add(T + timedelta(microseconds=1), 2000)  # Same final bucket, excluded.
    add(T + timedelta(days=12), 3000)
    payload = get(aggregation=aggregation, hours=24)
    assert timestamps(payload) == expected_times
    assert [row["value"] for row in payload["data"]] == expected_values
    assert [row["sample_count"] for row in payload["data"]] == counts
    assert [row["valid_sample_count"] for row in payload["data"]] == counts
    assert [row["invalid_sample_count"] for row in payload["data"]] == [0] * len(counts)


@pytest.mark.parametrize("include_invalid,expected", [(False, [10]), (True, [10, 20])])
def test_relative_validity_filter_and_historical_qc(history, include_invalid, expected):
    _, _, add, get, _ = history
    add(LOWER, 10, recorded=True)
    add(T, 20, valid=False, recorded=True)
    add(T + timedelta(days=12), 30, valid=False, recorded=True)
    payload = get(include_invalid=include_invalid, include_qc=True)
    assert [row["value"] for row in payload["data"]] == expected
    assert all(row["qc_provenance_status"] == "recorded" for row in payload["data"])
    if include_invalid:
        assert payload["data"][-1]["qc_results"][0]["failure_action"] == "mark_invalid"


@pytest.mark.parametrize("state,expected", [("empty", "no_observations"), ("future", "no_observations"), ("invalid", "no_eligible_observations")])
def test_empty_status_uses_same_window(history, state, expected):
    _, _, add, get, _ = history
    if state == "future":
        add(T + timedelta(days=12), 10)
    if state == "invalid":
        add(T, 10, valid=False)
    payload = get()
    assert payload["data"] == []
    assert payload["history_status"] == expected


@pytest.mark.parametrize("delta", [timedelta(days=-10), timedelta(days=10)])
def test_explicit_past_and_future_ranges_are_not_clamped(history, delta):
    _, _, add, get, _ = history
    start, end = T + delta, T + delta + timedelta(hours=1)
    add(start - timedelta(microseconds=1), 1)
    add(start, 10)
    add(end, 20)
    add(end + timedelta(microseconds=1), 100)
    payload = get(start=start.isoformat(), end=end.isoformat())
    assert timestamps(payload) == [start, end]
    assert [row["value"] for row in payload["data"]] == [10, 20]


def test_start_without_end_defaults_to_evaluation_time(history):
    _, _, add, get, _ = history
    add(LOWER, 10)
    add(T, 20)
    add(T + timedelta(microseconds=1), 100)
    assert timestamps(get(start=LOWER.isoformat(), hours=1)) == [LOWER, T]


def test_end_without_start_preserves_now_relative_lower_bound(history):
    _, _, add, get, _ = history
    add(LOWER - timedelta(microseconds=1), 1)
    add(LOWER, 10)
    add(T, 20)
    end = T + timedelta(days=12)
    add(end, 30)
    add(end + timedelta(microseconds=1), 100)
    assert timestamps(get(end=end.isoformat(), include_qc=True)) == [LOWER, T, end]


@pytest.mark.parametrize("start,end", [
    ("2026-10-18T07:30:54-07:00", "2026-10-19T20:15:54+05:45"),
    ("2026-10-18T14:30:54", "2026-10-19T14:30:54"),
])
def test_explicit_offsets_and_naive_utc(history, start, end):
    _, _, add, get, _ = history
    add(LOWER, 10)
    add(T, 20)
    add(T + timedelta(microseconds=1), 100)
    assert timestamps(get(start=start, end=end)) == [LOWER, T]


@pytest.mark.parametrize("instant", [datetime(2026, 3, 8, 10, tzinfo=UTC), datetime(2026, 11, 1, 9, tzinfo=UTC)])
def test_relative_windows_remain_24_elapsed_hours_across_dst(history, instant):
    _, _, add, get, evaluation = history
    evaluation[0] = instant
    add(instant - timedelta(hours=24, microseconds=1), 1)
    add(instant - timedelta(hours=24), 10)
    add(instant, 20)
    add(instant + timedelta(microseconds=1), 100)
    assert timestamps(get()) == [instant - timedelta(hours=24), instant]


def test_many_future_observations_do_not_expand_relative_response(history):
    session, sensor, add, get, _ = history
    add(LOWER, 10)
    add(T, 20)
    session.add_all([models.Measurement(sensor_id=sensor.sensor_id, value=999,
        observed_at=T + timedelta(minutes=index), is_valid=True) for index in range(1, 17281)])
    session.flush()
    assert timestamps(get()) == [LOWER, T]
