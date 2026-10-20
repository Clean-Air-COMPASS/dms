import i18n, { formatDisplayNumber } from './i18n';

export type AqiBucket = { max: number; color: string };

export const AQI_BUCKETS: AqiBucket[] = [
  { max: 50, color: '#00E400' },
  { max: 100, color: '#FFFF00' },
  { max: 150, color: '#FF7E00' },
  { max: 200, color: '#FF0000' },
  { max: 300, color: '#8F3F97' },
  { max: 500, color: '#7E0023' },
];

export const AQI_NO_DATA_COLOR = '#9CA3AF'; 

export function getAggregationDisplayLabel(code?: string | null): string {
  if (!code) return '';
  const lower = code.toLowerCase();
  const labelKeys = {
    raw: 'aq:aggregation.rawLatest',
    latest: 'aq:aggregation.rawLatest',
    '1m': 'aq:aggregation.oneMinute',
    '2m': 'aq:aggregation.twoMinute',
    '5m': 'aq:aggregation.fiveMinute',
    '15m': 'aq:aggregation.fifteenMinute',
    '1h': 'aq:aggregation.oneHourAverage',
    '8h': 'aq:aggregation.eightHourAverage',
    '24h': 'aq:aggregation.twentyFourHourAverage',
    rolling_24h: 'aq:aggregation.rollingTwentyFourHourAverage',
    hour: 'aq:aggregation.oneHourAverage',
    daily: 'aq:aggregation.dailyAverage',
    day: 'aq:aggregation.dailyAverage',
  } as const;
  const key = labelKeys[lower as keyof typeof labelKeys];
  return key ? i18n.t(key) : i18n.t('aq:unknown.aggregation', { code });
}


export function formatAqiValue(value?: number | null, maximumDecimalPlaces = 0): string {
  if (value == null || Number.isNaN(value)) return '-';
  return formatDisplayNumber(value, i18n.resolvedLanguage === 'es' ? 'es' : 'en', {
    maximumFractionDigits: maximumDecimalPlaces,
    minimumFractionDigits: 0,
  });
}

export function getAqiColor(aqiValue?: number | null): string {
  if (aqiValue == null || Number.isNaN(aqiValue)) return AQI_NO_DATA_COLOR;
  const val = Math.max(0, Math.round(aqiValue));
  for (const bucket of AQI_BUCKETS) {
    if (val <= bucket.max) return bucket.color;
  }
  
  return AQI_BUCKETS[AQI_BUCKETS.length - 1].color;
}


export const AQI_COLOR_TEST_VECTORS: Array<{ value: number; color: string }> = [
  { value: 10, color: '#00E400' },
  { value: 75, color: '#FFFF00' },
  { value: 125, color: '#FF7E00' },
  { value: 175, color: '#FF0000' },
  { value: 225, color: '#8F3F97' },
  { value: 350, color: '#7E0023' },
];

export function verifyAqiColorTable(): boolean {
  return AQI_COLOR_TEST_VECTORS.every((vec) => getAqiColor(vec.value) === vec.color);
}
