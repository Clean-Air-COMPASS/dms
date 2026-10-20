from __future__ import annotations

import smtplib
import socket
import ssl
from email.message import EmailMessage

import pytest
from cryptography.fernet import Fernet

from models import EmailSettings
from services.email_configuration import SmtpSecurityMode
from services.email_delivery import (
    SMTP_TIMEOUT_SECONDS,
    EmailDeliveryError,
    EmailDeliveryErrorCode,
    EmailService,
    EmailTransportConfiguration,
    email_transport_configuration_from_settings,
)
from services.secret_encryption import ENCRYPTION_KEY_ENVIRONMENT_VARIABLE, encrypt_secret


class FakeSmtpClient:
    def __init__(self, *, failures=None, refused_recipients=None):
        self.failures = failures or {}
        self.refused_recipients = refused_recipients or {}
        self.calls: list[tuple] = []
        self.message: EmailMessage | None = None

    def _record(self, method: str, *arguments):
        self.calls.append((method, *arguments))
        failure = self.failures.get(method)
        if failure is not None:
            raise failure

    def ehlo(self):
        self._record("ehlo")
        return 250, b"smtp ready"

    def starttls(self, *, context):
        self._record("starttls", context)
        return 220, b"tls ready"

    def login(self, username, password):
        self._record("login", username, password)
        return 235, b"authenticated"

    def send_message(self, message, *, from_addr, to_addrs):
        self._record("send_message", from_addr, tuple(to_addrs))
        self.message = message
        return self.refused_recipients

    def quit(self):
        self._record("quit")
        return 221, b"bye"

    def close(self):
        self._record("close")


class FakeSmtpFactory:
    def __init__(self, client=None, *, failure=None):
        self.client = client or FakeSmtpClient()
        self.failure = failure
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return self.client


def _transport(**overrides) -> EmailTransportConfiguration:
    values = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_security_mode": "starttls",
        "smtp_username": "smtp-user",
        "smtp_password": "smtp-secret",
        "from_email": "sender@example.com",
        "from_display_name": "CompassAQ Alerts",
        "reply_to_email": "support@example.com",
    }
    values.update(overrides)
    values["smtp_security_mode"] = SmtpSecurityMode(values["smtp_security_mode"])
    return EmailTransportConfiguration(**values)


def _send(service: EmailService):
    return service.send(
        recipients=("admin@example.com",),
        subject="Delivery test",
        text_body="Plain delivery test",
        html_body="<p>HTML delivery test</p>",
    )


def test_starttls_delivery_authenticates_and_builds_plain_and_html_message():
    client = FakeSmtpClient()
    plain_factory = FakeSmtpFactory(client)
    ssl_factory = FakeSmtpFactory()
    tls_context = object()
    service = EmailService(
        _transport(),
        smtp_factory=plain_factory,
        smtp_ssl_factory=ssl_factory,
        ssl_context_factory=lambda: tls_context,
    )

    result = _send(service)

    assert result.accepted_recipients == ("admin@example.com",)
    assert plain_factory.calls == [
        {
            "host": "smtp.example.com",
            "port": 587,
            "timeout": SMTP_TIMEOUT_SECONDS,
        }
    ]
    assert ssl_factory.calls == []
    assert client.calls == [
        ("ehlo",),
        ("starttls", tls_context),
        ("ehlo",),
        ("login", "smtp-user", "smtp-secret"),
        ("send_message", "sender@example.com", ("admin@example.com",)),
        ("quit",),
    ]
    assert client.message is not None
    assert client.message["From"] == "CompassAQ Alerts <sender@example.com>"
    assert client.message["Reply-To"] == "support@example.com"
    assert client.message.is_multipart()
    assert [part.get_content_type() for part in client.message.iter_parts()] == [
        "text/plain",
        "text/html",
    ]


def test_implicit_tls_uses_verified_context_and_never_calls_starttls():
    client = FakeSmtpClient()
    plain_factory = FakeSmtpFactory()
    ssl_factory = FakeSmtpFactory(client)
    tls_context = object()
    service = EmailService(
        _transport(smtp_port=465, smtp_security_mode="ssl_tls"),
        smtp_factory=plain_factory,
        smtp_ssl_factory=ssl_factory,
        ssl_context_factory=lambda: tls_context,
    )

    _send(service)

    assert plain_factory.calls == []
    assert ssl_factory.calls == [
        {
            "host": "smtp.example.com",
            "port": 465,
            "timeout": SMTP_TIMEOUT_SECONDS,
            "context": tls_context,
        }
    ]
    assert all(call[0] != "starttls" for call in client.calls)


def test_default_tls_context_requires_certificate_and_hostname_verification():
    client = FakeSmtpClient()
    service = EmailService(_transport(), smtp_factory=FakeSmtpFactory(client))

    _send(service)

    tls_context = next(
        call[1] for call in client.calls if call[0] == "starttls"
    )
    assert tls_context.check_hostname is True
    assert tls_context.verify_mode == ssl.CERT_REQUIRED


def test_unauthenticated_relay_omits_login_and_tls_when_configured():
    client = FakeSmtpClient()
    service = EmailService(
        _transport(
            smtp_port=25,
            smtp_security_mode="none",
            smtp_username=None,
            smtp_password=None,
        ),
        smtp_factory=FakeSmtpFactory(client),
        ssl_context_factory=lambda: pytest.fail("TLS context should not be created"),
    )

    _send(service)

    assert all(call[0] not in {"starttls", "login"} for call in client.calls)


def test_starttls_failure_does_not_downgrade_to_unencrypted_delivery():
    client = FakeSmtpClient(
        failures={"starttls": smtplib.SMTPNotSupportedError("not supported")}
    )
    service = EmailService(
        _transport(),
        smtp_factory=FakeSmtpFactory(client),
        ssl_context_factory=ssl.create_default_context,
    )

    with pytest.raises(EmailDeliveryError) as exc_info:
        _send(service)

    assert exc_info.value.error_code is EmailDeliveryErrorCode.TLS_ERROR
    assert all(call[0] not in {"login", "send_message"} for call in client.calls)


@pytest.mark.parametrize(
    ("stage", "failure", "expected_code"),
    [
        ("connect", socket.gaierror("contains smtp-secret"), EmailDeliveryErrorCode.DNS_FAILURE),
        ("connect", socket.timeout("contains smtp-secret"), EmailDeliveryErrorCode.CONNECTION_TIMEOUT),
        ("connect", ConnectionRefusedError("contains smtp-secret"), EmailDeliveryErrorCode.CONNECTION_FAILED),
        ("connect", ssl.SSLCertVerificationError("contains smtp-secret"), EmailDeliveryErrorCode.TLS_ERROR),
        ("login", smtplib.SMTPAuthenticationError(535, b"contains smtp-secret"), EmailDeliveryErrorCode.AUTHENTICATION_FAILED),
        ("send_message", smtplib.SMTPSenderRefused(550, b"contains smtp-secret", "sender@example.com"), EmailDeliveryErrorCode.SENDER_REJECTED),
        ("send_message", smtplib.SMTPSenderRefused(530, b"contains smtp-secret", "sender@example.com"), EmailDeliveryErrorCode.RELAY_DENIED),
        ("send_message", smtplib.SMTPServerDisconnected("contains smtp-secret"), EmailDeliveryErrorCode.SERVER_DISCONNECTED),
        ("send_message", smtplib.SMTPDataError(554, b"contains smtp-secret"), EmailDeliveryErrorCode.SERVER_ERROR),
    ],
)
def test_smtp_failures_are_mapped_to_stable_redacted_errors(
    stage, failure, expected_code
):
    if stage == "connect":
        factory = FakeSmtpFactory(failure=failure)
    else:
        factory = FakeSmtpFactory(FakeSmtpClient(failures={stage: failure}))
    service = EmailService(_transport(), smtp_factory=factory)

    with pytest.raises(EmailDeliveryError) as exc_info:
        _send(service)

    assert exc_info.value.error_code is expected_code
    assert "smtp-secret" not in str(exc_info.value)
    assert "smtp-user" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


@pytest.mark.parametrize(
    ("refusals", "expected_code", "smtp_code"),
    [
        ({"admin@example.com": (550, b"no")}, EmailDeliveryErrorCode.RECIPIENT_REJECTED, 550),
        ({"admin@example.com": (530, b"relay denied")}, EmailDeliveryErrorCode.RELAY_DENIED, 530),
    ],
)
def test_returned_recipient_refusals_are_classified(refusals, expected_code, smtp_code):
    client = FakeSmtpClient(refused_recipients=refusals)
    service = EmailService(_transport(), smtp_factory=FakeSmtpFactory(client))

    with pytest.raises(EmailDeliveryError) as exc_info:
        _send(service)

    assert exc_info.value.error_code is expected_code
    assert exc_info.value.smtp_code == smtp_code


@pytest.mark.parametrize(
    ("recipients", "subject"),
    [
        (("not-an-email",), "Delivery test"),
        (("admin@example.com",), "Unsafe\r\nBcc: hidden@example.com"),
    ],
)
def test_invalid_message_is_rejected_before_opening_a_connection(
    recipients, subject
):
    factory = FakeSmtpFactory()
    service = EmailService(_transport(), smtp_factory=factory)

    with pytest.raises(EmailDeliveryError) as exc_info:
        service.send(
            recipients=recipients,
            subject=subject,
            text_body="test",
        )

    assert exc_info.value.error_code is EmailDeliveryErrorCode.INVALID_MESSAGE
    assert factory.calls == []


def test_client_is_closed_if_graceful_quit_fails():
    client = FakeSmtpClient(failures={"quit": RuntimeError("socket closed")})
    service = EmailService(_transport(), smtp_factory=FakeSmtpFactory(client))

    _send(service)

    assert client.calls[-2:] == [("quit",), ("close",)]


def test_transport_configuration_decrypts_only_the_saved_password_for_sending():
    environment = {
        ENCRYPTION_KEY_ENVIRONMENT_VARIABLE: Fernet.generate_key().decode("ascii")
    }
    settings = EmailSettings(
        email_settings_id=1,
        enabled=True,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_security_mode="starttls",
        smtp_username="smtp-user",
        smtp_password_ciphertext=encrypt_secret("smtp-secret", environment=environment),
        from_email="sender@example.com",
        administrator_recipients=["admin@example.com"],
    )

    configuration = email_transport_configuration_from_settings(
        settings,
        encryption_environment=environment,
    )

    assert configuration.smtp_password == "smtp-secret"
    assert "smtp-secret" not in repr(configuration)

    wrong_environment = {
        ENCRYPTION_KEY_ENVIRONMENT_VARIABLE: Fernet.generate_key().decode("ascii")
    }
    with pytest.raises(EmailDeliveryError) as exc_info:
        email_transport_configuration_from_settings(
            settings,
            encryption_environment=wrong_environment,
        )
    assert exc_info.value.error_code is EmailDeliveryErrorCode.SECRET_UNAVAILABLE
