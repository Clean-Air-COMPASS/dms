import { describe, expect, it } from 'vitest';

import {
  buildMeasurementCsv,
  createUtf8CsvBlob,
  MEASUREMENT_CSV_HEADERS,
  measurementCsvRowFromApi,
} from '../measurementCsv';

function parseCsv(csv: string): string[][] {
  const records: string[][] = [];
  let record: string[] = [];
  let field = '';
  let quoted = false;

  for (let index = 0; index < csv.length; index += 1) {
    const character = csv[index];
    const nextCharacter = csv[index + 1];
    if (quoted) {
      if (character === '"' && nextCharacter === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
    } else if (character === '"' && field === '') {
      quoted = true;
    } else if (character === ',') {
      record.push(field);
      field = '';
    } else if (character === '\n') {
      record.push(field);
      records.push(record);
      record = [];
      field = '';
    } else {
      field += character;
    }
  }

  if (field !== '' || record.length > 0) {
    record.push(field);
    records.push(record);
  }
  return records;
}

const attribution = {
  acquisition_path: 'openaq_public',
  data_provider_name: 'OpenAQ',
  hardware_provider_name: 'Reference Hardware',
  provider_url: 'https://provider.example/device?id=1',
  contributor_name: 'Analyst, "North"\nTeam',
  contributor_url: 'https://example.org/contributors/north',
  license_code: 'CC-BY-4.0',
  license_url: 'https://creativecommons.org/licenses/by/4.0/',
  license_share_alike: false,
};

describe('measurement CSV contract', () => {
  it('exports exactly the approved columns in the stable English order', () => {
    expect(MEASUREMENT_CSV_HEADERS).toHaveLength(18);
    expect([...MEASUREMENT_CSV_HEADERS]).toEqual([
      'Measurement ID', 'Sensor ID', 'External Sensor ID', 'Parameter', 'Parameter Name',
      'Value', 'Unit', 'Observed At (UTC)', 'Device ID', 'Device Name', 'Latitude',
      'Longitude', 'Data Provider', 'Contributor', 'Contributor URL', 'Provider URL',
      'License', 'License URL',
    ]);

    const csv = buildMeasurementCsv([measurementCsvRowFromApi({
      measurement_id: 101,
      sensor_id: 202,
      external_sensor_id: 'provider-sensor-202',
      parameter: 'pm25',
      parameter_name: 'PM2.5',
      value: 12.5,
      unit: 'µg/m³',
      observed_at: '2026-09-16T12:00:00-07:00',
      device: {
        device_id: 303,
        friendly_name: 'Friendly "North, Station"\nMonitor',
        name: 'Internal Device Name',
        latitude: 38.5,
        longitude: -122.8,
        network: 'OpenAQ',
        data_attribution: attribution,
      },
    })]);
    const [headers, row] = parseCsv(csv);

    expect(headers).toHaveLength(18);
    expect(row).toHaveLength(18);
    expect(headers).toEqual([...MEASUREMENT_CSV_HEADERS]);
    expect(row).toEqual([
      '101', '202', 'provider-sensor-202', 'pm25', 'PM2.5', '12.5', 'µg/m³',
      '2026-09-16T19:00:00.000Z', '303', 'Friendly "North, Station"\nMonitor',
      '38.5', '-122.8', 'OpenAQ', 'Analyst, "North"\nTeam',
      'https://example.org/contributors/north', 'https://provider.example/device?id=1',
      'CC-BY-4.0', 'https://creativecommons.org/licenses/by/4.0/',
    ]);
    expect(csv).not.toContain('Network/Source');
    expect(csv).not.toContain('Acquisition Path');
    expect(csv).not.toContain('Hardware Provider');
    expect(csv).not.toContain('license_share_alike');
  });

  it('keeps optional attribution fields blank and preserves every requested unit', () => {
    const rows = ['µg/m³', 'ppm', 'ppb', '°C', '%'].map((unit, index) => measurementCsvRowFromApi({
      measurement_id: index + 1,
      sensor_id: 10,
      external_sensor_id: null,
      parameter: 'test_parameter',
      parameter_name: 'Test parameter',
      value: index + 0.5,
      unit,
      observed_at: '2026-09-16T12:00:00Z',
      device: {
        device_id: 20,
        name: 'Station',
        network: 'OpenAQ',
      },
    }));
    const records = parseCsv(buildMeasurementCsv(rows));

    expect(records.slice(1).map((row) => row[6])).toEqual(['µg/m³', 'ppm', 'ppb', '°C', '%']);
    for (const row of records.slice(1)) {
      expect(row).toHaveLength(18);
      expect(row[12]).toBe('OpenAQ');
      expect(row.slice(13)).toEqual(['', '', '', '', '']);
      expect(row.join(',')).not.toMatch(/\b(?:null|undefined|N\/A)\b/);
    }
  });

  it('writes clean UTF-8 bytes and adds only a UTF-8 signature at download time', async () => {
    const csv = buildMeasurementCsv([measurementCsvRowFromApi({
      measurement_id: 1,
      sensor_id: 2,
      parameter: 'pm25',
      parameter_name: 'PM2.5',
      value: 4,
      unit: 'µg/m³',
      observed_at: '2026-09-16T12:00:00Z',
      device: { device_id: 3, name: 'Station', network: 'OpenAQ' },
    })]);
    const csvBytes = new TextEncoder().encode(csv);
    expect(new TextDecoder('utf-8', { fatal: true }).decode(csvBytes)).toBe(csv);
    expect(csv).not.toContain('Âµ');
    expect(csv).not.toContain('Â³');
    expect(csv).not.toContain('�');

    const blobBytes = new Uint8Array(await new Promise<ArrayBuffer>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(createUtf8CsvBlob(csv));
    }));
    expect([...blobBytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    const downloadedText = new TextDecoder('utf-8', { fatal: true }).decode(blobBytes);
    expect(downloadedText.replace(/^\uFEFF/, '')).toBe(csv);
  });
});
