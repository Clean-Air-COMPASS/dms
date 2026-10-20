import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminSources from '../AdminSources';
import i18n from '../i18n';

const mocks = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), run: vi.fn() }));
vi.mock('../api', () => ({ listExternalAPIs: mocks.list, runImport: mocks.run }));
vi.mock('../auth', () => ({ authFetchJson: mocks.detail }));
vi.mock('../AdminSourceForm', () => ({ default: () => null }));
vi.mock('../SchedulesTab', () => ({ default: () => null }));

const prior = {
  external_api_id: 3, provider_code: 'airgradient', name: 'AirGradient',
  enabled: true, is_runnable: true, device_count: 3,
  latest_import: { job_run_id: 1, status: 'success', summary: { devices_processed: 3 } },
};

beforeEach(async () => {
  vi.resetAllMocks();
  await i18n.changeLanguage('en');
  mocks.detail.mockResolvedValue(prior);
});

function renderSource() {
  render(<MemoryRouter><AdminSources onClose={() => {}} preselectExternalApiId={3} /></MemoryRouter>);
}

it.each(['failed', 'success'])('shows the completed %s run without a page reload and retains its result', async status => {
  const initial = status === 'failed' ? prior : { ...prior, latest_import: { ...prior.latest_import, status: 'failed' } };
  mocks.detail.mockResolvedValue(initial);
  const completed = {
    ...prior,
    latest_import: { job_run_id: 2, status, summary: { devices_processed: 3 },
      error_message: status === 'failed' ? 'AirGradient acquisition failed: 3 locations could not be reached' : null },
  };
  mocks.list.mockResolvedValueOnce([initial]).mockResolvedValueOnce([completed]);
  mocks.run.mockResolvedValue({ ok: true, status: 200, data: { job_run_id: 2, returncode: status === 'failed' ? 1 : 0 } });
  renderSource();
  const monitoring = await screen.findByRole('region', { name: 'Monitoring' });
  expect(within(monitoring).getByText(status === 'failed' ? 'Success' : 'Failed')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Run import now' }));
  await waitFor(() => expect(within(monitoring).getByText(status === 'failed' ? 'Failed' : 'Success')).toBeVisible());
  expect(mocks.list).toHaveBeenLastCalledWith({ skipCache: true });
  expect(screen.getByText(/"job_run_id": 2/)).toBeVisible();
  if (status === 'failed') expect(within(monitoring).getByText(completed.latest_import.error_message!)).toBeVisible();
});

it.each(['request_failed', 'source_missing'])('keeps the run result and makes monitoring unavailable when refresh is %s', async failure => {
  mocks.list.mockResolvedValueOnce([prior]);
  if (failure === 'request_failed') mocks.list.mockRejectedValueOnce(new Error('Synthetic refresh outage'));
  else mocks.list.mockResolvedValueOnce([]);
  mocks.run.mockResolvedValue({ ok: true, status: 200, data: { job_run_id: 2, returncode: 1 } });
  renderSource();
  await screen.findByRole('region', { name: 'Monitoring' });
  fireEvent.click(screen.getByRole('button', { name: 'Run import now' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t('common:errors.loadDataSources'));
  expect(screen.queryByRole('region', { name: 'Monitoring' })).not.toBeInTheDocument();
  expect(screen.getByText(/"job_run_id": 2/)).toBeVisible();
});
