from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Base, EmailSettings
from services.email_configuration import (
    PASSWORD_UNCHANGED,
    EmailConfigurationValidationError,
    EmailReadinessStatus,
    EmailSettingsUpdate,
    PasswordAction,
    apply_email_settings_update,
    derive_email_readiness,
    get_or_create_email_settings,
    normalize_email_settings_update,
    record_email_test_failure,
    record_email_test_success,
)
from services.secret_encryption import (
    ENCRYPTION_KEY_ENVIRONMENT_VARIABLE,
    SecretEncryptionError,
    decrypt_secret,
    encrypt_secret,
)


def _encryption_environment() -> dict[str, str]:
    return {
        ENCRYPTION_KEY_ENVIRONMENT_VARIABLE: Fernet.generate_key().decode("ascii")
    }


def _complete_update(
    *,
    enabled: bool = True,
    smtp_password=PASSWORD_UNCHANGED,
    administrator_recipients: tuple[str, ...] = ("alerts@example.com",),
    **overrides,
) -> EmailSettingsUpdate:
    values = {
        "enabled": enabled,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_security_mode": "starttls",
        "smtp_username": None,
        "smtp_password": smtp_password,
        "from_email": "compass@example.com",
        "from_display_name": "CompassAQ",
        "reply_to_email": None,
        "administrator_recipients": administrator_recipients,
    }
    values.update(overrides)
    return EmailSettingsUpdate(**values)


def _configured_settings(
    *,
    encryption_environment: dict[str, str] | None = None,
    authenticated: bool = False,
) -> EmailSettings:
    settings = EmailSettings(email_settings_id=1)
    update = _complete_update()
    if authenticated:
        update = _complete_update(
            smtp_username="smtp-user",
            smtp_password="smtp-password",
        )
    apply_email_settings_update(
        settings,
        update,
        encryption_environment=encryption_environment,
    )
    return settings


def test_secret_encryption_uses_only_the_dedicated_environment_key() -> None:
    environment = {
        "JWT_SECRET_KEY": "jwt-only-key",
    }
    with pytest.raises(SecretEncryptionError) as exc_info:
        encrypt_secret("smtp-password", environment=environment)

    assert exc_info.value.error_code == "encryption_key_missing"
    assert "smtp-password" not in str(exc_info.value)


def test_secret_encryption_round_trip_stores_no_plaintext() -> None:
    environment = _encryption_environment()
    ciphertext = encrypt_secret("  exact smtp password  ", environment=environment)

    assert ciphertext != "  exact smtp password  "
    assert "exact smtp password" not in ciphertext
    assert decrypt_secret(ciphertext, environment=environment) == "  exact smtp password  "


def test_secret_decryption_fails_safely_for_missing_wrong_and_invalid_keys() -> None:
    environment = _encryption_environment()
    ciphertext = encrypt_secret("smtp-password", environment=environment)

    with pytest.raises(SecretEncryptionError) as missing_error:
        decrypt_secret(ciphertext, environment={})
    assert missing_error.value.error_code == "encryption_key_missing"

    with pytest.raises(SecretEncryptionError) as wrong_error:
        decrypt_secret(ciphertext, environment=_encryption_environment())
    assert wrong_error.value.error_code == "encrypted_secret_unreadable"

    with pytest.raises(SecretEncryptionError) as invalid_error:
        decrypt_secret(
            ciphertext,
            environment={ENCRYPTION_KEY_ENVIRONMENT_VARIABLE: "not-a-fernet-key"},
        )
    assert invalid_error.value.error_code == "encryption_key_invalid"
    assert "smtp-password" not in str(wrong_error.value)


def test_get_or_create_email_settings_uses_one_fixed_row_without_committing() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first = get_or_create_email_settings(session)
        second = get_or_create_email_settings(session)
        assert first is second
        assert first.email_settings_id == 1
        session.commit()

    with Session(engine) as session:
        rows = session.scalars(sa.select(EmailSettings)).all()
        assert len(rows) == 1
        assert rows[0].administrator_recipients == []


def test_sqlite_model_constraints_enforce_singleton_and_test_state() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(EmailSettings(email_settings_id=2))
        with pytest.raises(IntegrityError):
            session.commit()

    with Session(engine) as session:
        session.add(
            EmailSettings(
                email_settings_id=1,
                last_test_status="success",
                last_test_error_code="unexpected_error",
                last_tested_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_normalization_is_explicit_and_recipient_duplicates_are_removed() -> None:
    normalized = normalize_email_settings_update(
        EmailSettingsUpdate(
            enabled=True,
            smtp_host="  SMTP.Example.COM.  ",
            smtp_port=587,
            smtp_security_mode=" STARTTLS ",
            smtp_username=" relay-user ",
            from_email=" Compass@Example.COM ",
            from_display_name=" CompassAQ Operations ",
            reply_to_email=" Support@Example.COM ",
            administrator_recipients=(
                " Alerts@Example.COM ",
                "alerts@example.com",
                "second@example.com",
            ),
        )
    )

    assert normalized.smtp_host == "smtp.example.com"
    assert normalized.smtp_security_mode == "starttls"
    assert normalized.smtp_username == "relay-user"
    assert normalized.from_email == "Compass@example.com"
    assert normalized.reply_to_email == "support@example.com"
    assert normalized.administrator_recipients == (
        "Alerts@example.com",
        "second@example.com",
    )


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("smtp_host", "https://smtp.example.com", "invalid_smtp_host"),
        ("smtp_host", "bad host.example.com", "invalid_smtp_host"),
        ("smtp_port", 0, "invalid_smtp_port"),
        ("smtp_port", 65536, "invalid_smtp_port"),
        ("smtp_port", True, "invalid_smtp_port"),
        ("smtp_security_mode", "opportunistic", "invalid_smtp_security_mode"),
        ("from_email", "not-an-email", "invalid_email_address"),
        ("reply_to_email", "two@example.com,three@example.com", "invalid_email_address"),
        ("from_display_name", "CompassAQ\nBcc: target@example.com", "invalid_control_character"),
    ],
)
def test_invalid_configuration_values_are_rejected(field, value, error_code) -> None:
    values = {"enabled": False, field: value}
    with pytest.raises(EmailConfigurationValidationError) as exc_info:
        normalize_email_settings_update(EmailSettingsUpdate(**values))
    assert exc_info.value.error_code == error_code


def test_password_omission_preserves_ciphertext_without_decryption_or_a_key() -> None:
    settings = EmailSettings(
        email_settings_id=1,
        smtp_password_ciphertext="opaque-existing-ciphertext",
    )

    result = apply_email_settings_update(
        settings,
        _complete_update(
            enabled=False,
            smtp_username="smtp-user",
            administrator_recipients=("new-alerts@example.com",),
        ),
        encryption_environment={},
    )

    assert settings.smtp_password_ciphertext == "opaque-existing-ciphertext"
    assert result.password_action is PasswordAction.UNCHANGED
    assert "administrator_recipients" in result.changed_fields


def test_non_empty_password_replaces_with_ciphertext_and_preserves_whitespace() -> None:
    environment = _encryption_environment()
    settings = EmailSettings(email_settings_id=1)

    result = apply_email_settings_update(
        settings,
        _complete_update(
            smtp_username="smtp-user",
            smtp_password="  exact smtp password  ",
        ),
        encryption_environment=environment,
    )

    assert result.password_action is PasswordAction.REPLACED
    assert settings.smtp_password_ciphertext is not None
    assert settings.smtp_password_ciphertext != "  exact smtp password  "
    assert "exact smtp password" not in settings.smtp_password_ciphertext
    assert (
        decrypt_secret(settings.smtp_password_ciphertext, environment=environment)
        == "  exact smtp password  "
    )
    assert not hasattr(settings, "smtp_password")


def test_password_is_redacted_from_update_object_representations() -> None:
    update = _complete_update(
        smtp_username="smtp-user",
        smtp_password="do-not-log-this-password",
    )
    normalized = normalize_email_settings_update(update)

    assert "do-not-log-this-password" not in repr(update)
    assert "do-not-log-this-password" not in repr(normalized)


def test_null_password_clears_ciphertext() -> None:
    settings = EmailSettings(
        email_settings_id=1,
        smtp_password_ciphertext="opaque-existing-ciphertext",
    )

    result = apply_email_settings_update(
        settings,
        _complete_update(smtp_username=None, smtp_password=None),
        encryption_environment={},
    )

    assert result.password_action is PasswordAction.CLEARED
    assert settings.smtp_password_ciphertext is None


def test_empty_password_is_rejected_before_any_field_is_changed() -> None:
    settings = EmailSettings(
        email_settings_id=1,
        smtp_host="original.example.com",
        smtp_password_ciphertext="existing-ciphertext",
    )

    with pytest.raises(EmailConfigurationValidationError) as exc_info:
        apply_email_settings_update(
            settings,
            _complete_update(smtp_host="changed.example.com", smtp_password=""),
            encryption_environment={},
        )

    assert exc_info.value.error_code == "empty_smtp_password"
    assert settings.smtp_host == "original.example.com"
    assert settings.smtp_password_ciphertext == "existing-ciphertext"


def test_password_replacement_with_missing_key_fails_before_mutation() -> None:
    settings = EmailSettings(email_settings_id=1, smtp_host="original.example.com")

    with pytest.raises(SecretEncryptionError) as exc_info:
        apply_email_settings_update(
            settings,
            _complete_update(
                smtp_host="changed.example.com",
                smtp_username="smtp-user",
                smtp_password="new-password",
            ),
            encryption_environment={},
        )

    assert exc_info.value.error_code == "encryption_key_missing"
    assert settings.smtp_host == "original.example.com"
    assert settings.smtp_password_ciphertext is None


def test_unencrypted_smtp_rejects_credentials_but_allows_network_relay() -> None:
    settings = EmailSettings(email_settings_id=1)
    result = apply_email_settings_update(
        settings,
        _complete_update(smtp_security_mode="none", smtp_port=25),
        encryption_environment={},
    )
    assert "smtp_security_mode" in result.changed_fields

    with pytest.raises(EmailConfigurationValidationError) as exc_info:
        apply_email_settings_update(
            EmailSettings(email_settings_id=1),
            _complete_update(
                smtp_security_mode="none",
                smtp_port=25,
                smtp_username="relay-user",
                smtp_password="password",
            ),
            encryption_environment=_encryption_environment(),
        )
    assert exc_info.value.error_code == "unencrypted_smtp_credentials_not_allowed"


@pytest.mark.parametrize("smtp_port", [1, 65535])
@pytest.mark.parametrize("security_mode", ["starttls", "ssl_tls", "none"])
def test_supported_security_modes_accept_port_boundaries(
    smtp_port: int,
    security_mode: str,
) -> None:
    normalized = normalize_email_settings_update(
        _complete_update(
            smtp_port=smtp_port,
            smtp_security_mode=security_mode,
        )
    )
    assert normalized.smtp_port == smtp_port
    assert normalized.smtp_security_mode == security_mode


def test_recipient_limit_and_empty_recipient_are_rejected() -> None:
    too_many = tuple(f"alerts-{index}@example.com" for index in range(51))
    with pytest.raises(EmailConfigurationValidationError) as limit_error:
        normalize_email_settings_update(
            _complete_update(administrator_recipients=too_many)
        )
    assert limit_error.value.error_code == "too_many_administrator_recipients"

    with pytest.raises(EmailConfigurationValidationError) as empty_error:
        normalize_email_settings_update(
            _complete_update(administrator_recipients=("   ",))
        )
    assert empty_error.value.error_code == "invalid_email_address"


def test_incomplete_enabled_configuration_is_saved_and_needs_attention() -> None:
    settings = EmailSettings(email_settings_id=1)
    result = apply_email_settings_update(
        settings,
        EmailSettingsUpdate(enabled=True, smtp_host="smtp.example.com"),
        encryption_environment={},
    )
    readiness = derive_email_readiness(settings, encryption_environment={})

    assert result.changed_fields == ("enabled", "smtp_host")
    assert readiness.status is EmailReadinessStatus.NEEDS_ATTENTION
    assert "smtp_port_missing" in readiness.reason_codes
    assert "administrator_recipients_missing" in readiness.reason_codes


def test_incomplete_authentication_pair_is_explicitly_needs_attention() -> None:
    settings = EmailSettings(email_settings_id=1)
    apply_email_settings_update(
        settings,
        _complete_update(smtp_username="smtp-user"),
        encryption_environment={},
    )

    readiness = derive_email_readiness(settings, encryption_environment={})
    assert readiness.status is EmailReadinessStatus.NEEDS_ATTENTION
    assert readiness.reason_codes == ("smtp_credentials_incomplete",)


def test_readiness_requires_successful_test_for_complete_configuration() -> None:
    settings = _configured_settings()

    assert derive_email_readiness(settings).status is EmailReadinessStatus.NEEDS_ATTENTION
    assert derive_email_readiness(settings).reason_codes == ("test_required",)

    tested_at = datetime.now(timezone.utc)
    record_email_test_success(settings, tested_at=tested_at)
    readiness = derive_email_readiness(settings)
    assert readiness.status is EmailReadinessStatus.READY
    assert readiness.reason_codes == ()

    record_email_test_failure(
        settings,
        tested_at=tested_at,
        error_code="smtp_authentication_failed",
    )
    readiness = derive_email_readiness(settings)
    assert readiness.status is EmailReadinessStatus.NEEDS_ATTENTION
    assert readiness.reason_codes == ("smtp_authentication_failed",)


def test_readiness_fails_safely_when_saved_password_cannot_be_decrypted() -> None:
    correct_environment = _encryption_environment()
    settings = _configured_settings(
        encryption_environment=correct_environment,
        authenticated=True,
    )
    record_email_test_success(settings, tested_at=datetime.now(timezone.utc))

    missing_key = derive_email_readiness(settings, encryption_environment={})
    wrong_key = derive_email_readiness(
        settings,
        encryption_environment=_encryption_environment(),
    )
    correct_key = derive_email_readiness(
        settings,
        encryption_environment=correct_environment,
    )

    assert missing_key.status is EmailReadinessStatus.NEEDS_ATTENTION
    assert missing_key.reason_codes == ("smtp_secret_unavailable",)
    assert wrong_key.reason_codes == ("smtp_secret_unavailable",)
    assert correct_key.status is EmailReadinessStatus.READY


def test_fresh_and_disabled_configuration_have_distinct_states() -> None:
    fresh = EmailSettings(email_settings_id=1, enabled=False)
    disabled = EmailSettings(
        email_settings_id=1,
        enabled=False,
        smtp_host="smtp.example.com",
    )

    assert derive_email_readiness(fresh).status is EmailReadinessStatus.NOT_CONFIGURED
    assert derive_email_readiness(disabled).status is EmailReadinessStatus.DISABLED


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("smtp_host", "smtp2.example.com"),
        ("smtp_port", 465),
        ("smtp_security_mode", "ssl_tls"),
        ("smtp_username", "replacement-user"),
        ("smtp_password", "replacement-password"),
        ("from_email", "other-sender@example.com"),
        ("from_display_name", "Other Sender"),
        ("reply_to_email", "reply@example.com"),
    ],
)
def test_material_configuration_changes_invalidate_successful_test(
    changed_field: str,
    changed_value,
) -> None:
    environment = _encryption_environment()
    settings = _configured_settings(
        encryption_environment=environment,
        authenticated=True,
    )
    record_email_test_success(settings, tested_at=datetime.now(timezone.utc))
    overrides = {changed_field: changed_value}

    result = apply_email_settings_update(
        settings,
        _complete_update(
            smtp_username=(
                changed_value if changed_field == "smtp_username" else "smtp-user"
            ),
            **({} if changed_field == "smtp_username" else overrides),
        ),
        encryption_environment=environment,
    )

    assert result.test_state_invalidated is True
    assert settings.last_test_status is None
    assert settings.last_test_error_code is None
    assert settings.last_tested_at is None


def test_enabled_and_recipient_changes_retain_transport_verification() -> None:
    settings = _configured_settings()
    tested_at = datetime.now(timezone.utc)
    record_email_test_success(settings, tested_at=tested_at)

    result = apply_email_settings_update(
        settings,
        _complete_update(
            enabled=False,
            administrator_recipients=("new-recipient@example.com",),
        ),
        encryption_environment={},
    )

    assert result.test_state_invalidated is False
    assert result.changed_fields == ("administrator_recipients", "enabled")
    assert settings.last_test_status == "success"
    assert settings.last_tested_at == tested_at
    assert derive_email_readiness(settings).status is EmailReadinessStatus.DISABLED


def test_recipient_only_update_preserves_encrypted_password_without_the_key() -> None:
    environment = _encryption_environment()
    settings = _configured_settings(
        encryption_environment=environment,
        authenticated=True,
    )
    tested_at = datetime.now(timezone.utc)
    record_email_test_success(settings, tested_at=tested_at)
    ciphertext = settings.smtp_password_ciphertext

    result = apply_email_settings_update(
        settings,
        _complete_update(
            smtp_username="smtp-user",
            administrator_recipients=("new-recipient@example.com",),
        ),
        encryption_environment={},
    )

    assert result.changed_fields == ("administrator_recipients",)
    assert result.test_state_invalidated is False
    assert settings.smtp_password_ciphertext == ciphertext
    assert settings.last_test_status == "success"
    assert settings.last_tested_at == tested_at


def test_unchanged_update_does_not_invalidate_test_state() -> None:
    settings = _configured_settings()
    tested_at = datetime.now(timezone.utc)
    record_email_test_success(settings, tested_at=tested_at)

    result = apply_email_settings_update(
        settings,
        _complete_update(),
        encryption_environment={},
    )

    assert result.changed_fields == ()
    assert result.test_state_invalidated is False
    assert settings.last_test_status == "success"
    assert settings.last_tested_at == tested_at


def test_clearing_password_invalidates_successful_test() -> None:
    environment = _encryption_environment()
    settings = _configured_settings(
        encryption_environment=environment,
        authenticated=True,
    )
    record_email_test_success(settings, tested_at=datetime.now(timezone.utc))

    result = apply_email_settings_update(
        settings,
        _complete_update(smtp_username=None, smtp_password=None),
        encryption_environment={},
    )

    assert result.password_action is PasswordAction.CLEARED
    assert result.test_state_invalidated is True
    assert settings.smtp_password_ciphertext is None
    assert settings.last_test_status is None


def test_test_state_helpers_require_utc_capable_timestamp_and_machine_code() -> None:
    settings = _configured_settings()
    with pytest.raises(EmailConfigurationValidationError) as timestamp_error:
        record_email_test_success(settings, tested_at=datetime(2026, 8, 20, 12, 0))
    assert timestamp_error.value.error_code == "invalid_test_timestamp"

    with pytest.raises(EmailConfigurationValidationError) as code_error:
        record_email_test_failure(
            settings,
            tested_at=datetime.now(timezone.utc),
            error_code="SMTP Failure!",
        )
    assert code_error.value.error_code == "invalid_test_error_code"
