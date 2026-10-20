import { describe, expect, it } from 'vitest';
import {
  getMeasurementAggregationOptions,
  type MeasurementAggregationCapability,
} from '../measurementAggregations';

const capabilities: MeasurementAggregationCapability[] = [{
  parameter_code: 'pm25',
  native_aggregation_code: '2m',
  native_status: 'known',
  supported_aggregations: [
    { result_aggregation_code: '2m', display_name: '2 Minutes', duration_minutes: 2, is_rolling: false, capability_kind: 'native', rollup_path: ['2m'], supports_latest: true, supports_history: true, formatting_status: 'not_configured', display_precision: null },
    { result_aggregation_code: '1h', display_name: '1-hour average', duration_minutes: 60, is_rolling: false, capability_kind: 'direct_rollup', rollup_path: ['2m', '1h'], supports_latest: true, supports_history: true, formatting_status: 'configured', display_precision: 1 },
    { result_aggregation_code: '8h', display_name: '8-hour average', duration_minutes: 480, is_rolling: false, capability_kind: 'chained_rollup', rollup_path: ['2m', '1h', '8h'], supports_latest: true, supports_history: true, formatting_status: 'configured', display_precision: 1 },
    { result_aggregation_code: '24h', display_name: '24-hour average', duration_minutes: 1440, is_rolling: false, capability_kind: 'chained_rollup', rollup_path: ['2m', '1h', '24h'], supports_latest: true, supports_history: true, formatting_status: 'configured', display_precision: 1 },
    { result_aggregation_code: 'rolling_24h', display_name: 'Rolling 24-hour', duration_minutes: 1440, is_rolling: true, capability_kind: 'chained_rollup', rollup_path: ['2m', '1h', 'rolling_24h'], supports_latest: true, supports_history: false, formatting_status: 'configured', display_precision: null },
  ],
}, {
  parameter_code: 'pm25',
  native_aggregation_code: null,
  native_status: 'unknown',
  supported_aggregations: [
    { result_aggregation_code: 'raw', display_name: 'Raw/latest (native period unknown)', duration_minutes: null, is_rolling: false, capability_kind: 'native', rollup_path: ['raw'], supports_latest: true, supports_history: true, formatting_status: 'not_configured', display_precision: null },
  ],
}];

describe('backend-owned measurement aggregation choices', () => {
  it('presents native and every backend-supported fixed history target', () => {
    expect(getMeasurementAggregationOptions({
      nativeAggregationCode: '2m', parameterCode: 'pm25', capabilities,
    })).toEqual([
      { code: '2m', display: '2-minute (native)', displayPrecision: null },
      { code: '1h', display: '1-hour average', displayPrecision: 1 },
      { code: '8h', display: '8-hour average', displayPrecision: 1 },
      { code: '24h', display: '24-hour average', displayPrecision: 1 },
    ]);
  });

  it('does not infer options for a native period absent from backend metadata', () => {
    expect(getMeasurementAggregationOptions({
      nativeAggregationCode: '1m', parameterCode: 'pm25', capabilities,
    })).toEqual([]);
  });

  it('keeps unknown-native streams raw-only', () => {
    expect(getMeasurementAggregationOptions({
      nativeAggregationCode: null, parameterCode: 'pm25', capabilities,
    }).map((option) => option.code)).toEqual(['raw']);
  });

  it('shows rolling products only for latest-result consumers', () => {
    expect(getMeasurementAggregationOptions({
      nativeAggregationCode: '2m', parameterCode: 'pm25', capabilities, usage: 'latest',
    }).map((option) => option.code)).toContain('rolling_24h');
    expect(getMeasurementAggregationOptions({
      nativeAggregationCode: '2m', parameterCode: 'pm25', capabilities, usage: 'history',
    }).map((option) => option.code)).not.toContain('rolling_24h');
  });
});
