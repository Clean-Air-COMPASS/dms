import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { DeviceAirQualityIndexResult, UsEpaOzoneCandidate } from '../airQualityIndex';
import UsEpaOzoneDetails from '../components/UsEpaOzoneDetails';


const candidate = (
  aggregationPeriod: '8h' | '1h',
  overrides: Partial<UsEpaOzoneCandidate> = {},
): UsEpaOzoneCandidate => ({
  candidate_status: 'calculated',
  aggregation_period: aggregationPeriod,
  interval_started_at: '2026-08-01T00:00:00Z',
  interval_ended_at: aggregationPeriod === '8h'
    ? '2026-08-01T08:00:00Z'
    : '2026-08-01T05:00:00Z',
  normalized_concentration: 0.078,
  normalized_unit: 'ppm',
  preprocessed_concentration: 0.078,
  numeric_value: 126,
  category_code: 'unhealthy_for_sensitive_groups',
  category_label: 'Unhealthy for Sensitive Groups',
  aqi_scale_status: 'within_0_to_500',
  coverage_status: 'complete',
  expected_hour_count: aggregationPeriod === '8h' ? 8 : 1,
  valid_hour_count: aggregationPeriod === '8h' ? 8 : 1,
  exclusion_reason: null,
  zero_substitution_used: false,
  reference_basis: [],
  ...overrides,
});

const result = {
  sensor_id: 42,
  coverage_status: 'complete',
  selected_aggregation_period: '8h',
  ozone_8_hour_candidate: candidate('8h'),
  ozone_1_hour_candidate: candidate('1h', {
    candidate_status: 'not_applicable',
    numeric_value: null,
    preprocessed_concentration: null,
    category_code: null,
    category_label: null,
    exclusion_reason: 'ozone_1_hour_not_applicable',
  }),
  ozone_candidate_sensor_evaluations: [{
    sensor_id: 42,
    input_unit_code: 'ppb',
    input_unit_symbol: 'ppb',
  }],
} as DeviceAirQualityIndexResult;


describe('UsEpaOzoneDetails', () => {
  it('shows the selected basis, both candidates, provenance, and limitation', () => {
    render(<UsEpaOzoneDetails result={result} />);

    expect(screen.getByText('Selected basis')).toBeInTheDocument();
    expect(screen.getAllByText('8-hour average').length).toBeGreaterThan(0);
    expect(screen.getByText('1-hour maximum')).toBeInTheDocument();
    expect(screen.getAllByText(/8 of 8/).length).toBeGreaterThan(0);
    expect(screen.getByText('ppb → ppm')).toBeInTheDocument();
    expect(screen.getByText(/one-hour ozone AQI does not apply/i)).toBeInTheDocument();
    expect(screen.getByText(/precautionary CompassAQ informational policy/i)).toBeInTheDocument();
    expect(screen.getByText(/official EPA reporting areas universally use/i)).toBeInTheDocument();
    expect(screen.getByText(/not EPA O₃ NowCast/i)).toBeInTheDocument();
  });

  it('uses the selected one-hour candidate for interval, coverage, and counts', () => {
    render(
      <UsEpaOzoneDetails
        result={{
          ...result,
          coverage_status: 'partial',
          selected_aggregation_period: '1h',
          ozone_8_hour_candidate: candidate('8h', {
            coverage_status: 'partial',
            valid_hour_count: 6,
            numeric_value: 172,
          }),
          ozone_1_hour_candidate: candidate('1h', {
            interval_started_at: '2026-08-01T04:00:00Z',
            interval_ended_at: '2026-08-01T05:00:00Z',
            normalized_concentration: 0.405,
            preprocessed_concentration: 0.405,
            numeric_value: 301,
            category_code: 'hazardous',
            category_label: 'Hazardous',
          }),
        }}
      />,
    );

    expect(screen.getAllByText('1-hour maximum').length).toBeGreaterThan(0);
    expect(screen.getByText('0.405 ppm')).toBeInTheDocument();
    expect(screen.getByTestId('ozone-selected-interval')).toHaveTextContent(/4:00 AM UTC.*5:00 AM UTC/);
    expect(screen.getByTestId('ozone-selected-coverage')).toHaveTextContent('Complete');
    expect(screen.getAllByText(/1 of 1/).length).toBeGreaterThan(0);
    expect(screen.getByText(/6 of 8 eligible hours/)).toBeInTheDocument();
  });

  it('shows partial zero-substitution coverage explicitly', () => {
    render(
      <UsEpaOzoneDetails
        result={{
          ...result,
          coverage_status: 'partial',
          ozone_8_hour_candidate: candidate('8h', {
            coverage_status: 'partial',
            valid_hour_count: 5,
            zero_substitution_used: true,
          }),
        }}
      />,
    );

    expect(screen.getAllByText('Partial').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/5 of 8/).length).toBeGreaterThan(0);
    expect(screen.getByText(/zero substitution was used/i)).toBeInTheDocument();
  });

  it('explains an unsupported unit when no ozone sensor can be selected', () => {
    render(
      <UsEpaOzoneDetails
        result={{
          ...result,
          sensor_id: null,
          coverage_status: 'none',
          selected_aggregation_period: null,
          ozone_candidate_sensor_evaluations: [{
            ...result.ozone_candidate_sensor_evaluations![0],
            input_unit_code: 'ug_per_m3',
            input_unit_symbol: 'µg/m³',
            blocking_reasons: ['conversion_not_supported'],
          }],
        }}
      />,
    );

    expect(screen.getByText('µg/m³')).toBeInTheDocument();
    expect(screen.queryByText(/µg\/m³ → ppm/)).not.toBeInTheDocument();
    expect(screen.getByText(/without temperature and pressure/i)).toBeInTheDocument();
  });
});
