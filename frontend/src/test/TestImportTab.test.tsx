import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TestImportTab from '../TestImportTab';
import { runImport, type ExternalAPI } from '../api';
import i18n from '../i18n';

vi.mock('../api', () => ({ runImport: vi.fn() }));

const source: ExternalAPI = {
  external_api_id: 3, provider_code: 'airgradient', name: 'AirGradient', enabled: true, is_runnable: true,
};

describe('live import action', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(async () => { await i18n.changeLanguage('en'); });

  it('explains the real import and submits only the displayed source', async () => {
    vi.mocked(runImport).mockResolvedValue({ ok: true, status: 200, data: { imported: 4 } });
    render(<TestImportTab selectedExternalAPI={source} />);
    expect(screen.getByText(/Starts a real import/)).toHaveTextContent(/retrieve provider data and add measurements/);
    expect(screen.getByText('AirGradient')).toBeVisible();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Sensor ID (optional)' }), { target: { value: '1620' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run import now' }));
    await waitFor(() => expect(runImport).toHaveBeenCalledWith('airgradient', '1620', false));
    expect(await screen.findByText(/"imported": 4/)).toBeVisible();
  });

  it.each([null, 'demo'])('does not default an unsupported provider %s to OpenAQ', (provider_code) => {
    render(<TestImportTab selectedExternalAPI={{ ...source, provider_code }} />);
    expect(screen.getByRole('button', { name: 'Run import now' })).toBeDisabled();
    expect(screen.getByText('This data source does not support manual imports.')).toBeVisible();
    expect(runImport).not.toHaveBeenCalled();
  });

  it('preserves the disabled source guard', () => {
    render(<TestImportTab selectedExternalAPI={{ ...source, is_runnable: false, runnable_reason: 'disabled' }} />);
    expect(screen.getByRole('button', { name: 'Run import now' })).toBeDisabled();
  });

  it('explains the same consequences in Spanish', async () => {
    await i18n.changeLanguage('es');
    render(<TestImportTab selectedExternalAPI={source} />);
    expect(screen.getByRole('button', { name: 'Ejecutar importación ahora' })).toBeVisible();
    expect(screen.getByText(/Inicia una importación real/)).toHaveTextContent(/añadir mediciones/);
    expect(screen.getByText(/Inicia una importación real/)).toHaveTextContent(/no es una prueba de configuración/);
  });
});

it.each(['openaq', 'purpleair', 'airgradient'])('blocks %s imports with missing credentials and explains the prerequisite', provider => {
  render(<TestImportTab selectedExternalAPI={{ ...source, provider_code: provider, has_api_key: false, is_configured: false, is_runnable: false, runnable_reason: 'configuration_required' }} />);
  expect(screen.getByRole('button', { name: 'Run import now' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Run import now' })).toHaveAccessibleDescription('Missing API key. Save a credential before running an import.');
});
