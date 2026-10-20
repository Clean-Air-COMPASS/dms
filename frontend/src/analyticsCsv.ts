import i18n from './i18n';
import type { DataAttribution } from './dataAttribution';
import { buildMeasurementCsv, type MeasurementCsvRow } from './measurementCsv';

export type AnalyticsCsvRow = {
  seriesType: 'measurement' | 'aqi';
  sensorName: string;
  externalSensorId: string | number | null;
  source: string | null;
  parameterCode: string;
  parameterDisplayName: string;
  parameterName?: string | null;
  measurementId?: string | number | null;
  sensorId?: string | number | null;
  deviceId?: string | number | null;
  deviceName?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  shownDuration: string;
  timestamp: string;
  intervalStartedAt: string | null;
  intervalEndedAt: string | null;
  measurementTimestampSemantics: string | null;
  representedLocalDate: string | null;
  value: number | null;
  unit: string;
  concentrationUnit: string | null;
  categoryLabel: string | null;
  normalizedConcentration: number | null;
  preprocessedConcentration: number | null;
  isValid: boolean | null;
  coverageStatus: string | null;
  eligibilityStatus: string | null;
  exclusionReason: string | null;
  dominantPollutants: string[];
  availablePollutants: string[];
  missingPollutants: string[];
  ineligiblePollutants: string[];
  standardDisplayName: string | null;
  failedChecks: { check_code: string }[];
  dataAttribution?: DataAttribution | null;
};

function csvField(value: string | number | null | undefined): string {
  if (value == null) return '';
  const text = String(value);
  return /[,"\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function measurementCsvRowFromAnalytics(row: AnalyticsCsvRow): MeasurementCsvRow {
  return {
    measurementId: row.measurementId ?? null,
    sensorId: row.sensorId ?? null,
    externalSensorId: row.externalSensorId,
    parameter: row.parameterCode,
    parameterName: row.parameterName ?? row.parameterDisplayName,
    value: row.value,
    unit: row.unit,
    observedAt: row.timestamp,
    deviceId: row.deviceId ?? null,
    deviceName: row.deviceName ?? row.sensorName,
    latitude: row.latitude ?? null,
    longitude: row.longitude ?? null,
    dataProvider: row.dataAttribution?.data_provider_name || row.source,
    contributor: row.dataAttribution?.contributor_name ?? null,
    contributorUrl: row.dataAttribution?.contributor_url ?? null,
    providerUrl: row.dataAttribution?.provider_url ?? null,
    license: row.dataAttribution?.license_code ?? null,
    licenseUrl: row.dataAttribution?.license_url ?? null,
  };
}


export function buildAnalyticsCsv(rows: AnalyticsCsvRow[], containsAqi: boolean): string {
  const attributionHeaders = [
    i18n.t('analytics:analytics.csv.acquisitionPath'),
    i18n.t('analytics:analytics.csv.dataProvider'),
    i18n.t('analytics:analytics.csv.hardwareProvider'),
    i18n.t('analytics:analytics.csv.contributor'),
    i18n.t('analytics:analytics.csv.contributorUrl'),
    i18n.t('analytics:analytics.csv.providerUrl'),
    i18n.t('analytics:analytics.csv.license'),
    i18n.t('analytics:analytics.csv.licenseUrl'),
    i18n.t('analytics:analytics.csv.shareAlike'),
  ];
  const localizedBoolean = (value: boolean | null | undefined): string => {
    if (value == null) return '';
    return value
      ? i18n.t('analytics:analytics.csv.yes')
      : i18n.t('analytics:analytics.csv.no');
  };

  if (!containsAqi) {
    return buildMeasurementCsv(rows.map(measurementCsvRowFromAnalytics));
  }

  const header = [
    'Series Type', 'Site', 'External ID', 'Source',
    i18n.t('analytics:analytics.csv.parameterOrProductCode'),
    i18n.t('analytics:analytics.csv.parameterOrProductName'), 'Resolution',
    'Standard', 'UTC Timestamp', 'UTC Interval Start', 'UTC Interval End', 'Represented Local Date',
    'Measurement Value', 'Numeric AQI', 'Category', 'Normalized Concentration',
    'Processed Concentration', 'Unit', 'Validity',
    'Eligibility', 'Coverage', 'Dominant Pollutants', 'Available Pollutants',
    'Missing Pollutants', 'Ineligible Pollutants', 'Availability or Blocking Reason',
    'Measurement Timestamp Role',
    ...attributionHeaders,
  ].join(',');
  const body = rows.map((row) => [
    row.seriesType, csvField(row.sensorName), csvField(row.externalSensorId), csvField(row.source),
    csvField(row.parameterCode), csvField(row.parameterDisplayName), csvField(row.shownDuration), csvField(row.standardDisplayName),
    new Date(row.timestamp).toISOString(),
    row.intervalStartedAt ? new Date(row.intervalStartedAt).toISOString() : '',
    row.intervalEndedAt ? new Date(row.intervalEndedAt).toISOString() : '',
    row.representedLocalDate || '', row.seriesType === 'measurement' ? row.value ?? '' : '',
    row.seriesType === 'aqi' ? row.value ?? '' : '', csvField(row.categoryLabel),
    row.normalizedConcentration ?? '', row.preprocessedConcentration ?? '',
    csvField(row.seriesType === 'aqi' ? row.concentrationUnit : row.unit),
    row.isValid == null ? '' : row.isValid ? 'Valid' : 'Invalid',
    row.eligibilityStatus || '', row.coverageStatus || '',
    csvField(row.dominantPollutants.join(';')), csvField(row.availablePollutants.join(';')),
    csvField(row.missingPollutants.join(';')), csvField(row.ineligiblePollutants.join(';')),
    csvField(row.exclusionReason || ''),
    csvField(row.measurementTimestampSemantics),
    csvField(row.dataAttribution?.acquisition_path),
    csvField(row.dataAttribution?.data_provider_name),
    csvField(row.dataAttribution?.hardware_provider_name),
    csvField(row.dataAttribution?.contributor_name),
    csvField(row.dataAttribution?.contributor_url),
    csvField(row.dataAttribution?.provider_url),
    csvField(row.dataAttribution?.license_code),
    csvField(row.dataAttribution?.license_url),
    localizedBoolean(row.dataAttribution?.license_share_alike),
  ].join(','));
  return [header, ...body].join('\n');
}
