import { fetchJson } from './api';
import {
  analyticsSeriesKey,
  normalizeMeasurementAggregationCode,
  type MeasurementSeriesSelection,
} from './analyticsSeries';
import type { DataAttribution } from './dataAttribution';

export interface MeasurementQcResult {
  check_code: string;
  evaluation_status: 'failed' | 'indeterminate';
  passed: boolean | null;
  failure_action: 'flag_for_review' | 'mark_invalid' | null;
  reason_code: string | null;
  severity?: string;
}

export interface MeasurementQcDetail extends MeasurementQcResult {
  message: string | null;
  rule_source: string | null;
  plugin_version: string | null;
  qc_version: string | null;
  stage: string;
  recorded_at: string | null;
  params_snapshot: Record<string, unknown> | null;
  policy_snapshot: Record<string, unknown> | null;
  policy_provenance: Record<string, Record<string, unknown>> | null;
  settings_disclosure: 'supported' | 'unavailable';
}

export interface MeasurementQcResponse {
  measurement_id: number;
  sensor_id: number;
  timestamp: string;
  value: number;
  is_valid: boolean;
  qc_provenance_status: 'recorded' | 'not_recorded';
  qc_results: MeasurementQcDetail[];
}

export interface MeasurementHistoryDataPoint {
  timestamp: string;
  value: number;
  measurement_id?: number | null;
  is_valid?: boolean;
  qc_flags?: Record<string, unknown> | null;
  qc_results?: MeasurementQcResult[];
  qc_provenance_status?: 'recorded' | 'not_recorded' | 'source_details_unavailable';
  failed_checks?: { check_code: string; severity?: string; message?: string | null }[];
  interval_started_at?: string | null;
  interval_ended_at?: string | null;
  sample_count?: number;
  valid_sample_count?: number;
  invalid_sample_count?: number;
}

export interface MeasurementHistoryResponse {
  sensor_id: number;
  parameter: string;
  parameter_name: string;
  unit: string;
  hours?: number;
  start?: string | null;
  end?: string | null;
  data: MeasurementHistoryDataPoint[];
  history_status?: 'available' | 'no_observations' | 'no_eligible_observations';
  includes_invalid?: boolean;
  qc_scope?: 'native' | 'aggregate';
  device_name?: string;
  device_friendly_name?: string | null;
  device_id?: number | null;
  latitude?: number | null;
  longitude?: number | null;
  device_timezone?: string | null;
  external_sensor_id?: string | number;
  external_api?: { name: string | null } | null;
  data_attribution?: DataAttribution | null;
  native_aggregation_code?: string | null;
  result_aggregation_code?: string | null;
  expected_frequency_seconds?: number | null;
  measurement_duration_seconds?: number | null;
  source_aggregation_duration_seconds?: number | null;
  acquisition_metadata?: Record<string, unknown> | null;
  measurement_timestamp_semantics?: string | null;
  formatting_status?: 'configured' | 'not_configured';
  display_precision?: number | null;
  _displayAggregate: string;
  _seriesKey: string;
}

type RawMeasurementHistoryResponse = Omit<MeasurementHistoryResponse, '_displayAggregate' | '_seriesKey'>;

export type MeasurementHistoryRequest = {
  sensorId: number;
  parameterCode?: string | null;
  aggregation: string;
  start?: string | null;
  end?: string | null;
  hours?: number;
  includeInvalid?: boolean;
  signal?: AbortSignal;
};

function normalizedAggregationCode(aggregation: string): string {
  return normalizeMeasurementAggregationCode(aggregation) || '1h';
}

export function buildMeasurementHistoryPath(request: MeasurementHistoryRequest): string {
  const aggregationCode = normalizedAggregationCode(request.aggregation);
  const query = new URLSearchParams({
    aggregation: aggregationCode,
    include_qc: 'true',
  });
  if (request.start) query.set('start', request.start);
  if (request.end) query.set('end', request.end);
  if (!request.start && !request.end && request.hours != null) {
    query.set('hours', String(request.hours));
  }
  if (request.includeInvalid) query.set('include_invalid', 'true');
  return `/sensors/${encodeURIComponent(String(request.sensorId))}/history?${query.toString()}`;
}

/**
 * Fetch and normalize the measurement history shape consumed by Analytics and
 * SensorChart. The backend remains responsible for aggregation and validity.
 */
export async function fetchMeasurementHistory(
  request: MeasurementHistoryRequest,
): Promise<MeasurementHistoryResponse> {
  const aggregationCode = normalizedAggregationCode(request.aggregation);
  const response = await fetchJson<RawMeasurementHistoryResponse>(
    buildMeasurementHistoryPath(request),
    { signal: request.signal, skipCache: true },
  );
  if (!response || Array.isArray(response) || !Array.isArray(response.data)) {
    throw new Error('measurement_history_response_invalid');
  }
  const parameterCode = (request.parameterCode || response.parameter || '').toLowerCase();
  const series: MeasurementSeriesSelection = {
    kind: 'measurement',
    sensor_id: request.sensorId,
    parameter_code: parameterCode,
    aggregation_code: aggregationCode,
  };
  return {
    ...response,
    _displayAggregate: aggregationCode,
    _seriesKey: analyticsSeriesKey(series),
  };
}
