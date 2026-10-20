import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SetupWizard from '../SetupWizard';
import AdminSourceForm from '../AdminSourceForm';
import AdminSourcesList from '../AdminSourcesList';
import { listExternalAPIs, updateExternalAPI, type ExternalAPI } from '../api';
import i18n from '../i18n';

vi.mock('../auth', () => ({ useAuth: () => ({ isAuthenticated: false, user: null, logout: vi.fn(), isLoading: false }) }));
vi.mock('../api', async () => ({ ...await vi.importActual<typeof import('../api')>('../api'), listExternalAPIs: vi.fn(), updateExternalAPI: vi.fn() }));
const demo: ExternalAPI = { external_api_id: 4, provider_code: 'demo', name: 'Demo Data', enabled: true, requires_credential: false, has_api_key: false, is_configured: true, is_runnable: true, runnable_reason: 'ready', is_builtin: true, can_delete: false };

beforeEach(async () => { vi.clearAllMocks(); await act(() => i18n.changeLanguage('en')); });
afterEach(async () => { vi.restoreAllMocks(); await act(() => i18n.changeLanguage('en')); });

function setupApi(enabled = true) {
  const state = { ...demo, enabled };
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    if (String(input).endsWith('/setup/data-sources')) return new Response(JSON.stringify({ data_sources: [state] }));
    if (String(input).endsWith('/setup/data-source')) Object.assign(state, JSON.parse(String(init?.body)));
    return new Response(JSON.stringify({ success: true }));
  });
  return { state, fetch };
}

describe('Demo Data setup', () => {
  it.each([true, false])('renders persisted enabled=%s without credentials', async enabled => {
    setupApi(enabled);
    render(<SetupWizard initialAdminCreated onSetupComplete={vi.fn()} />);
    const toggle = await screen.findByRole('checkbox', { name: 'Enable Demo Data' });
    expect(toggle).toHaveProperty('checked', enabled);
    expect(screen.getByText('Demo Data')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'API Key' })).not.toBeInTheDocument();
  });
  it('persists clean-install opt-out across save, back, reload, skip and completion', async () => {
    const { state, fetch } = setupApi();
    const complete = vi.fn();
    const view = render(<SetupWizard initialAdminCreated onSetupComplete={complete} />);
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Enable Demo Data' }));
    await waitFor(() => expect(screen.getByRole('checkbox')).not.toBeChecked());
    expect(state.enabled).toBe(false);
    expect(JSON.parse(String(fetch.mock.calls.find(([url]) => String(url).endsWith('/setup/data-source'))?.[1]?.body))).toEqual({ external_api_id: 4, enabled: false });
    fireEvent.click(screen.getByRole('button', { name: 'Save Sources & Continue' }));
    fireEvent.click(await screen.findByRole('button', { name: '← Back' }));
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    view.unmount();
    render(<SetupWizard initialAdminCreated onSetupComplete={complete} />);
    expect(await screen.findByRole('checkbox')).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Skip for Now →' }));
    fireEvent.click(screen.getByRole('button', { name: 'Skip for Now →' }));
    expect(screen.getByText('Demo Data: Disabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Complete Setup & Start Using Platform' }));
    await waitFor(() => expect(complete).toHaveBeenCalled());
    expect(state.enabled).toBe(false);
    expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/setup/data-source'))).toHaveLength(1);
  });
  it('keeps persisted state and shows an error when saving fails', async () => {
    const { fetch } = setupApi();
    render(<SetupWizard initialAdminCreated onSetupComplete={vi.fn()} />);
    const toggle = await screen.findByRole('checkbox');
    fetch.mockResolvedValueOnce(new Response('{}', { status: 500 }));
    fireEvent.click(toggle);
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be saved');
    expect(toggle).toBeChecked();
    expect(toggle).toBeEnabled();
  });
  it('shows source-loading failures explicitly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('offline'));
    render(<SetupWizard initialAdminCreated onSetupComplete={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t('common:errors.loadDataSources'));
  });
});

describe('Demo Data administration', () => {
  it.each([true, false])('saves enabled=%s through the existing source API', async enabled => {
    vi.mocked(updateExternalAPI).mockResolvedValue({ ...demo, enabled });
    const saved = vi.fn();
    render(<MemoryRouter><AdminSourceForm selectedExternalAPI={{ ...demo, enabled: !enabled }} onSaved={saved} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Enable Demo Data' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith({ ...demo, enabled }));
    expect(updateExternalAPI).toHaveBeenCalledWith(4, { enabled });
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Base URL')).not.toBeInTheDocument();
    expect(screen.getByText(i18n.t('dataSources:demo.disableHelp'))).toBeInTheDocument();
    expect(screen.queryByText('Configuration required')).not.toBeInTheDocument();
  });
  it.each(['en', 'es'])('shows Demo and real-provider credential states in %s', async lang => {
    await act(() => i18n.changeLanguage(lang));
    vi.mocked(listExternalAPIs).mockResolvedValue([demo, ...['PurpleAir', 'OpenAQ', 'AirGradient'].map((name, id) => ({ external_api_id: id + 10, name, enabled: true, requires_credential: true, has_api_key: id === 0, runnable_reason: id === 0 ? 'ready' as const : 'configuration_required' as const }))]);
    render(<MemoryRouter><AdminSourcesList /></MemoryRouter>);
    const row = (await screen.findByRole('link', { name: i18n.t('dataSources:adminSourcesList.accessibility.openDataSource', { name: 'Demo Data' }) })).closest('tr')!;
    expect(within(row).getByText(i18n.t('dataSources:credentialFree'))).toBeInTheDocument();
    expect(within(row).getByText(i18n.t('dataSources:demo.disableHelp'))).toBeInTheDocument();
    expect(within(row).queryByText(i18n.t('admin:workspace.credentialMissing'))).not.toBeInTheDocument();
    expect(screen.getAllByText(i18n.t('admin:workspace.credentialMissing'))).toHaveLength(2);
    expect(screen.getByText(i18n.t('admin:workspace.credentialStored'))).toBeInTheDocument();
  });
});

