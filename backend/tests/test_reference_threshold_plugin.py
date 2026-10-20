"""End-to-end acceptance for an application-unknown packaged QC plugin."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import shutil
import uuid

from sqlalchemy import event, select

import models
from api.routes.admin.events import list_qc_failures
from db import SessionLocal
from qaqc import discovery, registry
from qaqc.admin_policy import (
    OverrideValue,
    PolicyScope,
    build_policy_response,
    get_check_metadata,
    list_parameter_policy_summaries,
    replace_generic_scope_overrides,
)
from qaqc.persistence import apply_ingest_qc_result
from qaqc.pipeline import run_ingest_detailed
from qaqc.types import QCRecord
from qaqc.types import QCDecision
from services.administrator_summary_collector import (
    collect_qc_activity,
    derive_attention_items,
)
from services.administrator_summary_domain import (
    AdministratorSummary,
    AdministratorSummaryCadence,
    ReportingWindow,
)
from services.administrator_summary_renderer import render_administrator_summary_email


UTC = timezone.utc
PLUGIN_ROOT = Path(__file__).parent / "plugins" / "reference_threshold"


def _install_test_distribution(tmp_path: Path, monkeypatch) -> Path:
    """Expose real dist-info so importlib discovers the standard entry point."""

    distribution_root = tmp_path / "installed-reference-threshold"
    distribution_root.mkdir()
    dist_info = distribution_root / "compassaq_reference_threshold_test-1.0.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\n"
        "Name: compassaq-reference-threshold-test\n"
        "Version: 1.0.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        "[aq_platform.qaqc_plugins]\n"
        "reference_threshold = compassaq_reference_threshold.plugin:plugin\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(PLUGIN_ROOT / "src"))
    monkeypatch.syspath_prepend(str(distribution_root))
    importlib.invalidate_caches()
    return dist_info


def test_reference_threshold_package_uses_the_complete_generic_path(
    tmp_path,
    monkeypatch,
):
    previous_registrations = tuple(registry.all_registrations().values())
    dist_info = _install_test_distribution(tmp_path, monkeypatch)
    try:
        report = discovery.load_plugins()
        registration = registry.get_registration("reference_threshold")
        assert registration is not None
        assert registration.metadata.origin == "entry_point"
        assert registration.metadata.distribution == (
            "compassaq-reference-threshold-test"
        )
        assert {item["name"] for item in report["entry_points"]} >= {
            "reference_threshold"
        }

        metadata = get_check_metadata()
        reference_metadata = next(
            item for item in metadata if item["check_code"] == "reference_threshold"
        )
        assert reference_metadata["overview"] == {
            "visible": True,
            "label": "Reference Threshold",
            "order": 40,
            "summary_setting": "limit",
        }
        assert [item["check_code"] for item in metadata[:4]] == [
            "min_value",
            "max_value",
            "baseline_drift",
            "reference_threshold",
        ]

        suffix = uuid.uuid4().hex
        with SessionLocal() as session:
            parameter = session.scalar(
                select(models.Parameter).where(models.Parameter.code == "pm25")
            )
            unit = session.get(models.Unit, parameter.default_unit_id)
            source = models.ExternalAPI(
                provider_code=f"reference-threshold-{suffix}",
                name=f"Reference threshold source {suffix}",
                params={},
            )
            session.add(source)
            session.flush()
            device = models.Device(
                name=f"Reference threshold site {suffix}",
                external_id=f"reference-threshold-device-{suffix}",
                external_api_id=source.external_api_id,
            )
            session.add(device)
            session.flush()
            sensor = models.Sensor(
                device_id=device.device_id,
                parameter_id=parameter.parameter_id,
                unit_id=unit.unit_id,
                external_sensor_id=f"reference-threshold-sensor-{suffix}",
            )
            session.add(sensor)
            session.flush()

            replace_generic_scope_overrides(
                session,
                PolicyScope("parameter", parameter_id=parameter.parameter_id),
                [
                    OverrideValue(
                        check_code="reference_threshold",
                        enabled_override=True,
                        failure_action_override="flag_for_review",
                        settings={"limit": 5},
                        policy_unit_code=None,
                    )
                ],
            )
            parameter_policy = build_policy_response(
                session,
                PolicyScope("parameter", parameter_id=parameter.parameter_id),
            )
            source_policy = build_policy_response(
                session,
                PolicyScope(
                    "source_parameter",
                    parameter_id=parameter.parameter_id,
                    external_api_id=source.external_api_id,
                ),
            )
            sensor_policy = build_policy_response(
                session,
                PolicyScope("sensor", sensor_id=sensor.sensor_id),
            )
            for policy in (parameter_policy, source_policy, sensor_policy):
                check = next(
                    item
                    for item in policy["checks"]
                    if item["check_code"] == "reference_threshold"
                )
                assert check["status"] == "ready"
                assert check["configured_settings"]["limit"] == 5

            observed_at = datetime.now(UTC)
            measurement = models.Measurement(
                sensor_id=sensor.sensor_id,
                value=6,
                observed_at=observed_at,
            )
            session.add(measurement)
            session.flush()
            detailed = run_ingest_detailed(
                [
                    QCRecord(
                        sensor_id=sensor.sensor_id,
                        parameter_id=parameter.parameter_id,
                        value=measurement.value,
                        unit_id=unit.unit_id,
                        observed_at=observed_at,
                    )
                ],
                {"session": session, "aggregate_code": "raw"},
            )
            assert detailed["per_plugin"]["reference_threshold"][0].is_valid is False
            apply_ingest_qc_result(
                session,
                measurement,
                parameter.parameter_id,
                "raw",
                detailed,
                replace_existing=False,
            )
            session.flush()
            persisted = session.scalar(
                select(models.MeasurementQCResult).where(
                    models.MeasurementQCResult.measurement_id
                    == measurement.measurement_id,
                    models.MeasurementQCResult.check_code
                    == "reference_threshold",
                )
            )
            assert persisted is not None
            assert persisted.plugin_version == "1.0.0"
            assert persisted.params_snapshot == {"limit": 5}

            events = list_qc_failures(
                limit=25,
                offset=0,
                search=None,
                parameter=None,
                status=None,
                outcome=None,
                data_source=source.provider_code,
                session=session,
            )
            assert events.total == 1
            assert events.items[0].check_name == "Reference Threshold QC Check"
            assert events.items[0].plugin_version == "1.0.0"

            window = ReportingWindow(
                cadence=AdministratorSummaryCadence.HOURLY,
                reporting_timezone="UTC",
                period_start_utc=observed_at - timedelta(minutes=1),
                period_end_utc=observed_at + timedelta(minutes=1),
                period_start_local=observed_at - timedelta(minutes=1),
                period_end_local=observed_at + timedelta(minutes=1),
            )
            qc_activity, truncated = collect_qc_activity(session, window)
            reference_activity = next(
                item for item in qc_activity if item.check_code == "reference_threshold"
            )
            assert reference_activity.check_name == "Reference Threshold QC Check"
            attention = derive_attention_items((), qc_activity, (), ())
            summary = AdministratorSummary(
                reporting_window=window,
                generated_at_utc=observed_at,
                qc_activity=qc_activity,
                attention_items=attention,
                qc_groups_truncated=truncated,
            )
            rendered = render_administrator_summary_email(summary, "en")
            assert (
                "1 PM2.5 measurement at Reference threshold site"
                in rendered.text_body
            )
            assert "flagged for review by the Reference Threshold QC Check" in rendered.text_body

            shutil.rmtree(dist_info)
            importlib.invalidate_caches()
            discovery.load_plugins()
            assert registry.get_registration("reference_threshold") is None
            assert all(
                item["check_code"] != "reference_threshold"
                for item in get_check_metadata()
            )
            unavailable_policy = build_policy_response(
                session,
                PolicyScope("sensor", sensor_id=sensor.sensor_id),
            )
            unavailable = next(
                item
                for item in unavailable_policy["checks"]
                if item["check_code"] == "reference_threshold"
            )
            assert unavailable["status"] == "ready"
            unavailable_result = run_ingest_detailed(
                [
                    QCRecord(
                        sensor_id=sensor.sensor_id,
                        parameter_id=parameter.parameter_id,
                        value=6,
                        unit_id=unit.unit_id,
                        observed_at=observed_at,
                    )
                ],
                {"session": session, "aggregate_code": "raw"},
            )
            assert unavailable_result["per_plugin"]["reference_threshold"][0].patch == {
                "reason_code": "plugin_unavailable"
            }
            events_after_uninstall = list_qc_failures(
                limit=25,
                offset=0,
                search=None,
                parameter=None,
                status=None,
                outcome=None,
                data_source=source.provider_code,
                session=session,
            )
            assert events_after_uninstall.items[0].check_name == "Reference threshold"
            assert events_after_uninstall.items[0].plugin_version == "1.0.0"
            session.rollback()
    finally:
        registry.replace_all(previous_registrations)


def test_application_source_has_no_reference_threshold_integration():
    repository_root = Path(__file__).resolve().parents[2]
    application_roots = (
        repository_root / "backend" / "qaqc",
        repository_root / "backend" / "api",
        repository_root / "backend" / "services",
        repository_root / "frontend" / "src",
    )
    occurrences = []
    for application_root in application_roots:
        for path in application_root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            if "test" in path.relative_to(application_root).parts:
                continue
            if "reference_threshold" in path.read_text(encoding="utf-8"):
                occurrences.append(path.relative_to(repository_root).as_posix())
    assert occurrences == []


def test_qc_overview_has_no_max_value_renderer():
    overview_source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "qc"
        / "AdminQcOverview.tsx"
    ).read_text(encoding="utf-8")
    assert "max_value" not in overview_source
    assert 'checkCode="max_value"' not in overview_source


def test_unconfigured_overview_plugin_does_not_add_parameter_queries():
    class UnconfiguredPlugin:
        name = "query_count_guardrail"
        version = "1.0.0"
        qc_api = 1
        required_access = "api-only"
        display_name = "Query Count Guardrail"
        description = "Test query-count stability"
        long_description = "Test query-count stability for the overview"
        param_schema = {}
        unit_settings = ()
        overview = {"visible": True, "label": "Query Count Guardrail", "order": 900}

        def apply(self, records, context):
            return [QCDecision(True, [], "info") for _record in records]

    previous_registrations = tuple(registry.all_registrations().values())
    with SessionLocal() as session:
        statement_count = 0

        def count_statement(*_args):
            nonlocal statement_count
            statement_count += 1

        event.listen(session.bind, "before_cursor_execute", count_statement)
        try:
            list_parameter_policy_summaries(session)
            baseline_count = statement_count
            registry.register(UnconfiguredPlugin())
            statement_count = 0
            list_parameter_policy_summaries(session)
            assert statement_count == baseline_count
        finally:
            event.remove(session.bind, "before_cursor_execute", count_statement)
            registry.replace_all(previous_registrations)
