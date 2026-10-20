import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AdminDevicesList from '../AdminDevicesList';
import * as api from '../api';
import i18n from '../i18n';

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
    listDevicesAdmin: vi.fn().mockResolvedValue([]),
    listExternalAPIs: vi.fn().mockResolvedValue([
      { external_api_id: 1, name: 'alpha source', enabled: true },
      { external_api_id: 2, name: 'beta source', enabled: true },
    ]),
  };
});

describe('AdminDevicesList', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    sessionStorage.clear();
    await i18n.changeLanguage('en');
  });

  it('filters by the Other data source token without prompting for a name', async () => {
    const listDevicesAdminMock = vi.mocked(api.listDevicesAdmin);

    render(
      <MemoryRouter>
        <AdminDevicesList />
      </MemoryRouter>
    );

    const dataSourceSelect = await screen.findByLabelText('Data Source');
    fireEvent.change(dataSourceSelect, { target: { value: '__other__' } });
    expect(screen.queryByPlaceholderText('Enter data source name…')).not.toBeInTheDocument();

    await waitFor(() => {
      expect(listDevicesAdminMock).toHaveBeenLastCalledWith(
        expect.objectContaining({
          network: '__other__',
        })
      );
    });
  });

  it('renders localized operational statuses and measurement observation times', async () => {
    const lastSeenAt = '2026-08-26T18:30:00+00:00';
    vi.mocked(api.listDevicesAdmin).mockResolvedValue([
      {
        device_id: 10,
        name: 'Measured Device',
        status: 'active',
        last_seen_at: lastSeenAt,
      },
      {
        device_id: 11,
        name: 'Never Measured Device',
        status: 'unknown',
        last_seen_at: null,
      },
    ]);

    render(
      <MemoryRouter>
        <AdminDevicesList />
      </MemoryRouter>
    );

    const measuredRow = (await screen.findByRole('link', { name: 'Open Measured Device view' })).closest('tr');
    const unknownRow = screen.getByRole('link', { name: 'Open Never Measured Device view' }).closest('tr');
    expect(measuredRow).not.toBeNull();
    expect(unknownRow).not.toBeNull();
    expect(within(measuredRow!).getByText('Active')).toHaveClass('status-badge', 'active');
    expect(within(measuredRow!).getByText('8/26/2026, 06:30:00 PM UTC')).toBeInTheDocument();
    expect(within(unknownRow!).getByText('Unknown')).toHaveClass('status-badge', 'status-unknown');
    expect(within(unknownRow!).getAllByText('—').length).toBeGreaterThan(0);
  });

  it('only offers supported status filters and no misleading Type control', async () => {
    const listDevicesAdminMock = vi.mocked(api.listDevicesAdmin);

    render(
      <MemoryRouter>
        <AdminDevicesList />
      </MemoryRouter>
    );

    const statusSelect = await screen.findByLabelText('Status');
    expect(within(statusSelect).getByRole('option', { name: 'Active' })).toBeInTheDocument();
    expect(within(statusSelect).getByRole('option', { name: 'Inactive' })).toBeInTheDocument();
    expect(within(statusSelect).getByRole('option', { name: 'Unknown' })).toBeInTheDocument();
    expect(within(statusSelect).queryByRole('option', { name: 'Error' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Type')).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText('e.g. PurpleAir')).not.toBeInTheDocument();

    fireEvent.change(statusSelect, { target: { value: 'inactive' } });
    await waitFor(() => {
      expect(listDevicesAdminMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'inactive' })
      );
    });
  });

  it('does not resend an unsupported status from an old URL', async () => {
    const listDevicesAdminMock = vi.mocked(api.listDevicesAdmin);

    render(
      <MemoryRouter initialEntries={['/?status=error']}>
        <AdminDevicesList />
      </MemoryRouter>
    );

    expect(await screen.findByLabelText('Status')).toHaveValue('');
    await waitFor(() => {
      expect(listDevicesAdminMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: undefined })
      );
    });
  });

  it('sorts status and last seen values with deterministic missing timestamps', async () => {
    vi.mocked(api.listDevicesAdmin).mockResolvedValue([
      { device_id: 3, name: 'Never Measured', status: 'unknown', last_seen_at: null },
      { device_id: 2, name: 'Newest', status: 'active', last_seen_at: '2026-08-26T12:00:00Z' },
      { device_id: 1, name: 'Oldest', status: 'inactive', last_seen_at: '2026-08-20T12:00:00Z' },
    ]);

    render(
      <MemoryRouter>
        <AdminDevicesList />
      </MemoryRouter>
    );
    await screen.findByRole('link', { name: 'Open Never Measured view' });

    fireEvent.click(screen.getByRole('button', { name: /Last seen/ }));
    let bodyRows = screen.getAllByRole('row').slice(1);
    expect(within(bodyRows[0]).getByRole('link', { name: 'Open Never Measured view' })).toBeInTheDocument();
    expect(within(bodyRows[1]).getByRole('link', { name: 'Open Oldest view' })).toBeInTheDocument();
    expect(within(bodyRows[2]).getByRole('link', { name: 'Open Newest view' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^Status/ }));
    bodyRows = screen.getAllByRole('row').slice(1);
    expect(within(bodyRows[0]).getByRole('link', { name: 'Open Newest view' })).toBeInTheDocument();
    expect(within(bodyRows[1]).getByRole('link', { name: 'Open Oldest view' })).toBeInTheDocument();
    expect(within(bodyRows[2]).getByRole('link', { name: 'Open Never Measured view' })).toBeInTheDocument();
  });

  it('renders Spanish status labels', async () => {
    await i18n.changeLanguage('es');
    vi.mocked(api.listDevicesAdmin).mockResolvedValue([
      { device_id: 20, name: 'Activo', status: 'active', last_seen_at: '2026-08-26T12:00:00Z' },
      { device_id: 21, name: 'Inactivo', status: 'inactive', last_seen_at: '2026-08-20T12:00:00Z' },
      { device_id: 22, name: 'Sin datos', status: 'unknown', last_seen_at: null },
    ]);

    render(
      <MemoryRouter>
        <AdminDevicesList />
      </MemoryRouter>
    );

    expect(await screen.findByText('Activo', { selector: '.status-badge' })).toBeInTheDocument();
    expect(screen.getByText('Inactivo', { selector: '.status-badge' })).toBeInTheDocument();
    expect(screen.getByText('Desconocido', { selector: '.status-badge' })).toBeInTheDocument();
  });
});
