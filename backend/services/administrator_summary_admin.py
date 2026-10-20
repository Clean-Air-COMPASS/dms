"""Read-only administrator-summary state and preview preparation for the admin API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import os
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import AdministratorSummaryDelivery, EmailSettings, SystemSettings
from services.administrator_summary_collector import build_administrator_summary
from services.administrator_summary_delivery import AdministratorSummaryDeliveryStatus
from services.administrator_summary_domain import (
    AdministratorSummary,
    AdministratorSummaryCadence,
    administrator_summary_environment_label,
    calculate_completed_reporting_window,
)
from services.administrator_summary_renderer import (
    RenderedAdministratorSummaryEmail,
    render_administrator_summary_email,
)
from services.administrator_summary_schedule import (
    AdministratorSummarySchedule,
    DueAdministratorSummaryWindow,
    administrator_summary_schedule_from_settings,
    next_administrator_summary_window,
)
from services.system_settings import resolve_default_language_code
from services.email_configuration import (
    EmailReadinessStatus,
    derive_email_readiness,
)


UTC = timezone.utc


class AdministratorSummaryScheduleStatus(str, Enum):
    SUMMARY_OFF = "summary_off"
    BLOCKED_EMAIL_DELIVERY = "blocked_email_delivery"
    WAITING_FOR_FIRST_SCHEDULED_PERIOD = "waiting_for_first_scheduled_period"
    LAST_SUMMARY_SENT = "last_summary_sent"
    LAST_SUMMARY_FAILED = "last_summary_failed"
    DELIVERY_UNKNOWN = "delivery_unknown"
    DELIVERY_IN_PROGRESS = "delivery_in_progress"


@dataclass(frozen=True)
class AdministratorSummaryOperationalState:
    schedule: AdministratorSummarySchedule
    schedule_status: AdministratorSummaryScheduleStatus
    blocker_codes: tuple[str, ...]
    email_delivery_ready: bool
    next_window: DueAdministratorSummaryWindow | None
    last_delivery: AdministratorSummaryDelivery | None


@dataclass(frozen=True)
class AdministratorSummaryPreview:
    summary: AdministratorSummary
    rendered_email: RenderedAdministratorSummaryEmail


def _summary_language(session: Session) -> str:
    language_code = session.scalar(select(SystemSettings.default_language_code))
    return resolve_default_language_code(language_code)


def latest_administrator_summary_delivery(
    session: Session,
) -> AdministratorSummaryDelivery | None:
    return session.scalar(
        select(AdministratorSummaryDelivery).order_by(
            AdministratorSummaryDelivery.period_end.desc(),
            AdministratorSummaryDelivery.administrator_summary_delivery_id.desc(),
        )
    )


def _delivery_belongs_to_current_schedule(
    delivery: AdministratorSummaryDelivery,
    schedule: AdministratorSummarySchedule,
) -> bool:
    if schedule.effective_at_utc is None:
        return False
    delivery_time = delivery.last_attempted_at or delivery.created_at
    if delivery_time.tzinfo is None or delivery_time.utcoffset() is None:
        delivery_time_utc = delivery_time.replace(tzinfo=UTC)
    else:
        delivery_time_utc = delivery_time.astimezone(UTC)
    return delivery_time_utc >= schedule.effective_at_utc


def administrator_summary_operational_state(
    session: Session,
    settings: EmailSettings,
    *,
    now_utc: datetime,
    system_timezone: str = "UTC",
    environment: Mapping[str, str] | None = None,
) -> AdministratorSummaryOperationalState:
    """Combine saved schedule, Email readiness, and safe delivery history."""
    environment_values = environment if environment is not None else os.environ
    schedule = administrator_summary_schedule_from_settings(
        settings,
        system_timezone=system_timezone,
    )
    readiness = derive_email_readiness(
        settings,
        # Preserve the secret-encryption contract: ``None`` enables the
        # persisted runtime key, while explicit mappings stay deterministic.
        encryption_environment=environment,
    )
    email_delivery_ready = readiness.status is EmailReadinessStatus.READY
    last_delivery = latest_administrator_summary_delivery(session)

    if not schedule.enabled:
        schedule_status = AdministratorSummaryScheduleStatus.SUMMARY_OFF
        blocker_codes: tuple[str, ...] = ()
    elif not email_delivery_ready:
        schedule_status = AdministratorSummaryScheduleStatus.BLOCKED_EMAIL_DELIVERY
        blocker_codes = readiness.reason_codes
    elif last_delivery is None or not _delivery_belongs_to_current_schedule(
        last_delivery,
        schedule,
    ):
        schedule_status = (
            AdministratorSummaryScheduleStatus.WAITING_FOR_FIRST_SCHEDULED_PERIOD
        )
        blocker_codes = ()
    elif last_delivery.status == AdministratorSummaryDeliveryStatus.SENT.value:
        schedule_status = AdministratorSummaryScheduleStatus.LAST_SUMMARY_SENT
        blocker_codes = ()
    elif last_delivery.status == AdministratorSummaryDeliveryStatus.DELIVERY_UNKNOWN.value:
        schedule_status = AdministratorSummaryScheduleStatus.DELIVERY_UNKNOWN
        blocker_codes = ()
    elif last_delivery.status == AdministratorSummaryDeliveryStatus.FAILED.value:
        schedule_status = AdministratorSummaryScheduleStatus.LAST_SUMMARY_FAILED
        blocker_codes = ()
    else:
        schedule_status = AdministratorSummaryScheduleStatus.DELIVERY_IN_PROGRESS
        blocker_codes = ()

    return AdministratorSummaryOperationalState(
        schedule=schedule,
        schedule_status=schedule_status,
        blocker_codes=blocker_codes,
        email_delivery_ready=email_delivery_ready,
        next_window=next_administrator_summary_window(schedule, now_utc=now_utc),
        last_delivery=last_delivery,
    )


def build_administrator_summary_preview(
    session: Session,
    *,
    cadence: AdministratorSummaryCadence | str,
    reporting_timezone: str,
    generated_at_utc: datetime,
    environment: Mapping[str, str] | None = None,
) -> AdministratorSummaryPreview:
    """Build and render one completed window without delivery-side effects."""
    environment_values = environment if environment is not None else os.environ
    reporting_window = calculate_completed_reporting_window(
        generated_at_utc,
        cadence,
        reporting_timezone,
    )
    summary = build_administrator_summary(
        session,
        reporting_window,
        generated_at_utc=generated_at_utc,
        environment_label=administrator_summary_environment_label(environment_values),
        environment=environment_values,
    )
    rendered_email = render_administrator_summary_email(
        summary,
        _summary_language(session),
    )
    return AdministratorSummaryPreview(
        summary=summary,
        rendered_email=rendered_email,
    )
