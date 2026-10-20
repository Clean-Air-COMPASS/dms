"""Pure English/Spanish rendering for structured administrator summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Final, Literal

from services.administrator_summary_domain import (
    AdministratorSummary,
    AdministratorSummaryCadence,
    AttentionItem,
    EventDigestGroup,
    ImportSourceSummary,
    NOT_SCHEDULED_THIS_PERIOD_STATUS,
    qc_check_display_name,
)


SummaryLanguageCode = Literal["en", "es"]


@dataclass(frozen=True)
class RenderedAdministratorSummaryEmail:
    subject: str
    text_body: str
    html_body: str


MONTHS: Final[dict[SummaryLanguageCode, tuple[str, ...]]] = {
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
    "es": (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ),
}
SHORT_MONTHS: Final[dict[SummaryLanguageCode, tuple[str, ...]]] = {
    "en": (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ),
    "es": (
        "ene", "feb", "mar", "abr", "may", "jun",
        "jul", "ago", "sept", "oct", "nov", "dic",
    ),
}


TEXT: Final[dict[SummaryLanguageCode, dict[str, str]]] = {
    "en": {
        "title": "CompassAQ Administrator Summary",
        "reporting_period": "Reporting period",
        "generated": "Generated",
        "status": "Status",
        "normal": "All systems normal",
        "attention": "{count} issues need attention",
        "attention_one": "1 issue needs attention",
        "needs_attention": "Needs attention",
        "imports": "Data imports",
        "events": "System events",
        "source": "Source",
        "job_status": "Job Status",
        "received": "Received",
        "inserted": "Inserted",
        "updated": "Updated",
        "skipped": "Skipped",
        "skipped_note": (
            "Skipped counts received measurements that the importer did not "
            "insert, including duplicates or other non-insertable records."
        ),
        "no_imports": "No importer jobs ran during this reporting period.",
        "no_events": "No additional significant system events were recorded.",
        "qc_truncated": "Additional QC groups are available in the database.",
        "events_truncated": "Additional event groups are available in Admin Events.",
        "footer": "Detailed information is available in Admin Events and Job Runs.",
        "environment": "Environment",
    },
    "es": {
        "title": "Resumen para administradores de CompassAQ",
        "reporting_period": "Período del informe",
        "generated": "Generado",
        "status": "Estado",
        "normal": "Todos los sistemas normales",
        "attention": "{count} problemas requieren atención",
        "attention_one": "1 problema requiere atención",
        "needs_attention": "Requiere atención",
        "imports": "Importaciones de datos",
        "events": "Eventos del sistema",
        "source": "Fuente",
        "job_status": "Estado del trabajo",
        "received": "Recibidos",
        "inserted": "Insertados",
        "updated": "Actualizados",
        "skipped": "Omitidos",
        "skipped_note": (
            "Omitidos cuenta las mediciones recibidas que el importador no "
            "insertó, como duplicados u otros registros no insertables."
        ),
        "no_imports": "No se ejecutaron trabajos de importación durante este período.",
        "no_events": "No se registraron otros eventos significativos del sistema.",
        "qc_truncated": "Hay otros grupos de control de calidad disponibles en la base de datos.",
        "events_truncated": "Hay otros grupos de eventos disponibles en Eventos de administración.",
        "footer": "La información detallada está disponible en Eventos y Trabajos de administración.",
        "environment": "Entorno",
    },
}


IMPORT_JOB_STATUS_LABELS: Final[dict[SummaryLanguageCode, dict[str, str]]] = {
    "en": {
        "success": "Success",
        "failed": "Failed",
        "interrupted": "Interrupted",
        "timed_out": "Timed out",
        "running": "Running",
        "skipped": "Skipped",
        "not_scheduled_this_period": "Not scheduled this period",
        "no_scheduled_run": "No scheduled run",
        "unknown": "Unknown",
    },
    "es": {
        "success": "Correcto",
        "failed": "Fallido",
        "interrupted": "Interrumpido",
        "timed_out": "Tiempo agotado",
        "running": "En curso",
        "skipped": "Omitido",
        "not_scheduled_this_period": "No programada durante este período",
        "no_scheduled_run": "Sin ejecución programada",
        "unknown": "Desconocido",
    },
}


EVENT_LABELS: Final[dict[SummaryLanguageCode, dict[str, str]]] = {
    "en": {
        "reference_location_failed": "reference location could not be loaded",
        "source_configuration_error": "source configuration problem",
        "source_fetch_error": "source fetch problem",
        "source_device_error": "device configuration problem",
        "source_rate_limited": "provider rate limit",
        "source_measurement_error": "measurement import problem",
        "source_measurement_validation_failed": "measurement response validation problem",
        "system_error": "system error",
    },
    "es": {
        "reference_location_failed": "no se pudo cargar una ubicación de referencia",
        "source_configuration_error": "problema de configuración de la fuente",
        "source_fetch_error": "problema al consultar la fuente",
        "source_device_error": "problema de configuración del dispositivo",
        "source_rate_limited": "límite de solicitudes del proveedor",
        "source_measurement_error": "problema al importar mediciones",
        "source_measurement_validation_failed": "problema al validar la respuesta de mediciones",
        "system_error": "error del sistema",
    },
}


QC_REASON_LABELS: Final[dict[SummaryLanguageCode, dict[str, str]]] = {
    "en": {
        "invalid_measurement_value": "the measurement value was not numeric",
        "invalid_plugin_result": "the QC check returned an invalid result",
        "missing_effective_policy": "the effective QC policy was unavailable",
        "missing_required_setting": "a required QC setting is missing",
        "plugin_error": "the QC check reported an error",
        "plugin_unavailable": "the QC check was unavailable",
        "policy_unavailable": "the effective QC policy was unavailable",
        "unknown_unit": "the evaluation unit could not be resolved",
        "conversion_not_supported": "the unit conversion is not supported",
    },
    "es": {
        "invalid_measurement_value": "el valor de la medición no era numérico",
        "invalid_plugin_result": "el control de calidad devolvió un resultado no válido",
        "missing_effective_policy": "la política de control de calidad efectiva no estaba disponible",
        "missing_required_setting": "falta una configuración necesaria del control de calidad",
        "plugin_error": "el control de calidad informó un error",
        "plugin_unavailable": "el control de calidad no estaba disponible",
        "policy_unavailable": "la política de control de calidad efectiva no estaba disponible",
        "unknown_unit": "no se pudo resolver la unidad de evaluación",
        "conversion_not_supported": "la conversión de unidades no es compatible",
    },
}


def _validate_language(language_code: str) -> SummaryLanguageCode:
    if language_code not in {"en", "es"}:
        raise ValueError("Administrator summary language must be 'en' or 'es'")
    return language_code  # type: ignore[return-value]


def _long_date(value: datetime, language: SummaryLanguageCode) -> str:
    month = MONTHS[language][value.month - 1]
    if language == "es":
        return f"{value.day} de {month} de {value.year}"
    return f"{month} {value.day}, {value.year}"


def _short_date(value: datetime, language: SummaryLanguageCode) -> str:
    month = SHORT_MONTHS[language][value.month - 1]
    return f"{value.day} {month}" if language == "es" else f"{month} {value.day}"


def _clock(value: datetime) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _display_clock(value: datetime) -> str:
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d}"


def _meridiem(value: datetime, language: SummaryLanguageCode) -> str:
    if language == "es":
        return "a. m." if value.hour < 12 else "p. m."
    return "AM" if value.hour < 12 else "PM"


def _period_clock_label(
    start: datetime,
    end: datetime,
    language: SummaryLanguageCode,
) -> str:
    start_meridiem = _meridiem(start, language)
    end_meridiem = _meridiem(end, language)
    if start_meridiem == end_meridiem:
        return f"{_display_clock(start)}–{_display_clock(end)} {end_meridiem}"
    return (
        f"{_display_clock(start)} {start_meridiem}–"
        f"{_display_clock(end)} {end_meridiem}"
    )


def _period_zone_label(
    start: datetime,
    end: datetime,
    reporting_timezone: str,
) -> tuple[str, str]:
    return (
        start.tzname() or reporting_timezone,
        end.tzname() or reporting_timezone,
    )


def _period_label(summary: AdministratorSummary, language: SummaryLanguageCode) -> str:
    window = summary.reporting_window
    start = window.period_start_local
    end = window.period_end_local
    start_zone, end_zone = _period_zone_label(
        start,
        end,
        window.reporting_timezone,
    )
    if window.cadence is AdministratorSummaryCadence.DAILY:
        date_label = _long_date(start, language)
        if start_zone == end_zone:
            return f"{date_label} {start_zone}"
        return f"{date_label} {start_zone}–{end_zone}"

    if start.date() == end.date():
        date_label = _long_date(start, language)
        if start_zone == end_zone:
            return (
                f"{date_label}, {_period_clock_label(start, end, language)} "
                f"{start_zone}"
            )
        return (
            f"{date_label}, {_display_clock(start)} {_meridiem(start, language)} "
            f"{start_zone}–{_display_clock(end)} {_meridiem(end, language)} "
            f"{end_zone}"
        )
    return (
        f"{_long_date(start, language)}, {_display_clock(start)} "
        f"{_meridiem(start, language)} {start_zone}–"
        f"{_long_date(end, language)}, {_display_clock(end)} "
        f"{_meridiem(end, language)} {end_zone}"
    )


def _subject_period(summary: AdministratorSummary, language: SummaryLanguageCode) -> str:
    window = summary.reporting_window
    if window.cadence is AdministratorSummaryCadence.DAILY:
        return _short_date(window.period_start_local, language)
    return (
        f"{_short_date(window.period_start_local, language)} "
        f"{_clock(window.period_start_local)}–{_clock(window.period_end_local)}"
    )


def _clean_subject_component(value: str) -> str:
    cleaned = "".join(
        " " if ord(character) < 32 or ord(character) == 127 else character
        for character in value
    )
    return " ".join(cleaned.split())


def _status_label(summary: AdministratorSummary, language: SummaryLanguageCode) -> str:
    if not summary.attention_items:
        return TEXT[language]["normal"]
    if summary.attention_item_count == 1:
        return TEXT[language]["attention_one"]
    return TEXT[language]["attention"].format(count=summary.attention_item_count)


def generate_administrator_summary_subject(
    summary: AdministratorSummary,
    language_code: str,
) -> str:
    language = _validate_language(language_code)
    environment = _clean_subject_component(summary.environment_label or "")
    prefix = f"CompassAQ {environment}" if environment else "CompassAQ"
    summary_word = "Summary" if language == "en" else "Resumen"
    return (
        f"[{prefix}] {summary_word} — {_subject_period(summary, language)} — "
        f"{_status_label(summary, language)}"
    )


def _indeterminate_reason_clause(
    reason_code: str | None,
    language: SummaryLanguageCode,
) -> str:
    fallback = (
        "el resultado del control de calidad no estaba disponible"
        if language == "es"
        else "the QC result was unavailable"
    )
    reason = QC_REASON_LABELS[language].get(reason_code or "", fallback)
    prefix = "porque" if language == "es" else "because"
    return f"{prefix} {reason}"


def _qc_failure_reason_clause(
    item: AttentionItem,
    language: SummaryLanguageCode,
) -> str:
    threshold = (
        _format_qc_number(item.effective_threshold)
        if item.effective_threshold is not None
        else None
    )
    unit = f" {item.effective_unit_symbol}" if item.effective_unit_symbol else ""
    is_singular = item.count == 1

    if item.check_code == "min_value":
        if threshold is None:
            return (
                "porque el umbral mínimo efectivo no estaba disponible"
                if language == "es"
                else "because the effective minimum threshold was unavailable"
            )
        if language == "es":
            verb = "estaba" if is_singular else "estaban"
            return f"porque {verb} por debajo del mínimo de {threshold}{unit}"
        verb = "was" if is_singular else "were"
        pronoun = "it" if is_singular else "they"
        return f"because {pronoun} {verb} below the {threshold}{unit} minimum"

    if item.check_code == "max_value":
        if threshold is None:
            return (
                "porque el umbral máximo efectivo no estaba disponible"
                if language == "es"
                else "because the effective maximum threshold was unavailable"
            )
        if language == "es":
            verb = "excedió" if is_singular else "excedieron"
            return f"porque {verb} el máximo de {threshold}{unit}"
        verb = "exceeded"
        pronoun = "it" if is_singular else "they"
        return f"because {pronoun} {verb} the {threshold}{unit} maximum"

    if (
        item.check_code == "baseline_drift"
        and item.effective_max_drift_per_day is not None
    ):
        limit = _format_qc_number(item.effective_max_drift_per_day)
        if language == "es":
            rate = (
                f"{limit} {item.effective_unit_symbol}/día"
                if item.effective_unit_symbol
                else f"{limit} por día"
            )
            direction = {
                "up": " en dirección ascendente",
                "down": " en dirección descendente",
                "both": " en ambas direcciones",
            }.get(item.effective_drift_direction or "", "")
            return (
                f"porque la deriva observada superó el máximo configurado de "
                f"{rate}{direction}"
            )
        rate = (
            f"{limit} {item.effective_unit_symbol}/day"
            if item.effective_unit_symbol
            else f"{limit} per day"
        )
        direction = {
            "up": " in the upward direction",
            "down": " in the downward direction",
            "both": " in both directions",
        }.get(item.effective_drift_direction or "", "")
        return (
            f"because the observed drift exceeded the configured maximum of "
            f"{rate}{direction}"
        )

    if item.check_code == "baseline_drift":
        return (
            "porque la configuración del máximo de deriva no estaba disponible"
            if language == "es"
            else "because the configured maximum drift setting was unavailable"
        )
    return (
        "porque el motivo del fallo del control de calidad no estaba disponible"
        if language == "es"
        else "because the QC failure reason was unavailable"
    )


def _qc_consequence_text(item: AttentionItem, language: SummaryLanguageCode) -> str:
    if language == "es":
        if item.count == 1:
            return "No se marcó como no válida."
        return "No se marcaron como no válidas."
    return "It was not marked invalid." if item.count == 1 else "They were not marked invalid."


def _format_storage_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    amount = float(value)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if amount < 1024 or candidate == units[-1]:
            break
        amount /= 1024
    return f"{amount:.1f} {unit}" if amount < 100 else f"{amount:.0f} {unit}"


def _attention_text(item: AttentionItem, language: SummaryLanguageCode) -> str:
    source = item.source_name or ("CompassAQ" if language == "en" else "CompassAQ")
    device = f" — {item.device_name}" if item.device_name else ""
    check_name = qc_check_display_name(
        item.check_code,
        language,
        fallback=item.check_name,
    )
    if item.attention_code == "storage_low":
        free_space = _format_storage_bytes(item.free_bytes)
        percent_free = f"{item.percent_free:.1f}%" if item.percent_free is not None else "unknown"
        if language == "es":
            severity = "críticamente bajo" if item.storage_status == "critical" else "bajo"
            return f"El espacio de almacenamiento es {severity}: quedan {free_space} ({percent_free})."
        severity = "critically low" if item.storage_status == "critical" else "running low"
        return f"Storage is {severity}: {free_space} ({percent_free}) remains."
    if language == "es":
        measurement_label = "medición" if item.count == 1 else "mediciones"
        evaluation_label = "evaluación" if item.count == 1 else "evaluaciones"
        import_job_label = (
            "trabajo de importación"
            if item.count == 1
            else "trabajos de importación"
        )
        marked_verb = "se marcó" if item.count == 1 else "se marcaron"
        unable_verb = "no pudo completarse" if item.count == 1 else "no pudieron completarse"
        if item.attention_code == "import_jobs_failed":
            if not item.successful_job_count:
                failed_verb = "falló" if item.count == 1 else "fallaron"
                return (
                    f"{source}: {item.count} {import_job_label} {failed_verb} "
                    "y ninguno fue correcto."
                )
            failed_verb = "falló" if item.count == 1 else "fallaron"
            successful_verb = (
                "fue correcto"
                if item.successful_job_count == 1
                else "fueron correctos"
            )
            return (
                f"{source}: {item.count} {import_job_label} {failed_verb}; "
                f"{item.successful_job_count} {successful_verb}."
            )
        if item.attention_code == "import_jobs_interrupted":
            interrupted_verb = (
                "fue interrumpido"
                if item.count == 1
                else "fueron interrumpidos"
            )
            return (
                f"{source}: {item.count} {import_job_label} {interrupted_verb} "
                "por la recuperación de ejecuciones obsoletas."
            )
        if item.attention_code == "scheduled_import_missing":
            return (
                f"{source}: no se ejecutó ninguna importación programada "
                "durante este período."
            )
        if item.attention_code == "qc_marked_invalid":
            return (
                f"{item.count} {measurement_label} de {item.parameter_name} en {item.device_name} "
                f"{marked_verb} como no válida{'s' if item.count != 1 else ''} mediante la {check_name}"
                f" {_qc_failure_reason_clause(item, language)}."
            )
        if item.attention_code == "qc_flagged_for_review":
            return (
                f"{item.count} {measurement_label} de {item.parameter_name} en {item.device_name} "
                f"{marked_verb} para revisión mediante la {check_name} "
                f"{_qc_failure_reason_clause(item, language)}. "
                f"{_qc_consequence_text(item, language)}"
            )
        if item.attention_code == "qc_indeterminate":
            return (
                f"{item.count} {evaluation_label} de CC de {item.parameter_name} en {item.device_name} "
                f"{unable_verb} mediante la {check_name} "
                f"{_indeterminate_reason_clause(item.reason_code, language)}."
            )
        if item.attention_code == "system_error":
            error_label = "error del sistema" if item.count == 1 else "errores del sistema"
            return f"CompassAQ registró {item.count} {error_label}{device}."
        label = EVENT_LABELS[language].get(item.attention_code, "problema operativo")
        event_label = "evento" if item.count == 1 else "eventos"
        return f"{source}: {item.count} {event_label} de {label}{device}."

    if item.attention_code == "import_jobs_failed":
        import_job_label = "import job" if item.count == 1 else "import jobs"
        if not item.successful_job_count:
            return (
                f"{source}: {item.count} {import_job_label} failed and no import job "
                "succeeded."
            )
        return (
            f"{source}: {item.count} {import_job_label} failed; "
            f"{item.successful_job_count} succeeded."
        )
    if item.attention_code == "import_jobs_interrupted":
        import_job_label = "import job" if item.count == 1 else "import jobs"
        interrupted_verb = "was interrupted" if item.count == 1 else "were interrupted"
        return (
            f"{source}: {item.count} {import_job_label} {interrupted_verb} by stale-run "
            "recovery."
        )
    if item.attention_code == "scheduled_import_missing":
        return f"{source}: no scheduled import ran during this reporting period."
    measurement_label = "measurement" if item.count == 1 else "measurements"
    evaluation_label = "evaluation" if item.count == 1 else "evaluations"
    past_verb = "was" if item.count == 1 else "were"
    if item.attention_code == "qc_marked_invalid":
        return (
            f"{item.count} {item.parameter_name} {measurement_label} at {item.device_name} "
            f"{past_verb} marked invalid by the {check_name}"
            f" {_qc_failure_reason_clause(item, language)}."
        )
    if item.attention_code == "qc_flagged_for_review":
        return (
            f"{item.count} {item.parameter_name} {measurement_label} at {item.device_name} "
            f"{past_verb} flagged for review by the {check_name} "
            f"{_qc_failure_reason_clause(item, language)}. "
            f"{_qc_consequence_text(item, language)}"
        )
    if item.attention_code == "qc_indeterminate":
        return (
            f"{item.count} {item.parameter_name} QC {evaluation_label} at {item.device_name} "
            f"could not be completed by the {check_name} "
            f"{_indeterminate_reason_clause(item.reason_code, language)}."
        )
    if item.attention_code == "system_error":
        error_label = "system error" if item.count == 1 else "system errors"
        return f"CompassAQ recorded {item.count} {error_label}{device}."
    label = EVENT_LABELS[language].get(item.attention_code, "operational problem")
    event_label = "event" if item.count == 1 else "events"
    return f"{source}: {item.count} {label} {event_label}{device}."


def _format_qc_number(value: float) -> str:
    numeric_value = float(value)
    if numeric_value == 0:
        return "0"
    if numeric_value.is_integer():
        return str(int(numeric_value))
    return format(numeric_value, ".6g")


def _event_text(group: EventDigestGroup, language: SummaryLanguageCode) -> str:
    label = EVENT_LABELS[language].get(
        group.digest_code,
        "operational problem" if language == "en" else "problema operativo",
    )
    device = f" — {group.device_name}" if group.device_name else ""
    if language == "es":
        event_label = "evento" if group.event_count == 1 else "eventos"
        return f"{group.source_name}: {group.event_count} {event_label} de {label}{device}."
    event_label = "event" if group.event_count == 1 else "events"
    return f"{group.source_name}: {group.event_count} {label} {event_label}{device}."


def _import_text(
    source: ImportSourceSummary,
    language: SummaryLanguageCode,
) -> str:
    copy = TEXT[language]
    counter_values = _import_counter_values(source)
    return (
        f"{source.source_name}: {copy['job_status']}: "
        f"{_import_job_status_text(source, language)}; "
        f"{copy['received']}: {counter_values['received']}; "
        f"{copy['inserted']}: {counter_values['inserted']}; "
        f"{copy['updated']}: {counter_values['updated']}; "
        f"{copy['skipped']}: {counter_values['skipped']}"
    )


def _import_counter_values(source: ImportSourceSummary) -> dict[str, int | str]:
    if (
        source.job_status_code == NOT_SCHEDULED_THIS_PERIOD_STATUS
        and source.scheduled_job_count == 0
    ):
        return {
            "received": "—",
            "inserted": "—",
            "updated": "—",
            "skipped": "—",
        }
    return {
        "received": source.measurements_received,
        "inserted": source.measurements_inserted,
        "updated": source.measurements_updated,
        "skipped": source.measurements_skipped,
    }


def _import_row_html(
    source: ImportSourceSummary,
    copy: dict[str, str],
    language: SummaryLanguageCode,
) -> str:
    counters = _import_counter_values(source)
    return (
        "<tr>"
        f"<td data-label=\"{_html_text(copy['source'])}\" style=\"padding:8px;border-bottom:1px solid #e2e8f0;text-align:left\">{_html_text(source.source_name)}</td>"
        f"<td data-label=\"{_html_text(copy['job_status'])}\" style=\"padding:8px;border-bottom:1px solid #e2e8f0;text-align:left;word-break:break-word\">{_html_text(_import_job_status_text(source, language))}</td>"
        f"<td data-label=\"{_html_text(copy['received'])}\" style=\"padding:8px;border-bottom:1px solid #e2e8f0;text-align:right\">{_html_text(counters['received'])}</td>"
        f"<td data-label=\"{_html_text(copy['inserted'])}\" style=\"padding:8px;border-bottom:1px solid #e2e8f0;text-align:right\">{_html_text(counters['inserted'])}</td>"
        f"<td data-label=\"{_html_text(copy['updated'])}\" style=\"padding:8px;border-bottom:1px solid #e2e8f0;text-align:right\">{_html_text(counters['updated'])}</td>"
        f"<td data-label=\"{_html_text(copy['skipped'])}\" style=\"padding:8px;border-bottom:1px solid #e2e8f0;text-align:right\">{_html_text(counters['skipped'])}</td>"
        "</tr>"
    )


def _import_job_status_text(
    source: ImportSourceSummary,
    language: SummaryLanguageCode,
) -> str:
    labels = IMPORT_JOB_STATUS_LABELS[language]
    return labels.get(source.job_status_code, labels["unknown"])


def render_administrator_summary_text(
    summary: AdministratorSummary,
    language_code: str,
) -> str:
    language = _validate_language(language_code)
    copy = TEXT[language]
    lines = [
        copy["title"].upper(),
        f"{copy['reporting_period']}: {_period_label(summary, language)}",
    ]
    if summary.environment_label:
        lines.append(f"{copy['environment']}: {summary.environment_label}")
    lines.extend(("", f"{copy['status'].upper()}: {_status_label(summary, language)}"))

    if summary.attention_items:
        lines.extend(("", copy["needs_attention"].upper()))
        lines.extend(
            f"{index}. {_attention_text(item, language)}"
            for index, item in enumerate(summary.attention_items, start=1)
        )
        if summary.qc_groups_truncated:
            lines.append(copy["qc_truncated"])
    elif summary.qc_groups_truncated:
        lines.extend(("", copy["needs_attention"].upper(), copy["qc_truncated"]))

    lines.extend(("", copy["imports"].upper()))
    if summary.import_sources:
        lines.extend(_import_text(source, language) for source in summary.import_sources)
        lines.append(copy["skipped_note"])
    else:
        lines.append(copy["no_imports"])
    lines.extend(f"- {_event_text(group, language)}" for group in summary.import_events)

    lines.extend(("", copy["events"].upper()))
    if summary.system_events:
        lines.extend(f"- {_event_text(group, language)}" for group in summary.system_events)
    else:
        lines.append(copy["no_events"])
    if summary.event_groups_truncated:
        lines.append(copy["events_truncated"])

    generated_local = summary.generated_at_utc.astimezone(
        summary.reporting_window.period_end_local.tzinfo
    )
    lines.extend(
        (
            "",
            "CompassAQ",
            f"{copy['generated']}: {_long_date(generated_local, language)} {_clock(generated_local)} {generated_local.tzname() or ''}".rstrip(),
            copy["footer"],
        )
    )
    return "\n".join(lines) + "\n"


def _html_text(value: object) -> str:
    return escape(str(value), quote=True)


def _html_list(items: list[str]) -> str:
    return "<ul style=\"margin:8px 0 0;padding-left:22px\">" + "".join(
        f"<li style=\"margin:0 0 8px\">{_html_text(item)}</li>" for item in items
    ) + "</ul>"


def render_administrator_summary_html(
    summary: AdministratorSummary,
    language_code: str,
) -> str:
    language = _validate_language(language_code)
    copy = TEXT[language]
    attention = bool(summary.attention_items)
    status_background = "#fff8e7" if attention else "#eaf8f0"
    status_border = "#d48a1f" if attention else "#2f8f5b"
    status_color = "#7a4308" if attention else "#17643a"

    metadata = (
        f"<p style=\"margin:4px 0;color:#536174\"><strong>{_html_text(copy['reporting_period'])}:</strong> "
        f"{_html_text(_period_label(summary, language))}</p>"
    )
    if summary.environment_label:
        metadata += (
            f"<p style=\"margin:4px 0;color:#536174\"><strong>{_html_text(copy['environment'])}:</strong> "
            f"{_html_text(summary.environment_label)}</p>"
        )

    attention_html = ""
    if summary.attention_items:
        attention_html = (
            f"<h2 style=\"margin:24px 0 8px;font-size:20px;color:#172033\">{_html_text(copy['needs_attention'])}</h2>"
            + _html_list(
                [_attention_text(item, language) for item in summary.attention_items]
            )
        )
        if summary.qc_groups_truncated:
            attention_html += (
                f"<p style=\"color:#64748b\">{_html_text(copy['qc_truncated'])}</p>"
            )

    if summary.import_sources:
        import_rows = "".join(
            _import_row_html(source, copy, language)
            for source in summary.import_sources
        )
        headers = ("source", "job_status", "received", "inserted", "updated", "skipped")
        header_cells = "".join(
            f"<th style=\"padding:8px;border-bottom:2px solid #cbd5e1;text-align:{'left' if key in {'source', 'job_status'} else 'right'};font-size:12px;color:#475569;word-break:break-word\">{_html_text(copy[key])}</th>"
            for key in headers
        )
        imports_html = (
            "<div style=\"max-width:100%;overflow-x:auto\"><table class=\"imports-table\" style=\"width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed\">"
            f"<thead><tr>{header_cells}</tr></thead><tbody>{import_rows}</tbody></table></div>"
            f"<p style=\"margin:8px 0 0;color:#64748b;font-size:12px;line-height:1.5\">{_html_text(copy['skipped_note'])}</p>"
        )
    else:
        imports_html = f"<p style=\"color:#536174\">{_html_text(copy['no_imports'])}</p>"
    if summary.import_events:
        imports_html += _html_list(
            [_event_text(group, language) for group in summary.import_events]
        )

    events_html = (
        _html_list([_event_text(group, language) for group in summary.system_events])
        if summary.system_events
        else f"<p style=\"color:#536174\">{_html_text(copy['no_events'])}</p>"
    )
    if summary.event_groups_truncated:
        events_html += f"<p style=\"color:#64748b\">{_html_text(copy['events_truncated'])}</p>"

    generated_local = summary.generated_at_utc.astimezone(
        summary.reporting_window.period_end_local.tzinfo
    )
    generated_label = (
        f"{_long_date(generated_local, language)} {_clock(generated_local)} "
        f"{generated_local.tzname() or ''}"
    ).rstrip()
    return (
        "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\"><style>"
        "@media only screen and (max-width:520px) {"
        ".summary-shell{padding:12px !important;}"
        ".summary-card{padding:16px !important;border-radius:8px !important;}"
        ".imports-table,.imports-table tbody,.imports-table tr,.imports-table td{display:block !important;width:100% !important;box-sizing:border-box !important;}"
        ".imports-table thead{display:none !important;}"
        ".imports-table tr{padding:8px 0 !important;border-bottom:1px solid #e2e8f0 !important;}"
        ".imports-table td{padding:3px 0 !important;border-bottom:0 !important;text-align:left !important;}"
        ".imports-table td::before{content:attr(data-label) ': ';font-weight:700;color:#475569;}"
        ".imports-table td:first-child{padding-top:0 !important;font-size:14px;font-weight:700;}"
        ".imports-table td:first-child::before{display:none;}"
        "}</style></head><body style=\"margin:0;padding:0;background:#f4f7fa;color:#172033;font-family:Arial,sans-serif\">"
        "<div class=\"summary-shell\" style=\"max-width:680px;margin:0 auto;padding:24px\">"
        "<div class=\"summary-card\" style=\"padding:24px;border:1px solid #dce3eb;border-radius:10px;background:#ffffff\">"
        f"<h1 style=\"margin:0 0 12px;font-size:24px\">{_html_text(copy['title'])}</h1>"
        f"{metadata}"
        f"<div style=\"margin-top:20px;padding:14px 16px;border-left:5px solid {status_border};background:{status_background};color:{status_color};font-weight:700\">"
        f"{_html_text(_status_label(summary, language))}</div>"
        f"{attention_html}"
        f"<h2 style=\"margin:24px 0 10px;font-size:20px\">{_html_text(copy['imports'])}</h2>{imports_html}"
        f"<h2 style=\"margin:24px 0 10px;font-size:20px\">{_html_text(copy['events'])}</h2>{events_html}"
        "<div style=\"margin-top:26px;padding-top:16px;border-top:1px solid #e2e8f0;color:#64748b;font-size:12px;line-height:1.5\">"
        f"<strong>CompassAQ</strong><br>{_html_text(copy['generated'])}: {_html_text(generated_label)}<br>{_html_text(copy['footer'])}"
        "</div></div></div></body></html>"
    )


def render_administrator_summary_email(
    summary: AdministratorSummary,
    language_code: str,
) -> RenderedAdministratorSummaryEmail:
    """Render one structured summary without database or transport access."""
    return RenderedAdministratorSummaryEmail(
        subject=generate_administrator_summary_subject(summary, language_code),
        text_body=render_administrator_summary_text(summary, language_code),
        html_body=render_administrator_summary_html(summary, language_code),
    )
