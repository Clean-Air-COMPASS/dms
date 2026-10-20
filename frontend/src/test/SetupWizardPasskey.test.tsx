import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { browserSupportsWebAuthnAutofill } from '@simplewebauthn/browser';
import SetupWizard from '../SetupWizard';
import { registerPasskey } from '../auth/passkeys';
import i18n from '../i18n';

vi.mock('../auth/passkeys', () => ({ registerPasskey: vi.fn() }));
vi.mock('@simplewebauthn/browser', () => ({
  browserSupportsWebAuthnAutofill: vi.fn(), WebAuthnAbortService: { cancelCeremony: vi.fn() },
}));

beforeEach(async () => {
  await act(() => i18n.changeLanguage('en'));
  vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true);
  vi.mocked(registerPasskey).mockResolvedValue(undefined);
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    if (String(input).endsWith('/setup/data-sources')) return Response.json({ data_sources: [] });
    if (String(input).endsWith('/auth/login')) return Response.json({ access_token: 'test-token' });
    return Response.json({ success: true });
  });
});
afterEach(() => { vi.restoreAllMocks(); vi.clearAllMocks(); });

async function createAdmin() {
  render(<SetupWizard onSetupComplete={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  fireEvent.change(screen.getByLabelText('Email Address'), { target: { value: 'admin@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'StrongPassword1!' } });
  fireEvent.change(screen.getByLabelText('Confirm Password'), { target: { value: 'StrongPassword1!' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create Admin Account' }));
  await screen.findByRole('heading', { name: 'Protect your administrator account' });
}

it('appears after creation and registers before advancing', async () => {
  await createAdmin();
  fireEvent.click(screen.getByRole('button', { name: 'Create a passkey' }));
  await screen.findByRole('heading', { name: 'Configure Data Source' });
  expect(registerPasskey).toHaveBeenCalledWith('test-token', expect.any(AbortSignal));
  expect(document.body).not.toHaveTextContent('test-token');
});

it('can skip without starting authentication', async () => {
  await createAdmin();
  fireEvent.click(screen.getByRole('button', { name: 'Set up later' }));
  expect(screen.getByRole('heading', { name: 'Configure Data Source' })).toBeVisible();
  expect(registerPasskey).not.toHaveBeenCalled();
});

it('retries failed registration using the same in-memory authorization', async () => {
  vi.mocked(registerPasskey).mockRejectedValueOnce(new Error('temporary failure'));
  await createAdmin();
  fireEvent.click(screen.getByRole('button', { name: 'Create a passkey' }));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Create a passkey' }));
  await screen.findByRole('heading', { name: 'Configure Data Source' });
  const authRequests = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith('/auth/login'));
  expect(authRequests).toHaveLength(1);
  expect(authRequests[0][1]?.credentials).toBe('omit');
  expect(registerPasskey).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('status')).toHaveTextContent('Passkey created');
});

it.each(['NotAllowedError', 'UnknownError'])('sanitizes %s and allows retry and skip', async (name) => {
  vi.mocked(registerPasskey).mockRejectedValueOnce(new DOMException('SECRET credential details', name));
  await createAdmin();
  fireEvent.click(screen.getByRole('button', { name: 'Create a passkey' }));
  expect(await screen.findByRole('alert')).not.toHaveTextContent('SECRET');
  expect(screen.getByRole('button', { name: 'Create a passkey' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Set up later' }));
  expect(screen.getByRole('heading', { name: 'Configure Data Source' })).toBeVisible();
});

it('unsupported browsers can continue and Spanish copy updates immediately', async () => {
  vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(false);
  await createAdmin();
  await act(() => i18n.changeLanguage('es'));
  expect(screen.getByRole('heading', { name: 'Proteja su cuenta de administrador' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Crear una clave de acceso' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('no están disponibles');
  fireEvent.click(screen.getByRole('button', { name: 'Configurar más adelante' }));
  expect(screen.getByRole('heading', { name: 'Configurar fuente de datos' })).toBeVisible();
});

it('skips on resumed setup', () => {
  render(<SetupWizard initialAdminCreated onSetupComplete={vi.fn()} />);
  expect(screen.getByRole('heading', { name: 'Configure Data Source' })).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Create a passkey' })).toBeNull();
});

it('can skip while registration is pending without a late navigation', async () => {
  let finish!: () => void;
  vi.mocked(registerPasskey).mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
  await createAdmin();
  fireEvent.click(screen.getByRole('button', { name: 'Create a passkey' }));
  await waitFor(() => expect(registerPasskey).toHaveBeenCalled());
  fireEvent.click(screen.getByRole('button', { name: 'Set up later' }));
  fireEvent.click(screen.getByRole('button', { name: /Skip for Now/ }));
  await act(async () => finish());
  expect(screen.getByRole('heading', { name: 'Configure Location Search' })).toBeVisible();
});
