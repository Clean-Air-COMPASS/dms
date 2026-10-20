import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getAdministratorSummaryConfiguration,
  getEmailConfiguration,
  previewAdministratorSummary,
  sendAdministratorSummaryTest,
  sendEmailTest,
  updateAdministratorSummaryConfiguration,
  updateEmailConfiguration,
} from '../email/api';
import type { EmailConfigurationUpdate } from '../email/types';
import { reasonMessage } from '../email/presentation';
import i18n from '../i18n';

const authMocks = vi.hoisted(() => ({ authFetchJson: vi.fn() }));

vi.mock('../auth', () => ({ authFetchJson: authMocks.authFetchJson }));

describe('email administration API', () => {
  beforeEach(() => authMocks.authFetchJson.mockReset());

  it('reads the safe saved configuration contract', async () => {
    authMocks.authFetchJson.mockResolvedValue({ status: 'not_configured' });

    await getEmailConfiguration();

    expect(authMocks.authFetchJson).toHaveBeenCalledWith('/admin/email/configuration');
  });

  it('preserves a saved password when smtp_password is omitted', async () => {
    const update: EmailConfigurationUpdate = {
      enabled: true,
      smtp_host: 'smtp.example.com',
      smtp_port: 587,
      smtp_security_mode: 'starttls',
      smtp_username: 'smtp-user',
      from_email: 'sender@example.com',
      from_display_name: 'CompassAQ',
      reply_to_email: null,
      administrator_recipients: ['admin@example.com'],
    };
    authMocks.authFetchJson.mockResolvedValue({ status: 'needs_attention' });

    await updateEmailConfiguration(update);

    const request = authMocks.authFetchJson.mock.calls[0][1];
    expect(request.method).toBe('PUT');
    expect(JSON.parse(request.body)).toEqual(update);
    expect(request.body).not.toContain('smtp_password');
  });

  it('sends null only for a deliberate password clear', async () => {
    const update: EmailConfigurationUpdate = {
      enabled: false,
      smtp_host: 'smtp.example.com',
      smtp_port: 587,
      smtp_security_mode: 'starttls',
      smtp_username: null,
      smtp_password: null,
      from_email: 'sender@example.com',
      from_display_name: null,
      reply_to_email: null,
      administrator_recipients: [],
    };
    authMocks.authFetchJson.mockResolvedValue({ status: 'disabled' });

    await updateEmailConfiguration(update);

    expect(JSON.parse(authMocks.authFetchJson.mock.calls[0][1].body).smtp_password).toBeNull();
  });

  it('tests the saved default recipient unless a one-time recipient is supplied', async () => {
    authMocks.authFetchJson.mockResolvedValue({ delivery_status: 'sent' });

    await sendEmailTest();
    await sendEmailTest('one-time@example.com');

    expect(JSON.parse(authMocks.authFetchJson.mock.calls[0][1].body)).toEqual({});
    expect(JSON.parse(authMocks.authFetchJson.mock.calls[1][1].body)).toEqual({
      recipient: 'one-time@example.com',
    });
  });

  it('uses the dedicated summary endpoints without mixing transport configuration', async () => {
    authMocks.authFetchJson.mockResolvedValue({ schedule_status: 'summary_off' });

    await getAdministratorSummaryConfiguration();
    await updateAdministratorSummaryConfiguration({
      enabled: true,
      cadence: 'daily',
      daily_send_time: '07:00:00',
      reporting_timezone_mode: 'override',
      reporting_timezone_override: 'America/Los_Angeles',
    });
    await previewAdministratorSummary({
      cadence: 'hourly',
      reporting_timezone_mode: 'override',
      reporting_timezone_override: 'UTC',
    });
    await sendAdministratorSummaryTest({ recipient: 'one-time@example.com' });

    expect(authMocks.authFetchJson.mock.calls.map((call) => call[0])).toEqual([
      '/admin/email/administrator-summary',
      '/admin/email/administrator-summary',
      '/admin/email/administrator-summary/preview',
      '/admin/email/administrator-summary/test',
    ]);
    expect(authMocks.authFetchJson.mock.calls[1][1].method).toBe('PUT');
    expect(JSON.parse(authMocks.authFetchJson.mock.calls[2][1].body)).toEqual({
      cadence: 'hourly',
      reporting_timezone_mode: 'override',
      reporting_timezone_override: 'UTC',
    });
    expect(JSON.parse(authMocks.authFetchJson.mock.calls[3][1].body)).toEqual({
      recipient: 'one-time@example.com',
    });
  });

  it.each([
    ['smtp_dns_failure', 'SMTP server name could not be found'],
    ['smtp_connection_timeout', 'did not respond in time'],
    ['smtp_connection_failed', 'could not connect'],
    ['smtp_tls_error', 'secure SMTP connection failed'],
    ['smtp_authentication_failed', 'rejected the saved username or password'],
    ['smtp_sender_rejected', 'rejected the sender address'],
    ['smtp_recipient_rejected', 'rejected the test recipient'],
    ['smtp_relay_denied', 'would not relay'],
    ['smtp_server_disconnected', 'disconnected before delivery completed'],
    ['smtp_server_error', 'unexpected error'],
    ['smtp_secret_unavailable', 'saved SMTP password cannot be read'],
  ])('translates the backend %s code without exposing it', async (errorCode, expectedText) => {
    await i18n.changeLanguage('en');
    const message = reasonMessage(errorCode);
    expect(message).toContain(expectedText);
    expect(message).not.toContain(errorCode);
  });
});
