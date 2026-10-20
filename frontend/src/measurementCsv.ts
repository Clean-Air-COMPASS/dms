export const MEASUREMENT_CSV_HEADERS = [
  'Measurement ID',
  'Sensor ID',
  'External Sensor ID',
  'Parameter',
  'Parameter Name',
  'Value',
  'Unit',
  'Observed At (UTC)',
  'Device ID',
  'Device Name',
  'Latitude',
  'Longitude',
  'Data Provider',
  'Contributor',
  'Contributor URL',
  'Provider URL',
  'License',
  'License URL',
] as const;

type MeasurementCsvValue = string | number | null | undefined;

export type MeasurementCsvRow = {
  measurementId: MeasurementCsvValue;
  sensorId: MeasurementCsvValue;
  externalSensorId: MeasurementCsvValue;
  parameter: MeasurementCsvValue;
  parameterName: MeasurementCsvValue;
  value: MeasurementCsvValue;
  unit: MeasurementCsvValue;
  observedAt: MeasurementCsvValue;
  deviceId: MeasurementCsvValue;
  deviceName: MeasurementCsvValue;
  latitude: MeasurementCsvValue;
  longitude: MeasurementCsvValue;
  dataProvider: MeasurementCsvValue;
  contributor: MeasurementCsvValue;
  contributorUrl: MeasurementCsvValue;
  providerUrl: MeasurementCsvValue;
  license: MeasurementCsvValue;
  licenseUrl: MeasurementCsvValue;
};

function csvField(value: MeasurementCsvValue): string {
  if (value == null) return '';
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function scalarValue(value: unknown): MeasurementCsvValue {
  return typeof value === 'string' || typeof value === 'number' ? value : null;
}

function firstPresent(...values: unknown[]): MeasurementCsvValue {
  for (const value of values) {
    if (value == null) continue;
    if (typeof value === 'string' && value.trim() === '') continue;
    return scalarValue(value);
  }
  return null;
}

/** Normalize an API timestamp whose source timezone may be UTC or an explicit offset. */
export function normalizeUtcTimestamp(value: unknown): string {
  if (value == null) return '';
  const text = value instanceof Date ? value.toISOString() : String(value).trim();
  if (!text) return '';

  // Backend-naive datetimes are UTC by contract. Add the explicit designator
  // before parsing so the browser timezone cannot affect the result.
  const timestampWithTimezone = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(text)
    ? text
    : `${text}Z`;
  const date = new Date(timestampWithTimezone);
  if (!Number.isFinite(date.getTime())) {
    throw new Error('invalid_measurement_timestamp');
  }
  return date.toISOString();
}

export function buildMeasurementCsv(rows: MeasurementCsvRow[]): string {
  const header = MEASUREMENT_CSV_HEADERS.map(csvField).join(',');
  const body = rows.map((row) => [
    row.measurementId,
    row.sensorId,
    row.externalSensorId,
    row.parameter,
    row.parameterName,
    row.value,
    row.unit,
    normalizeUtcTimestamp(row.observedAt),
    row.deviceId,
    row.deviceName,
    row.latitude,
    row.longitude,
    row.dataProvider,
    row.contributor,
    row.contributorUrl,
    row.providerUrl,
    row.license,
    row.licenseUrl,
  ].map(csvField).join(','));

  return [header, ...body].join('\n');
}

/** Map the public latest-measurement API shape into the stable export contract. */
export function measurementCsvRowFromApi(row: Record<string, unknown>): MeasurementCsvRow {
  const device = asRecord(row.device);
  const attribution = asRecord(device?.data_attribution);
  const externalApi = asRecord(device?.external_api);
  const measurementId = scalarValue(row.measurement_id);

  return {
    measurementId: measurementId === 0 ? null : measurementId,
    sensorId: scalarValue(row.sensor_id),
    externalSensorId: scalarValue(row.external_sensor_id),
    parameter: scalarValue(row.parameter),
    parameterName: scalarValue(row.parameter_name),
    value: scalarValue(row.value),
    unit: scalarValue(row.unit),
    observedAt: scalarValue(row.observed_at),
    deviceId: scalarValue(device?.device_id),
    deviceName: firstPresent(device?.friendly_name, device?.name),
    latitude: scalarValue(device?.latitude),
    longitude: scalarValue(device?.longitude),
    dataProvider: firstPresent(
      attribution?.data_provider_name,
      device?.network,
      externalApi?.name,
    ),
    contributor: scalarValue(attribution?.contributor_name),
    contributorUrl: scalarValue(attribution?.contributor_url),
    providerUrl: scalarValue(attribution?.provider_url),
    license: scalarValue(attribution?.license_code),
    licenseUrl: scalarValue(attribution?.license_url),
  };
}

export function buildMeasurementCsvFromApiRows(rows: Record<string, unknown>[]): string {
  return buildMeasurementCsv(rows.map(measurementCsvRowFromApi));
}

// A UTF-8 BOM is a standards-compatible signature that lets common spreadsheet
// applications detect UTF-8 instead of guessing a legacy Windows code page.
export const CSV_UTF8_BOM = '\uFEFF';

export function createUtf8CsvBlob(csv: string): Blob {
  return new Blob([CSV_UTF8_BOM, csv], { type: 'text/csv;charset=utf-8;' });
}
