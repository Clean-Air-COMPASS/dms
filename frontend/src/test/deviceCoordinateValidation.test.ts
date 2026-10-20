import { describe, expect, it } from 'vitest';
import { validateDeviceCoordinates } from '../deviceCoordinateValidation';

describe('device location input validation', () => {
  it.each([[-90, -180], [90, 180], [0, 0], ['-35.1234', '-120.1234'], ['', ''], [null, null], [undefined, undefined], ['  ', ' ']])(
    'accepts latitude %s and longitude %s', (latitude, longitude) => {
      expect(validateDeviceCoordinates(latitude, longitude)).toEqual({});
    },
  );
  it.each([-90.0001, 90.0001, 2000])('rejects latitude %s', latitude => {
    expect(validateDeviceCoordinates(latitude, 0)).toEqual({ latitude: 'latitudeRange' });
  });
  it.each([-180.0001, 180.0001, 3000, 360])('rejects longitude %s without wrapping it', longitude => {
    expect(validateDeviceCoordinates(0, longitude)).toEqual({ longitude: 'longitudeRange' });
  });
  it.each(['invalid', 'NaN', 'Infinity', Infinity, NaN])('rejects non-finite or nonnumeric coordinates %s', value => {
    expect(validateDeviceCoordinates(value, value)).toEqual({ latitude: 'coordinateNumber', longitude: 'coordinateNumber' });
  });
  it('requires the missing member of a coordinate pair', () => {
    expect(validateDeviceCoordinates('', 0)).toEqual({ latitude: 'coordinatePair' });
    expect(validateDeviceCoordinates(-35.1, null)).toEqual({ longitude: 'coordinatePair' });
  });
  it('reports both invalid ranges together', () => {
    expect(validateDeviceCoordinates(2000, 3000)).toEqual({ latitude: 'latitudeRange', longitude: 'longitudeRange' });
  });
});
