import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { DeviceAirQualityIndexResult, UsEpaSo2Candidate } from '../airQualityIndex';
import UsEpaSo2Details from '../components/UsEpaSo2Details';


const oneHourCandidate: UsEpaSo2Candidate = {
  candidate_status: 'calculated',
  calculation_code: 'so2_1_hour_capped_at_200',
  aggregation_period: '1h',
  interval_started_at: '2025-02-02T11:00:00Z',
  interval_ended_at: '2025-02-02T12:00:00Z',
  evaluation_interval_started_at: '2025-02-01T12:00:00Z',
  evaluation_interval_ended_at: '2025-02-02T12:00:00Z',
  normalized_concentration: 305,
  normalized_unit: 'ppb',
  preprocessed_concentration: 305,
  numeric_value: 200,
  category_code: 'unhealthy',
  category_label: 'Unhealthy',
  aqi_scale_status: 'within_0_to_500',
  coverage_status: 'complete',
  expected_hour_count: 24,
  valid_hour_count: 24,
  exclusion_reason: null,
  measurement_ids: [24],
  reference_basis: [],
};

const twentyFourHourCandidate: UsEpaSo2Candidate = {
  ...oneHourCandidate,
  candidate_status: 'not_applicable',
  calculation_code: 'so2_24_hour_high',
  aggregation_period: '24h',
  interval_started_at: '2025-02-01T12:00:00Z',
  normalized_concentration: 108.5,
  preprocessed_concentration: 108,
  numeric_value: null,
  category_code: null,
  category_label: null,
  aqi_scale_status: null,
  exclusion_reason: 'so2_24_hour_not_applicable',
  measurement_ids: Array.from({ length: 24 }, (_, index) => index + 1),
};

const result = {
  parameter_code: 'so2',
  product_display_name: 'Sulfur Dioxide AQI',
  selected_aggregation_period: '1h',
  selected_calculation_code: 'so2_1_hour_capped_at_200',
  sensor_id: 8,
  so2_1_hour_candidate: oneHourCandidate,
  so2_24_hour_candidate: twentyFourHourCandidate,
  so2_candidate_sensor_evaluations: [{
    sensor_id: 8,
    input_unit_code: 'ppm',
    input_unit_symbol: 'ppm',
  }],
} as DeviceAirQualityIndexResult;

describe('UsEpaSo2Details', () => {
  it('shows the selected capped basis and both backend-provided candidates', () => {
    render(<UsEpaSo2Details result={result} />);

    expect(screen.getByText('1-hour maximum capped at AQI 200')).toBeInTheDocument();
    expect(screen.getByText('305 ppb')).toBeInTheDocument();
    expect(screen.getByText('AQI 200 · 305 ppb')).toBeInTheDocument();
    expect(screen.getByText('Not applicable')).toBeInTheDocument();
    expect(screen.getByText('ppm → ppb')).toBeInTheDocument();
    expect(screen.getByText(/EPA guidance assigns AQI 200/i)).toBeInTheDocument();
    expect(screen.getByText(/CompassAQ policy/i)).toBeInTheDocument();
  });

  it('does not imply an unsupported candidate unit was converted', () => {
    render(<UsEpaSo2Details result={{
      ...result,
      selected_aggregation_period: null,
      selected_calculation_code: null,
      sensor_id: null,
      exclusion_reason: 'no_eligible_sensor_stream',
      so2_candidate_sensor_evaluations: [{
        ...result.so2_candidate_sensor_evaluations![0],
        input_unit_code: 'ug_m3',
        input_unit_symbol: 'µg/m³',
      }],
    }} />);

    expect(screen.getByText('No candidate selected')).toBeInTheDocument();
    expect(screen.getByText('µg/m³')).toBeInTheDocument();
    expect(screen.queryByText(/µg\/m³ → ppb/)).not.toBeInTheDocument();
  });
});
