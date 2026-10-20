import { describe, expect, it } from 'vitest';
import { MAP_QUERY_KEYS, readMapViewport, withoutMapQueryState } from '../mapUrlState';

describe('Map query ownership', () => {
  it.each(MAP_QUERY_KEYS)('removes only Map key %s from Home', key => {
    expect(withoutMapQueryState(`?campaign=clean-air&${key}=value&${key}=duplicate`))
      .toBe('?campaign=clean-air');
  });
  it('leaves an unrelated query byte-for-byte unchanged', () => {
    expect(withoutMapQueryState('?campaign=clean%20air')).toBe('?campaign=clean%20air');
    expect(withoutMapQueryState('')).toBe('');
  });
});

describe('explicit Map camera links', () => {
  it('reads a complete camera, including wrapped longitude', () => {
    expect(readMapViewport('?lat=51.5&lng=359.88&zoom=10'))
      .toEqual({ lat: 51.5, lng: 359.88, zoom: 10 });
  });
  it.each(['', '?lat=0&lng=0', '?lat=&lng=0&zoom=2', '?lat=90&lng=0&zoom=2',
    '?lat=0&lng=NaN&zoom=2', '?lat=0&lng=0&zoom=-2', '?lat=0&lng=0&zoom=23'])(
    'rejects incomplete or invalid camera %s', search => {
    expect(readMapViewport(search)).toBeNull();
  });
});
