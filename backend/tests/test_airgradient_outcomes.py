"""DEF-006: acquisition outcomes are independent of observation counts.

HTTP responses here are synthetic provider fixtures. Real PostgreSQL/subprocess
and browser acceptance evidence is recorded separately in the DEF-006 report.
"""
import json
import sys
from datetime import datetime, timezone

import pytest
import requests
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import models
from sources.airgradient import importer, map_history
from tests.test_airgradient_reference_locations import _provider_payloads, _reference_session
from tests.test_airgradient_authenticated import _authenticated_fixtures


@pytest.fixture
def acquisition(tmp_path, monkeypatch):
    session, source = _reference_session(tmp_path)
    source.api_key = None
    source.params = {"import_authenticated_locations": False}
    session.commit()
    monkeypatch.delenv("AIRGRADIENT_API_KEY", raising=False)
    monkeypatch.setattr(importer, "SessionLocal", sessionmaker(bind=session.get_bind()))
    monkeypatch.setattr(importer, "import_location_history", lambda *args, **kwargs: None)
    events = []
    monkeypatch.setattr(importer, "_emit_event", lambda *args, **kwargs: events.append((args, kwargs)))
    yield session, source, events
    session.close()


def provider(monkeypatch, failed=(), *, empty=False, empty_place=False, error="network"):
    payloads = _provider_payloads()
    calls = []
    place, locations = _authenticated_fixtures()

    def get(url, params, timeout):
        calls.append(url)
        if url.endswith("/place"):
            payload = place
            location_id = "discovery"
        elif url.endswith("/locations/measures/current"):
            payload = [] if empty_place else locations
            location_id = "discovery"
        else:
            location_id = url.split("/locations/")[1].split("/")[0]
            payload = payloads.get(location_id) or next(
                x for x in locations if str(x["locationId"]) == location_id
            )
        status = 200
        if location_id in failed:
            if error == "timeout":
                raise requests.Timeout("https://sensitive.invalid/?token=synthetic-secret")
            if error == "network":
                raise requests.ConnectionError("https://sensitive.invalid/?token=synthetic-secret")
            if error == "malformed":
                payload = ["synthetic-secret", {"locationId": "token=synthetic-secret"}]
            else:
                status = {"auth": 401, "rate": 429, "unavailable": 503}[error]
        if empty and isinstance(payload, dict) and "locationId" in payload:
            payload = {k: v for k, v in payload.items() if k.lower() not in importer.PARAM_MAP}

        class Response:
            status_code = status

            def raise_for_status(self):
                if status >= 400:
                    raise requests.HTTPError("synthetic-secret")

            def json(self):
                return payload

        return Response()

    monkeypatch.setattr(importer.requests, "get", get)
    return calls


@pytest.mark.parametrize("failed,expected", [
    ((), "success"),
    (("58376",), "partial_failure"),
    (("58376", "175911"), "partial_failure"),
    (("58376", "175911", "160791"), "failed"),
])
@pytest.mark.parametrize("initialized", [False, True])
def test_public_location_outcomes_and_cli_exit(acquisition, monkeypatch, tmp_path, failed, expected, initialized):
    session, _, events = acquisition
    provider(monkeypatch)
    if initialized:
        importer.run_import()
    events.clear()
    calls = provider(monkeypatch, failed)
    path = tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", ["airgradient", "--summary-json", str(path)])
    if expected == "success":
        importer.main()
    else:
        with pytest.raises(SystemExit) as exited:
            importer.main()
        assert exited.value.code == 1
    result = json.loads(path.read_text())
    assert result["acquisition_outcome"] == expected
    assert result["snapshot_locations_succeeded"] == 3 - len(failed)
    assert result["snapshot_locations_failed"] == len(failed)
    assert len(calls) == 3
    assert len([args for args, _ in events if args[0] in {
        "airgradient_reference_location_error", "airgradient_provider_unavailable"
    }]) == len(failed)
    if failed:
        assert "could not be reached" in result["acquisition_error_message"]
    session.expire_all()
    expected_measurements = 5 if initialized else sum(
        count for location_id, count in {"58376": 2, "175911": 1, "160791": 2}.items()
        if location_id not in failed
    )
    assert session.scalar(select(func.count()).select_from(models.Measurement)) == expected_measurements


@pytest.mark.parametrize("empty", [False, True])
def test_successful_empty_and_duplicate_only_remain_success(acquisition, monkeypatch, empty):
    session, _, _ = acquisition
    provider(monkeypatch, empty=empty)
    first = importer.run_import()
    second = importer.run_import()
    assert first["acquisition_outcome"] == second["acquisition_outcome"] == "success"
    assert second["measurements_inserted"] == second["measurements_updated"] == 0
    if empty:
        assert first["measurements_received"] == second["measurements_received"] == 0
    else:
        assert second["measurements_received"] == second["measurements_skipped"] > 0
    assert "acquisition_error_message" not in second


@pytest.mark.parametrize("error,reason", [
    ("network", "could not be reached"), ("timeout", "timed out"),
    ("unavailable", "HTTP 503"), ("rate", "rate limit"),
    ("auth", "rejected the saved API token"), ("malformed", "unexpected location IDs"),
])
def test_diagnostic_categories_are_sanitized(acquisition, monkeypatch, error, reason):
    _, _, events = acquisition
    provider(monkeypatch, ("58376",), error=error)
    result = importer.run_import()
    assert result["acquisition_outcome"] == "partial_failure"
    assert reason in result["acquisition_error_message"]
    diagnostics = json.dumps([result, events])
    assert "synthetic-secret" not in diagnostics
    assert "sensitive.invalid" not in diagnostics


def test_authentication_discovery_failure_preserves_summary(acquisition, monkeypatch, tmp_path):
    session, source, events = acquisition
    source.api_key = "synthetic-secret"
    source.params = {"import_authenticated_locations": True}
    session.commit()
    provider(monkeypatch, ("discovery",), error="auth")
    path = tmp_path / "summary.json"
    with pytest.raises(importer.AirGradientAuthenticationError):
        importer.run_import(str(path))
    result = json.loads(path.read_text())
    assert result["acquisition_outcome"] == "failed"
    assert result["acquisition_essential_failure"] is True
    assert result["measurements_received"] == 0
    assert "rejected the saved API token" in result["acquisition_error_message"]
    assert "synthetic-secret" not in json.dumps([result, events])


@pytest.mark.parametrize("failed,expected", [((), "success"),
    (("58376", "175911", "160791"), "partial_failure")])
def test_successful_empty_account_discovery(acquisition, monkeypatch, failed, expected):
    session, source, _ = acquisition
    source.api_key = "synthetic-secret"
    source.params = {"import_authenticated_locations": True}
    session.commit()
    provider(monkeypatch, failed, empty_place=True)
    result = importer.run_import()
    assert result["acquisition_outcome"] == expected
    assert result["authenticated_empty_place"] is True
    assert result["authenticated_locations_discovered"] == 0


def test_existing_device_refresh_can_recover_initialization_failure(acquisition, monkeypatch):
    session, source, _ = acquisition
    provider(monkeypatch)
    importer.run_import()
    session.expire_all()
    source.params = {"import_authenticated_locations": False,
                     "reference_locations_initialized_ids": []}
    session.commit()
    calls = []
    payloads = _provider_payloads()

    def get(path, *args, **kwargs):
        location_id = path.split("/locations/")[1].split("/")[0]
        calls.append(location_id)
        if calls == ["58376"]:
            raise importer.AirGradientNetworkError("AirGradient could not be reached")
        return payloads[location_id]

    monkeypatch.setattr(importer, "_api_get", get)
    result = importer.run_import()
    assert calls == ["58376", "175911", "160791", "58376"]
    assert result["snapshot_locations_failed"] == 0
    assert result["snapshot_locations_succeeded"] == 3
    assert result["acquisition_outcome"] == "success"


@pytest.mark.parametrize("failed", [(), ("58376",)])
def test_unexpected_persistence_failure_has_safe_cli_error_and_saved_summary(acquisition, monkeypatch, tmp_path, capsys, failed):
    _, _, events = acquisition
    provider(monkeypatch, failed)

    def fail(*args, **kwargs):
        raise RuntimeError("https://sensitive.invalid?token=synthetic-secret")

    monkeypatch.setattr(importer, "_store_measurements", fail)
    path = tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", ["airgradient", "--summary-json", str(path)])
    with pytest.raises(SystemExit) as exited:
        importer.main()
    assert exited.value.code == 1
    result = json.loads(path.read_text())
    assert result["acquisition_outcome"] == "failed"
    assert result["acquisition_essential_failure"] is True
    assert result["snapshot_locations_failed"] == len(failed)
    diagnostics = json.dumps([result, events, capsys.readouterr().err])
    assert "RuntimeError" in diagnostics
    assert "synthetic-secret" not in diagnostics
    assert "sensitive.invalid" not in diagnostics


@pytest.mark.parametrize("failed,expected", [((), "success"), (("70001",), "partial_failure"),
                                               (("58376", "175911", "160791"), "partial_failure")])
def test_mixed_public_and_authenticated_targets(acquisition, monkeypatch, failed, expected):
    session, source, _ = acquisition
    source.api_key = "synthetic-secret"
    source.params = {"import_authenticated_locations": True}
    session.commit()
    provider(monkeypatch, failed, error="auth")
    result = importer.run_import()
    assert result["acquisition_outcome"] == expected
    assert result["snapshot_locations_succeeded"] == 5 - len(failed)
    assert result["snapshot_locations_failed"] == len(failed)


def test_unexpected_failure_after_a_commit_retains_partial_outcome_and_data(acquisition, monkeypatch, tmp_path):
    session, _, _ = acquisition
    provider(monkeypatch)
    store = importer._store_measurements
    calls = 0

    def fail_second_target(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic-secret")
        return store(*args, **kwargs)

    monkeypatch.setattr(importer, "_store_measurements", fail_second_target)
    path = tmp_path / "summary.json"
    with pytest.raises(RuntimeError):
        importer.run_import(str(path))
    result = json.loads(path.read_text())
    assert result["acquisition_outcome"] == "partial_failure"
    assert result["snapshot_locations_succeeded"] == 1
    assert result["measurements_inserted"] == 2
    assert session.scalar(select(func.count()).select_from(models.Measurement)) == 2
    assert "synthetic-secret" not in json.dumps(result)


@pytest.mark.parametrize("rate_limit", [False, True])
def test_history_metadata_failures_are_not_success(acquisition, monkeypatch, rate_limit):
    provider(monkeypatch)

    def history(*args, **kwargs):
        cls = map_history.MapHistoryRateLimit if rate_limit else map_history.MapHistoryError
        raise cls("AirGradient Map rate limit" if rate_limit else "AirGradient Map could not be reached")

    monkeypatch.setattr(importer, "import_location_history", history)
    result = importer.run_import()
    assert result["acquisition_outcome"] == "partial_failure"
    assert result["snapshot_locations_succeeded"] == 3
    assert result["history_location_failures"] == (1 if rate_limit else 3)
    assert "Public history" in result["acquisition_error_message"]


def test_disabled_authenticated_targets_are_not_failures(acquisition, monkeypatch):
    session, source, _ = acquisition
    session.add(models.Device(name="Synthetic disabled account device", external_id="70001",
                             external_api_id=source.external_api_id,
                             acquisition_path=importer.AIRGRADIENT_AUTHENTICATED_PATH))
    session.commit()
    calls = provider(monkeypatch, ("70001",), error="auth")
    result = importer.run_import()
    assert result["acquisition_outcome"] == "success"
    assert len(calls) == 3


def test_history_timeout_is_distinct_and_sanitized(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout('https://sensitive.invalid?token=synthetic-secret')

    monkeypatch.setattr(map_history.requests, 'get', timeout)
    with pytest.raises(map_history.MapHistoryError, match='Map request timed out') as error:
        map_history.public_get('locations/14699912')
    assert 'synthetic-secret' not in str(error.value)


@pytest.mark.parametrize("empty", [False, True])
def test_real_history_partial_checkpoint_recovery_and_duplicate_safety(acquisition, monkeypatch, empty):
    from sources.airgradient.history_ingestion import import_location_history

    session, _, events = acquisition
    # Keep the provider's closed bucket fixed across the first attempt and
    # recovery. Crossing a 15-minute boundary legitimately adds a second initial
    # chunk for the failed stream, making the exact interval count time-dependent.
    fixed_until = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(map_history, "closed_until", lambda _now: fixed_until)
    provider(monkeypatch)
    payloads = _provider_payloads()
    failing = True

    def public_get(path, params=None):
        map_id = int(path.split("/")[1])
        location_id, mapping = next((key, value) for key, value in map_history.REFERENCE_MAPPINGS.items()
                                    if value.map_id == map_id)
        payload = payloads[location_id]
        # Match the independent approved mapping used by identity validation.
        if params is None:
            return dict(locationId=map_id, locationName=mapping.name, latitude=mapping.latitude,
                        longitude=mapping.longitude, provider="AirGradient", dataSource="AirGradient",
                        licenses=["CC BY-SA 4.0"], ownerName=payload.get("publicContributorName"),
                        url=payload.get("publicPlaceUrl"))
        if failing and map_id == 14699912 and params["measure"] == "pm10":
            raise map_history.MapHistoryError("AirGradient Map could not be reached")
        rows = [] if empty else [{"timebucket": params["start"], "value": 4.25}]
        return {"total": len(rows), "data": rows}

    # Current response names must match their approved Map counterpart.
    def current(path, *args, **kwargs):
        location_id = path.split("/locations/")[1].split("/")[0]
        return {**payloads[location_id], "locationName": map_history.REFERENCE_MAPPINGS[location_id].name}

    monkeypatch.setattr(importer, "_api_get", current)
    monkeypatch.setattr(importer, "import_location_history", import_location_history)
    monkeypatch.setattr(map_history, "public_get", public_get)
    first = importer.run_import()
    assert first["acquisition_outcome"] == "partial_failure"
    assert first["history_intervals_examined"] == 14
    assert first["history_intervals_failed"] == 1
    session.expire_all()
    sensors = {s.external_sensor_id: s for s in session.scalars(select(models.Sensor))}
    failed_sensor = sensors["map:14699912:pm10:15m"]
    assert failed_sensor.acquisition_examined_until is None
    checkpoint = sensors["map:14699912:pm25:15m"].acquisition_examined_until
    assert checkpoint is not None
    assert any(args[0] == "airgradient_history_error" for args, _ in events)
    failing = False
    recovered = importer.run_import()
    assert recovered["acquisition_outcome"] == "success"
    assert recovered["history_intervals_examined"] == 15
    session.expire_all()
    assert session.get(models.Sensor, failed_sensor.sensor_id).acquisition_examined_until >= checkpoint
    importer.run_import()
    duplicates = session.execute(select(models.Measurement.sensor_id, models.Measurement.observed_at)
                                 .group_by(models.Measurement.sensor_id, models.Measurement.observed_at)
                                 .having(func.count() > 1)).all()
    assert duplicates == []
    if empty:
        assert recovered["measurements_inserted"] == 0
