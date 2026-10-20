from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import models
from services.administrator_summary_collector import (
    build_administrator_summary,
    build_event_summary_statement,
    build_import_summary_statement,
    build_qc_summary_statement,
    collect_qc_activity,
    derive_attention_items,
)
from services.administrator_summary_domain import (
    AdministratorSummaryCadence,
    AdministratorSummaryStatus,
    QcDigestOutcome,
    calculate_completed_reporting_window,
)
from services.administrator_summary_renderer import render_administrator_summary_email


UTC = timezone.utc
PERIOD_REFERENCE = datetime(2026, 8, 22, 12, tzinfo=UTC)


def _new_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    return Session(engine)


def _window():
    return calculate_completed_reporting_window(
        PERIOD_REFERENCE,
        AdministratorSummaryCadence.DAILY,
        "UTC",
    )


def _source_device_sensor(
    session: Session,
    *,
    provider_code: str,
    source_name: str,
    device_name: str,
    parameter_code: str = "pm25",
    parameter_name: str = "PM2.5",
) -> tuple[models.ExternalAPI, models.Device, models.Sensor, models.Parameter]:
    unit = session.query(models.Unit).filter_by(code="ug_m3").one_or_none()
    if unit is None:
        unit = models.Unit(
            code="ug_m3",
            symbol="µg/m³",
            name="Micrograms per cubic meter",
        )
        session.add(unit)
        session.flush()
    parameter = session.query(models.Parameter).filter_by(code=parameter_code).one_or_none()
    if parameter is None:
        parameter = models.Parameter(
            code=parameter_code,
            display_name=parameter_name,
            default_unit_id=unit.unit_id,
        )
        session.add(parameter)
        session.flush()
    source = models.ExternalAPI(
        provider_code=provider_code,
        name=source_name,
        base_url="https://provider.invalid",
        params={},
        enabled=True,
    )
    session.add(source)
    session.flush()
    device = models.Device(
        name=device_name,
        friendly_name=device_name,
        external_api_id=source.external_api_id,
        timezone="UTC",
    )
    session.add(device)
    session.flush()
    sensor = models.Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        external_sensor_id=f"{provider_code}-{parameter_code}",
    )
    session.add(sensor)
    session.flush()
    return source, device, sensor, parameter


def _job_run(
    session: Session,
    *,
    task: str,
    status: str,
    started_at: datetime,
    summary: dict | None,
    error_message: str | None = None,
    execution_trigger: str = "scheduled",
) -> models.JobRun:
    schedule = session.query(models.JobSchedule).filter_by(task=task).one_or_none()
    if schedule is None:
        schedule = models.JobSchedule(
            task=task,
            cron_expr="0 * * * *",
            timezone="UTC",
            enabled=True,
            allow_overlap=False,
        )
        session.add(schedule)
        session.flush()
    run = models.JobRun(
        job_schedule_id=schedule.job_schedule_id,
        status=status,
        execution_trigger=execution_trigger,
        started_at=started_at,
        finished_at=started_at,
        summary=summary,
        error_message=error_message,
    )
    session.add(run)
    session.flush()
    return run


def _measurement_with_qc(
    session: Session,
    *,
    sensor: models.Sensor,
    parameter: models.Parameter,
    created_at: datetime,
    check_code: str,
    evaluation_status: str,
    failure_action: str,
    reason_code: str | None = None,
    params_snapshot: dict | None = None,
    policy_snapshot: dict | None = None,
    passed_value: bool | None = None,
) -> models.MeasurementQCResult:
    measurement = models.Measurement(
        sensor_id=sensor.sensor_id,
        value=12.5,
        # Operational summaries use the QC result creation time. The source
        # observation time is deliberately irrelevant to this test.
        observed_at=None,
        is_valid=failure_action != "mark_invalid",
        created_at=created_at,
    )
    session.add(measurement)
    session.flush()
    result = models.MeasurementQCResult(
        measurement_id=measurement.measurement_id,
        parameter_id=parameter.parameter_id,
        aggregate_code="1h",
        check_code=check_code,
        passed=(
            passed_value
            if passed_value is not None
            else (False if evaluation_status == "failed" else None)
        ),
        severity="error" if evaluation_status == "failed" else "warn",
        evaluation_status=evaluation_status,
        failure_action=failure_action,
        reason_code=reason_code,
        params_snapshot=params_snapshot,
        policy_snapshot=policy_snapshot,
        created_at=created_at,
    )
    session.add(result)
    session.flush()
    return result


def test_all_good_period_uses_job_counters_but_not_importer_qc_identity() -> None:
    with _new_session() as session:
        _job_run(
            session,
            task="purpleair_import",
            status="success",
            started_at=datetime(2026, 8, 21, 4, tzinfo=UTC),
            summary={
                "measurements_received": 10,
                "measurements_inserted": 8,
                "measurements_updated": 1,
                "measurements_skipped": 1,
                # This aggregate is context only. It must not create a QC
                # warning without a persisted MeasurementQCResult.
                "qc": {"evaluated": 9, "passed": 2, "flagged": 7},
            },
        )
        session.add(
            models.Event(
                event_type="unmapped_routine_warning",
                source="background.worker",
                severity="warning",
                message="should not be included",
                created_at=datetime(2026, 8, 21, 5, tzinfo=UTC),
            )
        )
        session.commit()

        summary = build_administrator_summary(
            session,
            _window(),
            generated_at_utc=PERIOD_REFERENCE,
        )

    assert summary.overall_status is AdministratorSummaryStatus.ALL_SYSTEMS_NORMAL
    assert summary.attention_items == ()
    assert summary.qc_activity == ()
    assert summary.system_events == ()
    assert len(summary.import_sources) == 1
    purpleair = summary.import_sources[0]
    assert purpleair.source_name == "PurpleAir"
    assert purpleair.job_count == 1
    assert purpleair.successful_job_count == 1
    assert purpleair.measurements_received == 10
    assert purpleair.measurements_inserted == 8
    assert purpleair.measurements_updated == 1
    assert purpleair.measurements_skipped == 1


def test_mixed_error_period_preserves_qc_meaning_and_suppresses_duplicates() -> None:
    with _new_session() as session:
        _, device, sensor, parameter = _source_device_sensor(
            session,
            provider_code="purpleair",
            source_name="PurpleAir",
            device_name="Calzada <script>alert(1)</script>",
        )
        _job_run(
            session,
            task="airgradient_import",
            status="failed",
            started_at=datetime(2026, 8, 21, 2, tzinfo=UTC),
            summary=None,
            error_message="provider secret and raw exception must never appear",
        )
        _job_run(
            session,
            task="airgradient_import",
            status="success",
            started_at=datetime(2026, 8, 21, 3, tzinfo=UTC),
            summary={
                "measurements_received": 4,
                "measurements_inserted": 4,
                "measurements_updated": 0,
                "measurements_skipped": 0,
            },
        )

        qc_time = datetime(2026, 8, 21, 4, tzinfo=UTC)
        _measurement_with_qc(
            session,
            sensor=sensor,
            parameter=parameter,
            created_at=qc_time,
            check_code="min_value",
            evaluation_status="failed",
            failure_action="flag_for_review",
        )
        _measurement_with_qc(
            session,
            sensor=sensor,
            parameter=parameter,
            created_at=qc_time,
            check_code="max_value",
            evaluation_status="failed",
            failure_action="mark_invalid",
        )
        _measurement_with_qc(
            session,
            sensor=sensor,
            parameter=parameter,
            created_at=qc_time,
            check_code="missing_plugin",
            evaluation_status="indeterminate",
            failure_action="flag_for_review",
            reason_code="plugin_unavailable",
        )

        events = [
            models.Event(
                event_type="airgradient_measurement_error",
                source="airgradient_importer",
                severity="error",
                message="duplicate of failed JobRun",
                raw_snippet="raw provider response",
                endpoint="https://sensitive.invalid/path",
                params={"token": "secret"},
                created_at=datetime(2026, 8, 21, 5, tzinfo=UTC),
            ),
            models.Event(
                event_type="openaq_measurements_validation_failed",
                source="openaq_importer",
                severity="warning",
                message="raw schema exception",
                raw_snippet="sensitive raw body",
                endpoint="https://provider.invalid/private",
                params={"api_key": "secret"},
                created_at=datetime(2026, 8, 21, 6, tzinfo=UTC),
            ),
            models.Event(
                event_type="unmapped_warning",
                source="system.worker",
                severity="warning",
                message="not on the explicit warning allowlist",
                created_at=datetime(2026, 8, 21, 7, tzinfo=UTC),
            ),
            models.Event(
                event_type="unmapped_system_failure",
                source="system.worker",
                severity="error",
                device_id=device.device_id,
                message="exception with secret value",
                raw_snippet="<img src=x onerror=alert(1)>",
                created_at=datetime(2026, 8, 21, 8, tzinfo=UTC),
            ),
            models.Event(
                event_type="email.test.failed",
                source="admin.email",
                severity="error",
                message="suppressed administrative email event",
                created_at=datetime(2026, 8, 21, 9, tzinfo=UTC),
            ),
        ]
        session.add_all(events)
        session.commit()

        summary = build_administrator_summary(
            session,
            _window(),
            generated_at_utc=PERIOD_REFERENCE,
        )

    assert summary.overall_status is AdministratorSummaryStatus.NEEDS_ATTENTION
    assert {group.outcome for group in summary.qc_activity} == {
        QcDigestOutcome.FLAGGED_FOR_REVIEW,
        QcDigestOutcome.MARKED_INVALID,
        QcDigestOutcome.INDETERMINATE,
    }
    flag_group = next(
        group
        for group in summary.qc_activity
        if group.outcome is QcDigestOutcome.FLAGGED_FOR_REVIEW
    )
    assert flag_group.measurement_count == 1
    assert flag_group.check_name == "Minimum Value QC Check"

    attention_codes = [item.attention_code for item in summary.attention_items]
    assert attention_codes.count("import_jobs_failed") == 1
    assert "source_measurement_error" not in attention_codes
    assert "source_measurement_validation_failed" in attention_codes
    assert "qc_marked_invalid" in attention_codes
    assert "qc_flagged_for_review" in attention_codes
    assert "qc_indeterminate" in attention_codes
    assert "system_error" in attention_codes
    qc_attention = [
        item for item in summary.attention_items if item.attention_code.startswith("qc_")
    ]
    assert [item.attention_code for item in qc_attention] == [
        "qc_marked_invalid",
        "qc_flagged_for_review",
        "qc_indeterminate",
    ]
    assert len(summary.attention_items) == 6
    assert summary.import_sources[0].job_status_code == "failed"

    assert [group.digest_code for group in summary.import_events] == [
        "source_measurement_validation_failed"
    ]
    assert [group.digest_code for group in summary.system_events] == [
        "system_error"
    ]
    assert summary.system_events[0].device_name == "Calzada <script>alert(1)</script>"
    rendered = render_administrator_summary_email(summary, "en")
    combined_message = "\n".join(
        (rendered.subject, rendered.text_body, rendered.html_body)
    )
    for sensitive_value in (
        "provider secret",
        "raw provider response",
        "sensitive raw body",
        "api_key",
        "secret value",
        "https://sensitive.invalid",
        "https://provider.invalid/private",
    ):
        assert sensitive_value not in combined_message


def test_qc_summary_uses_persisted_effective_settings_and_excludes_normal_cases() -> None:
    with _new_session() as session:
        _, _, sensor, parameter = _source_device_sensor(
            session,
            provider_code="openaq",
            source_name="OpenAQ",
            device_name="Effective settings station",
        )
        qc_time = datetime(2026, 8, 21, 4, tzinfo=UTC)
        common_policy = {
            "configured_unit_code": "mg_m3",
            "evaluation_unit_code": "ug_m3",
            "applicability": "applicable",
        }
        _measurement_with_qc(
            session,
            sensor=sensor,
            parameter=parameter,
            created_at=qc_time,
            check_code="min_value",
            evaluation_status="failed",
            failure_action="flag_for_review",
            params_snapshot={"min": 100},
            policy_snapshot=common_policy,
        )
        _measurement_with_qc(
            session,
            sensor=sensor,
            parameter=parameter,
            created_at=qc_time,
            check_code="max_value",
            evaluation_status="failed",
            failure_action="mark_invalid",
            params_snapshot={"max": 0},
            policy_snapshot=common_policy,
        )
        _measurement_with_qc(
            session,
            sensor=sensor,
            parameter=parameter,
            created_at=qc_time,
            check_code="baseline_drift",
            evaluation_status="failed",
            failure_action="flag_for_review",
            params_snapshot={"max_drift_per_day": 0.5, "direction": "both"},
            policy_snapshot=common_policy,
        )
        _measurement_with_qc(
            session,
            sensor=sensor,
            parameter=parameter,
            created_at=qc_time,
            check_code="min_value",
            evaluation_status="failed",
            failure_action="flag_for_review",
            reason_code="no_matching_rule",
            params_snapshot={"min": -999},
            policy_snapshot={
                "evaluation_unit_code": "ug_m3",
                "applicability": "not_applicable",
            },
        )
        _measurement_with_qc(
            session,
            sensor=sensor,
            parameter=parameter,
            created_at=qc_time,
            check_code="max_value",
            evaluation_status="failed",
            failure_action="mark_invalid",
            params_snapshot={"max": 999},
            policy_snapshot=common_policy,
            passed_value=True,
        )
        session.commit()

        groups, truncated = collect_qc_activity(session, _window())

    assert truncated is False
    settings_by_check = {group.check_code: group for group in groups}
    assert set(settings_by_check) == {"min_value", "max_value", "baseline_drift"}
    assert settings_by_check["min_value"].effective_threshold == 100
    assert settings_by_check["max_value"].effective_threshold == 0
    assert settings_by_check["baseline_drift"].effective_max_drift_per_day == 0.5
    assert settings_by_check["baseline_drift"].effective_drift_direction == "both"
    assert all(group.effective_unit_symbol == "µg/m³" for group in groups)

    attention_by_check = {
        item.check_code: item
        for item in derive_attention_items((), groups, (), ())
    }
    assert attention_by_check["min_value"].effective_threshold == 100
    assert attention_by_check["max_value"].effective_unit_symbol == "µg/m³"
    assert attention_by_check["baseline_drift"].effective_max_drift_per_day == 0.5
    assert attention_by_check["baseline_drift"].effective_drift_direction == "both"


def test_collectors_use_bounded_queries_without_selecting_sensitive_payloads() -> None:
    with _new_session() as session:
        statements: list[str] = []

        @event.listens_for(session.get_bind(), "before_cursor_execute")
        def capture_statement(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())

        try:
            build_administrator_summary(
                session,
                _window(),
                generated_at_utc=PERIOD_REFERENCE,
            )
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", capture_statement)

    selects = [statement for statement in statements if statement.lstrip().startswith("select")]
    assert len(selects) == 4
    assert sum("group by" in statement for statement in selects) == 3
    expected_source_queries = [
        statement
        for statement in selects
        if "job_schedule.cron_expr" in statement
    ]
    assert len(expected_source_queries) == 1
    assert " limit " in expected_source_queries[0]
    combined_sql = "\n".join(selects)
    assert "count(distinct" in combined_sql
    assert "measurement.value" not in combined_sql
    assert "event.message" not in combined_sql
    assert "event.raw_snippet" not in combined_sql
    assert "event.endpoint" not in combined_sql
    assert "event.params" not in combined_sql
    assert "job_run.error_message" not in combined_sql


def test_aggregate_statements_preserve_half_open_window_filters() -> None:
    window = _window()
    for statement in (
        build_import_summary_statement(window),
        build_qc_summary_statement(window),
        build_event_summary_statement(window),
    ):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
        assert ">=" in sql
        assert "<" in sql
        assert "group by" in sql


def test_collectors_include_period_start_and_exclude_period_end() -> None:
    window = _window()
    with _new_session() as session:
        _, device, sensor, parameter = _source_device_sensor(
            session,
            provider_code="purpleair",
            source_name="PurpleAir",
            device_name="Boundary device",
        )
        for boundary_time in (window.period_start_utc, window.period_end_utc):
            _job_run(
                session,
                task="purpleair_import",
                status="success",
                started_at=boundary_time,
                summary={"measurements_received": 1},
            )
            _measurement_with_qc(
                session,
                sensor=sensor,
                parameter=parameter,
                created_at=boundary_time,
                check_code="min_value",
                evaluation_status="failed",
                failure_action="flag_for_review",
            )
            session.add(
                models.Event(
                    event_type="unmapped_boundary_error",
                    source="system.worker",
                    severity="error",
                    device_id=device.device_id,
                    created_at=boundary_time,
                )
            )
        session.commit()

        summary = build_administrator_summary(
            session,
            window,
            generated_at_utc=PERIOD_REFERENCE,
        )

    assert summary.import_sources[0].job_count == 1
    assert summary.import_sources[0].measurements_received == 1
    assert summary.qc_activity[0].result_count == 1
    assert summary.system_events[0].event_count == 1


def test_runnable_due_source_with_only_manual_run_reports_scheduled_run_missing() -> None:
    with _new_session() as session:
        session.add(
            models.ExternalAPI(
                provider_code="airgradient",
                name="AirGradient",
                base_url="https://api.airgradient.com/public/api",
                api_key="configured-key",
                params={},
                enabled=True,
            )
        )
        _job_run(
            session,
            task="airgradient_import",
            status="success",
            started_at=datetime(2026, 8, 21, 4, tzinfo=UTC),
            summary={"measurements_received": 0},
            execution_trigger="manual",
        )
        schedule = session.query(models.JobSchedule).filter_by(
            task="airgradient_import"
        ).one()
        schedule.created_at = datetime(2026, 8, 20, tzinfo=UTC)
        schedule.updated_at = datetime(2026, 8, 20, tzinfo=UTC)
        session.commit()

        summary = build_administrator_summary(
            session,
            _window(),
            generated_at_utc=PERIOD_REFERENCE,
            environment={
                "COMPASSAQ_ENV": "development",
                "DISABLE_PAID_API_REQUESTS": "false",
            },
        )

    source = summary.import_sources[0]
    assert source.source_name == "AirGradient"
    assert source.job_count == 1
    assert source.manual_job_count == 1
    assert source.scheduled_job_count == 0
    assert source.scheduled_run_expected is True
    assert source.scheduled_run_missing is True
    assert source.job_status_code == "no_scheduled_run"
    assert [item.attention_code for item in summary.attention_items] == [
        "scheduled_import_missing"
    ]
    assert summary.system_events == ()
    rendered = render_administrator_summary_email(summary, "en")
    assert "AirGradient: Job Status: No scheduled run" in rendered.text_body
    assert "configured-key" not in (
        rendered.subject + rendered.text_body + rendered.html_body
    )


def test_manual_run_does_not_contribute_to_scheduled_import_counters() -> None:
    with _new_session() as session:
        _job_run(
            session,
            task="openaq_import",
            status="success",
            started_at=datetime(2026, 8, 21, 4, tzinfo=UTC),
            summary={
                "measurements_received": 10,
                "measurements_inserted": 8,
                "measurements_updated": 1,
                "measurements_skipped": 1,
            },
            execution_trigger="scheduled",
        )
        _job_run(
            session,
            task="openaq_import",
            status="failed",
            started_at=datetime(2026, 8, 21, 5, tzinfo=UTC),
            summary={
                "measurements_received": 100,
                "measurements_inserted": 90,
                "measurements_updated": 5,
                "measurements_skipped": 5,
            },
            error_message="manual test failure",
            execution_trigger="manual",
        )
        session.commit()

        summary = build_administrator_summary(
            session,
            _window(),
            generated_at_utc=PERIOD_REFERENCE,
        )

    source = summary.import_sources[0]
    assert source.scheduled_job_count == 1
    assert source.manual_job_count == 1
    assert source.job_status_code == "success"
    assert source.measurements_received == 10
    assert source.measurements_inserted == 8
    assert source.measurements_updated == 1
    assert source.measurements_skipped == 1
    rendered = render_administrator_summary_email(summary, "en")
    assert "OpenAQ: Job Status: Success; Received: 10; Inserted: 8; Updated: 1; Skipped: 1" in rendered.text_body
    assert "Received: 100" not in rendered.text_body


def test_all_active_sources_are_reported_when_cron_is_not_due() -> None:
    not_due_window = calculate_completed_reporting_window(
        PERIOD_REFERENCE,
        AdministratorSummaryCadence.EVERY_15_MINUTES,
        "UTC",
    )
    source_definitions = (
        ("openaq", "openaq_import", "OpenAQ"),
        ("purpleair", "purpleair_import", "PurpleAir"),
        ("airgradient", "airgradient_import", "AirGradient"),
    )
    with _new_session() as session:
        for provider_code, task, source_name in source_definitions:
            session.add(
                models.ExternalAPI(
                    provider_code=provider_code,
                    name=source_name,
                    base_url="https://provider.invalid",
                    api_key="configured-key",
                    params={},
                    enabled=True,
                )
            )
            session.add(
                models.JobSchedule(
                    task=task,
                    cron_expr="0 0 * * *",
                    timezone="UTC",
                    enabled=True,
                    allow_overlap=False,
                    created_at=datetime(2026, 8, 20, tzinfo=UTC),
                    updated_at=datetime(2026, 8, 20, tzinfo=UTC),
                )
            )
        session.commit()

        summary = build_administrator_summary(
            session,
            not_due_window,
            generated_at_utc=PERIOD_REFERENCE,
            environment={"COMPASSAQ_ENV": "development"},
        )

    assert [source.source_name for source in summary.import_sources] == [
        "AirGradient",
        "OpenAQ",
        "PurpleAir",
    ]
    assert all(
        source.job_status_code == "not_scheduled_this_period"
        and source.scheduled_run_expected is False
        and source.scheduled_job_count == 0
        for source in summary.import_sources
    )
    assert summary.attention_items == ()
    assert summary.system_events == ()

    rendered = render_administrator_summary_email(summary, "en")
    for source_name in ("AirGradient", "OpenAQ", "PurpleAir"):
        assert (
            f"{source_name}: Job Status: Not scheduled this period; "
            "Received: —; Inserted: —; Updated: —; Skipped: —"
        ) in rendered.text_body
    assert "Received: 0" not in rendered.text_body


def test_expected_scheduled_run_with_zero_received_is_not_a_failure() -> None:
    with _new_session() as session:
        session.add(
            models.ExternalAPI(
                provider_code="airgradient",
                name="AirGradient",
                base_url="https://api.airgradient.com/public/api",
                api_key="configured-key",
                params={},
                enabled=True,
            )
        )
        _job_run(
            session,
            task="airgradient_import",
            status="success",
            started_at=datetime(2026, 8, 21, 4, tzinfo=UTC),
            summary={
                "measurements_received": 0,
                "measurements_inserted": 0,
                "measurements_updated": 0,
                "measurements_skipped": 0,
            },
            execution_trigger="scheduled",
        )
        schedule = session.query(models.JobSchedule).filter_by(
            task="airgradient_import"
        ).one()
        schedule.created_at = datetime(2026, 8, 20, tzinfo=UTC)
        schedule.updated_at = datetime(2026, 8, 20, tzinfo=UTC)
        session.commit()

        summary = build_administrator_summary(
            session,
            _window(),
            generated_at_utc=PERIOD_REFERENCE,
            environment={"COMPASSAQ_ENV": "development"},
        )

    source = summary.import_sources[0]
    assert source.scheduled_run_expected is True
    assert source.scheduled_job_count == 1
    assert source.measurements_received == 0
    assert source.scheduled_run_missing is False
    assert source.job_status_code == "success"
    assert summary.attention_items == ()
    rendered = render_administrator_summary_email(summary, "en")
    assert "AirGradient: Job Status: Success; Received: 0; Inserted: 0; Updated: 0; Skipped: 0" in rendered.text_body


def test_multiple_scheduled_runs_use_the_most_important_status() -> None:
    with _new_session() as session:
        _job_run(
            session,
            task="purpleair_import",
            status="success",
            started_at=datetime(2026, 8, 21, 2, tzinfo=UTC),
            summary={"measurements_received": 2},
        )
        _job_run(
            session,
            task="purpleair_import",
            status="failed",
            started_at=datetime(2026, 8, 21, 3, tzinfo=UTC),
            summary=None,
        )
        _job_run(
            session,
            task="purpleair_import",
            status="timeout",
            started_at=datetime(2026, 8, 21, 4, tzinfo=UTC),
            summary=None,
            execution_trigger="manual",
        )
        session.commit()

        summary = build_administrator_summary(
            session,
            _window(),
            generated_at_utc=PERIOD_REFERENCE,
        )

    source = summary.import_sources[0]
    assert source.scheduled_job_count == 2
    assert source.manual_job_count == 1
    # Manual status does not determine the scheduled-status cell; among the
    # two scheduled rows, Failed outranks Success under the documented rule.
    assert source.job_status_code == "failed"


def test_scheduled_timeout_and_interruption_map_to_distinct_status_codes() -> None:
    with _new_session() as session:
        _job_run(
            session,
            task="openaq_import",
            status="timeout",
            started_at=datetime(2026, 8, 21, 2, tzinfo=UTC),
            summary=None,
        )
        _job_run(
            session,
            task="airgradient_import",
            status="interrupted",
            started_at=datetime(2026, 8, 21, 3, tzinfo=UTC),
            summary=None,
        )
        session.commit()

        summary = build_administrator_summary(
            session,
            _window(),
            generated_at_utc=PERIOD_REFERENCE,
        )

    status_by_source = {
        source.source_code: source.job_status_code
        for source in summary.import_sources
    }
    assert status_by_source["openaq"] == "timed_out"
    assert status_by_source["airgradient"] == "interrupted"
