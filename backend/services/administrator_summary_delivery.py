"""Canonical scheduled delivery for administrator summaries.

The scheduler calls this module once at the beginning of each polling loop.
It intentionally owns only the single platform-wide administrator-summary
workflow rather than providing a generic notification framework.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import os
from typing import ContextManager, Final

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobs.locking import postgres_advisory_lock
from models import AdministratorSummaryDelivery, EmailSettings, SystemSettings
from services.administrator_summary_collector import build_administrator_summary
from services.administrator_summary_domain import (
    AdministratorSummary,
    ReportingWindow,
    administrator_summary_environment_label,
)
from services.administrator_summary_renderer import (
    render_administrator_summary_email,
)
from services.administrator_summary_schedule import (
    AdministratorSummaryScheduleValidationError,
    administrator_summary_schedule_from_settings,
    latest_due_administrator_summary_window,
)
from services.email_configuration import (
    EmailReadinessStatus,
    derive_email_readiness,
    get_or_create_email_settings,
)
from services.system_settings import (
    get_system_timezone,
    resolve_default_language_code,
)
from services.email_delivery import (
    EmailDeliveryError,
    EmailDeliveryErrorCode,
    EmailService,
    EmailTransportConfiguration,
    email_transport_configuration_from_settings,
)
from services.event_log import add_event


UTC = timezone.utc
# Stable ASCII-derived "CAQS" key, separate from importer schedule-id locks.
ADMINISTRATOR_SUMMARY_ADVISORY_LOCK_KEY: Final = 0x43415153
ADMINISTRATOR_SUMMARY_MAX_ATTEMPTS: Final = 2
ADMINISTRATOR_SUMMARY_RETRY_DELAY: Final = timedelta(minutes=5)

RETRYABLE_ERROR_CODES: Final = frozenset(
    {
        EmailDeliveryErrorCode.DNS_FAILURE.value,
        EmailDeliveryErrorCode.CONNECTION_TIMEOUT.value,
        EmailDeliveryErrorCode.CONNECTION_FAILED.value,
    }
)
AMBIGUOUS_ACCEPTANCE_ERROR_CODES: Final = frozenset(
    {
        EmailDeliveryErrorCode.SERVER_DISCONNECTED.value,
        EmailDeliveryErrorCode.SERVER_ERROR.value,
    }
)


class AdministratorSummaryDeliveryStatus(str, Enum):
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERY_UNKNOWN = "delivery_unknown"


class AdministratorSummaryDeliveryAction(str, Enum):
    CLAIM = "claim"
    WAIT_FOR_RETRY = "wait_for_retry"
    OBSERVE_EXISTING = "observe_existing"
    MARK_DELIVERY_UNKNOWN = "mark_delivery_unknown"


class AdministratorSummaryProcessingStatus(str, Enum):
    SUMMARY_DISABLED = "summary_disabled"
    EMAIL_NOT_READY = "email_not_ready"
    RECIPIENTS_MISSING = "recipients_missing"
    INVALID_SCHEDULE = "invalid_schedule"
    SCHEDULE_NOT_EFFECTIVE = "schedule_not_effective"
    NO_DUE_WINDOW = "no_due_window"
    LOCK_UNAVAILABLE = "lock_unavailable"
    DELIVERY_IN_PROGRESS = "delivery_in_progress"
    ALREADY_SENT = "already_sent"
    RETRY_WAITING = "retry_waiting"
    FAILED_NO_RETRY = "failed_no_retry"
    DELIVERY_UNKNOWN = "delivery_unknown"
    SENT = "sent"
    FAILED = "failed"


@dataclass(frozen=True)
class AdministratorSummaryProcessingResult:
    status: AdministratorSummaryProcessingStatus
    period_start_utc: datetime | None = None
    period_end_utc: datetime | None = None
    attempt_count: int = 0
    reason_codes: tuple[str, ...] = ()


LockContextFactory = Callable[[Engine, int], ContextManager[bool]]
EmailServiceFactory = Callable[[EmailTransportConfiguration], EmailService]


def _normalize_now(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must include a timezone")
    return now_utc.astimezone(UTC)


def determine_administrator_summary_delivery_action(
    delivery: AdministratorSummaryDelivery,
    *,
    now_utc: datetime,
) -> AdministratorSummaryDeliveryAction:
    """Apply the bounded retry and ambiguous-delivery policy to one row."""
    now = _normalize_now(now_utc)
    status = AdministratorSummaryDeliveryStatus(delivery.status)
    if status in {
        AdministratorSummaryDeliveryStatus.SENT,
        AdministratorSummaryDeliveryStatus.DELIVERY_UNKNOWN,
    }:
        return AdministratorSummaryDeliveryAction.OBSERVE_EXISTING

    last_attempted_at = delivery.last_attempted_at
    normalized_last_attempted_at = (
        last_attempted_at.astimezone(UTC)
        if last_attempted_at is not None
        and last_attempted_at.tzinfo is not None
        and last_attempted_at.utcoffset() is not None
        else None
    )
    if last_attempted_at is not None and normalized_last_attempted_at is None:
        # SQLite's test fallback drops timezone metadata from UTC columns.
        normalized_last_attempted_at = last_attempted_at.replace(tzinfo=UTC)
    if status is AdministratorSummaryDeliveryStatus.SENDING:
        # This decision runs only after acquiring the one global summary lock.
        # A conforming active sender would still hold that lock, so an observed
        # sending row is necessarily left behind by an interrupted process.
        return AdministratorSummaryDeliveryAction.MARK_DELIVERY_UNKNOWN

    if delivery.attempt_count >= ADMINISTRATOR_SUMMARY_MAX_ATTEMPTS:
        return AdministratorSummaryDeliveryAction.OBSERVE_EXISTING
    if delivery.error_code not in RETRYABLE_ERROR_CODES:
        return AdministratorSummaryDeliveryAction.OBSERVE_EXISTING
    if (
        normalized_last_attempted_at is not None
        and now - normalized_last_attempted_at < ADMINISTRATOR_SUMMARY_RETRY_DELAY
    ):
        return AdministratorSummaryDeliveryAction.WAIT_FOR_RETRY
    return AdministratorSummaryDeliveryAction.CLAIM


def _result_for_existing_delivery(
    delivery: AdministratorSummaryDelivery,
    action: AdministratorSummaryDeliveryAction,
) -> AdministratorSummaryProcessingResult:
    period_values = {
        "period_start_utc": delivery.period_start,
        "period_end_utc": delivery.period_end,
        "attempt_count": delivery.attempt_count,
    }
    if action is AdministratorSummaryDeliveryAction.WAIT_FOR_RETRY:
        return AdministratorSummaryProcessingResult(
            AdministratorSummaryProcessingStatus.RETRY_WAITING,
            **period_values,
        )
    if delivery.status == AdministratorSummaryDeliveryStatus.SENT.value:
        status = AdministratorSummaryProcessingStatus.ALREADY_SENT
    elif delivery.status == AdministratorSummaryDeliveryStatus.SENDING.value:
        status = AdministratorSummaryProcessingStatus.DELIVERY_IN_PROGRESS
    elif delivery.status == AdministratorSummaryDeliveryStatus.DELIVERY_UNKNOWN.value:
        status = AdministratorSummaryProcessingStatus.DELIVERY_UNKNOWN
    else:
        status = AdministratorSummaryProcessingStatus.FAILED_NO_RETRY
    return AdministratorSummaryProcessingResult(status, **period_values)


def _safe_event_params(
    delivery: AdministratorSummaryDelivery,
    *,
    recipient_count: int,
    summary: AdministratorSummary | None = None,
) -> dict[str, object]:
    params: dict[str, object] = {
        "period_start": delivery.period_start.isoformat(),
        "period_end": delivery.period_end.isoformat(),
        "cadence": delivery.cadence,
        "reporting_timezone": delivery.reporting_timezone,
        "attempt_count": delivery.attempt_count,
        "recipient_count": recipient_count,
    }
    if delivery.error_code:
        params["error_code"] = delivery.error_code
    if summary is not None:
        params.update(
            {
                "attention_item_count": summary.attention_item_count,
                "import_job_count": sum(
                    source.job_count for source in summary.import_sources
                ),
                "qc_group_count": len(summary.qc_activity),
                "event_group_count": (
                    len(summary.import_events) + len(summary.system_events)
                ),
            }
        )
    return params


def _record_delivery_event(
    session: Session,
    delivery: AdministratorSummaryDelivery,
    *,
    recipient_count: int,
    summary: AdministratorSummary | None = None,
) -> None:
    if delivery.status == AdministratorSummaryDeliveryStatus.SENT.value:
        event_type = "email.administrator_summary.sent"
        severity = "info"
        message = "Administrator summary sent"
    elif delivery.status == AdministratorSummaryDeliveryStatus.DELIVERY_UNKNOWN.value:
        event_type = "email.administrator_summary.delivery_unknown"
        severity = "warning"
        message = "Administrator summary delivery outcome is unknown"
    else:
        event_type = "email.administrator_summary.failed"
        severity = "warning"
        message = "Administrator summary delivery failed"
    add_event(
        session,
        event_type=event_type,
        source="scheduler.email",
        severity=severity,
        message=message,
        params=_safe_event_params(
            delivery,
            recipient_count=recipient_count,
            summary=summary,
        ),
    )


def _mark_delivery_unknown(
    session: Session,
    delivery: AdministratorSummaryDelivery,
    *,
    error_code: str,
    recipient_count: int,
) -> AdministratorSummaryProcessingResult:
    delivery.status = AdministratorSummaryDeliveryStatus.DELIVERY_UNKNOWN.value
    delivery.error_code = error_code
    session.add(delivery)
    _record_delivery_event(
        session,
        delivery,
        recipient_count=recipient_count,
    )
    session.commit()
    return _result_for_existing_delivery(
        delivery,
        AdministratorSummaryDeliveryAction.OBSERVE_EXISTING,
    )


def _recover_interrupted_sending_deliveries(
    session: Session,
    *,
    recipient_count: int,
) -> None:
    interrupted_deliveries = session.scalars(
        select(AdministratorSummaryDelivery).where(
            AdministratorSummaryDelivery.status
            == AdministratorSummaryDeliveryStatus.SENDING.value,
        )
    ).all()
    for interrupted_delivery in interrupted_deliveries:
        interrupted_delivery.status = (
            AdministratorSummaryDeliveryStatus.DELIVERY_UNKNOWN.value
        )
        interrupted_delivery.error_code = "stale_sending_after_restart"
        session.add(interrupted_delivery)
        _record_delivery_event(
            session,
            interrupted_delivery,
            recipient_count=recipient_count,
        )
    if interrupted_deliveries:
        session.commit()


def _claim_delivery(
    session: Session,
    *,
    existing_delivery: AdministratorSummaryDelivery | None,
    reporting_window: ReportingWindow,
    now_utc: datetime,
) -> AdministratorSummaryDelivery | None:
    if existing_delivery is None:
        delivery = AdministratorSummaryDelivery(
            period_start=reporting_window.period_start_utc,
            period_end=reporting_window.period_end_utc,
            cadence=reporting_window.cadence.value,
            reporting_timezone=reporting_window.reporting_timezone,
            status=AdministratorSummaryDeliveryStatus.SENDING.value,
            attempt_count=1,
            last_attempted_at=now_utc,
        )
        session.add(delivery)
    else:
        delivery = existing_delivery
        delivery.status = AdministratorSummaryDeliveryStatus.SENDING.value
        delivery.attempt_count += 1
        delivery.last_attempted_at = now_utc
        delivery.sent_at = None
        delivery.error_code = None
        session.add(delivery)
    try:
        session.commit()
    except IntegrityError:
        # Another worker may have inserted the unique period identity before
        # observing our advisory lock. Reload and observe its canonical row.
        session.rollback()
        return None
    session.refresh(delivery)
    return delivery


def _record_failed_or_unknown_delivery(
    session: Session,
    delivery: AdministratorSummaryDelivery,
    *,
    error_code: str,
    recipient_count: int,
    summary: AdministratorSummary | None = None,
    delivery_unknown: bool,
) -> AdministratorSummaryProcessingResult:
    delivery.status = (
        AdministratorSummaryDeliveryStatus.DELIVERY_UNKNOWN.value
        if delivery_unknown
        else AdministratorSummaryDeliveryStatus.FAILED.value
    )
    delivery.error_code = error_code[:64]
    session.add(delivery)
    _record_delivery_event(
        session,
        delivery,
        recipient_count=recipient_count,
        summary=summary,
    )
    session.commit()
    return AdministratorSummaryProcessingResult(
        (
            AdministratorSummaryProcessingStatus.DELIVERY_UNKNOWN
            if delivery_unknown
            else AdministratorSummaryProcessingStatus.FAILED
        ),
        period_start_utc=delivery.period_start,
        period_end_utc=delivery.period_end,
        attempt_count=delivery.attempt_count,
        reason_codes=(delivery.error_code,),
    )


def _summary_language(session: Session) -> str:
    language_code = session.scalar(select(SystemSettings.default_language_code))
    return resolve_default_language_code(language_code)


def process_due_administrator_summary(
    session: Session,
    *,
    now_utc: datetime,
    environment: Mapping[str, str] | None = None,
    lock_context_factory: LockContextFactory = postgres_advisory_lock,
    email_service_factory: EmailServiceFactory = EmailService,
) -> AdministratorSummaryProcessingResult:
    """Process at most one latest reporting window under the global lock."""
    now = _normalize_now(now_utc)
    environment_values = environment if environment is not None else os.environ
    engine = session.get_bind()

    with lock_context_factory(engine, ADMINISTRATOR_SUMMARY_ADVISORY_LOCK_KEY) as acquired:
        if not acquired:
            return AdministratorSummaryProcessingResult(
                AdministratorSummaryProcessingStatus.LOCK_UNAVAILABLE
            )

        settings = get_or_create_email_settings(session)
        _recover_interrupted_sending_deliveries(
            session,
            recipient_count=len(settings.administrator_recipients or []),
        )
        if not settings.administrator_summary_enabled:
            return AdministratorSummaryProcessingResult(
                AdministratorSummaryProcessingStatus.SUMMARY_DISABLED
            )
        if not settings.administrator_recipients:
            return AdministratorSummaryProcessingResult(
                AdministratorSummaryProcessingStatus.RECIPIENTS_MISSING,
                reason_codes=("administrator_recipients_missing",),
            )
        readiness = derive_email_readiness(
            settings,
            # ``None`` lets normal deployments use the persisted runtime key.
            # An explicit mapping remains available for isolated tests and
            # deployments that intentionally supply their own key.
            encryption_environment=environment,
        )
        if readiness.status is not EmailReadinessStatus.READY:
            return AdministratorSummaryProcessingResult(
                AdministratorSummaryProcessingStatus.EMAIL_NOT_READY,
                reason_codes=readiness.reason_codes,
            )
        try:
            schedule = administrator_summary_schedule_from_settings(
                settings,
                system_timezone=get_system_timezone(session),
            )
        except AdministratorSummaryScheduleValidationError as exc:
            return AdministratorSummaryProcessingResult(
                AdministratorSummaryProcessingStatus.INVALID_SCHEDULE,
                reason_codes=(exc.error_code,),
            )
        if schedule.effective_at_utc is None:
            return AdministratorSummaryProcessingResult(
                AdministratorSummaryProcessingStatus.SCHEDULE_NOT_EFFECTIVE,
                reason_codes=("administrator_summary_effective_at_missing",),
            )
        due_window = latest_due_administrator_summary_window(
            schedule,
            now_utc=now,
        )
        if due_window is None:
            return AdministratorSummaryProcessingResult(
                AdministratorSummaryProcessingStatus.NO_DUE_WINDOW
            )

        reporting_window = due_window.reporting_window
        delivery = session.scalar(
            select(AdministratorSummaryDelivery).where(
                AdministratorSummaryDelivery.period_start
                == reporting_window.period_start_utc,
                AdministratorSummaryDelivery.period_end
                == reporting_window.period_end_utc,
            )
        )
        if delivery is not None:
            action = determine_administrator_summary_delivery_action(
                delivery,
                now_utc=now,
            )
            if action is AdministratorSummaryDeliveryAction.MARK_DELIVERY_UNKNOWN:
                return _mark_delivery_unknown(
                    session,
                    delivery,
                    error_code="stale_sending_after_restart",
                    recipient_count=len(settings.administrator_recipients),
                )
            if action is not AdministratorSummaryDeliveryAction.CLAIM:
                return _result_for_existing_delivery(delivery, action)

        claimed_delivery = _claim_delivery(
            session,
            existing_delivery=delivery,
            reporting_window=reporting_window,
            now_utc=now,
        )
        if claimed_delivery is None:
            winning_delivery = session.scalar(
                select(AdministratorSummaryDelivery).where(
                    AdministratorSummaryDelivery.period_start
                    == reporting_window.period_start_utc,
                    AdministratorSummaryDelivery.period_end
                    == reporting_window.period_end_utc,
                )
            )
            if winning_delivery is None:
                raise RuntimeError("Administrator summary delivery identity was lost")
            action = determine_administrator_summary_delivery_action(
                winning_delivery,
                now_utc=now,
            )
            return _result_for_existing_delivery(winning_delivery, action)

        recipients = tuple(settings.administrator_recipients)
        summary = None
        try:
            summary = build_administrator_summary(
                session,
                reporting_window,
                generated_at_utc=now,
                environment_label=administrator_summary_environment_label(environment_values),
                environment=environment_values,
            )
            rendered = render_administrator_summary_email(
                summary,
                _summary_language(session),
            )
            transport = email_transport_configuration_from_settings(
                settings,
                encryption_environment=environment,
            )
        except EmailDeliveryError as error:
            return _record_failed_or_unknown_delivery(
                session,
                claimed_delivery,
                error_code=error.error_code.value,
                recipient_count=len(recipients),
                summary=summary,
                delivery_unknown=False,
            )
        except Exception:
            return _record_failed_or_unknown_delivery(
                session,
                claimed_delivery,
                error_code="administrator_summary_build_failed",
                recipient_count=len(recipients),
                summary=summary,
                delivery_unknown=False,
            )

        try:
            email_service = email_service_factory(transport)
            email_service.send(
                recipients=recipients,
                subject=rendered.subject,
                text_body=rendered.text_body,
                html_body=rendered.html_body,
            )
        except EmailDeliveryError as error:
            error_code = error.error_code.value
            return _record_failed_or_unknown_delivery(
                session,
                claimed_delivery,
                error_code=error_code,
                recipient_count=len(recipients),
                summary=summary,
                delivery_unknown=(
                    error_code in AMBIGUOUS_ACCEPTANCE_ERROR_CODES
                ),
            )
        except Exception:
            return _record_failed_or_unknown_delivery(
                session,
                claimed_delivery,
                error_code="smtp_delivery_outcome_unknown",
                recipient_count=len(recipients),
                summary=summary,
                delivery_unknown=True,
            )

        claimed_delivery.status = AdministratorSummaryDeliveryStatus.SENT.value
        claimed_delivery.sent_at = now
        claimed_delivery.error_code = None
        session.add(claimed_delivery)
        _record_delivery_event(
            session,
            claimed_delivery,
            recipient_count=len(recipients),
            summary=summary,
        )
        session.commit()
        return AdministratorSummaryProcessingResult(
            AdministratorSummaryProcessingStatus.SENT,
            period_start_utc=claimed_delivery.period_start,
            period_end_utc=claimed_delivery.period_end,
            attempt_count=claimed_delivery.attempt_count,
        )
