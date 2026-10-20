"""Offline Map contracts and persistence. Values are synthetic, not provider data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import models
from api.main import app
from db import get_session
from services.external_sources import derive_external_source_state
from services.import_summaries import new_import_summary
from sources.airgradient import importer, map_history as history, history_ingestion as ingest
from tests.test_airgradient_reference_locations import _reference_session
from sources.openaq import openaq_upserts

START = datetime(2026, 10, 10, tzinfo=timezone.utc)
END = START + timedelta(days=1)
NOW = END + timedelta(hours=1, minutes=7)
DASHBOARD = {"locationId": 175911, "locationName": "São Paulo", "latitude": -23.6473149,
             "longitude": -46.6643635, "publicContributorName": "Synthetic contributor", "pm02": 7.0,
             "timestamp": "2026-10-10T00:00:00Z"}
METADATA = {"locationId": 14699912, "locationName": "São Paulo", "latitude": -23.6473149,
            "longitude": -46.6643635, "provider": "AirGradient", "dataSource": "AirGradient",
            "licenses": ["CC BY-SA 4.0"], "ownerName": "Synthetic contributor", "url": None}


def envelope(rows):
    return {"total": len(rows), "page": None, "pagesize": None, "data": rows}


def row(timestamp=START, value=0):
    return {"timebucket": timestamp.isoformat(), "value": value}


def summary():
    result = new_import_summary()
    result["per_parameter"] = {}
    return result


def stub_history(monkeypatch, *, value=12.5, empty=False, fail_parameter=None):
    requests_seen = []

    def public_get(path, params=None):
        requests_seen.append((path, params))
        if params is None:
            return deepcopy(METADATA)
        if params["measure"] == fail_parameter:
            raise history.MapHistoryError("Synthetic provider failure")
        if empty:
            return envelope([])
        start = datetime.fromisoformat(params["start"])
        return envelope([row(start, 0), row(start + timedelta(minutes=15), value)])

    monkeypatch.setattr(history, "public_get", public_get)
    return requests_seen


@pytest.fixture
def location(tmp_path, monkeypatch):
    monkeypatch.delenv("AIRGRADIENT_API_KEY", raising=False)
    session, source = _reference_session(tmp_path)
    source.api_key = None
    source.params = {"import_authenticated_locations": False}
    device = importer._ensure_reference_device(session, DASHBOARD, source.external_api_id,
                                               "175911", "America/Sao_Paulo")
    importer._ensure_airgradient_sensors(session, device, DASHBOARD)
    sensor = session.scalar(select(models.Sensor).where(models.Sensor.device_id == device.device_id))
    session.add(models.Measurement(sensor_id=sensor.sensor_id, observed_at=START, value=7, is_valid=True))
    session.commit()
    yield session, source, device, sensor.sensor_id
    session.close()


def acquire(session, device, result, *, now=NOW):
    ingest.import_location_history(session, device, DASHBOARD, result,
                                   deadline=time.monotonic() + 60, now=now)


def test_explicit_location_and_parameter_namespaces():
    assert {key: value.map_id for key, value in history.REFERENCE_MAPPINGS.items()} == {
        "58376": 4955171, "175911": 14699912, "160791": 8334410,
    }
    assert {key: (value.parameter_code, value.unit_code) for key, value in history.PARAMETERS.items()} == {
        "pm25": ("pm25", "ug_m3"), "pm10": ("pm10", "ug_m3"),
        "atmp": ("temperature", "celsius"), "rhum": ("relative_humidity", "percent"), "rco2": ("co2", "ppm"),
    }
    assert history.validate_location("175911", DASHBOARD, METADATA).map_id == 14699912


@pytest.mark.parametrize("field,value", [
    ("locationId", 175911), ("locationName", "Other site"), ("latitude", -23.5),
    ("longitude", None), ("provider", "OpenAQ"), ("dataSource", "OpenAQ"),
    ("licenses", []), ("licenses", "CC BY-SA 4.0"), ("licenses", ["CC BY-SA 4.0", "Unverified license"]),
    ("ownerName", "Unattributed contributor"), ("url", "https://example.org"),
])
def test_mismatched_location_fails_safely(field, value):
    metadata = {**METADATA, field: value}
    with pytest.raises(history.MapHistoryError):
        history.validate_location("175911", DASHBOARD, metadata)


def test_unknown_dashboard_id_cannot_use_known_map_id():
    with pytest.raises(history.MapHistoryError):
        history.validate_location("14699912", DASHBOARD, METADATA)


def test_public_http_never_sends_credentials(monkeypatch):
    monkeypatch.setenv("AIRGRADIENT_API_KEY", "must-not-send")
    calls = []

    class Response:
        status_code = 200
        def json(self):
            return envelope([])

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(requests, "get", get)
    history.fetch_history(14699912, "pm25", START, END)
    url, kwargs = calls[0]
    assert url == "https://map-data.airgradient.com/map/api/v1/locations/14699912/measures/history"
    assert kwargs["params"] == {"measure": "pm25", "bucketSize": "15m", "excludeOutliers": "true",
                                "start": START.isoformat(), "end": "2026-10-10T23:59:59.999000+00:00"}
    assert kwargs["allow_redirects"] is False
    assert "headers" not in kwargs and "auth" not in kwargs
    assert "must-not-send" not in str(calls)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503, 302])
def test_provider_errors_do_not_return_data(monkeypatch, status):
    response = type("Response", (), {"status_code": status})()
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    error = history.MapHistoryRateLimit if status == 429 else history.MapHistoryError
    with pytest.raises(error):
        history.public_get("locations/14699912")


def test_network_failure_is_sanitized(monkeypatch):
    def get(*args, **kwargs):
        raise requests.ConnectionError("sensitive URL content")
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(history.MapHistoryError, match="could not be reached") as exc:
        history.public_get("locations/14699912")
    assert "sensitive" not in str(exc.value)


def test_zero_null_and_decimal_string_contract():
    observations, missing = history.parse_history(envelope([
        row(value=0), row(START + timedelta(minutes=15), None),
        row(START + timedelta(minutes=30), "-1.25"),
    ]), START, END)
    assert [item.value for item in observations] == [0.0, -1.25]
    assert missing == 1
    assert history.parse_history(envelope([]), START, END) == ([], 0)


@pytest.mark.parametrize("payload", [
    [], {}, {"data": [], "total": 1}, {"data": [], "total": True},
    envelope([{"timebucket": "bad", "value": 1}]),
    envelope([{"timebucket": "2026-10-10T00:00:00", "value": 1}]),
    envelope([row(START + timedelta(seconds=1))]), envelope([row(END)]),
    envelope([row(), row()]), envelope([row(value=True)]), envelope([row(value="NaN")]),
    envelope([row(value=float("inf"))]), envelope([row(value={})]), envelope([{"timebucket": START.isoformat()}]),
])
def test_malformed_or_partial_response_rejects_whole_interval(payload):
    with pytest.raises(history.MapHistoryError):
        history.parse_history(payload, START, END)


def test_unsupported_parameters_and_resolution(monkeypatch):
    with pytest.raises(history.MapHistoryError, match="Unsupported"):
        history.fetch_history(14699912, "tvoc", START, END)
    with pytest.raises(history.MapHistoryError, match="resolution"):
        history.parse_history(envelope([row(START + timedelta(minutes=i)) for i in range(97)]), START, END)


def test_delay_and_bounded_catchup_are_independently_expected():
    assert history.closed_until(NOW) == END
    assert list(history.windows(None, END)) == [(START, END)]
    checkpoint = START - timedelta(days=5)
    windows = list(history.windows(checkpoint, END))
    assert windows == [
        (datetime(2026, 10, 4, 18, tzinfo=timezone.utc), datetime(2026, 10, 5, 18, tzinfo=timezone.utc)),
        (datetime(2026, 10, 5, 18, tzinfo=timezone.utc), datetime(2026, 10, 6, 18, tzinfo=timezone.utc)),
    ]


def test_history_is_separate_and_completeness_is_unknown(location, monkeypatch):
    session, source, device, snapshot_id = location
    stub_history(monkeypatch)
    result = summary()
    acquire(session, device, result)
    streams = session.scalars(select(models.Sensor).order_by(models.Sensor.sensor_id)).all()
    assert len(streams) == 6
    assert streams[0].sensor_id == snapshot_id and streams[0].external_sensor_id == "175911:pm02"
    assert streams[0].measurement_timestamp_semantics == "observation_instant"
    assert session.scalar(select(models.Measurement.value).where(models.Measurement.sensor_id == snapshot_id)) == 7
    assert result["measurements_inserted"] == 10 and result["sensors_created"] == 5
    assert result["history_intervals_examined"] == 5 and "errors" not in result
    for sensor in streams[1:]:
        assert sensor.external_sensor_id.startswith("map:14699912:")
        assert sensor.measurement_duration_seconds is None
        assert sensor.source_aggregation_duration_seconds == 900
        assert sensor.acquisition_metadata["underlying_sample_count"] is None
        assert sensor.acquisition_metadata["underlying_coverage_seconds"] is None
        assert sensor.acquisition_examined_until.replace(tzinfo=timezone.utc) == END
        assert sensor.acquisition_metadata["license_code"] == "CC-BY-SA-4.0"


def test_empty_success_advances_checkpoint_and_is_not_an_endless_backfill(location, monkeypatch):
    session, _, device, _ = location
    stub_history(monkeypatch, empty=True)
    acquire(session, device, summary())
    requests_seen = stub_history(monkeypatch, empty=True)
    result = summary()
    acquire(session, device, result, now=NOW + timedelta(hours=1))
    assert result["measurements_received"] == 0
    history_calls = [params for _, params in requests_seen if params]
    assert len(history_calls) == 5
    assert all(params["start"] == "2026-10-10T18:00:00+00:00" for params in history_calls)


def test_failed_parameter_checkpoint_does_not_advance_and_other_parameters_commit(location, monkeypatch):
    session, _, device, _ = location
    stub_history(monkeypatch, fail_parameter="pm10")
    result = summary()
    acquire(session, device, result)
    assert result["history_intervals_failed"] == 1
    assert result["history_intervals_examined"] == 4 and result["measurements_inserted"] == 8
    assert len(result["errors"]) == 1
    failed_sensor = session.scalar(select(models.Sensor).where(models.Sensor.external_sensor_id == "map:14699912:pm10:15m"))
    assert failed_sensor.acquisition_examined_until is None
    assert failed_sensor.acquisition_metadata["initial_interval_start"] == START.isoformat()
    stub_history(monkeypatch)
    second = summary()
    acquire(session, device, second)
    assert second["sensors_created"] == 0
    assert second["history_progress"][1]["start"] == START.isoformat()


def test_overlap_duplicate_skips_and_explicit_provider_revision_updates(location, monkeypatch):
    session, _, device, _ = location
    calls = []
    original = ingest.upsert_measurement_with_policy_detailed
    qc_calls = []
    original_qc = openaq_upserts.run_ingest_detailed
    def qc(records, context):
        qc_calls.extend(records)
        return original_qc(records, context)
    monkeypatch.setattr(openaq_upserts, "run_ingest_detailed", qc)
    def upsert(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result.action)
        return result
    monkeypatch.setattr(ingest, "upsert_measurement_with_policy_detailed", upsert)
    stub_history(monkeypatch)
    acquire(session, device, summary())
    assert len(qc_calls) == 10
    # Force retry of the identical initial interval, modeling a saved checkpoint
    # from an earlier examination with measurements already present.
    for sensor in session.scalars(select(models.Sensor).where(models.Sensor.sensor_id != location[3])):
        sensor.acquisition_examined_until = START + timedelta(hours=6)
    session.commit()
    calls.clear()
    stub_history(monkeypatch, value=99)
    skipped = summary()
    acquire(session, device, skipped)
    assert skipped["measurements_skipped"] == 10 and calls == ["skip"] * 10
    assert len(qc_calls) == 10
    assert session.scalar(select(func.count()).select_from(models.Measurement)) == 11
    device.allow_updates = models.UpdatePolicy.ALLOW
    for sensor in session.scalars(select(models.Sensor).where(models.Sensor.sensor_id != location[3])):
        sensor.acquisition_examined_until = START + timedelta(hours=6)
    session.commit()
    updated = summary()
    acquire(session, device, updated)
    assert updated["measurements_updated"] == 10
    assert len(qc_calls) == 20
    values = session.scalars(select(models.Measurement.value).where(models.Measurement.sensor_id != location[3])).all()
    assert sorted(values) == [0.0] * 5 + [99.0] * 5


def test_transaction_failure_rolls_back_values_and_checkpoint(location, monkeypatch):
    session, _, device, _ = location
    stub_history(monkeypatch)
    original = session.commit
    def crash():
        if any(isinstance(item, models.Sensor) and item.acquisition_examined_until is not None for item in session.dirty):
            raise RuntimeError("simulated lost observation transaction")
        original()
    monkeypatch.setattr(session, "commit", crash)
    failed = summary()
    acquire(session, device, failed)
    assert failed["measurements_inserted"] == 0 and failed["history_intervals_failed"] == 5
    assert failed["measurements_received"] == 10 and failed["measurements_failed"] == 10
    assert session.scalar(select(func.count()).select_from(models.Sensor)) == 6
    assert all(sensor.acquisition_examined_until is None for sensor in session.scalars(select(models.Sensor)))
    assert session.scalar(select(func.count()).select_from(models.Measurement)) == 1
    monkeypatch.setattr(session, "commit", original)
    recovered = summary()
    acquire(session, device, recovered)
    assert recovered["measurements_inserted"] == 10


def test_time_budget_defers_without_advancing(location, monkeypatch):
    session, _, device, _ = location
    stub_history(monkeypatch)
    result = summary()
    ingest.import_location_history(session, device, DASHBOARD, result, deadline=0, now=NOW)
    assert result["history_work_remaining"] is True
    assert result["history_intervals_examined"] == 0
    assert session.scalar(select(func.count()).select_from(models.Sensor)) == 1


def test_late_arriving_buckets_are_retrieved_from_overlap(location, monkeypatch):
    session, _, device, _ = location
    stub_history(monkeypatch, empty=True)
    acquire(session, device, summary())
    requests_seen = stub_history(monkeypatch, value=3)
    result = summary()
    acquire(session, device, result, now=NOW + timedelta(hours=1))
    assert result["measurements_inserted"] == 10
    assert [params["start"] for _, params in requests_seen if params] == ["2026-10-10T18:00:00+00:00"] * 5
    assert all(progress["examined_until"].startswith("2026-10-11T01:00:00") for progress in result["history_progress"])


def test_processing_budget_rolls_back_partial_interval(location, monkeypatch):
    session, _, device, _ = location
    stub_history(monkeypatch)
    clock = {"now": 0}
    monkeypatch.setattr(ingest, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    original = ingest.upsert_measurement_with_policy_detailed
    def expire_after_first_write(*args, **kwargs):
        result = original(*args, **kwargs)
        clock["now"] = 100
        return result
    monkeypatch.setattr(ingest, "upsert_measurement_with_policy_detailed", expire_after_first_write)
    result = summary()
    ingest.import_location_history(session, device, DASHBOARD, result, deadline=10, now=NOW)
    assert result["history_work_remaining"] and result["history_intervals_deferred"] == 1
    assert result["measurements_inserted"] == 0 and result["history_intervals_examined"] == 0
    assert session.scalar(select(func.count()).select_from(models.Measurement)) == 1
    sensor = session.scalar(select(models.Sensor).where(models.Sensor.external_sensor_id == "map:14699912:pm25:15m"))
    assert sensor.acquisition_examined_until is None
    assert sensor.acquisition_metadata["initial_interval_start"] == START.isoformat()


def test_malformed_json_fails_before_processing(monkeypatch):
    class Response:
        status_code = 200
        def json(self):
            raise ValueError("Synthetic malformed JSON")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    with pytest.raises(history.MapHistoryError, match="malformed JSON"):
        history.public_get("locations/14699912")


def test_public_only_config_and_authenticated_opt_in(location):
    session, source, _, _ = location
    assert derive_external_source_state(source, {}).is_runnable
    assert importer._load_airgradient_config(session)[2] == ""
    assert not importer._authenticated_import_enabled(source)
    source.params = {"import_authenticated_locations": True}
    assert not derive_external_source_state(source, {}).is_runnable
    with pytest.raises(importer.AirGradientImporterError, match="API key"):
        importer._load_airgradient_config(session)
    source.api_key = "legacy-key"
    source.params = {}
    assert importer._authenticated_import_enabled(source)


def test_environment_credential_presence_is_distinct_from_public_readiness(location, monkeypatch):
    from api.routes.admin.external_apis import _external_api_out
    session, source, _, _ = location
    assert not _external_api_out(session, source, device_count=1).credential_configured
    monkeypatch.setenv("AIRGRADIENT_API_KEY", "synthetic-environment-credential")
    source.params = {}
    output = _external_api_out(session, source, device_count=1)
    assert output.credential_configured and not output.has_api_key
    assert importer._authenticated_import_enabled(source)
    assert "synthetic-environment-credential" not in output.model_dump_json()


def test_setup_reports_public_readiness_and_missing_private_credential(location):
    from api.routes.setup import configure_data_source, ConfigureDataSourceRequest
    session, source, _, _ = location
    public = configure_data_source(ConfigureDataSourceRequest(
        external_api_id=source.external_api_id, enabled=True, import_authenticated_locations=False,
    ), session)
    assert public.is_configured is True
    private = configure_data_source(ConfigureDataSourceRequest(
        external_api_id=source.external_api_id, enabled=True, import_authenticated_locations=True,
    ), session)
    assert private.is_configured is False


def test_history_metadata_serializes_with_existing_attribution(location, monkeypatch):
    session, _, device, _ = location
    device.contributor_name = None
    session.commit()
    stub_history(monkeypatch)
    acquire(session, device, summary())
    sensor = session.scalar(select(models.Sensor).where(models.Sensor.external_sensor_id == "map:14699912:pm25:15m"))
    app.dependency_overrides[get_session] = lambda: session
    try:
        response = TestClient(app).get(f"/sensors/{sensor.sensor_id}/history?aggregation=15m&start=2026-10-10T00:00:00Z&end=2026-10-11T00:00:00Z")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["acquisition_metadata"]["acquisition_method"] == "map_processed_history"
        assert body["measurement_duration_seconds"] is None
        assert body["data_attribution"]["license_code"] == "CC-BY-SA-4.0"
        assert body["data_attribution"]["contributor_name"] == "Synthetic contributor"
        assert body["data"][0]["value"] == 0
        latest = TestClient(app).get("/measurements/pm25/latest", params={
            "device_id": device.device_id, "aggregation": "15m", "all_results": True,
        })
        assert latest.status_code == 200, latest.text
        assert latest.json()[0]["acquisition_metadata"]["underlying_sample_count"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("standard,product", [
    ("us_epa", "us_epa.pm25.nowcast"),
    ("eea_european", "eea_european.pm25.hourly"),
    ("philippines_denr", "philippines_denr.pm25.completed_day"),
])
def test_nominal_15m_buckets_never_qualify_for_aqi(location, monkeypatch, standard, product):
    session, _, device, _ = location
    def public_get(path, params=None):
        if params is None:
            return METADATA
        return envelope([row(START + timedelta(minutes=15 * i), 10) for i in range(96)])
    monkeypatch.setattr(history, "public_get", public_get)
    acquire(session, device, summary())
    app.dependency_overrides[get_session] = lambda: session
    try:
        response = TestClient(app).get(f"/air-quality-index/{standard}/latest", params={
            "device_id": device.device_id, "product_code": product, "until": NOW.isoformat(),
        })
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert results
        for result in results:
            assert result["eligibility_status"] != "eligible"
            assert result["category_code"] is None
    finally:
        app.dependency_overrides.clear()


def test_full_public_import_without_token_preserves_snapshots(location, monkeypatch):
    session, source, device, snapshot_id = location
    from tests.test_airgradient_reference_locations import _provider_payloads
    payloads = _provider_payloads()
    for location_id, payload in payloads.items():
        mapping = history.REFERENCE_MAPPINGS[location_id]
        payload["locationName"] = mapping.name
    payloads["175911"] = DASHBOARD
    source.params = {"import_authenticated_locations": False}
    session.commit()
    def dashboard_get(path, api_key, params=None, include_token=True):
        assert not api_key and not include_token
        assert "/world/locations/" in path
        return payloads[path.split("/world/locations/")[1].split("/")[0]]
    def public_get(path, params=None):
        map_id = int(path.split("/")[1])
        location_id, mapping = next((key, value) for key, value in history.REFERENCE_MAPPINGS.items() if value.map_id == map_id)
        payload = payloads[location_id]
        if params is None:
            return {**METADATA, "locationId": map_id, "locationName": mapping.name,
                    "latitude": mapping.latitude, "longitude": mapping.longitude,
                    "ownerName": payload.get("publicContributorName"), "url": payload.get("publicPlaceUrl")}
        return envelope([])
    monkeypatch.setattr(importer, "_api_get", dashboard_get)
    monkeypatch.setattr(history, "public_get", public_get)
    monkeypatch.setattr(importer, "SessionLocal", sessionmaker(bind=session.get_bind()))
    result = importer.run_import()
    assert result["devices_processed"] == 3
    assert result["import_authenticated_locations"] is False
    assert result["history_intervals_examined"] == 15
    assert "errors" not in result
    session.expire_all()
    assert session.get(models.Sensor, snapshot_id).external_sensor_id == "175911:pm02"
    assert session.scalar(select(models.Measurement.value).where(models.Measurement.sensor_id == snapshot_id)) == 7


def test_rate_limit_stops_parameter_requests_and_keeps_checkpoint(location, monkeypatch):
    session, _, device, _ = location
    def public_get(path, params=None):
        if params is None:
            return METADATA
        raise history.MapHistoryRateLimit("Synthetic rate limit")
    monkeypatch.setattr(history, "public_get", public_get)
    result = summary()
    with pytest.raises(history.MapHistoryRateLimit):
        acquire(session, device, result)
    assert result["history_intervals_failed"] == 1
    assert result["history_intervals_examined"] == 0
    assert session.scalar(select(func.count()).select_from(models.Sensor)) == 2


def test_first_poll_outage_does_not_slide_the_initial_lookback(location, monkeypatch):
    session, _, device, _ = location
    stub_history(monkeypatch, fail_parameter="pm25")
    acquire(session, device, summary())
    calls = stub_history(monkeypatch)
    recovered = summary()
    acquire(session, device, recovered, now=NOW + timedelta(days=3))
    pm25_requests = [params for _, params in calls if params and params["measure"] == "pm25"]
    assert [request["start"] for request in pm25_requests] == [START.isoformat(), END.isoformat()]
    assert recovered["history_work_remaining"] is True


def test_authenticated_view_of_reference_cannot_be_reclassified_as_public_history(location, monkeypatch):
    session, _, device, _ = location
    device.acquisition_path = "airgradient_authenticated"
    session.commit()
    calls = stub_history(monkeypatch)
    with pytest.raises(history.MapHistoryError, match="public reference"):
        acquire(session, device, summary())
    assert calls == [] and device.acquisition_path == "airgradient_authenticated"
