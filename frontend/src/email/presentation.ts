import i18n from '../i18n';
import type { EmailReadinessStatus, SmtpSecurityMode } from './types';

const reasonTranslationKeys: Record<string, string> = {
  email_not_configured: 'reasons.emailNotConfigured',
  email_disabled: 'reasons.emailDisabled',
  smtp_host_missing: 'reasons.smtpHostMissing',
  smtp_port_missing: 'reasons.smtpPortMissing',
  smtp_security_mode_missing: 'reasons.smtpSecurityModeMissing',
  from_email_missing: 'reasons.fromEmailMissing',
  administrator_recipients_missing: 'reasons.administratorRecipientsMissing',
  smtp_credentials_incomplete: 'reasons.smtpCredentialsIncomplete',
  unencrypted_smtp_credentials_not_allowed: 'reasons.unencryptedCredentialsNotAllowed',
  smtp_secret_unavailable: 'errors.smtpSecretUnavailable',
  test_required: 'reasons.testRequired',
  last_test_failed: 'reasons.lastTestFailed',
  email_configuration_disabled: 'errors.emailConfigurationDisabled',
  email_configuration_incomplete: 'errors.emailConfigurationIncomplete',
  smtp_dns_failure: 'errors.smtpDnsFailure',
  smtp_connection_timeout: 'errors.smtpConnectionTimeout',
  smtp_connection_failed: 'errors.smtpConnectionFailed',
  smtp_tls_error: 'errors.smtpTlsError',
  smtp_authentication_failed: 'errors.smtpAuthenticationFailed',
  smtp_sender_rejected: 'errors.smtpSenderRejected',
  smtp_recipient_rejected: 'errors.smtpRecipientRejected',
  smtp_relay_denied: 'errors.smtpRelayDenied',
  smtp_server_disconnected: 'errors.smtpServerDisconnected',
  smtp_server_error: 'errors.smtpServerError',
  invalid_email_message: 'errors.invalidEmailMessage',
};

const saveErrorTranslationKeys: Record<string, string> = {
  invalid_text: 'validation.invalidText',
  text_too_long: 'validation.textTooLong',
  invalid_control_character: 'validation.invalidControlCharacter',
  invalid_smtp_host: 'validation.invalidSmtpHost',
  invalid_smtp_port: 'validation.invalidSmtpPort',
  invalid_smtp_security_mode: 'validation.invalidSecurityMode',
  invalid_email_address: 'validation.invalidEmailAddress',
  invalid_administrator_recipients: 'validation.invalidRecipients',
  too_many_administrator_recipients: 'validation.tooManyRecipients',
  invalid_enabled_state: 'validation.invalidEnabledState',
  invalid_smtp_password: 'validation.invalidPassword',
  empty_smtp_password: 'validation.emptyPassword',
  smtp_password_too_long: 'validation.passwordTooLong',
  unencrypted_smtp_credentials_not_allowed: 'validation.unencryptedCredentials',
  smtp_secret_unavailable: 'errors.smtpSecretUnavailable',
};

function translate(key: string): string {
  return i18n.t(`emailNotifications:${key}` as never);
}

export function statusLabel(status: EmailReadinessStatus): string {
  return translate(`status.${status}.label`);
}

export function statusExplanation(status: EmailReadinessStatus): string {
  return translate(`status.${status}.explanation`);
}

export function statusNextAction(status: EmailReadinessStatus): string {
  return translate(`status.${status}.nextAction`);
}

export function reasonMessage(reasonCode: string): string {
  return translate(reasonTranslationKeys[reasonCode] ?? 'errors.unknown');
}

export function saveErrorMessage(errorCode: string | null): string {
  return translate(saveErrorTranslationKeys[errorCode ?? ''] ?? 'errors.saveFailed');
}

export function testErrorMessage(errorCode: string | null): string {
  return translate(reasonTranslationKeys[errorCode ?? ''] ?? 'errors.testFailed');
}

export function securityModeLabel(
  securityMode: SmtpSecurityMode | null,
): string {
  if (!securityMode) return translate('common.notConfigured');
  return translate(`security.options.${securityMode}`);
}
