import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminDeviceNewOpenAQ from '../AdminDeviceNewOpenAQ';
import * as api from '../api';
import i18n from '../i18n';

const apiMocks = vi.hoisted(() => ({
  lookupOpenAQLocations: vi.fn(),
  lookupOpenAQSensor: vi.fn(),
  createOpenAQDevices: vi.fn(),
}));

vi.mock('../api', async () => ({
  ...await vi.importActual<typeof import('../api')>('../api'),
  lookupOpenAQLocations: apiMocks.lookupOpenAQLocations,
  lookupOpenAQSensor: apiMocks.lookupOpenAQSensor,
  createOpenAQDevices: apiMocks.createOpenAQDevices,
}));

const location: api.OpenAQLocation = {
  device: {
    external_id: 'openaq-demo-456',
    name: 'Demo fixture — Coastal Air Lab',
    external_api_id: 1,
    latitude: -33.4489,
    longitude: -70.6693,
    timezone: 'America/Santiago',
  },
  sensors: [
    { sensor_id: 761, name: 'Fine particulate matter', parameter_code: 'pm25', parameter_display: 'PM2.5', unit: 'µg/m³', exists: false },
    { sensor_id: 762, name: 'Ozone', parameter_code: 'o3', parameter_display: 'O₃', unit: 'µg/m³', exists: false },
  ],
  metadata: {
    locality: 'Harbor District',
    country_name: 'Chile',
    country_code: 'CL',
    provider_name: 'Pacific Monitoring Network',
    owner_name: 'National Environment Agency',
    is_monitor: true,
    is_mobile: false,
    datetime_first_utc: '2024-01-15T00:00:00Z',
    datetime_last_utc: '2026-09-21T18:00:00Z',
    latest_value: 18.75,
    latest_datetime_utc: '2026-09-21T18:00:00Z',
    coverage_percent: 96.4,
    observed_count: 8432,
    expected_count: 8750,
  },
  already_exists: false,
};

async function searchLocations(language: 'en' | 'es') {
  await i18n.changeLanguage(language);
  vi.mocked(api.lookupOpenAQLocations).mockResolvedValue({ locations: [location] });
  const { container } = render(<MemoryRouter><AdminDeviceNewOpenAQ /></MemoryRouter>);

  const inputs = container.querySelectorAll<HTMLInputElement>('.bbox-fields-grid input');
  ['-73', '-34', '-70', '-33'].forEach((value, index) => {
    fireEvent.change(inputs[index], { target: { value } });
  });
  fireEvent.click(screen.getByRole('button', { name: i18n.t('common:actions.search') }));
  fireEvent.click(screen.getByRole('button', { name: i18n.t('devices:adminDeviceNewOpenAQ.actions.proceed') }));

  return screen.findByRole('table');
}

beforeEach(async () => {
  vi.clearAllMocks();
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value: vi.fn(function (this: HTMLDialogElement) { this.setAttribute('open', ''); }),
  });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value: vi.fn(function (this: HTMLDialogElement) { this.removeAttribute('open'); }),
  });
  await i18n.changeLanguage('en');
});

describe('OpenAQ location search result labels', () => {
  it.each([
    ['en', ['Select', 'Name', 'Location', 'Provider', 'Coordinates', 'Sensors', 'Data Range', 'Type']],
    ['es', ['Seleccionar', 'Nombre', 'Ubicación', 'Proveedor', 'Coordenadas', 'Sensores', 'Rango de datos', 'Tipo']],
  ] as const)('aligns every result cell with its %s column heading', async (language, expectedLabels) => {
    const table = await searchLocations(language);
    const headers = within(table).getAllByRole('columnheader');
    const cells = within(within(table).getAllByRole('row')[1]).getAllByRole('cell');

    expect(headers.map((header) => header.textContent?.trim())).toEqual(expectedLabels);
    expect(headers.every((header) => header.getAttribute('scope') === 'col')).toBe(true);
    expect(cells.map((cell) => cell.getAttribute('data-label'))).toEqual(expectedLabels);
    expect(cells.map((cell) => cell.getAttribute('headers'))).toEqual(headers.map((header) => header.id));

    expect(cells[2]).toHaveTextContent('Harbor District');
    expect(cells[2]).toHaveTextContent('Chile');
    expect(cells[2]).not.toHaveAttribute('data-label', language === 'en' ? 'Parameter' : 'Parámetro');
    expect(cells[3]).toHaveTextContent('Pacific Monitoring Network');
    expect(cells[3]).toHaveTextContent('National Environment Agency');
    expect(cells[3]).not.toHaveAttribute('data-label', language === 'en' ? 'Latest Value' : 'Último valor');
    expect(cells[5]).toHaveTextContent('PM25');
    expect(cells[5]).toHaveTextContent('O3');
    expect(cells[6]).toHaveTextContent('2024');
    expect(cells[6]).toHaveTextContent('2026');
    expect(cells[7]).toHaveTextContent('Monitor');
  });

  it('keeps result selection operable', async () => {
    const table = await searchLocations('en');
    const deviceCheckbox = within(within(table).getAllByRole('row')[1]).getAllByRole('checkbox')[0];

    expect(deviceCheckbox).toBeChecked();
    fireEvent.click(deviceCheckbox);
    expect(deviceCheckbox).not.toBeChecked();
    expect(screen.getByText(/No devices selected/)).toBeInTheDocument();
    fireEvent.click(deviceCheckbox);
    expect(deviceCheckbox).toBeChecked();
    expect(screen.getByText(/1 device, 2 sensors selected/)).toBeInTheDocument();
  });
});
