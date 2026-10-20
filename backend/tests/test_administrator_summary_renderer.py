from __future__ import annotations

from datetime import datetime, timezone
import inspect
import re

import pytest

from services import administrator_summary_renderer
from services.administrator_summary_collector import derive_attention_items
from services.administrator_summary_domain import (
    AdministratorSummary,
    AdministratorSummaryCadence,
    AttentionItem,
    EventDigestGroup,
    EventDigestSection,
    ImportSourceSummary,
    QcActivityGroup,
    QcDigestOutcome,
    calculate_completed_reporting_window,
)
from services.administrator_summary_renderer import (
    render_administrator_summary_email,
)


UTC = timezone.utc


def _window(cadence: AdministratorSummaryCadence = AdministratorSummaryCadence.DAILY):
    return calculate_completed_reporting_window(
        datetime(2026, 8, 22, 14, 30, tzinfo=UTC),
        cadence,
        "America/Los_Angeles",
    )


def _all_good_summary() -> AdministratorSummary:
    return AdministratorSummary(
        reporting_window=_window(),
        generated_at_utc=datetime(2026, 8, 22, 15, tzinfo=UTC),
        import_sources=(
            ImportSourceSummary(
                source_code="purpleair",
                source_name="PurpleAir",
                job_count=2,
                successful_job_count=2,
                failed_job_count=0,
                timed_out_job_count=0,
                running_job_count=0,
                skipped_job_count=0,
                measurements_received=100,
                measurements_inserted=90,
                measurements_updated=5,
                measurements_skipped=5,
                scheduled_job_count=2,
                scheduled_job_status_code="success",
            ),
        ),
        environment_label="Development",
    )


def _attention_summary() -> AdministratorSummary:
    device_name = "Calzada <script>alert('x')</script>"
    qc_groups = (
        QcActivityGroup(
            source_name="PurpleAir",
            device_name=device_name,
            parameter_name="PM2.5",
            check_code="min_value",
            check_name="Minimum plausible value",
            outcome=QcDigestOutcome.FLAGGED_FOR_REVIEW,
            reason_code=None,
            result_count=2,
            measurement_count=2,
            effective_threshold=100,
            effective_unit_symbol="µg/m³",
        ),
        QcActivityGroup(
            source_name="PurpleAir",
            device_name=device_name,
            parameter_name="PM10",
            check_code="max_value",
            check_name="Maximum plausible value",
            outcome=QcDigestOutcome.MARKED_INVALID,
            reason_code=None,
            result_count=4,
            measurement_count=4,
            effective_threshold=0,
            effective_unit_symbol="µg/m³",
        ),
        QcActivityGroup(
            source_name="PurpleAir",
            device_name=device_name,
            parameter_name="RH",
            check_code="missing_plugin",
            check_name="Missing plugin",
            outcome=QcDigestOutcome.INDETERMINATE,
            reason_code="plugin_unavailable",
            result_count=1,
            measurement_count=1,
        ),
    )
    system_event = EventDigestGroup(
        digest_code="system_error",
        section=EventDigestSection.SYSTEM,
        source_code="system",
        source_name="CompassAQ",
        device_name=device_name,
        severity="error",
        event_count=1,
    )
    attention = (
        AttentionItem(
            attention_code="import_jobs_failed",
            count=1,
            source_name="OpenAQ",
            successful_job_count=0,
        ),
        AttentionItem(
            attention_code="qc_marked_invalid",
            count=4,
            source_name="PurpleAir",
            device_name=device_name,
            parameter_name="PM10",
            check_code="max_value",
            check_name="Max Value QC Check",
            effective_threshold=0,
            effective_unit_symbol="µg/m³",
        ),
        AttentionItem(
            attention_code="qc_flagged_for_review",
            count=2,
            source_name="PurpleAir",
            device_name=device_name,
            parameter_name="PM2.5",
            check_code="min_value",
            check_name="Min Value QC Check",
            effective_threshold=100,
            effective_unit_symbol="µg/m³",
        ),
        AttentionItem(
            attention_code="qc_indeterminate",
            count=1,
            source_name="PurpleAir",
            device_name=device_name,
            parameter_name="RH",
            check_code="missing_plugin",
            check_name="Missing plugin",
            reason_code="plugin_unavailable",
        ),
        AttentionItem(
            attention_code="system_error",
            count=1,
            source_name="CompassAQ",
            device_name=device_name,
        ),
    )
    return AdministratorSummary(
        reporting_window=_window(AdministratorSummaryCadence.HOURLY),
        generated_at_utc=datetime(2026, 8, 22, 14, 30, tzinfo=UTC),
        qc_activity=qc_groups,
        system_events=(system_event,),
        attention_items=attention,
    )


@pytest.mark.parametrize(
    ("language", "subject_text", "title", "normal_text"),
    [
        (
            "en",
            "[CompassAQ Development] Summary — Aug 21 — All systems normal",
            "CompassAQ Administrator Summary",
            "All systems normal",
        ),
        (
            "es",
            "[CompassAQ Development] Resumen — 21 ago — Todos los sistemas normales",
            "Resumen para administradores de CompassAQ",
            "Todos los sistemas normales",
        ),
    ],
)
def test_all_good_summary_renders_subject_text_and_html_in_both_languages(
    language: str,
    subject_text: str,
    title: str,
    normal_text: str,
) -> None:
    rendered = render_administrator_summary_email(_all_good_summary(), language)

    assert rendered.subject == subject_text
    assert title.upper() in rendered.text_body
    assert title in rendered.html_body
    assert normal_text in rendered.text_body
    assert normal_text in rendered.html_body
    assert "PurpleAir" in rendered.text_body
    assert "100" in rendered.html_body
    assert "QC activity" not in rendered.text_body
    assert "Actividad de control de calidad" not in rendered.text_body


def test_attention_rendering_preserves_flag_invalid_and_indeterminate_meanings() -> None:
    english = render_administrator_summary_email(_attention_summary(), "en")
    spanish = render_administrator_summary_email(_attention_summary(), "es")

    assert english.subject.endswith("5 issues need attention")
    assert spanish.subject.endswith("5 problemas requieren atención")
    assert "flagged for review by the Min Value QC Check" in english.text_body
    assert "They were not marked invalid." in english.text_body
    assert "marked invalid" in english.text_body
    assert "could not be completed" in english.text_body
    assert "because the QC check was unavailable." in english.text_body
    assert "se marcaron para revisión mediante la Min Value QC Check" in spanish.text_body
    assert "No se marcaron como no válidas." in spanish.text_body
    assert "se marcaron como no válidas" in spanish.text_body
    assert "no pudo completarse" in spanish.text_body
    assert "porque el control de calidad no estaba disponible." in spanish.text_body


def _qc_attention_summary() -> AdministratorSummary:
    qc_groups = (
        QcActivityGroup(
            source_name="AirGradient",
            device_name="LQA PUC RIO",
            parameter_name="PM2.5",
            check_code="max_value",
            check_name="Maximum plausible value",
            outcome=QcDigestOutcome.MARKED_INVALID,
            reason_code=None,
            result_count=29,
            measurement_count=29,
            effective_threshold=0,
            effective_unit_symbol="µg/m³",
        ),
        QcActivityGroup(
            source_name="OpenAQ",
            device_name="Calzada, Taguig",
            parameter_name="PM2.5",
            check_code="baseline_drift",
            check_name="Baseline drift",
            outcome=QcDigestOutcome.FLAGGED_FOR_REVIEW,
            reason_code=None,
            result_count=30,
            measurement_count=30,
            effective_max_drift_per_day=0,
            effective_unit_symbol="µg/m³",
            effective_drift_direction="both",
        ),
        QcActivityGroup(
            source_name="PurpleAir",
            device_name="UAlbany – Queens College (DEC)",
            parameter_name="PM2.5",
            check_code="min_value",
            check_name="Minimum plausible value",
            outcome=QcDigestOutcome.FLAGGED_FOR_REVIEW,
            reason_code=None,
            result_count=15,
            measurement_count=15,
            effective_threshold=100,
            effective_unit_symbol="µg/m³",
        ),
    )
    import_sources = tuple(
        ImportSourceSummary(
            source_code=source_code,
            source_name=source_name,
            job_count=1,
            successful_job_count=1,
            failed_job_count=0,
            timed_out_job_count=0,
            running_job_count=0,
            skipped_job_count=0,
            measurements_received=received,
            measurements_inserted=inserted,
            measurements_updated=0,
            measurements_skipped=received - inserted,
            scheduled_job_count=1,
            scheduled_job_status_code="success",
        )
        for source_code, source_name, received, inserted in (
            ("airgradient", "AirGradient", 27, 6),
            ("openaq", "OpenAQ", 22, 0),
            ("purpleair", "PurpleAir", 92, 89),
        )
    )
    return AdministratorSummary(
        reporting_window=_window(AdministratorSummaryCadence.HOURLY),
        generated_at_utc=datetime(2026, 8, 22, 14, 30, tzinfo=UTC),
        import_sources=import_sources,
        qc_activity=qc_groups,
        attention_items=derive_attention_items(import_sources, qc_groups, (), ()),
    )


def test_qc_attention_groups_are_counted_sorted_and_localized() -> None:
    summary = _qc_attention_summary()
    english = render_administrator_summary_email(summary, "en")
    spanish = render_administrator_summary_email(summary, "es")

    assert summary.attention_item_count == 3
    assert [item.attention_code for item in summary.attention_items] == [
        "qc_marked_invalid",
        "qc_flagged_for_review",
        "qc_flagged_for_review",
    ]
    assert english.subject.endswith("3 issues need attention")
    assert "3 issues need attention" in english.text_body
    assert (
        "29 PM2.5 measurements at LQA PUC RIO were marked invalid by the Maximum plausible value "
        "because they exceeded the 0 µg/m³ maximum."
        in english.text_body
    )
    assert (
        "30 PM2.5 measurements at Calzada, Taguig were flagged for review by the "
        "Baseline drift because the observed drift exceeded the configured maximum "
        "of 0 µg/m³/day in both directions. They were not marked invalid."
        in english.text_body
    )
    assert (
        "15 PM2.5 measurements at UAlbany – Queens College (DEC) were flagged for review by the "
        "Minimum plausible value because they were below the 100 µg/m³ minimum. They were not marked invalid."
        in english.text_body
    )
    assert english.text_body.index("marked invalid by the Maximum plausible value") < english.text_body.index(
        "flagged for review by the Baseline drift"
    )
    assert "(minimum:" not in english.text_body
    assert "(maximum:" not in english.text_body
    assert "Minimum plausible value" in english.text_body
    assert "Maximum plausible value" in english.text_body
    assert "Baseline drift" in english.text_body
    assert "Maximum plausible value" in spanish.text_body
    assert "Baseline drift" in spanish.text_body
    assert "Minimum plausible value" in spanish.text_body
    assert "No se marcaron como no válidas." in spanish.text_body
    assert "(mínimo:" not in spanish.text_body
    assert "(máximo:" not in spanish.text_body


def test_qc_activity_is_rendered_once_under_needs_attention() -> None:
    rendered = render_administrator_summary_email(_qc_attention_summary(), "en")

    assert rendered.text_body.count("Minimum plausible value") == 1
    assert rendered.html_body.count("Minimum plausible value") == 1
    assert "QC activity" not in rendered.text_body
    assert "QC activity" not in rendered.html_body
    assert rendered.text_body.index("NEEDS ATTENTION") < rendered.text_body.index(
        "DATA IMPORTS"
    )


def test_mark_invalid_copy_does_not_claim_that_measurements_were_not_invalid() -> None:
    attention = AttentionItem(
        attention_code="qc_marked_invalid",
        count=3,
        source_name="OpenAQ",
        device_name="LQA PUC RIO",
        parameter_name="PM2.5",
        check_code="max_value",
        check_name="Max Value QC Check",
        effective_threshold=0,
        effective_unit_symbol="µg/m³",
    )
    summary = AdministratorSummary(
        reporting_window=_window(AdministratorSummaryCadence.EVERY_15_MINUTES),
        generated_at_utc=datetime(2026, 8, 22, 15, tzinfo=UTC),
        attention_items=(attention,),
    )

    english = render_administrator_summary_email(summary, "en")
    spanish = render_administrator_summary_email(summary, "es")

    assert (
        "3 PM2.5 measurements at LQA PUC RIO were marked invalid by the Max Value QC Check "
        "because they exceeded the 0 µg/m³ maximum."
    ) in english.text_body
    assert "not marked invalid" not in english.text_body
    assert "No se marcaron como no válidas" not in spanish.text_body


def test_reporting_period_contains_local_timezone_and_not_a_redundant_raw_timezone_line() -> None:
    reporting_window = calculate_completed_reporting_window(
        datetime(2026, 8, 27, 7, 30, tzinfo=UTC),
        AdministratorSummaryCadence.EVERY_15_MINUTES,
        "America/Los_Angeles",
    )
    summary = AdministratorSummary(
        reporting_window=reporting_window,
        generated_at_utc=datetime(2026, 8, 27, 7, 31, tzinfo=UTC),
        environment_label="Development",
    )

    english = render_administrator_summary_email(summary, "en")
    spanish = render_administrator_summary_email(summary, "es")

    assert "Reporting period: August 27, 2026, 12:15–12:30 AM PDT" in english.text_body
    assert "Reporting timezone:" not in english.text_body
    assert "Environment: Development" in english.text_body
    assert "Período del informe: 27 de agosto de 2026, 12:15–12:30 a. m. PDT" in spanish.text_body
    assert "Zona horaria del informe:" not in spanish.text_body
    assert "Entorno: Development" in spanish.text_body


@pytest.mark.parametrize(
    ("reference_time", "expected_period"),
    [
        (
            datetime(2026, 3, 8, 10, 0, tzinfo=UTC),
            "Reporting period: March 8, 2026, 1:45 AM PST–3:00 AM PDT",
        ),
        (
            datetime(2026, 11, 1, 9, 0, tzinfo=UTC),
            "Reporting period: November 1, 2026, 1:45 AM PDT–1:00 AM PST",
        ),
    ],
)
def test_reporting_period_preserves_dst_timezone_abbreviations(
    reference_time: datetime,
    expected_period: str,
) -> None:
    reporting_window = calculate_completed_reporting_window(
        reference_time,
        AdministratorSummaryCadence.EVERY_15_MINUTES,
        "America/Los_Angeles",
    )
    summary = AdministratorSummary(
        reporting_window=reporting_window,
        generated_at_utc=reference_time,
    )

    rendered = render_administrator_summary_email(summary, "en")

    assert expected_period in rendered.text_body


@pytest.mark.parametrize(
    ("status_code", "english_label", "spanish_label"),
    [
        ("success", "Success", "Correcto"),
        ("failed", "Failed", "Fallido"),
        ("interrupted", "Interrupted", "Interrumpido"),
        ("timed_out", "Timed out", "Tiempo agotado"),
        ("no_scheduled_run", "No scheduled run", "Sin ejecución programada"),
        (
            "not_scheduled_this_period",
            "Not scheduled this period",
            "No programada durante este período",
        ),
    ],
)
def test_import_table_uses_one_localized_job_status(
    status_code: str,
    english_label: str,
    spanish_label: str,
) -> None:
    source = ImportSourceSummary(
        source_code="openaq",
        source_name="OpenAQ",
        job_count=0
        if status_code in {"no_scheduled_run", "not_scheduled_this_period"}
        else 1,
        successful_job_count=0,
        failed_job_count=0,
        timed_out_job_count=0,
        running_job_count=0,
        skipped_job_count=0,
        measurements_received=0,
        measurements_inserted=0,
        measurements_updated=0,
        measurements_skipped=0,
        scheduled_job_count=0
        if status_code in {"no_scheduled_run", "not_scheduled_this_period"}
        else 1,
        scheduled_job_status_code=status_code,
    )
    summary = AdministratorSummary(
        reporting_window=_window(),
        generated_at_utc=datetime(2026, 8, 22, 15, tzinfo=UTC),
        import_sources=(source,),
    )

    english = render_administrator_summary_email(summary, "en")
    spanish = render_administrator_summary_email(summary, "es")

    assert f"Job Status: {english_label}" in english.text_body
    assert english_label in english.html_body
    expected_counter = "—" if status_code == "not_scheduled_this_period" else "0"
    assert f"Received: {expected_counter}" in english.text_body
    assert f"Estado del trabajo: {spanish_label}" in spanish.text_body
    expected_spanish_counter = "—" if status_code == "not_scheduled_this_period" else "0"
    assert f"Recibidos: {expected_spanish_counter}" in spanish.text_body
    assert spanish_label in spanish.html_body
    headers = re.findall(r"<th(?:\s[^>]*)?>(.*?)</th>", english.html_body)
    assert headers == ["Source", "Job Status", "Received", "Inserted", "Updated", "Skipped"]
    assert "class=\"imports-table\"" in english.html_body
    assert "@media only screen and (max-width:520px)" in english.html_body
    assert 'data-label="Job Status"' in english.html_body


def test_successful_import_with_qc_attention_still_has_success_job_status() -> None:
    rendered = render_administrator_summary_email(_qc_attention_summary(), "en")

    assert "Job Status: Success" in rendered.text_body
    assert rendered.html_body.count(">Success</td>") == 3
    assert "Maximum plausible value" in rendered.html_body
    assert "flagged for review" in rendered.html_body
    assert "QC activity" not in rendered.text_body
    assert "QC activity" not in rendered.html_body


def test_one_actionable_qc_group_uses_singular_attention_copy() -> None:
    group = QcActivityGroup(
        source_name="OpenAQ",
        device_name="Single attention site",
        parameter_name="PM2.5",
        check_code="min_value",
        check_name="Minimum plausible value",
        outcome=QcDigestOutcome.FLAGGED_FOR_REVIEW,
        reason_code=None,
        result_count=1,
        measurement_count=1,
        effective_threshold=100,
        effective_unit_symbol="µg/m³",
    )
    summary = AdministratorSummary(
        reporting_window=_window(),
        generated_at_utc=datetime(2026, 8, 22, 15, tzinfo=UTC),
        qc_activity=(group,),
        attention_items=derive_attention_items((), (group,), (), ()),
    )

    english = render_administrator_summary_email(summary, "en")
    spanish = render_administrator_summary_email(summary, "es")

    assert "1 issue needs attention" in english.subject
    assert "1 issues need attention" not in english.subject
    assert "1 problema requiere atención" in spanish.subject
    assert (
        "1 PM2.5 measurement at Single attention site was flagged for review by the "
        "Minimum plausible value because it was below the 100 µg/m³ minimum. "
        "It was not marked invalid."
    ) in english.text_body
    assert (
        "1 medición de PM2.5 en Single attention site se marcó para revisión mediante la "
        "Minimum plausible value porque estaba por debajo del mínimo de 100 µg/m³. "
        "No se marcó como no válida."
    ) in spanish.text_body


def test_singular_interrupted_import_uses_singular_copy_in_both_languages() -> None:
    attention = AttentionItem(
        attention_code="import_jobs_interrupted",
        count=1,
        source_name="OpenAQ",
    )
    summary = AdministratorSummary(
        reporting_window=_window(),
        generated_at_utc=datetime(2026, 8, 22, 15, tzinfo=UTC),
        attention_items=(attention,),
    )

    english = render_administrator_summary_email(summary, "en")
    spanish = render_administrator_summary_email(summary, "es")

    assert "OpenAQ: 1 import job was interrupted by stale-run recovery." in english.text_body
    assert "OpenAQ: 1 trabajo de importación fue interrumpido por la recuperación de ejecuciones obsoletas." in spanish.text_body


def test_import_explanation_and_environment_are_in_both_renderings() -> None:
    rendered_english = render_administrator_summary_email(_all_good_summary(), "en")
    rendered_spanish = render_administrator_summary_email(_all_good_summary(), "es")

    assert "Environment: Development" in rendered_english.text_body
    assert "Environment:</strong> Development" in rendered_english.html_body
    assert (
        "Skipped counts received measurements that the importer did not insert"
        in rendered_english.text_body
    )
    assert "Entorno: Development" in rendered_spanish.text_body
    assert "Omitidos cuenta las mediciones recibidas" in rendered_spanish.text_body


def test_html_escapes_all_database_derived_labels() -> None:
    rendered = render_administrator_summary_email(_attention_summary(), "en")

    assert "<script>" not in rendered.html_body
    assert "&lt;script&gt;" in rendered.html_body
    assert "onerror=" not in rendered.html_body


def test_subject_removes_control_characters_from_environment_label() -> None:
    base = _all_good_summary()
    summary = AdministratorSummary(
        reporting_window=base.reporting_window,
        generated_at_utc=base.generated_at_utc,
        environment_label="Development\r\nBcc: outsider@example.com",
    )

    rendered = render_administrator_summary_email(summary, "en")

    assert "\r" not in rendered.subject
    assert "\n" not in rendered.subject
    assert rendered.subject.startswith(
        "[CompassAQ Development Bcc: outsider@example.com]"
    )


def test_renderer_is_pure_and_has_no_database_imports() -> None:
    source = inspect.getsource(administrator_summary_renderer)

    assert "sqlalchemy" not in source
    assert "from models" not in source
    assert "Session" not in source


def test_unsupported_language_is_rejected() -> None:
    with pytest.raises(ValueError, match="language"):
        render_administrator_summary_email(_all_good_summary(), "fr")
