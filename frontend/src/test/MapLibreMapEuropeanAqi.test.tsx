import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import * as maplibregl from 'maplibre-gl';
import MapLibreMap from '../MapLibreMap';
import { fetchJson } from '../api';
import {
  getLatestAirQualityIndex,
  getUsEpaCompletedDayHistory,
  type AirQualityIndexCollection,
  type AirQualityIndexStandardMetadata,
  type UsEpaCompletedDayHistorySummary,
} from '../airQualityIndex';

vi.mock('../airQualityIndex', async (importActual) => {
  const actual = await importActual<typeof import('../airQualityIndex')>();
  return {
    ...actual,
    getLatestAirQualityIndex: vi.fn(),
    getUsEpaCompletedDayHistory: vi.fn(),
  };
});

vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>();
  return { ...actual, fetchJson: vi.fn() };
});

const mockedGetLatest = vi.mocked(getLatestAirQualityIndex);
const mockedGetHistory = vi.mocked(getUsEpaCompletedDayHistory);
const mockedFetchJson = vi.mocked(fetchJson);
const standardMetadata: AirQualityIndexStandardMetadata = {
  standard_code: 'eea_european', display_name: 'European Air Quality Index',
  methodology_version: 'eea_2024_bands', result_kind: 'categorical', averaging_minutes: 60,
  required_averaging_period: '1h', supported_parameter_codes: ['pm25'], normalized_unit: 'µg/m³',
  categories: [
    { code: 'fair', label: 'Fair', internal_severity_rank: 2, color: '#50CCAA' },
    { code: 'poor', label: 'Poor', internal_severity_rank: 4, color: '#FF5050' },
  ],
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
  default_product_code: 'eea_european.overall.hourly',
  is_default: false,
};

const usEpaStandardMetadata: AirQualityIndexStandardMetadata = {
  standard_code: 'us_epa',
  display_name: 'U.S. EPA AQI',
  methodology_version: 'us_epa_aqi_2024',
  methodology_code: 'us_epa_aqi_40_cfr_58_appendix_g',
  methodology_revision: '2024-05',
  methodology_effective_date: '2024-05-06',
  methodology_references: [],
  limitations: [],
  result_kind: 'numeric',
  averaging_minutes: 60,
  required_averaging_period: '12h_nowcast',
  supported_parameter_codes: ['pm25', 'pm10'],
  normalized_unit: 'AQI',
  categories: [
    { code: 'moderate', label: 'Moderate', internal_severity_rank: 2, color: '#FFFF00' },
    { code: 'hazardous', label: 'Hazardous', internal_severity_rank: 6, color: '#7E0023' },
  ],
  products: [{
    product_code: 'us_epa.pm25.nowcast',
    display_name: 'PM2.5 NowCast AQI',
    parameter_code: 'pm25',
    calculation_code: 'pm_nowcast',
    aggregation_period: '12h_nowcast',
    aggregation_display_name: 'NowCast from 12 completed hourly slots',
    result_scope: 'pollutant',
    is_parameter_default: true,
    availability_status: 'available',
    availability_reason: null,
    product_kind: 'nowcast',
    methodology_code: 'us_epa_aqi_40_cfr_58_appendix_g',
    methodology_revision: '2024-05',
    methodology_effective_date: '2024-05-06',
    methodology_references: [],
    limitations: [],
  }, {
    product_code: 'us_epa.pm25.completed_day',
    display_name: 'U.S. EPA PM2.5 Completed-Day AQI',
    parameter_code: 'pm25',
    calculation_code: 'pm_completed_local_day',
    aggregation_period: 'completed_local_day',
    aggregation_display_name: 'Completed Day',
    result_scope: 'pollutant',
    is_parameter_default: false,
    availability_status: 'available',
    availability_reason: null,
    product_kind: 'completed_day',
    methodology_references: [],
    limitations: [],
  }, {
    product_code: 'us_epa.pm10.completed_day',
    display_name: 'U.S. EPA PM10 Completed-Day AQI',
    parameter_code: 'pm10',
    calculation_code: 'pm_completed_local_day',
    aggregation_period: 'completed_local_day',
    aggregation_display_name: 'Completed Day',
    result_scope: 'pollutant',
    is_parameter_default: false,
    availability_status: 'available',
    availability_reason: null,
    product_kind: 'completed_day',
    methodology_references: [],
    limitations: [],
  }],
  default_product_code: 'us_epa.pm25.nowcast',
  is_default: true,
};

const eligibleCollection: AirQualityIndexCollection = {
  standard_code: 'eea_european', methodology_version: 'eea_2024_bands', result_kind: 'categorical', count: 1,
  results: [{
    standard_code: 'eea_european', methodology_version: 'eea_2024_bands', result_kind: 'categorical',
    device_id: 1, device_name: 'station-1', device_friendly_name: 'Central Station',
    latitude: 48.85, longitude: 2.35, device_timezone: 'Europe/Paris', source_name: 'OpenAQ',
    observed_at: '2026-07-14T10:00:00Z', numeric_value: null, category_code: 'poor', category_label: 'Poor',
    eligibility_status: 'eligible', exclusion_reasons: [], dominant_pollutants: ['o3'], pollutant_results: [{
      standard_code: 'eea_european', methodology_version: 'eea_2024_bands', parameter_code: 'pm25',
      normalized_concentration: 12, normalized_unit: 'µg/m³', result_kind: 'categorical', numeric_value: null,
      category_code: 'fair', category_label: 'Fair', eligibility_status: 'eligible', exclusion_reason: null,
    }],
    coverage: { coverage_status: 'partial', available_pollutants: ['pm25'], missing_pollutants: [], ineligible_pollutants: [], missing_or_ineligible_pollutants: [], display_qualification: 'not_evaluated' },
    sensor_provenance: [],
  }],
};

const usEpaCollection: AirQualityIndexCollection = {
  standard_code: 'us_epa',
  methodology_version: 'us_epa_aqi_2024',
  result_kind: 'numeric',
  product_code: 'us_epa.pm25.nowcast',
  product_display_name: 'PM2.5 NowCast AQI',
  product_kind: 'nowcast',
  methodology_code: 'us_epa_aqi_40_cfr_58_appendix_g',
  methodology_revision: '2024-05',
  methodology_effective_date: '2024-05-06',
  methodology_references: [],
  count: 1,
  results: [{
    standard_code: 'us_epa',
    methodology_version: 'us_epa_aqi_2024',
    result_kind: 'numeric',
    device_id: 301,
    device_name: 'us-station',
    device_friendly_name: 'U.S. Station',
    latitude: 48.86,
    longitude: 2.36,
    device_timezone: 'UTC',
    source_name: 'OpenAQ',
    observed_at: '2026-07-14T10:00:00Z',
    numeric_value: 87,
    category_code: 'moderate',
    category_label: 'Moderate',
    eligibility_status: 'eligible',
    exclusion_reasons: [],
    dominant_pollutants: ['pm25'],
    pollutant_results: [],
    coverage: {
      coverage_status: 'complete',
      available_pollutants: ['pm25'],
      missing_pollutants: [],
      ineligible_pollutants: [],
      missing_or_ineligible_pollutants: [],
      display_qualification: 'not_evaluated',
    },
    sensor_provenance: [],
    product_code: 'us_epa.pm25.nowcast',
    product_display_name: 'PM2.5 NowCast AQI',
    product_kind: 'nowcast',
    methodology_code: 'us_epa_aqi_40_cfr_58_appendix_g',
    methodology_revision: '2024-05',
    methodology_effective_date: '2024-05-06',
    methodology_references: [],
    calculation_status: 'calculated',
    coverage_status: 'complete',
    exclusion_reason: null,
    aqi_scale_status: 'within_0_to_500',
    expected_observation_count: 12,
    valid_observation_count: 12,
    window_started_at: '2026-07-13T22:00:00Z',
    window_ended_at: '2026-07-14T10:00:00Z',
    normalized_concentration: 30.1,
    normalized_unit: 'µg/m³',
    preprocessed_concentration: 30.1,
    sensor_id: 201,
    external_sensor_id: null,
    measurement_ids: [],
    valid_sample_count: 12,
    data_qualification_status: 'not_evaluated',
  }],
};

const completedDayCollection: AirQualityIndexCollection = {
  ...usEpaCollection,
  product_code: 'us_epa.pm25.completed_day',
  product_display_name: 'U.S. EPA PM2.5 Completed-Day AQI',
  product_kind: 'completed_day',
  results: [{
    ...usEpaCollection.results[0],
    product_code: 'us_epa.pm25.completed_day',
    product_display_name: 'U.S. EPA PM2.5 Completed-Day AQI',
    product_kind: 'completed_day',
    observed_at: '2026-07-31T07:00:00Z',
    represented_local_date: '2026-07-30',
    local_day_started_at: '2026-07-30T00:00:00-07:00',
    local_day_ended_at: '2026-07-31T00:00:00-07:00',
    utc_window_started_at: '2026-07-30T07:00:00Z',
    utc_window_ended_at: '2026-07-31T07:00:00Z',
    expected_hour_count: 24,
    valid_hour_count: 18,
    required_valid_hour_count: 18,
    required_completeness_fraction: 0.75,
    achieved_completeness_fraction: 0.75,
    daily_concentration: 30.1,
    expected_observation_count: null,
    valid_observation_count: null,
    latest_completed_hour_valid_observation_count: null,
    latest_completed_hour_expected_observation_count: null,
    latest_completed_hour_required_observation_count: null,
    nowcast_hourly_input_eligibility: null,
  }],
};

function completedDayHistoryResponse(
  productCode: string = 'us_epa.pm25.completed_day',
  representedLocalDate: string = '2026-07-30',
): UsEpaCompletedDayHistorySummary {
  const isPm10 = productCode.includes('pm10');
  return {
    standard_code: 'us_epa',
    methodology_version: 'us_epa_aqi_2024',
    result_kind: 'numeric',
    product_code: productCode,
    product_display_name: isPm10
      ? 'U.S. EPA PM10 Completed-Day AQI'
      : 'U.S. EPA PM2.5 Completed-Day AQI',
    product_kind: 'completed_day',
    parameter_code: isPm10 ? 'pm10' : 'pm25',
    methodology_code: 'us_epa_aqi_40_cfr_58_appendix_g',
    methodology_revision: '2024-05',
    methodology_effective_date: '2024-05-06',
    start_local_date: representedLocalDate,
    end_local_date: representedLocalDate,
    requested_day_count: 1,
    returned_device_count: 1,
    returned_result_count: 1,
    calculated_result_count: 1,
    unavailable_result_count: 0,
    maximum_supported_day_count: 366,
    detail: 'summary',
    device_series: [{
      device_id: 301,
      device_name: 'us-station',
      device_friendly_name: 'U.S. Station',
      latitude: 48.86,
      longitude: 2.36,
      device_timezone: 'UTC',
      source_name: 'OpenAQ',
      results: [{
        represented_local_date: representedLocalDate,
        local_day_started_at: null,
        local_day_ended_at: null,
        utc_window_started_at: null,
        utc_window_ended_at: null,
        expected_hour_count: 24,
        valid_hour_count: 18,
        required_valid_hour_count: 18,
        required_completeness_fraction: 0.75,
        achieved_completeness_fraction: 0.75,
        daily_concentration: 30.1,
        preprocessed_concentration: 30.1,
        normalized_unit: 'µg/m³',
        calculation_status: 'calculated',
        coverage_status: 'complete',
        numeric_value: 87,
        category_code: 'moderate',
        category_label: 'Moderate',
        aqi_scale_status: 'within_0_to_500',
        selected_sensor_id: 201,
        blocking_reasons: [],
        audit_flags: [],
      }],
    }],
  };
}

describe('European AQI map mode', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetLatest.mockReset();
    mockedGetHistory.mockReset();
    mockedGetHistory.mockResolvedValue(completedDayHistoryResponse());
    mockedFetchJson.mockReset();
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: undefined });
  });
  afterEach(() => {
    // Unmount first so an in-flight request cannot append a marker after the
    // manual cleanup used by the MapLibre test double.
    cleanup();
    document
      .querySelectorAll('.european-aqi-marker, [title^="PM25"]')
      .forEach((element) => element.remove());
  });

  it('shows loading, loads unbounded locations and forwards source, and renders an accessible categorical marker', async () => {
    let resolveRequest!: (collection: AirQualityIndexCollection) => void;
    mockedGetLatest.mockImplementation(() => new Promise((resolve) => { resolveRequest = resolve; }));
    render(<MapLibreMap parameter="pm25" displayMode="eea_european" europeanStandardMetadata={standardMetadata} sourceFilter="OpenAQ" />);
    expect(screen.getByText('Loading European Air Quality Index…')).toBeInTheDocument();
    resolveRequest(eligibleCollection);
    const marker = await screen.findByRole('button', { name: /Central Station: Overall hourly European AQI Poor, partial pollutant coverage/ });
    expect(marker).toHaveTextContent('Poor · Partial');
    await waitFor(() => expect(mockedGetLatest).toHaveBeenCalledWith(expect.objectContaining({
      standard_code: 'eea_european', external_api_name: 'openaq',
    })));
    expect(screen.queryByText(/Poor AQI/)).not.toBeInTheDocument();
  });

  it('shows an explicit empty state and clears markers', async () => {
    mockedGetLatest.mockResolvedValue({ ...eligibleCollection, count: 0, results: [] });
    render(<MapLibreMap parameter="pm25" displayMode="eea_european" europeanStandardMetadata={standardMetadata} />);
    expect(await screen.findByText(/No AQI results found in this area/)).toBeInTheDocument();
    expect(document.querySelector('.european-aqi-marker')).not.toBeInTheDocument();
  });

  it('shows a specific request error and no stale marker', async () => {
    mockedGetLatest.mockRejectedValue(new Error('network failed'));
    render(<MapLibreMap parameter="pm25" displayMode="eea_european" europeanStandardMetadata={standardMetadata} />);
    expect(await screen.findByText(/Unable to load European Air Quality Index results/)).toBeInTheDocument();
    expect(document.querySelector('.european-aqi-marker')).not.toBeInTheDocument();
  });

  it('shows unsupported state when the standards endpoint does not advertise the method', async () => {
    render(<MapLibreMap parameter="pm25" displayMode="eea_european" europeanStandardMetadata={null} />);
    expect(await screen.findByText(/European Air Quality Index is not supported/)).toBeInTheDocument();
    expect(mockedGetLatest).not.toHaveBeenCalled();
  });

  it('uses the selected pollutant result, backend color, legend, and existing details layout', async () => {
    mockedGetLatest.mockResolvedValue(eligibleCollection);
    const pm25Product = standardMetadata.products[1];
    render(
      <MemoryRouter>
        <MapLibreMap
          parameter="pm25"
          timeResolution="1h"
          displayMode="eea_european"
          europeanStandardMetadata={standardMetadata}
          selectedAirQualityIndexProduct={pm25Product}
        />
      </MemoryRouter>,
    );

    const marker = await screen.findByRole('button', {
      name: /Central Station: PM2.5 hourly European AQI Fair, partial pollutant coverage/,
    });
    expect(marker).toHaveTextContent('Fair · Partial');
    expect(marker).toHaveStyle({ backgroundColor: '#50CCAA' });
    expect(screen.getByLabelText('European Air Quality Index legend')).toHaveTextContent(
      'PM2.5 hourly European AQI',
    );

    fireEvent.click(marker);
    expect(screen.getByRole('heading', { name: 'Central Station' })).toBeInTheDocument();
    expect(screen.getAllByText('PM2.5 hourly European AQI').length).toBeGreaterThan(0);
    expect(screen.getByText('European Air Quality Index')).toBeInTheDocument();
    expect(screen.getByText('Fair · 12 µg/m³')).toBeInTheDocument();
  });

  it('switches all map layers without recreating or repositioning the map', async () => {
    const rawMeasurement = {
      measurement_id: 101,
      sensor_id: 201,
      value: 12.3,
      parameter: 'pm25',
      unit: 'µg/m³',
      observed_at: new Date().toISOString(),
      device: {
        device_id: 301,
        name: 'raw-station',
        friendly_name: 'Raw Station',
        latitude: 48.86,
        longitude: 2.36,
      },
    };
    const device = {
      device_id: 401,
      name: 'Device Station',
      latitude: 48.87,
      longitude: 2.37,
    };
    mockedFetchJson.mockImplementation(async (path: string) => {
      if (path.startsWith('/measurements/pm25/latest')) return [rawMeasurement];
      if (path.startsWith('/devices')) return [device];
      return [];
    });
    mockedGetLatest.mockImplementation(async (query) => (
      query.standard_code === 'us_epa' ? usEpaCollection : eligibleCollection
    ));

    const mapProps = {
      parameter: 'pm25',
      mode: 'pollutants' as const,
      timeResolution: '1h',
      sourceFilter: 'phase31-transition',
      europeanStandardMetadata: standardMetadata,
      usEpaStandardMetadata,
    };
    const mapForDisplayMode = (displayMode: 'measurements' | 'eea_european' | 'us_epa') => (
      <MemoryRouter>
        <MapLibreMap
          {...mapProps}
          displayMode={displayMode}
          timeResolution={displayMode === 'us_epa' ? '12h_nowcast' : '1h'}
          selectedAirQualityIndexProduct={
            displayMode === 'us_epa' ? usEpaStandardMetadata.products[0] : null
          }
        />
      </MemoryRouter>
    );
    const { rerender } = render(mapForDisplayMode('measurements'));

    const initialRawMarker = await waitFor(() => {
      const marker = document.querySelector<HTMLElement>('[title^="PM25 12.3"]');
      expect(marker).toBeInTheDocument();
      return marker!;
    });
    expect(initialRawMarker.innerText).toBe('12.3 µg/m³');
    expect(screen.queryByLabelText('European Air Quality Index legend')).not.toBeInTheDocument();
    expect(document.querySelector('.aqi-legend')).not.toBeInTheDocument();

    await new Promise((resolve) => window.setTimeout(resolve, 300));
    const mapConstructor = vi.mocked(maplibregl.Map);
    expect(mapConstructor).toHaveBeenCalledTimes(1);
    const mapInstance = mapConstructor.mock.results[0].value as unknown as {
      flyTo: ReturnType<typeof vi.fn>;
      fitBounds: ReturnType<typeof vi.fn>;
      remove: ReturnType<typeof vi.fn>;
    };
    const initialFlyToCount = mapInstance.flyTo.mock.calls.length;
    const initialFitBoundsCount = mapInstance.fitBounds.mock.calls.length;

    rerender(
      <MemoryRouter>
        <MapLibreMap
          {...mapProps}
          parameter=""
          mode="devices"
          displayMode="measurements"
        />
      </MemoryRouter>,
    );
    const deviceMarker = await waitFor(() => {
      const marker = document.querySelector<HTMLElement>('[title="Device Station"]');
      expect(marker).toBeInTheDocument();
      return marker!;
    });
    expect(initialRawMarker).not.toBeInTheDocument();
    expect(deviceMarker).toBeInTheDocument();

    rerender(mapForDisplayMode('eea_european'));
    const europeanMarker = await screen.findByRole('button', {
      name: /Central Station: Overall hourly European AQI Poor, partial pollutant coverage/,
    });
    expect(initialRawMarker).not.toBeInTheDocument();
    expect(europeanMarker).toHaveTextContent('Poor · Partial');
    expect(europeanMarker.textContent).not.toMatch(/\d/);
    expect(screen.getByLabelText('European Air Quality Index legend')).toBeInTheDocument();
    expect(document.querySelector('.aqi-legend')).not.toBeInTheDocument();

    fireEvent.click(europeanMarker);
    expect(screen.getByRole('heading', { name: 'Central Station' })).toBeInTheDocument();

    rerender(mapForDisplayMode('us_epa'));
    const usAqiMarker = await waitFor(() => {
      const marker = document.querySelector<HTMLElement>('[title*="87 AQI"]');
      expect(marker).toBeInTheDocument();
      return marker!;
    });
    expect(europeanMarker).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Central Station' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('European Air Quality Index legend')).not.toBeInTheDocument();
    expect(document.querySelector('.aqi-legend')).toBeInTheDocument();
    expect(usAqiMarker.innerText).toBe('87 AQI');
    expect(mockedGetLatest).toHaveBeenCalledWith(expect.objectContaining({
      standard_code: 'us_epa',
      product_code: 'us_epa.pm25.nowcast',
    }));
    expect(mockedFetchJson).not.toHaveBeenCalledWith(
      expect.stringContaining('aggregation=aqi-nowcast'),
    );

    rerender(mapForDisplayMode('measurements'));
    const finalRawMarker = await waitFor(() => {
      const marker = document.querySelector<HTMLElement>('[title^="PM25 12.3"]');
      expect(marker).toBeInTheDocument();
      return marker!;
    });
    expect(usAqiMarker).not.toBeInTheDocument();
    expect(finalRawMarker.innerText).toBe('12.3 µg/m³');
    expect(screen.queryByLabelText('European Air Quality Index legend')).not.toBeInTheDocument();
    expect(document.querySelector('.aqi-legend')).not.toBeInTheDocument();
    fireEvent.click(finalRawMarker);
    expect(screen.getByRole('heading', { name: 'Raw Station' })).toBeInTheDocument();

    await new Promise((resolve) => window.setTimeout(resolve, 300));
    expect(mapConstructor).toHaveBeenCalledTimes(1);
    expect(mapInstance.remove).not.toHaveBeenCalled();
    expect(mapInstance.flyTo).toHaveBeenCalledTimes(initialFlyToCount);
    expect(mapInstance.fitBounds).toHaveBeenCalledTimes(initialFitBoundsCount);
  });

  it('renders an explicit U.S. EPA insufficient-data status', async () => {
    const unavailableCollection: AirQualityIndexCollection = {
      ...usEpaCollection,
      results: [{
        ...usEpaCollection.results[0],
        numeric_value: null,
        category_code: null,
        category_label: null,
        eligibility_status: 'ineligible',
        exclusion_reasons: ['insufficient_recent_hours'],
        calculation_status: 'unavailable',
        coverage_status: 'partial',
        exclusion_reason: 'insufficient_recent_hours',
        aqi_scale_status: null,
        valid_observation_count: 1,
        latest_completed_hour_valid_observation_count: 22,
        latest_completed_hour_expected_observation_count: 30,
        latest_completed_hour_required_observation_count: 23,
      }],
    };
    mockedGetLatest.mockResolvedValue(unavailableCollection);
    render(
      <MemoryRouter>
        <MapLibreMap
          parameter="pm25"
          mode="pollutants"
          timeResolution="12h_nowcast"
          displayMode="us_epa"
          usEpaStandardMetadata={usEpaStandardMetadata}
          selectedAirQualityIndexProduct={usEpaStandardMetadata.products[0]}
        />
      </MemoryRouter>,
    );
    const marker = await waitFor(() => {
      const resultMarker = document.querySelector<HTMLElement>('[title*="PM2.5 NowCast AQI: -"]');
      expect(resultMarker).toBeInTheDocument();
      return resultMarker!;
    });
    fireEvent.click(marker);
    expect(await screen.findByRole('status')).toHaveTextContent(
      'AQI unavailable: Not enough complete recent hours for NowCast',
    );
    expect(screen.getByTestId('aqi-hourly-completeness')).toHaveTextContent(
      'Latest completed hour: 22 of 30 readings available; 23 required.',
    );
    expect(screen.queryByText('insufficient_recent_hours')).not.toBeInTheDocument();
    expect(screen.getByText('AQI details').closest('details')).toHaveTextContent('Not enough complete recent hours for NowCast');
  });

  it('renders completed-day date and backend completeness without NowCast wording', async () => {
    mockedGetLatest.mockResolvedValue(completedDayCollection);
    render(
      <MemoryRouter>
        <MapLibreMap
          parameter="pm25"
          mode="pollutants"
          timeResolution="completed_local_day"
          displayMode="us_epa"
          usEpaStandardMetadata={usEpaStandardMetadata}
          selectedAirQualityIndexProduct={usEpaStandardMetadata.products[1]}
        />
      </MemoryRouter>,
    );
    const marker = await waitFor(() => {
      const resultMarker = document.querySelector<HTMLElement>('[title*="87 AQI"]');
      expect(resultMarker).toBeInTheDocument();
      return resultMarker!;
    });
    fireEvent.click(marker);
    expect(await screen.findByTestId('completed-day-date')).toHaveTextContent(
      'Completed day: July 30, 2026',
    );
    expect(screen.getByTestId('completed-day-completeness')).toHaveTextContent(
      '18 of 24 hourly concentrations available; 18 required.',
    );
    expect(screen.getAllByText('U.S. EPA PM2.5 Completed-Day AQI').length).toBeGreaterThan(0);
    expect(screen.queryByText('completed_local_day')).not.toBeInTheDocument();
    expect(screen.queryByTestId('aqi-hourly-completeness')).not.toBeInTheDocument();
    expect(mockedGetLatest).toHaveBeenCalledWith(expect.objectContaining({
      product_code: 'us_epa.pm25.completed_day',
    }));
  });

  it('keeps the map and selected panel stable while AQI trend products change', async () => {
    const pm10CompletedDayCollection: AirQualityIndexCollection = {
      ...completedDayCollection,
      product_code: 'us_epa.pm10.completed_day',
      product_display_name: 'U.S. EPA PM10 Completed-Day AQI',
      results: [{
        ...completedDayCollection.results[0],
        parameter_code: 'pm10',
        product_code: 'us_epa.pm10.completed_day',
        product_display_name: 'U.S. EPA PM10 Completed-Day AQI',
        represented_local_date: '2026-07-31',
      }],
    };
    mockedGetLatest.mockImplementation(async (query) => {
      if (query.product_code === 'us_epa.pm10.completed_day') return pm10CompletedDayCollection;
      if (query.product_code === 'us_epa.pm25.nowcast') return usEpaCollection;
      return completedDayCollection;
    });
    const mapForProduct = (productIndex: number) => (
      <MemoryRouter>
        <MapLibreMap
          parameter={usEpaStandardMetadata.products[productIndex].parameter_code || ''}
          mode="pollutants"
          timeResolution={usEpaStandardMetadata.products[productIndex].aggregation_period}
          displayMode="us_epa"
          usEpaStandardMetadata={usEpaStandardMetadata}
          selectedAirQualityIndexProduct={usEpaStandardMetadata.products[productIndex]}
        />
      </MemoryRouter>
    );
    const { rerender } = render(mapForProduct(1));
    const marker = await waitFor(() => {
      const resultMarker = document.querySelector<HTMLElement>('[title*="87 AQI"]');
      expect(resultMarker).toBeInTheDocument();
      return resultMarker!;
    });
    fireEvent.click(marker);
    expect(await screen.findByTestId('aqi-trend-card')).toHaveAttribute(
      'data-product-code',
      'us_epa.pm25.completed_day',
    );
    expect(screen.getByText('Last 7 Days')).toBeInTheDocument();
    await new Promise((resolve) => window.setTimeout(resolve, 300));

    const mapConstructor = vi.mocked(maplibregl.Map);
    expect(mapConstructor).toHaveBeenCalledTimes(1);
    const mapInstance = mapConstructor.mock.results[0].value as unknown as {
      flyTo: ReturnType<typeof vi.fn>;
      fitBounds: ReturnType<typeof vi.fn>;
      remove: ReturnType<typeof vi.fn>;
    };
    const initialFlyToCount = mapInstance.flyTo.mock.calls.length;
    const initialFitBoundsCount = mapInstance.fitBounds.mock.calls.length;
    const markerConstructor = vi.mocked(maplibregl.Marker);
    const initialMarkerCount = markerConstructor.mock.calls.length;

    expect(mapConstructor).toHaveBeenCalledTimes(1);
    expect(markerConstructor).toHaveBeenCalledTimes(initialMarkerCount);
    expect(mapInstance.flyTo).toHaveBeenCalledTimes(initialFlyToCount);
    expect(mapInstance.fitBounds).toHaveBeenCalledTimes(initialFitBoundsCount);

    rerender(mapForProduct(2));
    expect(await screen.findByTestId('aqi-trend-card')).toHaveAttribute(
      'data-product-code',
      'us_epa.pm10.completed_day',
    );
    expect(screen.getByRole('heading', { name: 'U.S. Station' })).toBeInTheDocument();
    expect(mapConstructor).toHaveBeenCalledTimes(1);
    expect(mapInstance.remove).not.toHaveBeenCalled();
    expect(mapInstance.flyTo).toHaveBeenCalledTimes(initialFlyToCount);
    expect(mapInstance.fitBounds).toHaveBeenCalledTimes(initialFitBoundsCount);

    rerender(mapForProduct(0));
    expect(await screen.findByTestId('aqi-trend-card')).toHaveAttribute(
      'data-product-code',
      'us_epa.pm25.nowcast',
    );
    expect(screen.getByText('Last 24 Hours')).toBeInTheDocument();
    expect(mapConstructor).toHaveBeenCalledTimes(1);
    expect(mapInstance.remove).not.toHaveBeenCalled();
  });

  it('renders a plain completed-day unavailable message without raw enum values', async () => {
    const unavailableCompletedDay: AirQualityIndexCollection = {
      ...completedDayCollection,
      results: [{
        ...completedDayCollection.results[0],
        numeric_value: null,
        category_code: null,
        category_label: null,
        eligibility_status: 'ineligible',
        calculation_status: 'unavailable',
        coverage_status: 'partial',
        exclusion_reason: 'daily_completeness_not_met',
        exclusion_reasons: ['no_eligible_sensor_stream', 'daily_completeness_not_met'],
        blocking_reasons: ['no_eligible_sensor_stream', 'daily_completeness_not_met'],
        valid_hour_count: 17,
        required_valid_hour_count: 18,
      }],
    };
    mockedGetLatest.mockResolvedValue(unavailableCompletedDay);
    render(
      <MemoryRouter>
        <MapLibreMap
          parameter="pm25"
          mode="pollutants"
          timeResolution="completed_local_day"
          displayMode="us_epa"
          usEpaStandardMetadata={usEpaStandardMetadata}
          selectedAirQualityIndexProduct={usEpaStandardMetadata.products[1]}
        />
      </MemoryRouter>,
    );
    const marker = await waitFor(() => {
      const resultMarker = document.querySelector<HTMLElement>(
        '[title*="U.S. EPA PM2.5 Completed-Day AQI: -"]',
      );
      expect(resultMarker).toBeInTheDocument();
      return resultMarker!;
    });
    fireEvent.click(marker);
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Daily AQI unavailable: Not enough eligible hourly concentrations for the completed day.',
    );
    expect(screen.getByTestId('completed-day-completeness')).toHaveTextContent(
      '17 of 24 hourly concentrations available; 18 required.',
    );
    expect(screen.queryByText('daily_completeness_not_met')).not.toBeInTheDocument();
  });

  it('renders the numeric value and distinct above-500 status', async () => {
    const aboveScaleCollection: AirQualityIndexCollection = {
      ...usEpaCollection,
      results: [{
        ...usEpaCollection.results[0],
        numeric_value: 649,
        category_code: 'hazardous',
        category_label: 'Hazardous',
        aqi_scale_status: 'above_500',
      }],
    };
    mockedGetLatest.mockResolvedValue(aboveScaleCollection);
    render(
      <MemoryRouter>
        <MapLibreMap
          parameter="pm25"
          mode="pollutants"
          timeResolution="12h_nowcast"
          displayMode="us_epa"
          usEpaStandardMetadata={usEpaStandardMetadata}
          selectedAirQualityIndexProduct={usEpaStandardMetadata.products[0]}
        />
      </MemoryRouter>,
    );
    const marker = await waitFor(() => {
      const resultMarker = document.querySelector<HTMLElement>('[title*="649 AQI"]');
      expect(resultMarker).toBeInTheDocument();
      return resultMarker!;
    });
    fireEvent.click(marker);
    expect(await screen.findByText(/Hazardous · Above AQI 500/)).toHaveTextContent(
      'Above AQI 500',
    );
  });

  it('still honors explicit location, reset, and fit requests', async () => {
    const rawMeasurement = {
      measurement_id: 501,
      sensor_id: 502,
      value: 8.5,
      parameter: 'pm25',
      unit: 'µg/m³',
      observed_at: new Date().toISOString(),
      device: {
        device_id: 503,
        name: 'camera-test-station',
        friendly_name: 'Camera Test Station',
        latitude: 40.7,
        longitude: -74,
      },
    };
    mockedFetchJson.mockResolvedValue([rawMeasurement]);
    const location = { lat: 34.05, lng: -118.25, zoom: 9 };
    const mapForCameraProps = (fitTrigger: number, resetTrigger: number, includeLocation: boolean) => (
      <MemoryRouter>
        <MapLibreMap
          parameter="pm25"
          mode="pollutants"
          timeResolution="1h"
          displayMode="measurements"
          fitTrigger={fitTrigger}
          resetTrigger={resetTrigger}
          flyToCoords={includeLocation ? location : null}
        />
      </MemoryRouter>
    );
    const { rerender } = render(mapForCameraProps(0, 0, false));
    await waitFor(() => {
      expect(document.querySelector('[title^="PM25 8.5"]')).toBeInTheDocument();
    });
    await new Promise((resolve) => window.setTimeout(resolve, 300));

    const mapInstance = vi.mocked(maplibregl.Map).mock.results[0].value as unknown as {
      flyTo: ReturnType<typeof vi.fn>;
      fitBounds: ReturnType<typeof vi.fn>;
    };
    const initialFlyToCount = mapInstance.flyTo.mock.calls.length;
    const initialFitBoundsCount = mapInstance.fitBounds.mock.calls.length;

    rerender(mapForCameraProps(0, 0, true));
    await waitFor(() => expect(mapInstance.flyTo).toHaveBeenCalledTimes(initialFlyToCount + 1));
    expect(mapInstance.flyTo).toHaveBeenLastCalledWith(expect.objectContaining({
      center: [location.lng, location.lat],
      zoom: location.zoom,
    }));

    rerender(mapForCameraProps(0, 1, true));
    await waitFor(() => expect(mapInstance.flyTo).toHaveBeenCalledTimes(initialFlyToCount + 2));

    rerender(mapForCameraProps(1, 1, true));
    await waitFor(() => expect(mapInstance.fitBounds).toHaveBeenCalledTimes(initialFitBoundsCount + 1));
  });
});

vi.mock('../components/CompletedDayAqiHistoryChart', () => ({
  default: () => <div role="img" aria-label="Completed-day history chart" />,
}));

vi.mock('../components/AqiTrendCard', () => ({
  default: ({ product }: { product: { product_code: string; product_kind?: string | null } }) => (
    <div data-testid="aqi-trend-card" data-product-code={product.product_code}>
      {product.product_kind === 'completed_day' ? 'Last 7 Days' : 'Last 24 Hours'}
    </div>
  ),
}));

it.each([1, 2])('initial camera uses regional zoom for one location and normal bounds for %i locations', async (locationCount) => {
  const measurements = Array.from({ length: locationCount }, (_, index) => ({
    measurement_id: index + 1, sensor_id: index + 1, value: 8.5,
    parameter: 'pm25', unit: 'µg/m³', observed_at: new Date().toISOString(),
    device: { device_id: index + 1, name: 'DEMO — CompassAQ Sample Station',
      latitude: 52.0907 + index, longitude: 5.1214 + index },
  }));
  mockedFetchJson.mockResolvedValue(measurements);
  const view = (source?: string, fitTrigger = 0) => <MemoryRouter><MapLibreMap
    parameter="pm25" mode="pollutants" timeResolution="1h" displayMode="measurements"
    sourceFilter={source} fitTrigger={fitTrigger}
  /></MemoryRouter>;
  const { rerender } = render(view());
  const map = vi.mocked(maplibregl.Map).mock.results.at(-1)!.value;
  await waitFor(() => expect(map.fitBounds).toHaveBeenCalled());
  await new Promise(resolve => window.setTimeout(resolve, 300));
  expect(map.fitBounds).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ maxZoom: locationCount === 1 ? 5 : 12 }));
  expect(maplibregl.LngLatBounds).toHaveBeenCalledWith([5.1214, 52.0907], [5.1214, 52.0907]);
  const fitCount = vi.mocked(map.fitBounds).mock.calls.length;
  mockedFetchJson.mockResolvedValue([measurements[0]]);
  rerender(view('Demo Data'));
  await waitFor(() => expect(mockedFetchJson).toHaveBeenLastCalledWith(expect.stringContaining('external_api_name=demo'), { skipCache: true }));
  expect(map.fitBounds).toHaveBeenCalledTimes(fitCount);
  rerender(view('Demo Data', 1));
  await waitFor(() => expect(map.fitBounds).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ maxZoom: 12 })));
  cleanup();
  vi.clearAllMocks();
});


describe('Map MVP states and initial geolocation', () => {
  const device = { device_id: 901, name: 'Old station', latitude: 50, longitude: 0 };
  const measurement = { measurement_id: 902, sensor_id: 903, parameter: 'pm25', value: 12,
    unit: 'µg/m³', observed_at: '2020-01-01T00:00:00Z', device };
  const layers = ['devices', 'measurements', 'us_epa', 'philippines_denr', 'eea_european'] as const;
  type Layer = typeof layers[number];
  function props(layer: Layer): React.ComponentProps<typeof MapLibreMap> {
    return { parameter: layer === 'devices' ? '' : 'pm25', mode: layer === 'devices' ? 'devices' : 'pollutants',
      displayMode: layer === 'devices' ? 'measurements' : layer,
      timeResolution: layer === 'measurements' ? '1h' : undefined,
      numericStandardMetadata: layer === 'philippines_denr'
        ? { ...usEpaStandardMetadata, standard_code: 'philippines_denr' } : usEpaStandardMetadata,
      europeanStandardMetadata: standardMetadata,
      selectedAirQualityIndexProduct: layer === 'eea_european' ? standardMetadata.products[0] : usEpaStandardMetadata.products[0] };
  }
  function renderLayer(layer: Layer, extra = {}) {
    return render(<MemoryRouter><MapLibreMap {...props(layer)} {...extra} /></MemoryRouter>);
  }
  function latestMap() {
    return vi.mocked(maplibregl.Map).mock.results.at(-1)!.value;
  }
  function event(name: string, payload = {}) {
    const calls = vi.mocked(latestMap().on).mock.calls as Array<[string, (event: object) => void]>;
    const handlers = calls.filter(call => call[0] === name);
    act(() => handlers.forEach(call => (call[1] as (event: object) => void)(payload)));
  }
  beforeEach(() => {
    vi.clearAllMocks();
    mockedFetchJson.mockReset().mockResolvedValue([]);
    mockedGetLatest.mockReset().mockResolvedValue({ ...eligibleCollection, results: [], count: 0 });
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: {
      getCurrentPosition: vi.fn(success => success({ coords: { latitude: 50, longitude: 0 } })),
    } });
  });
  afterEach(() => { cleanup(); Object.defineProperty(navigator, 'geolocation', { configurable: true, value: undefined }); });

  it('uses native viewport constraints with a nonnegative minimum zoom and world wrapping', async () => {
    renderLayer('devices');
    await waitFor(() => expect(maplibregl.Map).toHaveBeenCalled());
    const options = vi.mocked(maplibregl.Map).mock.calls.at(-1)![0];
    expect(options.renderWorldCopies).toBe(true);
    expect(options.minZoom).toBe(0);
    expect(options.transformConstrain).toBeUndefined();
    // Actual pole coverage and antimeridian behavior are checked in the browser.
  });

  it.each(layers)('%s shares loading, error, and empty presentation without a recency request', async layer => {
    let reject!: (reason: Error) => void;
    const pending = new Promise<never>((_, fail) => { reject = fail; });
    mockedFetchJson.mockReturnValue(pending);
    mockedGetLatest.mockReturnValue(pending);
    const view = renderLayer(layer);
    expect(document.querySelector('.map-loading')).toHaveAttribute('role', 'status');
    await act(async () => reject(new Error('Offline')));
    expect(document.querySelector('.map-error')).toHaveAttribute('role', 'alert');
    expect(screen.queryByTestId('map-empty-state')).not.toBeInTheDocument();
    expect(document.querySelector('[data-map-marker-key]')).not.toBeInTheDocument();
    view.unmount();
    mockedFetchJson.mockResolvedValue([]);
    mockedGetLatest.mockResolvedValue({ ...eligibleCollection, results: [], count: 0 });
    renderLayer(layer);
    expect(await screen.findByTestId('map-empty-state')).toHaveTextContent('in this area');
    await waitFor(() => expect(latestMap().fitBounds).toHaveBeenCalledWith(expect.anything(), { padding: 48, duration: 0 }));
    expect(maplibregl.LngLatBounds).toHaveBeenCalledWith([-180, -85], [180, 85]);
    for (const [path] of mockedFetchJson.mock.calls) expect(String(path)).not.toMatch(/since=|until=|start=|recency=/);
    for (const [request] of mockedGetLatest.mock.calls) {
      expect(request).not.toHaveProperty('until');
      expect(request).not.toHaveProperty('bbox');
    }
  });

  it.each(['devices', 'measurements'] as const)('keeps nearby %s even without recent observations', async layer => {
    mockedFetchJson.mockResolvedValue(layer === 'devices' ? [device] : [measurement]);
    renderLayer(layer);
    await waitFor(() => expect(document.querySelector('[data-map-marker-key]')).toBeInTheDocument());
    expect(latestMap().fitBounds).not.toHaveBeenCalled();
    expect(latestMap().flyTo).not.toHaveBeenCalled();
    expect(screen.queryByTestId('map-empty-state')).not.toBeInTheDocument();
    expect(mockedFetchJson).toHaveBeenCalledTimes(1);
    expect(mockedFetchJson).toHaveBeenCalledWith(layer === 'devices' ? '/devices' : '/measurements/pm25/latest?all_results=true&aggregation=1h', { skipCache: true });
  });

  it('fits remote data once at a regional zoom and never refits on layer switches', async () => {
    mockedFetchJson.mockResolvedValue([{ ...device, longitude: 120 }]);
    const view = renderLayer('devices');
    await waitFor(() => expect(latestMap().fitBounds).toHaveBeenCalledTimes(1));
    expect(latestMap().fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ maxZoom: 5 }));
    mockedFetchJson.mockResolvedValue([]);
    view.rerender(<MemoryRouter><MapLibreMap {...props('measurements')} /></MemoryRouter>);
    expect(await screen.findByTestId('map-empty-state')).toHaveTextContent('No measurements');
    expect(document.querySelector('[data-map-marker-key]')).not.toBeInTheDocument();
    view.rerender(<MemoryRouter><MapLibreMap {...props('eea_european')} /></MemoryRouter>);
    expect(await screen.findByTestId('map-empty-state')).toHaveTextContent('No AQI');
    expect(latestMap().fitBounds).toHaveBeenCalledTimes(1);
    expect(latestMap().flyTo).not.toHaveBeenCalled();
    expect(maplibregl.Map).toHaveBeenCalledTimes(1);
  });

  it('leaves an intentionally empty viewport alone and does not refetch on pan', async () => {
    mockedFetchJson.mockResolvedValue([device]);
    renderLayer('devices');
    await waitFor(() => expect(document.querySelector('[data-map-marker-key]')).toBeInTheDocument());
    vi.mocked(latestMap().getBounds).mockReturnValue({ getWest: () => 80, getEast: () => 90, getSouth: () => 0, getNorth: () => 10 } as ReturnType<maplibregl.Map['getBounds']>);
    event('movestart', { originalEvent: new Event('pointerdown') });
    event('moveend');
    expect(screen.getByTestId('map-empty-state')).toHaveTextContent('No devices');
    expect(latestMap().fitBounds).not.toHaveBeenCalled();
    expect(latestMap().flyTo).not.toHaveBeenCalled();
    expect(mockedFetchJson).toHaveBeenCalledTimes(1);
  });

  it.each(['pan', 'search', 'location'] as const)('protects explicit %s while initial data is still loading', async navigation => {
    let resolve!: (rows: typeof device[]) => void;
    mockedFetchJson.mockImplementation(() => new Promise(complete => { resolve = complete; }));
    const view = renderLayer('devices');
    await waitFor(() => expect(latestMap().on).toHaveBeenCalledWith('load', expect.anything()));
    if (navigation === 'pan') event('movestart', { originalEvent: new Event('wheel') });
    else view.rerender(<MemoryRouter><MapLibreMap {...props('devices')}
      {...(navigation === 'search' ? { flyToCoords: { lat: 1, lng: 2, zoom: 10 } } : { resetTrigger: 1 })} /></MemoryRouter>);
    await act(async () => resolve([{ ...device, longitude: 120 }]));
    expect(latestMap().fitBounds).not.toHaveBeenCalled();
    if (navigation !== 'pan') expect(latestMap().flyTo).toHaveBeenCalledTimes(1);
  });
  it.each(layers)('resets %s consistently for each geolocation state and result count after search', async layer => {
    for (const locationState of ['available', 'denied', 'unanswered']) {
      Object.defineProperty(navigator, 'geolocation', { configurable: true, value: {
        getCurrentPosition: vi.fn((success, fail) => {
          if (locationState === 'available') success({ coords: { latitude: 37, longitude: -122 } });
          if (locationState === 'denied') fail({ code: 1 });
        }),
      } });
      for (const count of [0, 1, 2]) {
        mockedFetchJson.mockResolvedValue(Array.from({length: count}, (_, index) => layer === 'devices'
          ? {...device, device_id: index + 1, longitude: -74 + index}
          : {...measurement, device: {...device, device_id: index + 1, longitude: -74 + index}}));
        mockedGetLatest.mockResolvedValue({...eligibleCollection, count, results: Array.from({length: count}, (_, index) =>
          ({...eligibleCollection.results[0], device_id: index + 1, longitude: -74 + index}))});
        const view = renderLayer(layer, {resetTrigger: 0});
        await waitFor(() => expect(document.querySelector('.map-loading')).not.toBeInTheDocument());
        view.rerender(<MemoryRouter><MapLibreMap {...props(layer)} resetTrigger={0} flyToCoords={{ lat: 51.5, lng: -0.12, zoom: 12 }} /></MemoryRouter>);
        expect(latestMap().flyTo).toHaveBeenLastCalledWith(expect.objectContaining({center: [-0.12, 51.5]}));
        view.rerender(<MemoryRouter><MapLibreMap {...props(layer)} resetTrigger={1} /></MemoryRouter>);
        expect(latestMap().flyTo).toHaveBeenLastCalledWith({center: locationState === 'available' ? [-122, 37] : [0, 0], zoom: locationState === 'available' ? 10 : 2, duration: 500});
        view.unmount();
      }
    }
  });

  it('restores the entry camera before an immediate geolocation response', async () => {
    renderLayer('devices', { initialViewport: { lat: 51.5, lng: -0.12, zoom: 10 } });
    await waitFor(() => expect(document.querySelector('.map-loading')).not.toBeInTheDocument());
    expect(vi.mocked(maplibregl.Map).mock.calls.at(-1)![0]).toMatchObject({ center: [-0.12, 51.5], zoom: 10 });
    expect(latestMap().jumpTo).not.toHaveBeenCalled();
    expect(latestMap().fitBounds).not.toHaveBeenCalled();
  });

  it.each(layers)('honors an explicit %s device over location and a restored camera', async layer => {
    let locate!: PositionCallback;
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: {
      getCurrentPosition: vi.fn(success => {
        locate = success;
        success({ coords: { latitude: 37, longitude: -122 } });
      }),
    } });
    mockedFetchJson.mockImplementation(async path => String(path).includes('/sensors') ? []
      : layer === 'devices' ? [device] : [measurement]);
    mockedGetLatest.mockResolvedValue({ ...eligibleCollection, results: eligibleCollection.results.map(result => ({ ...result, device_id: 901 })) });
    renderLayer(layer, { initialDeviceId: 901, initialViewport: { lat: 40, lng: 80, zoom: 5 } });
    await waitFor(() => expect(latestMap().easeTo).toHaveBeenCalled());
    expect(latestMap().jumpTo).not.toHaveBeenCalled();
    expect(latestMap().fitBounds).not.toHaveBeenCalled();
    const cameraCalls = vi.mocked(latestMap().easeTo).mock.calls.length;
    act(() => locate({ coords: { latitude: 37, longitude: -122 } } as GeolocationPosition));
    expect(latestMap().jumpTo).not.toHaveBeenCalled();
    expect(latestMap().easeTo).toHaveBeenCalledTimes(cameraCalls);
  });

  it('creates a usable map while geolocation remains unanswered and ignores late location after search', async () => {
    let locate!: PositionCallback;
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: {
      getCurrentPosition: vi.fn(success => { locate = success; }),
    } });
    const view = renderLayer('devices');
    await waitFor(() => expect(latestMap().on).toHaveBeenCalledWith('load', expect.anything()));
    view.rerender(<MemoryRouter><MapLibreMap {...props('measurements')} flyToCoords={{lat: 1, lng: 2, zoom: 10}} /></MemoryRouter>);
    act(() => locate({coords: {latitude: 50, longitude: 0}} as GeolocationPosition));
    expect(latestMap().jumpTo).not.toHaveBeenCalled();
    expect(latestMap().flyTo).toHaveBeenLastCalledWith(expect.objectContaining({center:[2, 1]}));
    view.rerender(<MemoryRouter><MapLibreMap {...props('us_epa')} resetTrigger={1} /></MemoryRouter>);
    expect(latestMap().flyTo).toHaveBeenLastCalledWith({center:[0, 50], zoom:10, duration:500});
    expect(maplibregl.Map).toHaveBeenCalledTimes(1);
  });

});
