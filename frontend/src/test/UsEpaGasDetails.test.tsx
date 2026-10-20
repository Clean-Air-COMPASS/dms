import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { DeviceAirQualityIndexResult } from '../airQualityIndex';
import UsEpaGasDetails from '../components/UsEpaGasDetails';


const result = {
  parameter_code: 'co',
  product_display_name: 'Carbon Monoxide AQI',
  preprocessed_concentration: 4.4,
  normalized_unit: 'ppm',
  window_started_at: '2025-02-02T04:00:00Z',
  window_ended_at: '2025-02-02T12:00:00Z',
  expected_observation_count: 8,
  valid_observation_count: 6,
  coverage_status: 'partial',
  calculation_status: 'calculated',
  selected_aggregation_period: '8h',
  sensor_id: 12,
  gas_candidate_sensor_evaluations: [{
    sensor_id: 12,
    input_unit_code: 'ppb',
    input_unit_symbol: 'ppb',
  }],
} as DeviceAirQualityIndexResult;

describe('UsEpaGasDetails', () => {
  it('shows the selected CO basis, conversion, interval, and partial coverage', () => {
    render(<UsEpaGasDetails result={result} />);

    expect(screen.getByText('8-hour average')).toBeInTheDocument();
    expect(screen.getByText('4.4 ppm')).toBeInTheDocument();
    expect(screen.getByText('6 of 8')).toBeInTheDocument();
    expect(screen.getByText('ppb → ppm')).toBeInTheDocument();
    expect(screen.getByTestId('gas-selected-interval')).toHaveTextContent('UTC');
    expect(screen.getByText(/not a completed-day or reporting-area AQI/i)).toBeInTheDocument();
  });

  it('shows the completed one-hour basis for nitrogen dioxide', () => {
    render(<UsEpaGasDetails result={{
      ...result,
      parameter_code: 'no2',
      product_display_name: 'Nitrogen Dioxide AQI',
      preprocessed_concentration: 53,
      normalized_unit: 'ppb',
      expected_observation_count: 1,
      valid_observation_count: 1,
      coverage_status: 'complete',
      selected_aggregation_period: '1h',
      gas_candidate_sensor_evaluations: [{
        ...result.gas_candidate_sensor_evaluations![0],
        parameter_code: 'no2',
        input_unit_code: 'ppm',
        input_unit_symbol: 'ppm',
      }],
    }} />);

    expect(screen.getByText('1-hour average')).toBeInTheDocument();
    expect(screen.getByText('53 ppb')).toBeInTheDocument();
    expect(screen.getByText('ppm → ppb')).toBeInTheDocument();
  });

  it('does not present candidate values as a selected unavailable result', () => {
    render(<UsEpaGasDetails result={{
      ...result,
      calculation_status: 'unavailable',
      selected_aggregation_period: null,
      preprocessed_concentration: null,
      normalized_unit: null,
      window_started_at: null,
      window_ended_at: null,
      expected_observation_count: null,
      valid_observation_count: null,
      coverage_status: 'none',
      sensor_id: null,
      exclusion_reason: 'no_eligible_sensor_stream',
      gas_candidate_sensor_evaluations: [{
        ...result.gas_candidate_sensor_evaluations![0],
        input_unit_code: 'ug_m3',
        input_unit_symbol: 'µg/m³',
      }],
    }} />);

    expect(screen.getByText('No result selected')).toBeInTheDocument();
    expect(screen.getByText('µg/m³')).toBeInTheDocument();
    expect(screen.queryByText(/µg\/m³ → ppm/)).not.toBeInTheDocument();
    expect(screen.queryByText('Eligible hours')).not.toBeInTheDocument();
    expect(screen.queryByText('Coverage')).not.toBeInTheDocument();
  });
});
