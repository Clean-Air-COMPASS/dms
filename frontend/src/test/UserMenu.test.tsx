import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import UserMenu from '../components/UserMenu';
import { useAuth, type AuthContextValue } from '../auth';

vi.mock('../auth', () => ({
  useAuth: vi.fn(),
}));

const email = 'jdevinter@domain.com';
const logout = vi.fn().mockResolvedValue(undefined);
const setPreferredLanguageCode = vi.fn().mockResolvedValue(undefined);

function createAuthValue(): AuthContextValue {
  return {
    isAuthenticated: true,
    user: {
      user_id: 'user-1',
      first_name: null, last_name: null, display_name: email, passkey_count: 0,
      email,
      org_id: 'org-1',
      roles: ['admin'],
      scopes: ['users:write'],
      preferred_language_code: null,
      system_default_language_code: 'en',
    },
    accessToken: 'test-token',
    isLoading: false,
    login: vi.fn().mockResolvedValue({ success: true }),
    logout,
    setPreferredLanguageCode,
    hasScope: vi.fn().mockReturnValue(true),
    hasAnyScope: vi.fn().mockReturnValue(true),
    hasAllScopes: vi.fn().mockReturnValue(true),
  };
}

function renderUserMenu(initialPath = '/map') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/map" element={<UserMenu />} />
        <Route path="/admin" element={<div>Admin home</div>} />
        <Route path="/account" element={<div>Account page</div>} />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('UserMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAuth).mockReturnValue(createAuthValue());
  });

  it('derives the compact avatar from the first character of the email local part', () => {
    renderUserMenu();

    expect(screen.getByRole('button', { name: `Account menu for ${email}` })).toHaveTextContent('J');
    expect(screen.queryByText(email)).not.toBeInTheDocument();
  });

  it('shows the full email and My Account navigation inside the opened account menu', async () => {
    const user = userEvent.setup();
    renderUserMenu();

    await user.click(screen.getByRole('button', { name: /Account menu/ }));

    expect(screen.getByRole('region')).toBeInTheDocument();
    expect(screen.getByText(email)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'My Account' })).toHaveAttribute('href', '/account');
    expect(screen.getByRole('button', { name: 'Sign Out' })).toBeInTheDocument();
  });

  it('routes My Account from the account menu to /account and keeps logout behavior intact', async () => {
    const user = userEvent.setup();
    renderUserMenu();

    await user.click(screen.getByRole('button', { name: /Account menu/ }));
    await user.click(screen.getByRole('link', { name: 'My Account' }));
    expect(screen.getByText('Account page')).toBeInTheDocument();

    renderUserMenu();
    await user.click(screen.getByRole('button', { name: /Account menu/ }));
    await user.click(screen.getByRole('button', { name: 'Sign Out' }));

    await waitFor(() => expect(logout).toHaveBeenCalledOnce());
    expect(screen.getByText('Login page')).toBeInTheDocument();
  });

  it('shows the backend display name with secondary email', async () => {
    const auth = createAuthValue();
    auth.user!.display_name = 'Jennifer DeWinter';
    vi.mocked(useAuth).mockReturnValue(auth);
    renderUserMenu();
    await userEvent.click(screen.getByRole('button', { name: 'Account menu for Jennifer DeWinter' }));
    expect(screen.getByText('Jennifer DeWinter')).toBeVisible();
    expect(screen.getByText(email)).toBeVisible();
  });

  it('returns focus to the avatar when Escape closes the menu', async () => {
    const user = userEvent.setup();
    renderUserMenu();

    const trigger = screen.getByRole('button', { name: /Account menu/ });
    await user.click(trigger);
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('persists Spanish and clears the override when system default is selected', async () => {
    const user = userEvent.setup();
    renderUserMenu();

    await user.click(screen.getByRole('button', { name: /Account menu/ }));
    const selector = screen.getByRole('combobox', { name: 'Language' });
    await user.selectOptions(selector, 'es');
    expect(setPreferredLanguageCode).toHaveBeenCalledWith('es');

    await user.selectOptions(selector, 'system');
    expect(setPreferredLanguageCode).toHaveBeenCalledWith(null);
  });
  it('orders Admin directly after My Account and navigates to the canonical home', async () => {
    renderUserMenu();
    await userEvent.click(screen.getByRole('button', { name: /Account menu/ }));
    const items = document.querySelector('.user-menu__items')!;
    expect(Array.from(items.children).map(item => item.textContent)).toEqual([
      'My Account', 'Admin', expect.stringContaining('Language'), 'Sign Out',
    ]);
    await userEvent.click(screen.getByRole('link', { name: 'Admin' }));
    expect(screen.getByText('Admin home')).toBeVisible();
  });

  it('uses the current user permission and updates an open menu after session changes', async () => {
    const auth = createAuthValue();
    auth.user = { ...auth.user!, roles: ['viewer'], scopes: [] };
    vi.mocked(useAuth).mockReturnValue(auth);
    const view = render(<MemoryRouter><UserMenu /></MemoryRouter>);
    await userEvent.click(screen.getByRole('button', { name: /Account menu/ }));
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument();
    vi.mocked(useAuth).mockReturnValue(createAuthValue());
    view.rerender(<MemoryRouter><UserMenu /></MemoryRouter>);
    expect(within(screen.getByRole('region')).getByRole('link', { name: 'Admin' })).toHaveAttribute('href', '/admin');
    vi.mocked(useAuth).mockReturnValue(auth);
    view.rerender(<MemoryRouter><UserMenu /></MemoryRouter>);
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument();
  });

});
