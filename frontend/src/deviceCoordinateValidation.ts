type CoordinateValue = string | number | null | undefined;
type CoordinateError = 'latitudeRange' | 'longitudeRange' | 'coordinateNumber' | 'coordinatePair';

export function validateDeviceCoordinates(latitude: CoordinateValue, longitude: CoordinateValue) {
  const errors: Partial<Record<'latitude' | 'longitude', CoordinateError>> = {};
  const latitudeBlank = latitude == null || String(latitude).trim() === '';
  const longitudeBlank = longitude == null || String(longitude).trim() === '';

  if (!latitudeBlank) {
    if (!Number.isFinite(Number(latitude))) errors.latitude = 'coordinateNumber';
    else if (Number(latitude) < -90 || Number(latitude) > 90) errors.latitude = 'latitudeRange';
  }
  if (!longitudeBlank) {
    if (!Number.isFinite(Number(longitude))) errors.longitude = 'coordinateNumber';
    else if (Number(longitude) < -180 || Number(longitude) > 180) errors.longitude = 'longitudeRange';
  }
  // The backend stores one location: supply both coordinates or leave both blank.
  if (latitudeBlank && !longitudeBlank) errors.latitude = 'coordinatePair';
  if (longitudeBlank && !latitudeBlank) errors.longitude = 'coordinatePair';
  return errors;
}
