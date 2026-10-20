from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Final

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.orm import Session

from models import EmailSettings
from services.administrator_summary_schedule import (
    DEFAULT_ADMINISTRATOR_SUMMARY_DAILY_SEND_TIME,
)
from services.secret_encryption import (
    SecretEncryptionError,
    decrypt_secret,
    encrypt_secret,
)


EMAIL_SETTINGS_SINGLETON_ID: Final = 1
MAX_ADMINISTRATOR_RECIPIENTS: Final = 50
MAX_SMTP_PASSWORD_LENGTH: Final = 4096
_DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MACHINE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class SmtpSecurityMode(str, Enum):
    STARTTLS = "starttls"
    SSL_TLS = "ssl_tls"
    NONE = "none"


class EmailReadinessStatus(str, Enum):
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"
    NEEDS_ATTENTION = "needs_attention"
    READY = "ready"


class PasswordAction(str, Enum):
    UNCHANGED = "unchanged"
    REPLACED = "replaced"
    CLEARED = "cleared"


class _PasswordUnchanged:
    pass


PASSWORD_UNCHANGED: Final = _PasswordUnchanged()
PasswordUpdate = str | None | _PasswordUnchanged


class EmailConfigurationValidationError(ValueError):
    """A stable validation error for saved email configuration."""

    def __init__(self, error_code: str, field: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.field = field


@dataclass(frozen=True)
class EmailSettingsUpdate:
    enabled: bool
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security_mode: str | SmtpSecurityMode | None = None
    smtp_username: str | None = None
    smtp_password: PasswordUpdate = field(
        default=PASSWORD_UNCHANGED,
        repr=False,
    )
    from_email: str | None = None
    from_display_name: str | None = None
    reply_to_email: str | None = None
    administrator_recipients: Sequence[str] = ()


@dataclass(frozen=True)
class NormalizedEmailSettingsUpdate:
    enabled: bool
    smtp_host: str | None
    smtp_port: int | None
    smtp_security_mode: str | None
    smtp_username: str | None
    smtp_password: PasswordUpdate = field(repr=False)
    from_email: str | None
    from_display_name: str | None
    reply_to_email: str | None
    administrator_recipients: tuple[str, ...]


@dataclass(frozen=True)
class EmailSettingsUpdateResult:
    changed_fields: tuple[str, ...]
    password_action: PasswordAction
    test_state_invalidated: bool


@dataclass(frozen=True)
class EmailReadiness:
    status: EmailReadinessStatus
    reason_codes: tuple[str, ...]


MATERIAL_CONFIGURATION_FIELDS: Final = frozenset(
    {
        "smtp_host",
        "smtp_port",
        "smtp_security_mode",
        "smtp_username",
        "smtp_password_ciphertext",
        "from_email",
        "from_display_name",
        "reply_to_email",
    }
)


def get_or_create_email_settings(session: Session) -> EmailSettings:
    """Return the fixed singleton without committing the caller's transaction."""
    settings = session.get(EmailSettings, EMAIL_SETTINGS_SINGLETON_ID)
    if settings is None:
        # Set application defaults explicitly so fallback creation behaves the
        # same on SQLite and PostgreSQL instead of depending on dialect-specific
        # Boolean server-default coercion.
        settings = EmailSettings(
            email_settings_id=EMAIL_SETTINGS_SINGLETON_ID,
            enabled=False,
            administrator_recipients=[],
            administrator_summary_enabled=False,
            administrator_summary_cadence="daily",
            administrator_summary_daily_send_time=(
                DEFAULT_ADMINISTRATOR_SUMMARY_DAILY_SEND_TIME
            ),
            administrator_summary_reporting_timezone_override=None,
        )
        session.add(settings)
        session.flush()
    return settings


def _has_header_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _normalize_optional_text(
    value: str | None,
    *,
    field: str,
    maximum_length: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EmailConfigurationValidationError(
            "invalid_text",
            field,
            f"{field} must be text or null",
        )
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum_length:
        raise EmailConfigurationValidationError(
            "text_too_long",
            field,
            f"{field} must not exceed {maximum_length} characters",
        )
    if _has_header_control_characters(normalized):
        raise EmailConfigurationValidationError(
            "invalid_control_character",
            field,
            f"{field} contains an unsupported control character",
        )
    return normalized


def _normalize_smtp_host(value: str | None) -> str | None:
    normalized = _normalize_optional_text(
        value,
        field="smtp_host",
        maximum_length=253,
    )
    if normalized is None:
        return None
    if any(character in normalized for character in ("/", "\\", "@")):
        raise EmailConfigurationValidationError(
            "invalid_smtp_host",
            "smtp_host",
            "SMTP host must be a hostname or IP address without a scheme or path",
        )
    try:
        return str(ipaddress.ip_address(normalized))
    except ValueError:
        pass

    hostname = normalized.rstrip(".").lower()
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise EmailConfigurationValidationError(
            "invalid_smtp_host",
            "smtp_host",
            "SMTP host is not a valid hostname",
        ) from exc
    if len(ascii_hostname) > 253 or not ascii_hostname:
        raise EmailConfigurationValidationError(
            "invalid_smtp_host",
            "smtp_host",
            "SMTP host is not a valid hostname",
        )
    if not all(_DNS_LABEL_PATTERN.fullmatch(label) for label in ascii_hostname.split(".")):
        raise EmailConfigurationValidationError(
            "invalid_smtp_host",
            "smtp_host",
            "SMTP host is not a valid hostname",
        )
    return ascii_hostname


def _normalize_smtp_port(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise EmailConfigurationValidationError(
            "invalid_smtp_port",
            "smtp_port",
            "SMTP port must be an integer from 1 through 65535",
        )
    return value


def _normalize_security_mode(
    value: str | SmtpSecurityMode | None,
) -> str | None:
    if value is None:
        return None
    normalized = str(value.value if isinstance(value, SmtpSecurityMode) else value).strip().lower()
    if not normalized:
        return None
    allowed_modes = {mode.value for mode in SmtpSecurityMode}
    if normalized not in allowed_modes:
        raise EmailConfigurationValidationError(
            "invalid_smtp_security_mode",
            "smtp_security_mode",
            "SMTP security mode must be starttls, ssl_tls, or none",
        )
    return normalized


def normalize_email_address(value: str | None, *, field: str) -> str | None:
    normalized = _normalize_optional_text(
        value,
        field=field,
        maximum_length=320,
    )
    if normalized is None:
        return None
    try:
        validated = validate_email(normalized, check_deliverability=False)
    except EmailNotValidError as exc:
        raise EmailConfigurationValidationError(
            "invalid_email_address",
            field,
            f"{field} must contain one valid email address",
        ) from exc
    canonical = validated.normalized
    if len(canonical) > 320:
        raise EmailConfigurationValidationError(
            "invalid_email_address",
            field,
            f"{field} must not exceed 320 characters",
        )
    return canonical


def _normalize_recipients(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise EmailConfigurationValidationError(
            "invalid_administrator_recipients",
            "administrator_recipients",
            "Administrator recipients must be a list of email addresses",
        )
    if len(values) > MAX_ADMINISTRATOR_RECIPIENTS:
        raise EmailConfigurationValidationError(
            "too_many_administrator_recipients",
            "administrator_recipients",
            f"No more than {MAX_ADMINISTRATOR_RECIPIENTS} recipients are allowed",
        )

    recipients: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        recipient = normalize_email_address(
            value,
            field=f"administrator_recipients[{index}]",
        )
        if recipient is None:
            raise EmailConfigurationValidationError(
                "invalid_email_address",
                f"administrator_recipients[{index}]",
                "Administrator recipient cannot be empty",
            )
        duplicate_key = recipient.casefold()
        if duplicate_key not in seen:
            seen.add(duplicate_key)
            recipients.append(recipient)
    return tuple(recipients)


def normalize_email_settings_update(
    update: EmailSettingsUpdate,
) -> NormalizedEmailSettingsUpdate:
    if not isinstance(update.enabled, bool):
        raise EmailConfigurationValidationError(
            "invalid_enabled_state",
            "enabled",
            "enabled must be true or false",
        )
    if not isinstance(update.smtp_password, (str, _PasswordUnchanged)) and update.smtp_password is not None:
        raise EmailConfigurationValidationError(
            "invalid_smtp_password",
            "smtp_password",
            "SMTP password must be text, null, or omitted",
        )
    if isinstance(update.smtp_password, str):
        if update.smtp_password == "":
            raise EmailConfigurationValidationError(
                "empty_smtp_password",
                "smtp_password",
                "SMTP password cannot be empty; use null to clear it",
            )
        if len(update.smtp_password) > MAX_SMTP_PASSWORD_LENGTH:
            raise EmailConfigurationValidationError(
                "smtp_password_too_long",
                "smtp_password",
                f"SMTP password must not exceed {MAX_SMTP_PASSWORD_LENGTH} characters",
            )

    return NormalizedEmailSettingsUpdate(
        enabled=update.enabled,
        smtp_host=_normalize_smtp_host(update.smtp_host),
        smtp_port=_normalize_smtp_port(update.smtp_port),
        smtp_security_mode=_normalize_security_mode(update.smtp_security_mode),
        smtp_username=_normalize_optional_text(
            update.smtp_username,
            field="smtp_username",
            maximum_length=512,
        ),
        smtp_password=update.smtp_password,
        from_email=normalize_email_address(update.from_email, field="from_email"),
        from_display_name=_normalize_optional_text(
            update.from_display_name,
            field="from_display_name",
            maximum_length=200,
        ),
        reply_to_email=normalize_email_address(
            update.reply_to_email,
            field="reply_to_email",
        ),
        administrator_recipients=_normalize_recipients(
            update.administrator_recipients
        ),
    )


def apply_email_settings_update(
    settings: EmailSettings,
    update: EmailSettingsUpdate,
    *,
    encryption_environment: Mapping[str, str] | None = None,
) -> EmailSettingsUpdateResult:
    """Validate and apply an update without decrypting an existing password."""
    normalized = normalize_email_settings_update(update)

    password_action = PasswordAction.UNCHANGED
    candidate_ciphertext = settings.smtp_password_ciphertext
    if isinstance(normalized.smtp_password, str):
        candidate_ciphertext = encrypt_secret(
            normalized.smtp_password,
            environment=encryption_environment,
        )
        password_action = PasswordAction.REPLACED
    elif normalized.smtp_password is None:
        candidate_ciphertext = None
        password_action = PasswordAction.CLEARED

    if normalized.smtp_security_mode == SmtpSecurityMode.NONE.value and (
        normalized.smtp_username is not None or candidate_ciphertext is not None
    ):
        raise EmailConfigurationValidationError(
            "unencrypted_smtp_credentials_not_allowed",
            "smtp_security_mode",
            "Unencrypted SMTP cannot be saved with a username or password",
        )

    candidate_values: dict[str, object] = {
        "enabled": normalized.enabled,
        "smtp_host": normalized.smtp_host,
        "smtp_port": normalized.smtp_port,
        "smtp_security_mode": normalized.smtp_security_mode,
        "smtp_username": normalized.smtp_username,
        "smtp_password_ciphertext": candidate_ciphertext,
        "from_email": normalized.from_email,
        "from_display_name": normalized.from_display_name,
        "reply_to_email": normalized.reply_to_email,
        "administrator_recipients": list(normalized.administrator_recipients),
    }
    changed_fields: set[str] = set()
    for field, candidate_value in candidate_values.items():
        existing_value = getattr(settings, field)
        if field == "administrator_recipients" and existing_value is None:
            existing_value = []
        if existing_value != candidate_value:
            changed_fields.add(field)
    test_state_invalidated = bool(changed_fields & MATERIAL_CONFIGURATION_FIELDS)

    for field, candidate_value in candidate_values.items():
        if field in changed_fields:
            setattr(settings, field, candidate_value)

    if test_state_invalidated:
        settings.last_test_status = None
        settings.last_test_error_code = None
        settings.last_tested_at = None

    return EmailSettingsUpdateResult(
        changed_fields=tuple(sorted(changed_fields)),
        password_action=password_action,
        test_state_invalidated=test_state_invalidated,
    )


def _has_meaningful_configuration(settings: EmailSettings) -> bool:
    return any(
        (
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_security_mode,
            settings.smtp_username,
            settings.smtp_password_ciphertext,
            settings.from_email,
            settings.from_display_name,
            settings.reply_to_email,
            settings.administrator_recipients,
        )
    )


def derive_email_readiness(
    settings: EmailSettings,
    *,
    encryption_environment: Mapping[str, str] | None = None,
) -> EmailReadiness:
    """Derive the server-owned operational state from persisted configuration."""
    has_configuration = _has_meaningful_configuration(settings)
    if not settings.enabled and not has_configuration:
        return EmailReadiness(
            EmailReadinessStatus.NOT_CONFIGURED,
            ("email_not_configured",),
        )
    if not settings.enabled:
        return EmailReadiness(
            EmailReadinessStatus.DISABLED,
            ("email_disabled",),
        )

    reasons = email_configuration_issue_codes(
        settings,
        encryption_environment=encryption_environment,
        verify_secret=True,
        require_administrator_recipients=True,
    )

    if reasons:
        return EmailReadiness(
            EmailReadinessStatus.NEEDS_ATTENTION,
            reasons,
        )
    if settings.last_test_status == "success":
        return EmailReadiness(EmailReadinessStatus.READY, ())
    if settings.last_test_status == "failed":
        return EmailReadiness(
            EmailReadinessStatus.NEEDS_ATTENTION,
            (settings.last_test_error_code or "last_test_failed",),
        )
    return EmailReadiness(
        EmailReadinessStatus.NEEDS_ATTENTION,
        ("test_required",),
    )


def email_configuration_issue_codes(
    settings: EmailSettings,
    *,
    encryption_environment: Mapping[str, str] | None = None,
    verify_secret: bool,
    require_administrator_recipients: bool,
) -> tuple[str, ...]:
    """Return structural issues without considering enabled or test state."""
    reasons: list[str] = []
    if not settings.smtp_host:
        reasons.append("smtp_host_missing")
    if settings.smtp_port is None:
        reasons.append("smtp_port_missing")
    if not settings.smtp_security_mode:
        reasons.append("smtp_security_mode_missing")
    if not settings.from_email:
        reasons.append("from_email_missing")
    if require_administrator_recipients and not settings.administrator_recipients:
        reasons.append("administrator_recipients_missing")

    username_configured = bool(settings.smtp_username)
    password_configured = bool(settings.smtp_password_ciphertext)
    if username_configured != password_configured:
        reasons.append("smtp_credentials_incomplete")
    if settings.smtp_security_mode == SmtpSecurityMode.NONE.value and (
        username_configured or password_configured
    ):
        reasons.append("unencrypted_smtp_credentials_not_allowed")
    if password_configured and verify_secret:
        try:
            decrypt_secret(
                settings.smtp_password_ciphertext or "",
                environment=encryption_environment,
            )
        except SecretEncryptionError:
            reasons.append("smtp_secret_unavailable")

    return tuple(reasons)


def record_email_test_success(settings: EmailSettings, *, tested_at: datetime) -> None:
    tested_at = _normalize_tested_at(tested_at)
    settings.last_test_status = "success"
    settings.last_test_error_code = None
    settings.last_tested_at = tested_at


def record_email_test_failure(
    settings: EmailSettings,
    *,
    tested_at: datetime,
    error_code: str,
) -> None:
    tested_at = _normalize_tested_at(tested_at)
    normalized_error_code = _normalize_optional_text(
        error_code,
        field="last_test_error_code",
        maximum_length=64,
    )
    if normalized_error_code is None:
        raise EmailConfigurationValidationError(
            "invalid_test_error_code",
            "last_test_error_code",
            "Test failure error code is required",
        )
    if not _MACHINE_CODE_PATTERN.fullmatch(normalized_error_code):
        raise EmailConfigurationValidationError(
            "invalid_test_error_code",
            "last_test_error_code",
            "Test failure error code must be a lowercase machine-readable code",
        )
    settings.last_test_status = "failed"
    settings.last_test_error_code = normalized_error_code
    settings.last_tested_at = tested_at


def _normalize_tested_at(tested_at: datetime) -> datetime:
    if (
        not isinstance(tested_at, datetime)
        or tested_at.tzinfo is None
        or tested_at.utcoffset() is None
    ):
        raise EmailConfigurationValidationError(
            "invalid_test_timestamp",
            "last_tested_at",
            "Email test timestamp must include a timezone",
        )
    return tested_at.astimezone(timezone.utc)
