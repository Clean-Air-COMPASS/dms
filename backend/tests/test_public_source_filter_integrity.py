"""Public filters must use the same source identity as public provenance."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db import SessionLocal
from models import AggregationPeriod, Device, ExternalAPI, Measurement, Parameter, ParameterAggregationRollup, Sensor, Unit


@pytest.fixture(scope="module")
def source_streams():
    with SessionLocal() as session:
        suffix = uuid4().hex
        names = {key: f"{key}-{suffix}" for key in ("OpenAQ", "PurpleAir", "AirGradient")}
        names["similar"] = names["OpenAQ"] + "-similar"
        names["absent"] = ""
        providers = {}
        for key, name in names.items():
            provider = ExternalAPI(name=name, params={}, enabled=False)
            session.add(provider)
            session.flush()
            providers[key] = provider.external_api_id
        parameter = session.scalar(select(Parameter).where(Parameter.code == "pm25"))
        unit = session.scalar(select(Unit).where(Unit.code == "ug_m3"))
        periods = {}
        for code, minutes in (("1m", 1), ("5m", 5), ("15m", 15)):
            period = session.scalar(select(AggregationPeriod).where(AggregationPeriod.code == code))
            if period is None:
                period = AggregationPeriod(code=code, display_name=code)
                session.add(period)
            period.duration_minutes = minutes
            period.is_rolling = False
            session.flush()
            periods[code] = period.aggregation_period_id
        hourly = session.scalar(select(AggregationPeriod).where(AggregationPeriod.code == '1h'))
        hourly.duration_minutes = 60
        hourly.is_rolling = False
        if session.scalar(select(ParameterAggregationRollup).where(
            ParameterAggregationRollup.parameter_id == parameter.parameter_id,
            ParameterAggregationRollup.from_aggregation_period_id == periods['5m'],
            ParameterAggregationRollup.to_aggregation_period_id == hourly.aggregation_period_id,
        )) is None:
            session.add(ParameterAggregationRollup(parameter_id=parameter.parameter_id,
                from_aggregation_period_id=periods['5m'], to_aggregation_period_id=hourly.aggregation_period_id))
        observed_at = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        streams = {}
        for key, provider, manual, period in (
            ("manual", "OpenAQ", "Neighborhood Lab", "5m"),
            ("OpenAQ", "OpenAQ", None, "5m"),
            ("PurpleAir", "PurpleAir", None, "5m"),
            ("snapshot", "AirGradient", None, "1m"),
            ("history", "AirGradient", None, "15m"),
            ("similar", "similar", None, "5m"),
            ("absent", "absent", None, "5m"),
        ):
            device = Device(name=f"SYNTHETIC {key} {suffix}", external_api_id=providers[provider],
                            manual_data_source_name=manual, timezone="UTC")
            session.add(device)
            session.flush()
            sensor = Sensor(device_id=device.device_id, parameter_id=parameter.parameter_id,
                            unit_id=unit.unit_id, aggregation_period_id=periods[period])
            session.add(sensor)
            session.flush()
            session.add(Measurement(sensor_id=sensor.sensor_id, value=13.291666666666666,
                                    observed_at=observed_at, is_valid=True))
            streams[key] = (device.device_id, sensor.sensor_id)
        session.commit()
        return names, streams, observed_at


@pytest.mark.parametrize("endpoint", ["/devices", "/measurements/pm25/latest", "/measurements/latest"])
@pytest.mark.parametrize("source,expected", [
    ("all", {"manual", "OpenAQ", "PurpleAir", "snapshot", "history", "similar", "absent"}),
    ("OpenAQ", {"OpenAQ"}), ("other", {"manual"}),
    ("PurpleAir", {"PurpleAir"}), ("AirGradient", {"snapshot", "history"}),
    ("similar", {"similar"}),
])
def test_public_discovery_matches_displayed_source(source_streams, endpoint, source, expected):
    names, streams, observed_at = source_streams
    params = {"since": observed_at.isoformat()}
    if source != "all":
        params["external_api_name"] = " OtHeR " if source == "other" else f" {names[source].upper()} "
    response = TestClient(app).get(endpoint, params=params)
    assert response.status_code == 200, response.text
    rows = response.json()
    returned = {row["device_id"] if endpoint == "/devices" else row["device"]["device_id"] for row in rows}
    fixture_devices = {ids[0] for ids in streams.values()}
    assert returned & fixture_devices == {streams[key][0] for key in expected}
    for row in rows:
        device = row if endpoint == "/devices" else row["device"]
        if device["device_id"] == streams["manual"][0]:
            assert device["network"] == "Other"
            assert device["data_attribution"]["data_provider_name"] == "Other"


def test_capabilities_exclude_manual_streams_from_provider(source_streams):
    names, streams, _ = source_streams
    client = TestClient(app)
    # The manual device is the only manual 5m fixture. Give it a unique native
    # period so a leaking capability cannot be hidden by the real OpenAQ group.
    with SessionLocal() as session:
        period = AggregationPeriod(code=f"integrity-{uuid4().hex[:16]}", display_name="Synthetic period")
        session.add(period)
        session.flush()
        sensor = session.get(Sensor, streams["manual"][1])
        previous_period = sensor.aggregation_period_id
        sensor.aggregation_period_id = period.aggregation_period_id
        session.commit()
        code = period.code
    try:
        for source, expected in ((names["OpenAQ"], False), ("other", True), ("", True)):
            response = client.get("/measurement-aggregation-capabilities", params={"source": source, "parameter": "pm25"})
            assert response.status_code == 200, response.text
            assert any(row["native_aggregation_code"] == code for row in response.json()) is expected
    finally:
        with SessionLocal() as session:
            session.get(Sensor, streams["manual"][1]).aggregation_period_id = previous_period
            session.commit()


@pytest.mark.parametrize("source,includes_manual", [("OpenAQ", False), ("other", True), ("all", True)])
def test_legacy_aggregate_uses_public_source_identity(source_streams, source, includes_manual):
    names, streams, observed_at = source_streams
    params = {"from": "5m", "to": "1h", "since": observed_at.isoformat(),
              "until": (observed_at + timedelta(hours=1)).isoformat()}
    if source != "all":
        params["external_api_name"] = names[source] if source != "other" else "other"
    response = TestClient(app).get("/measurements/pm25/aggregate", params=params)
    assert response.status_code == 200, response.text
    assert any(row["sensor_id"] == streams["manual"][1] for row in response.json()) is includes_manual


def test_editing_manual_device_preserves_source_and_history(source_streams, admin_auth_headers):
    names, streams, _ = source_streams
    device_id, sensor_id = streams["manual"]
    with SessionLocal() as session:
        provider_id = session.get(Device, device_id).external_api_id
    response = TestClient(app).put(f"/admin/devices/{device_id}",
                                    json={"friendly_name": "SYNTHETIC renamed"}, headers=admin_auth_headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as session:
        device = session.get(Device, device_id)
        assert device.external_api_id == provider_id
        assert device.manual_data_source_name == "Neighborhood Lab"
        assert session.scalar(select(Measurement).where(Measurement.sensor_id == sensor_id)) is not None
    history = TestClient(app).get(f"/sensors/{sensor_id}/history", params={"aggregate": "raw"})
    assert history.status_code == 200, history.text
    assert history.json()["external_api"]["name"] == "Other"
