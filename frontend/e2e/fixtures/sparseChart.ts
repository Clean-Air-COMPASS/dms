import type { MeasurementHistoryResponse } from '../../src/measurementHistory';

export const start = '2026-08-01T00:00:00Z';
export const end = '2026-08-02T00:00:00Z';
export function history(scenario: string, count = 100): MeasurementHistoryResponse {
  const minutes = scenario === 'single' ? [60] : scenario === 'two' ? [60, 120]
    : scenario === 'sparse' ? [60, 120, 180, 240]
    : scenario === 'mixed' ? [60, 62, 64, 180, 182, 184, 300]
    : scenario === 'qc' ? [60, 62, 64, 66, 68, 70, 72]
    : Array.from({ length: count }, (_, index) => index * 2);
  return {
    sensor_id: 902, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³',
    device_name: 'Synthetic chart station', device_timezone: 'America/New_York',
    native_aggregation_code: '2m', result_aggregation_code: '2m', display_precision: 1,
    _displayAggregate: '2m', _seriesKey: 'measurement|902|pm25|2m',
    data: minutes.map((minute, index) => ({
      timestamp: new Date(Date.parse(start) + minute * 60_000).toISOString(),
      value: 12 + index % 17, is_valid: !(scenario === 'qc' && [2, 4].includes(index)),
      ...(scenario === 'qc' && [1, 2, 4].includes(index) ? { qc_results: [{
        check_code: 'max_value', evaluation_status: 'failed' as const, passed: false,
        failure_action: index === 1 ? 'flag_for_review' as const : 'mark_invalid' as const, reason_code: null,
      }] } : {}),
    })),
  };
}
