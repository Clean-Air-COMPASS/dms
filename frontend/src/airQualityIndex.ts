import { fetchJson } from './api';


export type AirQualityIndexResultKind = 'numeric' | 'categorical';
export type AirQualityIndexEligibilityStatus = 'eligible' | 'ineligible';
export type AirQualityIndexCoverageStatus = 'complete' | 'partial' | 'none';
export type AirQualityIndexCalculationStatus = 'calculated' | 'category_only' | 'unavailable';
export type AirQualityIndexScaleStatus =
  | 'within_0_to_500'
  | 'above_500'
  | 'within_published_numeric_range'
  | 'above_published_numeric_range';

export interface AirQualityIndexCategoryMetadata {
  code: string;
  label: string;
  internal_severity_rank: number;
  color: string;
  index_min?: number | null;
  index_max?: number | null;
}

export interface AirQualityIndexMethodologyReference {
  reference_code: string;
  title: string;
  document_number: string | null;
  publication_date: string | null;
  section: string;
  url: string;
}

export interface CompletenessApplicationProvenance {
  provenance_code: string;
  description: string;
}

export interface AirQualityIndexProductMetadata {
  product_code: string;
  display_name: string;
  parameter_code: string | null;
  calculation_code: string;
  aggregation_period: string;
  aggregation_display_name: string;
  result_scope: 'overall' | 'pollutant';
  is_parameter_default: boolean;
  availability_status: 'available' | string;
  availability_reason: string | null;
  product_kind?: string;
  history_status?: 'available' | string;
  history_interval?: 'utc_hour' | 'represented_device_local_date' | string;
  maximum_history_interval_count?: number;
  methodology_code?: string | null;
  methodology_revision?: string | null;
  methodology_effective_date?: string | null;
  methodology_references?: AirQualityIndexMethodologyReference[];
  limitations?: string[];
}

export interface AirQualityIndexStandardMetadata {
  standard_code: string;
  display_name: string;
  methodology_version: string;
  result_kind: AirQualityIndexResultKind;
  averaging_minutes: number | null;
  required_averaging_period: string | null;
  supported_parameter_codes: string[];
  normalized_unit: string;
  categories: AirQualityIndexCategoryMetadata[];
  products: AirQualityIndexProductMetadata[];
  default_product_code: string;
  is_default: boolean;
  methodology_code?: string | null;
  methodology_revision?: string | null;
  methodology_effective_date?: string | null;
  methodology_references?: AirQualityIndexMethodologyReference[];
  limitations?: string[];
}

export interface AirQualityIndexPollutantResult {
  standard_code: string;
  methodology_version: string;
  parameter_code: string;
  normalized_concentration: number | null;
  preprocessed_concentration?: number | null;
  normalized_unit: string | null;
  result_kind: AirQualityIndexResultKind;
  numeric_value: number | null;
  category_code: string | null;
  category_label: string | null;
  eligibility_status: AirQualityIndexEligibilityStatus;
  exclusion_reason: string | null;
}

export interface AirQualityIndexCoverage {
  coverage_status: AirQualityIndexCoverageStatus;
  available_pollutants: string[];
  missing_pollutants: string[];
  ineligible_pollutants: string[];
  missing_or_ineligible_pollutants: string[];
  display_qualification: 'not_evaluated' | string;
}

export interface AirQualityIndexSensorStreamEvaluation {
  sensor_id: number;
  aggregation_period: string | null;
  eligibility_status: AirQualityIndexEligibilityStatus;
  exclusion_reason: string | null;
  hourly_concentration_provenance?: string | null;
  hourly_timestamp_semantics?: string | null;
  expected_frequency_seconds?: number | null;
  input_frequency_display?: string | null;
  measurement_duration_seconds?: number | null;
  source_aggregation_duration_seconds?: number | null;
  measurement_timestamp_semantics?: string | null;
  measurement_metadata_status?: string | null;
  metadata_is_verified_and_complete?: boolean;
  exclusion_reasons?: string[];
  audit_flags?: string[];
  valid_hourly_slot_count?: number | null;
  valid_recent_hourly_slot_count?: number | null;
  missing_hourly_slot_count?: number | null;
  valid_sample_count?: number | null;
  duplicate_observation_count?: number | null;
  rejected_observation_count?: number | null;
  off_frequency_observation_count?: number | null;
  measurement_ids?: number[];
  completeness_reference_basis?: AirQualityIndexMethodologyReference[];
  application_provenance?: CompletenessApplicationProvenance[];
  hourly_inputs?: UsEpaHourlyCompleteness[];
}

export interface UsEpaCompletedDaySensorEvaluation {
  sensor_id: number;
  external_sensor_id: string | null;
  aggregation_period: string | null;
  metadata_is_verified_and_complete: boolean;
  eligibility_status: AirQualityIndexEligibilityStatus;
  blocking_reasons: string[];
  audit_flags: string[];
  represented_local_date: string | null;
  device_timezone: string | null;
  expected_hour_count: number;
  valid_hour_count: number;
  required_valid_hour_count: number;
  required_completeness_fraction: number | null;
  achieved_completeness_fraction: number;
  daily_concentration: number | null;
  normalized_unit: string | null;
  measurement_ids: number[];
  valid_sample_count: number;
  duplicate_observation_count: number;
  rejected_observation_count: number;
  off_frequency_observation_count: number;
  daily_completeness_rule_code: string | null;
  reference_basis: AirQualityIndexMethodologyReference[];
  application_provenance: CompletenessApplicationProvenance[];
  hourly_inputs: UsEpaHourlyCompleteness[];
}

export interface UsEpaHourlyCompleteness {
  interval_started_at: string;
  interval_ended_at: string;
  hourly_concentration: number | null;
  normalized_unit: string | null;
  hourly_eligibility_status: AirQualityIndexEligibilityStatus;
  exclusion_reason: string | null;
  exclusion_reasons: string[];
  audit_flags: string[];
  input_frequency_seconds: number;
  input_frequency_display: string;
  measurement_duration_seconds: number;
  source_aggregation_duration_seconds: number;
  target_duration_seconds: number;
  expected_observation_count: number;
  valid_observation_count: number;
  required_valid_observation_count: number;
  required_completeness_fraction: number | null;
  achieved_completeness_fraction: number;
  measurement_ids: number[];
  duplicate_measurement_ids: number[];
  rejected_measurement_ids: number[];
  off_frequency_measurement_ids: number[];
  duplicate_observation_count: number;
  rejected_observation_count: number;
  off_frequency_observation_count: number;
  missing_position_count: number;
  completeness_rule_code: string;
  completeness_reference_basis: AirQualityIndexMethodologyReference[];
  application_provenance: CompletenessApplicationProvenance[];
}

export interface UsEpaOzoneCandidate {
  candidate_status: 'calculated' | 'not_applicable' | 'unavailable';
  aggregation_period: '8h' | '1h';
  interval_started_at: string;
  interval_ended_at: string;
  normalized_concentration: number | null;
  normalized_unit: string | null;
  preprocessed_concentration: number | null;
  numeric_value: number | null;
  category_code: string | null;
  category_label: string | null;
  aqi_scale_status: AirQualityIndexScaleStatus | null;
  coverage_status: AirQualityIndexCoverageStatus;
  expected_hour_count: number;
  valid_hour_count: number;
  exclusion_reason: string | null;
  zero_substitution_used: boolean;
  reference_basis: AirQualityIndexMethodologyReference[];
}

export interface UsEpaOzoneSensorEvaluation {
  sensor_id: number;
  external_sensor_id: string | null;
  aggregation_period: string | null;
  input_unit_code: string | null;
  input_unit_symbol: string | null;
  hourly_concentration_provenance: string | null;
  hourly_timestamp_semantics: string | null;
  expected_frequency_seconds: number | null;
  measurement_duration_seconds: number | null;
  source_aggregation_duration_seconds: number | null;
  measurement_timestamp_semantics: string | null;
  measurement_metadata_status: string | null;
  metadata_is_verified_and_complete: boolean;
  calculation_status: AirQualityIndexCalculationStatus;
  blocking_reasons: string[];
  audit_flags: string[];
  valid_hour_count: number;
  valid_sample_count: number;
  duplicate_observation_count: number;
  rejected_observation_count: number;
  off_frequency_observation_count: number;
  measurement_ids: number[];
  ozone_8_hour_candidate: UsEpaOzoneCandidate;
  ozone_1_hour_candidate: UsEpaOzoneCandidate;
  selected_aggregation_period: '8h' | '1h' | null;
  hourly_inputs: UsEpaHourlyCompleteness[];
}

export interface UsEpaGasSensorEvaluation {
  sensor_id: number;
  external_sensor_id: string | null;
  parameter_code: string;
  aggregation_period: string | null;
  input_unit_code: string | null;
  input_unit_symbol: string | null;
  hourly_concentration_provenance: string | null;
  hourly_timestamp_semantics: string | null;
  expected_frequency_seconds: number | null;
  measurement_duration_seconds: number | null;
  source_aggregation_duration_seconds: number | null;
  measurement_timestamp_semantics: string | null;
  measurement_metadata_status: string | null;
  measurement_metadata_managed_by: string | null;
  metadata_is_verified_and_complete: boolean;
  calculation_status: AirQualityIndexCalculationStatus;
  blocking_reasons: string[];
  audit_flags: string[];
  valid_hour_count: number;
  valid_sample_count: number;
  duplicate_observation_count: number;
  rejected_observation_count: number;
  off_frequency_observation_count: number;
  measurement_ids: number[];
  hourly_inputs: UsEpaHourlyCompleteness[];
}

export interface UsEpaSo2Candidate {
  candidate_status: 'calculated' | 'not_applicable' | 'unavailable';
  calculation_code: string;
  aggregation_period: '1h' | '24h';
  interval_started_at: string;
  interval_ended_at: string;
  evaluation_interval_started_at: string;
  evaluation_interval_ended_at: string;
  normalized_concentration: number | null;
  normalized_unit: string;
  preprocessed_concentration: number | null;
  numeric_value: number | null;
  category_code: string | null;
  category_label: string | null;
  aqi_scale_status: AirQualityIndexScaleStatus | null;
  coverage_status: AirQualityIndexCoverageStatus;
  expected_hour_count: number;
  valid_hour_count: number;
  exclusion_reason: string | null;
  measurement_ids: number[];
  reference_basis: AirQualityIndexMethodologyReference[];
}

export interface UsEpaSo2SensorEvaluation extends UsEpaGasSensorEvaluation {
  so2_1_hour_candidate: UsEpaSo2Candidate;
  so2_24_hour_candidate: UsEpaSo2Candidate;
  selected_aggregation_period: '1h' | '24h' | null;
  selected_calculation_code: string | null;
}

export interface AirQualityIndexSensorProvenance {
  parameter_code: string;
  selected_sensor_id: number | null;
  selected_external_sensor_id: string | null;
  selected_sensor_aggregation_period: string | null;
  input_unit_code: string | null;
  input_unit_symbol: string | null;
  hourly_concentration: number | null;
  measurement_ids: number[];
  sample_count: number;
  candidate_sensor_ids: number[];
  eligible_sensor_ids: number[];
  duplicate_eligible_sensor_ids: number[];
  sensor_stream_evaluations: AirQualityIndexSensorStreamEvaluation[];
  selection_rule: string | null;
}

export interface DeviceAirQualityIndexResult {
  standard_code: string;
  methodology_version: string;
  result_kind: AirQualityIndexResultKind;
  device_id: number;
  device_name: string;
  device_friendly_name: string | null;
  latitude: number | null;
  longitude: number | null;
  device_timezone: string | null;
  source_name: string | null;
  observed_at: string;
  numeric_value: number | null;
  category_code: string | null;
  category_label: string | null;
  eligibility_status: AirQualityIndexEligibilityStatus;
  exclusion_reasons: string[];
  dominant_pollutants: string[];
  pollutant_results: AirQualityIndexPollutantResult[];
  coverage: AirQualityIndexCoverage;
  sensor_provenance: AirQualityIndexSensorProvenance[];
  parameter_code?: string | null;
  product_code?: string | null;
  product_display_name?: string | null;
  product_kind?: string | null;
  methodology_code?: string | null;
  methodology_revision?: string | null;
  methodology_effective_date?: string | null;
  methodology_references?: AirQualityIndexMethodologyReference[];
  calculation_status?: AirQualityIndexCalculationStatus | null;
  coverage_status?: AirQualityIndexCoverageStatus | null;
  exclusion_reason?: string | null;
  aqi_scale_status?: AirQualityIndexScaleStatus | null;
  expected_observation_count?: number | null;
  valid_observation_count?: number | null;
  window_started_at?: string | null;
  window_ended_at?: string | null;
  normalized_concentration?: number | null;
  normalized_unit?: string | null;
  preprocessed_concentration?: number | null;
  sensor_id?: number | null;
  external_sensor_id?: string | null;
  measurement_ids?: number[];
  valid_sample_count?: number | null;
  selected_sensor_reason?: string | null;
  valid_hourly_slot_count?: number | null;
  valid_recent_hourly_slot_count?: number | null;
  missing_hourly_slot_count?: number | null;
  latest_completed_hour_input_frequency_seconds?: number | null;
  latest_completed_hour_input_frequency_display?: string | null;
  latest_completed_hour_measurement_duration_seconds?: number | null;
  latest_completed_hour_source_aggregation_duration_seconds?: number | null;
  latest_completed_hour_target_duration_seconds?: number | null;
  latest_completed_hour_expected_observation_count?: number | null;
  latest_completed_hour_valid_observation_count?: number | null;
  latest_completed_hour_required_observation_count?: number | null;
  latest_completed_hour_required_completeness_fraction?: number | null;
  latest_completed_hour_achieved_completeness_fraction?: number | null;
  nowcast_window_duplicate_observation_count?: number | null;
  nowcast_window_rejected_observation_count?: number | null;
  nowcast_window_off_frequency_observation_count?: number | null;
  latest_completed_hour_eligibility_status?: AirQualityIndexEligibilityStatus | null;
  latest_completed_hour_completeness_rule_code?: string | null;
  latest_completed_hour_audit_flags?: string[];
  latest_completed_hour_completeness_reference_basis?: AirQualityIndexMethodologyReference[];
  latest_completed_hour_application_provenance?: CompletenessApplicationProvenance[];
  nowcast_hourly_input_eligibility?: 'eligible' | 'insufficient_recent_hours' | 'not_evaluated' | null;
  candidate_sensor_evaluations?: AirQualityIndexSensorStreamEvaluation[];
  data_qualification_status?: string | null;
  limitations?: string[];
  represented_local_date?: string | null;
  local_day_started_at?: string | null;
  local_day_ended_at?: string | null;
  utc_window_started_at?: string | null;
  utc_window_ended_at?: string | null;
  expected_hour_count?: number | null;
  valid_hour_count?: number | null;
  required_valid_hour_count?: number | null;
  required_completeness_fraction?: number | null;
  achieved_completeness_fraction?: number | null;
  daily_concentration?: number | null;
  daily_completeness_rule_code?: string | null;
  blocking_reasons?: string[];
  audit_flags?: string[];
  reference_basis?: AirQualityIndexMethodologyReference[];
  application_provenance?: CompletenessApplicationProvenance[];
  completed_day_candidate_sensor_evaluations?: UsEpaCompletedDaySensorEvaluation[];
  selected_aggregation_period?: '8h' | '1h' | '24h' | null;
  selected_calculation_code?: string | null;
  ozone_8_hour_candidate?: UsEpaOzoneCandidate | null;
  ozone_1_hour_candidate?: UsEpaOzoneCandidate | null;
  ozone_candidate_sensor_evaluations?: UsEpaOzoneSensorEvaluation[];
  gas_candidate_sensor_evaluations?: UsEpaGasSensorEvaluation[];
  so2_1_hour_candidate?: UsEpaSo2Candidate | null;
  so2_24_hour_candidate?: UsEpaSo2Candidate | null;
  so2_candidate_sensor_evaluations?: UsEpaSo2SensorEvaluation[];
}

export interface AirQualityIndexCollection {
  standard_code: string;
  methodology_version: string;
  result_kind: AirQualityIndexResultKind;
  count: number;
  results: DeviceAirQualityIndexResult[];
  product_code?: string | null;
  product_display_name?: string | null;
  product_kind?: string | null;
  methodology_code?: string | null;
  methodology_revision?: string | null;
  methodology_effective_date?: string | null;
  methodology_references?: AirQualityIndexMethodologyReference[];
  limitations?: string[];
}

export interface UsEpaCompletedDayHistoryResult {
  represented_local_date: string;
  local_day_started_at: string | null;
  local_day_ended_at: string | null;
  utc_window_started_at: string | null;
  utc_window_ended_at: string | null;
  expected_hour_count: number | null;
  valid_hour_count: number;
  required_valid_hour_count: number | null;
  required_completeness_fraction: number | null;
  achieved_completeness_fraction: number | null;
  daily_concentration: number | null;
  preprocessed_concentration: number | null;
  normalized_unit: string | null;
  calculation_status: AirQualityIndexCalculationStatus;
  coverage_status: AirQualityIndexCoverageStatus;
  numeric_value: number | null;
  category_code: string | null;
  category_label: string | null;
  aqi_scale_status: AirQualityIndexScaleStatus | null;
  selected_sensor_id: number | null;
  blocking_reasons: string[];
  audit_flags: string[];
}

export interface UsEpaCompletedDayHistoryDeviceSeries {
  device_id: number;
  device_name: string;
  device_friendly_name: string | null;
  latitude: number | null;
  longitude: number | null;
  device_timezone: string | null;
  source_name: string | null;
  results: UsEpaCompletedDayHistoryResult[];
}

export interface UsEpaCompletedDayHistorySummary {
  standard_code: string;
  methodology_version: string;
  result_kind: AirQualityIndexResultKind;
  product_code: string;
  product_display_name: string;
  product_kind: 'completed_day';
  parameter_code: string;
  methodology_code: string | null;
  methodology_revision: string | null;
  methodology_effective_date: string | null;
  start_local_date: string;
  end_local_date: string;
  requested_day_count: number;
  returned_device_count: number;
  returned_result_count: number;
  calculated_result_count: number;
  unavailable_result_count: number;
  maximum_supported_day_count: number;
  detail: 'summary';
  device_series: UsEpaCompletedDayHistoryDeviceSeries[];
}

export interface UsEpaCompletedDayHistoryQuery {
  product_code: string;
  start_local_date: string;
  end_local_date: string;
  device_id: number;
  external_api_name?: string | null;
}

export interface AirQualityIndexHistoryQuery {
  standard_code: string;
  product_code: string;
  start: string;
  end: string;
  device_id: number;
  external_api_name?: string | null;
}

export interface LatestAirQualityIndexQuery {
  all_results?: boolean;
  standard_code: string;
  product_code?: string | null;
  bbox?: string | null;
  external_api_name?: string | null;
  device_id?: number | null;
  until?: string | null;
  limit?: number | null;
}

export type MapDisplayMode = 'measurements' | 'us_epa' | 'eea_european' | 'philippines_denr';


export interface AirQualityIndexAnalyticsContext {
  standard_code: string;
  product_code: string;
  device_id: number;
  parameter_code?: string | null;
  sensor_id?: number | null;
  source?: string | null;
  external_api_name?: string | null;
  completed_day: boolean;
}


export function buildAirQualityIndexAnalyticsPath(
  context: AirQualityIndexAnalyticsContext,
): string {
  const queryParameters = new URLSearchParams();
  queryParameters.append(
    'series',
    `aqi|${context.standard_code}|${context.product_code}|${context.device_id}`,
  );
  const source = context.source || context.external_api_name;
  if (source) {
    queryParameters.set('source', source);
  }
  queryParameters.set('recency', context.completed_day ? '7d' : '24h');
  queryParameters.set('timezone', 'utc');
  return `/analytics?${queryParameters.toString()}`;
}


export interface AirQualityIndexAnalyticsSeriesRequest {
  standard_code: string;
  product_code: string;
  device_id: number;
}

export interface AirQualityIndexAnalyticsPoint {
  observed_at: string;
  interval_started_at: string;
  interval_ended_at: string;
  represented_local_date: string | null;
  numeric_value: number | null;
  category_code: string | null;
  category_label: string | null;
  normalized_concentration: number | null;
  preprocessed_concentration: number | null;
  normalized_unit: string | null;
  calculation_status: AirQualityIndexCalculationStatus;
  eligibility_status: AirQualityIndexEligibilityStatus;
  coverage_status: AirQualityIndexCoverageStatus;
  exclusion_reason: string | null;
  selected_calculation_code: string | null;
  selected_aggregation_period: string | null;
  dominant_pollutants: string[];
  available_pollutants: string[];
  missing_pollutants: string[];
  ineligible_pollutants: string[];
}

export interface AirQualityIndexAnalyticsSeries {
  standard_code: string;
  standard_display_name: string;
  methodology_version: string;
  product_code: string;
  product_display_name: string;
  parameter_code: string | null;
  calculation_code: string;
  aggregation_period: string;
  result_kind: AirQualityIndexResultKind;
  result_scope: 'overall' | 'pollutant';
  history_interval: string;
  device_id: number;
  device_name: string;
  device_friendly_name: string | null;
  device_timezone: string | null;
  source_name: string | null;
  points: AirQualityIndexAnalyticsPoint[];
}

export interface AirQualityIndexAnalyticsHistory {
  range_started_at: string;
  range_ended_at: string;
  requested_series_count: number;
  returned_series_count: number;
  maximum_series_count: number;
  maximum_hourly_interval_count: number;
  maximum_completed_day_interval_count: number;
  series: AirQualityIndexAnalyticsSeries[];
}

export async function getAirQualityIndexAnalyticsHistory(
  rangeStartedAt: string,
  rangeEndedAt: string,
  series: AirQualityIndexAnalyticsSeriesRequest[],
  signal?: AbortSignal,
): Promise<AirQualityIndexAnalyticsHistory> {
  return fetchJson<AirQualityIndexAnalyticsHistory>(
    '/air-quality-index/analytics-history',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        range_started_at: rangeStartedAt,
        range_ended_at: rangeEndedAt,
        series,
      }),
      signal,
    },
  );
}


export function buildLatestAirQualityIndexPath(query: LatestAirQualityIndexQuery): string {
  const queryParameters = new URLSearchParams();
  if (query.product_code) queryParameters.set('product_code', query.product_code);
  if (query.bbox) queryParameters.set('bbox', query.bbox);
  if (query.external_api_name) {
    queryParameters.set('external_api_name', query.external_api_name);
  }
  if (query.device_id != null) queryParameters.set('device_id', String(query.device_id));
  if (query.until) queryParameters.set('until', query.until);
  if (query.limit != null) queryParameters.set('limit', String(query.limit));
  if (query.all_results) queryParameters.set('all_results', 'true');
  const queryString = queryParameters.toString();
  const path = `/air-quality-index/${encodeURIComponent(query.standard_code)}/latest`;
  return queryString ? `${path}?${queryString}` : path;
}


export function buildUsEpaCompletedDayHistoryPath(
  query: UsEpaCompletedDayHistoryQuery,
): string {
  const queryParameters = new URLSearchParams();
  queryParameters.set('product_code', query.product_code);
  queryParameters.set('start_local_date', query.start_local_date);
  queryParameters.set('end_local_date', query.end_local_date);
  queryParameters.set('device_id', String(query.device_id));
  if (query.external_api_name) {
    queryParameters.set('external_api_name', query.external_api_name);
  }
  queryParameters.set('detail', 'summary');
  return `/air-quality-index/us_epa/history?${queryParameters.toString()}`;
}


export function buildAirQualityIndexHistoryPath(
  query: AirQualityIndexHistoryQuery,
): string {
  const queryParameters = new URLSearchParams();
  queryParameters.set('start', query.start);
  queryParameters.set('end', query.end);
  queryParameters.set('product_code', query.product_code);
  queryParameters.set('device_id', String(query.device_id));
  if (query.external_api_name) {
    queryParameters.set('external_api_name', query.external_api_name);
  }
  queryParameters.set('limit', '1000');
  const path = query.standard_code === 'us_epa'
    ? '/air-quality-index/us_epa/current-history'
    : `/air-quality-index/${encodeURIComponent(query.standard_code)}/history`;
  return `${path}?${queryParameters.toString()}`;
}


export async function listAirQualityIndexStandards(): Promise<AirQualityIndexStandardMetadata[]> {
  return fetchJson<AirQualityIndexStandardMetadata[]>('/air-quality-index/standards', {
    skipCache: true,
  });
}


export async function getLatestAirQualityIndex(
  query: LatestAirQualityIndexQuery,
): Promise<AirQualityIndexCollection> {
  return fetchJson<AirQualityIndexCollection>(buildLatestAirQualityIndexPath(query), {
    skipCache: true,
  });
}


export async function getUsEpaCompletedDayHistory(
  query: UsEpaCompletedDayHistoryQuery,
  signal?: AbortSignal,
): Promise<UsEpaCompletedDayHistorySummary> {
  return fetchJson<UsEpaCompletedDayHistorySummary>(
    buildUsEpaCompletedDayHistoryPath(query),
    { skipCache: true, signal },
  );
}


export async function getAirQualityIndexHistory(
  query: AirQualityIndexHistoryQuery,
  signal?: AbortSignal,
): Promise<AirQualityIndexCollection> {
  return fetchJson<AirQualityIndexCollection>(
    buildAirQualityIndexHistoryPath(query),
    { skipCache: true, signal },
  );
}


export function findAirQualityIndexStandard(
  standards: AirQualityIndexStandardMetadata[],
  standardCode: string,
): AirQualityIndexStandardMetadata | null {
  const normalizedStandardCode = standardCode.trim().toLowerCase();
  return standards.find(
    (standardMetadata) => standardMetadata.standard_code.toLowerCase() === normalizedStandardCode,
  ) ?? null;
}
