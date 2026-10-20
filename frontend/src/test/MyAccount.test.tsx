import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { startAuthentication, startRegistration } from '@simplewebauthn/browser';
import { AuthProvider, RequireAuth, type AuthUser } from '../auth';
import { getAccessToken, setAccessToken } from '../auth/authClient';
import MyAccount from '../account/MyAccount';
import type { Passkey } from '../account/accountApi';
import i18n from '../i18n';

vi.mock('@simplewebauthn/browser', () => ({ startAuthentication: vi.fn(), startRegistration: vi.fn() }));

let currentUser: AuthUser;
let keys: Passkey[];
let authenticated: boolean;
let failure: { path: string; code: string; status: number } | null;
let calls: { path: string; method: string; body: Record<string, string>; headers: Headers }[];
const key: Passkey = { id: 'opaque-1', name: 'Windows laptop', created_at: '2026-09-07T10:00:00Z', last_used_at: null };

beforeEach(async () => {
  cleanup(); vi.clearAllMocks(); setAccessToken(null); await i18n.changeLanguage('en');
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  authenticated = true; failure = null; calls = []; keys = [];
  currentUser = { user_id: 'user-1', org_id: 'org-1', email: 'jennifer@example.com', first_name: 'Jennifer',
    last_name: 'DeWinter', display_name: 'Jennifer DeWinter', passkey_count: 0, roles: [], scopes: [],
    preferred_language_code: 'en', system_default_language_code: 'en' };
  vi.mocked(startAuthentication).mockResolvedValue({ id: 'assertion' } as Awaited<ReturnType<typeof startAuthentication>>);
  vi.mocked(startRegistration).mockResolvedValue({ id: 'new-key' } as Awaited<ReturnType<typeof startRegistration>>);
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^.*\/api/, '');
    const method = init?.method || 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    calls.push({ path, method, body, headers: new Headers(init?.headers) });
    const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
    if (failure?.path === path) return reply({ detail: { error_code: failure.code, message: 'SECRET diagnostics' } }, failure.status);
    if (path === '/auth/refresh') return reply({ access_token: 'original-session' }, authenticated ? 200 : 401);
    if (path === '/auth/me') {
      if (method === 'PATCH') {
        currentUser = { ...currentUser, first_name: body.first_name || null, last_name: body.last_name || null,
          display_name: [body.first_name, body.last_name].filter(Boolean).join(' ') || currentUser.email };
      }
      return reply(currentUser);
    }
    if (path === '/auth/me/preferences') { currentUser.preferred_language_code = body.preferred_language_code; return reply(currentUser); }
    if (path === '/auth/reauthenticate' || path === '/auth/passkeys/reauthenticate/verify') return reply({ reauthentication_token: 'one-use-proof' });
    if (path.endsWith('/options')) return reply({ challenge: 'challenge' });
    if (path === '/auth/me/email' || path === '/auth/me/password') {
      if (body.email) currentUser.email = body.email;
      return reply({ access_token: 'replacement-session' });
    }
    if (path === '/auth/passkeys') return reply({ passkeys: keys });
    if (path === '/auth/passkeys/register/verify') { keys = [...keys, { ...key, id: 'new-key', name: body.name }]; currentUser.passkey_count = keys.length; return reply({ success: true }); }
    if (method === 'DELETE') { keys = keys.filter((item) => !path.endsWith(item.id)); currentUser.passkey_count = keys.length; return reply({ success: true }); }
    return reply({ success: true });
  }));
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mount() {
  return render(<MemoryRouter initialEntries={['/account']}><AuthProvider><Routes>
    <Route path="/account" element={<RequireAuth><MyAccount /></RequireAuth>} />
    <Route path="/login" element={<h1>Sign in required</h1>} />
  </Routes></AuthProvider></MemoryRouter>);
}

async function ready() { mount(); await screen.findByRole('heading', { name: 'My Account' }); await waitFor(() => expect(screen.queryByText('Loading passkeys…')).not.toBeInTheDocument()); }
async function open(label: string) { fireEvent.click(screen.getByRole('button', { name: label })); return within(screen.getByRole('dialog')); }
async function passwordProof(dialog: ReturnType<typeof within>, submit: string) {
  fireEvent.change(dialog.getByLabelText('Current password'), { target: { value: 'CurrentPassword1!' } });
  fireEvent.click(dialog.getByRole('button', { name: submit }));
}

describe('My Account and live AuthContext integration', () => {
  it('allows a signed-in user without admin scopes and loads names', async () => {
    await ready(); expect(screen.getByLabelText('First name')).toHaveValue('Jennifer');
    expect(screen.getByLabelText('Last name')).toHaveValue('DeWinter');
  });
  it('redirects signed-out visitors to login', async () => {
    authenticated = false; mount(); expect(await screen.findByRole('heading', { name: 'Sign in required' })).toBeVisible();
    expect(calls.some((call) => call.path === '/auth/passkeys')).toBe(false);
  });
  it('saves Unicode names and immediately updates page and menu identity', async () => {
    await ready(); fireEvent.change(screen.getByLabelText('First name'), { target: { value: 'María' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(await screen.findByText('Saved')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Account menu for María DeWinter' })).toBeVisible();
  });
  it('clears optional names and consumes the backend email fallback', async () => {
    await ready(); fireEvent.change(screen.getByLabelText('First name'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Last name'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' })); await screen.findByText('Saved');
    expect(screen.getByRole('button', { name: 'Account menu for jennifer@example.com' })).toBeVisible();
  });
  it('loads and saves language through existing preferences and updates auth immediately', async () => {
    await ready(); expect(screen.getByLabelText('Language')).toHaveValue('en');
    await userEvent.selectOptions(screen.getByLabelText('Language'), 'es');
    expect(await screen.findByRole('heading', { name: 'Mi cuenta' })).toBeVisible();
    expect(document.documentElement.lang).toBe('es');
    expect(currentUser.preferred_language_code).toBe('es');
  });
  it('keeps language and shows an error when preference save fails', async () => {
    await ready(); failure = { path: '/auth/me/preferences', code: 'unknown', status: 500 };
    await userEvent.selectOptions(screen.getByLabelText('Language'), 'es');
    expect(await screen.findByRole('alert')).toHaveTextContent('The change could not be completed');
    expect(screen.getByLabelText('Language')).toHaveValue('en');
  });
  it('verifies password before email change, replaces the token and refreshes current user', async () => {
    await ready(); const dialog = await open('Change email');
    fireEvent.change(dialog.getByLabelText('New email address'), { target: { value: 'new@example.com' } });
    expect(calls.some((call) => call.path === '/auth/me/email')).toBe(false);
    await passwordProof(dialog, 'Verify and change email');
    await screen.findByText('Email updated. You are still signed in.');
    expect(getAccessToken()).toBe('replacement-session'); expect(screen.getByText('new@example.com')).toBeVisible();
    const verifyIndex = calls.findIndex((call) => call.path === '/auth/reauthenticate');
    const changeIndex = calls.findIndex((call) => call.path === '/auth/me/email');
    expect(verifyIndex).toBeLessThan(changeIndex); expect(calls[changeIndex].body.reauthentication_token).toBe('one-use-proof');
    expect(calls.slice(changeIndex + 1).find((call) => call.path === '/auth/me')?.headers.get('Authorization')).toBe('Bearer replacement-session');
  });
  it('lets users choose passkey verification and never submits a password in that flow', async () => {
    keys = [key]; await ready(); const dialog = await open('Change email');
    expect(dialog.getByLabelText('Verify with password')).toBeChecked();
    fireEvent.change(dialog.getByLabelText('New email address'), { target: { value: 'new@example.com' } });
    fireEvent.click(dialog.getByLabelText('Verify with passkey')); fireEvent.click(dialog.getByRole('button', { name: 'Verify and change email' }));
    await screen.findByText('Email updated. You are still signed in.');
    expect(startAuthentication).toHaveBeenCalled(); expect(calls.some((call) => call.path === '/auth/reauthenticate')).toBe(false);
  });
  it.each(['email_already_in_use', 'incorrect_current_password', 'reauthentication_required'] as const)('translates %s without exposing diagnostics', async (code) => {
    await ready(); failure = { path: code === 'incorrect_current_password' ? '/auth/reauthenticate' : '/auth/me/email', code, status: 403 };
    const dialog = await open('Change email'); fireEvent.change(dialog.getByLabelText('New email address'), { target: { value: 'new@example.com' } });
    await passwordProof(dialog, 'Verify and change email');
    expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t(`auth:account.errors.${code}`));
    expect(document.body.textContent).not.toContain('SECRET');
  });
  it('validates confirmation before verification and preserves password strength UI', async () => {
    await ready(); const dialog = await open('Change password');
    fireEvent.change(dialog.getByLabelText('New password'), { target: { value: 'LongNewPassword1!' } });
    fireEvent.change(dialog.getByLabelText('Confirm password'), { target: { value: 'different' } });
    expect(dialog.getByRole('progressbar')).toBeVisible(); await passwordProof(dialog, 'Verify and change password');
    expect(await screen.findByRole('alert')).toHaveTextContent('The new passwords do not match');
    expect(calls.some((call) => call.path === '/auth/reauthenticate')).toBe(false);
  });
  it('verifies and changes password, accepts replacement session, and clears fields', async () => {
    await ready(); const dialog = await open('Change password');
    for (const label of ['New password', 'Confirm password']) fireEvent.change(dialog.getByLabelText(label), { target: { value: 'LongNewPassword1!' } });
    await passwordProof(dialog, 'Verify and change password'); await screen.findByText('Password updated. Your passkeys are unchanged.');
    expect(getAccessToken()).toBe('replacement-session');
    const reopened = await open('Change password'); expect(reopened.getByLabelText('New password')).toHaveValue('');
  });
  it.each([0, 1, 3])('renders %i passkeys with friendly fallback and dates', async (count) => {
    keys = Array.from({ length: count }, (_, index) => ({ ...key, id: String(index), name: index ? null : key.name }));
    await ready(); expect(screen.queryAllByRole('button', { name: /Remove “/ })).toHaveLength(count);
    if (!count) expect(screen.getByText('You have no passkeys yet.')).toBeVisible();
    if (count > 1) expect(screen.getAllByText('Unnamed passkey')).toHaveLength(count - 1);
  });
  it('adds another named passkey after verification and retains existing keys', async () => {
    keys = [key]; await ready(); const dialog = await open('Add passkey');
    fireEvent.change(dialog.getByLabelText('Passkey name (optional)'), { target: { value: 'Phone' } });
    await passwordProof(dialog, 'Verify and add passkey'); await screen.findByText('Passkey added.');
    expect(screen.getByText('Phone')).toBeVisible(); expect(screen.getByText('Windows laptop')).toBeVisible();
    expect(startRegistration).toHaveBeenCalled();
    expect(calls.find((call) => call.path === '/auth/passkeys/register/options')?.body.reauthentication_token).toBe('one-use-proof');
  });
  it('confirms removal, verifies identity and sends proof in the removal header', async () => {
    keys = [key]; await ready(); const dialog = await open('Remove “Windows laptop”?');
    expect(dialog.getByText(/You will no longer be able/)).toBeVisible();
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false);
    await passwordProof(dialog, 'Verify and remove passkey'); await screen.findByText('Passkey removed.');
    expect(calls.find((call) => call.method === 'DELETE')?.headers.get('X-Reauthentication-Token')).toBe('one-use-proof');
    expect(screen.getByText('You have no passkeys yet.')).toBeVisible();
  });
  it('shows backend last authentication method protection and keeps the key', async () => {
    keys = [key]; await ready(); failure = { path: '/auth/passkeys/opaque-1', code: 'last_authentication_method', status: 409 };
    const dialog = await open('Remove “Windows laptop”?'); await passwordProof(dialog, 'Verify and remove passkey');
    expect(await screen.findByRole('alert')).toHaveTextContent('You need another way to sign in');
    expect(screen.getByText('Windows laptop')).toBeVisible();
  });
  it('contains profile save errors and retains entered names', async () => {
    await ready(); failure = { path: '/auth/me', code: 'invalid_name_length', status: 422 };
    fireEvent.change(screen.getByLabelText('First name'), { target: { value: 'María' } }); fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('100 characters'); expect(screen.getByLabelText('First name')).toHaveValue('María');
  });
  it('keeps the replacement session when identity refresh fails and explains the saved change', async () => {
    await ready(); const dialog = await open('Change email');
    failure = { path: '/auth/me', code: 'unavailable', status: 503 };
    fireEvent.change(dialog.getByLabelText('New email address'), { target: { value: 'new@example.com' } });
    await passwordProof(dialog, 'Verify and change email');
    expect(await screen.findByRole('alert')).toHaveTextContent('The change was saved');
    expect(getAccessToken()).toBe('replacement-session');
    expect(screen.getByRole('button', { name: 'Reload page' })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Verify and change email' })).not.toBeInTheDocument();
  });
  it('translates a browser passkey failure without submitting the sensitive change', async () => {
    keys = [key]; await ready();
    vi.mocked(startAuthentication).mockRejectedValue(Object.assign(new Error('SECRET browser diagnostics'), { name: 'WebAuthnError' }));
    const dialog = await open('Change email');
    fireEvent.change(dialog.getByLabelText('New email address'), { target: { value: 'new@example.com' } });
    fireEvent.click(dialog.getByLabelText('Verify with passkey')); fireEvent.click(dialog.getByRole('button', { name: 'Verify and change email' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The passkey could not be verified or added');
    expect(calls.some((call) => call.path === '/auth/me/email')).toBe(false);
  });
  it('shows password policy errors from the backend without changing session', async () => {
    await ready(); failure = { path: '/auth/me/password', code: 'password_policy', status: 400 };
    const dialog = await open('Change password');
    for (const label of ['New password', 'Confirm password']) fireEvent.change(dialog.getByLabelText(label), { target: { value: 'short' } });
    await passwordProof(dialog, 'Verify and change password');
    expect(await screen.findByRole('alert')).toHaveTextContent('Use at least 12 characters');
    expect(getAccessToken()).toBe('original-session');
  });
  it('keeps passkey loading failures distinct from an empty list and offers retry', async () => {
    failure = { path: '/auth/passkeys', code: 'unknown', status: 503 }; await ready();
    expect(screen.queryByText('You have no passkeys yet.')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load your passkeys');
    failure = null; fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('You have no passkeys yet.')).toBeVisible();
  });

});
