import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SetupWizard from '../SetupWizard';
import i18n from '../i18n';

const passwords = {
  password: 'StrongPassword1!',
  confirmPassword: 'StrongPassword1!',
};

function mockSetupAdmin(response: () => Response | Promise<Response>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    if (String(input).endsWith('/setup/data-sources')) {
      return new Response(JSON.stringify({ data_sources: [] }), { status: 200 });
    }
    if (String(input).endsWith('/setup/admin')) return response();
    throw new Error(`Unexpected setup request: ${String(input)}`);
  });
}

async function openAdminStep(language: 'en' | 'es') {
  const user = userEvent.setup();
  render(<SetupWizard onSetupComplete={vi.fn()} />);
  await user.click(screen.getByRole('button', { name: language === 'es' ? 'Continuar' : 'Continue' }));
  await screen.findByRole('heading', {
    name: language === 'es' ? 'Crear cuenta de administrador' : 'Create Admin Account',
  });
  return user;
}

describe('setup administrator email validation feedback', () => {
  beforeEach(async () => {
    vi.restoreAllMocks();
    await act(() => i18n.changeLanguage('en'));
  });

  afterEach(async () => {
    cleanup();
    vi.restoreAllMocks();
    await act(() => i18n.changeLanguage('en'));
  });

  it.each([
    {
      language: 'en' as const,
      message: 'Enter a valid email address, such as name@example.com.',
    },
    {
      language: 'es' as const,
      message: 'Ingrese una dirección de correo electrónico válida, por ejemplo, nombre@ejemplo.com.',
    },
  ])('shows a localized field error and recovers after correction ($language)', async ({ language, message }) => {
    const fetchMock = mockSetupAdmin(() => new Response(JSON.stringify({ success: true }), { status: 200 }));
    await act(() => i18n.changeLanguage(language));
    const user = await openAdminStep(language);
    const email = screen.getByLabelText(language === 'es' ? 'Dirección de correo electrónico' : 'Email Address');

    fireEvent.change(email, { target: { value: 'not-an-email' } });
    fireEvent.invalid(email);

    expect(email).toHaveFocus();
    expect(email).toHaveAttribute('aria-invalid', 'true');
    expect(email).toHaveAttribute('aria-describedby', 'admin-email-error');
    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(fetchMock.mock.calls.filter(([input, init]) => (
      String(input).endsWith('/setup/admin') && init?.method === 'POST'
    ))).toHaveLength(0);

    fireEvent.change(email, { target: { value: 'installer@example.org' } });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(email).not.toHaveAttribute('aria-invalid');

    fireEvent.change(screen.getByLabelText(language === 'es' ? 'Contraseña' : 'Password'), { target: { value: passwords.password } });
    fireEvent.change(screen.getByLabelText(language === 'es' ? 'Confirmar contraseña' : 'Confirm Password'), { target: { value: passwords.confirmPassword } });
    await user.click(screen.getByRole('button', { name: language === 'es' ? 'Crear cuenta de administrador' : 'Create Admin Account' }));

    await screen.findByRole('heading', { name: language === 'es' ? 'Proteja su cuenta de administrador' : 'Protect your administrator account' });
    const request = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/setup/admin'));
    expect(request).toBeDefined();
    expect(request?.[1]?.method).toBe('POST');
    expect(JSON.parse(String(request?.[1]?.body)).email).toBe('installer@example.org');
  });

  it('announces a missing email through the existing setup error pattern', async () => {
    const fetchMock = mockSetupAdmin(() => new Response(JSON.stringify({ success: true }), { status: 200 }));
    const user = await openAdminStep('en');

    await user.click(screen.getByRole('button', { name: 'Create Admin Account' }));

    expect(screen.getByRole('alert')).toHaveTextContent('Email address is required');
    expect(fetchMock.mock.calls.filter(([input, init]) => (
      String(input).endsWith('/setup/admin') && init?.method === 'POST'
    ))).toHaveLength(0);
  });

  it('keeps entered values and hides raw backend validation details', async () => {
    const fetchMock = mockSetupAdmin(() => new Response(JSON.stringify({
      detail: [{ msg: 'value is not a valid email address: An internal validator detail.' }],
    }), { status: 422 }));
    const user = await openAdminStep('en');
    const email = screen.getByLabelText('Email Address');
    const password = screen.getByLabelText('Password');
    const confirmPassword = screen.getByLabelText('Confirm Password');

    fireEvent.change(email, { target: { value: 'installer@example.org' } });
    fireEvent.change(password, { target: { value: passwords.password } });
    fireEvent.change(confirmPassword, { target: { value: passwords.confirmPassword } });
    await user.click(screen.getByRole('button', { name: 'Create Admin Account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('The administrator account could not be created.');
    expect(screen.queryByText(/internal validator detail/i)).not.toBeInTheDocument();
    expect(email).toHaveValue('installer@example.org');
    expect(password).toHaveValue(passwords.password);
    expect(confirmPassword).toHaveValue(passwords.confirmPassword);
    expect(fetchMock.mock.calls.filter(([input, init]) => (
      String(input).endsWith('/setup/admin') && init?.method === 'POST'
    ))).toHaveLength(1);
  });

  it('shows the network recovery message and retains entered values', async () => {
    const fetchMock = mockSetupAdmin(() => Promise.reject(new TypeError('Failed to fetch')));
    const user = await openAdminStep('en');
    const email = screen.getByLabelText('Email Address');
    const password = screen.getByLabelText('Password');
    const confirmPassword = screen.getByLabelText('Confirm Password');

    fireEvent.change(email, { target: { value: 'installer@example.org' } });
    fireEvent.change(password, { target: { value: passwords.password } });
    fireEvent.change(confirmPassword, { target: { value: passwords.confirmPassword } });
    await user.click(screen.getByRole('button', { name: 'Create Admin Account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Network error. Please try again.');
    expect(email).toHaveValue('installer@example.org');
    expect(email).not.toHaveAttribute('aria-invalid');
    expect(email).not.toHaveAttribute('aria-describedby');
    expect(password).toHaveValue(passwords.password);
    expect(confirmPassword).toHaveValue(passwords.confirmPassword);
    expect(fetchMock.mock.calls.filter(([input, init]) => (
      String(input).endsWith('/setup/admin') && init?.method === 'POST'
    ))).toHaveLength(1);
  });

  it.each([
    { password: 'weak', confirmation: 'weak', message: 'Please choose a stronger password' },
    { password: passwords.password, confirmation: 'DifferentPassword1!', message: 'Passwords do not match' },
  ])('preserves client password validation ($message)', async ({ password, confirmation, message }) => {
    const response = vi.fn(() => new Response(JSON.stringify({ success: true }), { status: 200 }));
    mockSetupAdmin(response);
    const user = await openAdminStep('en');
    const email = screen.getByLabelText('Email Address');
    fireEvent.change(email, { target: { value: 'installer@example.org' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } });
    fireEvent.change(screen.getByLabelText('Confirm Password'), { target: { value: confirmation } });
    await user.click(screen.getByRole('button', { name: 'Create Admin Account' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(email).not.toHaveAttribute('aria-invalid');
    expect(response).not.toHaveBeenCalled();
  });

  it.each([
    { language: 'en' as const, message: 'Enter a valid email address, such as name@example.com.' },
    { language: 'es' as const, message: 'Ingrese una dirección de correo electrónico válida, por ejemplo, nombre@ejemplo.com.' },
  ])('maps the original P1-02 backend rejection to the email field ($language)', async ({ language, message }) => {
    const response = vi.fn()
      .mockReturnValueOnce(new Response(JSON.stringify({ detail: [{
        loc: ['body', 'email'], type: 'value_error', msg: 'PRIVATE validator diagnostics',
      }] }), { status: 422 }))
      .mockReturnValueOnce(new Response(JSON.stringify({ success: true }), { status: 200 }));
    const fetchMock = mockSetupAdmin(response);
    await act(() => i18n.changeLanguage(language));
    const user = await openAdminStep(language);
    const email = document.getElementById('admin-email') as HTMLInputElement;
    const password = document.getElementById('admin-password') as HTMLInputElement;
    const confirmation = document.getElementById('admin-confirm-password') as HTMLInputElement;
    fireEvent.change(email, { target: { value: 'qa.jordan@example.invalid' } });
    fireEvent.change(password, { target: { value: passwords.password } });
    fireEvent.change(confirmation, { target: { value: passwords.confirmPassword } });
    expect(email.validity.valid).toBe(true);
    await user.click(screen.getByRole('button', { name: language === 'es' ? 'Crear cuenta de administrador' : 'Create Admin Account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(email).toHaveFocus();
    expect(email).toHaveAttribute('aria-invalid', 'true');
    expect(email).toHaveAccessibleDescription(message);
    expect(email).toHaveValue('qa.jordan@example.invalid');
    expect(password).toHaveValue(passwords.password);
    expect(confirmation).toHaveValue(passwords.confirmPassword);
    expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
    expect(response).toHaveBeenCalledTimes(1);

    fireEvent.change(email, { target: { value: '  installer@example.org  ' } });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(email).not.toHaveAttribute('aria-invalid');
    await user.click(screen.getByRole('button', { name: language === 'es' ? 'Crear cuenta de administrador' : 'Create Admin Account' }));
    await screen.findByRole('heading', { name: language === 'es' ? 'Proteja su cuenta de administrador' : 'Protect your administrator account' });
    expect(response).toHaveBeenCalledTimes(2);
    const requests = fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/setup/admin'));
    expect(JSON.parse(String(requests[0][1]?.body)).email).toBe('qa.jordan@example.invalid');
    expect(JSON.parse(String(requests[1][1]?.body)).email).toBe('installer@example.org');
  });

  it.each([
    { name: 'another field', status: 422, detail: [{ loc: ['body', 'password'], type: 'value_error' }] },
    { name: 'nested email', status: 422, detail: [{ loc: ['body', 'other', 'email'], type: 'value_error' }] },
    { name: 'query email', status: 422, detail: [{ loc: ['query', 'email'], type: 'value_error' }] },
    { name: 'unexpected validation type', status: 422, detail: [{ loc: ['body', 'email'], type: 'unexpected' }] },
    { name: 'missing validation type', status: 422, detail: [{ loc: ['body', 'email'] }] },
    { name: 'unstructured message', status: 422, detail: 'invalid email PRIVATE' },
    { name: 'malformed validation entry', status: 422, detail: [null, 42, { loc: 'email', type: 'value_error' }] },
    { name: 'duplicate administrator', status: 409, detail: { error_code: 'setup_admin_already_created' } },
    { name: 'completed setup', status: 403, detail: { error_code: 'setup_already_completed' }, message: 'System setup has already been completed.' },
    { name: 'unauthorized', status: 401, detail: 'PRIVATE' },
    { name: 'server error', status: 500, detail: [{ loc: ['body', 'email'], type: 'value_error' }] },
    { name: 'server unavailable', status: 503, detail: 'PRIVATE' },
  ])('keeps $name failures out of the email field', async ({ status, detail, message }) => {
    mockSetupAdmin(() => new Response(JSON.stringify({ detail }), { status }));
    const user = await openAdminStep('en');
    const email = screen.getByLabelText('Email Address');
    fireEvent.change(email, { target: { value: 'installer@example.org' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: passwords.password } });
    fireEvent.change(screen.getByLabelText('Confirm Password'), { target: { value: passwords.confirmPassword } });
    await user.click(screen.getByRole('button', { name: 'Create Admin Account' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message ?? 'The administrator account could not be created.');
    expect(email).not.toHaveAttribute('aria-invalid');
    expect(email).not.toHaveAttribute('aria-describedby');
    expect(email).toHaveValue('installer@example.org');
    expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
  });

  it('retains generic recovery for a malformed server response', async () => {
    mockSetupAdmin(() => new Response('not JSON PRIVATE', { status: 422 }));
    const user = await openAdminStep('en');
    const email = screen.getByLabelText('Email Address');
    fireEvent.change(email, { target: { value: 'installer@example.org' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: passwords.password } });
    fireEvent.change(screen.getByLabelText('Confirm Password'), { target: { value: passwords.confirmPassword } });
    await user.click(screen.getByRole('button', { name: 'Create Admin Account' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Network error. Please try again.');
    expect(email).not.toHaveAttribute('aria-invalid');
    expect(email).toHaveValue('installer@example.org');
  });
});
