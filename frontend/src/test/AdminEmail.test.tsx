import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AdminHome from '../AdminHome';
import { ApiError } from '../apiError';
import AdminEmail from '../email/AdminEmail';
import type { EmailConfiguration } from '../email/types';
import i18n from '../i18n';

const emailApiMocks = vi.hoisted(() => ({
  getEmailConfiguration: vi.fn(),
  updateEmailConfiguration: vi.fn(),
  sendEmailTest: vi.fn(),
  getAdministratorSummaryConfiguration: vi.fn(),
  updateAdministratorSummaryConfiguration: vi.fn(),
  previewAdministratorSummary: vi.fn(),
  sendAdministratorSummaryTest: vi.fn(),
}));

vi.mock('../auth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { email: 'admin@example.com', scopes: ['users:write'], preferred_language_code: null },
    logout: vi.fn(),
    isLoading: false,
  }),
}));

vi.mock('../email/api', () => emailApiMocks);

function configuration(overrides: Partial<EmailConfiguration> = {}): EmailConfiguration {
  return {
    enabled: true,
    status: 'ready',
    status_reason_codes: [],
    smtp_host: 'smtp.example.com',
    smtp_port: 587,
    smtp_security_mode: 'starttls',
    smtp_username: 'smtp-user',
    password_configured: true,
    from_email: 'sender@example.com',
    from_display_name: 'CompassAQ Alerts',
    reply_to_email: 'support@example.com',
    administrator_recipients: ['primary@example.com', 'backup@example.com'],
    last_test_status: 'success',
    last_test_error_code: null,
    last_tested_at: '2026-08-21T16:30:00Z',
    created_at: '2026-08-20T12:00:00Z',
    updated_at: '2026-08-21T16:30:00Z',
    ...overrides,
  };
}

function renderPage() {
  return render(<MemoryRouter><AdminEmail /></MemoryRouter>);
}

describe('Email & notifications administration', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
    Object.values(emailApiMocks).forEach((mock) => mock.mockReset());
    emailApiMocks.getAdministratorSummaryConfiguration.mockResolvedValue({
      enabled: false,
      cadence: 'daily',
      daily_send_time: '07:00:00',
      reporting_timezone: 'UTC',
      reporting_timezone_source: 'system_preferences',
      reporting_timezone_override: null,
      system_timezone: 'UTC',
      effective_at: null,
      schedule_status: 'summary_off',
      blocker_codes: [],
      email_delivery_ready: false,
      next_due_at: null,
      next_reporting_window: null,
      last_scheduled_delivery: null,
    });
  });

  it('opens a fresh installation in grouped edit mode with suggested local defaults', async () => {
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration({
      enabled: false,
      status: 'not_configured',
      status_reason_codes: ['email_not_configured'],
      smtp_host: null,
      smtp_port: null,
      smtp_security_mode: null,
      smtp_username: null,
      password_configured: false,
      from_email: null,
      from_display_name: null,
      reply_to_email: null,
      administrator_recipients: [],
      last_test_status: null,
      last_tested_at: null,
    }));

    renderPage();

    expect(await screen.findByRole('heading', { name: 'Email & notifications' })).toBeInTheDocument();
    expect(screen.getByText('Not configured', { selector: '.email-status-badge' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'SMTP connection' })).toBeInTheDocument();
    expect(screen.getByLabelText('Port')).toHaveValue(587);
    expect(screen.getByLabelText('Security')).toHaveValue('starttls');
    expect(screen.getByLabelText('Enable email delivery')).toBeChecked();
    expect(within(screen.getByRole('form', { name: i18n.t('emailNotifications:form.delivery.title') })).getByRole('button', { name: 'Save changes' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send test email' })).toBeDisabled();
  });

  it('shows the backend-owned ready state and readable saved summary without raw enum values', async () => {
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration());

    renderPage();

    expect(await screen.findByText('Ready', { selector: '.email-status-badge' })).toBeInTheDocument();
    expect(screen.getByText('CompassAQ Alerts <sender@example.com>')).toBeInTheDocument();
    expect(screen.getAllByText('Password configured').length).toBeGreaterThan(0);
    expect(screen.getByText('2 recipients')).toBeInTheDocument();
    expect(screen.getByText('STARTTLS')).toBeInTheDocument();
    expect(screen.queryByText('starttls')).not.toBeInTheDocument();
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/SMTP password/i)).not.toBeInTheDocument();
  });

  it('saves a fresh authenticated configuration with a new write-only password', async () => {
    const fresh = configuration({
      enabled: false,
      status: 'not_configured',
      status_reason_codes: ['email_not_configured'],
      smtp_host: null,
      smtp_port: null,
      smtp_security_mode: null,
      smtp_username: null,
      password_configured: false,
      from_email: null,
      from_display_name: null,
      reply_to_email: null,
      administrator_recipients: [],
      last_test_status: null,
      last_tested_at: null,
    });
    emailApiMocks.getEmailConfiguration.mockResolvedValue(fresh);
    emailApiMocks.updateEmailConfiguration.mockResolvedValue(configuration({
      status: 'needs_attention',
      status_reason_codes: ['test_required'],
      last_test_status: null,
      last_tested_at: null,
      administrator_recipients: ['primary@example.com'],
    }));
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText('SMTP server'), 'smtp.example.com');
    await user.type(screen.getByLabelText('SMTP username'), 'smtp-user');
    await user.type(screen.getByLabelText('SMTP password'), 'new-secret');
    await user.type(screen.getByLabelText('From email'), 'sender@example.com');
    await user.type(screen.getByLabelText('From display name'), 'CompassAQ Alerts');
    await user.type(screen.getByLabelText('Recipient 1'), 'primary@example.com');
    await user.click(within(screen.getByRole('form', { name: i18n.t('emailNotifications:form.delivery.title') })).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(emailApiMocks.updateEmailConfiguration).toHaveBeenCalledTimes(1));
    expect(emailApiMocks.updateEmailConfiguration.mock.calls[0][0]).toMatchObject({
      enabled: true,
      smtp_host: 'smtp.example.com',
      smtp_port: 587,
      smtp_security_mode: 'starttls',
      smtp_username: 'smtp-user',
      smtp_password: 'new-secret',
      from_email: 'sender@example.com',
      administrator_recipients: ['primary@example.com'],
    });
    expect(screen.queryByDisplayValue('new-secret')).not.toBeInTheDocument();
  });

  it('validates recipients inline, focuses the first error, and supports add/remove controls', async () => {
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration());
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Edit configuration' }));
    await user.click(screen.getByRole('button', { name: 'Add recipient' }));
    expect(screen.getByLabelText('Recipient 3')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Recipient 3'), 'not-an-email');
    await user.click(within(screen.getByRole('form', { name: i18n.t('emailNotifications:form.delivery.title') })).getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByText('Enter one valid email address.')).toBeInTheDocument();
    expect(screen.getByLabelText('Recipient 3')).toHaveFocus();
    expect(emailApiMocks.updateEmailConfiguration).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Remove recipient 3' }));
    expect(screen.queryByLabelText('Recipient 3')).not.toBeInTheDocument();
  });

  it('preserves the write-only password when another field is saved', async () => {
    const current = configuration();
    emailApiMocks.getEmailConfiguration.mockResolvedValue(current);
    emailApiMocks.updateEmailConfiguration.mockResolvedValue({
      ...current,
      from_display_name: 'Updated alerts',
      status: 'needs_attention',
      status_reason_codes: ['test_required'],
      last_test_status: null,
      last_tested_at: null,
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Edit configuration' }));
    await user.clear(screen.getByLabelText('From display name'));
    await user.type(screen.getByLabelText('From display name'), 'Updated alerts');
    expect(screen.getByRole('button', { name: 'Send test email' })).toBeDisabled();
    await user.click(within(screen.getByRole('form', { name: i18n.t('emailNotifications:form.delivery.title') })).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(emailApiMocks.updateEmailConfiguration).toHaveBeenCalledTimes(1));
    const update = emailApiMocks.updateEmailConfiguration.mock.calls[0][0];
    expect(update.from_display_name).toBe('Updated alerts');
    expect(update).not.toHaveProperty('smtp_password');
    expect(await screen.findByRole('status')).toHaveTextContent('Email configuration saved.');
  });

  it('requires confirmation before deliberately clearing the password', async () => {
    const current = configuration();
    emailApiMocks.getEmailConfiguration.mockResolvedValue(current);
    emailApiMocks.updateEmailConfiguration.mockResolvedValue(configuration({
      enabled: false,
      smtp_username: null,
      password_configured: false,
      status: 'disabled',
      last_test_status: 'success',
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Edit configuration' }));
    await user.click(screen.getByRole('button', { name: 'Clear password' }));
    const dialog = screen.getByRole('dialog', { name: 'Clear the saved SMTP password?' });
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.click(within(dialog).getByRole('button', { name: 'Clear password' }));
    expect(screen.getByText('Password will be cleared')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('SMTP username'));
    await user.click(screen.getByLabelText('Enable email delivery'));
    await user.click(within(screen.getByRole('form', { name: i18n.t('emailNotifications:form.delivery.title') })).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(emailApiMocks.updateEmailConfiguration).toHaveBeenCalledTimes(1));
    expect(emailApiMocks.updateEmailConfiguration.mock.calls[0][0]).toMatchObject({
      enabled: false,
      smtp_username: null,
      smtp_password: null,
    });
  });

  it('never sends an empty replacement password and clears transient secret state on cancel', async () => {
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration());
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Edit configuration' }));
    await user.click(screen.getByRole('button', { name: 'Replace password' }));
    const passwordInput = screen.getByLabelText('New SMTP password');
    expect(passwordInput).toHaveAttribute('autocomplete', 'new-password');
    await user.type(passwordInput, 'transient-secret');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(emailApiMocks.updateEmailConfiguration).not.toHaveBeenCalled();
    expect(screen.queryByDisplayValue('transient-secret')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('New SMTP password')).not.toBeInTheDocument();
  });

  it('shows an actionable authentication failure, SMTP code details, and successful retry', async () => {
    const needsTest = configuration({
      status: 'needs_attention',
      status_reason_codes: ['test_required'],
      last_test_status: null,
      last_tested_at: null,
    });
    const failed = configuration({
      status: 'needs_attention',
      status_reason_codes: ['smtp_authentication_failed'],
      last_test_status: 'failed',
      last_test_error_code: 'smtp_authentication_failed',
    });
    const ready = configuration();
    emailApiMocks.getEmailConfiguration
      .mockResolvedValueOnce(needsTest)
      .mockResolvedValueOnce(failed)
      .mockResolvedValueOnce(ready);
    emailApiMocks.sendEmailTest
      .mockRejectedValueOnce(new ApiError({
        status: 502,
        errorCode: 'smtp_authentication_failed',
        errorContext: { smtp_code: 535 },
      }))
      .mockResolvedValueOnce({
        delivery_status: 'sent',
        recipient: 'primary@example.com',
        sent_at: '2026-08-21T16:30:00Z',
      });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Send test email' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('rejected the saved username or password');
    await user.click(screen.getByText('More details'));
    expect(screen.getByText('SMTP response code: 535')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry test' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Test email sent to primary@example.com.');
    expect(emailApiMocks.sendEmailTest).toHaveBeenNthCalledWith(1, undefined);
    expect(emailApiMocks.sendEmailTest).toHaveBeenNthCalledWith(2, undefined);
    expect(await screen.findByText('Ready', { selector: '.email-status-badge' })).toBeInTheDocument();
  });

  it('announces test delivery progress while the saved configuration is being tested', async () => {
    let resolveTest: ((value: {
      delivery_status: 'sent';
      recipient: string;
      sent_at: string;
    }) => void) | undefined;
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration());
    emailApiMocks.sendEmailTest.mockReturnValue(new Promise((resolve) => {
      resolveTest = resolve;
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Send test email' }));
    const sendingButton = screen.getByRole('button', { name: 'Sending test…' });
    expect(sendingButton).toBeDisabled();

    await act(async () => resolveTest?.({
      delivery_status: 'sent',
      recipient: 'primary@example.com',
      sent_at: '2026-08-21T16:30:00Z',
    }));
    expect(await screen.findByRole('status')).toHaveTextContent('Test email sent to primary@example.com.');
  });

  it('keeps the editor open and shows an actionable save failure', async () => {
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration());
    emailApiMocks.updateEmailConfiguration.mockRejectedValue(new Error('offline'));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Edit configuration' }));
    await user.clear(screen.getByLabelText('From display name'));
    await user.type(screen.getByLabelText('From display name'), 'Updated alerts');
    await user.click(within(screen.getByRole('form', { name: i18n.t('emailNotifications:form.delivery.title') })).getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Email configuration could not be saved. Review the fields and try again.',
    );
    expect(screen.getByLabelText('From display name')).toHaveValue('Updated alerts');
    expect(within(screen.getByRole('form', { name: i18n.t('emailNotifications:form.delivery.title') })).getByRole('button', { name: 'Save changes' })).toBeEnabled();
  });

  it('confirms unencrypted SMTP without changing a deliberately saved port', async () => {
    const relay = configuration({
      smtp_username: null,
      password_configured: false,
    });
    emailApiMocks.getEmailConfiguration.mockResolvedValue(relay);
    emailApiMocks.updateEmailConfiguration.mockResolvedValue({
      ...relay,
      smtp_security_mode: 'none',
      status: 'needs_attention',
      status_reason_codes: ['test_required'],
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Edit configuration' }));
    await user.selectOptions(screen.getByLabelText('Security'), 'none');
    expect(screen.getByLabelText('Port')).toHaveValue(587);
    expect(screen.getByText('This connection will not be encrypted.')).toBeInTheDocument();
    await user.click(within(screen.getByRole('form', { name: i18n.t('emailNotifications:form.delivery.title') })).getByRole('button', { name: 'Save changes' }));
    const dialog = screen.getByRole('dialog', { name: 'Save unencrypted SMTP?' });
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.click(within(dialog).getByRole('button', { name: 'Save unencrypted SMTP' }));

    await waitFor(() => expect(emailApiMocks.updateEmailConfiguration).toHaveBeenCalledTimes(1));
    expect(emailApiMocks.updateEmailConfiguration.mock.calls[0][0]).toMatchObject({
      smtp_port: 587,
      smtp_security_mode: 'none',
      smtp_username: null,
    });
  });

  it('translates backend reason codes and the admin tile in Spanish', async () => {
    await i18n.changeLanguage('es');
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration({
      status: 'needs_attention',
      status_reason_codes: ['smtp_tls_error'],
      last_test_status: 'failed',
      last_test_error_code: 'smtp_tls_error',
    }));

    const { unmount } = renderPage();

    expect(await screen.findByRole('heading', { name: 'Correo y notificaciones' })).toBeInTheDocument();
    expect(screen.getByText('Requiere atención', { selector: '.email-status-badge' })).toBeInTheDocument();
    expect(screen.getByText(/Falló la conexión SMTP segura/)).toBeInTheDocument();
    expect(screen.queryByText('smtp_tls_error')).not.toBeInTheDocument();
    unmount();

    render(<MemoryRouter><AdminHome /></MemoryRouter>);
    expect(screen.getByRole('link', { name: /Correo y notificaciones/ })).toHaveAttribute('href', '/admin/email');
  });

  it('offers a focused retry when loading fails', async () => {
    emailApiMocks.getEmailConfiguration
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(configuration());
    const user = userEvent.setup();
    renderPage();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('could not be loaded');
    await user.click(within(alert).getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Ready', { selector: '.email-status-badge' })).toBeInTheDocument();
  });

  it.each(['en', 'es'])('presents the task order and concise ready overview in %s', async (language) => {
    await i18n.changeLanguage(language);
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration());
    const { container } = renderPage();
    await screen.findByRole('heading', { name: i18n.t('emailNotifications:workflow.activityTitle') });
    expect(Array.from(container.querySelectorAll('h2')).map((heading) => heading.textContent)).toEqual([
      i18n.t('emailNotifications:workflow.deliveryTitle'),
      i18n.t('emailNotifications:test.title'),
      i18n.t('emailNotifications:administratorSummary.title'),
      i18n.t('emailNotifications:workflow.activityTitle'),
    ]);
    const overview = screen.getByLabelText(i18n.t('emailNotifications:overview.title'));
    expect(overview).toHaveTextContent(i18n.t('emailNotifications:workflow.summary'));
    expect(overview).not.toHaveTextContent(i18n.t('emailNotifications:password.configured'));
    expect(container.querySelector('.email-fact-grid')).toBeNull();
    expect(container.querySelector('.admin-section-links')).toBeNull();
    expect(screen.getByLabelText(i18n.t('emailNotifications:administratorSummary.form.enabledLabel'))).toBeEnabled();
  });

  it.each([
    ['not_configured', ['email_not_configured'], 'configure', true],
    ['needs_attention', ['test_required'], 'test', false],
    ['needs_attention', ['smtp_host_missing'], 'configure', true],
  ] as const)('recommends the next task for %s with %s', async (status, reasons, action, blocked) => {
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration({
      status, status_reason_codes: [...reasons], enabled: status !== 'not_configured',
      last_test_status: null, last_tested_at: null,
    }));
    renderPage();
    const overview = await screen.findByLabelText('Overall status');
    expect(overview).toHaveTextContent(i18n.t(`emailNotifications:workflow.${action}`));
    const testButton = screen.getByRole('button', { name: 'Send test email' });
    if (blocked) expect(testButton).toBeDisabled();
    else expect(testButton).toBeEnabled();
  });

  it('recommends monitoring once the saved summary is enabled', async () => {
    emailApiMocks.getEmailConfiguration.mockResolvedValue(configuration());
    emailApiMocks.getAdministratorSummaryConfiguration.mockResolvedValue({
      ...await emailApiMocks.getAdministratorSummaryConfiguration(),
      enabled: true,
      schedule_status: 'waiting_for_first_scheduled_period',
    });
    renderPage();
    await waitFor(() => expect(screen.getByLabelText('Overall status')).toHaveTextContent('Monitor recent delivery activity'));
  });
});
