import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiError } from '../apiError';
import AdministratorSummarySection from '../email/AdministratorSummarySection';
import type {
  AdministratorSummaryConfiguration,
  AdministratorSummaryPreview,
} from '../email/types';
import i18n from '../i18n';

const emailApiMocks = vi.hoisted(() => ({
  getAdministratorSummaryConfiguration: vi.fn(),
  updateAdministratorSummaryConfiguration: vi.fn(),
  previewAdministratorSummary: vi.fn(),
  sendAdministratorSummaryTest: vi.fn(),
}));

vi.mock('../email/api', () => emailApiMocks);

function summaryConfiguration(
  overrides: Partial<AdministratorSummaryConfiguration> = {},
): AdministratorSummaryConfiguration {
  return {
    enabled: false,
    cadence: 'daily',
    daily_send_time: '07:00:00',
    reporting_timezone: 'America/Los_Angeles',
    reporting_timezone_source: 'system_preferences',
    reporting_timezone_override: null,
    system_timezone: 'America/Los_Angeles',
    effective_at: null,
    schedule_status: 'summary_off',
    blocker_codes: [],
    email_delivery_ready: true,
    next_due_at: null,
    next_reporting_window: null,
    last_scheduled_delivery: null,
    ...overrides,
  };
}

function summaryPreview(overrides: Partial<AdministratorSummaryPreview> = {}): AdministratorSummaryPreview {
  return {
    reporting_window: {
      period_start: '2026-08-20T07:00:00Z',
      period_end: '2026-08-21T07:00:00Z',
    },
    overall_status: 'needs_attention',
    attention_count: 3,
    subject: '[CompassAQ] Summary — Aug 20 — 3 issues need attention',
    html_body: '<!doctype html><html><body><h1>Needs attention</h1><h2>Needs attention</h2><p>QC issue details</p><h2>Data imports</h2><h2>System events</h2></body></html>',
    text_body: 'Needs attention\n\nNeeds attention\nQC issue details\n\nData imports\nSystem events',
    ...overrides,
  };
}

function renderSection(defaultRecipient = 'saved@example.com') {
  return render(<AdministratorSummarySection defaultRecipient={defaultRecipient} />);
}

describe('Administrator summary administration', () => {
  it.each(['en', 'es'])('separates saved cadence from disabled state and unsaved edits in %s', async language => {
    await i18n.changeLanguage(language);
    emailApiMocks.getAdministratorSummaryConfiguration.mockResolvedValue(summaryConfiguration());
    renderSection();
    const cadence = i18n.t('emailNotifications:administratorSummary.schedule.dailyAt', { time: new Intl.DateTimeFormat(language, { hour: 'numeric', minute: '2-digit', timeZone: 'UTC' }).format(new Date('2020-01-01T07:00:00Z')) });
    const disabled = i18n.t('emailNotifications:administratorSummary.schedule.whenEnabled', { cadence });
    expect(await screen.findByRole('heading', { name: disabled })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: i18n.t('emailNotifications:administratorSummary.form.enabledLabel') }));
    fireEvent.change(screen.getByLabelText(i18n.t('emailNotifications:administratorSummary.form.sendTimeLabel')), { target: { value: '08:30' } });
    expect(screen.getByRole('heading', { name: disabled })).toBeInTheDocument();
  });
  beforeEach(async () => {
    await i18n.changeLanguage('en');
    Object.values(emailApiMocks).forEach((mock) => mock.mockReset());
    emailApiMocks.getAdministratorSummaryConfiguration.mockResolvedValue(summaryConfiguration());
  });

  it('shows the fresh Summary off state and saves an enabled Daily schedule', async () => {
    const user = userEvent.setup();
    const updated = summaryConfiguration({
      enabled: true,
      daily_send_time: '08:30:00',
      reporting_timezone: 'Asia/Manila',
      reporting_timezone_source: 'summary_override',
      reporting_timezone_override: 'Asia/Manila',
      effective_at: '2026-08-21T17:00:00Z',
      schedule_status: 'waiting_for_first_scheduled_period',
      next_due_at: '2026-08-22T12:30:00Z',
      next_reporting_window: {
        period_start: '2026-08-21T04:00:00Z',
        period_end: '2026-08-22T04:00:00Z',
      },
    });
    emailApiMocks.updateAdministratorSummaryConfiguration.mockResolvedValue(updated);
    renderSection();

    expect(await screen.findByText('Summary off')).toBeInTheDocument();
    expect(screen.getByLabelText('Enable administrator summary')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    await user.click(screen.getByLabelText('Enable administrator summary'));
    await user.clear(screen.getByLabelText('Send time'));
    await user.type(screen.getByLabelText('Send time'), '08:30');
    await user.selectOptions(screen.getByLabelText('Reporting timezone'), 'Asia/Manila');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(emailApiMocks.updateAdministratorSummaryConfiguration).toHaveBeenCalledWith({
      enabled: true,
      cadence: 'daily',
      daily_send_time: '08:30:00',
      reporting_timezone_mode: 'override',
      reporting_timezone_override: 'Asia/Manila',
    }));
    expect(screen.getByText('Waiting for first period')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Administrator summary schedule saved.');
    expect(document.activeElement).toBe(screen.getByRole('status'));
  });

  it('keeps America/Los_Angeles available and submits it for the development configuration', async () => {
    const user = userEvent.setup();
    emailApiMocks.getAdministratorSummaryConfiguration.mockResolvedValue(summaryConfiguration({
      reporting_timezone: 'America/New_York',
      system_timezone: 'America/New_York',
    }));
    emailApiMocks.updateAdministratorSummaryConfiguration.mockResolvedValue(summaryConfiguration({
      reporting_timezone: 'America/Los_Angeles',
      reporting_timezone_source: 'summary_override',
      reporting_timezone_override: 'America/Los_Angeles',
    }));
    renderSection();

    const timezoneSelect = await screen.findByLabelText('Reporting timezone');
    await user.selectOptions(timezoneSelect, 'America/Los_Angeles');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(emailApiMocks.updateAdministratorSummaryConfiguration).toHaveBeenCalledWith({
      enabled: false,
      cadence: 'daily',
      daily_send_time: '07:00:00',
      reporting_timezone_mode: 'override',
      reporting_timezone_override: 'America/Los_Angeles',
    }));
  });

  it('preserves an arbitrary backend-valid IANA timezone when the runtime fallback omits it', async () => {
    const supportedValuesOf = vi.spyOn(Intl, 'supportedValuesOf').mockImplementation(() => {
      throw new Error('timeZone discovery is unavailable');
    });

    emailApiMocks.getAdministratorSummaryConfiguration.mockResolvedValue(summaryConfiguration({
      reporting_timezone: 'Pacific/Apia',
      reporting_timezone_source: 'summary_override',
      reporting_timezone_override: 'Pacific/Apia',
    }));

    try {
      renderSection();

      const timezoneSelect = await screen.findByLabelText('Reporting timezone');
      expect(timezoneSelect).toHaveValue('Pacific/Apia');
      expect(screen.getByRole('option', { name: /Pacific\/Apia/ })).toBeInTheDocument();
    } finally {
      supportedValuesOf.mockRestore();
    }
  });

  it('keeps Hourly and the 15-minute commissioning cadence in Advanced / Testing', async () => {
    const user = userEvent.setup();
    renderSection();

    const disclosure = await screen.findByText('Advanced / Testing');
    expect(disclosure.closest('details')).not.toHaveAttribute('open');
    await user.click(disclosure);
    await user.click(screen.getByLabelText('Hourly'));
    expect(screen.getByText('Each email summarizes the previous completed hour.')).toBeInTheDocument();
    await user.click(screen.getByLabelText('Testing — every 15 minutes'));
    expect(screen.getByRole('note')).toHaveTextContent('can generate frequent email');
    expect(screen.getByText('Each email summarizes the previous completed 15-minute period.')).toBeInTheDocument();
  });

  it('automatically reveals a saved every-15-minute testing schedule', async () => {
    emailApiMocks.getAdministratorSummaryConfiguration.mockResolvedValue(summaryConfiguration({
      enabled: true,
      cadence: 'every_15_minutes',
      schedule_status: 'waiting_for_first_scheduled_period',
    }));

    renderSection();

    expect(await screen.findByLabelText('Testing — every 15 minutes')).toBeChecked();
    expect(screen.getByRole('note')).toHaveTextContent('testing or commissioning');
  });

  it('shows backend-owned blocked, next-due, failed, and delivery-unknown information', async () => {
    emailApiMocks.getAdministratorSummaryConfiguration.mockResolvedValue(summaryConfiguration({
      enabled: true,
      schedule_status: 'blocked_email_delivery',
      blocker_codes: ['test_required'],
      email_delivery_ready: false,
      next_due_at: '2026-08-22T14:00:00Z',
      next_reporting_window: {
        period_start: '2026-08-21T07:00:00Z',
        period_end: '2026-08-22T07:00:00Z',
      },
      last_scheduled_delivery: {
        status: 'delivery_unknown',
        period_start: '2026-08-20T07:00:00Z',
        period_end: '2026-08-21T07:00:00Z',
        last_attempted_at: '2026-08-21T14:00:00Z',
        sent_at: null,
        error_code: 'smtp_server_disconnected',
      },
    }));

    renderSection();

    expect(await screen.findByText('Blocked')).toBeInTheDocument();
    expect(screen.getByText('Save is complete. Send a test email to verify delivery.')).toBeInTheDocument();
    expect(screen.getByText('Outcome unknown')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send test summary' })).toBeDisabled();
    expect(screen.getAllByText(/Aug 22, 2026/).length).toBeGreaterThan(0);
  });

  it.each([
    ['last_summary_sent', 'Last summary sent'],
    ['last_summary_failed', 'Last summary failed'],
    ['delivery_unknown', 'Delivery outcome unknown'],
  ] as const)('renders the backend %s state as localized text', async (status, label) => {
    emailApiMocks.getAdministratorSummaryConfiguration.mockResolvedValue(summaryConfiguration({
      enabled: true,
      schedule_status: status,
    }));

    renderSection();

    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.queryByText(status)).not.toBeInTheDocument();
  });

  it('previews the real HTML and plain-text representations without requiring a save', async () => {
    const user = userEvent.setup();
    emailApiMocks.previewAdministratorSummary.mockResolvedValue(summaryPreview());
    renderSection();

    await user.click(await screen.findByText('Advanced / Testing'));
    await user.click(screen.getByLabelText('Hourly'));
    await user.click(screen.getByRole('button', { name: 'Preview summary' }));

    await waitFor(() => expect(emailApiMocks.previewAdministratorSummary).toHaveBeenCalledWith({
      cadence: 'hourly',
      daily_send_time: '07:00:00',
      reporting_timezone_mode: 'system',
      reporting_timezone_override: null,
    }));
    expect(screen.getByTitle('Rendered administrator summary email')).toHaveAttribute('sandbox', '');
    expect(screen.getByText('3 need attention')).toBeInTheDocument();
    expect(screen.getByText(/No email was sent/)).toBeInTheDocument();
    expect(document.activeElement).toBe(
      screen.getByRole('heading', { name: 'Summary preview' }).closest('section'),
    );
    await user.click(screen.getByRole('tab', { name: 'Plain text' }));
    expect(screen.getByText((_content, element) => (
      element?.tagName === 'PRE'
      && element.textContent?.includes('Data imports\nSystem events') === true
      && !element.textContent?.includes('QC activity')
    ))).toBeInTheDocument();
  });

  it('announces preview errors and moves focus to the result', async () => {
    const user = userEvent.setup();
    emailApiMocks.previewAdministratorSummary.mockRejectedValue(new Error('offline'));
    renderSection();

    await user.click(await screen.findByRole('button', { name: 'Preview summary' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('could not build the summary preview');
    expect(document.activeElement).toBe(alert);
  });

  it('confirms and sends a test summary to a non-persisted one-time recipient', async () => {
    const user = userEvent.setup();
    let resolveSend: ((value: unknown) => void) | undefined;
    emailApiMocks.sendAdministratorSummaryTest.mockReturnValue(new Promise((resolve) => {
      resolveSend = resolve;
    }));
    renderSection();

    await user.click(await screen.findByRole('button', { name: 'Send test summary' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByLabelText('Test summary recipient')).toHaveFocus();
    await user.clear(within(dialog).getByLabelText('Test summary recipient'));
    await user.type(within(dialog).getByLabelText('Test summary recipient'), 'one-time@example.com');
    await user.click(within(dialog).getByRole('button', { name: 'Send test summary' }));
    expect(within(dialog).getByRole('button', { name: 'Sending test summary…' })).toBeDisabled();
    resolveSend?.({ delivery_status: 'sent', recipient: 'one-time@example.com' });

    expect(await screen.findByRole('status')).toHaveTextContent('Test summary sent to one-time@example.com.');
    expect(emailApiMocks.sendAdministratorSummaryTest).toHaveBeenCalledWith(expect.objectContaining({
      recipient: 'one-time@example.com',
    }));
  });

  it('announces a test-summary transport failure without exposing a machine code', async () => {
    const user = userEvent.setup();
    emailApiMocks.sendAdministratorSummaryTest.mockRejectedValue(new ApiError({
      status: 504,
      errorCode: 'smtp_connection_timeout',
    }));
    renderSection();

    await user.click(await screen.findByRole('button', { name: 'Send test summary' }));
    await user.click(screen.getByRole('dialog').querySelector('.btn-primary') as HTMLElement);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('SMTP server did not respond in time');
    expect(alert).not.toHaveTextContent('smtp_connection_timeout');
    expect(document.activeElement).toBe(alert);
  });

  it('renders the schedule controls in Spanish at a narrow viewport', async () => {
    await i18n.changeLanguage('es');
    window.innerWidth = 390;
    renderSection();

    await waitFor(() => {
      expect(screen.getByText('Resumen para administradores', { selector: 'h2' })).toBeInTheDocument();
    });
    expect(screen.getByLabelText('Habilitar resumen para administradores')).toBeInTheDocument();
    expect(screen.getByLabelText('Zona horaria del informe')).toHaveValue('__system_timezone__');
    expect(screen.getByRole('option', { name: /Usar zona horaria del sistema/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Vista previa del resumen' })).toBeInTheDocument();
  });
});
