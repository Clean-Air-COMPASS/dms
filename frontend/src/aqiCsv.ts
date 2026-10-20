import { buildLatestAirQualityIndexPath, type AirQualityIndexCollection } from './airQualityIndex';
import { API_BASE } from './api';

// The Map and this export share the backend's complete latest-result contract.
// Reject duplicate identities or incomplete responses rather than choosing an
// arbitrary result or downloading a silently partial dataset.
export async function fetchLatestAqiCsv(standardCode: string, productCode: string, source?: string, parameterCode?: string | null): Promise<string> {
  if (!standardCode || !productCode) throw new Error('download_missing_product');
  const path = buildLatestAirQualityIndexPath({
    standard_code: standardCode, product_code: productCode,
    external_api_name: source, all_results: true,
  });
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw new Error(`download_failed:${response.status}`);
  const collection: AirQualityIndexCollection = await response.json();
  // The EEA response predates product metadata; its pollutant entries carry
  // the individual product results. Numeric standards identify their product.
  const european = standardCode === 'eea_european';
  if (!collection || collection.standard_code !== standardCode
    || ((!european || collection.product_code != null) && collection.product_code !== productCode) || !Array.isArray(collection.results)
    || collection.count !== collection.results.length) throw new Error('download_invalid_response');
  const deviceIds = new Set<number>();
  for (const result of collection.results) {
    if (!result || !Number.isInteger(result.device_id) || deviceIds.has(result.device_id)
      || result.standard_code !== standardCode || ((!european || result.product_code != null) && result.product_code !== productCode)) {
      throw new Error('download_inconsistent_result');
    }
    deviceIds.add(result.device_id);
  }
  if (!collection.results.length) throw new Error('download_empty');
  return buildAqiCsv(collection, productCode, parameterCode);
}

export function buildAqiCsv(collection: AirQualityIndexCollection, productCode: string, parameterCode?: string | null): string {
  const headers = [
    'Device ID', 'Device Name', 'Friendly Name', 'Latitude', 'Longitude', 'Data Provider',
    'AQI Standard', 'AQI Product', 'Result Kind', 'AQI Value', 'AQI Category',
    'Dominant Pollutants', 'Observed / Represented Time', 'Calculation Status',
    'Eligibility Status', 'Location Coverage Status', 'Exclusion Reasons', 'Missing Pollutants',
  ];
  const csvField = (value: unknown): string => {
    if (value == null) return '';
    const text = String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const rows = collection.results.map(result => {
    // EEA returns the overall result plus backend-calculated pollutant results.
    // Select the same product as the Map without calculating or inferring AQI.
    const isEuropeanPollutant = collection.standard_code === 'eea_european' && Boolean(parameterCode);
    const selectedResult = isEuropeanPollutant
      ? result.pollutant_results.find(pollutant => pollutant.parameter_code === parameterCode)
      : result;
    return [
      result.device_id, result.device_name, result.device_friendly_name,
      result.latitude, result.longitude, result.source_name,
      result.standard_code, productCode, result.result_kind,
      selectedResult?.numeric_value, selectedResult?.category_label,
      isEuropeanPollutant ? null : result.dominant_pollutants?.join('; '),
      result.observed_at, isEuropeanPollutant ? null : result.calculation_status, selectedResult?.eligibility_status,
      result.coverage_status ?? result.coverage?.coverage_status,
      isEuropeanPollutant ? selectedResult?.exclusion_reason : result.exclusion_reasons?.join('; '),
      result.coverage?.missing_pollutants?.join('; '),
    ].map(csvField).join(',');
  });
  return [headers.join(','), ...rows].join('\n');
}
