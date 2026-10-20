"""CSV → policy → persisted measurements/QC → Events, on both database engines."""

from datetime import UTC, datetime, timedelta, timezone
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from api.main import app
from api.auth_deps import CurrentUser, get_current_user
from db import get_session
import models
from qaqc.policy import resolve_effective_qc_policy
from services import csv_measurement_import as csv_import
from services.auth import scopes_from_roles
from services.aqi_engine import calculate_latest_us_epa_aqi


@pytest.fixture(scope="module", params=["sqlite", "postgresql"])
def csv_session_factory(request, tmp_path_factory):
    if request.param == "postgresql":
        if not os.environ.get("COMPASSAQ_POSTGRES_TEST_URL"):
            pytest.skip(
                "Set COMPASSAQ_POSTGRES_TEST_URL for PostgreSQL persistence acceptance"
            )
        from postgresql_test_support import temporary_postgres_database, upgrade

        with temporary_postgres_database("csv_workflow") as (url, engine):
            upgrade(url)
            yield sessionmaker(bind=engine, autoflush=False)
        return
    engine = create_engine(
        f"sqlite:///{tmp_path_factory.mktemp('csv') / 'workflow.sqlite3'}",
        connect_args={"check_same_thread": False},
    )

    # SQLite's legacy driver does not BEGIN for SELECT/SAVEPOINT, so its first
    # released savepoint would commit independently of our outer transaction.
    # Match PostgreSQL transaction behavior for the atomic-audit regression.
    @event.listens_for(engine, "connect")
    def configure_sqlite_transaction(connection, _):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin_sqlite_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    models.Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


@pytest.fixture()
def csv_context(csv_session_factory, monkeypatch):
    monkeypatch.setattr(csv_import, "SessionLocal", csv_session_factory)
    with csv_session_factory() as session:
        unit = session.scalar(select(models.Unit).where(models.Unit.code == "ug_m3"))
        if unit is None:
            unit = models.Unit(
                code="ug_m3", symbol="µg/m³", name="Micrograms per cubic meter"
            )
            session.add(unit)
            session.flush()
        parameter = session.scalar(
            select(models.Parameter).where(models.Parameter.code == "pm25")
        )
        if parameter is None:
            parameter = models.Parameter(
                code="pm25", display_name="PM2.5", default_unit_id=unit.unit_id
            )
            session.add(parameter)
            session.flush()
        suffix = uuid.uuid4().hex
        source = models.ExternalAPI(name=f"Synthetic CSV source {suffix}", params={})
        session.add(source)
        session.flush()
        device = models.Device(
            name=f"Synthetic CSV device {suffix}",
            friendly_name=f"Synthetic friendly {suffix}",
            external_id=f"external-device-{suffix}",
            external_api_id=source.external_api_id,
            timezone="UTC",
        )
        session.add(device)
        session.flush()
        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            external_sensor_id=f"external-sensor-{suffix}",
        )
        session.add(sensor)
        user = models.User(
            user_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            email=f"synthetic-{suffix}@example.test",
            first_name="Synthetic CSV",
            last_name="administrator",
            password_hash="unused",
            is_active=True,
        )
        session.add(user)
        session.commit()
        context = {
            "factory": csv_session_factory,
            "sensor_id": sensor.sensor_id,
            "device_id": device.device_id,
            "unit_id": unit.unit_id,
            "user_id": user.user_id,
            "email": user.email,
            "suffix": suffix,
        }
        current_user = CurrentUser(
            user_id=user.user_id,
            org_id=user.org_id,
            email=user.email,
            roles=["admin"],
            scopes=scopes_from_roles(["admin"]),
            token_jti=uuid.uuid4(),
            token_exp=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def session_dependency():
        with csv_session_factory() as session:
            yield session

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with TestClient(app) as client:
            context["client"] = client
            yield context
    finally:
        app.dependency_overrides = previous


def upload(context, rows):
    text = "internalsensorid,datetime,value\n" + "".join(
        f"{context['sensor_id']},{timestamp.isoformat()},{value}\n"
        for timestamp, value in rows
    )
    response = context["client"].post(
        "/admin/imports/upload-csv", files={"file": ("synthetic.csv", text, "text/csv")}
    )
    assert response.status_code == 200, response.text
    return response.json()


def stored(context):
    with context["factory"]() as session:
        return list(
            session.scalars(
                select(models.Measurement)
                .where(models.Measurement.sensor_id == context["sensor_id"])
                .order_by(models.Measurement.observed_at)
            )
        )


@pytest.mark.parametrize(
    "case,header,row,expected_detail,expected_value,expected_failed",
    [
        pytest.param(
            "original malformed header",
            "sensor_id,value,observed_at",
            "{sensor_id},12.5,{timestamp}",
            "missing required CSV columns: internalsensorid, datetime",
            None,
            0,
            id="original-malformed-header",
        ),
        pytest.param(
            "canonical header",
            "internalsensorid,datetime,value",
            "{sensor_id},{timestamp},12.5",
            None,
            12.5,
            0,
            id="canonical-header",
        ),
        pytest.param(
            "missing required column",
            "internalsensorid,datetime",
            "{sensor_id},{timestamp}",
            "missing required CSV columns: value",
            None,
            0,
            id="missing-required-column",
        ),
        pytest.param(
            "misspelled required column",
            "internalsensorid,datetim,value",
            "{sensor_id},{timestamp},12.5",
            "missing required CSV columns: datetime",
            None,
            0,
            id="misspelled-required-column",
        ),
        pytest.param(
            "empty file",
            None,
            None,
            "Uploaded file is empty",
            None,
            0,
            id="empty-file",
        ),
        pytest.param(
            "empty header cells",
            ",,",
            "{sensor_id},{timestamp},12.5",
            "missing required CSV columns: internalsensorid, datetime, value",
            None,
            0,
            id="empty-header-cells",
        ),
        pytest.param(
            "duplicate value header",
            "internalsensorid,datetime,value,value",
            "{sensor_id},{timestamp},12.5,13.75",
            None,
            13.75,
            0,
            id="duplicate-header-current-last-value-behavior",
        ),
        pytest.param(
            "permitted extra column",
            "internalsensorid,datetime,value,notes",
            "{sensor_id},{timestamp},12.5,ignored",
            None,
            12.5,
            0,
            id="extra-column",
        ),
        pytest.param(
            "reordered supported columns",
            "value,internalsensorid,datetime",
            "12.5,{sensor_id},{timestamp}",
            None,
            12.5,
            0,
            id="reordered-columns",
        ),
        pytest.param(
            "trimmed and case-normalized header names",
            " InternalSensorId , DateTime , Value ",
            "{sensor_id},{timestamp},12.5",
            None,
            12.5,
            0,
            id="header-whitespace-and-case",
        ),
        pytest.param(
            "UTF-8 BOM header",
            "\ufeffinternalsensorid,datetime,value",
            "{sensor_id},{timestamp},12.5",
            None,
            12.5,
            0,
            id="utf8-bom",
        ),
        pytest.param(
            "incorrect delimiter",
            "internalsensorid;datetime;value",
            "{sensor_id};{timestamp};12.5",
            "Uploaded file does not appear to be CSV",
            None,
            0,
            id="incorrect-delimiter",
        ),
        pytest.param(
            "header-only file",
            "internalsensorid,datetime,value",
            None,
            None,
            None,
            0,
            id="header-only",
        ),
        pytest.param(
            "row-value error under a valid header",
            "internalsensorid,datetime,value",
            "{sensor_id},{timestamp},not-a-number",
            None,
            None,
            1,
            id="row-value-error-is-not-header-error",
        ),
    ],
)
def test_existing_csv_header_contract(
    csv_context,
    case,
    header,
    row,
    expected_detail,
    expected_value,
    expected_failed,
):
    timestamp_text = "2026-01-15T00:00:00Z"
    if header is None:
        csv_text = ""
    elif row is None:
        csv_text = f"{header}\n"
    else:
        formatted_row = row.format(
            sensor_id=csv_context["sensor_id"], timestamp=timestamp_text
        )
        csv_text = f"{header}\n{formatted_row}\n"

    response = csv_context["client"].post(
        "/admin/imports/upload-csv",
        files={"file": ("header-contract.csv", csv_text, "text/csv")},
    )

    if expected_detail is not None:
        assert response.status_code == 400, f"{case}: {response.text}"
        assert response.json()["detail"] == expected_detail
        assert stored(csv_context) == []
        return

    assert response.status_code == 200, f"{case}: {response.text}"
    result = response.json()
    assert result["failed_records"] == expected_failed
    if expected_value is None and expected_failed == 0:
        assert result["total_records"] == 0
        assert result["inserted_records"] == 0
        assert result["success"] is True
        return

    assert result["total_records"] == 1
    assert result["inserted_records"] == int(expected_value is not None)
    measurements = stored(csv_context)

    if expected_value is None:
        assert result["success"] is False
        assert result["row_errors"][0]["code"] == "value_invalid"
        assert measurements == []
        return

    assert result["success"] is True
    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement.sensor_id == csv_context["sensor_id"]
    observed_at = measurement.observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    assert observed_at == datetime(2026, 1, 15, tzinfo=UTC)
    assert measurement.value == expected_value


@pytest.mark.parametrize(
    "sensor_policy,device_policy,action",
    [
        ("deny", "allow", "skip"),
        ("allow", "deny", "update"),
        ("inherit", "allow", "update"),
        ("inherit", "deny", "skip"),
        ("inherit", "inherit", "skip"),
    ],
)
def test_duplicate_update_policy_and_qc(
    csv_context, sensor_policy, device_policy, action
):
    timestamp = datetime(2026, 1, 15, tzinfo=timezone.utc)
    first = upload(csv_context, [(timestamp, 12)])
    with csv_context["factory"]() as session:
        session.get(models.Sensor, csv_context["sensor_id"]).allow_updates = (
            models.UpdatePolicy(sensor_policy)
        )
        session.get(models.Device, csv_context["device_id"]).allow_updates = (
            models.UpdatePolicy(device_policy)
        )
        session.commit()
    result = upload(
        csv_context, [(timestamp, 40000), (timestamp + timedelta(minutes=1), 8)]
    )
    assert result["success"] is True
    assert result["total_records"] == 2
    assert result["inserted_records"] == 1
    assert result["updated_records"] == int(action == "update")
    assert result["skipped_records"] == int(action == "skip")
    assert result["failed_records"] == 0
    assert stored(csv_context)[0].value == (40000 if action == "update" else 12)
    assert stored(csv_context)[0].is_valid is True
    assert stored(csv_context)[0].qc_flags == (
        ["max_value"] if action == "update" else None
    )
    assert result["qc"]["evaluated"] == (2 if action == "update" else 1)
    assert result["qc"]["flagged"] == int(action == "update")
    assert first["inserted_records"] == 1


@pytest.mark.parametrize(
    "action,valid", [("flag_for_review", True), ("mark_invalid", False)]
)
def test_max_qc_persists_and_is_discoverable(csv_context, action, valid):
    with csv_context["factory"]() as session:
        session.add(
            models.QCRule(
                check_code="max_value",
                sensor_id=csv_context["sensor_id"],
                policy_unit_id=csv_context["unit_id"],
                failure_action_override=action,
            )
        )
        session.commit()
        policy = resolve_effective_qc_policy(
            session, csv_context["sensor_id"], "max_value"
        )
        assert policy.evaluation_settings == {"max": 10000.0}
    result = upload(csv_context, [(datetime(2026, 1, 15, tzinfo=timezone.utc), 35000)])
    measurement = stored(csv_context)[0]
    assert measurement.value == 35000
    assert measurement.is_valid is valid
    assert measurement.qc_flags == ["max_value"]
    assert result["qc"]["flagged"] == 1
    response = csv_context["client"].get(
        "/admin/events/qc-failures",
        params={"search": str(csv_context["sensor_id"]), "outcome": action},
    )
    assert response.status_code == 200
    match = next(
        row
        for row in response.json()["items"]
        if row["measurement_id"] == measurement.measurement_id
    )
    assert match["evaluation_status"] == "failed"
    assert match["measurement_is_valid"] is valid
    assert match["params_snapshot"] == {"max": 10000.0}


def test_replace_reruns_qc_and_clears_old_failure(csv_context):
    with csv_context["factory"]() as session:
        session.get(models.Sensor, csv_context["sensor_id"]).allow_updates = (
            models.UpdatePolicy.ALLOW
        )
        session.add(
            models.QCRule(
                check_code="max_value",
                sensor_id=csv_context["sensor_id"],
                policy_unit_id=csv_context["unit_id"],
                failure_action_override="mark_invalid",
            )
        )
        session.commit()
    timestamp = datetime(2026, 1, 15, tzinfo=timezone.utc)
    upload(csv_context, [(timestamp, 40000)])
    original_id = stored(csv_context)[0].measurement_id
    assert stored(csv_context)[0].is_valid is False
    result = upload(csv_context, [(timestamp, 20)])
    measurement = stored(csv_context)[0]
    assert result["updated_records"] == 1
    assert measurement.measurement_id == original_id
    assert measurement.value == 20
    assert measurement.is_valid is True
    assert measurement.qc_flags is None
    with csv_context["factory"]() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(models.MeasurementQCResult)
                .where(models.MeasurementQCResult.measurement_id == original_id)
            )
            == 0
        )


def test_future_tolerance_historical_backfill_and_line_numbers(
    csv_context, monkeypatch
):
    now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(csv_import, "datetime", FixedDatetime)
    result = upload(
        csv_context,
        [
            (now, 12),
            (now + timedelta(minutes=5, seconds=1), 15),
            (now + timedelta(minutes=5), 14),
            (now - timedelta(days=3650), 10),
        ],
    )
    assert result["inserted_records"] == 3
    assert result["failed_records"] == 1
    assert result["row_errors"][0]["line"] == 3
    assert result["row_errors"][0]["code"] == "timestamp_future"
    assert result["errors"][0].startswith("Line 3: timestamp is later")
    assert len(stored(csv_context)) == 3


@pytest.mark.parametrize(
    "value,code",
    [
        ("NaN", "value_invalid"),
        ("Infinity", "value_invalid"),
        ("12,13", "extra_columns"),
    ],
)
def test_reject_invalid_values_without_poisoning_next_row(csv_context, value, code):
    timestamp = datetime(2026, 1, 15, tzinfo=timezone.utc)
    result = upload(
        csv_context, [(timestamp, value), (timestamp + timedelta(minutes=1), 12)]
    )
    assert result["inserted_records"] == 1
    assert result["failed_records"] == 1
    assert result["row_errors"][0]["code"] == code


@pytest.mark.parametrize(
    "kind,outcome,severity",
    [
        ("success", "success", "info"),
        ("partial", "partial", "warning"),
        ("failed", "failed", "error"),
        ("bad_file", "failed", "error"),
    ],
)
def test_one_actor_attributed_event_per_upload(csv_context, kind, outcome, severity):
    with csv_context["factory"]() as session:
        before = session.scalar(
            select(func.count())
            .select_from(models.Event)
            .where(models.Event.event_type == "csv.upload")
        )
    if kind == "bad_file":
        response = csv_context["client"].post(
            "/admin/imports/upload-csv",
            files={"file": ("synthetic.csv", "wrong,header\n1,2\n", "text/csv")},
        )
        assert response.status_code == 400
    else:
        now = datetime.now(timezone.utc)
        rows = (
            [(now - timedelta(days=1), 12)]
            if kind == "success"
            else [(now + timedelta(days=1), 12)]
        )
        if kind == "partial":
            rows.append((now - timedelta(days=1), 14))
        result = upload(csv_context, rows)
    with csv_context["factory"]() as session:
        events = list(
            session.scalars(
                select(models.Event)
                .where(models.Event.event_type == "csv.upload")
                .order_by(models.Event.event_id)
            )
        )
        assert len(events) == before + 1
        event = events[-1]
        assert event.source == "CSV upload"
        assert event.actor_user_id == csv_context["user_id"]
        assert event.actor_email == csv_context["email"]
        assert event.actor_display_name == "Synthetic CSV administrator"
        assert event.params["outcome"] == outcome
        assert event.severity == severity
        assert event.params["started_at"] <= event.params["completed_at"]
        if kind != "bad_file":
            for key in (
                "inserted_records",
                "updated_records",
                "skipped_records",
                "failed_records",
            ):
                assert event.params[key] == result[key]
        else:
            assert event.params["error_code"] == "csv_file_invalid"
    response = csv_context["client"].get(
        "/admin/events", params={"event_type": "csv.upload"}
    )
    assert response.status_code == 200
    assert any(item["event_id"] == event.event_id for item in response.json())


def test_measurements_and_completed_audit_commit_together(csv_context, monkeypatch):
    original = csv_import._update_csv_event

    def fail_completion(session, event_id, result, error_code=None):
        if result is not None:
            raise RuntimeError("Synthetic completion write failure")
        original(session, event_id, result, error_code)

    monkeypatch.setattr(csv_import, "_update_csv_event", fail_completion)
    text = f"internalsensorid,datetime,value\n{csv_context['sensor_id']},2026-01-15T00:00:00Z,12\n"
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/admin/imports/upload-csv",
            files={"file": ("synthetic.csv", text, "text/csv")},
        )
    assert response.status_code == 500
    assert stored(csv_context) == []
    with csv_context["factory"]() as session:
        event = session.scalar(
            select(models.Event)
            .where(models.Event.actor_user_id == csv_context["user_id"])
            .order_by(models.Event.event_id.desc())
        )
        assert event.params["outcome"] == "failed"
        assert event.params["error_code"] == "csv_import_failed"
        assert event.params["inserted_records"] == 0


def test_invalid_internal_ids_do_not_poison_postgresql_transaction(csv_context):
    text = (
        "internalsensorid,datetime,value\n"
        "99999999999999999999999999,2026-01-15T00:00:00Z,12\n"
        f"{csv_context['sensor_id']},2026-01-15T00:00:00Z,14\n"
    )
    response = csv_context["client"].post(
        "/admin/imports/upload-csv", files={"file": ("synthetic.csv", text, "text/csv")}
    )
    assert response.status_code == 200
    assert response.json()["row_errors"][0]["code"] == "sensor_invalid"
    assert response.json()["inserted_records"] == 1
    assert stored(csv_context)[0].value == 14


@pytest.mark.parametrize(
    "enabled,enough_history", [(False, True), (True, False), (True, True)]
)
def test_baseline_drift_csv_history_execution(csv_context, enabled, enough_history):
    with csv_context["factory"]() as session:
        session.add(
            models.QCRule(
                check_code="baseline_drift",
                sensor_id=csv_context["sensor_id"],
                policy_unit_id=csv_context["unit_id"],
                enabled_override=enabled,
                settings={
                    "lookback_hours": 192,
                    "min_samples": 8,
                    "baseline_quantile": 0.1,
                    "max_drift_per_day": 5,
                    "direction": "both",
                },
            )
        )
        session.commit()
    candidate_time = datetime(2026, 1, 15, tzinfo=timezone.utc)
    rows = (
        [(candidate_time - timedelta(days=8 - i), 20 * i) for i in range(8)]
        if enough_history
        else []
    )
    rows.append((candidate_time, 180))
    result = upload(csv_context, rows)
    assert result["failed_records"] == 0
    with csv_context["factory"]() as session:
        measurement = session.scalar(
            select(models.Measurement).where(
                models.Measurement.sensor_id == csv_context["sensor_id"],
                models.Measurement.observed_at == candidate_time,
            )
        )
        results = list(
            session.scalars(
                select(models.MeasurementQCResult)
                .join(models.Measurement)
                .where(
                    models.Measurement.sensor_id == csv_context["sensor_id"],
                    models.MeasurementQCResult.check_code == "baseline_drift",
                )
            )
        )
        assert measurement.is_valid is True
        if not enabled:
            assert results == []
            assert measurement.qc_flags is None
        elif not enough_history:
            assert len(results) == 1
            assert results[0].evaluation_status == "indeterminate"
            assert results[0].reason_code == "insufficient_history"
            assert measurement.qc_flags is None
        else:
            final = next(
                row
                for row in results
                if row.measurement_id == measurement.measurement_id
            )
            assert final.evaluation_status == "failed"
            assert final.details["samples"] == 8
            assert final.details["drift_per_day"] == pytest.approx(10)
            assert measurement.qc_flags == ["baseline_drift"]
            assert (
                len(
                    [
                        row
                        for row in results
                        if row.reason_code == "insufficient_history"
                    ]
                )
                == 1
            )


@pytest.mark.parametrize(
    "search_kind",
    [
        "device_id",
        "sensor_id",
        "external_device",
        "external_sensor",
        "name",
        "friendly",
        "parameter",
        "empty",
        "no_match",
    ],
)
def test_destination_lookup_before_pagination(csv_context, search_kind):
    suffix = csv_context["suffix"]
    searches = {
        "device_id": str(csv_context["device_id"]),
        "sensor_id": str(csv_context["sensor_id"]),
        "external_device": f"external-device-{suffix}",
        "external_sensor": f"external-sensor-{suffix}",
        "name": f"Synthetic CSV device {suffix}",
        "friendly": f"Synthetic friendly {suffix}",
        "parameter": "PM2.5",
        "empty": "",
        "no_match": f"no-match-{suffix}",
    }
    response = csv_context["client"].get(
        "/admin/devices",
        params={"search": searches[search_kind], "page": 0, "page_size": 100},
    )
    assert response.status_code == 200, response.text
    if search_kind == "no_match":
        assert response.json() == []
    else:
        assert any(
            row["device_id"] == csv_context["device_id"] for row in response.json()
        )


def test_search_finds_destination_beyond_first_page(csv_context):
    with csv_context["factory"]() as session:
        destination = session.get(models.Device, csv_context["device_id"])
        destination.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        session.add_all(
            [
                models.Device(
                    name=f"Synthetic pagination {csv_context['suffix']} {i}",
                    external_api_id=destination.external_api_id,
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
                for i in range(25)
            ]
        )
        session.commit()
    client = csv_context["client"]
    first_page = client.get(
        "/admin/devices", params={"page": 0, "page_size": 20}
    ).json()
    assert csv_context["device_id"] not in [row["device_id"] for row in first_page]
    matches = client.get(
        "/admin/devices",
        params={
            "search": f"external-device-{csv_context['suffix']}",
            "page": 0,
            "page_size": 20,
        },
    ).json()
    assert [row["device_id"] for row in matches] == [csv_context["device_id"]]


@pytest.mark.parametrize("complete", [True, False])
def test_csv_can_feed_aqi_only_with_qualifying_metadata_and_coverage(
    csv_context, complete
):
    with csv_context["factory"]() as session:
        period = session.scalar(
            select(models.AggregationPeriod).where(
                models.AggregationPeriod.code == "2m"
            )
        )
        if period is None:
            period = models.AggregationPeriod(
                code="2m", display_name="2 minutes", duration_minutes=2
            )
            session.add(period)
            session.flush()
        sensor = session.get(models.Sensor, csv_context["sensor_id"])
        sensor.aggregation_period_id = period.aggregation_period_id
        sensor.expected_frequency_seconds = 120
        sensor.measurement_duration_seconds = 120
        sensor.source_aggregation_duration_seconds = 120
        sensor.measurement_timestamp_semantics = "interval_start"
        sensor.measurement_metadata_status = "provider_documented"
        sensor.measurement_metadata_managed_by = "synthetic_test_fixture"
        session.commit()
    reference = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    samples_per_hour = 30 if complete else 5
    result = upload(
        csv_context,
        [
            (reference - timedelta(hours=hour) + timedelta(minutes=2 * i), 20)
            for hour in (2, 1)
            for i in range(samples_per_hour)
        ],
    )
    assert result["failed_records"] == 0
    with csv_context["factory"]() as session:
        calculation = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            reference_time_utc=reference,
            current_time_utc=reference,
            device_id=csv_context["device_id"],
        )[0]
        assert (calculation.calculation.numeric_value is not None) is complete
        if not complete:
            assert calculation.calculation.exclusion_reason is not None
        sensor = session.get(models.Sensor, csv_context["sensor_id"])
        assert sensor.measurement_timestamp_semantics == "interval_start"
        assert sensor.expected_frequency_seconds == 120
