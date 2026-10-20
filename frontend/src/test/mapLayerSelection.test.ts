import { describe, expect, it } from 'vitest';

import type { AirQualityIndexStandardMetadata } from '../airQualityIndex';
import i18n from '../i18n';
import {
  createRequestedMapSelection,
  listAvailableAirQualityIndexProducts,
  listValidAggregationPeriods,
  normalizeSelectedDataProduct,
  type MapSelectionMetadata,
  type RequestedMapSelection,
} from '../mapLayerSelection';


const standards: AirQualityIndexStandardMetadata[] = [
  {
    standard_code: 'us_epa',
    display_name: 'U.S. EPA AQI',
    methodology_version: 'test',
    result_kind: 'numeric',
    averaging_minutes: null,
    required_averaging_period: null,
    supported_parameter_codes: ['pm25', 'pm10'],
    normalized_unit: 'AQI',
    categories: [],
    default_product_code: 'us_epa.pm25.nowcast',
    is_default: true,
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
    ],
  },
  {
    standard_code: 'eea_european',
    display_name: 'European Air Quality Index',
    methodology_version: 'eea_2024_bands',
    result_kind: 'categorical',
    averaging_minutes: 60,
    required_averaging_period: '1h',
    supported_parameter_codes: ['pm25', 'o3'],
    normalized_unit: 'µg/m³',
    categories: [{ code: 'good', label: 'Good', internal_severity_rank: 1, color: '#50F0E6' }],
    default_product_code: 'eea_european.overall.hourly',
    is_default: false,
    products: [
      {
        product_code: 'eea_european.overall.hourly', display_name: 'Overall hourly European AQI',
        parameter_code: null, calculation_code: 'worst_available_category', aggregation_period: '1h',
        aggregation_display_name: '1-hour average', result_scope: 'overall', is_parameter_default: false,
        availability_status: 'available', availability_reason: null,
      },
      {
        product_code: 'eea_european.o3.hourly', display_name: 'O₃ hourly European AQI',
        parameter_code: 'o3', calculation_code: 'hourly_category', aggregation_period: '1h',
        aggregation_display_name: '1-hour average', result_scope: 'pollutant', is_parameter_default: false,
        availability_status: 'available', availability_reason: null,
      },
    ],
  },
];

const metadata: MapSelectionMetadata = {
  parameters: [
    { code: 'pm25', display_name: 'PM2.5' },
    { code: 'temperature', display_name: 'Temperature' },
  ],
  measurement_aggregation_capabilities: [
    {
      parameter_code: 'pm25', native_aggregation_code: '1m', native_status: 'known',
      supported_aggregations: [
        { result_aggregation_code: '1m', display_name: '1 Minute', duration_minutes: 1, is_rolling: false, capability_kind: 'native', rollup_path: ['1m'], supports_latest: true, supports_history: true, formatting_status: 'configured', display_precision: 1 },
        { result_aggregation_code: '1h', display_name: '1-hour average', duration_minutes: 60, is_rolling: false, capability_kind: 'direct_rollup', rollup_path: ['1m', '1h'], supports_latest: true, supports_history: true, formatting_status: 'configured', display_precision: 1 },
        { result_aggregation_code: '24h', display_name: '24-hour average', duration_minutes: 1440, is_rolling: false, capability_kind: 'chained_rollup', rollup_path: ['1m', '1h', '24h'], supports_latest: true, supports_history: true, formatting_status: 'configured', display_precision: 1 },
      ],
    },
    {
      parameter_code: 'temperature', native_aggregation_code: '1m', native_status: 'known',
      supported_aggregations: [
        { result_aggregation_code: '1m', display_name: '1 Minute', duration_minutes: 1, is_rolling: false, capability_kind: 'native', rollup_path: ['1m'], supports_latest: true, supports_history: true, formatting_status: 'not_configured', display_precision: null },
      ],
    },
  ],
  air_quality_index_standards: standards,
};

function request(overrides: Partial<RequestedMapSelection>): RequestedMapSelection {
  return {
    layer: 'devices',
    parameter_code: '',
    aggregation_period: '',
    air_quality_index_product_code: '',
    standard_code: '',
    ...overrides,
  };
}


describe('map selection URL parsing', () => {
  it('recognizes all three layers and reads the explicit product code', () => {
    expect(createRequestedMapSelection('?mode=devices').layer).toBe('devices');
    expect(createRequestedMapSelection('?mode=pollutants').layer).toBe('measurements');
    expect(createRequestedMapSelection('?display_mode=us_epa').layer).toBe('aqi');
    expect(createRequestedMapSelection('?standard_code=eea_european').standard_code).toBe('eea_european');
    expect(createRequestedMapSelection('?product_code=us_epa.pm10.nowcast').air_quality_index_product_code)
      .toBe('us_epa.pm10.nowcast');
  });
});

describe('pure selection normalization', () => {
  it('defaults Devices to All parameter and All time resolution', () => {
    expect(normalizeSelectedDataProduct(request({ layer: 'devices' }), metadata)).toEqual({
      selection: {
        layer: 'devices', parameter_code: '', aggregation_period: '', air_quality_index_product_code: '',
      },
      unavailable_reason: null,
    });
  });

  it('preserves a valid device parameter and drops its legacy time resolution', () => {
    const normalized = normalizeSelectedDataProduct(request({
      layer: 'devices', parameter_code: 'temperature', aggregation_period: '1m',
    }), metadata);
    expect(normalized.selection.parameter_code).toBe('temperature');
    expect(normalized.selection.aggregation_period).toBe('');
  });

  it('uses explicit All when a device aggregation is invalid', () => {
    const normalized = normalizeSelectedDataProduct(request({
      layer: 'devices', parameter_code: 'temperature', aggregation_period: '24h',
    }), metadata);
    expect(normalized.selection.aggregation_period).toBe('');
  });

  it('uses the explicit PM2.5 measurement default and preserves valid periods', () => {
    const defaulted = normalizeSelectedDataProduct(request({ layer: 'measurements' }), metadata);
    expect(defaulted.selection.parameter_code).toBe('pm25');
    const preserved = normalizeSelectedDataProduct(request({
      layer: 'measurements', parameter_code: 'pm25', aggregation_period: '24h',
    }), metadata);
    expect(preserved.selection.aggregation_period).toBe('24h');
  });

  it('does not infer a measurement default from list ordering when PM2.5 is missing', () => {
    const withoutPm25 = { ...metadata, parameters: [{ code: 'temperature', display_name: 'Temperature' }] };
    const normalized = normalizeSelectedDataProduct(request({ layer: 'measurements' }), withoutPm25);
    expect(normalized.selection.parameter_code).toBe('');
    expect(normalized.unavailable_reason).toMatch(/default PM2\.5/);
  });

  it('uses the backend-declared global and per-standard AQI defaults', () => {
    const defaulted = normalizeSelectedDataProduct(request({ layer: 'aqi' }), metadata);
    expect(defaulted.selection.air_quality_index_product_code).toBe('us_epa.pm25.nowcast');
    const european = normalizeSelectedDataProduct(request({
      layer: 'aqi', standard_code: 'eea_european',
    }), metadata);
    expect(european.selection.air_quality_index_product_code).toBe('eea_european.overall.hourly');
  });

  it('preserves a selected AQI product and its exact aggregation identity', () => {
    const normalized = normalizeSelectedDataProduct(request({
      layer: 'aqi', air_quality_index_product_code: 'us_epa.pm10.nowcast',
    }), metadata);
    expect(normalized.selection).toEqual({
      layer: 'aqi', parameter_code: 'pm10', aggregation_period: '12h_nowcast',
      air_quality_index_product_code: 'us_epa.pm10.nowcast',
    });
  });

  it('does not silently fall back when a requested AQI standard is unavailable', () => {
    const normalized = normalizeSelectedDataProduct(request({
      layer: 'aqi', standard_code: 'missing_standard',
    }), metadata);
    expect(normalized.selection.air_quality_index_product_code).toBe('');
    expect(normalized.unavailable_reason).toMatch(/missing_standard/);
  });

  it('does not silently translate removed product codes', () => {
    const normalized = normalizeSelectedDataProduct(request({
      layer: 'aqi', air_quality_index_product_code: 'us_epa.pm25.daily',
    }), metadata);
    expect(normalized.selection.air_quality_index_product_code).toBe('');
    expect(normalized.unavailable_reason).toMatch(/pm25\.daily/);
  });

  it('does not silently translate legacy AQI aggregation URLs', () => {
    const normalized = normalizeSelectedDataProduct(request({
      layer: 'aqi', standard_code: 'us_epa', aggregation_period: 'aqi-nowcast',
    }), metadata);
    expect(normalized.selection.air_quality_index_product_code).toBe('');
    expect(normalized.unavailable_reason).toMatch(/Legacy AQI selection/);
  });

  it('uses only backend-advertised products as the selector source', () => {
    expect(listAvailableAirQualityIndexProducts(standards).map((product) => product.product_code))
      .toContain('us_epa.pm10.nowcast');
  });
});

describe('aggregation compatibility', () => {
  it('lists the union for Devices and only parameter-compatible periods for Measurements', () => {
    expect(listValidAggregationPeriods(metadata, 'devices', '').map((period) => period.code))
      .toEqual(['1m', '1h', '24h']);
    expect(listValidAggregationPeriods(metadata, 'measurements', 'temperature').map((period) => period.code))
      .toEqual(['1m']);
  });

  it('uses localized labels for stable aggregation codes', async () => {
    await i18n.changeLanguage('es');
    expect(listValidAggregationPeriods(metadata, 'devices', '')[1]).toEqual({
      code: '1h',
      display_name: 'Promedio de 1 hora',
    });
    await i18n.changeLanguage('en');
  });
});
