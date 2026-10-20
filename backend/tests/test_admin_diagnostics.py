from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from api.routes.admin import diagnostics
from db import SessionLocal
from models import Device, ExternalAPI, Measurement, Parameter, Sensor, Unit, User
from services import auth


NOW = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        assert tz == timezone.utc
        return NOW


class QueryRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class DiagnosticsSession:
    def __init__(self, latest, parameter_rows):
        self.scalars = iter((2, 3, 4, latest, 5, 1))
        self.row_sets = iter((parameter_rows, [("range", 2)], []))

    def scalar(self, query):
        return next(self.scalars)

    def execute(self, query):
        return QueryRows(next(self.row_sets))


class CalculationFailure:
    def isoformat(self):
        return "invalid-calculation"

    @property
    def tzinfo(self):
        raise TypeError("cannot read timezone")


@pytest.mark.parametrize(
    ("observed_at", "expected_lag"),
    [
        (None, None),
        (datetime(2024, 1, 1, 11, 58, 59), 1),
        (datetime(2024, 1, 1, 11, 58, tzinfo=timezone.utc), 2),
        (datetime(2024, 1, 1, 4, tzinfo=timezone(timedelta(hours=-7))), 60),
        (datetime(2024, 1, 1, 12, 1, tzinfo=timezone.utc), 0),
        (NOW, 0),
        (CalculationFailure(), None),
        (datetime(2023, 1, 1, 12, tzinfo=timezone.utc), 525600),
    ],
)
def test_overall_and_parameter_lags_have_the_same_existing_contract(
    monkeypatch, observed_at, expected_lag
):
    monkeypatch.setattr(diagnostics, "datetime", FixedDateTime)
    session = DiagnosticsSession(observed_at, [("pm25", observed_at)])

    payload = diagnostics.diagnostics_summary(session=session)
    expected_iso = observed_at.isoformat() if observed_at else None

    assert payload["ingest"] == {
        "latest_observed_at": expected_iso,
        "lag_minutes": expected_lag,
        "per_parameter": [
            {"code": "pm25", "latest_observed_at": expected_iso, "lag_minutes": expected_lag}
        ],
    }


def test_multiple_parameter_times_and_no_parameter_observations(monkeypatch):
    monkeypatch.setattr(diagnostics, "datetime", FixedDateTime)
    older = datetime(2024, 1, 1, 10, tzinfo=timezone.utc)
    newer = datetime(2024, 1, 1, 11, 30, tzinfo=timezone.utc)

    payload = diagnostics.diagnostics_summary(
        session=DiagnosticsSession(newer, [("pm10", older), ("pm25", newer)])
    )
    assert payload["ingest"] == {
        "latest_observed_at": newer.isoformat(),
        "lag_minutes": 30,
        "per_parameter": [
            {"code": "pm10", "latest_observed_at": older.isoformat(), "lag_minutes": 120},
            {"code": "pm25", "latest_observed_at": newer.isoformat(), "lag_minutes": 30},
        ],
    }

    empty = diagnostics.diagnostics_summary(session=DiagnosticsSession(None, []))
    assert empty["ingest"] == {
        "latest_observed_at": None,
        "lag_minutes": None,
        "per_parameter": [],
    }


def test_invalid_timestamp_serialization_still_returns_http_500(monkeypatch):
    monkeypatch.setattr(diagnostics, "datetime", FixedDateTime)
    with pytest.raises(HTTPException) as error:
        diagnostics.diagnostics_summary(session=DiagnosticsSession(object(), []))
    assert error.value.status_code == 500


def test_diagnostics_api_response_keys_types_and_legacy_fields(admin_auth_headers):
    client = TestClient(app)

    summary_response = client.get("/admin/diagnostics/summary", headers=admin_auth_headers)
    assert summary_response.status_code == 200, summary_response.text
    summary = summary_response.json()
    assert set(summary) == {"counts", "ingest", "qc", "jobs"}
    assert set(summary["counts"]) == {"devices", "sensors", "measurements"}
    assert all(type(count) is int for count in summary["counts"].values())
    assert set(summary["ingest"]) == {"latest_observed_at", "lag_minutes", "per_parameter"}
    assert summary["ingest"]["latest_observed_at"] is None or isinstance(
        summary["ingest"]["latest_observed_at"], str
    )
    assert isinstance(summary["ingest"]["per_parameter"], list)
    assert summary["ingest"]["lag_minutes"] is None or type(summary["ingest"]["lag_minutes"]) is int
    for parameter in summary["ingest"]["per_parameter"]:
        assert set(parameter) == {"code", "latest_observed_at", "lag_minutes"}
        assert isinstance(parameter["code"], str)
        assert parameter["latest_observed_at"] is None or isinstance(parameter["latest_observed_at"], str)
        assert parameter["lag_minutes"] is None or type(parameter["lag_minutes"]) is int
    assert set(summary["qc"]) == {"last_24h"}
    assert set(summary["qc"]["last_24h"]) == {
        "valid", "invalid", "total", "pct_valid", "failures_by_check"
    }
    qc = summary["qc"]["last_24h"]
    assert all(type(qc[key]) is int for key in ("valid", "invalid", "total"))
    assert qc["pct_valid"] is None or type(qc["pct_valid"]) is float
    assert isinstance(qc["failures_by_check"], dict)
    assert all(
        isinstance(key, str) and type(count) is int
        for key, count in qc["failures_by_check"].items()
    )
    assert set(summary["jobs"]) == {"last_runs"}
    assert isinstance(summary["jobs"]["last_runs"], list)
    for run in summary["jobs"]["last_runs"]:
        assert set(run) == {"task", "status", "started_at", "finished_at"}
        assert isinstance(run["task"], str)
        assert isinstance(run["status"], str)
        assert run["started_at"] is None or isinstance(run["started_at"], str)
        assert run["finished_at"] is None or isinstance(run["finished_at"], str)

    legacy_response = client.get(
        "/admin/diagnostics/location_migration", headers=admin_auth_headers
    )
    assert legacy_response.status_code == 200, legacy_response.text
    legacy = legacy_response.json()
    assert set(legacy) == {"devices", "sensors", "measurements"}
    assert set(legacy["devices"]) == {
        "total", "with_external_id", "with_latitude", "with_longitude",
        "with_coords", "missing_coords", "with_location_id", "location_link_removed",
    }
    assert all(type(value) is int for key, value in legacy["devices"].items() if key != "location_link_removed")
    assert type(legacy["devices"]["location_link_removed"]) is bool
    assert set(legacy["sensors"]) == {"total"}
    assert set(legacy["measurements"]) == {"total"}
    assert type(legacy["sensors"]["total"]) is int
    assert type(legacy["measurements"]["total"]) is int


def test_diagnostics_api_reads_distinct_parameter_observations(admin_auth_headers):
    suffix = uuid4().hex[:8]
    codes = (f"p3a{suffix}", f"p3b{suffix}")
    observed_times = (
        datetime(2023, 12, 31, 10),
        datetime(2023, 12, 31, 11),
    )
    with SessionLocal() as session:
        unit_id = session.scalar(select(Unit.unit_id).where(Unit.code == "ug_m3"))
        source = ExternalAPI(name=f"P3 diagnostics {suffix}", params={})
        session.add(source)
        session.flush()
        device = Device(name=f"P3 diagnostics {suffix}", external_api_id=source.external_api_id)
        session.add(device)
        session.flush()
        parameters = [
            Parameter(code=code, display_name=code, default_unit_id=unit_id)
            for code in codes
        ]
        session.add_all(parameters)
        session.flush()
        sensors = [
            Sensor(device_id=device.device_id, parameter_id=parameter.parameter_id, unit_id=unit_id)
            for parameter in parameters
        ]
        session.add_all(sensors)
        session.flush()
        measurements = [
            Measurement(sensor_id=sensor.sensor_id, value=1.0, observed_at=observed_at)
            for sensor, observed_at in zip(sensors, observed_times)
        ]
        session.add_all(measurements)
        session.commit()
        ids = (
            [measurement.measurement_id for measurement in measurements],
            [sensor.sensor_id for sensor in sensors],
            [parameter.parameter_id for parameter in parameters],
            device.device_id,
            source.external_api_id,
        )

    try:
        response = TestClient(app).get(
            "/admin/diagnostics/summary", headers=admin_auth_headers
        )
        assert response.status_code == 200, response.text
        by_code = {row["code"]: row for row in response.json()["ingest"]["per_parameter"]}
        for code, observed_at in zip(codes, observed_times):
            assert by_code[code]["latest_observed_at"] == observed_at.isoformat()
            assert type(by_code[code]["lag_minutes"]) is int
            assert by_code[code]["lag_minutes"] >= 0
    finally:
        with SessionLocal() as session:
            measurement_ids, sensor_ids, parameter_ids, device_id, source_id = ids
            for model, row_ids in (
                (Measurement, measurement_ids), (Sensor, sensor_ids),
                (Parameter, parameter_ids), (Device, [device_id]),
                (ExternalAPI, [source_id]),
            ):
                for row_id in row_ids:
                    session.delete(session.get(model, row_id))
            session.commit()


@pytest.mark.parametrize("path", ["/admin/diagnostics/summary", "/admin/diagnostics/location_migration"])
def test_diagnostics_require_admin_scope(path, admin_auth_headers):
    client = TestClient(app)
    assert client.get(path, headers=admin_auth_headers).status_code == 200
    assert client.get(path).status_code == 401

    with SessionLocal() as session:
        viewer = User(
            user_id=uuid4(),
            org_id=uuid4(),
            email=f"diagnostics-viewer-{uuid4()}@example.com",
            password_hash=auth.hash_password("strong-password-123"),
            is_active=True,
        )
        session.add(viewer)
        session.commit()
        settings = auth.get_auth_settings()
        viewer_token, _ = auth.create_access_token(
            settings=settings,
            user_id=viewer.user_id,
            org_id=viewer.org_id,
            roles=["viewer"],
            scopes=auth.scopes_from_roles(["viewer"]),
        )
    response = client.get(path, headers={"Authorization": f"Bearer {viewer_token}"})
    assert response.status_code == 403, response.text
