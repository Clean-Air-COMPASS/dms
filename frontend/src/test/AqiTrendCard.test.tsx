import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getAirQualityIndexHistory,
  getUsEpaCompletedDayHistory,
  type AirQualityIndexCollection,
  type AirQualityIndexProductMetadata,
  type AirQualityIndexStandardMetadata,
  type UsEpaCompletedDayHistorySummary,
} from '../airQualityIndex';
import { createCurrentConditionHistoryRange } from '../aqiTrend';
import AqiTrendCard from '../components/AqiTrendCard';


vi.mock('../airQualityIndex', async (importActual) => {
  const actual = await importActual<typeof import('../airQualityIndex')>();
  return {
    ...actual,
    getAirQualityIndexHistory: vi.fn(),
    getUsEpaCompletedDayHistory: vi.fn(),
  };
});

vi.mock('react-chartjs-2', () => ({
  Line: ({ data, options }: { data: unknown; options: unknown }) => (
    <div data-testid="aqi-chart-model">{JSON.stringify({ data, options })}</div>
  ),
}));


const standardMetadata: AirQualityIndexStandardMetadata = {
  standard_code: 'us_epa',
  display_name: 'U.S. EPA AQI',
  methodology_version: 'test',
  result_kind: 'numeric',
  averaging_minutes: 60,
  required_averaging_period: '12h_nowcast',
  supported_parameter_codes: ['pm25'],
  normalized_unit: 'AQI',
  categories: [
    { code: 'moderate', label: 'Moderate', internal_severity_rank: 2, color: '#FFFF00' },
  ],
  products: [],
  default_product_code: 'us_epa.pm25.nowcast',
  is_default: true,
};

const nowcastProduct: AirQualityIndexProductMetadata = {
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
};

const completedDayProduct: AirQualityIndexProductMetadata = {
  ...nowcastProduct,
  product_code: 'us_epa.pm25.completed_day',
  display_name: 'U.S. EPA PM2.5 Completed-Day AQI',
  calculation_code: 'pm_completed_local_day',
  aggregation_period: 'completed_local_day',
  aggregation_display_name: 'Completed Day',
  product_kind: 'completed_day',
};

const hourlyCollection: AirQualityIndexCollection = {
  standard_code: 'us_epa',
  methodology_version: 'test',
  result_kind: 'numeric',
  count: 2,
  results: [
    {
      standard_code: 'us_epa', methodology_version: 'test', result_kind: 'numeric',
      device_id: 42, device_name: 'station-42', device_friendly_name: 'Riverside',
      latitude: 1, longitude: 2, device_timezone: 'UTC', source_name: 'OpenAQ',
      observed_at: '2026-07-14T09:00:00Z', window_ended_at: '2026-07-14T07:00:00Z',
      numeric_value: 73, category_code: 'moderate', category_label: 'Moderate',
      eligibility_status: 'eligible', exclusion_reasons: [], dominant_pollutants: ['pm25'],
      pollutant_results: [], coverage: { coverage_status: 'complete', available_pollutants: ['pm25'], missing_pollutants: [], ineligible_pollutants: [], missing_or_ineligible_pollutants: [], display_qualification: 'not_evaluated' },
      sensor_provenance: [], exclusion_reason: null,
    },
    {
      standard_code: 'us_epa', methodology_version: 'test', result_kind: 'numeric',
      device_id: 42, device_name: 'station-42', device_friendly_name: 'Riverside',
      latitude: 1, longitude: 2, device_timezone: 'UTC', source_name: 'OpenAQ',
      observed_at: '2026-07-14T10:00:00Z', window_ended_at: '2026-07-14T10:00:00Z',
      numeric_value: null, category_code: null, category_label: null,
      eligibility_status: 'ineligible', exclusion_reasons: ['insufficient_data'], dominant_pollutants: [],
      pollutant_results: [], coverage: { coverage_status: 'none', available_pollutants: [], missing_pollutants: [], ineligible_pollutants: ['pm25'], missing_or_ineligible_pollutants: ['pm25'], display_qualification: 'not_evaluated' },
      sensor_provenance: [], exclusion_reason: 'insufficient_data',
    },
  ],
};

const completedDayHistory: UsEpaCompletedDayHistorySummary = {
  standard_code: 'us_epa', methodology_version: 'test', result_kind: 'numeric',
  product_code: completedDayProduct.product_code,
  product_display_name: completedDayProduct.display_name,
  product_kind: 'completed_day', parameter_code: 'pm25', methodology_code: null,
  methodology_revision: null, methodology_effective_date: null,
  start_local_date: '2026-07-24', end_local_date: '2026-07-30', requested_day_count: 7,
  returned_device_count: 1, returned_result_count: 1, calculated_result_count: 1,
  unavailable_result_count: 0, maximum_supported_day_count: 366, detail: 'summary',
  device_series: [{
    device_id: 42, device_name: 'station-42', device_friendly_name: 'Riverside',
    latitude: 1, longitude: 2, device_timezone: 'UTC', source_name: 'OpenAQ',
    results: [{
      represented_local_date: '2026-07-30', local_day_started_at: null,
      local_day_ended_at: null, utc_window_started_at: null, utc_window_ended_at: null,
      expected_hour_count: 24, valid_hour_count: 24, required_valid_hour_count: 18,
      required_completeness_fraction: 0.75, achieved_completeness_fraction: 1,
      daily_concentration: 12, preprocessed_concentration: 12, normalized_unit: 'µg/m³',
      calculation_status: 'calculated', coverage_status: 'complete', numeric_value: 52,
      category_code: 'moderate', category_label: 'Moderate', aqi_scale_status: 'within_0_to_500',
      selected_sensor_id: 7, blocking_reasons: [], audit_flags: [],
    }],
  }],
};

const mockedGetHourlyHistory = vi.mocked(getAirQualityIndexHistory);
const mockedGetCompletedDayHistory = vi.mocked(getUsEpaCompletedDayHistory);


function renderTrend(product: AirQualityIndexProductMetadata = nowcastProduct) {
  return render(
    <AqiTrendCard
      standardMetadata={standardMetadata}
      product={product}
      deviceId={42}
      deviceName="Riverside"
      sourceName="OpenAQ"
      latestObservedAt="2026-07-14T10:00:00Z"
      latestRepresentedLocalDate="2026-07-30"
    />,
  );
}


describe('AqiTrendCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetHourlyHistory.mockResolvedValue(hourlyCollection);
    mockedGetCompletedDayHistory.mockResolvedValue(completedDayHistory);
  });

  it('builds the exact 24-hour evaluation range', () => {
    expect(createCurrentConditionHistoryRange('2026-07-14T10:00:00Z')).toEqual({
      start: '2026-07-13T11:00:00.000Z',
      end: '2026-07-14T11:00:00.000Z',
    });
  });

  it('requests the selected current-condition product and shows partial history', async () => {
    renderTrend();
    expect(screen.getByRole('status')).toHaveTextContent('Loading AQI history');
    expect(await screen.findByText('Last 24 Hours')).toBeInTheDocument();
    expect(mockedGetHourlyHistory).toHaveBeenCalledWith({
      standard_code: 'us_epa',
      product_code: 'us_epa.pm25.nowcast',
      start: '2026-07-13T11:00:00.000Z',
      end: '2026-07-14T11:00:00.000Z',
      device_id: 42,
      external_api_name: 'OpenAQ',
    }, expect.any(AbortSignal));
    expect(screen.getByTestId('aqi-chart-model')).toHaveTextContent('73');
    expect(screen.getByTestId('aqi-chart-model')).toHaveTextContent(
      `{"x":${new Date('2026-07-14T09:00:00Z').getTime()},"y":73`,
    );
    expect(screen.getByRole('status')).toHaveTextContent('23 unavailable intervals');
  });

  it('requests exactly seven completed local days', async () => {
    renderTrend(completedDayProduct);
    expect(await screen.findByText('Last 7 Days')).toBeInTheDocument();
    expect(mockedGetCompletedDayHistory).toHaveBeenCalledWith({
      product_code: 'us_epa.pm25.completed_day',
      start_local_date: '2026-07-24',
      end_local_date: '2026-07-30',
      device_id: 42,
      external_api_name: 'OpenAQ',
    }, expect.any(AbortSignal));
    expect(mockedGetHourlyHistory).not.toHaveBeenCalled();
    expect(screen.getByTestId('aqi-chart-model')).toHaveTextContent('"unit":"day"');
    expect(screen.getByTestId('aqi-chart-model')).toHaveTextContent('"day":"MMM d"');
    expect(screen.getByTestId('aqi-chart-model')).toHaveTextContent('Local date');
  });

  it('shows a calm unavailable-history state without fabricating zero', async () => {
    mockedGetHourlyHistory.mockResolvedValue({ ...hourlyCollection, count: 0, results: [] });
    renderTrend();
    expect(await screen.findByText(/No historical AQI values are available/)).toBeInTheDocument();
    expect(screen.queryByTestId('aqi-chart-model')).not.toBeInTheDocument();
  });

  it('contains an API error within the chart card', async () => {
    mockedGetHourlyHistory.mockRejectedValue(new Error('network failed'));
    renderTrend();
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(
      'Historical AQI could not be loaded',
    ));
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
