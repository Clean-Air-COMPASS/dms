import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import MapLibreMap from '../MapLibreMap';
import * as maplibregl from 'maplibre-gl';
import { fetchJson } from '../api';

vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>();
  return { ...actual, fetchJson: vi.fn() };
});

vi.mock('../SensorChart', () => ({
  default: (props: { timezoneMode?: string; data?: { sensor_id: number; data: unknown[]; _displayAggregate: string } | null }) => (
    <div data-testid="sensor-chart" data-timezone={props.timezoneMode}>
      {props.data
        ? `sensor:${props.data.sensor_id};points:${props.data.data.length};aggregation:${props.data._displayAggregate}`
        : 'empty'}
    </div>
  ),
}));

const mockedFetchJson = vi.mocked(fetchJson);

function createLatestMeasurement(sensorId: number, deviceId: number, deviceName: string) {
  return {
    measurement_id: sensorId,
    sensor_id: sensorId,
    value: 4.9,
    parameter: 'pm25',
    unit: 'µg/m³',
    observed_at: new Date().toISOString(),
    result_aggregation_code: '2m',
    native_aggregation_code: '2m',
    display_precision: 1,
    device: {
      device_id: deviceId,
      name: deviceName,
      friendly_name: deviceName,
      latitude: -22.9,
      longitude: -43.2,
      network: 'PurpleAir',
      timezone: 'America/Sao_Paulo',
    },
  };
}

function createHistoryResponse(sensorId: number, values: number[], aggregation = '2m') {
  const now = Date.now();
  return {
    sensor_id: sensorId,
    parameter: 'pm25',
    parameter_name: 'PM2.5',
    unit: 'µg/m³',
    device_name: 'LOA PUC RIO',
    device_timezone: 'America/Sao_Paulo',
    external_sensor_id: `purpleair-${sensorId}`,
    external_api: { name: 'PurpleAir' },
    native_aggregation_code: aggregation,
    result_aggregation_code: aggregation,
    display_precision: 1,
    data: values.map((value, index) => ({
      timestamp: new Date(now - (values.length - index) * 120_000).toISOString(),
      value,
      is_valid: true,
      failed_checks: [],
    })),
  };
}

function renderMap(props: React.ComponentProps<typeof MapLibreMap>) {
  return render(
    <MemoryRouter>
      <MapLibreMap {...props} />
    </MemoryRouter>,
  );
}

async function openMeasurementPanel() {
  const marker = await waitFor(() => {
    const candidate = document.querySelector('[title^="PM25"]');
    if (!candidate) throw new Error('Measurement marker has not rendered yet.');
    return candidate as HTMLElement;
  });
  fireEvent.click(marker);
  expect(await screen.findByRole('heading', { name: 'LOA PUC RIO' })).toBeInTheDocument();
}

describe('Map measurement history slide-outs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedFetchJson.mockReset();
  });

  it('temporarily hides mobile details for controls without clearing identity or refetching unchanged history', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
    HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
    mockedFetchJson.mockImplementation(async path => String(path).startsWith('/measurements/')
      ? [{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), value: String(path).includes('1h') ? 12.5 : 4.9 }]
      : createHistoryResponse(101, [4.9]));
    const onOpenControls = vi.fn();
    const props = { parameter: 'pm25', timeResolution: '2m', onOpenControls };
    const view = renderMap(props);
    await openMeasurementPanel();
    await screen.findByTestId('sensor-chart');
    fireEvent.click(screen.getByRole('button', { name: 'Map controls' }));
    expect(onOpenControls).toHaveBeenCalledOnce();
    const requestCount = mockedFetchJson.mock.calls.length;
    view.rerender(<MemoryRouter><MapLibreMap {...props} controlsOpen /></MemoryRouter>);
    expect(document.querySelector('dialog')).not.toHaveAttribute('open');
    view.rerender(<MemoryRouter><MapLibreMap {...props} /></MemoryRouter>);
    expect(screen.getByRole('heading', { name: 'LOA PUC RIO' })).toBeVisible();
    expect(mockedFetchJson).toHaveBeenCalledTimes(requestCount);
    view.rerender(<MemoryRouter><MapLibreMap {...props} controlsOpen timeResolution="1h" /></MemoryRouter>);
    await waitFor(() => expect(document.querySelector('.hero-value')).toHaveTextContent('12.5'));
    view.rerender(<MemoryRouter><MapLibreMap {...props} timeResolution="1h" /></MemoryRouter>);
    expect(screen.getByRole('heading', { name: 'LOA PUC RIO' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Close panel' }));
    view.rerender(<MemoryRouter><MapLibreMap {...props} controlsOpen /></MemoryRouter>);
    view.rerender(<MemoryRouter><MapLibreMap {...props} /></MemoryRouter>);
    expect(screen.queryByRole('heading', { name: 'LOA PUC RIO' })).not.toBeInTheDocument();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    document.querySelectorAll('[title^="PM25"], [title="RIO DEVICE"]').forEach((element) => element.remove());
  });

  it('loads the selected marker history with the map aggregation and renders populated points', async () => {
    const latestMeasurement = createLatestMeasurement(101, 11, 'LOA PUC RIO');
    mockedFetchJson.mockImplementation(async (path) => {
      const requestPath = String(path);
      if (requestPath.startsWith('/measurements/pm25/latest')) return [latestMeasurement];
      if (requestPath.startsWith('/sensors/101/history')) return createHistoryResponse(101, [3.2, 4.9]);
      throw new Error(`Unexpected request: ${requestPath}`);
    });

    renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();

    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent(
      'sensor:101;points:2;aggregation:2m',
    );
    expect(screen.getByTestId('sensor-chart')).toHaveAttribute('data-timezone', 'utc');
    const historyRequest = mockedFetchJson.mock.calls
      .map(([path]) => String(path))
      .find((path) => path.startsWith('/sensors/101/history'));
    expect(historyRequest).toContain('aggregation=2m');
    expect(historyRequest).toContain('include_qc=true');
    expect(historyRequest).toContain('hours=24');
    expect(historyRequest).not.toContain('start=');
    expect(historyRequest).not.toContain('end=');
  });

  it('shows backend averaging and exact time with all resolutions selected, and identifies missing QC status', async () => {
    const measurement = { ...createLatestMeasurement(105, 15, 'LOA PUC RIO'), observed_at: '2026-09-05T09:30:12Z' };
    mockedFetchJson.mockImplementation(async (path) => {
      if (String(path).startsWith('/measurements/pm25/latest')) return [measurement];
      if (String(path).startsWith('/sensors/105/history')) return createHistoryResponse(105, []);
      throw new Error(`Unexpected request: ${path}`);
    });
    renderMap({ parameter: 'pm25', timeResolution: '' });
    await openMeasurementPanel();
    expect(screen.getByText('2-minute')).toBeVisible();
    expect(screen.getByText('QC status').nextElementSibling).toHaveTextContent('Not provided');
    expect(document.querySelector('time')).toHaveAttribute('datetime', '2026-09-05T09:30:12.000Z');
  });

  it('refreshes marker and open history data without requiring a page reload', async () => {
    const latestMeasurement = createLatestMeasurement(104, 14, 'LOA PUC RIO');
    let latestRequests = 0;
    let historyRequests = 0;
    mockedFetchJson.mockImplementation(async (path) => {
      const requestPath = String(path);
      if (requestPath.startsWith('/measurements/pm25/latest')) {
        latestRequests += 1;
        return [{ ...latestMeasurement, value: latestRequests === 1 ? 4.9 : 6.1 }];
      }
      if (requestPath.startsWith('/sensors/104/history')) {
        historyRequests += 1;
        return createHistoryResponse(104, historyRequests === 1 ? [4.9] : [4.9, 6.1]);
      }
      throw new Error(`Unexpected request: ${requestPath}`);
    });

    renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();
    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent('points:1');

    fireEvent.click(await screen.findByRole('button', { name: 'Refresh now' }));

    await waitFor(() => expect(latestRequests).toBe(2));
    await waitFor(() => expect(historyRequests).toBe(2));
    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent('points:2');
    expect(document.querySelector('.hero-value')).toHaveTextContent('6.1');
    expect(screen.getByRole('heading', { name: 'LOA PUC RIO' })).toBeVisible();
  });

  it('shows the legitimate empty-window state for a successful empty history response', async () => {
    const latestMeasurement = createLatestMeasurement(102, 12, 'LOA PUC RIO');
    mockedFetchJson.mockImplementation(async (path) => {
      const requestPath = String(path);
      if (requestPath.startsWith('/measurements/pm25/latest')) return [latestMeasurement];
      if (requestPath.startsWith('/sensors/102/history')) return createHistoryResponse(102, []);
      throw new Error(`Unexpected request: ${requestPath}`);
    });

    renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();

    expect(await screen.findByText('No data available for the selected window')).toBeInTheDocument();
    expect(screen.queryByTestId('sensor-chart')).not.toBeInTheDocument();
  });

  it('explains a legitimate single eligible observation in the bounded preview', async () => {
    mockedFetchJson.mockImplementation(async (path) => {
      if (String(path).startsWith('/measurements/pm25/latest')) return [createLatestMeasurement(101, 11, 'LOA PUC RIO')];
      if (String(path).startsWith('/sensors/101/history')) return createHistoryResponse(101, [4.9]);
      throw new Error(`Unexpected request: ${path}`);
    });
    renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();
    expect(await screen.findByText('Only one eligible observation is available in the last 24 hours.')).toBeVisible();
    expect(screen.getByTestId('sensor-chart')).toHaveTextContent('points:1');
  });

  it('explains unsupported history separately from a network failure', async () => {
    const { ApiError } = await import('../apiError');
    mockedFetchJson.mockImplementation(async (path) => {
      if (String(path).startsWith('/measurements/pm25/latest')) return [createLatestMeasurement(101, 11, 'LOA PUC RIO')];
      throw new ApiError({ status: 400, errorCode: 'rolling_history_not_supported' });
    });
    renderMap({ parameter: 'pm25', timeResolution: 'rolling_24h' });
    await openMeasurementPanel();
    expect(await screen.findByRole('alert')).toHaveTextContent('This averaging period supports latest results only. Choose a different time resolution to view history.');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('uses backend capabilities to avoid requesting latest-only rolling history', async () => {
    mockedFetchJson.mockImplementation(async (path) => {
      if (String(path).startsWith('/measurements/pm25/latest')) return [{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), result_aggregation_code: 'rolling_24h' }];
      throw new Error(`Unexpected request: ${path}`);
    });
    renderMap({ parameter: 'pm25', timeResolution: 'rolling_24h', measurementAggregationCapabilities: [{
      parameter_code: 'pm25', native_aggregation_code: '2m', native_status: 'known', supported_aggregations: [{
        result_aggregation_code: 'rolling_24h', display_name: 'Rolling 24-hour', is_rolling: true,
        capability_kind: 'chained_rollup', rollup_path: ['2m', '1h', 'rolling_24h'], supports_latest: true,
        supports_history: false, formatting_status: 'configured',
      }],
    }] });
    await openMeasurementPanel();
    expect(await screen.findByRole('alert')).toHaveTextContent('supports latest results only');
    expect(mockedFetchJson.mock.calls.some(([path]) => String(path).includes('/history'))).toBe(false);
  });

  it('refreshes aggregation and clears pending history when changing layers and parameters', async () => {
    const pending = deferred<ReturnType<typeof createHistoryResponse>>();
    mockedFetchJson.mockImplementation(async (path) => {
      if (String(path).startsWith('/measurements/')) return [{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), result_aggregation_code: String(path).includes('aggregation=1h') ? '1h' : '2m' }];
      if (String(path).includes('aggregation=1h')) return createHistoryResponse(101, [12, 15], '1h');
      if (String(path).startsWith('/sensors/101/history')) return pending.promise;
      throw new Error(`Unexpected request: ${path}`);
    });
    const view = renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();
    expect(await screen.findByText('Loading measurement history…')).toBeVisible();
    view.rerender(<MemoryRouter><MapLibreMap parameter="pm25" timeResolution="1h" /></MemoryRouter>);
    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent('aggregation:1h');
    pending.resolve(createHistoryResponse(101, [99]));
    await waitFor(() => expect(screen.getByTestId('sensor-chart')).toHaveTextContent('points:2;aggregation:1h'));
    view.rerender(<MemoryRouter><MapLibreMap parameter="pm25" displayMode="us_epa" /></MemoryRouter>);
    await waitFor(() => expect(screen.queryByTestId('sensor-chart')).not.toBeInTheDocument());
    view.rerender(<MemoryRouter><MapLibreMap parameter="pm10" timeResolution="2m" /></MemoryRouter>);
    expect(screen.queryByTestId('sensor-chart')).not.toBeInTheDocument();
  });

  it('shows an error and retries the history request instead of showing the empty state', async () => {
    const latestMeasurement = createLatestMeasurement(103, 13, 'LOA PUC RIO');
    let historyAttempts = 0;
    mockedFetchJson.mockImplementation(async (path) => {
      const requestPath = String(path);
      if (requestPath.startsWith('/measurements/pm25/latest')) return [latestMeasurement];
      if (requestPath.startsWith('/sensors/103/history')) {
        historyAttempts += 1;
        if (historyAttempts === 1) throw new Error('history unavailable');
        return createHistoryResponse(103, [4.9]);
      }
      throw new Error(`Unexpected request: ${requestPath}`);
    });

    renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load measurement history.');
    expect(screen.queryByText('No data available for the selected window')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent('sensor:103;points:1;aggregation:2m');
    expect(historyAttempts).toBe(2);
  });

  it('updates the selected identity, value, unit, timestamps and chart together through every resolution', async () => {
    const values: Record<string, number> = { '2m': 2.5, '1h': 12.5, '24h': 22.5, rolling_24h: 32.5 };
    mockedFetchJson.mockImplementation(async (path) => {
      const url = new URL(String(path), 'http://localhost');
      const aggregation = url.searchParams.get('aggregation') || '2m';
      if (url.pathname.startsWith('/measurements/')) return [{
        ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), value: values[aggregation],
        measurement_id: aggregation === '2m' ? 999 : 0,
        unit: aggregation === '1h' ? 'ppb' : 'µg/m³', result_aggregation_code: aggregation,
        result_is_rolling: aggregation === 'rolling_24h', observed_at: '2026-10-09T04:50:00Z',
        interval_started_at: '2026-10-08T04:50:00Z', interval_ended_at: '2026-10-09T04:50:00Z',
        latest_source_observed_at: '2026-10-09T04:00:00Z',
        device: { ...createLatestMeasurement(101, 11, 'LOA PUC RIO').device, external_api: { name: 'Synthetic provider' } },
      }];
      if (aggregation === 'rolling_24h') {
        const { ApiError } = await import('../apiError');
        throw new ApiError({ status: 400, errorCode: 'rolling_history_not_supported' });
      }
      return createHistoryResponse(101, [values[aggregation]], aggregation);
    });
    const view = renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();
    for (const aggregation of ['2m', '1h', '24h', 'rolling_24h', '2m']) {
      view.rerender(<MemoryRouter><MapLibreMap parameter="pm25" timeResolution={aggregation} /></MemoryRouter>);
      await waitFor(() => expect(document.querySelector('.hero-value')).toHaveTextContent(String(values[aggregation])));
      expect(document.querySelector('.hero-unit')).toHaveTextContent(aggregation === '1h' ? 'ppb' : 'µg/m³');
      expect(screen.getByText('Synthetic provider')).toBeVisible();
      if (aggregation === 'rolling_24h') {
        expect(screen.getByText('Calculated at (UTC)')).toBeVisible();
        expect(screen.getByText('Latest source observation (UTC)').nextElementSibling).toHaveTextContent('04:00:00');
        expect(await screen.findByRole('alert')).toHaveTextContent('supports latest results only');
      } else {
        expect(await screen.findByTestId('sensor-chart')).toHaveTextContent(`aggregation:${aggregation}`);
        expect(screen.getByText('Observed at (UTC)')).toBeVisible();
      }
      expect(screen.getByRole('heading', { name: 'LOA PUC RIO' })).toBeVisible();
    }
  });

  it('ignores older latest responses and errors during rapid resolution changes and refreshes', async () => {
    const hourly = deferred<unknown[]>();
    const daily = deferred<unknown[]>();
    const refreshed = deferred<unknown[]>();
    let nativeRequests = 0;
    mockedFetchJson.mockImplementation(async (path) => {
      const url = new URL(String(path), 'http://localhost');
      const aggregation = url.searchParams.get('aggregation') || '2m';
      if (url.pathname.startsWith('/sensors/')) return createHistoryResponse(101, [7.5], aggregation);
      if (aggregation === '1h') return hourly.promise;
      if (aggregation === '24h') return daily.promise;
      nativeRequests += 1;
      return nativeRequests === 1 ? [createLatestMeasurement(101, 11, 'LOA PUC RIO')] : refreshed.promise;
    });
    const view = renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();
    view.rerender(<MemoryRouter><MapLibreMap parameter="pm25" timeResolution="1h" /></MemoryRouter>);
    expect(await screen.findByText('Loading measurements…')).toBeVisible();
    expect(document.querySelector('.hero-value')).toBeNull();
    view.rerender(<MemoryRouter><MapLibreMap parameter="pm25" timeResolution="24h" /></MemoryRouter>);
    view.rerender(<MemoryRouter><MapLibreMap parameter="pm25" timeResolution="2m" /></MemoryRouter>);
    await waitFor(() => expect(document.querySelector('.hero-value')).toHaveTextContent('4.9'));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }));
    await waitFor(() => expect(nativeRequests).toBe(2));
    await act(async () => {
      refreshed.resolve([{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), value: 7.5 }]);
    });
    await waitFor(() => expect(document.querySelector('.hero-value')).toHaveTextContent('7.5'));
    await act(async () => {
      hourly.resolve([{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), value: 99, result_aggregation_code: '1h' }]);
      daily.reject(new Error('stale daily failure'));
    });
    expect(document.querySelector('.hero-value')).toHaveTextContent('7.5');
    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent('aggregation:2m');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('preserves a missing sensor context without substituting another result, and recovers on refresh', async () => {
    let results = [createLatestMeasurement(101, 11, 'LOA PUC RIO')];
    mockedFetchJson.mockImplementation(async (path) => String(path).startsWith('/measurements/')
      ? results : createHistoryResponse(101, [4.9], '1h'));
    const view = renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();
    results = [{ ...createLatestMeasurement(102, 12, 'Other sensor'), value: 99, result_aggregation_code: '1h' }];
    view.rerender(<MemoryRouter><MapLibreMap parameter="pm25" timeResolution="1h" /></MemoryRouter>);
    expect(await screen.findByText('No measurement available for this sensor with the selected filters.')).toBeVisible();
    expect(document.querySelector('.hero-value')).toBeNull();
    expect(screen.queryByTestId('sensor-chart')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'LOA PUC RIO' })).toBeVisible();
    results = [{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), value: 8.5, result_aggregation_code: '1h' }];
    fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }));
    await waitFor(() => expect(document.querySelector('.hero-value')).toHaveTextContent('8.5'));
    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent('aggregation:1h');
  });

  it('does not let a pending older resolution replace a newer refresh', async () => {
    const first = deferred<unknown[]>();
    const second = deferred<unknown[]>();
    let requests = 0;
    mockedFetchJson.mockImplementation(async (path) => {
      if (String(path).startsWith('/measurements/')) {
        requests += 1;
        if (String(path).includes('aggregation=2m')) return first.promise;
        return requests === 2 ? [{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), result_aggregation_code: '1h' }]
          : second.promise;
      }
      return createHistoryResponse(101, [8.5], '1h');
    });
    const view = renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await waitFor(() => expect(requests).toBe(1));
    view.rerender(<MemoryRouter><MapLibreMap parameter="pm25" timeResolution="1h" /></MemoryRouter>);
    await openMeasurementPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }));
    await waitFor(() => expect(requests).toBe(3));
    await act(async () => second.resolve([{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), value: 8.5, result_aggregation_code: '1h' }]));
    await waitFor(() => expect(document.querySelector('.hero-value')).toHaveTextContent('8.5'));
    await act(async () => first.resolve([{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), value: 99 }]));
    expect(document.querySelector('.hero-value')).toHaveTextContent('8.5');
  });

  it('keeps source changes current and clears incompatible measurement selection on parameter and mode changes', async () => {
    mockedFetchJson.mockImplementation(async (path) => String(path).startsWith('/measurements/')
      ? [{ ...createLatestMeasurement(101, 11, 'LOA PUC RIO'), value: String(path).includes('purpleair') ? 8.5 : 4.9 }]
      : String(path).startsWith('/devices') ? [] : createHistoryResponse(101, [4.9]));
    const view = renderMap({ parameter: 'pm25', timeResolution: '2m' });
    await openMeasurementPanel();
    view.rerender(<MemoryRouter><MapLibreMap parameter="pm25" timeResolution="2m" sourceFilter="PurpleAir" /></MemoryRouter>);
    await waitFor(() => expect(document.querySelector('.hero-value')).toHaveTextContent('8.5'));
    for (const props of [{ parameter: 'pm10' }, { parameter: 'pm25', mode: 'devices' as const },
      { parameter: 'pm25', displayMode: 'us_epa' as const }, { parameter: 'pm25', displayMode: 'measurements' as const }]) {
      view.rerender(<MemoryRouter><MapLibreMap {...props} /></MemoryRouter>);
      await waitFor(() => expect(screen.queryByRole('heading', { name: 'LOA PUC RIO' })).not.toBeInTheDocument());
    }
  });

  it('replaces device history when the active sensor changes and ignores the stale response', async () => {
    const firstHistory = deferred<ReturnType<typeof createHistoryResponse>>();
    const secondHistory = deferred<ReturnType<typeof createHistoryResponse>>();
    const deviceId = 201;
    mockedFetchJson.mockImplementation((path) => {
      const requestPath = String(path);
      if (requestPath.startsWith('/devices/201/sensors')) {
        return Promise.resolve([
          { sensor_id: 301, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³', latest_value: 4.9, latest_observed_at: new Date().toISOString(), result_aggregation_code: '1h', native_aggregation_code: '1h' },
          { sensor_id: 302, parameter: 'pm10', parameter_name: 'PM10', unit: 'µg/m³', latest_value: 8.1, latest_observed_at: new Date().toISOString(), result_aggregation_code: '1h', native_aggregation_code: '1h' },
        ]);
      }
      if (requestPath.startsWith('/devices?parameter=pm25')) {
        return Promise.resolve([{ device_id: deviceId, name: 'RIO DEVICE', friendly_name: 'RIO DEVICE', latitude: -22.9, longitude: -43.2, network: 'PurpleAir', timezone: 'America/Sao_Paulo', sensor_count: 2 }]);
      }
      if (requestPath.startsWith('/measurements/pm25/latest')) {
        return Promise.resolve([{ observed_at: new Date().toISOString(), device: { device_id: deviceId } }]);
      }
      if (requestPath.startsWith('/sensors/301/history')) return firstHistory.promise;
      if (requestPath.startsWith('/sensors/302/history')) return secondHistory.promise;
      throw new Error(`Unexpected request: ${requestPath}`);
    });

    renderMap({ parameter: 'pm25', mode: 'devices', timeResolution: '1h' });
    const deviceMarker = await waitFor(() => {
      const candidate = document.querySelector('[title="RIO DEVICE"]');
      if (!candidate) throw new Error('Device marker has not rendered yet.');
      return candidate as HTMLElement;
    });
    fireEvent.click(deviceMarker);
    expect(await screen.findByRole('button', { name: 'PM10' })).toBeInTheDocument();
    await waitFor(() => expect(
      mockedFetchJson.mock.calls.some(([path]) => String(path).startsWith('/sensors/301/history')),
    ).toBe(true));

    fireEvent.click(screen.getByRole('button', { name: 'PM10' }));
    await waitFor(() => expect(
      mockedFetchJson.mock.calls.some(([path]) => String(path).startsWith('/sensors/302/history')),
    ).toBe(true));

    firstHistory.resolve(createHistoryResponse(301, [4.9], '1h'));
    await waitFor(() => expect(screen.queryByTestId('sensor-chart')).not.toBeInTheDocument());
    expect(screen.getByText('Loading measurement history…')).toHaveAttribute('role', 'status');

    secondHistory.resolve(createHistoryResponse(302, [8.1], '1h'));
    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent('sensor:302;points:1;aggregation:1h');
    expect(screen.getByTestId('sensor-chart')).toHaveAttribute('data-timezone', 'utc');
  });
  it('opens mobile details as a modal and closes without moving or remounting the map', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
    HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
    mockedFetchJson.mockImplementation(async path => {
      if (String(path).startsWith('/measurements/pm25/latest')) return [createLatestMeasurement(109, 19, 'LOA PUC RIO')];
      if (String(path).startsWith('/sensors/109/history')) return createHistoryResponse(109, [4.9]);
      throw new Error(`Unexpected request: ${path}`);
    });
    renderMap({ parameter: 'pm25' });
    await openMeasurementPanel();
    expect(await screen.findByRole('dialog', { name: 'Device details' })).toHaveAttribute('open');
    expect(document.body.style.overflow).toBe('hidden');
    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent('points:1');
    const map = vi.mocked(maplibregl.Map).mock.results[0].value;
    map.fitBounds.mockClear(); map.flyTo.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Close panel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe('');
    expect(map.fitBounds).not.toHaveBeenCalled(); expect(map.flyTo).not.toHaveBeenCalled();
    expect(map.remove).not.toHaveBeenCalled();
    await waitFor(() => expect(document.querySelector('[title^="PM25"]')).toHaveFocus());
  });

  it('preserves the active device sensor on refresh and never substitutes a missing sensor', async () => {
    const sensor = (sensorId: number, parameter: string, value: number) => ({ sensor_id: sensorId, parameter,
      parameter_name: parameter === 'pm25' ? 'PM2.5' : 'PM10', latest_value: value, latest_observed_at: '2026-10-09T04:00:00Z',
      unit: 'µg/m³', result_aggregation_code: '1h', native_aggregation_code: '2m' });
    let rows = [sensor(301, 'pm25', 4.9), sensor(302, 'pm10', 8.1)];
    mockedFetchJson.mockImplementation(async (path) => {
      if (String(path).startsWith('/devices/201/sensors')) return rows;
      if (String(path).startsWith('/devices?')) return [{ device_id: 201, name: 'RIO DEVICE', latitude: 0, longitude: 0 }];
      const id = String(path).startsWith('/sensors/302') ? 302 : 301;
      return createHistoryResponse(id, [8.1], '1h');
    });
    renderMap({ parameter: 'pm25', mode: 'devices', timeResolution: '1h' });
    await waitFor(() => expect(document.querySelector('[title="RIO DEVICE"]')).not.toBeNull());
    fireEvent.click(document.querySelector('[title="RIO DEVICE"]')!);
    fireEvent.click(await screen.findByRole('button', { name: 'PM10' }));
    await waitFor(() => expect(document.querySelector('.hero-value')).toHaveTextContent('8.1'));
    rows = [sensor(301, 'pm25', 4.9), sensor(302, 'pm10', 9.4)];
    fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }));
    await waitFor(() => expect(document.querySelector('.hero-value')).toHaveTextContent('9.4'));
    expect(await screen.findByTestId('sensor-chart')).toHaveTextContent('sensor:302;');
    rows = [sensor(301, 'pm25', 4.9)];
    fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }));
    expect(await screen.findByText('No measurement available for this sensor with the selected filters.')).toBeVisible();
    expect(document.querySelector('.hero-value')).toBeNull();
    expect(screen.queryByTestId('sensor-chart')).not.toBeInTheDocument();
  });

});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}
