import { BrowserRouter, Link } from 'react-router-dom';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

import App from '../App';
import * as api from '../api';
import i18n from '../i18n';
import type { QuickDownloadProps } from '../components/QuickDownload';

const mapLifecycle = vi.hoisted(() => ({
  mounted: vi.fn(),
  unmounted: vi.fn(),
}));

function mockStartupFetch(setupStatus: {
  is_setup_required: boolean;
  has_users: boolean;
  default_language_code?: string | null;
}) {
  return vi.fn().mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith('/health/readiness')) {
      return new Response(JSON.stringify({ status: 'ready' }), { status: 200 });
    }
    if (url.endsWith('/setup/status')) {
      return new Response(JSON.stringify(setupStatus), { status: 200 });
    }
    throw new Error(`Unexpected startup request: ${url}`);
  });
}

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchJson: vi.fn(),
    listPublicDataSources: vi.fn(),
  };
});

vi.mock('../MapLibreMap', async () => {
  const { useEffect } = await import('react');

  return {
    default: function MockMapLibreMap({ sourceFilter, displayMode, europeanStandardMetadata, mode, parameter, timeResolution, selectedAirQualityIndexProduct }: { sourceFilter?: string; displayMode?: string; europeanStandardMetadata?: { standard_code: string } | null; mode?: string; parameter?: string; timeResolution?: string; selectedAirQualityIndexProduct?: { product_code: string } | null }) {
      useEffect(() => {
        mapLifecycle.mounted();
        return () => mapLifecycle.unmounted();
      }, []);

      return (
        <div>
          <div data-testid="map-source-filter">{sourceFilter || ''}</div>
          <div data-testid="map-display-mode">{displayMode || ''}</div>
          <div data-testid="map-data-layer-mode">{mode || ''}</div>
          <div data-testid="map-standard-code">{europeanStandardMetadata?.standard_code || ''}</div>
          <div data-testid="map-parameter">{parameter || ''}</div>
          <div data-testid="map-time-resolution">{timeResolution || ''}</div>
          <div data-testid="map-aqi-product">{selectedAirQualityIndexProduct?.product_code || ''}</div>
        </div>
      );
    },
  };
});

vi.mock('../LocationSearch', () => ({ default: () => null }));
vi.mock('../components/UserMenu', () => ({ default: () => null }));
vi.mock('../components/DateTimeRangePicker', () => ({ default: () => null }));
vi.mock('../components/QuickDownload', () => ({
  default: ({ iconOnly, mode, standardCode, productCode, aqiParameterCode, source }: QuickDownloadProps) => (
    <div data-testid="quick-download" data-icon-only={String(iconOnly ?? false)}
      data-mode={mode} data-standard={standardCode} data-product={productCode}
      data-parameter={aqiParameterCode} data-source={source} />
  ),
}));
vi.mock('../LandingPage', () => ({ default: () => <div>Landing<Link to="/map">Map</Link></div> }));
vi.mock('../LoginPage', () => ({ default: () => <div>Login</div> }));
vi.mock('../Analytics', () => ({ default: () => <div>Analytics</div> }));
vi.mock('../LoadingSplash', () => ({ default: () => <div>Loading</div> }));
vi.mock('../SetupWizard', () => ({
  default: ({ initialAdminCreated }: { initialAdminCreated?: boolean }) => (
    <div data-testid="setup-wizard" data-admin-created={String(initialAdminCreated ?? false)}>Setup</div>
  ),
}));
vi.mock('../qc/AdminQcOverview', () => ({ default: () => <div>AdminQcOverview</div> }));
vi.mock('../qc/AdminQcParameterDetail', () => ({ default: () => <div>AdminQcParameterDetail</div> }));
vi.mock('../qc/AdminQcSourcePolicy', () => ({ default: () => <div>AdminQcSourcePolicy</div> }));
vi.mock('../qc/AdminQcExtensions', () => ({ default: () => <div>AdminQcExtensions</div> }));
vi.mock('../qc/AdminQcSensorSearch', () => ({ default: () => <div>AdminQcSensorSearch</div> }));
vi.mock('../qc/AdminQcSensorPolicy', () => ({ default: () => <div>AdminQcSensorPolicy</div> }));
vi.mock('../AdminSourcesList', () => ({ default: () => <div>AdminSourcesList</div> }));
vi.mock('../AdminSourceDetail', () => ({ default: () => <div>AdminSourceDetail</div> }));
vi.mock('../AdminEventLog', () => ({ default: () => <div>AdminEventLog</div> }));
vi.mock('../AdminDevicesList', () => ({ default: () => <div>AdminDevicesList</div> }));
vi.mock('../AdminDeviceEditor', () => ({ default: () => <div>AdminDeviceEditor</div> }));
vi.mock('../AdminDeviceNew', () => ({ default: () => <div>AdminDeviceNew</div> }));
vi.mock('../AdminDeviceNewOpenAQ', () => ({ default: () => <div>AdminDeviceNewOpenAQ</div> }));
vi.mock('../AdminUsersList', () => ({ default: () => <div>AdminUsersList</div> }));
vi.mock('../AdminUserDetail', () => ({ default: () => <div>AdminUserDetail</div> }));
vi.mock('../AdminUserNew', () => ({ default: () => <div>AdminUserNew</div> }));
vi.mock('../AdminHome', () => ({ default: () => <div>AdminHome</div> }));
vi.mock('../AdminCsvUpload', () => ({ default: () => <div>AdminCsvUpload</div> }));
vi.mock('../auth', () => ({
  RequireAuth: ({ children }: { children: ReactNode }) => <>{children}</>,
  RequireScope: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAuth: () => ({ isAuthenticated: false, isLoading: false }),
}));

describe('App map source filter', () => {
  afterEach(() => { vi.unstubAllGlobals(); });
  beforeEach(() => {
    vi.clearAllMocks();

    window.history.replaceState({}, '', '/map');

    vi.stubGlobal('fetch', mockStartupFetch({
      is_setup_required: false,
      has_users: true,
    }));

    vi.mocked(api.fetchJson).mockImplementation(async (path: string) => {
      if (path === '/parameters') {
        return [
          { code: 'pm25', display_name: 'PM2.5' },
          { code: 'temperature', display_name: 'Temperature' },
        ];
      }
      if (path === '/version') {
        return { postgres_version: 'test' };
      }
      if (path.startsWith('/measurement-aggregation-capabilities')) {
        return [
          {
            parameter_code: 'pm25', native_aggregation_code: '1m', native_status: 'known',
            supported_aggregations: [
              { result_aggregation_code: '1m', display_name: '1 Minute', duration_minutes: 1, is_rolling: false, capability_kind: 'native', rollup_path: ['1m'], supports_latest: true, supports_history: true, formatting_status: 'not_configured', display_precision: null },
              { result_aggregation_code: '1h', display_name: 'Hourly', duration_minutes: 60, is_rolling: false, capability_kind: 'direct_rollup', rollup_path: ['1m', '1h'], supports_latest: true, supports_history: true, formatting_status: 'not_configured', display_precision: null },
              { result_aggregation_code: '24h', display_name: 'Daily', duration_minutes: 1440, is_rolling: false, capability_kind: 'chained_rollup', rollup_path: ['1m', '1h', '24h'], supports_latest: true, supports_history: true, formatting_status: 'not_configured', display_precision: null },
            ], diagnostics: [],
          },
          {
            parameter_code: 'temperature', native_aggregation_code: '1m', native_status: 'known',
            supported_aggregations: [
              { result_aggregation_code: '1m', display_name: '1 Minute', duration_minutes: 1, is_rolling: false, capability_kind: 'native', rollup_path: ['1m'], supports_latest: true, supports_history: true, formatting_status: 'not_configured', display_precision: null },
            ], diagnostics: [],
          },
        ];
      }
      if (path === '/air-quality-index/standards') {
        return [
          {
            standard_code: 'us_epa', display_name: 'U.S. EPA AQI', methodology_version: 'test',
            result_kind: 'numeric', averaging_minutes: null, required_averaging_period: null,
            supported_parameter_codes: ['pm25', 'pm10'], normalized_unit: 'AQI', categories: [],
            default_product_code: 'us_epa.pm25.nowcast', is_default: true,
            products: [
              {
                product_code: 'us_epa.pm25.nowcast', display_name: 'PM2.5 NowCast AQI',
                parameter_code: 'pm25', calculation_code: 'pm_nowcast', aggregation_period: '12h_nowcast',
                aggregation_display_name: 'NowCast from 12 completed hourly slots', result_scope: 'pollutant', is_parameter_default: true,
                availability_status: 'available', availability_reason: null,
              },
              {
                product_code: 'us_epa.pm10.nowcast', display_name: 'PM10 NowCast AQI',
                parameter_code: 'pm10', calculation_code: 'pm_nowcast', aggregation_period: '12h_nowcast',
                aggregation_display_name: 'NowCast from 12 completed hourly slots', result_scope: 'pollutant', is_parameter_default: true,
                availability_status: 'available', availability_reason: null,
              },
              {
                product_code: 'us_epa.pm25.completed_day', display_name: 'U.S. EPA PM2.5 Completed-Day AQI',
                parameter_code: 'pm25', calculation_code: 'pm_completed_local_day', aggregation_period: 'completed_local_day',
                aggregation_display_name: 'Completed Day', result_scope: 'pollutant', is_parameter_default: false,
                availability_status: 'available', availability_reason: null, product_kind: 'completed_day',
              },
              {
                product_code: 'us_epa.pm10.completed_day', display_name: 'U.S. EPA PM10 Completed-Day AQI',
                parameter_code: 'pm10', calculation_code: 'pm_completed_local_day', aggregation_period: 'completed_local_day',
                aggregation_display_name: 'Completed Day', result_scope: 'pollutant', is_parameter_default: false,
                availability_status: 'available', availability_reason: null, product_kind: 'completed_day',
              },
            ],
          },
          {
            standard_code: 'eea_european', display_name: 'European Air Quality Index',
            methodology_version: 'eea_2024_bands', result_kind: 'categorical', averaging_minutes: 60,
            required_averaging_period: '1h', supported_parameter_codes: ['pm25'],
            normalized_unit: 'µg/m³', categories: [],
            default_product_code: 'eea_european.overall.hourly', is_default: false,
            products: [
              {
                product_code: 'eea_european.overall.hourly', display_name: 'Overall hourly European AQI',
                parameter_code: null, calculation_code: 'worst_available_category', aggregation_period: '1h',
                aggregation_display_name: '1-hour average', result_scope: 'overall', is_parameter_default: false,
                availability_status: 'available', availability_reason: null,
              },
              {
                product_code: 'eea_european.pm25.hourly', display_name: 'PM2.5 hourly European AQI',
                parameter_code: 'pm25', calculation_code: 'hourly_category', aggregation_period: '1h',
                aggregation_display_name: '1-hour average', result_scope: 'pollutant', is_parameter_default: false,
                availability_status: 'available', availability_reason: null,
              },
            ],
          },
        ];
      }
      return [];
    });

    vi.mocked(api.listPublicDataSources).mockResolvedValue([
      { name: 'AirGradient', filter_value: 'airgradient' },
      { name: 'OpenAQ', filter_value: 'openaq' },
      { name: 'Other', filter_value: 'other' },
    ]);
  });

  it('keeps the fresh-install URL clean while setup is required', async () => {
    window.history.replaceState({}, '', '/');
    vi.stubGlobal('fetch', mockStartupFetch({
      is_setup_required: true,
      has_users: false,
    }));

    render(<BrowserRouter><App /></BrowserRouter>);

    expect(await screen.findByText('Setup')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/');
    expect(window.location.search).toBe('');
  });

  it('resumes setup after the administrator step when a user already exists', async () => {
    vi.stubGlobal('fetch', mockStartupFetch({
      is_setup_required: true,
      has_users: true,
    }));

    render(<BrowserRouter><App /></BrowserRouter>);

    expect(await screen.findByTestId('setup-wizard')).toHaveAttribute('data-admin-created', 'true');
  });

  it.each([null, 'invalid'])(
    'does not setup-gate a completed installation when the language is %s',
    async (defaultLanguageCode) => {
      vi.stubGlobal('fetch', mockStartupFetch({
        is_setup_required: false,
        has_users: true,
        default_language_code: defaultLanguageCode,
      }));

      render(<BrowserRouter><App /></BrowserRouter>);

      expect(await screen.findByTestId('map-data-layer-mode')).toBeInTheDocument();
      expect(screen.queryByText('Setup')).not.toBeInTheDocument();
    },
  );

  it('does not rewrite the URL while setup status is still loading', async () => {
    window.history.replaceState({}, '', '/');
    let resolveSetupStatus: (response: Response) => void = () => undefined;
    const setupStatus = new Promise<Response>((resolve) => {
      resolveSetupStatus = resolve;
    });
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input) => {
      if (String(input).endsWith('/health/readiness')) {
        return Promise.resolve(new Response(JSON.stringify({ status: 'ready' }), { status: 200 }));
      }
      return setupStatus;
    }));

    render(<BrowserRouter><App /></BrowserRouter>);

    expect(screen.getByRole('heading', { name: 'CompassAQ is starting' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/');
    expect(window.location.search).toBe('');

    resolveSetupStatus(new Response(JSON.stringify({ is_setup_required: true, has_users: false }), { status: 200 }));
    expect(await screen.findByText('Setup')).toBeInTheDocument();
    expect(window.location.search).toBe('');
  });

  it('checks readiness before setup status', async () => {
    const fetchMock = mockStartupFetch({ is_setup_required: true, has_users: false });
    vi.stubGlobal('fetch', fetchMock);

    render(<BrowserRouter><App /></BrowserRouter>);

    expect(await screen.findByText('Setup')).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      '/api/health/readiness',
      '/api/setup/status',
    ]);
  });

  it('shows startup while readiness is unavailable and continues automatically when ready', async () => {
    vi.useFakeTimers();
    try {
      let readinessCalls = 0;
      const fetchMock = vi.fn().mockImplementation(async (input) => {
        const url = String(input);
        if (url.endsWith('/health/readiness')) {
          readinessCalls += 1;
          return readinessCalls === 1
            ? new Response(JSON.stringify({ status: 'not_ready' }), { status: 503 })
            : new Response(JSON.stringify({ status: 'ready' }), { status: 200 });
        }
        return new Response(
          JSON.stringify({ is_setup_required: true, has_users: false }),
          { status: 200 },
        );
      });
      vi.stubGlobal('fetch', fetchMock);

      render(<BrowserRouter><App /></BrowserRouter>);

      expect(screen.getByRole('heading', { name: 'CompassAQ is starting' })).toBeInTheDocument();
      expect(screen.queryByText('Setup')).not.toBeInTheDocument();
      await act(async () => {});
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(screen.getByText('Setup')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('never assumes setup is complete when setup status is unavailable', async () => {
    const fetchMock = vi.fn().mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/health/readiness')) {
        return new Response(JSON.stringify({ status: 'ready' }), { status: 200 });
      }
      return new Response(JSON.stringify({ message: 'internal details' }), { status: 500 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<BrowserRouter><App /></BrowserRouter>);

    expect(await screen.findByRole('heading', { name: 'CompassAQ is starting' })).toBeInTheDocument();
    expect(screen.queryByText('Setup')).not.toBeInTheDocument();
    expect(screen.queryByText('Login')).not.toBeInTheDocument();
    expect(screen.queryByTestId('map-data-layer-mode')).not.toBeInTheDocument();
    expect(screen.queryByText('internal details')).not.toBeInTheDocument();
  });

  it('keeps the app gated after persistent failure and Retry checks immediately', async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: 'not_ready' }), { status: 503 }),
      );
      vi.stubGlobal('fetch', fetchMock);

      render(<BrowserRouter><App /></BrowserRouter>);
      await act(async () => {});
      for (const delay of [1000, 2000, 4000, 5000, 5000, 5000]) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(delay);
        });
      }

      expect(screen.getByRole('heading', { name: 'CompassAQ could not finish starting' })).toBeInTheDocument();
      expect(screen.queryByText('Setup')).not.toBeInTheDocument();
      expect(screen.queryByText('Login')).not.toBeInTheDocument();
      expect(screen.queryByTestId('map-data-layer-mode')).not.toBeInTheDocument();
      expect(fetchMock.mock.calls.every(([input]) => String(input).endsWith('/health/readiness'))).toBe(true);

      const callCountBeforeRetry = fetchMock.mock.calls.length;
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
      await act(async () => {});
      expect(fetchMock.mock.calls.length).toBe(callCountBeforeRetry + 1);
      expect(screen.getByRole('heading', { name: 'CompassAQ is starting' })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps normal map-state URL synchronization after setup is complete', async () => {
    window.history.replaceState({}, '', '/map');

    render(<BrowserRouter><App /></BrowserRouter>);

    await screen.findByLabelText('Layer');
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.has('mode')).toBe(false);
      expect(params.has('display_mode')).toBe(false);
      expect(params.has('recency')).toBe(false);
    });
  });

  it.each(['en', 'es'])('navigates the Map brand to Home with normal link behavior in %s', async (language) => {
    try {
      await i18n.changeLanguage(language);
      window.history.replaceState({}, '', '/map?mode=devices&parameter=pm25&source=openaq');
      const user = userEvent.setup();

      render(<BrowserRouter><App /></BrowserRouter>);

      const brandLink = await screen.findByRole('link', { name: 'COMPASS' });
      expect(brandLink).toHaveAttribute('href', '/');
      expect(brandLink).toHaveClass('overlay-title');

      await user.tab();
      expect(brandLink).toHaveFocus();
      await user.keyboard('{Enter}');

      expect(await screen.findByText('Landing')).toBeInTheDocument();
      expect(window.location.pathname + window.location.search + window.location.hash).toBe('/');
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it.each(['', '?mode=devices&display_mode=measurements&recency=24h'])('keeps Home clean after initialization: %s', async (search) => {
    window.history.replaceState({}, '', `/${search}`);
    render(<BrowserRouter><App /></BrowserRouter>);
    await screen.findByText('Landing');
    await waitFor(() => expect(api.listPublicDataSources).toHaveBeenCalled());
    expect(window.location.pathname + window.location.search).toBe('/');
    for (const key of ['mode', 'display_mode', 'recency']) {
      expect(new URLSearchParams(window.location.search).has(key)).toBe(false);
    }
    fireEvent.click(screen.getByRole('link', { name: 'Map' }));
    expect(await screen.findByLabelText('Layer')).toHaveValue('devices');
    expect(screen.getByLabelText('Parameter')).toHaveValue('');
    expect(screen.queryByLabelText('Time window presets')).not.toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe('/map');
  });

  it('preserves unrelated landing query parameters and hashes', async () => {
    window.history.replaceState({}, '', '/?utm_source=newsletter&mode=devices&parameter=pm25&recency=1h#about');
    render(<BrowserRouter><App /></BrowserRouter>);
    await screen.findByText('Landing');
    expect(window.location.search).toBe('?utm_source=newsletter');
    expect(window.location.hash).toBe('#about');
    fireEvent.click(screen.getByRole('link', { name: 'Map' }));
    expect(await screen.findByLabelText('Parameter')).toHaveValue('');
    expect(screen.queryByLabelText('Time window presets')).not.toBeInTheDocument();
  });

  it('restores Map deep links through Home and browser history without rewrite loops', async () => {
    window.history.replaceState({}, '', '/map?parameter=pm25&recency=1h');
    render(<BrowserRouter><Link to="/">Home</Link><App /></BrowserRouter>);
    expect(await screen.findByLabelText('Parameter')).toHaveValue('pm25');
    fireEvent.click(screen.getByRole('link', { name: 'Home' }));
    await screen.findByText('Landing');
    expect(window.location.pathname + window.location.search).toBe('/');
    fireEvent.click(screen.getByRole('link', { name: 'Map' }));
    await waitFor(() => expect(screen.getByLabelText('Parameter')).toHaveValue(''));
    await act(async () => window.history.back());
    await screen.findByText('Landing');
    await act(async () => window.history.back());
    await waitFor(() => expect(screen.getByLabelText('Parameter')).toHaveValue('pm25'));
    expect(screen.queryByLabelText('Time window presets')).not.toBeInTheDocument();
    await act(async () => window.history.forward());
    await screen.findByText('Landing');
    expect(window.location.pathname + window.location.search).toBe('/');
    const replace = vi.spyOn(window.history, 'replaceState');
    await act(async () => {});
    expect(replace).not.toHaveBeenCalled();
    replace.mockRestore();
  });

  it('continues to read and normalize explicit map deep links after setup', async () => {
    window.history.replaceState({}, '', '/map?mode=devices&display_mode=eea_european');

    render(<BrowserRouter><App /></BrowserRouter>);

    await waitFor(() => {
      expect(screen.getByTestId('map-display-mode')).toHaveTextContent('eea_european');
      expect(screen.getByTestId('map-data-layer-mode')).toHaveTextContent('pollutants');
    });

    await waitFor(() => expect(new URLSearchParams(window.location.search).get('product_code')).toBe('eea_european.overall.hourly'));
    const params = new URLSearchParams(window.location.search);
    expect(params.get('display_mode')).toBe('eea_european');
    expect(params.get('standard_code')).toBe('eea_european');
    expect(params.get('product_code')).toBe('eea_european.overall.hourly');
  });

  it('shows Other in the map source dropdown and passes it through the normal source filter path', async () => {
    render(
      <BrowserRouter>
        <App />
      </BrowserRouter>,
    );

    const sourceSelect = await screen.findByLabelText('Data source filter');
    expect(screen.getByRole('option', { name: 'AirGradient' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'OpenAQ' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Other' })).toBeInTheDocument();

    await waitFor(() => expect(sourceSelect).toBeEnabled());
    fireEvent.change(sourceSelect, { target: { value: 'other' } });

    await waitFor(() => {
      expect(screen.getByTestId('map-source-filter')).toHaveTextContent('other');
    });

    expect(window.location.search).toContain('source=other');
  });

  it('normalizes mixed-case source deep links to the visible source option', async () => {
    window.history.replaceState({}, '', '/map?source=PurpleAir');
    vi.mocked(api.listPublicDataSources).mockResolvedValue([
      { name: 'PurpleAir', filter_value: 'purpleair' },
    ]);

    render(<BrowserRouter><App /></BrowserRouter>);

    await waitFor(() => {
      expect(screen.getByLabelText('Data source filter')).toHaveValue('purpleair');
      expect(screen.getByTestId('map-source-filter')).toHaveTextContent('purpleair');
      expect(new URLSearchParams(window.location.search).get('source')).toBe('purpleair');
    });
  });

  it('does not render Admin as a standalone Map toolbar link', async () => {
    render(<BrowserRouter><App /></BrowserRouter>);

    await screen.findByLabelText('Layer');

    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument();
  });

  it('tolerates and removes every legacy Map time key without restoring controls', async () => {
    window.history.replaceState({}, '', '/map?recency=1h&start=2020-01-01&until=2020-02-01&time_start=2019-01-01&time_end=2019-02-01');
    render(<BrowserRouter><App /></BrowserRouter>);
    await screen.findByLabelText('Layer');
    for (const layer of ['devices', 'measurements', 'aqi', 'devices']) {
      fireEvent.change(screen.getByLabelText('Layer'), { target: { value: layer } });
      await waitFor(() => {
        for (const key of ['recency', 'start', 'until', 'time_start', 'time_end']) {
          expect(new URLSearchParams(window.location.search).has(key)).toBe(false);
        }
      });
      expect(screen.queryByLabelText('Time window presets')).not.toBeInTheDocument();
      expect(screen.queryByLabelText('Open custom date range picker')).not.toBeInTheDocument();
      expect(Boolean(screen.queryByLabelText('Time resolution'))).toBe(layer === 'measurements');
    }
  });

  it('uses one Layer dropdown with Devices, Measurements, and AQI', async () => {
    render(<BrowserRouter><App /></BrowserRouter>);

    const layerSelect = await screen.findByLabelText('Layer');
    expect(layerSelect).toHaveValue('devices');
    expect(screen.getByRole('option', { name: 'Devices' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Measurements' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'AQI' })).toBeInTheDocument();
    expect(screen.getByLabelText('Parameter')).toHaveValue('');
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'All Parameters' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'All Time Resolutions' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset view' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Analytics' })).toBeInTheDocument();
  });

  it('shows grouped U.S. and European products with product-specific time resolution', async () => {
    render(<BrowserRouter><App /></BrowserRouter>);
    await screen.findByLabelText('Layer');
    await act(async () => {});
    fireEvent.change(screen.getByLabelText('Layer'), { target: { value: 'aqi' } });

    const productSelect = screen.getByLabelText('AQI product');
    expect(productSelect).toHaveValue('us_epa.pm25.nowcast');
    expect(screen.getByRole('group', { name: 'U.S. EPA AQI' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'European Air Quality Index' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'PM10 NowCast AQI' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'U.S. EPA PM2.5 Completed-Day AQI' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'U.S. EPA PM10 Completed-Day AQI' })).toBeInTheDocument();

    fireEvent.change(productSelect, { target: { value: 'us_epa.pm25.completed_day' } });
    await waitFor(() => {
      expect(screen.getByTestId('map-aqi-product')).toHaveTextContent('us_epa.pm25.completed_day');
    });
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();

    fireEvent.change(productSelect, { target: { value: 'us_epa.pm10.nowcast' } });
    await waitFor(() => {
      expect(screen.getByTestId('map-aqi-product')).toHaveTextContent('us_epa.pm10.nowcast');
    });
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();

    fireEvent.change(productSelect, { target: { value: 'us_epa.pm10.completed_day' } });
    await waitFor(() => {
      expect(screen.getByTestId('map-aqi-product')).toHaveTextContent('us_epa.pm10.completed_day');
    });
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();

    fireEvent.change(productSelect, { target: { value: 'eea_european.pm25.hourly' } });
    await waitFor(() => {
      expect(screen.getByTestId('map-display-mode')).toHaveTextContent('eea_european');
      expect(screen.getByTestId('map-aqi-product')).toHaveTextContent('eea_european.pm25.hourly');
    });
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();
    expect(screen.getByText('Latest completed UTC hour')).toBeInTheDocument();
    expect(window.location.search).toContain('standard_code=eea_european');
  });

  it.each([
    ['display_mode=eea_european', 'eea_european', 'eea_european.overall.hourly'],
    ['standard_code=eea_european', 'eea_european', 'eea_european.overall.hourly'],
    ['display_mode=us_epa', 'us_epa', 'us_epa.pm25.nowcast'],
  ])('normalizes the existing URL field %s into the AQI layer', async (query, expectedMode, expectedProduct) => {
    window.history.replaceState({}, '', `/map?mode=devices&${query}`);
    render(<BrowserRouter><App /></BrowserRouter>);

    await waitFor(() => {
      expect(screen.getByLabelText('Layer')).toHaveValue('aqi');
      expect(screen.getByTestId('map-display-mode')).toHaveTextContent(expectedMode);
      expect(screen.getByTestId('map-data-layer-mode')).toHaveTextContent('pollutants');
      expect(screen.getByTestId('map-aqi-product')).toHaveTextContent(expectedProduct);
    });
  });

  it('shows an explicit reset state for a removed product URL', async () => {
    window.history.replaceState(
      {},
      '',
      '/map?display_mode=us_epa&product_code=us_epa.co.1_hour',
    );
    render(<BrowserRouter><App /></BrowserRouter>);

    expect(await screen.findByText(
      'Air-quality index product “us_epa.co.1_hour” is unavailable.',
    )).toBeInTheDocument();
    expect(screen.getByLabelText('AQI product')).toHaveValue('');
    expect(screen.getByTestId('map-aqi-product')).toHaveTextContent('');
  });

  it('keeps controls synchronized across all layers without changing Source or restoring time controls', async () => {
    render(<BrowserRouter><App /></BrowserRouter>);
    await screen.findByLabelText('Layer');
    const sourceSelect = screen.getByLabelText('Data source filter');
    fireEvent.change(sourceSelect, { target: { value: 'openaq' } });

    fireEvent.change(screen.getByLabelText('Layer'), { target: { value: 'measurements' } });
    expect(screen.getByLabelText('Parameter')).toHaveValue('pm25');
    expect(screen.queryByRole('group', { name: 'Time window' })).not.toBeInTheDocument();
    expect(screen.getByTestId('quick-download')).toBeInTheDocument();
    expect(screen.getByTestId('quick-download')).toHaveAttribute('data-icon-only', 'false');

    fireEvent.change(screen.getByLabelText('Layer'), { target: { value: 'aqi' } });
    expect(screen.getByLabelText('AQI product')).toHaveValue('us_epa.pm25.nowcast');
    expect(screen.queryByRole('group', { name: 'Time window' })).not.toBeInTheDocument();
    expect(screen.getByTestId('quick-download')).toBeInTheDocument();
    expect(screen.getByTestId('quick-download')).toHaveAttribute('data-mode', 'aqi');
    expect(screen.getByTestId('quick-download')).toHaveAttribute('data-standard', 'us_epa');
    expect(screen.getByTestId('quick-download')).toHaveAttribute('data-product', 'us_epa.pm25.nowcast');
    expect(screen.getByTestId('quick-download')).toHaveAttribute('data-source', 'openaq');

    fireEvent.change(screen.getByLabelText('AQI product'), {
      target: { value: 'eea_european.overall.hourly' },
    });
    expect(screen.getByTestId('quick-download')).toHaveAttribute('data-standard', 'eea_european');
    expect(screen.getByTestId('quick-download')).toHaveAttribute('data-product', 'eea_european.overall.hourly');
    expect(screen.queryByRole('group', { name: 'Time window' })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Layer'), { target: { value: 'devices' } });
    expect(screen.getByLabelText('Parameter')).toHaveValue('');
    expect(screen.queryByLabelText('Time resolution')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Data source filter')).toHaveValue('openaq');
    expect(screen.queryByRole('group', { name: 'Time window' })).not.toBeInTheDocument();
  });

  it('passes device Parameter without a meaningless Time Resolution', async () => {
    render(<BrowserRouter><App /></BrowserRouter>);
    await screen.findByLabelText('Layer');
    fireEvent.change(screen.getByLabelText('Parameter'), { target: { value: 'temperature' } });
    expect(screen.getByTestId('map-parameter')).toHaveTextContent('temperature');
    expect(screen.getByTestId('map-time-resolution')).toBeEmptyDOMElement();
    expect(screen.getByTestId('map-data-layer-mode')).toHaveTextContent('devices');
  });

  it('lists measurement parameters only and filters Time Resolution by Parameter', async () => {
    render(<BrowserRouter><App /></BrowserRouter>);
    fireEvent.change(await screen.findByLabelText('Layer'), { target: { value: 'measurements' } });
    const parameterSelect = screen.getByLabelText('Parameter');
    expect(within(parameterSelect).queryByRole('option', { name: 'All Parameters' })).not.toBeInTheDocument();
    expect(within(parameterSelect).getByRole('option', { name: 'PM2.5' })).toBeInTheDocument();
    expect(within(parameterSelect).getByRole('option', { name: 'Temperature' })).toBeInTheDocument();

    fireEvent.change(parameterSelect, { target: { value: 'temperature' } });
    const timeResolutionSelect = screen.getByLabelText('Time resolution');
    expect(within(timeResolutionSelect).getByRole('option', { name: '1-minute' })).toBeInTheDocument();
    expect(within(timeResolutionSelect).queryByRole('option', { name: 'Hourly' })).not.toBeInTheDocument();
    expect(within(timeResolutionSelect).queryByRole('option', { name: 'Daily' })).not.toBeInTheDocument();
  });

  it('loads AQI metadata once when switching layers', async () => {
    render(<BrowserRouter><App /></BrowserRouter>);
    await screen.findByLabelText('Layer');
    fireEvent.change(screen.getByLabelText('Layer'), { target: { value: 'measurements' } });
    fireEvent.change(screen.getByLabelText('Layer'), { target: { value: 'aqi' } });
    fireEvent.change(screen.getByLabelText('Layer'), { target: { value: 'devices' } });
    const standardsCalls = vi.mocked(api.fetchJson).mock.calls.filter(
      ([path]) => path === '/air-quality-index/standards',
    );
    expect(standardsCalls).toHaveLength(1);
  });

  it('keeps one map component mounted while toolbar filters change', async () => {
    render(<BrowserRouter><App /></BrowserRouter>);
    await screen.findByLabelText('Layer');
    await waitFor(() => expect(mapLifecycle.mounted).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText('Layer'), { target: { value: 'measurements' } });
    fireEvent.change(screen.getByLabelText('Parameter'), { target: { value: 'temperature' } });
    fireEvent.change(screen.getByLabelText('Time resolution'), { target: { value: '1m' } });
    fireEvent.change(screen.getByLabelText('Data source filter'), { target: { value: 'openaq' } });
    fireEvent.change(screen.getByLabelText('Layer'), { target: { value: 'aqi' } });
    fireEvent.change(screen.getByLabelText('AQI product'), {
      target: { value: 'eea_european.pm25.hourly' },
    });

    await waitFor(() => {
      expect(screen.getByTestId('map-aqi-product')).toHaveTextContent('eea_european.pm25.hourly');
    });
    expect(mapLifecycle.mounted).toHaveBeenCalledTimes(1);
    expect(mapLifecycle.unmounted).not.toHaveBeenCalled();
  });
  it('opens all existing controls on mobile and preserves filters and the map instance on dismissal', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
    HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
    render(<BrowserRouter><App /></BrowserRouter>);
    const trigger = await screen.findByRole('button', { name: 'Map controls' });
    expect(screen.queryByRole('combobox', { name: 'Layer' })).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Controls changed from defaults' })).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(await screen.findByRole('dialog', { name: 'Map controls' })).toBeVisible();
    expect(document.body.style.overflow).toBe('hidden');
    fireEvent.change(screen.getByLabelText('Parameter', { exact: true }), { target: { value: 'pm25' } });
    expect(screen.getByTestId('map-parameter')).toHaveTextContent('pm25');
    fireEvent.click(screen.getByRole('button', { name: 'Close controls' }));
    expect(document.body.style.overflow).toBe('');
    expect(screen.getByRole('img', { name: 'Controls changed from defaults' })).toBeInTheDocument();
    fireEvent.click(trigger);
    expect(screen.getByLabelText('Parameter', { exact: true })).toHaveValue('pm25');
    fireEvent.change(screen.getByLabelText('Parameter', { exact: true }), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Close controls' }));
    expect(screen.queryByRole('img', { name: 'Controls changed from defaults' })).not.toBeInTheDocument();
    expect(mapLifecycle.mounted).toHaveBeenCalledTimes(1);
    expect(mapLifecycle.unmounted).not.toHaveBeenCalled();
  });

});
