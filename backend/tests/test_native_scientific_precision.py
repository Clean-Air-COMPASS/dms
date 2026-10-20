"""Native scientific values are observations, even when their period has rules."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from api.main import app
from db import get_session
import models
from services import csv_measurement_import
from services.measurement_aggregation import execute_measurement_aggregation
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed


PARAMETER_UNITS = {
    "pm25": ("ug_m3", "µg/m³"),
    "pm10": ("ug_m3", "µg/m³"),
    "o3": ("ppm", "ppm"),
    "no2": ("ppm", "ppm"),
    "so2": ("ppm", "ppm"),
    "co": ("ppm", "ppm"),
    "no": ("ppb", "ppb"),
    "nox": ("ppb", "ppb"),
    "pm1": ("ug_m3", "µg/m³"),
    "co2": ("ppm", "ppm"),
    "temperature": ("celsius", "°C"),
    "relative_humidity": ("percent", "%"),
    "pressure": ("hpa", "hPa"),
    "tvoc": ("ppb", "ppb"),
    "tvoc_index": ("index", "index"),
    "nox_index": ("index", "index"),
}


@pytest.fixture
def precision_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'precision.sqlite'}",
                           connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(csv_measurement_import, "SessionLocal", factory)
    monkeypatch.setenv("COMPASSAQ_CSV_UPLOAD_API_KEY", "precision-test-only")

    def session_dependency():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def make_stream(factory, parameter_code="pm25", native_code="1m", method="round"):
    with factory() as session:
        unit_code, unit_symbol = PARAMETER_UNITS[parameter_code]
        unit = models.Unit(code=unit_code, symbol=unit_symbol, name=f"Fixture {unit_code}")
        session.add(unit)
        session.flush()
        parameter = models.Parameter(code=parameter_code, display_name=parameter_code, default_unit_id=unit.unit_id)
        source = models.ExternalAPI(name="SYNTHETIC precision provider", enabled=False, params={})
        periods = {code: models.AggregationPeriod(code=code, display_name=code, duration_minutes=minutes, is_rolling=False)
                   for code, minutes in [("1m", 1), ("1h", 60), ("24h", 1440)]}
        session.add_all([parameter, source, *periods.values()])
        session.flush()
        device = models.Device(name="SYNTHETIC precision station", external_api_id=source.external_api_id, timezone="UTC")
        session.add(device)
        session.flush()
        sensor = models.Sensor(device_id=device.device_id, parameter_id=parameter.parameter_id,
                               unit_id=unit.unit_id, aggregation_period_id=periods[native_code].aggregation_period_id,
                               external_sensor_id="SYNTHETIC-native-precision", measurement_timestamp_semantics="instant")
        session.add(sensor)
        for period in periods.values():
            session.add(models.ParameterAggregationRule(parameter_id=parameter.parameter_id,
                aggregation_period_id=period.aggregation_period_id, active=True,
                rounding_method="round" if method == "round" else "none", rounding_precision=1,
                truncation_method="truncate" if method == "truncate" else "none", truncation_precision=1))
        for source_code, target_code in [("1m", "1h"), ("1h", "24h")]:
            session.add(models.ParameterAggregationRollup(parameter_id=parameter.parameter_id,
                from_aggregation_period_id=periods[source_code].aggregation_period_id,
                to_aggregation_period_id=periods[target_code].aggregation_period_id))
        session.commit()
        return sensor.sensor_id, device.device_id


OBSERVED_AT = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("parameter", list(PARAMETER_UNITS))
@pytest.mark.parametrize("method", ["round", "truncate"])
def test_native_pollutants_retain_stored_precision_and_display_metadata(precision_database, parameter, method):
    sid, device_id = make_stream(precision_database, parameter, method=method)
    value = 0.07856123456789 if parameter == "o3" else 10.123456789
    with precision_database() as session:
        session.add(models.Measurement(sensor_id=sid, value=value, observed_at=OBSERVED_AT, is_valid=True))
        session.commit()
    client = TestClient(app)
    for aggregation in ["raw", "latest", "1m"]:
        response = client.get(f"/sensors/{sid}/history", params={"aggregation": aggregation, "start": OBSERVED_AT.isoformat()})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["data"][0]["value"] == value
        assert payload["data"][0]["timestamp"] == OBSERVED_AT.isoformat()
        assert payload["display_precision"] == 1
        assert payload["formatting_status"] == "configured"
        assert payload["external_sensor_id"] == "SYNTHETIC-native-precision"
        assert payload["unit"] == PARAMETER_UNITS[parameter][1]
        assert payload["external_api"]["name"] == "SYNTHETIC precision provider"
        assert payload["native_aggregation_code"] == payload["result_aggregation_code"] == "1m"
    response = client.get(f"/measurements/{parameter}/latest", params={"device_id": device_id})
    assert response.status_code == 200, response.text
    assert response.json()[0]["value"] == value


@pytest.mark.parametrize("period", ["1h", "24h"])
def test_imported_native_hourly_and_daily_are_not_reprocessed(precision_database, period):
    sid, device_id = make_stream(precision_database, native_code=period, method="truncate")
    with precision_database() as session:
        session.add(models.Measurement(sensor_id=sid, value=12.3987654321, observed_at=OBSERVED_AT, is_valid=True))
        session.commit()
    response = TestClient(app).get('/measurements/pm25/latest', params={"device_id": device_id, "aggregation": period})
    assert response.status_code == 200, response.text
    assert response.json()[0]["value"] == 12.3987654321


def test_csv_native_history_reproduces_independent_24_point_mean(precision_database):
    sid, _ = make_stream(precision_database)
    # Original DEF-004 fixture: one precise value followed by 10.1 through 12.3.
    values = [Decimal("10.123456789"), *[Decimal(100 + i) / 10 for i in range(1, 24)]]
    assert sum(values) / 24 == Decimal("11.155144032875")
    csv_text = "internalsensorid,datetime,value\n" + "\n".join(
        f"{sid},{(OBSERVED_AT + timedelta(minutes=index)).isoformat()},{value}" for index, value in enumerate(values))
    client = TestClient(app)
    response = client.post('/ingest/upload-csv', headers={"X-API-Key": "precision-test-only"},
                           files={"file": ("native.csv", io.BytesIO(csv_text.encode()), "text/csv")})
    assert response.status_code == 200, response.text
    history = client.get(f"/sensors/{sid}/history", params={"aggregation": "raw", "start": OBSERVED_AT.isoformat(), "include_qc": True}).json()
    returned = [Decimal(str(row["value"])) for row in history["data"]]
    assert returned == values
    assert sum(returned) / 24 == Decimal("11.155144032875")
    assert all(row["is_valid"] for row in history["data"])
    with precision_database() as session:
        stored = list(session.scalars(select(models.Measurement.value).where(models.Measurement.sensor_id == sid).order_by(models.Measurement.observed_at)))
        assert stored == [float(value) for value in values]


def test_provider_upsert_preserves_value_and_qc_filtering(precision_database):
    sid, _ = make_stream(precision_database)
    with precision_database() as session:
        sensor = session.get(models.Sensor, sid)
        result = upsert_measurement_with_policy_detailed(session,
            models.Measurement(sensor_id=sid, value=10.123456789, observed_at=OBSERVED_AT), sensor=sensor)
        assert result.action == "insert"
        session.add(models.Measurement(sensor_id=sid, value=99.987654321, observed_at=OBSERVED_AT + timedelta(minutes=1),
                                       is_valid=False, qc_flags=["max_value"]))
        session.commit()
    client = TestClient(app)
    params = {"aggregation": "raw", "start": OBSERVED_AT.isoformat(), "include_qc": True}
    valid = client.get(f"/sensors/{sid}/history", params=params).json()
    assert [row["value"] for row in valid["data"]] == [10.123456789]
    included = client.get(f"/sensors/{sid}/history", params={**params, "include_invalid": True}).json()
    assert [row["value"] for row in included["data"]] == [10.123456789, 99.987654321]
    assert included["data"][1]["is_valid"] is False
    assert included["data"][1]["qc_flags"] == ["max_value"]
    assert included["data"][1]["invalid_sample_count"] == 1


def test_derived_hourly_and_daily_processing_stays_authorized(precision_database):
    sid, _ = make_stream(precision_database, method="truncate")
    with precision_database() as session:
        # Unequal populations distinguish equal-hour weighting from direct weighting.
        for offset, value in [(0, 10.123456789), (1, 10.987654321), (60, 30.987654321)]:
            session.add(models.Measurement(sensor_id=sid, value=value, observed_at=OBSERVED_AT + timedelta(minutes=offset), is_valid=True))
        session.commit()
        options = dict(sensor_ids=[sid], parameter_code="pm25", native_aggregation_code="1m")
        hourly = execute_measurement_aggregation(session, **options, result_aggregation_code="1h")
        daily = execute_measurement_aggregation(session, **options, result_aggregation_code="24h")
        assert [point.value for point in hourly] == [10.5, 30.9]
        # (mean(10.123456789,10.987654321) + 30.987654321) / 2, truncated once.
        assert daily[0].value == 20.7
        assert daily[0].sample_count == 3


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "", "null"])
def test_csv_rejects_missing_and_nonfinite_scientific_values(precision_database, value):
    sid, _ = make_stream(precision_database)
    response = TestClient(app).post('/ingest/upload-csv', headers={"X-API-Key": "precision-test-only"},
        files={"file": ("invalid.csv", f"internalsensorid,datetime,value\n{sid},{OBSERVED_AT.isoformat()},{value}", "text/csv")})
    assert response.status_code == 200, response.text
    assert response.json()["success"] is False
    assert response.json()["failed_records"] == 1
    assert response.json()["row_errors"][0]["line"] == 2
    with precision_database() as session:
        assert list(session.scalars(select(models.Measurement))) == []
