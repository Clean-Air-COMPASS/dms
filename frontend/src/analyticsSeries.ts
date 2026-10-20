import type { AirQualityIndexResultKind } from './airQualityIndex';


export const MAX_ANALYTICS_SERIES = 6;
export const MAX_ANALYTICS_SCALE_GROUPS = 3;


export type MeasurementSeriesSelection = {
  kind: 'measurement';
  sensor_id: number;
  parameter_code: string;
  aggregation_code: string;
};


export type AirQualityIndexSeriesSelection = {
  kind: 'aqi';
  device_id: number;
  standard_code: string;
  product_code: string;
};


export type AnalyticsSeriesSelection = MeasurementSeriesSelection | AirQualityIndexSeriesSelection;


export type AnalyticsScaleDescriptor = {
  kind: 'measurement';
  normalized_unit: string;
} | {
  kind: 'aqi';
  result_kind: AirQualityIndexResultKind;
  standard_code: string;
};


export function normalizeMeasurementAggregationCode(code: string): string {
  const normalized = (code || '').toLowerCase();
  if (normalized === 'hour') return '1h';
  if (normalized === 'day' || normalized === 'daily') return '24h';
  if (normalized === 'latest') return 'raw';
  return normalized;
}


export function analyticsSeriesKey(series: AnalyticsSeriesSelection): string {
  if (series.kind === 'measurement') {
    return `measurement|${series.sensor_id}|${series.parameter_code}|${series.aggregation_code}`;
  }
  return `aqi|${series.standard_code}|${series.product_code}|${series.device_id}`;
}


export function parseAnalyticsSeries(value: string): AnalyticsSeriesSelection | null {
  const parts = value.split('|');
  if (parts[0] === 'measurement' && parts.length === 4) {
    const sensorId = Number(parts[1]);
    if (!Number.isInteger(sensorId) || sensorId <= 0 || !parts[2] || !parts[3]) return null;
    return {
      kind: 'measurement',
      sensor_id: sensorId,
      parameter_code: parts[2].toLowerCase(),
      aggregation_code: normalizeMeasurementAggregationCode(parts[3]),
    };
  }
  if (parts[0] === 'aqi' && parts.length === 4) {
    const deviceId = Number(parts[3]);
    if (!parts[1] || !parts[2] || !Number.isInteger(deviceId) || deviceId <= 0) return null;
    return {
      kind: 'aqi',
      standard_code: parts[1].toLowerCase(),
      product_code: parts[2].toLowerCase(),
      device_id: deviceId,
    };
  }
  return null;
}


function parseLegacyMeasurementOverlay(
  value: string,
  fallbackParameter: string,
  fallbackAggregation: string,
): MeasurementSeriesSelection | null {
  const [sensorIdValue, parameterValue, aggregationValue] = value.split(':');
  const sensorId = Number(sensorIdValue);
  if (!Number.isInteger(sensorId) || sensorId <= 0) return null;
  return {
    kind: 'measurement',
    sensor_id: sensorId,
    parameter_code: (parameterValue || fallbackParameter).toLowerCase(),
    aggregation_code: normalizeMeasurementAggregationCode(
      aggregationValue || fallbackAggregation,
    ),
  };
}


function parseLegacyAirQualityIndexSeries(value: string): AirQualityIndexSeriesSelection | null {
  const [standardCode, productCode, deviceIdValue] = value.split('|');
  const deviceId = Number(deviceIdValue);
  if (!standardCode || !productCode || !Number.isInteger(deviceId) || deviceId <= 0) return null;
  return {
    kind: 'aqi',
    standard_code: standardCode.toLowerCase(),
    product_code: productCode.toLowerCase(),
    device_id: deviceId,
  };
}


export function readAnalyticsSeries(searchParams: URLSearchParams): AnalyticsSeriesSelection[] {
  const canonicalValues = searchParams.getAll('series');
  const candidates: AnalyticsSeriesSelection[] = [];
  if (canonicalValues.length > 0) {
    canonicalValues.forEach((value) => {
      const parsed = parseAnalyticsSeries(value);
      if (parsed) candidates.push(parsed);
    });
  } else {
    const sensorId = Number(searchParams.get('sensor_id') || '');
    const parameterCode = (searchParams.get('parameter') || '').toLowerCase();
    const aggregationCode = normalizeMeasurementAggregationCode(
      searchParams.get('aggregate') || 'hour',
    );
    if (Number.isInteger(sensorId) && sensorId > 0 && parameterCode) {
      candidates.push({
        kind: 'measurement',
        sensor_id: sensorId,
        parameter_code: parameterCode,
        aggregation_code: aggregationCode,
      });
    }
    searchParams.getAll('overlay').forEach((value) => {
      const parsed = parseLegacyMeasurementOverlay(value, parameterCode, aggregationCode);
      if (parsed) candidates.push(parsed);
    });

    const standardCode = (searchParams.get('standard_code') || '').toLowerCase();
    const productCode = (searchParams.get('product_code') || '').toLowerCase();
    const deviceId = Number(searchParams.get('device_id') || '');
    if (standardCode && productCode && Number.isInteger(deviceId) && deviceId > 0) {
      candidates.push({
        kind: 'aqi',
        standard_code: standardCode,
        product_code: productCode,
        device_id: deviceId,
      });
    }
    searchParams.getAll('compare').forEach((value) => {
      const parsed = parseLegacyAirQualityIndexSeries(value);
      if (parsed) candidates.push(parsed);
    });
  }

  const seen = new Set<string>();
  return candidates.filter((series) => {
    const key = analyticsSeriesKey(series);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, MAX_ANALYTICS_SERIES);
}


export function writeAnalyticsSeries(
  searchParams: URLSearchParams,
  series: AnalyticsSeriesSelection[],
): URLSearchParams {
  const next = new URLSearchParams(searchParams.toString());
  ['series', 'sensor_id', 'parameter', 'aggregate', 'overlay', 'standard_code', 'product_code', 'device_id', 'compare', 'layer', 'range'].forEach(
    (key) => next.delete(key),
  );
  series.slice(0, MAX_ANALYTICS_SERIES).forEach((selectedSeries) => {
    next.append('series', analyticsSeriesKey(selectedSeries));
  });
  return next;
}


export function normalizeDisplayUnit(unit: string | null | undefined): string {
  return (unit || 'unit unavailable')
    .trim()
    .toLowerCase()
    .replaceAll('µ', 'u')
    .replaceAll('μ', 'u')
    .replaceAll('³', '3')
    .replaceAll(' ', '');
}


export function analyticsScaleGroupKey(scale: AnalyticsScaleDescriptor): string {
  if (scale.kind === 'measurement') {
    return `measurement:${normalizeDisplayUnit(scale.normalized_unit)}`;
  }
  if (scale.result_kind === 'numeric') return 'aqi:numeric';
  return `aqi:categorical:${scale.standard_code}`;
}


export function countAnalyticsScaleGroups(scales: AnalyticsScaleDescriptor[]): number {
  return new Set(scales.map(analyticsScaleGroupKey)).size;
}
