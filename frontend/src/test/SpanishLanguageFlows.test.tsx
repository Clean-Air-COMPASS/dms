import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import LandingPage from '../LandingPage';
import LoginPage from '../LoginPage';
import SetupWizard from '../SetupWizard';
import i18n, { LANGUAGE_STORAGE_KEY } from '../i18n';

const login = vi.fn().mockResolvedValue({ success: false, error: 'invalid', statusCode: 401 });

vi.mock('../auth', () => ({
  useAuth: () => ({
    login,
    isAuthenticated: false,
    isLoading: false,
  }),
}));

describe('Spanish public and setup flows', () => {
  beforeEach(async () => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    await act(() => i18n.changeLanguage('en'));
  });

  afterEach(async () => {
    await act(() => i18n.changeLanguage('en'));
  });

  it('persists a signed-out Spanish selection and renders the landing page in Spanish', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    );

    await user.selectOptions(screen.getByRole('combobox', { name: 'Language' }), 'es');

    await waitFor(() => expect(screen.getByRole('link', { name: 'Abrir mapa' })).toBeInTheDocument());
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('es');
    expect(document.documentElement.lang).toBe('es');
  });

  it('renders login in Spanish and keeps the language selector keyboard-accessible', async () => {
    await act(() => i18n.changeLanguage('es'));
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
    const selector = screen.getByRole('combobox', { name: 'Idioma' });
    selector.focus();
    expect(selector).toHaveFocus();
    expect(screen.getByRole('option', { name: 'English' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Español' })).toBeInTheDocument();
  });

  it('renders and completes setup in Spanish with Spanish as the explicit system default', async () => {
    await act(() => i18n.changeLanguage('es'));
    const onSetupComplete = vi.fn();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/setup/data-sources')) {
        return new Response(JSON.stringify({ data_sources: [] }), { status: 200 });
      }
      if (url.endsWith('/setup/admin')) {
        return new Response(JSON.stringify({ success: true, message_code: 'setup_admin_created' }), { status: 200 });
      }
      if (url.endsWith('/setup/complete')) {
        return new Response(JSON.stringify({ success: true, message_code: 'setup_completed' }), { status: 200 });
      }
      throw new Error(`Unexpected setup request: ${url} ${init?.method ?? 'GET'}`);
    });

    render(<SetupWizard onSetupComplete={onSetupComplete} />);

    expect(screen.getByRole('heading', { name: 'Bienvenido a CompassAQ' })).toBeInTheDocument();
    expect(screen.getByText(/Todo lo que omita podrá configurarse más adelante/)).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Idioma' })).toHaveValue('es');

    fireEvent.click(screen.getByRole('button', { name: 'Continuar' }));

    fireEvent.change(screen.getByLabelText('Dirección de correo electrónico'), {
      target: { value: 'admin@example.com' },
    });
    fireEvent.change(screen.getByLabelText('Contraseña'), {
      target: { value: 'StrongPassword1!' },
    });
    fireEvent.change(screen.getByLabelText('Confirmar contraseña'), {
      target: { value: 'StrongPassword1!' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Crear cuenta de administrador' }));

    fireEvent.click(await screen.findByRole('button', { name: 'Configurar más adelante' }));

    await screen.findByText(
      'Elija Demo Data o añada una clave API de un proveedor externo. Puede cambiar estas fuentes después en Administración.',
      { exact: false },
      { timeout: 3000 },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Saltar por ahora →' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Saltar por ahora →' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Complete la configuración y comience a usar la plataforma' }));

    await waitFor(() => expect(onSetupComplete).toHaveBeenCalledOnce());
    const completionRequest = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/setup/complete'));
    expect(JSON.parse(String(completionRequest?.[1]?.body))).toEqual({
      default_language_code: 'es',
      system_timezone: expect.any(String),
    });

  });
});
