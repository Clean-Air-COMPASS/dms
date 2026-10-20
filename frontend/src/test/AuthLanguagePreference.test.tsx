import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth, type AuthUser } from '../auth';
import i18n from '../i18n';

const authClientMocks = vi.hoisted(() => ({
  updateCurrentUserPreferences: vi.fn(),
  refreshAccessToken: vi.fn(),
  fetchCurrentUser: vi.fn(),
}));

vi.mock('../auth/authClient', () => ({
  setAccessToken: vi.fn(),
  setAuthStateChangeCallback: vi.fn(),
  refreshAccessToken: authClientMocks.refreshAccessToken,
  fetchCurrentUser: authClientMocks.fetchCurrentUser,
  login: vi.fn(),
  logout: vi.fn(),
  updateCurrentUserPreferences: authClientMocks.updateCurrentUserPreferences,
}));

const spanishUser: AuthUser = {
  user_id: 'user-1',
  first_name: null, last_name: null, display_name: 'user@example.com', passkey_count: 0,
  email: 'user@example.com',
  org_id: 'org-1',
  roles: [],
  scopes: [],
  preferred_language_code: 'es',
  system_default_language_code: 'en',
};

function PreferenceHarness() {
  const { isLoading, setPreferredLanguageCode } = useAuth();
  return (
    <div>
      <span>{isLoading ? 'initializing' : 'ready'}</span>
      <button
        type="button"
        onClick={() => {
          void setPreferredLanguageCode('es').catch(() => undefined);
        }}
      >
        choose Spanish
      </button>
    </div>
  );
}

describe('authenticated language preference persistence', () => {
  beforeEach(async () => {
    authClientMocks.updateCurrentUserPreferences.mockReset();
    authClientMocks.refreshAccessToken.mockReset().mockResolvedValue(null);
    authClientMocks.fetchCurrentUser.mockReset().mockResolvedValue(null);
    window.localStorage.clear();
    await i18n.changeLanguage('en');
  });

  afterEach(async () => {
    window.localStorage.clear();
    await i18n.changeLanguage('en');
  });

  it('applies the saved authenticated language before completing initial auth bootstrap', async () => {
    window.localStorage.setItem('compassaq.language', 'en');
    authClientMocks.refreshAccessToken.mockResolvedValue('session-token');
    authClientMocks.fetchCurrentUser.mockResolvedValue(spanishUser);

    render(
      <AuthProvider>
        <PreferenceHarness />
      </AuthProvider>,
    );

    await screen.findByText('ready');

    expect(i18n.resolvedLanguage).toBe('es');
    expect(document.documentElement.lang).toBe('es');
    expect(window.localStorage.getItem('compassaq.language')).toBe('es');
  });

  it('applies Spanish only after the user override is saved', async () => {
    authClientMocks.updateCurrentUserPreferences.mockResolvedValue(spanishUser);
    render(
      <AuthProvider>
        <PreferenceHarness />
      </AuthProvider>,
    );
    await screen.findByText('ready');

    await userEvent.click(screen.getByRole('button', { name: 'choose Spanish' }));

    await waitFor(() => expect(i18n.resolvedLanguage).toBe('es'));
    expect(authClientMocks.updateCurrentUserPreferences).toHaveBeenCalledWith('es');
  });

  it('keeps the prior language when saving the override fails', async () => {
    authClientMocks.updateCurrentUserPreferences.mockRejectedValue(new Error('save failed'));
    render(
      <AuthProvider>
        <PreferenceHarness />
      </AuthProvider>,
    );
    await screen.findByText('ready');

    await userEvent.click(screen.getByRole('button', { name: 'choose Spanish' }));

    await waitFor(() => expect(authClientMocks.updateCurrentUserPreferences).toHaveBeenCalledWith('es'));
    expect(i18n.resolvedLanguage).toBe('en');
    expect(document.documentElement.lang).toBe('en');
  });
});
