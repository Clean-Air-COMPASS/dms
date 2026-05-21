


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

const AQI_LABELS: Record<string, string> = {
  'aqi': 'AQI',
  'aqi-nowcast': 'AQI (NowCast)',
  'aqi-24h': 'AQI (24-hour)',
  'aqi-8h': 'AQI (8-hour)',
  'aqi-1h': 'AQI (1-hour)',
};


export function getAggregationDisplayLabel(code?: string | null): string {
  if (!code) return '';
  const lower = code.toLowerCase();
  
  
  if (AQI_LABELS[lower]) return AQI_LABELS[lower];
  
  
  const labels: Record<string, string> = {
    'raw': 'Raw/latest',
    'latest': 'Raw/latest',
    '1m': '1-minute',
    '5m': '5-minute',
    '15m': '15-minute',
    '1h': '1-hour average',
    '8h': '8-hour average',
    '24h': '24-hour average',
    'rolling_24h': 'Rolling 24-hour average',
    'hour': '1-hour average',
    'daily': 'Daily average',
  };
  
  return labels[lower] || code;
}


export function isAqiResolution(code?: string | null): boolean {
  if (!code) return false;
  const lower = code.toLowerCase();
  return lower === 'aqi' || lower.startsWith('aqi-');
}

export function describeAqiResolution(code?: string | null): string {
  if (!code) return 'AQI';
  const key = code.toLowerCase();
  return AQI_LABELS[key] || `AQI (${code})`;
}


export function getAqiAggregationCode(timeResolution?: string | null, parameter?: string | null): string {
  if (!timeResolution) return 'aqi-nowcast';
  const lower = timeResolution.toLowerCase();
  
  
  if (lower.startsWith('aqi-')) return lower;
  
  
  if (lower === 'aqi') {
    const param = (parameter || '').toLowerCase();
    
    if (param === 'pm25') return 'aqi-nowcast';
    if (param === 'pm10') return 'aqi-24h';
    
    if (param === 'o3') return 'aqi-8h';
    
    if (param === 'co') return 'aqi-8h';
    
    if (param === 'no2' || param === 'so2') return 'aqi-1h';
    
    return 'aqi-nowcast';
  }
  
  return timeResolution;
}

export function formatAqiValue(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '-';
  return Math.round(value).toString();
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


export const AQI_POLLUTANTS: ReadonlySet<string> = new Set([
  'pm25',
  'pm10',
  'o3',
  'co',
  'no2',
  'so2',
]);


export const POLLUTANT_AQI_RESOLUTIONS: Record<string, ReadonlySet<string>> = {
  pm25: new Set(['aqi-nowcast', 'aqi-24h']),
  pm10: new Set(['aqi-24h']),
  o3: new Set(['aqi-8h', 'aqi-1h']),
  co: new Set(['aqi-8h', 'aqi-1h']),
  no2: new Set(['aqi-1h']),
  so2: new Set(['aqi-1h']),
};


export function supportsAqi(pollutant?: string | null): boolean {
  if (!pollutant) return false;
  return AQI_POLLUTANTS.has(pollutant.toLowerCase());
}


export function getAqiDisplayName(pollutant: string): string {
  const code = pollutant.toLowerCase();
  const displayNames: Record<string, string> = {
    pm25: 'PM2.5',
    pm10: 'PM10',
    o3: 'O₃',
    co: 'CO',
    no2: 'NO₂',
    so2: 'SO₂',
  };
  return `${displayNames[code] || pollutant.toUpperCase()} AQI`;
}
