import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import MapLibreMap from '../MapLibreMap';
import { fetchJson } from '../api';
import i18n from '../i18n';
import type { DataAttribution } from '../dataAttribution';

vi.mock('../api', async (importActual) => ({
  ...await importActual<typeof import('../api')>(), fetchJson: vi.fn(),
}));
vi.mock('../SensorChart', () => ({ default: () => <div /> }));

afterEach(async () => {
  cleanup();
  vi.clearAllMocks();
  document.querySelectorAll('.maplibregl-marker, [title^="PM25"], [title="Synthetic attribution station"]').forEach(element => element.remove());
  await act(async () => { await i18n.changeLanguage('en'); });
});

describe.each(['en', 'es'])('Map canonical attribution in %s', language => {
  describe.each(['devices', 'measurements'] as const)('%s layer', mode => {
    it.each(['PurpleAir', 'OpenAQ', 'AirGradient'])('renders %s and its distinct contributor and links', async provider => {
      await act(async () => { await i18n.changeLanguage(language); });
      const attribution: DataAttribution = {
        acquisition_path: provider === 'AirGradient' ? 'airgradient_public_reference' : 'unspecified',
        data_provider_name: provider, hardware_provider_name: null,
        provider_url: 'https://example.org/device/123',
        contributor_name: 'Synthetic Monitoring Organization', contributor_url: 'https://example.org/contributor',
        license_code: 'CC-BY-4.0', license_url: 'https://creativecommons.org/licenses/by/4.0/', license_share_alike: false,
      };
      await openDetail(mode, attribution);
      const section = screen.getByRole('complementary', { name: language === 'es' ? 'Atribución de datos' : 'Data attribution' });
      expect(screen.getAllByRole('complementary')).toHaveLength(1);
      expect(section).toHaveTextContent(`${language === 'es' ? 'Datos proporcionados por' : 'Data provided by'} ${provider}`);
      for (const [name, href] of [[provider, attribution.provider_url], [attribution.contributor_name!, attribution.contributor_url], ['CC-BY-4.0', attribution.license_url]]) {
        const link = within(section).getByRole('link', { name: name! });
        expect(link).toHaveAttribute('href', href);
        expect(link).toHaveAttribute('target', '_blank');
        expect(link).toHaveAttribute('rel', 'noreferrer');
      }
      expect(document.body.innerHTML).not.toContain('synthetic-private-token');
    });

    it('omits missing optional PurpleAir fields', async () => {
      await act(async () => { await i18n.changeLanguage(language); });
      await openDetail(mode, {
        acquisition_path: 'unspecified', data_provider_name: 'PurpleAir', hardware_provider_name: null,
        provider_url: null, contributor_name: null, contributor_url: null,
        license_code: null, license_url: null, license_share_alike: null,
      });
      const section = screen.getByRole('complementary');
      expect(section.textContent).toBe(`${language === 'es' ? 'Datos proporcionados por' : 'Data provided by'} PurpleAir.`);
      expect(within(section).queryByRole('link')).not.toBeInTheDocument();
    });
  });
});

async function openDetail(mode: 'devices' | 'measurements', data_attribution: DataAttribution) {
  const device = { device_id: 901, name: 'Synthetic attribution station', latitude: 0, longitude: 0, network: data_attribution.data_provider_name, data_attribution, api_key: 'synthetic-private-token' };
  vi.mocked(fetchJson).mockImplementation(async path => {
    if (String(path).startsWith('/devices/901/sensors')) return [];
    if (String(path).startsWith('/devices?')) return [device];
    if (String(path).startsWith('/measurements/pm25/latest')) return [{ sensor_id: 902, parameter: 'pm25', value: 12, unit: 'µg/m³', observed_at: new Date().toISOString(), device }];
    if (String(path).startsWith('/sensors/902/history')) return { data: [], sensor_id: 902, parameter: 'pm25', unit: 'µg/m³' };
    throw new Error(`Unexpected request: ${path}`);
  });
  render(<MemoryRouter><MapLibreMap parameter="pm25" mode={mode === 'devices' ? 'devices' : 'pollutants'} /></MemoryRouter>);
  const marker = await waitFor(() => {
    const element = document.querySelector(mode === 'devices' ? '[title="Synthetic attribution station"]' : '[title^="PM25"]');
    expect(element).not.toBeNull();
    return element as HTMLElement;
  });
  fireEvent.click(marker);
  await screen.findByRole('complementary');
}
