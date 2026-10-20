import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type {
  AirQualityIndexStandardMetadata,
  DeviceAirQualityIndexResult,
} from '../airQualityIndex';
import EuropeanAqiDetails from '../components/EuropeanAqiDetails';
import EuropeanAqiLegend from '../components/EuropeanAqiLegend';

const standardMetadata: AirQualityIndexStandardMetadata = {
  standard_code: 'eea_european',
  display_name: 'European Air Quality Index',
  methodology_version: 'eea_2024_bands',
  result_kind: 'categorical',
  averaging_minutes: 60,
  required_averaging_period: '1h',
  supported_parameter_codes: ['pm25', 'pm10', 'o3', 'no2', 'so2'],
  normalized_unit: 'µg/m³',
  categories: [
    { code: 'extremely_poor', label: 'Extremely poor', internal_severity_rank: 6, color: '#7D2181' },
    { code: 'good', label: 'Good', internal_severity_rank: 1, color: '#50F0E6' },
    { code: 'fair', label: 'Fair', internal_severity_rank: 2, color: '#50CCAA' },
    { code: 'moderate', label: 'Moderate', internal_severity_rank: 3, color: '#F0E641' },
    { code: 'poor', label: 'Poor', internal_severity_rank: 4, color: '#FF5050' },
    { code: 'very_poor', label: 'Very poor', internal_severity_rank: 5, color: '#960032' },
  ],
  products: [],
  default_product_code: 'eea_european.overall.hourly',
  is_default: false,
};
const overallProduct = {
  product_code: 'eea_european.overall.hourly', display_name: 'Overall hourly European AQI',
  parameter_code: null, calculation_code: 'worst_available_category', aggregation_period: '1h',
  aggregation_display_name: '1-hour average', result_scope: 'overall' as const,
  is_parameter_default: false, availability_status: 'available', availability_reason: null,
};
standardMetadata.products = [overallProduct];

const result: DeviceAirQualityIndexResult = {
  standard_code: 'eea_european', methodology_version: 'eea_2024_bands', result_kind: 'categorical',
  device_id: 11, device_name: 'station-11', device_friendly_name: 'Riverside',
  latitude: 51.5, longitude: -0.12, device_timezone: 'Europe/London', source_name: 'OpenAQ',
  observed_at: '2026-07-14T10:00:00Z', numeric_value: null,
  category_code: 'poor', category_label: 'Poor', eligibility_status: 'eligible', exclusion_reasons: [],
  dominant_pollutants: ['pm25', 'no2'],
  pollutant_results: [
    { standard_code: 'eea_european', methodology_version: 'eea_2024_bands', parameter_code: 'pm25', normalized_concentration: 30.123456, preprocessed_concentration: 30.1, normalized_unit: 'µg/m³', result_kind: 'categorical', numeric_value: null, category_code: 'poor', category_label: 'Poor', eligibility_status: 'eligible', exclusion_reason: null },
    { standard_code: 'eea_european', methodology_version: 'eea_2024_bands', parameter_code: 'o3', normalized_concentration: null, normalized_unit: null, result_kind: 'categorical', numeric_value: null, category_code: null, category_label: null, eligibility_status: 'ineligible', exclusion_reason: 'unsupported_unit' },
  ],
  coverage: { coverage_status: 'partial', available_pollutants: ['pm25', 'no2'], missing_pollutants: ['so2'], ineligible_pollutants: ['o3'], missing_or_ineligible_pollutants: ['so2', 'o3'], display_qualification: 'not_evaluated' },
  sensor_provenance: [],
};

describe('European AQI map components', () => {
  it('renders the six backend-provided categories in severity order with no numeric ranges', () => {
    render(<EuropeanAqiLegend standardMetadata={standardMetadata} product={overallProduct} />);
    const legend = screen.getByLabelText('European Air Quality Index legend');
    expect(legend.textContent).toMatch(/Good.*Fair.*Moderate.*Poor.*Very poor.*Extremely poor.*Unavailable/);
    expect(legend).not.toHaveTextContent(/\d/);
    const swatches = legend.querySelectorAll<HTMLElement>('.european-aqi-legend__swatch');
    expect(swatches[0]).toHaveStyle({ backgroundColor: '#50F0E6' });
    expect(swatches[5]).toHaveStyle({ backgroundColor: '#7D2181' });
  });

  it('shows category, tied dominant pollutants, coverage, qualification, and pollutant exclusions', () => {
    const onClose = vi.fn();
    render(
      <MemoryRouter>
        <EuropeanAqiDetails result={result} standardMetadata={standardMetadata} product={overallProduct} onClose={onClose} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'Riverside' })).toBeInTheDocument();
    expect(screen.getByText('Partial coverage')).toBeInTheDocument();
    expect(screen.getAllByText('PM2.5, NO₂')).toHaveLength(2);
    expect(screen.getByText('Not evaluated')).toBeInTheDocument();
    expect(screen.getByText(/has not evaluated the EEA station display qualification/)).toBeInTheDocument();
    expect(screen.getByText('European Air Quality Index')).toBeInTheDocument();
    expect(screen.getByText('1-hour average')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Pollutant results (2)'));
    expect(screen.getByText('Unsupported unit')).toBeInTheDocument();
    expect(screen.getByText(/Poor · 30.1 µg\/m³/)).toBeInTheDocument();
    expect(screen.queryByText(/30.123456/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close panel' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('uses calm copy when an unavailable result has no specific reason', () => {
    render(
      <MemoryRouter>
        <EuropeanAqiDetails
          result={{
            ...result,
            category_code: null,
            category_label: null,
            eligibility_status: 'ineligible',
            exclusion_reasons: [],
            coverage: { ...result.coverage, coverage_status: 'none' },
          }}
          standardMetadata={standardMetadata}
          product={overallProduct}
          onClose={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole('status')).toHaveTextContent(
      'European AQI is unavailable for this interval.',
    );
  });
});

vi.mock('../components/AqiTrendCard', () => ({
  default: () => <div data-testid="aqi-trend-card">Last 24 Hours</div>,
}));
