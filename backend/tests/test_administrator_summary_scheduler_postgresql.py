from __future__ import annotations

from datetime import datetime, time, timezone
import os
from threading import Event as ThreadEvent, Lock, Thread

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import (
    AdministratorSummaryDelivery,
    EmailSettings,
    Event,
    SystemSettings,
)
from postgresql_test_support import (
    POSTGRES_TEST_URL_ENV,
    temporary_postgres_database,
    upgrade,
)
from services.administrator_summary_delivery import (
    AdministratorSummaryProcessingStatus,
    process_due_administrator_summary,
)


UTC = timezone.utc


def test_postgresql_scheduler_delivery_lock_and_restart_idempotency() -> None:
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL scheduler tests")

    with temporary_postgres_database("administrator_summary_scheduler") as (
        database_url,
        engine,
    ):
        upgrade(database_url, "head")
        effective_at = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
        due_at = datetime(2026, 8, 21, 10, 30, tzinfo=UTC)
        with Session(engine) as session:
            settings = session.get(EmailSettings, 1)
            assert settings is not None
            settings.enabled = True
            settings.smtp_host = "smtp.example.com"
            settings.smtp_port = 25
            settings.smtp_security_mode = "none"
            settings.from_email = "compass@example.com"
            settings.administrator_recipients = ["administrator@example.com"]
            settings.last_test_status = "success"
            settings.last_tested_at = effective_at
            settings.administrator_summary_enabled = True
            settings.administrator_summary_cadence = "every_15_minutes"
            settings.administrator_summary_daily_send_time = time(7, 0)
            settings.administrator_summary_reporting_timezone_override = "UTC"
            settings.administrator_summary_effective_at = effective_at
            system_settings = session.scalar(select(SystemSettings))
            if system_settings is None:
                system_settings = SystemSettings()
            system_settings.default_language_code = "es"
            session.add_all([settings, system_settings])
            session.commit()

        send_started = ThreadEvent()
        allow_send_to_finish = ThreadEvent()
        sent_messages: list[dict] = []
        message_lock = Lock()

        class BlockingEmailService:
            def send(self, **message):
                with message_lock:
                    sent_messages.append(message)
                send_started.set()
                assert allow_send_to_finish.wait(timeout=10)

        def email_service_factory(_transport):
            return BlockingEmailService()

        worker_result: list = []

        def first_worker() -> None:
            with Session(engine) as session:
                worker_result.append(
                    process_due_administrator_summary(
                        session,
                        now_utc=due_at,
                        environment={"COMPASSAQ_ENV": "test"},
                        email_service_factory=email_service_factory,
                    )
                )

        worker = Thread(target=first_worker)
        worker.start()
        assert send_started.wait(timeout=10)

        with Session(engine) as competing_session:
            competing_result = process_due_administrator_summary(
                competing_session,
                now_utc=due_at,
                environment={"COMPASSAQ_ENV": "test"},
                email_service_factory=email_service_factory,
            )
        assert competing_result.status is (
            AdministratorSummaryProcessingStatus.LOCK_UNAVAILABLE
        )

        allow_send_to_finish.set()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert worker_result[0].status is AdministratorSummaryProcessingStatus.SENT

        with Session(engine) as restarted_session:
            restarted_result = process_due_administrator_summary(
                restarted_session,
                now_utc=due_at,
                environment={"COMPASSAQ_ENV": "test"},
                email_service_factory=email_service_factory,
            )
            delivery = restarted_session.scalar(
                select(AdministratorSummaryDelivery)
            )
            assert delivery is not None
            assert delivery.status == "sent"
            assert delivery.attempt_count == 1
            assert restarted_result.status is (
                AdministratorSummaryProcessingStatus.ALREADY_SENT
            )
            assert restarted_session.scalar(
                select(func.count()).select_from(AdministratorSummaryDelivery)
            ) == 1
            assert restarted_session.scalar(
                select(func.count()).select_from(Event).where(
                    Event.event_type == "email.administrator_summary.sent"
                )
            ) == 1

        assert len(sent_messages) == 1
        assert "Resumen" in sent_messages[0]["subject"]
        assert "RESUMEN PARA ADMINISTRADORES" in sent_messages[0]["text_body"]
