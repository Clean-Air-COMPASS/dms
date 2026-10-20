from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from models import (
    AdministratorSummaryDelivery,
    Base,
    EmailSettings,
    Event,
    SystemSettings,
)
from services.administrator_summary_delivery import (
    AdministratorSummaryDeliveryAction,
    AdministratorSummaryDeliveryStatus,
    AdministratorSummaryProcessingStatus,
    determine_administrator_summary_delivery_action,
    process_due_administrator_summary,
)
from services import administrator_summary_delivery
from services.email_delivery import EmailDeliveryError, EmailDeliveryErrorCode
from services.secret_encryption import encrypt_secret


UTC = timezone.utc
EFFECTIVE_AT = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
FIRST_DUE = datetime(2026, 8, 21, 10, 30, tzinfo=UTC)


@contextmanager
def _acquired_lock(_engine, _key):
    yield True


class RecordingEmailService:
    def __init__(self, sent_messages: list[dict], failures: list[EmailDeliveryError]):
        self.sent_messages = sent_messages
        self.failures = failures

    def send(self, **message):
        self.sent_messages.append(message)
        if self.failures:
            raise self.failures.pop(0)


def _email_service_factory(
    sent_messages: list[dict],
    failures: list[EmailDeliveryError] | None = None,
):
    remaining_failures = list(failures or [])

    def factory(_transport):
        return RecordingEmailService(sent_messages, remaining_failures)

    return factory


def _session_factory(tmp_path, *, language: str | None = "en"):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'summary.sqlite'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        session.add(
            EmailSettings(
                email_settings_id=1,
                enabled=True,
                smtp_host="smtp.example.com",
                smtp_port=25,
                smtp_security_mode="none",
                from_email="compass@example.com",
                administrator_recipients=["administrator@example.com"],
                administrator_summary_enabled=True,
                administrator_summary_cadence="every_15_minutes",
                administrator_summary_daily_send_time=time(7, 0),
                administrator_summary_reporting_timezone_override="UTC",
                administrator_summary_effective_at=EFFECTIVE_AT,
                last_test_status="success",
                last_tested_at=EFFECTIVE_AT,
            )
        )
        session.add(SystemSettings(default_language_code=language))
        session.commit()
    return SessionLocal


def _process(session: Session, sent_messages: list[dict], *, now=FIRST_DUE, failures=None):
    return process_due_administrator_summary(
        session,
        now_utc=now,
        environment={"COMPASSAQ_ENV": "test"},
        lock_context_factory=_acquired_lock,
        email_service_factory=_email_service_factory(sent_messages, failures),
    )


@pytest.mark.parametrize(
    "error_code",
    [
        EmailDeliveryErrorCode.DNS_FAILURE.value,
        EmailDeliveryErrorCode.CONNECTION_TIMEOUT.value,
        EmailDeliveryErrorCode.CONNECTION_FAILED.value,
    ],
)
def test_only_pre_acceptance_connection_errors_are_retryable(error_code) -> None:
    delivery = AdministratorSummaryDelivery(
        period_start=datetime(2026, 8, 21, 10, 15, tzinfo=UTC),
        period_end=FIRST_DUE,
        cadence="every_15_minutes",
        reporting_timezone="UTC",
        status="failed",
        attempt_count=1,
        last_attempted_at=FIRST_DUE,
        error_code=error_code,
    )

    assert determine_administrator_summary_delivery_action(
        delivery,
        now_utc=FIRST_DUE + timedelta(minutes=5),
    ) is AdministratorSummaryDeliveryAction.CLAIM


@pytest.mark.parametrize(
    "error_code",
    [
        EmailDeliveryErrorCode.AUTHENTICATION_FAILED.value,
        EmailDeliveryErrorCode.TLS_ERROR.value,
        EmailDeliveryErrorCode.CONFIGURATION_INCOMPLETE.value,
        EmailDeliveryErrorCode.SECRET_UNAVAILABLE.value,
        EmailDeliveryErrorCode.SENDER_REJECTED.value,
        EmailDeliveryErrorCode.RECIPIENT_REJECTED.value,
        EmailDeliveryErrorCode.RELAY_DENIED.value,
        EmailDeliveryErrorCode.INVALID_MESSAGE.value,
        EmailDeliveryErrorCode.SERVER_DISCONNECTED.value,
        EmailDeliveryErrorCode.SERVER_ERROR.value,
    ],
)
def test_other_delivery_failures_are_never_automatically_retried(error_code) -> None:
    delivery = AdministratorSummaryDelivery(
        period_start=datetime(2026, 8, 21, 10, 15, tzinfo=UTC),
        period_end=FIRST_DUE,
        cadence="every_15_minutes",
        reporting_timezone="UTC",
        status="failed",
        attempt_count=1,
        last_attempted_at=FIRST_DUE,
        error_code=error_code,
    )

    assert determine_administrator_summary_delivery_action(
        delivery,
        now_utc=FIRST_DUE + timedelta(hours=1),
    ) is AdministratorSummaryDeliveryAction.OBSERVE_EXISTING


@pytest.mark.parametrize(
    ("settings_change", "expected_status"),
    [
        (
            lambda settings: setattr(
                settings, "administrator_summary_enabled", False
            ),
            AdministratorSummaryProcessingStatus.SUMMARY_DISABLED,
        ),
        (
            lambda settings: setattr(settings, "enabled", False),
            AdministratorSummaryProcessingStatus.EMAIL_NOT_READY,
        ),
        (
            lambda settings: setattr(settings, "administrator_recipients", []),
            AdministratorSummaryProcessingStatus.RECIPIENTS_MISSING,
        ),
        (
            lambda settings: setattr(settings, "last_test_status", None),
            AdministratorSummaryProcessingStatus.EMAIL_NOT_READY,
        ),
    ],
)
def test_persistent_configuration_blockers_do_not_send_or_create_events(
    tmp_path,
    settings_change,
    expected_status,
) -> None:
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []
    with SessionLocal() as session:
        settings = session.get(EmailSettings, 1)
        settings_change(settings)
        if settings.last_test_status is None:
            settings.last_test_error_code = None
            settings.last_tested_at = None
        session.commit()

        result = _process(session, sent_messages)

        assert result.status is expected_status
        assert session.scalar(
            select(func.count()).select_from(AdministratorSummaryDelivery)
        ) == 0
        assert session.scalar(select(func.count()).select_from(Event)) == 0
    assert sent_messages == []


@pytest.mark.parametrize(
    ("language", "expected_subject_word", "expected_title"),
    [
        ("en", "Summary", "COMPASSAQ ADMINISTRATOR SUMMARY"),
        ("es", "Resumen", "RESUMEN PARA ADMINISTRADORES DE COMPASSAQ"),
        (None, "Summary", "COMPASSAQ ADMINISTRATOR SUMMARY"),
    ],
)
def test_scheduled_send_integrates_language_renderer_and_safe_event(
    tmp_path,
    language,
    expected_subject_word,
    expected_title,
) -> None:
    SessionLocal = _session_factory(tmp_path, language=language)
    sent_messages: list[dict] = []
    with SessionLocal() as session:
        settings = session.get(EmailSettings, 1)
        readiness_state = (
            settings.last_test_status,
            settings.last_test_error_code,
            settings.last_tested_at,
        )

        result = _process(session, sent_messages)

        assert result.status is AdministratorSummaryProcessingStatus.SENT
        assert len(sent_messages) == 1
        assert expected_subject_word in sent_messages[0]["subject"]
        assert expected_title in sent_messages[0]["text_body"]
        session.refresh(settings)
        assert (
            settings.last_test_status,
            settings.last_test_error_code,
            settings.last_tested_at,
        ) == readiness_state

        event = session.scalar(
            select(Event).where(
                Event.event_type == "email.administrator_summary.sent"
            )
        )
        assert event is not None
        serialized_event = json.dumps(event.params, sort_keys=True)
        assert "administrator@example.com" not in serialized_event
        assert "text_body" not in serialized_event
        assert "html_body" not in serialized_event
        assert "smtp.example.com" not in serialized_event
        assert event.params["recipient_count"] == 1


def test_sent_period_survives_restart_and_never_resends(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []
    with SessionLocal() as session:
        first = _process(session, sent_messages)
    with SessionLocal() as restarted_session:
        restarted = _process(restarted_session, sent_messages)

        assert first.status is AdministratorSummaryProcessingStatus.SENT
        assert restarted.status is AdministratorSummaryProcessingStatus.ALREADY_SENT
        assert restarted_session.scalar(
            select(func.count()).select_from(AdministratorSummaryDelivery)
        ) == 1
    assert len(sent_messages) == 1


def test_scheduled_send_uses_persisted_runtime_encryption_key(
    tmp_path,
    monkeypatch,
) -> None:
    runtime_data_dir = tmp_path / "runtime"
    monkeypatch.setenv("COMPASSAQ_DATA_DIR", str(runtime_data_dir))
    monkeypatch.delenv("COMPASSAQ_ENCRYPTION_KEY", raising=False)
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []

    with SessionLocal() as session:
        settings = session.get(EmailSettings, 1)
        settings.smtp_security_mode = "starttls"
        settings.smtp_port = 587
        settings.smtp_username = "smtp-user"
        settings.smtp_password_ciphertext = encrypt_secret("smtp-password")
        session.commit()

        result = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE,
            lock_context_factory=_acquired_lock,
            email_service_factory=_email_service_factory(sent_messages),
        )

        assert result.status is AdministratorSummaryProcessingStatus.SENT
        assert (runtime_data_dir / "encryption_key").is_file()
    assert len(sent_messages) == 1


def test_retryable_failure_waits_five_minutes_and_allows_only_one_retry(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []
    failure = EmailDeliveryError(EmailDeliveryErrorCode.DNS_FAILURE)
    factory = _email_service_factory(sent_messages, [failure])

    with SessionLocal() as session:
        first = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE,
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )
        too_soon = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE + timedelta(minutes=4, seconds=59),
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )
        retry = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE + timedelta(minutes=5),
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )
        after_success = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE + timedelta(minutes=6),
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )

        delivery = session.scalar(select(AdministratorSummaryDelivery))
        assert first.status is AdministratorSummaryProcessingStatus.FAILED
        assert too_soon.status is AdministratorSummaryProcessingStatus.RETRY_WAITING
        assert retry.status is AdministratorSummaryProcessingStatus.SENT
        assert after_success.status is AdministratorSummaryProcessingStatus.ALREADY_SENT
        assert delivery.attempt_count == 2
        assert delivery.status == AdministratorSummaryDeliveryStatus.SENT.value
    assert len(sent_messages) == 2


def test_second_retryable_failure_exhausts_two_attempt_limit(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []
    factory = _email_service_factory(
        sent_messages,
        [
            EmailDeliveryError(EmailDeliveryErrorCode.CONNECTION_TIMEOUT),
            EmailDeliveryError(EmailDeliveryErrorCode.CONNECTION_TIMEOUT),
        ],
    )
    with SessionLocal() as session:
        _ = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE,
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )
        second = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE + timedelta(minutes=5),
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )
        third = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE + timedelta(minutes=6),
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )

        delivery = session.scalar(select(AdministratorSummaryDelivery))
        assert second.status is AdministratorSummaryProcessingStatus.FAILED
        assert third.status is AdministratorSummaryProcessingStatus.FAILED_NO_RETRY
        assert delivery.attempt_count == 2
    assert len(sent_messages) == 2


def test_non_retryable_failure_is_not_attempted_again(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []
    factory = _email_service_factory(
        sent_messages,
        [EmailDeliveryError(EmailDeliveryErrorCode.AUTHENTICATION_FAILED)],
    )
    with SessionLocal() as session:
        first = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE,
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )
        later = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE + timedelta(minutes=6),
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )

        assert first.status is AdministratorSummaryProcessingStatus.FAILED
        assert later.status is AdministratorSummaryProcessingStatus.FAILED_NO_RETRY
        delivery = session.scalar(select(AdministratorSummaryDelivery))
        assert delivery.attempt_count == 1
        assert delivery.error_code == "smtp_authentication_failed"
        failure_event = session.scalar(
            select(Event).where(
                Event.event_type == "email.administrator_summary.failed"
            )
        )
        assert failure_event is not None
        assert failure_event.params["error_code"] == "smtp_authentication_failed"
        assert "administrator@example.com" not in json.dumps(failure_event.params)
    assert len(sent_messages) == 1


def test_ambiguous_smtp_acceptance_becomes_delivery_unknown(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []
    factory = _email_service_factory(
        sent_messages,
        [EmailDeliveryError(EmailDeliveryErrorCode.SERVER_DISCONNECTED)],
    )
    with SessionLocal() as session:
        first = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE,
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )
        later = process_due_administrator_summary(
            session,
            now_utc=FIRST_DUE + timedelta(minutes=6),
            lock_context_factory=_acquired_lock,
            email_service_factory=factory,
        )

        assert first.status is AdministratorSummaryProcessingStatus.DELIVERY_UNKNOWN
        assert later.status is AdministratorSummaryProcessingStatus.DELIVERY_UNKNOWN
        assert session.scalar(
            select(func.count()).select_from(Event).where(
                Event.event_type
                == "email.administrator_summary.delivery_unknown"
            )
        ) == 1
    assert len(sent_messages) == 1


def test_sending_left_by_restart_becomes_delivery_unknown_immediately(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []
    with SessionLocal() as session:
        session.add(
            AdministratorSummaryDelivery(
                period_start=datetime(2026, 8, 21, 10, 15, tzinfo=UTC),
                period_end=FIRST_DUE,
                cadence="every_15_minutes",
                reporting_timezone="UTC",
                status="sending",
                attempt_count=1,
                last_attempted_at=FIRST_DUE - timedelta(minutes=1),
            )
        )
        session.commit()

        result = _process(session, sent_messages)

        delivery = session.scalar(select(AdministratorSummaryDelivery))
        assert result.status is AdministratorSummaryProcessingStatus.DELIVERY_UNKNOWN
        assert delivery.status == "delivery_unknown"
        assert delivery.error_code == "stale_sending_after_restart"
    assert sent_messages == []


def test_old_failed_short_interval_does_not_delay_current_window(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []
    with SessionLocal() as session:
        session.add(
            AdministratorSummaryDelivery(
                period_start=datetime(2026, 8, 21, 10, 15, tzinfo=UTC),
                period_end=FIRST_DUE,
                cadence="every_15_minutes",
                reporting_timezone="UTC",
                status="failed",
                attempt_count=1,
                last_attempted_at=FIRST_DUE,
                error_code="smtp_dns_failure",
            )
        )
        session.commit()

        result = _process(
            session,
            sent_messages,
            now=datetime(2026, 8, 21, 10, 45, tzinfo=UTC),
        )

        deliveries = session.scalars(
            select(AdministratorSummaryDelivery).order_by(
                AdministratorSummaryDelivery.period_start
            )
        ).all()
        assert result.status is AdministratorSummaryProcessingStatus.SENT
        assert len(deliveries) == 2
        assert deliveries[0].status == "failed"
        assert deliveries[1].status == "sent"
    assert len(sent_messages) == 1


def test_reporting_window_identity_is_unique(tmp_path) -> None:
    SessionLocal = _session_factory(tmp_path)
    delivery_values = {
        "period_start": datetime(2026, 8, 21, 10, 15, tzinfo=UTC),
        "period_end": FIRST_DUE,
        "cadence": "every_15_minutes",
        "reporting_timezone": "UTC",
        "status": "failed",
        "attempt_count": 1,
        "last_attempted_at": FIRST_DUE,
        "error_code": "smtp_dns_failure",
    }
    with SessionLocal() as session:
        session.add(AdministratorSummaryDelivery(**delivery_values))
        session.commit()
        session.add(AdministratorSummaryDelivery(**delivery_values))
        with pytest.raises(IntegrityError):
            session.commit()


def test_unique_conflict_reloads_and_observes_winning_delivery(
    tmp_path,
    monkeypatch,
) -> None:
    SessionLocal = _session_factory(tmp_path)
    sent_messages: list[dict] = []

    def insert_winning_delivery(session, *, reporting_window, now_utc, **_kwargs):
        session.add(
            AdministratorSummaryDelivery(
                period_start=reporting_window.period_start_utc,
                period_end=reporting_window.period_end_utc,
                cadence=reporting_window.cadence.value,
                reporting_timezone=reporting_window.reporting_timezone,
                status="sending",
                attempt_count=1,
                last_attempted_at=now_utc,
            )
        )
        session.commit()
        return None

    monkeypatch.setattr(
        administrator_summary_delivery,
        "_claim_delivery",
        insert_winning_delivery,
    )
    with SessionLocal() as session:
        result = _process(session, sent_messages)

        assert result.status is (
            AdministratorSummaryProcessingStatus.DELIVERY_IN_PROGRESS
        )
        assert session.scalar(
            select(func.count()).select_from(AdministratorSummaryDelivery)
        ) == 1
    assert sent_messages == []
