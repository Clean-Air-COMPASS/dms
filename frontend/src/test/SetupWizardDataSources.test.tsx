import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SetupWizard from '../SetupWizard';
import i18n from '../i18n';

const dataSources = [
  {
    external_api_id: 1,
    provider_code: 'openaq',
    name: 'OpenAQ',
    description: 'Built-in source: OpenAQ',
    has_api_key: false,
    enabled: false,
    runnable_reason: 'disabled',
  },
  {
    external_api_id: 2,
    provider_code: 'purpleair',
    name: 'PurpleAir',
    description: 'Built-in source: PurpleAir',
    has_api_key: false,
    enabled: false,
    runnable_reason: 'disabled',
  },
  {
    external_api_id: 3,
    provider_code: 'airgradient',
    name: 'AirGradient',
    description: 'Built-in source: AirGradient',
    has_api_key: false,
    enabled: false,
    runnable_reason: 'disabled',
  },
];

const demoDataSource = {
  external_api_id: 4,
  provider_code: 'demo',
  name: 'Demo Data',
  description: 'Synthetic demonstration data',
  has_api_key: false,
  requires_credential: false,
  enabled: true,
  runnable_reason: 'ready',
};

function mockSetupRequests(sources = dataSources) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith('/setup/data-sources')) {
      return new Response(JSON.stringify({ data_sources: sources }), { status: 200 });
    }
    if (url.endsWith('/setup/admin')) {
      return new Response(JSON.stringify({ success: true }), { status: 200 });
    }
    if (url.endsWith('/setup/data-source')) {
      return new Response(JSON.stringify({ success: true }), { status: 200 });
    }
    if (url.endsWith('/setup/geoapify')) {
      return new Response(JSON.stringify({ success: true }), { status: 200 });
    }
    throw new Error(`Unexpected setup request: ${url}`);
  });
}

async function renderDataSourceStep() {
  const fetchMock = mockSetupRequests();
  render(<SetupWizard onSetupComplete={vi.fn()} />);

  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

  fireEvent.change(screen.getByLabelText('Email Address'), {
    target: { value: 'admin@example.com' },
  });
  fireEvent.change(screen.getByLabelText('Password'), {
    target: { value: 'StrongPassword1!' },
  });
  fireEvent.change(screen.getByLabelText('Confirm Password'), {
    target: { value: 'StrongPassword1!' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Create Admin Account' }));

  fireEvent.click(await screen.findByRole('button', { name: 'Set up later' }));

  await waitFor(() => {
    expect(screen.getByRole('heading', { name: 'Configure Data Source' })).toBeInTheDocument();
    expect(screen.getAllByRole('textbox', { name: 'API Key' })).toHaveLength(3);
  }, { timeout: 3000 });

  return fetchMock;
}

async function renderDemoCompletion(demoEnabled: boolean) {
  const user = userEvent.setup();
  const spanish = i18n.resolvedLanguage === 'es';
  mockSetupRequests([{ ...demoDataSource, enabled: true }, ...dataSources]);
  render(<SetupWizard onSetupComplete={vi.fn()} initialAdminCreated />);

  const toggle = await screen.findByRole('checkbox', {
    name: spanish ? 'Habilitar Demo Data' : 'Enable Demo Data',
  });
  if (!demoEnabled) await user.click(toggle);
  await user.click(screen.getByRole('button', {
    name: spanish ? 'Guardar fuentes y continuar' : 'Save Sources & Continue',
  }));
  await screen.findByRole('heading', {
    name: spanish ? 'Configurar la búsqueda de ubicación' : 'Configure Location Search',
  });
  await user.click(screen.getByRole('button', {
    name: spanish ? 'Saltar por ahora →' : 'Skip for Now →',
  }));

  const statusLabel = i18n.t(demoEnabled ? 'admin:workspace.enabled' : 'admin:workspace.disabled');
  return screen.getByText(`Demo Data: ${statusLabel}`).closest('.setup-summary-item') as HTMLElement;
}

describe('setup provider API-key cards', () => {
  beforeEach(async () => {
    vi.restoreAllMocks();
    await act(() => i18n.changeLanguage('en'));
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await act(() => i18n.changeLanguage('en'));
  });

  it('starts a clean install with an optional preparation guide', async () => {
    const user = userEvent.setup();
    mockSetupRequests();
    render(<SetupWizard onSetupComplete={vi.fn()} />);

    expect(screen.getByRole('heading', { name: 'Welcome to CompassAQ' })).toBeInTheDocument();
    expect(screen.queryByText('Before you begin')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Optional items to have ready' })).toBeInTheDocument();
    expect(screen.getByText('You can complete setup without any external service accounts. If you already have API keys or email settings available, you can add them during setup.')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem').map((item) => item.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      'AirGradient API token — Import your AirGradient locations.',
      'OpenAQ API key — Import monitoring data from OpenAQ.',
      'PurpleAir API key — Import PurpleAir sensor data.',
      'Geoapify API key — Enable map/geocoding features that require Geoapify.',
      'SMTP settings — Send Administrator Summary and other email notifications.',
    ]);
    expect(screen.getByText('Anything you skip can be configured later from Administration.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /skip/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(screen.getByRole('heading', { name: 'Create Admin Account' })).toBeInTheDocument();
  });

  it('uses the updated welcome copy in Spanish', async () => {
    await act(() => i18n.changeLanguage('es'));
    mockSetupRequests();
    render(<SetupWizard onSetupComplete={vi.fn()} />);

    expect(screen.getByRole('heading', { name: 'Bienvenido a CompassAQ' })).toBeInTheDocument();
    expect(screen.queryByText('Antes de comenzar')).not.toBeInTheDocument();
    expect(screen.getByText('Puede completar la configuración sin ninguna cuenta de servicios externos. Si ya dispone de claves API o de la configuración de correo electrónico, puede añadir esa información durante la configuración.')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem').map((item) => item.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      'Token API de AirGradient — Importe sus ubicaciones de AirGradient.',
      'Clave API de OpenAQ — Importe datos de monitoreo de OpenAQ.',
      'Clave API de PurpleAir — Importe datos de sensores de PurpleAir.',
      'Clave API de Geoapify — Habilite las funciones de mapas y geocodificación que requieren Geoapify.',
      'Configuración de SMTP — Envíe el Resumen para administradores y otras notificaciones por correo electrónico.',
    ]);
    expect(screen.getByText('Todo lo que omita podrá configurarse más adelante desde Administración.')).toBeInTheDocument();
  });

  it('uses visible, editable text inputs and removes redundant provider copy', async () => {
    const user = userEvent.setup();
    await renderDataSourceStep();

    const apiKeyInputs = screen.getAllByRole('textbox', { name: 'API Key' });
    expect(screen.getByPlaceholderText('AirGradient API key')).toBeInTheDocument();
    for (const input of apiKeyInputs) {
      expect(input).toHaveAttribute('type', 'text');
      expect(input).not.toHaveAttribute('maxlength');
    }
    expect(screen.queryByRole('button', { name: /show|hide/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Enabled' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Built-in source:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Credentials are saved/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/No provider (request|was contacted)/i)).not.toBeInTheDocument();

    const longApiKey = 'a'.repeat(64);
    await user.type(apiKeyInputs[0], longApiKey);
    expect(apiKeyInputs[0]).toHaveValue(longApiKey);
  }, 10000);

  it('resumes at data sources when an administrator already exists', async () => {
    mockSetupRequests();
    render(<SetupWizard onSetupComplete={vi.fn()} initialAdminCreated />);

    expect(await screen.findByRole('heading', { name: 'Configure Data Source' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Create Admin Account' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Welcome to CompassAQ' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '← Back' })).not.toBeInTheDocument();
  });

  it('derives setup enabled state from trimmed API keys and makes no provider calls', async () => {
    const user = userEvent.setup();
    const fetchMock = await renderDataSourceStep();

    const apiKeyInputs = screen.getAllByRole('textbox', { name: 'API Key' });
    await user.type(apiKeyInputs[0], '  purple-key  ');
    await user.type(apiKeyInputs[2], '   ');

    await user.click(screen.getByRole('button', { name: 'Save Sources & Continue' }));
    await waitFor(() => {
      const sourceRequests = fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/setup/data-source'));
      expect(sourceRequests).toHaveLength(3);
    });

    const sourceRequests = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith('/setup/data-source'))
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(sourceRequests).toEqual([
      { external_api_id: 2, enabled: true, api_key: 'purple-key' },
      { external_api_id: 1, enabled: false, api_key: null },
      { external_api_id: 3, enabled: false, api_key: null, import_authenticated_locations: false },
    ]);
    expect(fetchMock.mock.calls.some(([input]) => /api\.(openaq|purpleair|airgradient)\.com/i.test(String(input))))
      .toBe(false);

    expect(await screen.findByRole('heading', { name: 'Configure Location Search' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Skip for Now →' }));
    expect(await screen.findByRole('heading', { name: 'Setup Complete!' })).toBeInTheDocument();
    expect(screen.getByText('Data source configured and enabled')).toBeInTheDocument();
  }, 10000);

  it('summarizes an all-blank setup as not configured', async () => {
    const user = userEvent.setup();
    await renderDataSourceStep();

    await user.click(screen.getByRole('button', { name: 'Save Sources & Continue' }));
    expect(await screen.findByRole('heading', { name: 'Configure Location Search' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Skip for Now →' }));

    expect(await screen.findByRole('heading', { name: 'Setup Complete!' })).toBeInTheDocument();
    expect(screen.getByText('Data source not configured or enabled (can be done in Admin)')).toBeInTheDocument();
  }, 10000);

  it.each([false, true])('saves the explicit AirGradient linked-location choice: %s', async (linkedLocations) => {
    const user = userEvent.setup();
    const fetchMock = await renderDataSourceStep();
    const choice = screen.getByRole('checkbox', { name: 'Also import my AirGradient account locations' });
    expect(choice).not.toBeChecked();
    expect(screen.getByText('By default, CompassAQ imports only its built-in public AirGradient reference locations. Check this box to also import all locations associated with this API key.')).toBeInTheDocument();
    expect(screen.queryByText(/Turning this off later stops token-linked imports/i)).not.toBeInTheDocument();
    await user.type(screen.getAllByRole('textbox', { name: 'API Key' })[2], 'airgradient-key');
    if (linkedLocations) {
      await user.click(choice);
    }
    // The supplied boolean is the persisted import choice; the UI must not change it while saving.
    if (linkedLocations) expect(choice).toBeChecked();
    else expect(choice).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Save Sources & Continue' }));
    await screen.findByRole('heading', { name: 'Configure Location Search' });
    const request = fetchMock.mock.calls
      .filter(([input]) => String(input).endsWith('/setup/data-source'))
      .map(([, init]) => JSON.parse(String(init?.body)))
      .find(body => body.external_api_id === 3);
    expect(request).toEqual({ external_api_id: 3, enabled: true, api_key: 'airgradient-key', import_authenticated_locations: linkedLocations });
  }, 10000);

  it.each([true, false])('uses the matching summary icon when Demo Data is %s', async (demoEnabled) => {
    const demoSummary = await renderDemoCompletion(demoEnabled);

    expect(demoSummary.querySelector('.setup-summary-icon')).toHaveTextContent(demoEnabled ? '✓' : '○');
  });

  it('keeps the Demo Data summary status localized in Spanish', async () => {
    await act(() => i18n.changeLanguage('es'));
    const demoSummary = await renderDemoCompletion(true);

    expect(demoSummary).toHaveTextContent('Demo Data: Habilitada');
    expect(demoSummary.querySelector('.setup-summary-icon')).toHaveTextContent('✓');
  });

  it('keeps the same plain-text provider input behavior in Spanish', async () => {
    await renderDataSourceStep();
    await act(() => i18n.changeLanguage('es'));

    expect(screen.getByRole('heading', { name: 'Configurar fuente de datos' })).toBeInTheDocument();
    const apiKeyInputs = screen.getAllByRole('textbox', { name: 'Clave API' });
    expect(apiKeyInputs).toHaveLength(3);
    expect(screen.getByPlaceholderText('Clave API de AirGradient')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Importar también las ubicaciones de mi cuenta de AirGradient' })).not.toBeChecked();
    expect(screen.getByText('De forma predeterminada, CompassAQ importa solo las ubicaciones públicas de referencia de AirGradient integradas en CompassAQ. Marque esta casilla para importar también todas las ubicaciones asociadas con esta clave API.')).toBeInTheDocument();
    expect(screen.queryByText(/Si desactiva esta opción más adelante/i)).not.toBeInTheDocument();
    for (const input of apiKeyInputs) {
      expect(input).toHaveAttribute('type', 'text');
    }
    expect(screen.queryByText(/Fuente integrada:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sin contactar al proveedor/i)).not.toBeInTheDocument();
  }, 10000);

  it('advances successful intermediate steps without artificial timers', async () => {
    const user = userEvent.setup();
    const timeoutSpy = vi.spyOn(globalThis, 'setTimeout');
    await renderDataSourceStep();

    expect(screen.queryByText(/Moving to next step/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save Sources & Continue' }));
    expect(await screen.findByRole('heading', { name: 'Configure Location Search' })).toBeInTheDocument();

    await user.type(screen.getByLabelText('Geoapify API Key'), 'geoapify-key');
    await user.click(screen.getByRole('button', { name: 'Save & Continue' }));
    expect(await screen.findByRole('heading', { name: 'Setup Complete!' })).toBeInTheDocument();

    const artificialDelays = timeoutSpy.mock.calls
      .map(([, delay]) => delay)
      .filter((delay) => delay === 800 || delay === 1500);
    expect(artificialDelays).toEqual([]);
  }, 10000);

  it('keeps an intermediate-step error visible on the current step', async () => {
    const user = userEvent.setup();
    const fetchMock = mockSetupRequests();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/setup/data-sources')) {
        return new Response(JSON.stringify({ data_sources: dataSources }), { status: 200 });
      }
      if (url.endsWith('/setup/admin')) {
        return new Response(JSON.stringify({ success: false, detail: {} }), { status: 500 });
      }
      throw new Error(`Unexpected setup request: ${url}`);
    });
    render(<SetupWizard onSetupComplete={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Continue' }));

    await user.type(screen.getByLabelText('Email Address'), 'admin@example.com');
    await user.type(screen.getByLabelText('Password'), 'StrongPassword1!');
    await user.type(screen.getByLabelText('Confirm Password'), 'StrongPassword1!');
    await user.click(screen.getByRole('button', { name: 'Create Admin Account' }));

    expect(await screen.findByText('The administrator account could not be created.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Create Admin Account' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Configure Data Source' })).not.toBeInTheDocument();
  }, 10000);
});

it('orders wizard providers by identity and retains custom source order', async () => {
  const sources = [
    { ...dataSources[0], external_api_id: 99 },
    { ...dataSources[0], external_api_id: 8, provider_code: null, name: 'Custom A' },
    { ...dataSources[2], external_api_id: 1 },
    { ...dataSources[0], external_api_id: 7, provider_code: 'custom', name: 'Custom B' },
    { ...dataSources[1], external_api_id: 100 },
    { ...dataSources[0], external_api_id: 55, provider_code: 'demo', name: 'Demo Data', requires_credential: false, enabled: true },
  ];
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ data_sources: sources })));
  const { container } = render(<SetupWizard onSetupComplete={vi.fn()} initialAdminCreated />);
  await waitFor(() => expect(container.querySelectorAll('.setup-source-card')).toHaveLength(6));
  expect(Array.from(container.querySelectorAll('.setup-source-card strong')).map(el => el.textContent)).toEqual([
    'Demo Data', 'PurpleAir', 'OpenAQ', 'AirGradient', 'Custom A', 'Custom B',
  ]);
});
