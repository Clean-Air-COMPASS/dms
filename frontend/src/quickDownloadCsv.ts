import { buildMeasurementCsvFromApiRows } from './measurementCsv';

// Keep the historical module name as a small compatibility facade for the Map
// quick-download component and its callers.
export const buildMeasurementCsv = (rows: Record<string, unknown>[]): string =>
  buildMeasurementCsvFromApiRows(rows);

export function buildDeviceCsv(devices: Record<string, unknown>[]): string {
  const headers = [
    'Device ID', 'Device Name', 'Friendly Name', 'External Device ID',
    'Data Provider', 'Latitude', 'Longitude', 'Timezone', 'Sensor Count',
  ];
  const csvField = (value: unknown): string => {
    if (value == null) return '';
    const text = String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const rows = devices.map(device => [
    device.device_id, device.name, device.friendly_name, device.external_id,
    device.network, device.latitude, device.longitude, device.timezone, device.sensor_count,
  ].map(csvField).join(','));
  return [headers.join(','), ...rows].join('\n');
}
