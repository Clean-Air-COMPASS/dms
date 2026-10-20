import { afterEach, describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminSystemPreferences from '../AdminSystemPreferences';
import i18n from '../i18n';

vi.mock('../buildIdentity', async () => ({
  ...await vi.importActual<typeof import('../buildIdentity')>('../buildIdentity'),
  getBackendVersion: vi.fn().mockResolvedValue({ application_version: '0.1.0', backend: { commit_sha: null, build_time_utc: null }, environment: null }),
}));

const apiMocks = vi.hoisted(() => ({
  getSystemPreferencesMock: vi.fn(),
  updateSystemPreferencesMock: vi.fn(),
}));

vi.mock('../auth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { email: 'admin@example.com', scopes: ['users:write'], preferred_language_code: null },
    logout: vi.fn(),
    isLoading: false,
  }),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getSystemPreferences: apiMocks.getSystemPreferencesMock,
    updateSystemPreferences: apiMocks.updateSystemPreferencesMock,
  };
});

function getSaveButton(location: 'top' | 'bottom', name = 'Save changes') {
  const selector = location === 'top' ? '.admin-page-actions' : '.preferences-save-actions';
  const container = document.querySelector(selector);
  if (!(container instanceof HTMLElement)) {
    throw new Error(`Could not find the ${location} System Preferences save action.`);
  }
  return within(container).getByRole('button', { name });
}

describe('AdminSystemPreferences', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
    apiMocks.getSystemPreferencesMock.mockReset();
    apiMocks.updateSystemPreferencesMock.mockReset();
  });

  it('loads the current Geoapify key and saves updates', async () => {
    apiMocks.getSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: 'old-key',
      system_timezone: 'America/Los_Angeles',
      updated_at: '2026-04-20T00:00:00+00:00',
      last_updated_by_email: 'previous-admin@example.com',
      last_updated_by_display_name: 'Jennifer DeWinter',
    });
    apiMocks.updateSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: 'new-key',
      system_timezone: 'America/Los_Angeles',
      updated_at: '2026-04-20T01:00:00+00:00',
      last_updated_by_email: 'admin@example.com',
    });

    render(
      <MemoryRouter>
        <AdminSystemPreferences />
      </MemoryRouter>
    );

    const input = await screen.findByLabelText('Geoapify API Key');
    expect(input).toHaveValue('old-key');
    expect(screen.getByText(/by Jennifer DeWinter/)).toBeVisible();
    expect(screen.getAllByRole('button', { name: 'Save changes' })).toHaveLength(2);
    expect(getSaveButton('top')).toBeInTheDocument();
    expect(getSaveButton('bottom')).toBeInTheDocument();

    await userEvent.clear(input);
    await userEvent.type(input, 'new-key');
    await userEvent.click(getSaveButton('top'));

    expect(apiMocks.updateSystemPreferencesMock).toHaveBeenCalledWith({
      geoapify_api_key: 'new-key',
      default_language_code: 'en',
      system_timezone: 'America/Los_Angeles',
    });
    expect(await screen.findByText('System preferences updated.')).toBeInTheDocument();
    expect(screen.getAllByText('System preferences updated.', { exact: true })).toHaveLength(1);
    expect(screen.getByText(/by admin@example.com/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Geoapify' })).toHaveAttribute('href', 'https://www.geoapify.com/');
  });

  it('shows a no-change message without saving', async () => {
    apiMocks.getSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: 'same-key',
      updated_at: '2026-04-20T00:00:00+00:00',
    });

    render(
      <MemoryRouter>
        <AdminSystemPreferences />
      </MemoryRouter>
    );

    await screen.findByDisplayValue('same-key');
    await userEvent.click(getSaveButton('bottom'));

    expect(apiMocks.updateSystemPreferencesMock).not.toHaveBeenCalled();
    expect(await screen.findByText('No changes to save.')).toBeInTheDocument();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('renders older preference records without updater metadata', async () => {
    apiMocks.getSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: 'legacy-key',
      updated_at: '2026-04-20T00:00:00+00:00',
    });

    render(
      <MemoryRouter>
        <AdminSystemPreferences />
      </MemoryRouter>
    );

    await screen.findByDisplayValue('legacy-key');
    expect(screen.getByText(/Last updated:/)).not.toHaveTextContent(' by ');
  });

  it('persists Spanish as the system default and applies it for a user without an override', async () => {
    apiMocks.getSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: '',
      default_language_code: 'en',
      system_timezone: 'UTC',
      updated_at: '2026-04-20T00:00:00+00:00',
    });
    apiMocks.updateSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: '',
      default_language_code: 'es',
      system_timezone: 'UTC',
      updated_at: '2026-04-20T01:00:00+00:00',
    });

    render(
      <MemoryRouter>
        <AdminSystemPreferences />
      </MemoryRouter>
    );

    const selector = await screen.findByRole('combobox', { name: 'Language' });
    expect(screen.getAllByRole('button', { name: 'Save changes' })).toHaveLength(2);
    await userEvent.selectOptions(selector, 'es');
    await userEvent.click(getSaveButton('top'));

    expect(apiMocks.updateSystemPreferencesMock).toHaveBeenCalledWith({
      geoapify_api_key: '',
      default_language_code: 'es',
      system_timezone: 'UTC',
    });
    expect(i18n.resolvedLanguage).toBe('es');
    expect(document.documentElement.lang).toBe('es');
    expect(screen.getAllByRole('button', { name: 'Guardar cambios' })).toHaveLength(2);
    expect(getSaveButton('bottom', 'Guardar cambios')).toBeInTheDocument();
  });

  it('keeps both save entry points synchronized while saving and after success', async () => {
    const savedPreferences = {
      geoapify_api_key: '',
      default_language_code: 'en' as const,
      system_timezone: 'Asia/Manila',
      updated_at: '2026-04-20T01:00:00+00:00',
    };
    let resolveSave: ((value: typeof savedPreferences) => void) | undefined;
    apiMocks.getSystemPreferencesMock.mockResolvedValue({
      ...savedPreferences,
      system_timezone: 'UTC',
      updated_at: '2026-04-20T00:00:00+00:00',
    });
    apiMocks.updateSystemPreferencesMock.mockImplementation(
      () => new Promise((resolve) => {
        resolveSave = resolve;
      }),
    );

    render(
      <MemoryRouter>
        <AdminSystemPreferences />
      </MemoryRouter>,
    );

    const timezone = await screen.findByRole('combobox', { name: 'System timezone' });
    const topSave = getSaveButton('top');
    const bottomSave = getSaveButton('bottom');
    await userEvent.selectOptions(timezone, 'Asia/Manila');
    expect(topSave).toBeEnabled();
    expect(bottomSave).toBeEnabled();

    await userEvent.click(bottomSave);
    expect(topSave).toBeDisabled();
    expect(bottomSave).toBeDisabled();
    expect(screen.getAllByRole('button', { name: 'Saving...' })).toHaveLength(2);

    resolveSave?.(savedPreferences);
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Save changes' })).toHaveLength(2));
    expect(screen.getAllByText('System preferences updated.', { exact: true })).toHaveLength(1);
    expect(topSave).toBeEnabled();
    expect(bottomSave).toBeEnabled();
  });

  it('uses the same save behavior from the top and bottom actions', async () => {
    const initialPreferences = {
      geoapify_api_key: '',
      default_language_code: 'en' as const,
      system_timezone: 'UTC',
      updated_at: '2026-04-20T00:00:00+00:00',
    };
    apiMocks.getSystemPreferencesMock.mockResolvedValue(initialPreferences);
    apiMocks.updateSystemPreferencesMock
      .mockResolvedValueOnce({ ...initialPreferences, system_timezone: 'Asia/Manila' })
      .mockResolvedValueOnce({ ...initialPreferences, geoapify_api_key: 'updated-key' });

    render(
      <MemoryRouter>
        <AdminSystemPreferences />
      </MemoryRouter>,
    );

    const timezone = await screen.findByRole('combobox', { name: 'System timezone' });
    await userEvent.selectOptions(timezone, 'Asia/Manila');
    await userEvent.click(getSaveButton('bottom'));
    await waitFor(() => expect(apiMocks.updateSystemPreferencesMock).toHaveBeenCalledTimes(1));

    const input = screen.getByLabelText('Geoapify API Key');
    await userEvent.type(input, 'updated-key');
    await userEvent.click(getSaveButton('top'));
    await waitFor(() => expect(apiMocks.updateSystemPreferencesMock).toHaveBeenCalledTimes(2));

    expect(apiMocks.updateSystemPreferencesMock).toHaveBeenNthCalledWith(1, {
      geoapify_api_key: '',
      default_language_code: 'en',
      system_timezone: 'Asia/Manila',
    });
    expect(apiMocks.updateSystemPreferencesMock).toHaveBeenNthCalledWith(2, {
      geoapify_api_key: 'updated-key',
      default_language_code: 'en',
      system_timezone: 'Asia/Manila',
    });
  });

  it('preserves edits and synchronized dirty state when saving fails', async () => {
    apiMocks.getSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: '',
      default_language_code: 'en',
      system_timezone: 'UTC',
      updated_at: '2026-04-20T00:00:00+00:00',
    });
    apiMocks.updateSystemPreferencesMock.mockRejectedValue(new Error('Could not save preferences'));

    render(
      <MemoryRouter>
        <AdminSystemPreferences />
      </MemoryRouter>,
    );

    const timezone = await screen.findByRole('combobox', { name: 'System timezone' });
    await userEvent.selectOptions(timezone, 'Asia/Manila');
    await userEvent.click(getSaveButton('bottom'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save preferences');
    expect(timezone).toHaveValue('Asia/Manila');
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
    expect(getSaveButton('top')).toBeEnabled();
    expect(getSaveButton('bottom')).toBeEnabled();
  });

  it('places the bottom save action next in keyboard order after the final editable field', async () => {
    apiMocks.getSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: '',
      default_language_code: 'en',
      system_timezone: 'UTC',
      updated_at: '2026-04-20T00:00:00+00:00',
    });

    render(
      <MemoryRouter>
        <AdminSystemPreferences />
      </MemoryRouter>,
    );

    const timezone = await screen.findByRole('combobox', { name: 'System timezone' });
    const bottomSave = getSaveButton('bottom');
    timezone.focus();
    await userEvent.tab();
    expect(bottomSave).toHaveFocus();
  });

  it('shows and saves the system timezone with the priority choices available', async () => {
    apiMocks.getSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: '',
      default_language_code: 'en',
      system_timezone: 'UTC',
      updated_at: '2026-04-20T00:00:00+00:00',
    });
    apiMocks.updateSystemPreferencesMock.mockResolvedValue({
      geoapify_api_key: '',
      default_language_code: 'en',
      system_timezone: 'Asia/Manila',
      updated_at: '2026-04-20T01:00:00+00:00',
    });

    render(
      <MemoryRouter>
        <AdminSystemPreferences />
      </MemoryRouter>,
    );

    const selector = await screen.findByRole('combobox', { name: 'System timezone' });
    expect(within(selector).getByRole('option', { name: /Asia\/Manila/ })).toBeInTheDocument();
    expect(within(selector).getByRole('option', { name: /America\/Los_Angeles/ })).toBeInTheDocument();
    expect(within(selector).getByRole('option', { name: /America\/Sao_Paulo/ })).toBeInTheDocument();
    await userEvent.selectOptions(selector, 'Asia/Manila');
    await userEvent.click(getSaveButton('bottom'));

    expect(apiMocks.updateSystemPreferencesMock).toHaveBeenCalledWith({
      geoapify_api_key: '',
      default_language_code: 'en',
      system_timezone: 'Asia/Manila',
    });
  });
});
