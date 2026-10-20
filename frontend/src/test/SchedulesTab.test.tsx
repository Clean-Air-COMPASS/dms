import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import SchedulesTab, { scheduleCadence } from '../SchedulesTab';
import * as api from '../api';

vi.mock('../api', () => ({ listExternalAPISchedules: vi.fn(), previewSchedule: vi.fn(), updateSchedule: vi.fn() }));
const schedule: api.JobSchedule = { job_schedule_id: 1, task: 'openaq_import', cron_expr: '0 * * * *', timezone: 'UTC', enabled: true, allow_overlap: false };
const source: api.ExternalAPI = { external_api_id: 1, name: 'OpenAQ', enabled: true, is_runnable: true, runnable_reason: 'ready' };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.listExternalAPISchedules).mockResolvedValue([schedule]);
  vi.mocked(api.previewSchedule).mockResolvedValue({ valid: true, next_runs: ['2026-09-08T08:00:00Z'] });
});

describe('schedule cadence presentation', () => {
  it.each([
    ['* * * * *', 'everyMinute'], ['*/15 * * * *', 'everyMinutes'], ['0 * * * *', 'hourly'], ['30 7 * * *', 'daily'],
    ['*/7 * * * *', 'custom'], ['0 0 * * MON-FRI', 'custom'], ['0 0 L * *', 'custom'], ['invalid', 'custom'],
  ])('summarizes %s without inventing a regular interval', (cron, key) => expect(scheduleCadence(cron).key).toBe(key));
});

it('names the import and explains a configured schedule blocked by a disabled source', async () => {
  render(<SchedulesTab selectedExternalAPI={{ ...source, enabled: false, is_runnable: false, runnable_reason: 'disabled' }} />);
  expect(await screen.findByRole('heading', { name: 'Run OpenAQ import' })).toBeVisible();
  expect(screen.getByText('Schedule saved. This Data Source is disabled.', { exact: false })).toBeVisible();
  expect(await screen.findByText('Cadence preview: every hour at minute 00 (UTC).')).toBeVisible();
  expect(screen.getByLabelText('Start another run while one is still running')).toHaveAccessibleDescription(/increasing provider requests/);
});

it('keeps invalid cron visible, announces the error, and prevents saving', async () => {
  vi.mocked(api.previewSchedule).mockResolvedValue({ valid: false, next_runs: [] });
  render(<SchedulesTab selectedExternalAPI={source} />);
  const cron = await screen.findByLabelText('Run timing (cron)');
  fireEvent.change(cron, { target: { value: 'not cron' } });
  expect(await screen.findByRole('alert')).toHaveTextContent('Enter a valid cron expression');
  expect(cron).toHaveValue('not cron');
  expect(cron).toHaveAttribute('aria-invalid', 'true');
  expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  expect(api.updateSchedule).not.toHaveBeenCalled();
});

it('blocks duplicate submissions and retains values after a failed save, then confirms a retry', async () => {
  let reject!: (error: Error) => void;
  vi.mocked(api.updateSchedule).mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
  render(<SchedulesTab selectedExternalAPI={source} />);
  const cron = await screen.findByLabelText('Run timing (cron)');
  fireEvent.change(cron, { target: { value: '*/15 * * * *' } });
  const form = screen.getByRole('form', { name: 'Run OpenAQ import' });
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  expect(cron).toBeDisabled();
  expect(api.updateSchedule).toHaveBeenCalledTimes(1);
  reject(new Error('fixture failure'));
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(cron).toHaveValue('*/15 * * * *');
  vi.mocked(api.updateSchedule).mockResolvedValueOnce({ ...schedule, cron_expr: '*/15 * * * *' });
  fireEvent.submit(form);
  expect(await screen.findByText('Schedule updated')).toBeVisible();
});

it('does not show a previous expression preview after editing', async () => {
  render(<SchedulesTab selectedExternalAPI={source} />);
  await screen.findByText('Cadence preview: every hour at minute 00 (UTC).');
  fireEvent.change(screen.getByLabelText('Run timing (cron)'), { target: { value: '0 0 L * *' } });
  expect(screen.queryByText('Cadence preview: every hour at minute 00 (UTC).')).not.toBeInTheDocument();
  await waitFor(() => expect(api.previewSchedule).toHaveBeenCalledWith('0 0 L * *'));
  expect(await screen.findByText('Custom cadence. The next matching times are listed below.')).toBeVisible();
});

it.each([
  [{ ...source, is_runnable: false, runnable_reason: 'paid_provider_requests_disabled' as const }, 'Schedule saved. This Data Source is not ready to import.'],
  [{ external_api_id: 1, name: 'OpenAQ', enabled: true }, 'Schedule saved. Data Source readiness is unavailable.'],
])('explains source readiness without assuming it can run', async (selectedSource, message) => {
  render(<SchedulesTab selectedExternalAPI={selectedSource} />);
  expect(await screen.findByText(message, { exact: false })).toBeVisible();
});

it('shows when a valid advanced expression has no upcoming matching times', async () => {
  vi.mocked(api.previewSchedule).mockResolvedValue({ valid: true, next_runs: [] });
  render(<SchedulesTab selectedExternalAPI={source} />);
  expect(await screen.findByText("No upcoming matching times were found within the scheduler's search window.")).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
