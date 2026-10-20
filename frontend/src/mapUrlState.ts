// Includes current Map fields and supported legacy time-range aliases.
export const MAP_QUERY_KEYS = [
  'mode', 'display_mode', 'recency', 'parameter', 'time_resolution', 'aggregation',
  'source', 'standard_code', 'product_code', 'start', 'until', 'time_start',
  'time_end', 'device_id', 'lat', 'lng', 'zoom',
] as const;

export type MapViewport = { lat: number; lng: number; zoom: number; bearing?: number; pitch?: number };

/** A camera link is intentional only when all three coordinates are valid. */
export function readMapViewport(search: string): MapViewport | null {
  const parameters = new URLSearchParams(search);
  const values = ['lat', 'lng', 'zoom'].map(key => parameters.get(key));
  if (values.some(value => value == null || value.trim() === '')) return null;
  const [lat, lng, zoom] = values.map(Number);
  if (![lat, lng, zoom].every(Number.isFinite) || Math.abs(lat) > 85.051129
    || zoom < 0 || zoom > 22) return null;
  return { lat, lng, zoom };
}

export function withoutMapQueryState(search: string): string {
  const parameters = new URLSearchParams(search);
  if (!MAP_QUERY_KEYS.some(key => parameters.has(key))) return search;
  for (const key of MAP_QUERY_KEYS) parameters.delete(key);
  const query = parameters.toString();
  return query ? `?${query}` : '';
}
