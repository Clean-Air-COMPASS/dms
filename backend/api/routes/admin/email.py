from __future__ import annotations

from datetime import datetime, time, timezone
import os
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.auth_deps import CurrentUser, get_current_user
from api.user_messages import user_message_detail
from db import get_session
from models import EmailSettings
from services.administrator_summary_admin import (
    AdministratorSummaryPreview,
    AdministratorSummaryScheduleStatus,
    administrator_summary_operational_state,
    build_administrator_summary_preview,
)
from services.administrator_summary_domain import AdministratorSummaryCadence
from services.administrator_summary_schedule import (
    AdministratorSummarySchedule,
    AdministratorSummaryScheduleUpdate,
    AdministratorSummaryScheduleValidationError,
    AdministratorSummaryTimezoneSource,
    administrator_summary_schedule_from_settings,
    apply_administrator_summary_schedule_update,
)
from services.email_configuration import (
    PASSWORD_UNCHANGED,
    EmailConfigurationValidationError,
    EmailReadinessStatus,
    EmailSettingsUpdate,
    PasswordAction,
    SmtpSecurityMode,
    apply_email_settings_update,
    derive_email_readiness,
    email_configuration_issue_codes,
    get_or_create_email_settings,
    normalize_email_address,
    record_email_test_failure,
    record_email_test_success,
)
from services.email_delivery import (
    EmailDeliveryError,
    EmailDeliveryErrorCode,
    EmailService,
    email_transport_configuration_from_settings,
)
from services.event_log import add_event
from services.secret_encryption import SecretEncryptionError
from services.system_settings import get_system_timezone


router = APIRouter(prefix="/admin/email", tags=["admin-email"])


class EmailConfigurationResponse(BaseModel):
    enabled: bool
    status: EmailReadinessStatus
    status_reason_codes: list[str]
    smtp_host: str | None
    smtp_port: int | None
    smtp_security_mode: SmtpSecurityMode | None
    smtp_username: str | None
    password_configured: bool
    from_email: str | None
    from_display_name: str | None
    reply_to_email: str | None
    administrator_recipients: list[str]
    last_test_status: Literal["success", "failed"] | None
    last_test_error_code: str | None
    last_tested_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class EmailConfigurationUpdateRequest(BaseModel):
    # Extra values are rejected explicitly in the route so the error response
    # lists field names without echoing a submitted secret value.
    model_config = ConfigDict(extra="allow")

    enabled: bool
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security_mode: str | None = None
    smtp_username: str | None = None
    smtp_password: Any = Field(
        default=None,
        repr=False,
        json_schema_extra={"type": "string", "format": "password", "nullable": True},
    )
    from_email: str | None = None
    from_display_name: str | None = None
    reply_to_email: str | None = None
    administrator_recipients: list[str] = Field(default_factory=list)


class EmailTestRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    recipient: str | None = None


class EmailTestResponse(BaseModel):
    delivery_status: Literal["sent"]
    recipient: str
    sent_at: datetime


class AdministratorSummaryScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool
    cadence: str
    daily_send_time: time
    reporting_timezone_mode: Literal["system", "override"] | None = None
    reporting_timezone_override: str | None = None
    # Accept the previous request field so older admin clients retain an
    # explicit timezone override during the migration window.
    reporting_timezone: str | None = None


class AdministratorSummaryPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    cadence: str | None = None
    daily_send_time: time | None = None
    reporting_timezone_mode: Literal["system", "override"] | None = None
    reporting_timezone_override: str | None = None
    reporting_timezone: str | None = None


class AdministratorSummaryTestRequest(AdministratorSummaryPreviewRequest):
    recipient: str | None = None


class AdministratorSummaryWindowResponse(BaseModel):
    period_start: datetime
    period_end: datetime


class AdministratorSummaryLastDeliveryResponse(BaseModel):
    status: Literal["sending", "sent", "failed", "delivery_unknown"]
    period_start: datetime
    period_end: datetime
    last_attempted_at: datetime | None
    sent_at: datetime | None
    error_code: str | None


class AdministratorSummaryConfigurationResponse(BaseModel):
    enabled: bool
    cadence: AdministratorSummaryCadence
    daily_send_time: time
    reporting_timezone: str
    reporting_timezone_source: AdministratorSummaryTimezoneSource
    reporting_timezone_override: str | None
    system_timezone: str
    effective_at: datetime | None
    schedule_status: AdministratorSummaryScheduleStatus
    blocker_codes: list[str]
    email_delivery_ready: bool
    next_due_at: datetime | None
    next_reporting_window: AdministratorSummaryWindowResponse | None
    last_scheduled_delivery: AdministratorSummaryLastDeliveryResponse | None


class AdministratorSummaryPreviewResponse(BaseModel):
    reporting_window: AdministratorSummaryWindowResponse
    overall_status: str
    attention_count: int
    subject: str
    html_body: str
    text_body: str


class AdministratorSummaryTestResponse(BaseModel):
    delivery_status: Literal["sent"]
    recipient: str
    sent_at: datetime
    subject: str
    reporting_window: AdministratorSummaryWindowResponse


def _safe_validation_error(
    *,
    error_code: str,
    message: str,
    field: str | None = None,
) -> HTTPException:
    error_context = {"field": field} if field else {}
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=user_message_detail(
            error_code,
            message,
            error_context=error_context,
        ),
    )


def _reject_extra_fields(payload: BaseModel) -> None:
    extra_fields = sorted((payload.model_extra or {}).keys())
    if not extra_fields:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=user_message_detail(
            "unexpected_request_fields",
            "The request contains unsupported fields.",
            error_context={"fields": extra_fields},
        ),
    )


def _password_update_from_request(
    payload: EmailConfigurationUpdateRequest,
):
    if "smtp_password" not in payload.model_fields_set:
        return PASSWORD_UNCHANGED
    if payload.smtp_password is None or isinstance(payload.smtp_password, str):
        return payload.smtp_password
    raise _safe_validation_error(
        error_code="invalid_smtp_password",
        message="SMTP password must be text or null.",
        field="smtp_password",
    )


def _serialize_email_configuration(
    settings: EmailSettings,
) -> EmailConfigurationResponse:
    readiness = derive_email_readiness(settings)
    security_mode = (
        SmtpSecurityMode(settings.smtp_security_mode)
        if settings.smtp_security_mode
        else None
    )
    return EmailConfigurationResponse(
        enabled=bool(settings.enabled),
        status=readiness.status,
        status_reason_codes=list(readiness.reason_codes),
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_security_mode=security_mode,
        smtp_username=settings.smtp_username,
        password_configured=bool(settings.smtp_password_ciphertext),
        from_email=settings.from_email,
        from_display_name=settings.from_display_name,
        reply_to_email=settings.reply_to_email,
        administrator_recipients=list(settings.administrator_recipients or []),
        last_test_status=settings.last_test_status,
        last_test_error_code=settings.last_test_error_code,
        last_tested_at=settings.last_tested_at,
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


def _public_changed_fields(changed_fields: tuple[str, ...]) -> list[str]:
    return [
        "smtp_password" if field == "smtp_password_ciphertext" else field
        for field in changed_fields
    ]


def _password_event_action(
    password_action: PasswordAction,
    *,
    previously_configured: bool,
) -> str | None:
    if password_action is PasswordAction.REPLACED:
        return "replaced" if previously_configured else "configured"
    if password_action is PasswordAction.CLEARED:
        return "cleared"
    return None


@router.get("/configuration", response_model=EmailConfigurationResponse)
def get_email_configuration(
    session: Session = Depends(get_session),
    _current_user: CurrentUser = Depends(get_current_user),
) -> EmailConfigurationResponse:
    settings = get_or_create_email_settings(session)
    session.commit()
    session.refresh(settings)
    return _serialize_email_configuration(settings)


@router.put("/configuration", response_model=EmailConfigurationResponse)
def update_email_configuration(
    payload: EmailConfigurationUpdateRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> EmailConfigurationResponse:
    _reject_extra_fields(payload)
    settings = get_or_create_email_settings(session)
    previously_configured = bool(settings.smtp_password_ciphertext)
    try:
        update_result = apply_email_settings_update(
            settings,
            EmailSettingsUpdate(
                enabled=payload.enabled,
                smtp_host=payload.smtp_host,
                smtp_port=payload.smtp_port,
                smtp_security_mode=payload.smtp_security_mode,
                smtp_username=payload.smtp_username,
                smtp_password=_password_update_from_request(payload),
                from_email=payload.from_email,
                from_display_name=payload.from_display_name,
                reply_to_email=payload.reply_to_email,
                administrator_recipients=payload.administrator_recipients,
            ),
        )
    except EmailConfigurationValidationError as exc:
        session.rollback()
        raise _safe_validation_error(
            error_code=exc.error_code,
            message=str(exc),
            field=exc.field,
        ) from exc
    except SecretEncryptionError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=user_message_detail(
                "smtp_secret_unavailable",
                "The SMTP password cannot be saved because the encryption key is unavailable.",
            ),
        ) from exc

    if update_result.changed_fields:
        readiness = derive_email_readiness(settings)
        event_params: dict[str, object] = {
            "changed_fields": _public_changed_fields(update_result.changed_fields),
            "status": readiness.status.value,
        }
        password_event_action = _password_event_action(
            update_result.password_action,
            previously_configured=previously_configured,
        )
        if password_event_action:
            event_params["password_action"] = password_event_action
        add_event(
            session,
            event_type="email.configuration.updated",
            source="admin.email",
            severity="info",
            message="Email configuration updated",
            params=event_params,
            actor_user_id=current_user.user_id,
            actor_email=current_user.email,
        )

    session.add(settings)
    session.commit()
    session.refresh(settings)
    return _serialize_email_configuration(settings)


def _test_recipient(
    payload: EmailTestRequest,
    settings: EmailSettings,
) -> str:
    if payload.recipient is None:
        if not settings.administrator_recipients:
            raise EmailDeliveryError(
                EmailDeliveryErrorCode.CONFIGURATION_INCOMPLETE,
                configuration_reason_codes=("administrator_recipients_missing",),
            )
        return settings.administrator_recipients[0]
    try:
        recipient = normalize_email_address(
            payload.recipient,
            field="recipient",
        )
    except EmailConfigurationValidationError as exc:
        raise _safe_validation_error(
            error_code=exc.error_code,
            message=str(exc),
            field="recipient",
        ) from exc
    if recipient is None:
        raise _safe_validation_error(
            error_code="invalid_email_address",
            message="Test recipient cannot be empty.",
            field="recipient",
        )
    return recipient


def _delivery_error_status(error: EmailDeliveryError) -> int:
    if error.error_code in {
        EmailDeliveryErrorCode.CONFIGURATION_DISABLED,
        EmailDeliveryErrorCode.CONFIGURATION_INCOMPLETE,
        EmailDeliveryErrorCode.SECRET_UNAVAILABLE,
    }:
        return status.HTTP_409_CONFLICT
    if error.error_code is EmailDeliveryErrorCode.CONNECTION_TIMEOUT:
        return status.HTTP_504_GATEWAY_TIMEOUT
    return status.HTTP_502_BAD_GATEWAY


def _delivery_error_context(error: EmailDeliveryError) -> dict[str, object]:
    context: dict[str, object] = {}
    if error.smtp_code is not None:
        context["smtp_code"] = error.smtp_code
    if error.configuration_reason_codes:
        context["reason_codes"] = list(error.configuration_reason_codes)
    return context


def _record_test_failure_event(
    session: Session,
    *,
    settings: EmailSettings,
    current_user: CurrentUser,
    error: EmailDeliveryError,
    tested_at: datetime,
    update_test_state: bool,
) -> None:
    if update_test_state:
        record_email_test_failure(
            settings,
            tested_at=tested_at,
            error_code=error.error_code.value,
        )
    event_params: dict[str, object] = {"error_code": error.error_code.value}
    if error.smtp_code is not None:
        event_params["smtp_code"] = error.smtp_code
    add_event(
        session,
        event_type="email.test.failed",
        source="admin.email",
        severity="warning",
        message=str(error),
        params=event_params,
        actor_user_id=current_user.user_id,
        actor_email=current_user.email,
    )
    session.add(settings)
    session.commit()


def _raise_recorded_delivery_error(
    session: Session,
    *,
    settings: EmailSettings,
    current_user: CurrentUser,
    error: EmailDeliveryError,
    tested_at: datetime,
    update_test_state: bool = True,
) -> None:
    _record_test_failure_event(
        session,
        settings=settings,
        current_user=current_user,
        error=error,
        tested_at=tested_at,
        update_test_state=update_test_state,
    )
    raise HTTPException(
        status_code=_delivery_error_status(error),
        detail=user_message_detail(
            error.error_code.value,
            str(error),
            error_context=_delivery_error_context(error),
        ),
    )


@router.post("/test", response_model=EmailTestResponse)
def send_test_email(
    payload: EmailTestRequest | None = Body(default=None),
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> EmailTestResponse:
    payload = payload or EmailTestRequest()
    _reject_extra_fields(payload)
    settings = get_or_create_email_settings(session)
    tested_at = datetime.now(timezone.utc)

    if not settings.enabled:
        _raise_recorded_delivery_error(
            session,
            settings=settings,
            current_user=current_user,
            error=EmailDeliveryError(EmailDeliveryErrorCode.CONFIGURATION_DISABLED),
            tested_at=tested_at,
            update_test_state=False,
        )

    issue_codes = email_configuration_issue_codes(
        settings,
        verify_secret=False,
        require_administrator_recipients=True,
    )
    if issue_codes:
        _raise_recorded_delivery_error(
            session,
            settings=settings,
            current_user=current_user,
            error=EmailDeliveryError(
                EmailDeliveryErrorCode.CONFIGURATION_INCOMPLETE,
                configuration_reason_codes=issue_codes,
            ),
            tested_at=tested_at,
        )

    recipient = _test_recipient(payload, settings)
    try:
        transport_configuration = email_transport_configuration_from_settings(settings)
        email_service = EmailService(transport_configuration)
        sent_at_text = tested_at.isoformat()
        email_service.send(
            recipients=(recipient,),
            subject="[CompassAQ] Email delivery test",
            text_body=(
                "This is a CompassAQ email delivery test.\n\n"
                f"Sent at {sent_at_text}."
            ),
            html_body=(
                "<p>This is a <strong>CompassAQ</strong> email delivery test.</p>"
                f"<p>Sent at {sent_at_text}.</p>"
            ),
        )
    except EmailDeliveryError as error:
        _raise_recorded_delivery_error(
            session,
            settings=settings,
            current_user=current_user,
            error=error,
            tested_at=tested_at,
        )

    record_email_test_success(settings, tested_at=tested_at)
    add_event(
        session,
        event_type="email.test.sent",
        source="admin.email",
        severity="info",
        message="Test email sent successfully",
        params={"status": "success"},
        actor_user_id=current_user.user_id,
        actor_email=current_user.email,
    )
    session.add(settings)
    session.commit()
    return EmailTestResponse(
        delivery_status="sent",
        recipient=recipient,
        sent_at=tested_at,
    )


def _normalize_database_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _administrator_summary_window_response(
    *,
    period_start: datetime,
    period_end: datetime,
) -> AdministratorSummaryWindowResponse:
    return AdministratorSummaryWindowResponse(
        period_start=_normalize_database_datetime(period_start),
        period_end=_normalize_database_datetime(period_end),
    )


def _serialize_administrator_summary_configuration(
    session: Session,
    settings: EmailSettings,
    *,
    now_utc: datetime,
    system_timezone: str | None = None,
) -> AdministratorSummaryConfigurationResponse:
    effective_system_timezone = system_timezone or get_system_timezone(session)
    operational_state = administrator_summary_operational_state(
        session,
        settings,
        now_utc=now_utc,
        system_timezone=effective_system_timezone,
    )
    next_window = operational_state.next_window
    last_delivery = operational_state.last_delivery
    return AdministratorSummaryConfigurationResponse(
        enabled=operational_state.schedule.enabled,
        cadence=operational_state.schedule.cadence,
        daily_send_time=operational_state.schedule.daily_send_time,
        reporting_timezone=operational_state.schedule.reporting_timezone,
        reporting_timezone_source=operational_state.schedule.reporting_timezone_source,
        reporting_timezone_override=operational_state.schedule.reporting_timezone_override,
        system_timezone=effective_system_timezone,
        effective_at=operational_state.schedule.effective_at_utc,
        schedule_status=operational_state.schedule_status,
        blocker_codes=list(operational_state.blocker_codes),
        email_delivery_ready=operational_state.email_delivery_ready,
        next_due_at=next_window.due_at_utc if next_window else None,
        next_reporting_window=(
            _administrator_summary_window_response(
                period_start=next_window.reporting_window.period_start_utc,
                period_end=next_window.reporting_window.period_end_utc,
            )
            if next_window
            else None
        ),
        last_scheduled_delivery=(
            AdministratorSummaryLastDeliveryResponse(
                status=last_delivery.status,
                period_start=_normalize_database_datetime(last_delivery.period_start),
                period_end=_normalize_database_datetime(last_delivery.period_end),
                last_attempted_at=_normalize_database_datetime(
                    last_delivery.last_attempted_at
                ),
                sent_at=_normalize_database_datetime(last_delivery.sent_at),
                error_code=last_delivery.error_code,
            )
            if last_delivery
            else None
        ),
    )


def _raise_schedule_validation_error(
    error: AdministratorSummaryScheduleValidationError,
) -> None:
    raise _safe_validation_error(
        error_code=error.error_code,
        message=str(error),
        field=error.field,
    ) from error


def _public_administrator_summary_changed_fields(
    changed_fields: tuple[str, ...],
) -> list[str]:
    public_names = {
        "administrator_summary_enabled": "enabled",
        "administrator_summary_cadence": "cadence",
        "administrator_summary_daily_send_time": "daily_send_time",
        "administrator_summary_reporting_timezone_override": "reporting_timezone_override",
    }
    return [public_names[field] for field in changed_fields]


def _requested_reporting_timezone_override(
    payload: AdministratorSummaryPreviewRequest | AdministratorSummaryScheduleRequest,
    *,
    fallback: str | None,
) -> str | None:
    """Translate the explicit UI mode into a nullable persisted override."""
    legacy_override = payload.reporting_timezone
    requested_override = payload.reporting_timezone_override
    if payload.reporting_timezone_mode == "system":
        return None
    if payload.reporting_timezone_mode == "override":
        return requested_override if requested_override is not None else legacy_override
    if requested_override is not None:
        return requested_override
    if legacy_override is not None:
        return legacy_override
    return fallback


def _summary_schedule_update(
    payload: AdministratorSummaryScheduleRequest,
) -> AdministratorSummaryScheduleUpdate:
    requested_override = _requested_reporting_timezone_override(payload, fallback=None)
    if payload.reporting_timezone_mode == "override" and requested_override is None:
        raise _safe_validation_error(
            error_code="invalid_administrator_summary_reporting_timezone",
            message="An explicit reporting timezone is required for an override.",
            field="reporting_timezone_override",
        )
    return AdministratorSummaryScheduleUpdate(
        enabled=payload.enabled,
        cadence=payload.cadence,
        daily_send_time=payload.daily_send_time,
        reporting_timezone_override=requested_override,
    )


def _validated_preview_schedule(
    settings: EmailSettings,
    payload: AdministratorSummaryPreviewRequest,
    *,
    validated_at_utc: datetime,
    system_timezone: str,
) -> AdministratorSummarySchedule:
    saved_schedule = administrator_summary_schedule_from_settings(
        settings,
        system_timezone=system_timezone,
    )
    transient_settings = EmailSettings(
        email_settings_id=settings.email_settings_id,
        administrator_summary_enabled=True,
        administrator_summary_cadence=saved_schedule.cadence.value,
        administrator_summary_daily_send_time=saved_schedule.daily_send_time,
        administrator_summary_reporting_timezone_override=(
            saved_schedule.reporting_timezone_override
        ),
        administrator_summary_effective_at=saved_schedule.effective_at_utc,
    )
    requested_override = _requested_reporting_timezone_override(
        payload,
        fallback=saved_schedule.reporting_timezone_override,
    )
    if payload.reporting_timezone_mode == "override" and requested_override is None:
        raise _safe_validation_error(
            error_code="invalid_administrator_summary_reporting_timezone",
            message="An explicit reporting timezone is required for an override.",
            field="reporting_timezone_override",
        )
    try:
        apply_administrator_summary_schedule_update(
            transient_settings,
            AdministratorSummaryScheduleUpdate(
                enabled=True,
                cadence=payload.cadence or saved_schedule.cadence,
                daily_send_time=payload.daily_send_time or saved_schedule.daily_send_time,
                reporting_timezone_override=requested_override,
            ),
            changed_at_utc=validated_at_utc,
            system_timezone=system_timezone,
        )
    except AdministratorSummaryScheduleValidationError as error:
        _raise_schedule_validation_error(error)
    return administrator_summary_schedule_from_settings(
        transient_settings,
        system_timezone=system_timezone,
    )


def _serialize_administrator_summary_preview(
    preview: AdministratorSummaryPreview,
) -> AdministratorSummaryPreviewResponse:
    reporting_window = preview.summary.reporting_window
    return AdministratorSummaryPreviewResponse(
        reporting_window=_administrator_summary_window_response(
            period_start=reporting_window.period_start_utc,
            period_end=reporting_window.period_end_utc,
        ),
        overall_status=preview.summary.overall_status.value,
        attention_count=preview.summary.attention_item_count,
        subject=preview.rendered_email.subject,
        html_body=preview.rendered_email.html_body,
        text_body=preview.rendered_email.text_body,
    )


@router.get(
    "/administrator-summary",
    response_model=AdministratorSummaryConfigurationResponse,
)
def get_administrator_summary_configuration(
    session: Session = Depends(get_session),
    _current_user: CurrentUser = Depends(get_current_user),
) -> AdministratorSummaryConfigurationResponse:
    settings = get_or_create_email_settings(session)
    system_timezone = get_system_timezone(session)
    session.commit()
    session.refresh(settings)
    return _serialize_administrator_summary_configuration(
        session,
        settings,
        now_utc=datetime.now(timezone.utc),
        system_timezone=system_timezone,
    )


@router.put(
    "/administrator-summary",
    response_model=AdministratorSummaryConfigurationResponse,
)
def update_administrator_summary_configuration(
    payload: AdministratorSummaryScheduleRequest,
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> AdministratorSummaryConfigurationResponse:
    _reject_extra_fields(payload)
    settings = get_or_create_email_settings(session)
    system_timezone = get_system_timezone(session)
    changed_at = datetime.now(timezone.utc)
    try:
        changed_fields = apply_administrator_summary_schedule_update(
            settings,
            _summary_schedule_update(payload),
            changed_at_utc=changed_at,
            system_timezone=system_timezone,
        )
    except AdministratorSummaryScheduleValidationError as error:
        session.rollback()
        _raise_schedule_validation_error(error)

    session.add(settings)
    if changed_fields:
        resulting_state = administrator_summary_operational_state(
            session,
            settings,
            now_utc=changed_at,
            system_timezone=system_timezone,
        )
        add_event(
            session,
            event_type="email.administrator_summary.schedule.updated",
            source="admin.email",
            severity="info",
            message="Administrator summary schedule updated",
            params={
                "changed_fields": _public_administrator_summary_changed_fields(
                    changed_fields
                ),
                "schedule_status": resulting_state.schedule_status,
            },
            actor_user_id=current_user.user_id,
            actor_email=current_user.email,
        )
    session.commit()
    session.refresh(settings)
    return _serialize_administrator_summary_configuration(
        session,
        settings,
        now_utc=changed_at,
        system_timezone=system_timezone,
    )


@router.post(
    "/administrator-summary/preview",
    response_model=AdministratorSummaryPreviewResponse,
)
def preview_administrator_summary(
    payload: AdministratorSummaryPreviewRequest | None = Body(default=None),
    session: Session = Depends(get_session),
    _current_user: CurrentUser = Depends(get_current_user),
) -> AdministratorSummaryPreviewResponse:
    payload = payload or AdministratorSummaryPreviewRequest()
    _reject_extra_fields(payload)
    settings = get_or_create_email_settings(session)
    system_timezone = get_system_timezone(session)
    generated_at = datetime.now(timezone.utc)
    preview_schedule = _validated_preview_schedule(
        settings,
        payload,
        validated_at_utc=generated_at,
        system_timezone=system_timezone,
    )
    try:
        preview = build_administrator_summary_preview(
            session,
            cadence=preview_schedule.cadence,
            reporting_timezone=preview_schedule.reporting_timezone,
            generated_at_utc=generated_at,
            environment=os.environ,
        )
    except Exception as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=user_message_detail(
                "administrator_summary_build_failed",
                "The administrator summary could not be built.",
            ),
        ) from error
    session.rollback()
    return _serialize_administrator_summary_preview(preview)


def _record_administrator_summary_test_event(
    session: Session,
    *,
    current_user: CurrentUser,
    event_type: str,
    severity: str,
    error_code: str | None = None,
    preview: AdministratorSummaryPreview | None = None,
) -> None:
    params: dict[str, object] = {}
    if error_code:
        params["error_code"] = error_code
    if preview:
        reporting_window = preview.summary.reporting_window
        params.update(
            {
                "period_start": reporting_window.period_start_utc.isoformat(),
                "period_end": reporting_window.period_end_utc.isoformat(),
                "cadence": reporting_window.cadence.value,
                "reporting_timezone": reporting_window.reporting_timezone,
                "attention_item_count": preview.summary.attention_item_count,
            }
        )
    add_event(
        session,
        event_type=event_type,
        source="admin.email",
        severity=severity,
        message=(
            "Administrator summary test sent"
            if event_type.endswith(".sent")
            else "Administrator summary test failed"
        ),
        params=params,
        actor_user_id=current_user.user_id,
        actor_email=current_user.email,
    )
    session.commit()


@router.post(
    "/administrator-summary/test",
    response_model=AdministratorSummaryTestResponse,
)
def send_administrator_summary_test(
    payload: AdministratorSummaryTestRequest | None = Body(default=None),
    session: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> AdministratorSummaryTestResponse:
    payload = payload or AdministratorSummaryTestRequest()
    _reject_extra_fields(payload)
    settings = get_or_create_email_settings(session)
    system_timezone = get_system_timezone(session)
    sent_at = datetime.now(timezone.utc)
    operational_state = administrator_summary_operational_state(
        session,
        settings,
        now_utc=sent_at,
        system_timezone=system_timezone,
    )
    if not operational_state.email_delivery_ready:
        error = EmailDeliveryError(
            EmailDeliveryErrorCode.CONFIGURATION_INCOMPLETE,
            configuration_reason_codes=operational_state.blocker_codes,
        )
        _record_administrator_summary_test_event(
            session,
            current_user=current_user,
            event_type="email.administrator_summary.test.failed",
            severity="warning",
            error_code=error.error_code.value,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=user_message_detail(
                error.error_code.value,
                str(error),
                error_context=_delivery_error_context(error),
            ),
        )

    try:
        recipient = _test_recipient(payload, settings)
        preview_schedule = _validated_preview_schedule(
            settings,
            payload,
            validated_at_utc=sent_at,
            system_timezone=system_timezone,
        )
        preview = build_administrator_summary_preview(
            session,
            cadence=preview_schedule.cadence,
            reporting_timezone=preview_schedule.reporting_timezone,
            generated_at_utc=sent_at,
            environment=os.environ,
        )
        transport = email_transport_configuration_from_settings(settings)
        email_service = EmailService(transport)
        test_subject = f"[TEST] {preview.rendered_email.subject}"
        email_service.send(
            recipients=(recipient,),
            subject=test_subject,
            text_body=preview.rendered_email.text_body,
            html_body=preview.rendered_email.html_body,
        )
    except EmailDeliveryError as error:
        _record_administrator_summary_test_event(
            session,
            current_user=current_user,
            event_type="email.administrator_summary.test.failed",
            severity="warning",
            error_code=error.error_code.value,
        )
        raise HTTPException(
            status_code=_delivery_error_status(error),
            detail=user_message_detail(
                error.error_code.value,
                str(error),
                error_context=_delivery_error_context(error),
            ),
        ) from error
    except HTTPException:
        raise
    except Exception as error:
        _record_administrator_summary_test_event(
            session,
            current_user=current_user,
            event_type="email.administrator_summary.test.failed",
            severity="warning",
            error_code="administrator_summary_build_failed",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=user_message_detail(
                "administrator_summary_build_failed",
                "The administrator summary test could not be built or sent.",
            ),
        ) from error

    _record_administrator_summary_test_event(
        session,
        current_user=current_user,
        event_type="email.administrator_summary.test.sent",
        severity="info",
        preview=preview,
    )
    reporting_window = preview.summary.reporting_window
    return AdministratorSummaryTestResponse(
        delivery_status="sent",
        recipient=recipient,
        sent_at=sent_at,
        subject=test_subject,
        reporting_window=_administrator_summary_window_response(
            period_start=reporting_window.period_start_utc,
            period_end=reporting_window.period_end_utc,
        ),
    )
