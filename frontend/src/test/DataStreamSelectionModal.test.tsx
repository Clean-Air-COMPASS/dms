import { useState, type ComponentProps } from 'react';
import { isValidAnalyticsDateRange } from '../analyticsDateRange';
import { describe, expect, it, vi, beforeEach, beforeAll } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SelectionModal from '../components/DataStreamSelectionModal';
import * as api from '../api';

// The Analytics page owns the range; this harness supplies the same controlled contract.
function DataStreamSelectionModal(props: Omit<ComponentProps<typeof SelectionModal>, 'startIso' | 'endIso' | 'rangeValid' | 'onStartChange' | 'onEndChange' | 'onStartValidityChange' | 'onEndValidityChange'> & { startIso?: string; endIso?: string }) {
  const [start, setStart] = useState(props.startIso ?? '2026-03-08T06:30:00Z');
  const [end, setEnd] = useState(props.endIso ?? '2026-03-08T08:30:00Z');
  const [startValid, setStartValid] = useState(true);
  const [endValid, setEndValid] = useState(true);
  return <SelectionModal {...props} startIso={start} endIso={end}
    rangeValid={startValid && endValid && isValidAnalyticsDateRange(start, end)}
    onStartChange={setStart} onEndChange={setEnd}
    onStartValidityChange={setStartValid} onEndValidityChange={setEndValid} />;
}

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchJson: vi.fn(),
    listPublicDataSources: vi.fn(),
  };
});

describe('DataStreamSelectionModal', () => {
  // JSDOM has no native dialog implementation. Browser checks cover focus containment.
  const showModal = vi.fn(function (this: HTMLDialogElement) { this.open = true; });
  beforeAll(() => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: showModal });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.open = false; } });
  });
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(api.listPublicDataSources).mockResolvedValue([
      { name: 'AirGradient', filter_value: 'airgradient' },
      { name: 'OpenAQ', filter_value: 'openaq' },
      { name: 'Other', filter_value: 'other' },
    ]);

    vi.mocked(api.fetchJson).mockImplementation(async (path: string) => {
      if (path === '/parameters') {
        return [{ code: 'pm25', display_name: 'PM2.5' }];
      }
      if (path.startsWith('/measurement-aggregation-capabilities')) return [];
      if (typeof path === 'string' && path.startsWith('/measurements/pm25/latest')) {
        return [];
      }
      return [];
    });
  });

  it('uses the selected display timezone for range fields and serializes edited instants', async () => {
    render(<DataStreamSelectionModal open onClose={vi.fn()} onSelectPrimary={vi.fn()} onSelectOverlay={vi.fn()}
      initialParameter="pm25" startIso="2026-03-08T06:30:00Z" endIso="2026-03-08T08:30:00Z"
      displayTimezone="America/New_York" />);
    expect(screen.getByLabelText('Start date and time')).toHaveValue('2026-03-08T01:30');
    fireEvent.change(screen.getByLabelText('Start date and time'), { target: { value: '2026-03-08T03:30' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Load Sensors' }));
    await waitFor(() => expect(vi.mocked(api.fetchJson).mock.calls.some(([path]) =>
      String(path).includes(encodeURIComponent('2026-03-08T07:30:00.000Z')),
    )).toBe(true));
  });

  it('blocks sensor queries for an invalid range and recovers after correction', async () => {
    render(<DataStreamSelectionModal open onClose={vi.fn()} onSelectPrimary={vi.fn()} onSelectOverlay={vi.fn()}
      initialParameter="pm25" displayTimezone="UTC" />);
    fireEvent.change(screen.getByLabelText('Start date and time'), { target: { value: '2026-03-08T08:30' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Start must be before End');
    expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeDisabled();
    expect(vi.mocked(api.fetchJson).mock.calls.some(([path]) => path.includes('/latest'))).toBe(false);
    fireEvent.change(screen.getByLabelText('Start date and time'), { target: { value: '2026-03-08T07:30' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
  });

  it('requires a parameter, distinguishes loading and empty, and retries discovery failures', async () => {
    let resolveDiscovery!: (rows: unknown[]) => void;
    const original = vi.mocked(api.fetchJson).getMockImplementation()!;
    let attempts = 0;
    vi.mocked(api.fetchJson).mockImplementation((path, options) => {
      if (!path.includes('/latest')) return original(path, options);
      attempts += 1;
      if (attempts === 1) return Promise.reject(new Error('Unavailable'));
      return new Promise(resolve => { resolveDiscovery = resolve; });
    });
    render(<DataStreamSelectionModal open onClose={vi.fn()} onSelectPrimary={vi.fn()} onSelectOverlay={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeDisabled();
    await waitFor(() => expect(screen.getByLabelText('Select parameter')).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Select parameter'), { target: { value: 'pm25' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Load Sensors' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(screen.getByRole('status')).toHaveTextContent('Loading');
    expect(screen.queryByText(/No data streams found/)).not.toBeInTheDocument();
    await act(async () => resolveDiscovery([]));
    expect(screen.getByText(/No data streams found/)).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('discards late discovery after changing the range or switching modes without adding streams', async () => {
    const pending: Array<(rows: unknown[]) => void> = [];
    const original = vi.mocked(api.fetchJson).getMockImplementation()!;
    vi.mocked(api.fetchJson).mockImplementation((path, options) => path.includes('/latest')
      ? new Promise(resolve => pending.push(resolve)) : original(path, options));
    const onSelect = vi.fn();
    render(<DataStreamSelectionModal open initialParameter="pm25" displayTimezone="UTC"
      onClose={vi.fn()} onSelectPrimary={onSelect} onSelectOverlay={onSelect} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Load Sensors' }));
    fireEvent.change(screen.getByLabelText('End date and time'), { target: { value: '2026-03-09T08:30' } });
    await act(async () => pending[0]([{ sensor_id: 123, parameter: 'pm25', device: { name: 'Stale station' } }]));
    expect(screen.queryByText('Stale station')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Load Sensors' }));
    fireEvent.click(screen.getByRole('button', { name: 'AQI' }));
    await act(async () => pending[1]([{ sensor_id: 123, parameter: 'pm25', device: { name: 'Stale station' } }]));
    fireEvent.click(screen.getByRole('button', { name: 'Measurement' }));
    expect(screen.getByRole('button', { name: 'Measurement' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'AQI' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByText('Stale station')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Select parameter')).toHaveValue('pm25');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('recovers from failed filter metadata and handles an AQI catalog without history products', async () => {
    const original = vi.mocked(api.fetchJson).getMockImplementation()!;
    let fail = true;
    vi.mocked(api.fetchJson).mockImplementation((path, options) => path === '/parameters' && fail
      ? Promise.reject(new Error('Unavailable')) : original(path, options));
    render(<DataStreamSelectionModal open initialParameter="pm25" onClose={vi.fn()}
      onSelectPrimary={vi.fn()} onSelectOverlay={vi.fn()}
      aqiDevices={[{ device_id: 1, name: 'Synthetic station', friendly_name: null, timezone: 'UTC', network: null, sensor_count: 1 }]} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load parameters');
    expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeDisabled();
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'AQI' }));
    expect(screen.getByText('No AQI products with history are available for this standard.')).toBeVisible();
    expect(screen.queryByRole('button', { name: /Synthetic station/ })).not.toBeInTheDocument();
  });

  it('loads data source options from the API and queries manual streams with the Other filter', async () => {
    render(
      <DataStreamSelectionModal
        open={true}
        onClose={vi.fn()}
        onSelectPrimary={vi.fn()}
        onSelectOverlay={vi.fn()}
      />
    );

    expect(await screen.findByRole('option', { name: 'AirGradient' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'OpenAQ' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Other' })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Select parameter'), { target: { value: 'pm25' } });
    fireEvent.change(screen.getByLabelText('Select data source'), { target: { value: 'other' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Load Sensors' }));

    await waitFor(() => {
      expect(vi.mocked(api.fetchJson)).toHaveBeenCalledWith(
        expect.stringContaining('/measurements/pm25/latest?'), { skipCache: true }
      );
    });

    const measurementCall = vi.mocked(api.fetchJson).mock.calls.find(
      ([path]) => typeof path === 'string' && path.startsWith('/measurements/pm25/latest?')
    );
    expect(measurementCall?.[0]).toContain('external_api_name=other');
  });

  it('opens a named native modal, handles cancellation, and restores the opener on close', async () => {
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    opener.focus();
    const onClose = vi.fn();
    const { unmount } = render(<DataStreamSelectionModal open onClose={onClose} onSelectPrimary={vi.fn()} onSelectOverlay={vi.fn()} />);
    const dialog = screen.getByRole('dialog', { name: 'Select Data Stream' });
    expect(dialog.tagName).toBe('DIALOG');
    expect(showModal).toHaveBeenCalledOnce();
    await screen.findByRole('option', { name: 'PM2.5' });
    screen.getByRole('button', { name: 'Close modal' }).focus();
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(screen.getByRole('button', { name: 'Close modal' })).toHaveFocus();
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    expect(onClose).toHaveBeenCalledOnce();
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it('treats sensors without an aggregation period as raw/latest streams', async () => {
    vi.mocked(api.fetchJson).mockImplementation(async (path: string) => {
      if (path === '/parameters') {
        return [{ code: 'pm25', display_name: 'PM2.5' }];
      }
      if (path.startsWith('/measurement-aggregation-capabilities')) return [{
        parameter_code: 'pm25', native_aggregation_code: null, native_status: 'unknown', diagnostics: [],
        supported_aggregations: [{
          result_aggregation_code: 'raw', display_name: 'Raw/latest', duration_minutes: null,
          is_rolling: false, capability_kind: 'native', rollup_path: ['raw'], supports_latest: true,
          supports_history: true, formatting_status: 'not_configured', display_precision: null,
        }],
      }];
      if (typeof path === 'string' && path.startsWith('/measurements/pm25/latest')) {
        return [
          {
            sensor_id: 123,
            parameter: 'pm25',
            parameter_name: 'PM2.5',
            unit: 'ug/m3',
            observed_at: '2026-04-20T18:00:00Z',
            sensor_aggregation_period: null,
            device: { device_id: 22, name: 'Raw Sensor', network: 'Other' },
          },
        ];
      }
      return [];
    });

    render(
      <DataStreamSelectionModal
        open={true}
        onClose={vi.fn()}
        onSelectPrimary={vi.fn()}
        onSelectOverlay={vi.fn()}
      />
    );

    fireEvent.change(await screen.findByLabelText('Select parameter'), { target: { value: 'pm25' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Load Sensors' }));

    expect((await screen.findAllByText('Raw/latest (native)')).length).toBeGreaterThan(0);
  });

  it('offers native, hourly, and daily choices for a two-minute measurement stream', async () => {
    const onSelectOverlay = vi.fn();
    vi.mocked(api.fetchJson).mockImplementation(async (path: string) => {
      if (path === '/parameters') return [{ code: 'pm25', display_name: 'PM2.5' }];
      if (path.startsWith('/measurement-aggregation-capabilities')) return [{
        parameter_code: 'pm25', native_aggregation_code: '2m', native_status: 'known', diagnostics: [],
        supported_aggregations: [
          { result_aggregation_code: '2m', display_name: '2 Minutes', duration_minutes: 2, is_rolling: false, capability_kind: 'native', rollup_path: ['2m'], supports_latest: true, supports_history: true, formatting_status: 'not_configured', display_precision: null },
          { result_aggregation_code: '1h', display_name: '1-hour average', duration_minutes: 60, is_rolling: false, capability_kind: 'direct_rollup', rollup_path: ['2m', '1h'], supports_latest: true, supports_history: true, formatting_status: 'configured', display_precision: 1 },
          { result_aggregation_code: '24h', display_name: '24-hour average', duration_minutes: 1440, is_rolling: false, capability_kind: 'chained_rollup', rollup_path: ['2m', '1h', '24h'], supports_latest: true, supports_history: true, formatting_status: 'configured', display_precision: 1 },
        ],
      }];
      if (path.startsWith('/measurements/pm25/latest')) return [{
        sensor_id: 123, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³',
        sensor_aggregation_period: '2m', device: { device_id: 22, name: 'Two-minute Sensor', network: 'PurpleAir' },
      }];
      return [];
    });
    render(<DataStreamSelectionModal open onClose={vi.fn()} onSelectPrimary={vi.fn()} onSelectOverlay={onSelectOverlay} existingSelections={[{ sensor_id: 123, parameter: "pm25", aggregate: "2m" }]} />);
    const parameterSelector = await screen.findByLabelText('Select parameter');
    await waitFor(() => expect(parameterSelector).not.toBeDisabled());
    fireEvent.change(parameterSelector, { target: { value: 'pm25' } });
    fireEvent.click(screen.getByLabelText('Add as Overlay'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Load Sensors' }));
    const selector = await screen.findByLabelText('Select aggregation for this datastream');
    expect([...selector.querySelectorAll('option')].map((option) => option.textContent)).toEqual([
      '2-minute (native)', '1-hour average', '24-hour average',
    ]);
    expect(screen.getByRole('button', { name: /Two-minute Sensor/ })).toBeDisabled();
    expect(selector.closest('button')).toBeNull();
    expect(selector).toBeEnabled();
    fireEvent.change(selector, { target: { value: '1h' } });
    fireEvent.click(screen.getByRole('button', { name: /Two-minute Sensor/ }));
    expect(onSelectOverlay).toHaveBeenCalledWith(123, 'pm25', { aggregate: '1h' });
  });

  it('clears a resolution filter that is unavailable for the selected source', async () => {
    vi.mocked(api.listPublicDataSources).mockResolvedValue([
      { name: 'PurpleAir', filter_value: 'purpleair' },
      { name: 'AirGradient', filter_value: 'airgradient' },
    ]);
    vi.mocked(api.fetchJson).mockImplementation(async (path: string) => {
      if (path === '/parameters') return [{ code: 'pm25', display_name: 'PM2.5' }];
      if (path.startsWith('/measurement-aggregation-capabilities')) {
        const isAirGradient = path.includes('source=airgradient');
        const nativeCode = isAirGradient ? '1m' : '2m';
        return [{
          parameter_code: 'pm25', native_aggregation_code: nativeCode, native_status: 'known', diagnostics: [],
          supported_aggregations: [{
            result_aggregation_code: nativeCode, display_name: nativeCode, duration_minutes: isAirGradient ? 1 : 2,
            is_rolling: false, capability_kind: 'native', rollup_path: [nativeCode], supports_latest: true,
            supports_history: true, formatting_status: 'not_configured', display_precision: null,
          }],
        }];
      }
      return [];
    });

    render(<DataStreamSelectionModal open onClose={vi.fn()} onSelectPrimary={vi.fn()} onSelectOverlay={vi.fn()} />);

    const parameterSelector = await screen.findByLabelText('Select parameter');
    await waitFor(() => expect(parameterSelector).not.toBeDisabled());
    fireEvent.change(parameterSelector, { target: { value: 'pm25' } });
    fireEvent.change(screen.getByLabelText('Select data source'), { target: { value: 'purpleair' } });
    const resolutionFilter = screen.getByLabelText('Filter by sensor time resolution');
    await waitFor(() => expect(screen.getByRole('option', { name: '2-minute' })).toBeInTheDocument());
    fireEvent.change(resolutionFilter, { target: { value: '2m' } });

    fireEvent.change(screen.getByLabelText('Select data source'), { target: { value: 'airgradient' } });

    await waitFor(() => expect(resolutionFilter).toHaveValue(''));
    expect(screen.queryByRole('option', { name: '2-minute' })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: '1-minute' })).toBeInTheDocument();
  });

  it('selects catalog-driven AQI products from the same modal and enforces the total-series cap', async () => {
    const onSelectAqi = vi.fn();
    const { rerender } = render(
      <DataStreamSelectionModal
        open={true}
        onClose={vi.fn()}
        onSelectPrimary={vi.fn()}
        onSelectOverlay={vi.fn()}
        onSelectAqi={onSelectAqi}
        currentSeriesCount={2}
        existingScaleGroupKeys={['measurement:ug/m3']}
        aqiDevices={[{ device_id: 42, name: 'AQI Station', friendly_name: null, timezone: 'UTC', network: 'OpenAQ', sensor_count: 2 }]}
        aqiStandards={[{
          standard_code: 'us_epa', display_name: 'U.S. EPA AQI', methodology_version: '2024', result_kind: 'numeric',
          averaging_minutes: 60, required_averaging_period: null, supported_parameter_codes: ['pm25'], normalized_unit: 'AQI',
          categories: [], default_product_code: 'us_epa.pm25.nowcast', is_default: true,
          products: [{ product_code: 'us_epa.pm25.nowcast', display_name: 'PM2.5 NowCast AQI', parameter_code: 'pm25',
            calculation_code: 'pm_nowcast', aggregation_period: '12h_nowcast', aggregation_display_name: 'NowCast', result_scope: 'pollutant',
            is_parameter_default: true, availability_status: 'available', availability_reason: null, history_status: 'available', history_interval: 'utc_hour' }],
        }]}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'AQI' }));
    fireEvent.click(await screen.findByRole('button', { name: /AQI Station/ }));
    expect(onSelectAqi).toHaveBeenCalledWith({ kind: 'aqi', standard_code: 'us_epa', product_code: 'us_epa.pm25.nowcast', device_id: 42 }, expect.objectContaining({ role: 'primary' }));

    rerender(
      <DataStreamSelectionModal
        open={true} onClose={vi.fn()} onSelectPrimary={vi.fn()} onSelectOverlay={vi.fn()} onSelectAqi={onSelectAqi}
        currentSeriesCount={6} existingScaleGroupKeys={['measurement:ug/m3']}
        aqiDevices={[{ device_id: 42, name: 'AQI Station', friendly_name: null, timezone: 'UTC', network: 'OpenAQ', sensor_count: 2 }]}
        aqiStandards={[{
          standard_code: 'us_epa', display_name: 'U.S. EPA AQI', methodology_version: '2024', result_kind: 'numeric', averaging_minutes: 60,
          required_averaging_period: null, supported_parameter_codes: ['pm25'], normalized_unit: 'AQI', categories: [],
          default_product_code: 'us_epa.pm25.nowcast', is_default: true, products: [{ product_code: 'us_epa.pm25.nowcast',
            display_name: 'PM2.5 NowCast AQI', parameter_code: 'pm25', calculation_code: 'pm_nowcast', aggregation_period: '12h_nowcast',
            aggregation_display_name: 'NowCast', result_scope: 'pollutant', is_parameter_default: true, availability_status: 'available',
            availability_reason: null, history_status: 'available', history_interval: 'utc_hour' }],
        }]}
      />
    );
    expect(screen.getByRole('button', { name: /AQI Station/ })).toBeDisabled();
    expect(screen.getByText('Six-series maximum reached')).toBeInTheDocument();
  });
});
