import SourceMonitoring from '../SourceMonitoring';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import AdminSourceForm from '../AdminSourceForm';

vi.mock('../auth', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    user: null,
    logout: vi.fn(),
    isLoading: false,
  }),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    createExternalAPI: vi.fn().mockResolvedValue({ external_api_id: 42, name: 'New Source' }),
    updateExternalAPI: vi.fn().mockResolvedValue({ external_api_id: 12, name: 'OpenAQ', enabled: true, params: {} }),
  };
});

describe('AdminSourceNew', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('alert', vi.fn());
  });

  it('creates a new data source from the source form create state', async () => {
    const api = await import('../api');
    const onCreated = vi.fn();

    render(
      <MemoryRouter>
        <AdminSourceForm
          selectedExternalAPI={{
            external_api_id: 0,
            name: 'New Source',
            enabled: true,
            params: {},
          }}
          onCreated={onCreated}
        />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText('https://api.example.com'), { target: { value: 'https://example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Source' }));

    await waitFor(() => {
      expect(vi.mocked(api.createExternalAPI)).toHaveBeenCalledWith({
        name: 'New Source',
        base_url: 'https://example.test',
        description: undefined,
        api_key: null,
        enabled: true,
        params: {},
      });
    });
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ external_api_id: 42, name: 'New Source' }));
  });

  it('explains PurpleAir measurement metadata in plain language', () => {
    render(
      <MemoryRouter>
        <AdminSourceForm
          selectedExternalAPI={{
            external_api_id: 12,
            name: 'PurpleAir',
            enabled: true,
            params: { max_lookback_hours: 24 },
          }}
        />
        <SourceMonitoring
          selectedExternalAPI={{
            external_api_id: 12,
            name: 'PurpleAir',
            enabled: true,
            params: { max_lookback_hours: 24 },
          }}
        />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: 'About this data source' })).toBeInTheDocument();
    expect(screen.getByText('Reporting interval')).toBeInTheDocument();
    expect(screen.getByText(/new measurement approximately every 2 minutes/i)).toBeInTheDocument();
    expect(screen.getByText('Measurement period')).toBeInTheDocument();
    expect(screen.getByText(/2-minute average/i)).toBeInTheDocument();
    expect(screen.getByText('Measurement time')).toBeInTheDocument();
    expect(screen.getByText(/time PurpleAir received the measurement/i)).toBeInTheDocument();
    expect(screen.getByText('PM measurement source')).toBeInTheDocument();
    expect(screen.getByText(/combined-channel particulate matter values/i)).toBeInTheDocument();
    expect(screen.getByText('Metadata management')).toBeInTheDocument();
    expect(screen.getByText(/Managed automatically.*PurpleAir importer/i)).toBeInTheDocument();
    expect(screen.getByText('Data qualification')).toBeInTheDocument();
    expect(screen.getByText(/air sensors.*not automatically regulatory instruments/i)).toBeInTheDocument();

    const configurationSection = screen.getByRole('region', {
      name: 'Data source configuration',
    });
    const aboutSection = screen.getByRole('region', {
      name: 'About this data source',
    });

    expect(configurationSection).toHaveClass('card', 'admin-source-configuration-card');
    expect(configurationSection).toContainElement(screen.getByPlaceholderText('https://api.example.com'));
    expect(configurationSection).toContainElement(screen.getByRole('button', { name: 'Save changes' }));
    expect(configurationSection).not.toContainElement(aboutSection);
    expect(configurationSection.compareDocumentPosition(aboutSection) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(aboutSection).toHaveClass('card', 'purpleair-source-about');
    expect(aboutSection.querySelector('dl')).toHaveClass('purpleair-source-about-grid');

    expect(screen.queryByText(/seconds/i)).not.toBeInTheDocument();
    expect(screen.queryByText('provider_received_at')).not.toBeInTheDocument();
    expect(screen.queryByText('provider_documented')).not.toBeInTheDocument();
    expect(screen.queryByText('purpleair_importer')).not.toBeInTheDocument();
  });

  it('keeps the Admin enabled control independent from stored credentials', async () => {
    const api = await import('../api');
    vi.stubGlobal('alert', vi.fn());

    render(
      <MemoryRouter>
        <AdminSourceForm
          selectedExternalAPI={{
            external_api_id: 12,
            name: 'OpenAQ',
            has_api_key: true,
            enabled: false,
            params: {},
          }}
        />
      </MemoryRouter>
    );

    const enabledControl = screen.getByRole('checkbox', { name: 'Enabled' });
    expect(enabledControl).not.toBeChecked();
    fireEvent.click(enabledControl);
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(vi.mocked(api.updateExternalAPI)).toHaveBeenCalledWith(
        12,
        expect.objectContaining({ enabled: true }),
      );
    });
    const payload = vi.mocked(api.updateExternalAPI).mock.calls[0][1];
    expect(payload).not.toHaveProperty('api_key');
    expect(screen.getByDisplayValue('••••••••••••••••')).toBeInTheDocument();
    expect(screen.getByText('Credential stored')).toBeInTheDocument();
    expect(screen.queryByText('Enabled — ready')).not.toBeInTheDocument();
  });

  it('replaces and removes a stored credential only through explicit actions', async () => {
    const api = await import('../api');
    vi.stubGlobal('alert', vi.fn());

    const { rerender } = render(
      <MemoryRouter>
        <AdminSourceForm
          selectedExternalAPI={{
            external_api_id: 12,
            provider_code: 'airgradient',
            name: 'AirGradient',
            has_api_key: true,
            enabled: true,
            params: {},
          }}
        />
        <SourceMonitoring
          selectedExternalAPI={{
            external_api_id: 12,
            provider_code: 'airgradient',
            name: 'AirGradient',
            has_api_key: true,
            enabled: true,
            params: {},
          }}
        />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: 'AirGradient data paths' })).toBeInTheDocument();
    expect(screen.getByText(/does not contact AirGradient/i)).toBeInTheDocument();
    expect(screen.getByText(/nearest verified active public location to Rio/i)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Also import my AirGradient account locations' })).toBeChecked();
    expect(screen.getByText('By default, CompassAQ imports only its built-in public AirGradient reference locations. Check this box to also import all locations associated with this API key.')).toBeInTheDocument();
    expect(screen.queryByText(/Turning this off later stops token-linked imports/i)).not.toBeInTheDocument();
    expect(screen.getByText(/license metadata.*CSV export/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Replace credential' }));
    fireEvent.change(screen.getByPlaceholderText('New API Key'), { target: { value: 'replacement-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => {
      expect(vi.mocked(api.updateExternalAPI)).toHaveBeenCalledWith(
        12,
        expect.objectContaining({ api_key: 'replacement-key', params: { import_authenticated_locations: true } }),
      );
    });

    vi.mocked(api.updateExternalAPI).mockClear();
    rerender(
      <MemoryRouter>
        <AdminSourceForm
          selectedExternalAPI={{
            external_api_id: 12,
            provider_code: 'airgradient',
            name: 'AirGradient',
            has_api_key: true,
            enabled: true,
            params: {},
          }}
        />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByRole('button', { name: 'Remove credential' }));
    expect(screen.getByText(/will be removed when you save/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => {
      expect(vi.mocked(api.updateExternalAPI)).toHaveBeenCalledWith(
        12,
        expect.objectContaining({ api_key: null }),
      );
    });
  });

  it('uses shared AirGradient copy and preserves the unchecked and checked choices', async () => {
    const api = await import('../api');

    render(
      <MemoryRouter>
        <AdminSourceForm
          selectedExternalAPI={{
            external_api_id: 12,
            provider_code: 'airgradient',
            name: 'AirGradient',
            has_api_key: false,
            enabled: false,
            params: { import_authenticated_locations: false },
          }}
        />
      </MemoryRouter>
    );

    const choice = screen.getByRole('checkbox', { name: 'Also import my AirGradient account locations' });
    expect(screen.getByPlaceholderText('AirGradient API key')).toBeInTheDocument();
    expect(choice).not.toBeChecked();
    expect(screen.getByText('By default, CompassAQ imports only its built-in public AirGradient reference locations. Check this box to also import all locations associated with this API key.')).toBeInTheDocument();
    expect(screen.queryByText(/Turning this off later stops token-linked imports/i)).not.toBeInTheDocument();

    fireEvent.click(choice);
    expect(choice).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => {
      expect(vi.mocked(api.updateExternalAPI)).toHaveBeenCalledWith(
        12,
        expect.objectContaining({ params: { import_authenticated_locations: true } }),
      );
    });
  });

  it('shows the latest importer activity from the source response', () => {
    render(
      <MemoryRouter>
        <SourceMonitoring
          selectedExternalAPI={{
            external_api_id: 12,
            provider_code: 'openaq',
            name: 'OpenAQ',
            has_api_key: true,
            enabled: true,
            params: {},
            latest_import: {
              job_run_id: 50,
              job_schedule_id: 5,
              task: 'openaq_import',
              status: 'success',
              started_at: '2026-08-16T14:00:00Z',
              summary: { devices_processed: 3, measurements_inserted: 284 },
            },
          }}
        />
      </MemoryRouter>
    );

    expect(screen.getByText('Last import')).toBeInTheDocument();
    expect(screen.getByText('284 inserted')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View Job Runs' })).toHaveAttribute('href', '/admin/events?task=openaq_import');
  });

  it('keeps the sync timer across renders and cancels it on replacement and unmount', async () => {
    const api = await import('../api');
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout');
    const { unmount } = render(
      <MemoryRouter>
        <AdminSourceForm
          selectedExternalAPI={{
            external_api_id: 12,
            provider_code: 'openaq',
            name: 'OpenAQ',
            has_api_key: true,
            enabled: true,
            params: {},
            can_delete: false,
          }}
        />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(vi.mocked(api.updateExternalAPI)).toHaveBeenCalledTimes(1));
    const clearCallsBeforeReplacement = clearTimeoutSpy.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(vi.mocked(api.updateExternalAPI)).toHaveBeenCalledTimes(2));
    expect(clearTimeoutSpy.mock.calls.length).toBeGreaterThan(clearCallsBeforeReplacement);

    const clearCallsBeforeUnmount = clearTimeoutSpy.mock.calls.length;
    unmount();
    expect(clearTimeoutSpy.mock.calls.length).toBeGreaterThan(clearCallsBeforeUnmount);
  });

  it('shows delete only when the backend contract allows it', () => {
    const { rerender } = render(
      <MemoryRouter>
        <AdminSourceForm
          selectedExternalAPI={{
            external_api_id: 12,
            provider_code: 'airgradient',
            name: 'AirGradient',
            enabled: false,
            params: {},
            is_builtin: true,
            can_delete: false,
          }}
        />
      </MemoryRouter>
    );
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <AdminSourceForm
          selectedExternalAPI={{
            external_api_id: 99,
            name: 'Custom Source',
            enabled: false,
            params: {},
            is_builtin: false,
            can_delete: true,
          }}
        />
      </MemoryRouter>
    );
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
  });
});

it('prevents duplicate source saves and preserves configuration after a failed submission', async () => {
  const api = await import('../api');
  vi.clearAllMocks();
  let reject!: (error: Error) => void;
  vi.mocked(api.updateExternalAPI).mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
  render(<MemoryRouter><AdminSourceForm selectedExternalAPI={{ external_api_id: 12, name: 'OpenAQ', enabled: false, has_api_key: true, params: {} }} /></MemoryRouter>);
  const description = screen.getByLabelText('Description');
  fireEvent.change(description, { target: { value: 'Updated provider description' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
  fireEvent.click(screen.getByRole('button', { name: 'Saving…' }));
  expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  expect(description).toBeDisabled();
  expect(api.updateExternalAPI).toHaveBeenCalledTimes(1);
  reject(new Error('fixture failure'));
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(description).toHaveValue('Updated provider description');
});
