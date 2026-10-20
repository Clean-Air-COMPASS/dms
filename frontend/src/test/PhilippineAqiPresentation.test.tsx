import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { formatAqiValue } from '../aqi';
import type { AirQualityIndexStandardMetadata } from '../airQualityIndex';
import AqiLegend from '../components/AqiLegend';
import { getExclusionReasonLabel } from '../airQualityIndexPresentation';
import { createRequestedMapSelection } from '../mapLayerSelection';


const standard: AirQualityIndexStandardMetadata = {
  standard_code: 'philippines_denr',
  display_name: 'Philippines Air Quality Index',
  methodology_version: 'denr_emb_aqi_2021',
  result_kind: 'numeric',
  averaging_minutes: null,
  required_averaging_period: null,
  supported_parameter_codes: ['pm25', 'pm10', 'so2', 'o3', 'co', 'no2'],
  normalized_unit: 'AQI',
  categories: [
    { code: 'good', label: 'Good', internal_severity_rank: 1, color: '#00E400', index_min: 0, index_max: 50 },
    { code: 'fair', label: 'Fair', internal_severity_rank: 2, color: '#FFFF00', index_min: 51, index_max: 100 },
    { code: 'unhealthy_for_sensitive_groups', label: 'Unhealthy for Sensitive Groups', internal_severity_rank: 3, color: '#FF7E00', index_min: 101, index_max: 150 },
    { code: 'very_unhealthy', label: 'Very Unhealthy', internal_severity_rank: 4, color: '#FF0000', index_min: 151, index_max: 200 },
    { code: 'acutely_unhealthy', label: 'Acutely Unhealthy', internal_severity_rank: 5, color: '#8F3F97', index_min: 201, index_max: 300 },
    { code: 'emergency', label: 'Emergency', internal_severity_rank: 6, color: '#7E0023', index_min: 301, index_max: 500 },
  ],
  products: [],
  default_product_code: 'philippines_denr.pm25.completed_day',
  is_default: false,
};


describe('Philippine AQI presentation', () => {
  it('selects the distinct standard from URL state', () => {
    expect(createRequestedMapSelection(
      '?standard_code=philippines_denr&product_code=philippines_denr.pm25.completed_day',
    )).toMatchObject({
      layer: 'aqi',
      standard_code: 'philippines_denr',
      air_quality_index_product_code: 'philippines_denr.pm25.completed_day',
    });
  });

  it('renders official category names and backend numeric ranges', () => {
    render(<AqiLegend standardMetadata={standard} showNoData={false} />);
    expect(screen.getByText('Fair')).toBeInTheDocument();
    expect(screen.getByText('Acutely Unhealthy')).toBeInTheDocument();
    expect(screen.getByText('Emergency')).toBeInTheDocument();
    expect(screen.getByText('301-500')).toBeInTheDocument();
  });

  it('formats Philippine numeric values with up to two decimal places', () => {
    expect(formatAqiValue(145.05, 2)).toBe('145.05');
    expect(formatAqiValue(50, 2)).toBe('50');
  });

  it('explains Philippine-specific unavailable states', () => {
    expect(getExclusionReasonLabel('published_breakpoint_gap')).toContain('published breakpoints');
    expect(getExclusionReasonLabel('subindex_not_defined_for_concentration')).toContain('does not define');
    expect(getExclusionReasonLabel('conversion_not_supported')).toContain('temperature and pressure');
  });
});
