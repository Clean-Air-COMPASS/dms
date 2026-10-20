from __future__ import annotations

import smtplib
import socket
import ssl
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from email.headerregistry import Address
from email.message import EmailMessage
from enum import Enum
from typing import Any, Final

from models import EmailSettings
from services.email_configuration import (
    EmailConfigurationValidationError,
    SmtpSecurityMode,
    email_configuration_issue_codes,
    normalize_email_address,
)
from services.secret_encryption import SecretEncryptionError, decrypt_secret


SMTP_TIMEOUT_SECONDS: Final = 15
MAX_EMAIL_SUBJECT_LENGTH: Final = 255
MAX_EMAIL_RECIPIENTS: Final = 50


class EmailDeliveryErrorCode(str, Enum):
    CONFIGURATION_DISABLED = "email_configuration_disabled"
    CONFIGURATION_INCOMPLETE = "email_configuration_incomplete"
    SECRET_UNAVAILABLE = "smtp_secret_unavailable"
    DNS_FAILURE = "smtp_dns_failure"
    CONNECTION_TIMEOUT = "smtp_connection_timeout"
    CONNECTION_FAILED = "smtp_connection_failed"
    TLS_ERROR = "smtp_tls_error"
    AUTHENTICATION_FAILED = "smtp_authentication_failed"
    SENDER_REJECTED = "smtp_sender_rejected"
    RECIPIENT_REJECTED = "smtp_recipient_rejected"
    RELAY_DENIED = "smtp_relay_denied"
    SERVER_DISCONNECTED = "smtp_server_disconnected"
    SERVER_ERROR = "smtp_server_error"
    INVALID_MESSAGE = "invalid_email_message"


_ERROR_MESSAGES: Final[dict[EmailDeliveryErrorCode, str]] = {
    EmailDeliveryErrorCode.CONFIGURATION_DISABLED: (
        "Email delivery is disabled in the saved configuration."
    ),
    EmailDeliveryErrorCode.CONFIGURATION_INCOMPLETE: (
        "The saved email configuration is incomplete."
    ),
    EmailDeliveryErrorCode.SECRET_UNAVAILABLE: (
        "The saved SMTP password cannot be read with the configured encryption key."
    ),
    EmailDeliveryErrorCode.DNS_FAILURE: (
        "The SMTP server hostname could not be resolved."
    ),
    EmailDeliveryErrorCode.CONNECTION_TIMEOUT: (
        "The SMTP server did not respond before the connection timed out."
    ),
    EmailDeliveryErrorCode.CONNECTION_FAILED: (
        "CompassAQ could not connect to the SMTP server."
    ),
    EmailDeliveryErrorCode.TLS_ERROR: (
        "The secure SMTP connection or certificate verification failed."
    ),
    EmailDeliveryErrorCode.AUTHENTICATION_FAILED: (
        "The SMTP server rejected the configured credentials."
    ),
    EmailDeliveryErrorCode.SENDER_REJECTED: (
        "The SMTP server rejected the configured sender address."
    ),
    EmailDeliveryErrorCode.RECIPIENT_REJECTED: (
        "The SMTP server rejected the test recipient address."
    ),
    EmailDeliveryErrorCode.RELAY_DENIED: (
        "The SMTP server denied permission to relay this message."
    ),
    EmailDeliveryErrorCode.SERVER_DISCONNECTED: (
        "The SMTP server disconnected before delivery completed."
    ),
    EmailDeliveryErrorCode.SERVER_ERROR: (
        "The SMTP server returned an unexpected error."
    ),
    EmailDeliveryErrorCode.INVALID_MESSAGE: (
        "The email message contains an invalid subject, body, or recipient."
    ),
}


class EmailDeliveryError(RuntimeError):
    """A stable, sanitized delivery failure safe for API and Event use."""

    def __init__(
        self,
        error_code: EmailDeliveryErrorCode,
        *,
        smtp_code: int | None = None,
        configuration_reason_codes: Sequence[str] = (),
    ):
        super().__init__(_ERROR_MESSAGES[error_code])
        self.error_code = error_code
        self.smtp_code = smtp_code
        self.configuration_reason_codes = tuple(configuration_reason_codes)


@dataclass(frozen=True)
class EmailTransportConfiguration:
    smtp_host: str
    smtp_port: int
    smtp_security_mode: SmtpSecurityMode
    smtp_username: str | None
    smtp_password: str | None = field(repr=False)
    from_email: str
    from_display_name: str | None
    reply_to_email: str | None


@dataclass(frozen=True)
class EmailSendResult:
    accepted_recipients: tuple[str, ...]


def email_transport_configuration_from_settings(
    settings: EmailSettings,
    *,
    encryption_environment: Mapping[str, str] | None = None,
) -> EmailTransportConfiguration:
    """Build transport input, decrypting the saved password only for sending."""
    issue_codes = email_configuration_issue_codes(
        settings,
        encryption_environment=encryption_environment,
        verify_secret=False,
        require_administrator_recipients=False,
    )
    if issue_codes:
        raise EmailDeliveryError(
            EmailDeliveryErrorCode.CONFIGURATION_INCOMPLETE,
            configuration_reason_codes=issue_codes,
        )

    smtp_password: str | None = None
    if settings.smtp_password_ciphertext:
        try:
            smtp_password = decrypt_secret(
                settings.smtp_password_ciphertext,
                environment=encryption_environment,
            )
        except SecretEncryptionError as exc:
            raise EmailDeliveryError(
                EmailDeliveryErrorCode.SECRET_UNAVAILABLE
            ) from exc

    return EmailTransportConfiguration(
        smtp_host=settings.smtp_host or "",
        smtp_port=settings.smtp_port or 0,
        smtp_security_mode=SmtpSecurityMode(settings.smtp_security_mode or ""),
        smtp_username=settings.smtp_username,
        smtp_password=smtp_password,
        from_email=settings.from_email or "",
        from_display_name=settings.from_display_name,
        reply_to_email=settings.reply_to_email,
    )


class EmailService:
    """Send provider-neutral email through one saved SMTP transport."""

    def __init__(
        self,
        configuration: EmailTransportConfiguration,
        *,
        smtp_factory: Callable[..., Any] | None = None,
        smtp_ssl_factory: Callable[..., Any] | None = None,
        ssl_context_factory: Callable[[], ssl.SSLContext] | None = None,
    ):
        self.configuration = configuration
        self._smtp_factory = smtp_factory or smtplib.SMTP
        self._smtp_ssl_factory = smtp_ssl_factory or smtplib.SMTP_SSL
        self._ssl_context_factory = ssl_context_factory or ssl.create_default_context

    def send(
        self,
        *,
        recipients: Sequence[str],
        subject: str,
        text_body: str,
        html_body: str | None = None,
    ) -> EmailSendResult:
        normalized_recipients = _normalize_message_recipients(recipients)
        try:
            message = self._build_message(
                recipients=normalized_recipients,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
            )
        except EmailDeliveryError:
            raise
        except (TypeError, ValueError):
            raise EmailDeliveryError(
                EmailDeliveryErrorCode.INVALID_MESSAGE
            ) from None

        smtp_client: Any | None = None
        stage = "connect"
        try:
            if self.configuration.smtp_security_mode is SmtpSecurityMode.SSL_TLS:
                stage = "tls"
                tls_context = self._ssl_context_factory()
                smtp_client = self._smtp_ssl_factory(
                    host=self.configuration.smtp_host,
                    port=self.configuration.smtp_port,
                    timeout=SMTP_TIMEOUT_SECONDS,
                    context=tls_context,
                )
            else:
                smtp_client = self._smtp_factory(
                    host=self.configuration.smtp_host,
                    port=self.configuration.smtp_port,
                    timeout=SMTP_TIMEOUT_SECONDS,
                )

            stage = "greeting"
            _require_successful_ehlo(smtp_client)

            if self.configuration.smtp_security_mode is SmtpSecurityMode.STARTTLS:
                stage = "tls"
                tls_context = self._ssl_context_factory()
                smtp_client.starttls(context=tls_context)
                _require_successful_ehlo(smtp_client)

            if self.configuration.smtp_username is not None:
                stage = "authentication"
                smtp_client.login(
                    self.configuration.smtp_username,
                    self.configuration.smtp_password or "",
                )

            stage = "send"
            refused_recipients = smtp_client.send_message(
                message,
                from_addr=self.configuration.from_email,
                to_addrs=list(normalized_recipients),
            )
            if refused_recipients:
                raise _recipient_refusal_error(refused_recipients)
            return EmailSendResult(accepted_recipients=normalized_recipients)
        except EmailDeliveryError:
            raise
        except Exception as exc:
            # Provider responses can contain deployment-specific details. Keep
            # them out of tracebacks and expose only the sanitized translation.
            raise _translate_smtp_exception(exc, stage=stage) from None
        finally:
            _close_smtp_client(smtp_client)

    def _build_message(
        self,
        *,
        recipients: tuple[str, ...],
        subject: str,
        text_body: str,
        html_body: str | None,
    ) -> EmailMessage:
        normalized_subject = _normalize_subject(subject)
        if not isinstance(text_body, str) or not text_body:
            raise EmailDeliveryError(EmailDeliveryErrorCode.INVALID_MESSAGE)
        if html_body is not None and not isinstance(html_body, str):
            raise EmailDeliveryError(EmailDeliveryErrorCode.INVALID_MESSAGE)

        message = EmailMessage()
        message["Subject"] = normalized_subject
        message["From"] = str(
            Address(
                display_name=self.configuration.from_display_name or "",
                addr_spec=self.configuration.from_email,
            )
        )
        message["To"] = ", ".join(
            str(Address(addr_spec=recipient)) for recipient in recipients
        )
        if self.configuration.reply_to_email:
            message["Reply-To"] = str(
                Address(addr_spec=self.configuration.reply_to_email)
            )
        message.set_content(text_body)
        if html_body is not None:
            message.add_alternative(html_body, subtype="html")
        return message


def _normalize_message_recipients(recipients: Sequence[str]) -> tuple[str, ...]:
    if isinstance(recipients, (str, bytes)) or not isinstance(recipients, Sequence):
        raise EmailDeliveryError(EmailDeliveryErrorCode.INVALID_MESSAGE)
    if not recipients or len(recipients) > MAX_EMAIL_RECIPIENTS:
        raise EmailDeliveryError(EmailDeliveryErrorCode.INVALID_MESSAGE)

    normalized: list[str] = []
    seen: set[str] = set()
    try:
        for index, recipient in enumerate(recipients):
            address = normalize_email_address(
                recipient,
                field=f"recipients[{index}]",
            )
            if address is None:
                raise EmailDeliveryError(EmailDeliveryErrorCode.INVALID_MESSAGE)
            duplicate_key = address.casefold()
            if duplicate_key not in seen:
                seen.add(duplicate_key)
                normalized.append(address)
    except EmailConfigurationValidationError as exc:
        raise EmailDeliveryError(EmailDeliveryErrorCode.INVALID_MESSAGE) from exc
    return tuple(normalized)


def _normalize_subject(subject: str) -> str:
    if not isinstance(subject, str):
        raise EmailDeliveryError(EmailDeliveryErrorCode.INVALID_MESSAGE)
    normalized = subject.strip()
    if (
        not normalized
        or len(normalized) > MAX_EMAIL_SUBJECT_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise EmailDeliveryError(EmailDeliveryErrorCode.INVALID_MESSAGE)
    return normalized


def _require_successful_ehlo(smtp_client: Any) -> None:
    code, message = smtp_client.ehlo()
    if code < 200 or code >= 400:
        raise smtplib.SMTPHeloError(code, message)


def _smtp_response_code(exc: BaseException) -> int | None:
    code = getattr(exc, "smtp_code", None)
    return code if isinstance(code, int) else None


def _recipient_refusal_error(refused_recipients: Mapping[str, Any]) -> EmailDeliveryError:
    codes: list[int] = []
    for refusal in refused_recipients.values():
        if isinstance(refusal, tuple) and refusal and isinstance(refusal[0], int):
            codes.append(refusal[0])
        else:
            code = _smtp_response_code(refusal)
            if code is not None:
                codes.append(code)
    if codes and all(code == 530 for code in codes):
        return EmailDeliveryError(
            EmailDeliveryErrorCode.RELAY_DENIED,
            smtp_code=530,
        )
    return EmailDeliveryError(
        EmailDeliveryErrorCode.RECIPIENT_REJECTED,
        smtp_code=codes[0] if codes else None,
    )


def _translate_smtp_exception(exc: BaseException, *, stage: str) -> EmailDeliveryError:
    smtp_code = _smtp_response_code(exc)
    if isinstance(exc, socket.gaierror):
        return EmailDeliveryError(EmailDeliveryErrorCode.DNS_FAILURE)
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return EmailDeliveryError(EmailDeliveryErrorCode.CONNECTION_TIMEOUT)
    if isinstance(exc, (ssl.SSLError, ssl.CertificateError)):
        return EmailDeliveryError(EmailDeliveryErrorCode.TLS_ERROR)
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return EmailDeliveryError(
            EmailDeliveryErrorCode.AUTHENTICATION_FAILED,
            smtp_code=smtp_code,
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        error_code = (
            EmailDeliveryErrorCode.RELAY_DENIED
            if smtp_code == 530
            else EmailDeliveryErrorCode.SENDER_REJECTED
        )
        return EmailDeliveryError(error_code, smtp_code=smtp_code)
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return _recipient_refusal_error(exc.recipients)
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return EmailDeliveryError(EmailDeliveryErrorCode.SERVER_DISCONNECTED)
    if stage == "tls" and isinstance(exc, smtplib.SMTPException):
        return EmailDeliveryError(
            EmailDeliveryErrorCode.TLS_ERROR,
            smtp_code=smtp_code,
        )
    if stage == "authentication" and isinstance(exc, smtplib.SMTPException):
        return EmailDeliveryError(
            EmailDeliveryErrorCode.AUTHENTICATION_FAILED,
            smtp_code=smtp_code,
        )
    if smtp_code == 530:
        return EmailDeliveryError(
            EmailDeliveryErrorCode.RELAY_DENIED,
            smtp_code=smtp_code,
        )
    if isinstance(exc, smtplib.SMTPConnectError):
        return EmailDeliveryError(
            EmailDeliveryErrorCode.CONNECTION_FAILED,
            smtp_code=smtp_code,
        )
    if isinstance(exc, smtplib.SMTPException):
        return EmailDeliveryError(
            EmailDeliveryErrorCode.SERVER_ERROR,
            smtp_code=smtp_code,
        )
    if isinstance(exc, (ConnectionError, OSError)):
        return EmailDeliveryError(EmailDeliveryErrorCode.CONNECTION_FAILED)
    return EmailDeliveryError(EmailDeliveryErrorCode.SERVER_ERROR)


def _close_smtp_client(smtp_client: Any | None) -> None:
    if smtp_client is None:
        return
    try:
        smtp_client.quit()
    except Exception:
        try:
            smtp_client.close()
        except Exception:
            pass
