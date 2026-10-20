from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import EmailSettings
from postgresql_test_support import (
    POSTGRES_TEST_URL_ENV,
    downgrade,
    temporary_postgres_database,
    upgrade,
)
from services.email_configuration import (
    EmailReadinessStatus,
    EmailSettingsUpdate,
    apply_email_settings_update,
    derive_email_readiness,
    record_email_test_success,
)
from services.secret_encryption import (
    ENCRYPTION_KEY_ENVIRONMENT_VARIABLE,
    decrypt_secret,
)


def test_email_settings_postgresql_migration_and_ciphertext_persistence() -> None:
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL migration tests")

    with temporary_postgres_database("email_settings") as (database_url, engine):
        upgrade(database_url, "20260817_0009")
        # Verify this migration's reversible schema before upgrading to head
        # for current-model encryption/readiness checks. Demo cannot downgrade.
        upgrade(database_url, "20260820_0010")
        assert "email_settings" in inspect(engine).get_table_names()
        downgrade(database_url, "20260817_0009")
        assert "email_settings" not in inspect(engine).get_table_names()
        upgrade(database_url, "head")

        inspector = inspect(engine)
        assert "email_settings" in inspector.get_table_names()
        columns = {
            column["name"]: column for column in inspector.get_columns("email_settings")
        }
        assert {
            "email_settings_id",
            "enabled",
            "smtp_host",
            "smtp_port",
            "smtp_security_mode",
            "smtp_username",
            "smtp_password_ciphertext",
            "from_email",
            "from_display_name",
            "reply_to_email",
            "administrator_recipients",
            "administrator_summary_enabled",
            "administrator_summary_cadence",
            "administrator_summary_daily_send_time",
            "administrator_summary_reporting_timezone_override",
            "administrator_summary_effective_at",
            "last_test_status",
            "last_test_error_code",
            "last_tested_at",
            "created_at",
            "updated_at",
        } == set(columns)
        assert columns["smtp_password_ciphertext"]["type"].__class__.__name__ == "TEXT"

        with engine.connect() as connection:
            seeded_row = connection.execute(
                text(
                    "SELECT email_settings_id, enabled, administrator_recipients "
                    "FROM email_settings"
                )
            ).mappings().one()
        assert seeded_row["email_settings_id"] == 1
        assert seeded_row["enabled"] is False
        assert seeded_row["administrator_recipients"] == []

        environment = {
            ENCRYPTION_KEY_ENVIRONMENT_VARIABLE: Fernet.generate_key().decode("ascii")
        }
        plaintext = "postgres-smtp-password"
        with Session(engine) as session:
            settings = session.get(EmailSettings, 1)
            assert settings is not None
            apply_email_settings_update(
                settings,
                EmailSettingsUpdate(
                    enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=587,
                    smtp_security_mode="starttls",
                    smtp_username="smtp-user",
                    smtp_password=plaintext,
                    from_email="compass@example.com",
                    from_display_name="CompassAQ",
                    administrator_recipients=("alerts@example.com",),
                ),
                encryption_environment=environment,
            )
            record_email_test_success(settings, tested_at=datetime.now(timezone.utc))
            session.commit()
            ciphertext = settings.smtp_password_ciphertext

        assert ciphertext is not None

        with engine.connect() as connection:
            stored_ciphertext = connection.scalar(
                text(
                    "SELECT smtp_password_ciphertext FROM email_settings "
                    "WHERE email_settings_id = 1"
                )
            )
            plaintext_match_count = connection.scalar(
                text(
                    "SELECT count(*) FROM email_settings "
                    "WHERE smtp_password_ciphertext = :plaintext"
                ),
                {"plaintext": plaintext},
            )
        assert stored_ciphertext == ciphertext
        assert stored_ciphertext != plaintext
        assert plaintext_match_count == 0
        assert decrypt_secret(stored_ciphertext, environment=environment) == plaintext

        with Session(engine) as session:
            settings = session.get(EmailSettings, 1)
            assert settings is not None
            assert derive_email_readiness(
                settings,
                encryption_environment=environment,
            ).status is EmailReadinessStatus.READY
            apply_email_settings_update(
                settings,
                EmailSettingsUpdate(
                    enabled=True,
                    smtp_host="smtp.example.com",
                    smtp_port=587,
                    smtp_security_mode="starttls",
                    smtp_username="smtp-user",
                    from_email="compass@example.com",
                    from_display_name="CompassAQ",
                    administrator_recipients=("other-alerts@example.com",),
                ),
                encryption_environment={},
            )
            session.commit()

        with Session(engine) as session:
            settings = session.get(EmailSettings, 1)
            assert settings is not None
            assert settings.smtp_password_ciphertext == ciphertext
            assert settings.last_test_status == "success"

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO email_settings "
                        "(email_settings_id, enabled, administrator_recipients) "
                        "VALUES (2, false, '[]'::json)"
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE email_settings SET smtp_port = 70000 "
                        "WHERE email_settings_id = 1"
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE email_settings SET "
                        "last_test_status = 'success', "
                        "last_test_error_code = 'should_be_null', "
                        "last_tested_at = now() "
                        "WHERE email_settings_id = 1"
                    )
                )

        assert "email_settings" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM email_settings")) == 1
