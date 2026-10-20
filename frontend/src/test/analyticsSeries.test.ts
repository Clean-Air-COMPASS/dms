import { describe, expect, it } from 'vitest';
import {
  analyticsScaleGroupKey,
  analyticsSeriesKey,
  countAnalyticsScaleGroups,
  parseAnalyticsSeries,
  readAnalyticsSeries,
  writeAnalyticsSeries,
  type AnalyticsSeriesSelection,
} from '../analyticsSeries';


describe('mixed Analytics series URL state', () => {
  it('round-trips ordered measurement and AQI selections with stable identifiers', () => {
    const selectedSeries: AnalyticsSeriesSelection[] = [
      { kind: 'measurement', sensor_id: 10, parameter_code: 'pm25', aggregation_code: '2m' },
      { kind: 'measurement', sensor_id: 10, parameter_code: 'pm25', aggregation_code: '1h' },
      { kind: 'aqi', standard_code: 'us_epa', product_code: 'us_epa.pm25.nowcast', device_id: 4 },
    ];
    const params = writeAnalyticsSeries(new URLSearchParams('recency=24h&timezone=utc'), selectedSeries);

    expect(params.getAll('series')).toEqual([
      'measurement|10|pm25|2m',
      'measurement|10|pm25|1h',
      'aqi|us_epa|us_epa.pm25.nowcast|4',
    ]);
    expect(readAnalyticsSeries(params)).toEqual(selectedSeries);
    expect(params.get('recency')).toBe('24h');
    expect(params.get('timezone')).toBe('utc');
  });

  it('accepts legacy Measurement and AQI links without preserving their split layer', () => {
    expect(readAnalyticsSeries(new URLSearchParams(
      'layer=measurements&sensor_id=3&parameter=pm25&aggregate=hour&overlay=4:pm25:day',
    ))).toEqual([
      { kind: 'measurement', sensor_id: 3, parameter_code: 'pm25', aggregation_code: '1h' },
      { kind: 'measurement', sensor_id: 4, parameter_code: 'pm25', aggregation_code: '24h' },
    ]);
    expect(readAnalyticsSeries(new URLSearchParams(
      'layer=aqi&standard_code=eea_european&product_code=eea_european.overall.hourly&device_id=7&compare=us_epa|us_epa.pm25.nowcast|7',
    ))).toEqual([
      { kind: 'aqi', standard_code: 'eea_european', product_code: 'eea_european.overall.hourly', device_id: 7 },
      { kind: 'aqi', standard_code: 'us_epa', product_code: 'us_epa.pm25.nowcast', device_id: 7 },
    ]);
  });

  it('rejects malformed series values and removes duplicate selections', () => {
    const params = new URLSearchParams();
    params.append('series', 'measurement|12|pm25|1h');
    params.append('series', 'measurement|12|pm25|1h');
    params.append('series', 'aqi|missing-device');

    expect(readAnalyticsSeries(params)).toEqual([
      { kind: 'measurement', sensor_id: 12, parameter_code: 'pm25', aggregation_code: '1h' },
    ]);
    expect(parseAnalyticsSeries('measurement|0|pm25|1h')).toBeNull();
  });

  it('keeps the first six unique URL series in deterministic primary-to-overlay order', () => {
    const params = new URLSearchParams();
    for (let sensorId = 1; sensorId <= 7; sensorId += 1) {
      params.append('series', `measurement|${sensorId}|pm25|1h`);
    }
    expect(readAnalyticsSeries(params).map((series) => analyticsSeriesKey(series))).toEqual([
      'measurement|1|pm25|1h', 'measurement|2|pm25|1h', 'measurement|3|pm25|1h',
      'measurement|4|pm25|1h', 'measurement|5|pm25|1h', 'measurement|6|pm25|1h',
    ]);
  });
});


describe('semantic Analytics Y-axis grouping', () => {
  it('groups compatible concentration and numeric AQI series instead of creating per-stream axes', () => {
    const scales = [
      { kind: 'measurement' as const, normalized_unit: 'µg/m³' },
      { kind: 'measurement' as const, normalized_unit: 'ug/m3' },
      { kind: 'measurement' as const, normalized_unit: 'µg / m³' },
      { kind: 'aqi' as const, result_kind: 'numeric' as const, standard_code: 'us_epa' },
      { kind: 'aqi' as const, result_kind: 'numeric' as const, standard_code: 'us_epa' },
    ];

    expect(countAnalyticsScaleGroups(scales)).toBe(2);
    expect(analyticsScaleGroupKey(scales[0])).toBe('measurement:ug/m3');
    expect(analyticsScaleGroupKey(scales[3])).toBe('aqi:numeric');
  });

  it('keeps categorical AQI separate from concentration and numeric AQI', () => {
    expect(countAnalyticsScaleGroups([
      { kind: 'measurement', normalized_unit: 'µg/m³' },
      { kind: 'aqi', result_kind: 'numeric', standard_code: 'us_epa' },
      { kind: 'aqi', result_kind: 'categorical', standard_code: 'eea_european' },
    ])).toBe(3);
  });

  it('documents the fourth semantic scale group as beyond the three-axis readability limit', () => {
    expect(countAnalyticsScaleGroups([
      { kind: 'measurement', normalized_unit: 'µg/m³' },
      { kind: 'measurement', normalized_unit: 'ppb' },
      { kind: 'aqi', result_kind: 'numeric', standard_code: 'us_epa' },
      { kind: 'aqi', result_kind: 'categorical', standard_code: 'eea_european' },
    ])).toBe(4);
  });
});
