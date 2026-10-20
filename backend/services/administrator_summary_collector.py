"""SQL aggregation and attention rules for administrator summaries.

This module collects operational facts only. It has no SMTP, scheduling, API,
or rendering responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final, Mapping

from croniter import croniter
from sqlalchemy import Float, Integer, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from models import (
    Device,
    Event,
    ExternalAPI,
    JobExecutionTrigger,
    JobRun,
    JobSchedule,
    JobStatus,
    Measurement,
    MeasurementQCResult,
    Parameter,
    Sensor,
    Unit,
)
from services.external_sources import derive_builtin_external_source_state
from services.system_storage import StorageStatus, get_storage_status
from services.administrator_summary_domain import (
    AdministratorSummary,
    AttentionItem,
    EventDigestGroup,
    EventDigestSection,
    ImportSourceSummary,
    NO_SCHEDULED_RUN_STATUS,
    NOT_SCHEDULED_THIS_PERIOD_STATUS,
    QcActivityGroup,
    QcDigestOutcome,
    ReportingWindow,
    qc_check_display_name,
)
from qaqc.registry import get_registration


UTC = timezone.utc
MAX_QC_GROUPS: Final = 50
MAX_EVENT_GROUPS: Final = 50
RAW_EVENT_GROUP_QUERY_LIMIT: Final = 200
MAX_EXPECTED_SOURCE_ROWS: Final = 20


@dataclass(frozen=True)
class _ImportSourceDefinition:
    source_code: str
    source_name: str


IMPORT_SOURCE_BY_TASK: Final[dict[str, _ImportSourceDefinition]] = {
    "openaq_import": _ImportSourceDefinition("openaq", "OpenAQ"),
    "purpleair_import": _ImportSourceDefinition("purpleair", "PurpleAir"),
    "airgradient_import": _ImportSourceDefinition("airgradient", "AirGradient"),
}


@dataclass(frozen=True)
class EventDigestRule:
    digest_code: str
    section: EventDigestSection
    source_code: str
    source_name: str
    suppress_when_job_failed: bool = True


# Only these warning/error event types receive specialized digest wording.
# Unknown warnings are intentionally omitted. Unknown non-administrative errors
# receive one safe generic system label without exposing their raw payload.
EVENT_DIGEST_RULES: Final[dict[str, EventDigestRule]] = {
    "airgradient_reference_location_error": EventDigestRule(
        "reference_location_failed",
        EventDigestSection.IMPORTS,
        "airgradient",
        "AirGradient",
        suppress_when_job_failed=False,
    ),
    "airgradient_config_error": EventDigestRule(
        "source_configuration_error",
        EventDigestSection.IMPORTS,
        "airgradient",
        "AirGradient",
    ),
    "airgradient_fetch_error": EventDigestRule(
        "source_fetch_error",
        EventDigestSection.IMPORTS,
        "airgradient",
        "AirGradient",
    ),
    "airgradient_device_error": EventDigestRule(
        "source_device_error",
        EventDigestSection.IMPORTS,
        "airgradient",
        "AirGradient",
        suppress_when_job_failed=False,
    ),
    "airgradient_rate_limit": EventDigestRule(
        "source_rate_limited",
        EventDigestSection.IMPORTS,
        "airgradient",
        "AirGradient",
    ),
    "airgradient_measurement_error": EventDigestRule(
        "source_measurement_error",
        EventDigestSection.IMPORTS,
        "airgradient",
        "AirGradient",
    ),
    "openaq_measurements_validation_failed": EventDigestRule(
        "source_measurement_validation_failed",
        EventDigestSection.IMPORTS,
        "openaq",
        "OpenAQ",
        suppress_when_job_failed=False,
    ),
    "openaq_missing_api_key": EventDigestRule(
        "source_configuration_error",
        EventDigestSection.IMPORTS,
        "openaq",
        "OpenAQ",
    ),
}


SUPPRESSED_EVENT_PREFIXES: Final = (
    "auth.",
    "email.",
    "system_preferences.",
)
SUPPRESSED_EVENT_SOURCES: Final = {
    "admin.email",
    "admin.system_preferences",
    "auth",
    "scheduler.email",
}


SCHEDULED_JOB_STATUS_PRIORITY: Final[dict[str, int]] = {
    # If an unexpected duplicate scheduled run exists, the most consequential
    # status is shown so the summary does not hide an interrupted or failed run.
    JobStatus.SKIPPED.value: 0,
    JobStatus.SUCCESS.value: 1,
    JobStatus.RUNNING.value: 2,
    JobStatus.FAILED.value: 3,
    JobStatus.TIMEOUT.value: 4,
    JobStatus.INTERRUPTED.value: 5,
}
SCHEDULED_JOB_STATUS_BY_PRIORITY: Final[dict[int, str]] = {
    priority: (
        "timed_out" if status == JobStatus.TIMEOUT.value else status
    )
    for status, priority in SCHEDULED_JOB_STATUS_PRIORITY.items()
}
QC_ATTENTION_OUTCOME_ORDER: Final[dict[QcDigestOutcome, int]] = {
    QcDigestOutcome.MARKED_INVALID: 0,
    QcDigestOutcome.FLAGGED_FOR_REVIEW: 1,
    QcDigestOutcome.INDETERMINATE: 2,
}
QC_ATTENTION_CODE_BY_OUTCOME: Final[dict[QcDigestOutcome, str]] = {
    QcDigestOutcome.MARKED_INVALID: "qc_marked_invalid",
    QcDigestOutcome.FLAGGED_FOR_REVIEW: "qc_flagged_for_review",
    QcDigestOutcome.INDETERMINATE: "qc_indeterminate",
}


def _json_integer(column, key: str):
    """Read one provider-neutral numeric JSON summary field."""
    return cast(column[key].as_string(), Integer)


def _scheduled_job_status_code(status_rank: object) -> str:
    if status_rank is None:
        return NO_SCHEDULED_RUN_STATUS
    return SCHEDULED_JOB_STATUS_BY_PRIORITY.get(int(status_rank), NO_SCHEDULED_RUN_STATUS)


def build_import_summary_statement(reporting_window: ReportingWindow):
    """Build the grouped JobRun query without loading individual runs."""
    summary = JobRun.summary

    def status_count(status: JobStatus):
        return func.sum(case((JobRun.status == status.value, 1), else_=0))

    def counter_sum(key: str):
        # The Data imports row reports the scheduled import, so its measurement
        # counters must use the same scheduled JobRun population. Manual runs
        # remain available through the separate manual_job_count for other
        # operational reporting.
        return func.sum(
            case(
                (
                    JobRun.execution_trigger
                    == JobExecutionTrigger.SCHEDULED.value,
                    func.coalesce(_json_integer(summary, key), 0),
                ),
                else_=0,
            )
        )

    scheduled_status_rank = func.max(
        case(
            *(
                (
                    and_(
                        JobRun.execution_trigger
                        == JobExecutionTrigger.SCHEDULED.value,
                        JobRun.status == status,
                    ),
                    priority,
                )
                for status, priority in SCHEDULED_JOB_STATUS_PRIORITY.items()
            ),
            else_=None,
        )
    ).label("scheduled_job_status_rank")

    return (
        select(
            JobSchedule.task.label("task"),
            func.count(JobRun.job_run_id).label("job_count"),
            status_count(JobStatus.SUCCESS).label("successful_job_count"),
            status_count(JobStatus.FAILED).label("failed_job_count"),
            status_count(JobStatus.TIMEOUT).label("timed_out_job_count"),
            status_count(JobStatus.RUNNING).label("running_job_count"),
            status_count(JobStatus.SKIPPED).label("skipped_job_count"),
            status_count(JobStatus.INTERRUPTED).label("interrupted_job_count"),
            func.sum(
                case(
                    (
                        JobRun.execution_trigger
                        == JobExecutionTrigger.SCHEDULED.value,
                        1,
                    ),
                    else_=0,
                )
            ).label("scheduled_job_count"),
            func.sum(
                case(
                    (
                        JobRun.execution_trigger == JobExecutionTrigger.MANUAL.value,
                        1,
                    ),
                    else_=0,
                )
            ).label("manual_job_count"),
            scheduled_status_rank,
            counter_sum("measurements_received").label("measurements_received"),
            counter_sum("measurements_inserted").label("measurements_inserted"),
            counter_sum("measurements_updated").label("measurements_updated"),
            counter_sum("measurements_skipped").label("measurements_skipped"),
        )
        .join(JobSchedule, JobSchedule.job_schedule_id == JobRun.job_schedule_id)
        .where(
            JobSchedule.task.in_(tuple(IMPORT_SOURCE_BY_TASK)),
            JobRun.started_at >= reporting_window.period_start_utc,
            JobRun.started_at < reporting_window.period_end_utc,
        )
        .group_by(JobSchedule.task)
        .order_by(JobSchedule.task)
    )


def collect_import_summaries(
    session: Session,
    reporting_window: ReportingWindow,
    *,
    active_scheduled_tasks: set[str] | None = None,
    expected_scheduled_tasks: set[str] | None = None,
) -> tuple[ImportSourceSummary, ...]:
    active_tasks = set(active_scheduled_tasks or set())
    active_tasks.update(expected_scheduled_tasks or set())
    expected_tasks = set(expected_scheduled_tasks or set())
    rows = session.execute(build_import_summary_statement(reporting_window)).mappings()
    summaries: list[ImportSourceSummary] = []
    for row in rows:
        source = IMPORT_SOURCE_BY_TASK[row["task"]]
        scheduled_status_rank = row["scheduled_job_status_rank"]
        scheduled_job_count = int(row["scheduled_job_count"] or 0)
        scheduled_run_expected = row["task"] in expected_tasks
        if scheduled_status_rank is None and row["task"] in active_tasks and not scheduled_run_expected:
            scheduled_status_code = NOT_SCHEDULED_THIS_PERIOD_STATUS
        else:
            scheduled_status_code = _scheduled_job_status_code(scheduled_status_rank)
        summaries.append(
            ImportSourceSummary(
                source_code=source.source_code,
                source_name=source.source_name,
                job_count=int(row["job_count"] or 0),
                successful_job_count=int(row["successful_job_count"] or 0),
                failed_job_count=int(row["failed_job_count"] or 0),
                timed_out_job_count=int(row["timed_out_job_count"] or 0),
                running_job_count=int(row["running_job_count"] or 0),
                skipped_job_count=int(row["skipped_job_count"] or 0),
                interrupted_job_count=int(row["interrupted_job_count"] or 0),
                measurements_received=int(row["measurements_received"] or 0),
                measurements_inserted=int(row["measurements_inserted"] or 0),
                measurements_updated=int(row["measurements_updated"] or 0),
                measurements_skipped=int(row["measurements_skipped"] or 0),
                scheduled_job_count=scheduled_job_count,
                manual_job_count=int(row["manual_job_count"] or 0),
                scheduled_job_status_code=scheduled_status_code,
                scheduled_run_expected=scheduled_run_expected,
            )
        )
    present_source_codes = {summary.source_code for summary in summaries}
    for task in sorted(active_tasks):
        source = IMPORT_SOURCE_BY_TASK[task]
        if source.source_code in present_source_codes:
            continue
        scheduled_run_expected = task in expected_tasks
        summaries.append(
            ImportSourceSummary(
                source_code=source.source_code,
                source_name=source.source_name,
                job_count=0,
                successful_job_count=0,
                failed_job_count=0,
                timed_out_job_count=0,
                running_job_count=0,
                skipped_job_count=0,
                interrupted_job_count=0,
                measurements_received=0,
                measurements_inserted=0,
                measurements_updated=0,
                measurements_skipped=0,
                scheduled_job_count=0,
                manual_job_count=0,
                scheduled_run_expected=scheduled_run_expected,
                scheduled_job_status_code=(
                    NO_SCHEDULED_RUN_STATUS
                    if scheduled_run_expected
                    else NOT_SCHEDULED_THIS_PERIOD_STATUS
                ),
            )
        )
    return tuple(sorted(summaries, key=lambda summary: summary.source_name.casefold()))


def build_expected_source_statement():
    """Load built-in schedule/source pairs used for active-source and no-run rules."""
    task_source_pairs = tuple(
        and_(
            JobSchedule.task == task,
            ExternalAPI.provider_code == definition.source_code,
        )
        for task, definition in IMPORT_SOURCE_BY_TASK.items()
    )
    stored_credential_configured = and_(
        ExternalAPI.api_key.is_not(None),
        func.length(func.trim(ExternalAPI.api_key)) > 0,
    ).label("stored_credential_configured")
    return (
        select(
            JobSchedule,
            ExternalAPI.provider_code.label("provider_code"),
            ExternalAPI.enabled.label("source_enabled"),
            stored_credential_configured,
        )
        .join(ExternalAPI, or_(*task_source_pairs))
        .where(
            JobSchedule.enabled.is_(True),
            JobSchedule.task.in_(tuple(IMPORT_SOURCE_BY_TASK)),
        )
        .order_by(JobSchedule.task)
        .limit(MAX_EXPECTED_SOURCE_ROWS)
    )


def _schedule_has_occurrence_in_window(
    schedule: JobSchedule,
    reporting_window: ReportingWindow,
) -> bool:
    """Mirror the scheduler's current UTC croniter semantics.

    JobSchedule.timezone is currently not applied by the scheduler. Expected-run
    detection intentionally follows that behavior until importer cron timezone
    handling is changed in a dedicated phase. A due occurrence before the
    schedule's latest persisted change is ignored because historical enabled
    state is unavailable and a false no-run warning would not be actionable.
    """
    occurrence_search_start = reporting_window.period_start_utc
    schedule_changed_at = schedule.updated_at or schedule.created_at
    if schedule_changed_at is not None:
        if schedule_changed_at.tzinfo is None or schedule_changed_at.utcoffset() is None:
            schedule_changed_at = schedule_changed_at.replace(tzinfo=UTC)
        else:
            schedule_changed_at = schedule_changed_at.astimezone(UTC)
        occurrence_search_start = max(occurrence_search_start, schedule_changed_at)
    try:
        occurrence = croniter(
            schedule.cron_expr,
            occurrence_search_start - timedelta(microseconds=1),
        ).get_next(datetime)
    except (KeyError, TypeError, ValueError):
        return False
    if occurrence.tzinfo is None:
        occurrence = occurrence.replace(tzinfo=UTC)
    return occurrence.astimezone(UTC) < reporting_window.period_end_utc


def collect_expected_scheduled_tasks(
    session: Session,
    reporting_window: ReportingWindow,
    *,
    environment: Mapping[str, str] | None = None,
) -> set[str]:
    _, expected_tasks = collect_scheduled_import_tasks(
        session,
        reporting_window,
        environment=environment,
    )
    return expected_tasks


def collect_scheduled_import_tasks(
    session: Session,
    reporting_window: ReportingWindow,
    *,
    environment: Mapping[str, str] | None = None,
) -> tuple[set[str], set[str]]:
    """Return active built-in import tasks and the active tasks due this period.

    Both sets come from the same enabled JobSchedule/source rows. A task can be
    active without being due in this reporting window; that normal state is
    rendered as ``Not scheduled this period`` rather than being mistaken for a
    missing scheduled JobRun.
    """
    active_tasks: set[str] = set()
    expected_tasks: set[str] = set()
    rows = session.execute(build_expected_source_statement()).all()
    for schedule, provider_code, source_enabled, stored_credential_configured in rows:
        source_state = derive_builtin_external_source_state(
            provider_code=str(provider_code),
            enabled=bool(source_enabled),
            stored_credential_configured=bool(stored_credential_configured),
            environment=environment,
        )
        if not source_state.is_runnable:
            continue
        active_tasks.add(schedule.task)
        if _schedule_has_occurrence_in_window(schedule, reporting_window):
            expected_tasks.add(schedule.task)
    return active_tasks, expected_tasks


def _qc_outcome_expression():
    return case(
        (
            MeasurementQCResult.evaluation_status == "indeterminate",
            QcDigestOutcome.INDETERMINATE.value,
        ),
        (
            and_(
                MeasurementQCResult.evaluation_status == "failed",
                MeasurementQCResult.failure_action == "mark_invalid",
            ),
            QcDigestOutcome.MARKED_INVALID.value,
        ),
        (
            and_(
                MeasurementQCResult.evaluation_status == "failed",
                MeasurementQCResult.failure_action == "flag_for_review",
            ),
            QcDigestOutcome.FLAGGED_FOR_REVIEW.value,
        ),
        else_=QcDigestOutcome.INDETERMINATE.value,
    )


def build_qc_summary_statement(reporting_window: ReportingWindow):
    """Build grouped QC facts without loading measurements or provenance payloads.

    The selected snapshot fields are limited to the effective range threshold,
    baseline-drift settings, and evaluation unit needed by the email renderer.
    """
    outcome = _qc_outcome_expression().label("outcome")
    source_name = func.coalesce(
        ExternalAPI.name,
        Device.manual_data_source_name,
        "Unknown source",
    ).label("source_name")
    device_name = func.coalesce(
        Device.friendly_name,
        Device.name,
        "Unknown device",
    ).label("device_name")
    parameter_name = func.coalesce(
        Parameter.display_name,
        "Unknown parameter",
    ).label("parameter_name")
    evaluation_unit_code = MeasurementQCResult.policy_snapshot[
        "evaluation_unit_code"
    ].as_string()
    evaluation_unit = aliased(Unit)
    sensor_unit = aliased(Unit)
    effective_unit_symbol = func.coalesce(
        evaluation_unit.symbol,
        sensor_unit.symbol,
    ).label("effective_unit_symbol")
    minimum_threshold = cast(
        MeasurementQCResult.params_snapshot["min"].as_string(),
        Float,
    )
    maximum_threshold = cast(
        MeasurementQCResult.params_snapshot["max"].as_string(),
        Float,
    )
    effective_threshold = case(
        (MeasurementQCResult.check_code == "min_value", minimum_threshold),
        (MeasurementQCResult.check_code == "max_value", maximum_threshold),
        else_=None,
    ).label("effective_threshold")
    effective_max_drift_per_day = cast(
        MeasurementQCResult.params_snapshot["max_drift_per_day"].as_string(),
        Float,
    ).label("effective_max_drift_per_day")
    effective_drift_direction = MeasurementQCResult.params_snapshot[
        "direction"
    ].as_string().label("effective_drift_direction")
    policy_applicability = MeasurementQCResult.policy_snapshot[
        "applicability"
    ].as_string()
    reason_code = MeasurementQCResult.reason_code
    return (
        select(
            source_name,
            device_name,
            parameter_name,
            MeasurementQCResult.check_code.label("check_code"),
            outcome,
            MeasurementQCResult.reason_code.label("reason_code"),
            func.count(MeasurementQCResult.measurement_qc_result_id).label(
                "result_count"
            ),
            func.count(func.distinct(MeasurementQCResult.measurement_id)).label(
                "measurement_count"
            ),
            effective_threshold,
            effective_unit_symbol,
            effective_max_drift_per_day,
            effective_drift_direction,
        )
        .join(
            Measurement,
            Measurement.measurement_id == MeasurementQCResult.measurement_id,
        )
        .join(Sensor, Sensor.sensor_id == Measurement.sensor_id)
        .join(Device, Device.device_id == Sensor.device_id)
        .outerjoin(ExternalAPI, ExternalAPI.external_api_id == Device.external_api_id)
        .outerjoin(evaluation_unit, evaluation_unit.code == evaluation_unit_code)
        .outerjoin(sensor_unit, sensor_unit.unit_id == Sensor.unit_id)
        .outerjoin(
            Parameter,
            Parameter.parameter_id
            == func.coalesce(MeasurementQCResult.parameter_id, Sensor.parameter_id),
        )
        .where(
            MeasurementQCResult.evaluation_status.in_(
                ("failed", "indeterminate")
            ),
            MeasurementQCResult.passed.is_not(True),
            or_(reason_code.is_(None), reason_code.not_in(("no_matching_rule", "not_applicable"))),
            or_(
                policy_applicability.is_(None),
                policy_applicability != "not_applicable",
            ),
            MeasurementQCResult.created_at >= reporting_window.period_start_utc,
            MeasurementQCResult.created_at < reporting_window.period_end_utc,
        )
        .group_by(
            source_name,
            device_name,
            parameter_name,
            MeasurementQCResult.check_code,
            outcome,
            MeasurementQCResult.reason_code,
            effective_threshold,
            effective_unit_symbol,
            effective_max_drift_per_day,
            effective_drift_direction,
        )
        .order_by(
            case(
                (outcome == QcDigestOutcome.MARKED_INVALID.value, 0),
                (outcome == QcDigestOutcome.FLAGGED_FOR_REVIEW.value, 1),
                else_=2,
            ),
            func.count(func.distinct(MeasurementQCResult.measurement_id)).desc(),
            source_name,
            device_name,
            parameter_name,
            MeasurementQCResult.check_code,
        )
        .limit(MAX_QC_GROUPS + 1)
    )


def collect_qc_activity(
    session: Session,
    reporting_window: ReportingWindow,
) -> tuple[tuple[QcActivityGroup, ...], bool]:
    rows = list(
        session.execute(build_qc_summary_statement(reporting_window)).mappings()
    )
    truncated = len(rows) > MAX_QC_GROUPS
    groups = tuple(
        QcActivityGroup(
            source_name=str(row["source_name"]),
            device_name=str(row["device_name"]),
            parameter_name=str(row["parameter_name"]),
            check_code=str(row["check_code"]),
            check_name=(
                registration.metadata.display_name
                if (registration := get_registration(str(row["check_code"]))) is not None
                else qc_check_display_name(str(row["check_code"]), "en")
            ),
            outcome=QcDigestOutcome(str(row["outcome"])),
            reason_code=(str(row["reason_code"]) if row["reason_code"] else None),
            result_count=int(row["result_count"]),
            measurement_count=int(row["measurement_count"]),
            effective_threshold=(
                float(row["effective_threshold"])
                if row["effective_threshold"] is not None
                else None
            ),
            effective_unit_symbol=(
                str(row["effective_unit_symbol"])
                if row["effective_unit_symbol"]
                else None
            ),
            effective_max_drift_per_day=(
                float(row["effective_max_drift_per_day"])
                if row["effective_max_drift_per_day"] is not None
                else None
            ),
            effective_drift_direction=(
                str(row["effective_drift_direction"])
                if row["effective_drift_direction"]
                else None
            ),
        )
        for row in rows[:MAX_QC_GROUPS]
    )
    return groups, truncated


def build_event_summary_statement(reporting_window: ReportingWindow):
    """Select only fields approved for digest classification and grouping."""
    device_name = func.coalesce(Device.friendly_name, Device.name).label(
        "device_name"
    )
    return (
        select(
            Event.event_type.label("event_type"),
            Event.source.label("source"),
            Event.severity.label("severity"),
            device_name,
            func.count(Event.event_id).label("event_count"),
        )
        .outerjoin(Device, Device.device_id == Event.device_id)
        .where(
            Event.created_at >= reporting_window.period_start_utc,
            Event.created_at < reporting_window.period_end_utc,
            Event.severity.in_(("warning", "warn", "error")),
        )
        .group_by(Event.event_type, Event.source, Event.severity, device_name)
        .order_by(
            case((Event.severity == "error", 0), else_=1),
            func.count(Event.event_id).desc(),
            Event.event_type,
            Event.source,
        )
        .limit(RAW_EVENT_GROUP_QUERY_LIMIT + 1)
    )


def _classify_event_group(
    *,
    event_type: str,
    source: str,
    severity: str,
    device_name: str | None,
    event_count: int,
    failed_source_codes: set[str],
) -> EventDigestGroup | None:
    if source in SUPPRESSED_EVENT_SOURCES or event_type.startswith(
        SUPPRESSED_EVENT_PREFIXES
    ):
        return None

    rule = EVENT_DIGEST_RULES.get(event_type)
    if rule is not None:
        if rule.suppress_when_job_failed and rule.source_code in failed_source_codes:
            return None
        return EventDigestGroup(
            digest_code=rule.digest_code,
            section=rule.section,
            source_code=rule.source_code,
            source_name=rule.source_name,
            device_name=device_name,
            severity=severity,
            event_count=event_count,
        )

    if severity != "error":
        return None
    return EventDigestGroup(
        digest_code="system_error",
        section=EventDigestSection.SYSTEM,
        source_code="system",
        source_name="CompassAQ",
        device_name=device_name,
        severity=severity,
        event_count=event_count,
    )


def collect_event_groups(
    session: Session,
    reporting_window: ReportingWindow,
    import_sources: tuple[ImportSourceSummary, ...],
) -> tuple[tuple[EventDigestGroup, ...], tuple[EventDigestGroup, ...], bool]:
    rows = list(
        session.execute(build_event_summary_statement(reporting_window)).mappings()
    )
    failed_source_codes = {
        source.source_code
        for source in import_sources
        if source.failed_job_count or source.timed_out_job_count
    }
    classified: list[EventDigestGroup] = []
    for row in rows[:RAW_EVENT_GROUP_QUERY_LIMIT]:
        group = _classify_event_group(
            event_type=str(row["event_type"]),
            source=str(row["source"]),
            severity=str(row["severity"]),
            device_name=(str(row["device_name"]) if row["device_name"] else None),
            event_count=int(row["event_count"]),
            failed_source_codes=failed_source_codes,
        )
        if group is not None:
            classified.append(group)

    classified.sort(
        key=lambda group: (
            0 if group.severity == "error" else 1,
            -group.event_count,
            group.source_name.casefold(),
            group.digest_code,
            (group.device_name or "").casefold(),
        )
    )
    truncated = (
        len(rows) > RAW_EVENT_GROUP_QUERY_LIMIT
        or len(classified) > MAX_EVENT_GROUPS
    )
    limited = classified[:MAX_EVENT_GROUPS]
    import_events = tuple(
        group for group in limited if group.section is EventDigestSection.IMPORTS
    )
    system_events = tuple(
        group for group in limited if group.section is EventDigestSection.SYSTEM
    )
    return import_events, system_events, truncated


def derive_attention_items(
    import_sources: tuple[ImportSourceSummary, ...],
    qc_activity: tuple[QcActivityGroup, ...],
    import_events: tuple[EventDigestGroup, ...],
    system_events: tuple[EventDigestGroup, ...],
    storage_status: StorageStatus | None = None,
) -> tuple[AttentionItem, ...]:
    """Apply the summary attention policy to structured facts.

    QC attention is counted by aggregate group, not by measurement count. A
    marked-invalid group is listed before a review-only group, with stable
    names and counts providing deterministic ordering within each outcome.
    """
    items: list[AttentionItem] = []
    for source in import_sources:
        failure_count = source.failed_job_count + source.timed_out_job_count
        if failure_count:
            items.append(
                AttentionItem(
                    attention_code="import_jobs_failed",
                    count=failure_count,
                    source_name=source.source_name,
                    successful_job_count=source.successful_job_count,
                )
            )
        if source.interrupted_job_count:
            items.append(
                AttentionItem(
                    attention_code="import_jobs_interrupted",
                    count=source.interrupted_job_count,
                    source_name=source.source_name,
                    successful_job_count=source.successful_job_count,
                )
            )
        if source.scheduled_run_missing:
            items.append(
                AttentionItem(
                    attention_code="scheduled_import_missing",
                    count=1,
                    source_name=source.source_name,
                )
            )

    for event_group in import_events:
        items.append(
            AttentionItem(
                attention_code=event_group.digest_code,
                count=event_group.event_count,
                source_name=event_group.source_name,
                device_name=event_group.device_name,
            )
        )

    ordered_qc_groups = sorted(
        qc_activity,
        key=lambda group: (
            QC_ATTENTION_OUTCOME_ORDER[group.outcome],
            -group.measurement_count,
            group.source_name.casefold(),
            group.device_name.casefold(),
            group.parameter_name.casefold(),
            group.check_code.casefold(),
            (group.reason_code or "").casefold(),
            -group.result_count,
        ),
    )
    for qc_group in ordered_qc_groups:
        attention_code = QC_ATTENTION_CODE_BY_OUTCOME[qc_group.outcome]
        items.append(
            AttentionItem(
                attention_code=attention_code,
                count=qc_group.measurement_count,
                source_name=qc_group.source_name,
                device_name=qc_group.device_name,
                parameter_name=qc_group.parameter_name,
                check_name=qc_group.check_name,
                check_code=qc_group.check_code,
                reason_code=qc_group.reason_code,
                effective_threshold=qc_group.effective_threshold,
                effective_unit_symbol=qc_group.effective_unit_symbol,
                effective_max_drift_per_day=qc_group.effective_max_drift_per_day,
                effective_drift_direction=qc_group.effective_drift_direction,
            )
        )

    for event_group in system_events:
        items.append(
            AttentionItem(
                attention_code=event_group.digest_code,
                count=event_group.event_count,
                source_name=event_group.source_name,
                device_name=event_group.device_name,
            )
        )
    if storage_status is not None and storage_status.needs_attention:
        items.append(
            AttentionItem(
                attention_code="storage_low",
                count=1,
                source_name="CompassAQ",
                free_bytes=storage_status.free_bytes,
                percent_free=storage_status.percent_free,
                storage_status=storage_status.status,
            )
        )
    return tuple(items)


def build_administrator_summary(
    session: Session,
    reporting_window: ReportingWindow,
    *,
    generated_at_utc: datetime | None = None,
    environment_label: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> AdministratorSummary:
    """Collect one structured summary using bounded aggregate queries."""
    active_scheduled_tasks, expected_scheduled_tasks = collect_scheduled_import_tasks(
        session,
        reporting_window,
        environment=environment,
    )
    import_sources = collect_import_summaries(
        session,
        reporting_window,
        active_scheduled_tasks=active_scheduled_tasks,
        expected_scheduled_tasks=expected_scheduled_tasks,
    )
    qc_activity, qc_groups_truncated = collect_qc_activity(
        session, reporting_window
    )
    import_events, system_events, event_groups_truncated = collect_event_groups(
        session,
        reporting_window,
        import_sources,
    )
    storage_status = get_storage_status(environment)
    attention_items = derive_attention_items(
        import_sources,
        qc_activity,
        import_events,
        system_events,
        storage_status,
    )
    return AdministratorSummary(
        reporting_window=reporting_window,
        generated_at_utc=generated_at_utc or datetime.now(UTC),
        import_sources=import_sources,
        qc_activity=qc_activity,
        import_events=import_events,
        system_events=system_events,
        attention_items=attention_items,
        qc_groups_truncated=qc_groups_truncated,
        event_groups_truncated=event_groups_truncated,
        environment_label=(environment_label.strip() if environment_label else None),
    )
