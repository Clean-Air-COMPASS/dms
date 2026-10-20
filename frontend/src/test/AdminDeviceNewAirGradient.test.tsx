import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AdminDeviceNewAirGradient from '../AdminDeviceNewAirGradient';
import AdminDeviceNew from '../AdminDeviceNew';
import * as api from '../api';
import { ApiError } from '../apiError';
import i18n from '../i18n';

vi.mock('../auth', () => ({ useAuth: () => ({ isAuthenticated: false, user: null, logout: vi.fn(), isLoading: false }) }));
vi.mock('../api', async () => ({
  ...await vi.importActual<typeof import('../api')>('../api'),
  listExternalAPIs: vi.fn(), listAirGradientLocations: vi.fn(), addAirGradientLocation: vi.fn(),
}));
const location = { location_id: '70001', name: 'Library roof', latitude: 34.05, longitude: -118.24, timezone: 'America/Los_Angeles', existing_device_id: null };
const mount = () => render(<MemoryRouter initialEntries={['/add']}><Routes>
  <Route path="/add" element={<AdminDeviceNewAirGradient />} />
  <Route path="/admin/devices/123/edit" element={<h1>Device details destination</h1>} />
</Routes></MemoryRouter>);

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage('en');
  vi.mocked(api.listAirGradientLocations).mockResolvedValue({ locations: [location], automatic_imports_enabled: false });
  vi.mocked(api.addAirGradientLocation).mockResolvedValue({ device_id: 123, already_exists: false, measurements_imported: 2 });
});

describe('AirGradient add location', () => {
  it.each(['en', 'es'])('selects, previews and adds one location in %s', async language => {
    await i18n.changeLanguage(language);
    mount();
    expect(screen.getByRole('status')).toHaveTextContent(i18n.t('devices:airgradient.loading'));
    fireEvent.click(await screen.findByRole('radio', { name: /Library roof/ }));
    expect(screen.getByText(i18n.t('devices:airgradient.automaticOff'))).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: i18n.t('devices:airgradient.add') }));
    expect(await screen.findByText('Device details destination')).toBeVisible();
    expect(api.addAirGradientLocation).toHaveBeenCalledWith('70001');
  });

  it('shows an empty account and retries', async () => {
    vi.mocked(api.listAirGradientLocations).mockResolvedValueOnce({ locations: [], automatic_imports_enabled: false });
    mount();
    expect(await screen.findByText(i18n.t('devices:airgradient.empty'))).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('radio')).toBeVisible();
  });

  it('shows safe localized errors without provider diagnostics', async () => {
    vi.mocked(api.listAirGradientLocations).mockRejectedValue(new ApiError({ status: 422, errorCode: 'authentication_failed', diagnosticMessage: 'token=DO-NOT-SHOW' }));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t('devices:airgradient.errors.authentication_failed'));
    expect(screen.getByRole('link', { name: 'Configure Data Sources' })).toHaveAttribute('href', '/admin/sources');
    expect(document.body).not.toHaveTextContent('DO-NOT-SHOW');
  });

  it('links a known duplicate without creating it', async () => {
    vi.mocked(api.listAirGradientLocations).mockResolvedValue({ locations: [{ ...location, existing_device_id: 123 }], automatic_imports_enabled: true });
    mount();
    fireEvent.click(await screen.findByRole('radio'));
    expect(screen.getByText(i18n.t('devices:airgradient.duplicate'))).toBeVisible();
    expect(screen.getByRole('link', { name: 'View device' })).toHaveAttribute('href', '/admin/devices/123/edit');
    expect(api.addAirGradientLocation).not.toHaveBeenCalled();
  });

  it('handles a duplicate created since the list loaded', async () => {
    vi.mocked(api.addAirGradientLocation).mockResolvedValue({ device_id: 123, already_exists: true, measurements_imported: 0 });
    mount();
    fireEvent.click(await screen.findByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'Add location' }));
    expect(await screen.findByText(i18n.t('devices:airgradient.duplicate'))).toBeVisible();
  });

  it('keeps the selection after a creation error', async () => {
    vi.mocked(api.addAirGradientLocation).mockRejectedValue(new Error('unsafe provider message'));
    mount();
    fireEvent.click(await screen.findByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'Add location' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t('devices:airgradient.errors.operation_failed'));
    expect(screen.getByRole('radio')).toBeChecked();
    expect(document.body).not.toHaveTextContent('unsafe provider message');
  });

  it.each([true, false])('offers configured AirGradient or configuration guidance (%s)', async configured => {
    vi.mocked(api.listExternalAPIs).mockResolvedValue([{ provider_code: 'airgradient', has_api_key: configured } as api.ExternalAPI]);
    render(<MemoryRouter><AdminDeviceNew /></MemoryRouter>);
    await waitFor(() => expect(api.listExternalAPIs).toHaveBeenCalled());
    if (configured) expect(await screen.findByRole('button', { name: /AirGradient/ })).toBeVisible();
    else expect(await screen.findByRole('link', { name: 'Configure Data Sources' })).toBeVisible();
  });
});
