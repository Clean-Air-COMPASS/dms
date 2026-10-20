"""Rolling regressions on private SQLite and optional temporary PostgreSQL databases.

Never uses db.SessionLocal or the running development database.
"""
from datetime import datetime, timedelta, timezone
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    AggregationPeriod, Base, Device, ExternalAPI, Measurement, Parameter,
    ParameterAggregationRollup, Sensor, Unit,
)
from services import measurement_aggregation as service
from postgresql_test_support import temporary_postgres_database

UTC = timezone.utc
END = datetime(2026, 10, 9, 4, 50, tzinfo=UTC)
START = END - timedelta(days=1)


@pytest.fixture(scope="module", params=["sqlite", "postgresql"])
def rolling_engine(request):
    if request.param == "postgresql":
        if not os.environ.get("COMPASSAQ_POSTGRES_TEST_URL"):
            pytest.skip("COMPASSAQ_POSTGRES_TEST_URL is not configured")
        with temporary_postgres_database("rolling_boundaries") as (_, engine):
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                # Verify UTC grouping even with a non-UTC PostgreSQL session.
                connection.execute(text("SET TIME ZONE 'Asia/Kathmandu'"))
            Base.metadata.create_all(engine)
            yield engine
        return

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def rolling_sensor(rolling_engine):
    engine = rolling_engine
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        if engine.dialect.name == "postgresql":
            assert session.scalar(text("SHOW TIME ZONE")) == "Asia/Kathmandu"
        source = ExternalAPI(name="Synthetic rolling source", base_url="https://example.test", params={})
        unit = Unit(code="qa_roll_unit", symbol="µg/m³", name="QA unit")
        session.add_all((source, unit))
        session.flush()
        parameter = Parameter(code="qa_roll_pm", display_name="QA PM", default_unit_id=unit.unit_id)
        device = Device(name="Synthetic rolling device", external_api_id=source.external_api_id)
        session.add_all((parameter, device))
        session.flush()
        native = AggregationPeriod(code="qa_roll_2m", display_name="2m", duration_minutes=2, is_rolling=False)
        hour = AggregationPeriod(code="qa_roll_1h", display_name="1h", duration_minutes=60, is_rolling=False)
        rolling = AggregationPeriod(code="qa_roll_24h", display_name="Rolling 24h", duration_minutes=1440, is_rolling=True)
        session.add_all((native, hour, rolling))
        session.flush()
        session.add_all((
            ParameterAggregationRollup(parameter_id=parameter.parameter_id, from_aggregation_period_id=native.aggregation_period_id, to_aggregation_period_id=hour.aggregation_period_id),
            ParameterAggregationRollup(parameter_id=parameter.parameter_id, from_aggregation_period_id=hour.aggregation_period_id, to_aggregation_period_id=rolling.aggregation_period_id),
        ))
        sensor = Sensor(device_id=device.device_id, parameter_id=parameter.parameter_id, unit_id=unit.unit_id, aggregation_period_id=native.aggregation_period_id)
        session.add(sensor)
        session.flush()

        def add(when, value, valid=True):
            session.add(Measurement(sensor_id=sensor.sensor_id, observed_at=when, value=value, is_valid=valid))

        def evaluate(*, since=None, until=END, direct=False, public=False,
                     result_code="qa_roll_24h", include_invalid=False, latest_only=True):
            if direct:
                session.add(ParameterAggregationRollup(
                    parameter_id=parameter.parameter_id,
                    from_aggregation_period_id=native.aggregation_period_id,
                    to_aggregation_period_id=rolling.aggregation_period_id,
                ))
            session.flush()
            if public:
                # Exercise routing, dependency injection, and response serialization
                # against this fixture's private session, without application startup.
                from fastapi.testclient import TestClient
                from api.main import app
                from db import get_session

                def private_session():
                    yield session

                previous_overrides = app.dependency_overrides.copy()
                app.dependency_overrides[get_session] = private_session
                try:
                    params = {"aggregation": result_code}
                    if since is not None:
                        params["since"] = since.isoformat()
                    if until is not None:
                        params["until"] = until.isoformat()
                    path = f"/measurements/{parameter.code}/latest"
                    if public == "all_latest":
                        path = "/measurements/latest"
                    elif public == "device_sensors":
                        path = f"/devices/{device.device_id}/sensors"
                    response = TestClient(app).get(path, params=params)
                    assert response.status_code == 200, response.text
                    return response.json()
                finally:
                    app.dependency_overrides.clear()
                    app.dependency_overrides.update(previous_overrides)
            return service.execute_measurement_aggregation(
                session, sensor_ids=[sensor.sensor_id], parameter_code=parameter.code,
                native_aggregation_code=native.code, result_aggregation_code=result_code,
                since=since, until=until, latest_only=latest_only,
                include_invalid=include_invalid,
            )
        yield add, evaluate
        session.rollback()


@pytest.fixture()
def frozen_clock(monkeypatch):
    calls = []

    class ClockMeta(type):
        def __instancecheck__(cls, value):
            # SQLAlchemy returns ordinary datetime objects, not the clock subclass.
            return isinstance(value, datetime)

    class FixedDateTime(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            calls.append(tz)
            assert len(calls) == 1, "Resolve the rolling evaluation instant only once"
            return END if tz is not None else END.replace(tzinfo=None)

    monkeypatch.setattr(service, "datetime", FixedDateTime)
    return calls


def test_partial_first_hour_counts_only_observations_inside_rolling_window(rolling_sensor):
    add, evaluate = rolling_sensor
    add(START - timedelta(seconds=1), 900)  # outside the rolling window
    add(START, 800)                         # exact lower boundary: excluded
    add(START + timedelta(minutes=1), 10)   # first partial clock hour
    add(START + timedelta(minutes=9), 20)
    add(START + timedelta(minutes=10), 30)  # next UTC clock hour
    add(START + timedelta(minutes=12), 40)
    result = evaluate()
    assert len(result) == 1
    # First partial hour = (10+20)/2=15, next hour = (30+40)/2=35.
    # Equal weighting between clock-hour averages, not by raw observation count.
    assert result[0].value == pytest.approx(25)
    assert result[0].sample_count == 4


def test_upper_boundary_excludes_future_and_includes_exact_until(rolling_sensor):
    add, evaluate = rolling_sensor
    add(START + timedelta(minutes=1), 10)
    add(END, 30)  # exact upper bound is included
    add(END + timedelta(seconds=1), 10000)
    add(END + timedelta(days=22), 20000)
    result = evaluate()[0]
    assert result.value == pytest.approx(20)  # two equal clock-hour groups
    assert result.sample_count == 2


def test_sparse_hourly_groups_preserve_equal_bucket_weighting(rolling_sensor):
    add, evaluate = rolling_sensor
    add(START + timedelta(minutes=1), 10)
    add(START + timedelta(minutes=2), 20)
    add(START + timedelta(hours=12), 90)
    result = evaluate()[0]
    assert result.value == pytest.approx((15 + 90) / 2)
    assert result.sample_count == 3


def test_later_since_clips_raw_input_without_losing_partially_covered_hour(rolling_sensor):
    add, evaluate = rolling_sensor
    add(START + timedelta(hours=1), 100)  # outside explicit since
    add(START + timedelta(hours=1, minutes=20), 20)
    add(START + timedelta(hours=2, minutes=20), 40)
    result = evaluate(since=START + timedelta(hours=1, minutes=10))[0]
    assert result.value == pytest.approx(30)
    assert result.sample_count == 2


def test_omitted_until_uses_current_instant_for_both_raw_bounds(rolling_sensor, frozen_clock):
    add, evaluate = rolling_sensor
    add(START, 800)
    add(START + timedelta(seconds=1), 10)
    add(END, 30)
    add(END + timedelta(seconds=1), 9999)
    add(END + timedelta(days=22), 8888)

    result = evaluate(until=None)[0]
    assert result.value == pytest.approx(20)
    assert result.sample_count == 2
    assert result.observed_at == END
    assert (result.interval_started_at, result.interval_ended_at) == (START, END)
    assert result.latest_source_observed_at == END
    assert frozen_clock == [UTC]


@pytest.mark.parametrize("direct", [False, True], ids=["chained", "direct"])
@pytest.mark.parametrize("implicit_until", [False, True])
def test_future_rows_are_excluded_without_a_partial_first_hour(
    rolling_sensor, frozen_clock, direct, implicit_until,
):
    add, evaluate = rolling_sensor
    add(END - timedelta(minutes=1), 10)
    add(END, 30)
    add(END + timedelta(seconds=1), 9999)
    add(END + timedelta(days=22), 8888)
    point = evaluate(direct=direct, until=None if implicit_until else END)[0]
    # Only the two eligible observations in the final clock hour contribute.
    assert point.value == pytest.approx(20)
    assert (point.sample_count, point.valid_sample_count, point.invalid_sample_count) == (2, 2, 0)
    assert point.observed_at == END
    assert (point.interval_started_at, point.interval_ended_at) == (START, END)
    assert point.latest_source_observed_at == END
    assert len(frozen_clock) == int(implicit_until)


@pytest.mark.parametrize("direct", [False, True], ids=["chained", "direct"])
def test_exact_boundaries_and_validity_counts(rolling_sensor, direct):
    add, evaluate = rolling_sensor
    add(START - timedelta(seconds=1), 900)
    add(START, 800)
    add(START + timedelta(seconds=1), 10)
    add(END, 30)
    add(END - timedelta(seconds=1), 700, valid=False)
    add(END + timedelta(seconds=1), 1000)
    point = evaluate(direct=direct)[0]
    assert point.value == pytest.approx(20)
    assert (point.sample_count, point.valid_sample_count, point.invalid_sample_count) == (2, 2, 0)
    assert point.observed_at == END


@pytest.mark.parametrize("direct, expected", [(False, 52.5), (True, 40)])
def test_direct_and_chained_paths_keep_their_existing_weighting(rolling_sensor, direct, expected):
    add, evaluate = rolling_sensor
    add(START + timedelta(seconds=1), 10)
    add(START + timedelta(seconds=2), 20)
    add(START + timedelta(hours=12), 90)
    # Chained: ((10+20)/2 + 90)/2 = 52.5; direct: (10+20+90)/3 = 40.
    point = evaluate(direct=direct)[0]
    assert point.value == pytest.approx(expected)
    assert (point.sample_count, point.valid_sample_count, point.invalid_sample_count) == (3, 3, 0)


def test_include_invalid_preserves_explicit_opt_in_and_counts(rolling_sensor):
    add, evaluate = rolling_sensor
    add(START + timedelta(seconds=1), 10)
    add(START + timedelta(seconds=2), 30, valid=False)
    add(END, 80)
    point = evaluate(include_invalid=True)[0]
    assert point.value == pytest.approx(50)  # ((10+30)/2 + 80)/2
    assert (point.sample_count, point.valid_sample_count, point.invalid_sample_count) == (3, 2, 1)


@pytest.mark.parametrize("kind", ["absent", "outside", "invalid", "since_after_end"])
def test_no_eligible_observations_returns_no_result(rolling_sensor, frozen_clock, kind):
    add, evaluate = rolling_sensor
    if kind == "outside":
        add(START, 800)
        add(END + timedelta(seconds=1), 900)
    elif kind == "invalid":
        add(END, 10, valid=False)
    elif kind == "since_after_end":
        add(END, 10)
    since = END + timedelta(seconds=1) if kind == "since_after_end" else None
    assert evaluate(until=None, since=since) == []


@pytest.mark.parametrize("timezone_kind", ["naive_utc", "offset"])
def test_normalized_since_is_inclusive_and_keeps_its_partial_hour(rolling_sensor, timezone_kind):
    add, evaluate = rolling_sensor
    since = START + timedelta(hours=1, minutes=5)  # 05:55 UTC
    add(since - timedelta(seconds=1), 900)
    add(since, 10)
    add(since + timedelta(minutes=1), 30)
    add(END, 80)
    if timezone_kind == "naive_utc":
        since_arg, until_arg = since.replace(tzinfo=None), END.replace(tzinfo=None)
    else:
        offset = timezone(timedelta(hours=5, minutes=45))
        since_arg, until_arg = since.astimezone(offset), END.astimezone(offset)
    point = evaluate(since=since_arg, until=until_arg)[0]
    assert point.value == pytest.approx(50)  # ((10+30)/2 + 80)/2
    assert point.sample_count == 3
    assert point.observed_at == END


@pytest.mark.parametrize("implicit_until", [False, True])
def test_latest_api_preserves_raw_bounds_values_and_counts(rolling_sensor, frozen_clock, implicit_until):
    add, evaluate = rolling_sensor
    add(START, 900)
    add(START + timedelta(seconds=1), 10)
    add(START + timedelta(seconds=2), 20)
    add(END, 90)
    add(END - timedelta(seconds=1), 700, valid=False)
    add(END + timedelta(seconds=1), 1000)
    add(END + timedelta(days=22), 2000)
    rows = evaluate(public=True, until=None if implicit_until else END)
    assert len(rows) == 1
    row = rows[0]
    assert row["value"] == pytest.approx(52.5)
    assert (row["sample_count"], row["valid_sample_count"], row["invalid_sample_count"]) == (3, 3, 0)
    assert datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")) == END
    assert datetime.fromisoformat(row["interval_started_at"]) == START
    assert datetime.fromisoformat(row["interval_ended_at"]) == END
    assert datetime.fromisoformat(row["latest_source_observed_at"]) == END
    assert row["result_is_rolling"] is True
    assert row["query_since"] is None
    assert len(frozen_clock) == int(implicit_until)


def test_fixed_hour_history_keeps_inclusive_requested_bounds(rolling_sensor):
    add, evaluate = rolling_sensor
    add(START - timedelta(seconds=1), 900)
    add(START, 10)
    add(START + timedelta(minutes=1), 30)
    add(END, 80)
    add(END + timedelta(seconds=1), 1000)
    points = evaluate(since=START, result_code="qa_roll_1h", latest_only=False)
    assert [point.value for point in points] == pytest.approx([20, 80])
    assert [point.sample_count for point in points] == [2, 1]
    assert [point.observed_at for point in points] == [START.replace(minute=0), END.replace(minute=0)]


def test_nonrolling_latest_without_until_retains_unbounded_behavior(rolling_sensor):
    add, evaluate = rolling_sensor
    add(END, 10)
    add(END + timedelta(days=22), 30)
    native = evaluate(until=None, result_code="qa_roll_2m")[0]
    hourly = evaluate(until=None, result_code="qa_roll_1h")[0]
    assert native.value == hourly.value == 30
    assert native.sample_count == hourly.sample_count == 1
    assert native.observed_at == END + timedelta(days=22)
    assert hourly.observed_at == (END + timedelta(days=22)).replace(minute=0)
    assert native.latest_source_observed_at is hourly.latest_source_observed_at is None
    assert native.result_is_rolling is hourly.result_is_rolling is False
    assert native.interval_started_at is native.interval_ended_at is None
    assert hourly.interval_started_at == hourly.observed_at
    assert hourly.interval_ended_at == hourly.observed_at + timedelta(hours=1)


@pytest.mark.parametrize("direct, expected", [(False, 52.5), (True, 40)])
@pytest.mark.parametrize("public", [False, True, "all_latest", "device_sensors"], ids=["service", "api", "all_latest", "device_sensors"])
def test_source_freshness_tracks_raw_contributors_not_bucket_or_evaluation_time(rolling_sensor, direct, expected, public):
    add, evaluate = rolling_sensor
    latest = datetime(2026, 10, 9, 4, 0, tzinfo=UTC)
    add(START + timedelta(seconds=1), 10)
    add(START + timedelta(seconds=2), 20)
    add(latest, 90)
    add(END - timedelta(seconds=1), 700, valid=False)
    add(END + timedelta(seconds=1), 1000)
    point = evaluate(direct=direct, public=public)[0]
    if public:
        assert point["latest_value" if public == "device_sensors" else "value"] == pytest.approx(expected)
        assert datetime.fromisoformat(point["latest_source_observed_at"]) == latest
        assert datetime.fromisoformat(point["latest_observed_at" if public == "device_sensors" else "observed_at"]) == END
    else:
        assert point.value == pytest.approx(expected)
        assert point.latest_source_observed_at == latest
        assert point.observed_at == END


@pytest.mark.parametrize("public", [False, True], ids=["service", "api"])
def test_explicit_since_is_separate_from_nominal_interval(rolling_sensor, public):
    add, evaluate = rolling_sensor
    since = START + timedelta(hours=23)
    add(since - timedelta(seconds=1), 900)
    add(since, 10)  # Explicit since is inclusive, unlike the nominal rolling start.
    add(since + timedelta(minutes=1), 30)
    result = evaluate(since=since, public=public)[0]
    if public:
        assert result["value"] == pytest.approx(20)
        assert datetime.fromisoformat(result["query_since"]) == since
        assert datetime.fromisoformat(result["interval_started_at"]) == START
        assert datetime.fromisoformat(result["interval_ended_at"]) == END
        assert datetime.fromisoformat(result["latest_source_observed_at"]) == since + timedelta(minutes=1)
    else:
        assert result.value == pytest.approx(20)
        assert result.query_since == since
        assert (result.interval_started_at, result.interval_ended_at) == (START, END)
        assert result.latest_source_observed_at == since + timedelta(minutes=1)
