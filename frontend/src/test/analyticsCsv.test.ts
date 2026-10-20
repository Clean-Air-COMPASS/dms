import { describe, expect, it } from 'vitest';
import { buildAnalyticsCsv, type AnalyticsCsvRow } from '../analyticsCsv';
import { buildMeasurementCsvFromApiRows } from '../measurementCsv';

const baseRow: AnalyticsCsvRow = {
  seriesType: 'measurement', sensorName: 'Station, One', externalSensorId: 'sensor-1', source: 'OpenAQ',
  parameterCode: 'pm25', parameterDisplayName: 'PM2.5', shownDuration: 'Hourly', timestamp: '2026-08-01T01:00:00Z',
  intervalStartedAt: null, intervalEndedAt: null, representedLocalDate: null, value: 12.5, unit: 'µg/m³',
  measurementTimestampSemantics: 'observation_instant',
  concentrationUnit: null,
  categoryLabel: null, normalizedConcentration: null, preprocessedConcentration: null,
  isValid: true, coverageStatus: null, eligibilityStatus: null,
  exclusionReason: null, dominantPollutants: [], availablePollutants: [], missingPollutants: [], ineligiblePollutants: [],
  standardDisplayName: null, failedChecks: [],
};

describe('Analytics CSV', () => {
  it('exports UTC timing and timestamp semantics for measurement-only data', () => {
    const csv = buildAnalyticsCsv([baseRow], false);
    expect(csv.split('\n')[0]).toBe([
      'Measurement ID', 'Sensor ID', 'External Sensor ID', 'Parameter', 'Parameter Name',
      'Value', 'Unit', 'Observed At (UTC)', 'Device ID', 'Device Name', 'Latitude',
      'Longitude', 'Data Provider', 'Contributor', 'Contributor URL', 'Provider URL',
      'License', 'License URL',
    ].join(','));
    expect(csv).toContain(',,sensor-1,pm25,PM2.5,12.5,µg/m³,2026-08-01T01:00:00.000Z,,"Station, One",,,' + 'OpenAQ');
    expect(csv).not.toContain('Shown Duration');
    expect(csv).not.toContain('Failed Checks');
  });

  it('exports direct AirGradient attribution and license metadata', () => {
    const csv = buildAnalyticsCsv([{
      ...baseRow,
      source: 'AirGradient',
      dataAttribution: {
        acquisition_path: 'airgradient_public_reference',
        data_provider_name: 'AirGradient',
        hardware_provider_name: 'AirGradient',
        provider_url: 'https://www.airgradient.com',
        contributor_name: 'Community Lab',
        contributor_url: 'https://example.org/community-lab',
        license_code: 'CC-BY-SA-4.0',
        license_url: 'https://creativecommons.org/licenses/by-sa/4.0/',
        license_share_alike: true,
      },
    }], false);
    expect(csv).toContain('AirGradient,Community Lab,https://example.org/community-lab,https://www.airgradient.com,CC-BY-SA-4.0,https://creativecommons.org/licenses/by-sa/4.0/');
    expect(csv).not.toContain('airgradient_public_reference');
    expect(csv).not.toContain('Share Alike');
  });

  it('identifies independently selected resolutions for the same measurement sensor', () => {
    const csv = buildAnalyticsCsv([
      { ...baseRow, shownDuration: '2-minute', value: 11.2 },
      { ...baseRow, shownDuration: '1-hour average', value: 10.8 },
    ], false);
    expect(csv).toContain(',11.2,µg/m³,');
    expect(csv).toContain(',10.8,µg/m³,');
  });

  it('uses the same measurement export contract as the Map quick download', () => {
    const attribution = {
      acquisition_path: 'airgradient_public_reference',
      data_provider_name: 'AirGradient',
      hardware_provider_name: 'AirGradient',
      provider_url: 'https://www.airgradient.com',
      contributor_name: 'Community Lab',
      contributor_url: 'https://example.org/community-lab',
      license_code: 'CC-BY-SA-4.0',
      license_url: 'https://creativecommons.org/licenses/by-sa/4.0/',
      license_share_alike: true,
    };
    const analyticsCsv = buildAnalyticsCsv([{
      ...baseRow,
      measurementId: 11,
      sensorId: 12,
      deviceId: 13,
      deviceName: 'Friendly Station',
      latitude: 38.5,
      longitude: -122.8,
      parameterName: 'PM2.5',
      dataAttribution: attribution,
    }], false);
    const mapCsv = buildMeasurementCsvFromApiRows([{
      measurement_id: 11,
      sensor_id: 12,
      external_sensor_id: 'sensor-1',
      parameter: 'pm25',
      parameter_name: 'PM2.5',
      value: 12.5,
      unit: 'µg/m³',
      observed_at: '2026-08-01T01:00:00Z',
      device: {
        device_id: 13,
        friendly_name: 'Friendly Station',
        name: 'Raw Station Name',
        latitude: 38.5,
        longitude: -122.8,
        network: 'AirGradient',
        data_attribution: attribution,
      },
    }]);
    expect(analyticsCsv).toBe(mapCsv);
  });

  it('exports categorical AQI without fabricating a numeric value or severity rank', () => {
    const categoricalRow: AnalyticsCsvRow = {
      ...baseRow, seriesType: 'aqi', sensorName: 'European Station', externalSensorId: 2,
      parameterDisplayName: 'Overall hourly European AQI', standardDisplayName: 'European Air Quality Index',
      shownDuration: 'Hourly', intervalStartedAt: '2026-08-01T00:00:00Z', intervalEndedAt: '2026-08-01T01:00:00Z',
      value: null, unit: 'µg/m³', concentrationUnit: 'µg/m³', categoryLabel: 'Poor', normalizedConcentration: 50.98765,
      preprocessedConcentration: 50.9, isValid: null, eligibilityStatus: 'eligible',
      coverageStatus: 'partial', dominantPollutants: ['pm25'], availablePollutants: ['pm25'], missingPollutants: ['no2'],
    };
    const csv = buildAnalyticsCsv([categoricalRow], true);
    const fields = csv.split('\n')[1].split(',');
    expect(fields[13]).toBe('');
    expect(fields[14]).toBe('Poor');
    expect(fields[15]).toBe('50.98765');
    expect(fields[16]).toBe('50.9');
    expect(fields[9]).toBe('2026-08-01T00:00:00.000Z');
    expect(fields[10]).toBe('2026-08-01T01:00:00.000Z');
    expect(csv).not.toContain('severity');
    expect(csv).toContain('pm25,pm25,no2');
  });
});
