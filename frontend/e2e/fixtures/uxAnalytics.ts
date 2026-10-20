// Synthetic AQI metadata and history for the focused UX acceptance tests.
import type { AirQualityIndexStandardMetadata, AirQualityIndexAnalyticsHistory } from '../../src/airQualityIndex';
export const standards: AirQualityIndexStandardMetadata[] = [
  {
    standard_code: 'us_epa', display_name: 'U.S. EPA AQI', methodology_version: '2024', result_kind: 'numeric',
    averaging_minutes: 60, required_averaging_period: null, supported_parameter_codes: ['pm25'], normalized_unit: 'AQI', is_default: true,
    categories: [{ code: 'moderate', label: 'Moderate', internal_severity_rank: 2, color: '#ffff00' }],
    default_product_code: 'us_epa.pm25.nowcast', products: [{
      product_code: 'us_epa.pm25.nowcast', display_name: 'PM2.5 NowCast AQI', parameter_code: 'pm25', calculation_code: 'pm_nowcast',
      aggregation_period: '12h_nowcast', aggregation_display_name: 'NowCast', result_scope: 'pollutant', is_parameter_default: true,
      availability_status: 'available', availability_reason: null, history_status: 'available', history_interval: 'utc_hour', maximum_history_interval_count: 2160,
    }],
  },
  {
    standard_code: 'eea_european', display_name: 'European Air Quality Index', methodology_version: '2024', result_kind: 'categorical',
    averaging_minutes: 60, required_averaging_period: '1h', supported_parameter_codes: ['pm25'], normalized_unit: 'µg/m³', is_default: false,
    categories: [{ code: 'good', label: 'Good', internal_severity_rank: 1, color: '#50f0e6' }, { code: 'poor', label: 'Poor', internal_severity_rank: 4, color: '#ff5050' }],
    default_product_code: 'eea_european.overall.hourly', products: [{
      product_code: 'eea_european.overall.hourly', display_name: 'Overall hourly European AQI', parameter_code: null,
      calculation_code: 'worst_available_category', aggregation_period: '1h', aggregation_display_name: 'Hourly', result_scope: 'overall',
      is_parameter_default: false, availability_status: 'available', availability_reason: null, history_status: 'available',
      history_interval: 'utc_hour', maximum_history_interval_count: 2160,
    }],
  },
];

function aqiPoint(overrides: Record<string, unknown> = {}) {
  return {
    observed_at: '2026-08-01T01:00:00Z', interval_started_at: '2026-08-01T00:00:00Z', interval_ended_at: '2026-08-01T01:00:00Z',
    represented_local_date: null, numeric_value: 74, category_code: 'moderate', category_label: 'Moderate', normalized_concentration: 22.1234,
    preprocessed_concentration: 22.1,
    normalized_unit: 'µg/m³', calculation_status: 'calculated' as const, eligibility_status: 'eligible' as const, coverage_status: 'complete' as const,
    exclusion_reason: null, selected_calculation_code: 'pm_nowcast', selected_aggregation_period: '12h_nowcast', dominant_pollutants: ['pm25'],
    available_pollutants: ['pm25'], missing_pollutants: [], ineligible_pollutants: [], ...overrides,
  };
}

export const aqiHistory: AirQualityIndexAnalyticsHistory = {
  range_started_at: '2026-08-01T00:00:00Z', range_ended_at: '2026-08-02T00:00:00Z', requested_series_count: 2, returned_series_count: 2,
  maximum_series_count: 6, maximum_hourly_interval_count: 2160, maximum_completed_day_interval_count: 366,
  series: [
    {
      standard_code: 'us_epa', standard_display_name: 'U.S. EPA AQI', methodology_version: '2024', product_code: 'us_epa.pm25.nowcast',
      product_display_name: 'PM2.5 NowCast AQI', parameter_code: 'pm25', calculation_code: 'pm_nowcast', aggregation_period: '12h_nowcast',
      result_kind: 'numeric', result_scope: 'pollutant', history_interval: 'utc_hour', device_id: 1, device_name: 'U.S. Station',
      device_friendly_name: null, device_timezone: 'UTC', source_name: 'OpenAQ', points: [aqiPoint()],
    },
    {
      standard_code: 'eea_european', standard_display_name: 'European Air Quality Index', methodology_version: '2024',
      product_code: 'eea_european.overall.hourly', product_display_name: 'Overall hourly European AQI', parameter_code: null,
      calculation_code: 'worst_available_category', aggregation_period: '1h', result_kind: 'categorical', result_scope: 'overall', history_interval: 'utc_hour',
      device_id: 2, device_name: 'European Station', device_friendly_name: null, device_timezone: 'Europe/Paris', source_name: 'OpenAQ',
      points: [aqiPoint({ numeric_value: null, category_code: 'poor', category_label: 'Poor', coverage_status: 'partial', missing_pollutants: ['no2'] })],
    },
  ],
};
