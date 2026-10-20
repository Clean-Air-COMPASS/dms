import { API_BASE } from './apiBase';
import { authFetch, authFetchJson } from './auth';
import { apiErrorFromResponse } from './apiError';
import type { DataAttribution } from './dataAttribution';

export { API_BASE };


const GET_CACHE: Record<string, Promise<any> | undefined> = {};

type FetchJsonInit = RequestInit & { skipCache?: boolean; cacheKey?: string };

export async function fetchJson<T = unknown>(path: string, init?: FetchJsonInit): Promise<T> {
  const { skipCache, cacheKey, ...requestInit } = init || {};
  const url = path.startsWith('http') ? path : `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;

  const method = (requestInit && requestInit.method ? requestInit.method.toUpperCase() : 'GET');

  
  
  if (method === 'GET') {
    let normalizedKey: string | null = null;
    try {
      const base = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
      const u = new URL(url, base);
      const entries = Array.from(u.searchParams.entries());
      entries.sort((a, b) => {
        if (a[0] === b[0]) return a[1].localeCompare(b[1]);
        return a[0].localeCompare(b[0]);
      });
      const normalizedSearch = entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
      normalizedKey = cacheKey || `${u.origin}${u.pathname}${normalizedSearch ? `?${normalizedSearch}` : ''}`;
    } catch {
      normalizedKey = cacheKey || null;
      // If URL parsing fails for any reason, fall back to direct fetch behavior
      // and avoid caching. This keeps behavior safe.
    }

    if (normalizedKey && !skipCache) {
      const existing = GET_CACHE[normalizedKey];
      if (existing) return existing as Promise<T>;
    }

    const fetchPromise = (async () => {
      const res = await fetch(url, requestInit);
      if (!res.ok) {
        if (normalizedKey) delete GET_CACHE[normalizedKey];
        throw await apiErrorFromResponse(res);
      }
      return res.json() as Promise<T>;
    })();

    if (normalizedKey) {
      GET_CACHE[normalizedKey] = fetchPromise;
    }
    return fetchPromise as Promise<T>;
  }

  
  const res = await fetch(url, requestInit);
  if (!res.ok) {
    throw await apiErrorFromResponse(res);
  }
  return res.json() as Promise<T>;
}


export async function runImport(source: string, target_sensor_id?: string, force = false): Promise<{ status: number; ok: boolean; data: any }> {
  const res = await authFetch(`/admin/imports/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, target_sensor_id, force }),
  });
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  return { status: res.status, ok: res.ok, data };
}

export type CsvUploadResult = {
  success: boolean;
  message: string;
  total_records: number;
  inserted_records: number;
  updated_records?: number;
  skipped_records?: number;
  failed_records: number;
  errors?: string[];
  row_errors?: { line: number; code: string; message: string }[];
  qc?: { evaluated: number; passed: number; flagged: number; indeterminate: number };
  event_id?: number;
};

export async function uploadMeasurementsCsv(file: File): Promise<CsvUploadResult> {
  
  
  const bytes = await file.arrayBuffer();
  const snapshot = new Blob([bytes], { type: file.type || 'text/csv' });
  const fd = new FormData();
  fd.append('file', snapshot, file.name);
  return authFetchJson<CsvUploadResult>('/admin/imports/upload-csv', {
    method: 'POST',
    body: fd,
  });
}


export type JobSchedule = {
  job_schedule_id: number;
  task: string;
  cron_expr: string;
  timezone: string;
  enabled: boolean;
  params?: Record<string, any> | null;
  allow_overlap: boolean;
};

export type SchedulePreview = { valid: boolean; next_runs: string[] };

export async function previewSchedule(cron_expr: string): Promise<SchedulePreview> {
  return authFetchJson<SchedulePreview>(`/admin/jobs/schedule-preview?cron_expr=${encodeURIComponent(cron_expr)}`);
}

export async function listSchedules(task?: string): Promise<JobSchedule[]> {
  const q = task ? `?task=${encodeURIComponent(task)}` : '';
  return authFetchJson<JobSchedule[]>(`/admin/jobs/schedules${q}`);
}

export async function updateScheduleParams(job_schedule_id: number, params: Record<string, any>): Promise<JobSchedule> {
  return authFetchJson<JobSchedule>(`/admin/jobs/schedules/${job_schedule_id}/params`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
  });
}

export async function updateSchedule(job_schedule_id: number, payload: Partial<{ cron_expr: string; timezone: string; enabled: boolean; allow_overlap: boolean; params: Record<string, any>; }>): Promise<JobSchedule> {
  return authFetchJson<JobSchedule>(`/admin/jobs/schedules/${job_schedule_id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}


export type DeviceOperationalStatus = 'active' | 'inactive' | 'unknown';

export type DeviceRecord = {
  device_id: number;
  name: string;
  friendly_name?: string | null;
  external_id?: string | null;
  external_api_id?: number | null;
  external_api_name?: string | null;
  manual_data_source_name?: string | null;
  model?: string | null;
  network?: string | null;
  acquisition_path?: string | null;
  hardware_provider_name?: string | null;
  provider_url?: string | null;
  contributor_name?: string | null;
  contributor_url?: string | null;
  license_code?: string | null;
  license_url?: string | null;
  license_share_alike?: boolean | null;
  data_attribution?: DataAttribution | null;
  status: DeviceOperationalStatus;
  owner?: string | null;
  organization?: string | null;
  description?: string | null;
  tags?: string | null;
  location_notes?: string | null;
  hardware_id?: string | null;
  serial_number?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  timezone?: string | null;
  allow_updates?: string | null;
  last_seen_at: string | null;
  created_at?: string | null;
  is_external?: boolean;
};

export type DevicePayload = Partial<Omit<DeviceRecord, 'device_id' | 'created_at' | 'last_seen_at' | 'status'>>;

export type DeviceSensorSummary = {
  acquisition_metadata?: { acquisition_method: string; underlying_sample_count?: number | null; underlying_coverage_seconds?: number | null } | null;
  display_precision?: number | null;
  sensor_id: number;
  external_sensor_id?: string | null;
  aggregation_code?: string | null;
  parameter_code?: string | null;
  parameter_name?: string | null;
  unit_symbol?: string | null;
  value?: number | null;
  observed_at?: string | null;
  is_valid?: boolean | null;
  expected_frequency_seconds?: number | null;
  measurement_duration_seconds?: number | null;
  source_aggregation_duration_seconds?: number | null;
  measurement_timestamp_semantics?: string | null;
  measurement_metadata_status?: string | null;
  measurement_metadata_managed_by?: string | null;
  
  parameter?: string | null;
  unit?: string | null;
  latest_value?: number | null;
  latest_observed_at?: string | null;
  latest_is_valid?: boolean | null;
};

export type DeviceSensorCreatePayload = {
  parameter_code: string;
  external_sensor_id?: string;
  aggregation_code?: string;
};

export type DeviceSensorUpdatePayload = {
  parameter_code?: string;
  external_sensor_id?: string;
  aggregation_code?: string;
};

export type DeviceSensorCreateResult = {
  sensor_id: number;
  device_id: number;
  parameter_code: string;
  external_sensor_id?: string | null;
  aggregation_code?: string | null;
  unit_id?: number | null;
  expected_frequency_seconds?: number | null;
  measurement_duration_seconds?: number | null;
  source_aggregation_duration_seconds?: number | null;
  measurement_timestamp_semantics?: string | null;
  measurement_metadata_status?: string | null;
  measurement_metadata_managed_by?: string | null;
};

function cleanPayload(payload: DevicePayload): Record<string, any> {
  const body: Record<string, any> = {};
  Object.entries(payload).forEach(([k, v]) => {
    if (v !== undefined) {
      body[k] = v;
    }
  });
  return body;
}

/** The Admin Devices API uses zero-based `page` values when `page_size` is supplied. */
export async function listDevicesAdmin(filters?: Partial<{ name: string; search: string; status: DeviceOperationalStatus; network: string; last_seen_from: string; last_seen_to: string; page: number; page_size: number; external_device_id?: string; external_sensor_id?: string; sensor_id?: number; }>): Promise<DeviceRecord[]> {
  const params = new URLSearchParams();
  if (filters?.name) params.set('name', filters.name);
  if (filters?.search) params.set('search', filters.search);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.network) params.set('network', filters.network);
  if (filters?.last_seen_from) params.set('last_seen_from', filters.last_seen_from);
  if (filters?.last_seen_to) params.set('last_seen_to', filters.last_seen_to);
  if (filters?.external_device_id) params.set('external_device_id', filters.external_device_id);
  if (filters?.external_sensor_id) params.set('external_sensor_id', filters.external_sensor_id);
  if (filters?.sensor_id !== undefined && Number.isFinite(filters.sensor_id)) params.set('sensor_id', String(filters.sensor_id));
  if (filters?.page !== undefined) params.set('page', String(filters.page));
  if (filters?.page_size !== undefined) params.set('page_size', String(filters.page_size));
  const qs = params.toString();
  return authFetchJson<DeviceRecord[]>(`/admin/devices${qs ? `?${qs}` : ''}`);
}

export async function getDeviceAdmin(device_id: number): Promise<DeviceRecord> {
  return authFetchJson<DeviceRecord>(`/admin/devices/${device_id}`);
}

export async function createDeviceAdmin(payload: DevicePayload): Promise<DeviceRecord> {
  return authFetchJson<DeviceRecord>('/admin/devices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cleanPayload(payload)),
  });
}

export async function updateDeviceAdmin(device_id: number, payload: DevicePayload): Promise<DeviceRecord> {
  return authFetchJson<DeviceRecord>(`/admin/devices/${device_id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cleanPayload(payload)),
  });
}

export async function deleteDeviceAdmin(device_id: number): Promise<void> {
  const res = await authFetch(`/admin/devices/${device_id}`, { method: 'DELETE' });
  if (!res.ok) {
    throw await apiErrorFromResponse(res);
  }
}

export async function listDeviceSensors(device_id: number, aggregation?: string, since?: string): Promise<DeviceSensorSummary[]> {
  const params = new URLSearchParams();
  if (aggregation) params.set('aggregation', aggregation);
  if (since) params.set('since', since);
  const qs = params.toString();
  return fetchJson<DeviceSensorSummary[]>(`/devices/${device_id}/sensors${qs ? `?${qs}` : ''}`, { skipCache: true });
}

export async function createDeviceSensorAdmin(device_id: number, payload: DeviceSensorCreatePayload): Promise<DeviceSensorCreateResult> {
  return authFetchJson<DeviceSensorCreateResult>(`/admin/devices/${device_id}/sensors`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function updateDeviceSensorAdmin(
  device_id: number,
  sensor_id: number,
  payload: DeviceSensorUpdatePayload
): Promise<DeviceSensorCreateResult> {
  return authFetchJson<DeviceSensorCreateResult>(`/admin/devices/${device_id}/sensors/${sensor_id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function deleteDeviceSensorAdmin(device_id: number, sensor_id: number): Promise<void> {
  const res = await authFetch(`/admin/devices/${device_id}/sensors/${sensor_id}`, { method: 'DELETE' });
  if (!res.ok) {
    throw await apiErrorFromResponse(res);
  }
}


export type ExternalAPI = {
  credential_configured?: boolean;
  external_api_id: number;
  provider_code?: string | null;
  name: string;
  base_url?: string | null;
  description?: string | null;
  has_api_key?: boolean;
  requires_credential?: boolean;
  params?: Record<string, any> | null;
  enabled: boolean;
  is_configured?: boolean;
  is_runnable?: boolean;
  runnable_reason?: 'disabled' | 'configuration_required' | 'paid_provider_requests_disabled' | 'ready' | 'unsupported_provider';
  is_builtin?: boolean;
  can_delete?: boolean;
  device_count?: number;
  latest_import?: {
    job_run_id: number;
    job_schedule_id: number;
    task: string;
    status: string;
    started_at?: string | null;
    finished_at?: string | null;
    summary?: Record<string, unknown> | null;
    error_message?: string | null;
  } | null;
};

export type PublicDataSource = {
  name: string;
  filter_value: string;
};

export async function listPublicDataSources(init?: FetchJsonInit): Promise<PublicDataSource[]> {
  return fetchJson<PublicDataSource[]>('/data-sources', init);
}

export async function listExternalAPIs(init?: FetchJsonInit): Promise<ExternalAPI[]> {
  const { skipCache, cacheKey, ...requestInit } = init || {};
  void skipCache;
  void cacheKey;
  return authFetchJson<ExternalAPI[]>(`/admin/external_apis`, requestInit);
}

export async function updateExternalAPI(external_api_id: number, payload: Partial<{ base_url: string | null; description: string | null; api_key: string | null; params: Record<string, any>; enabled: boolean; }>): Promise<ExternalAPI> {
  return authFetchJson<ExternalAPI>(`/admin/external_apis/${external_api_id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function createExternalAPI(payload: { name: string; base_url?: string; description?: string; api_key?: string | null; params?: Record<string, any>; enabled?: boolean; }): Promise<ExternalAPI> {
  return authFetchJson<ExternalAPI>(`/admin/external_apis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function deleteExternalAPI(external_api_id: number): Promise<void> {
  const res = await authFetch(`/admin/external_apis/${external_api_id}`, { method: 'DELETE' });
  if (!res.ok) {
    throw await apiErrorFromResponse(res);
  }
}

export async function listExternalAPISchedules(external_api_id: number): Promise<JobSchedule[]> {
  return authFetchJson<JobSchedule[]>(`/admin/external_apis/${external_api_id}/schedules`);
}


export type PurpleAirLookupDevice = {
  name: string;
  external_id: string;
  external_api_id: number | null;
  latitude: number | null;
  longitude: number | null;
  timezone: string | null;
};

export type PurpleAirLookupSensor = {
  parameter_code: string;
  external_sensor_id: string;
  latest_value: number | null;
  unit_code: string;
};

export type PurpleAirLookupResult = {
  device: PurpleAirLookupDevice;
  sensors: PurpleAirLookupSensor[];
};

export type PurpleAirCreateResult = {
  device: DeviceRecord;
  sensors: { sensor_id: number; parameter_code: string; external_sensor_id: string }[];
};

export type AirGradientLocation = {
  location_id: string;
  name: string;
  latitude: number | null;
  longitude: number | null;
  timezone: string | null;
  existing_device_id: number | null;
};

export function listAirGradientLocations() {
  return authFetchJson<{ locations: AirGradientLocation[]; automatic_imports_enabled: boolean }>(
    '/admin/devices/airgradient/locations',
  );
}

export function addAirGradientLocation(location_id: string) {
  return authFetchJson<{ device_id: number; already_exists: boolean; measurements_imported: number }>(
    '/admin/devices/airgradient/locations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ location_id }),
    },
  );
}

export async function lookupPurpleAirSensor(sensor_index: string, allow_paid_api = false): Promise<PurpleAirLookupResult> {
  return authFetchJson<PurpleAirLookupResult>('/admin/devices/purpleair/lookup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sensor_index, allow_paid_api }),
  });
}

export async function createPurpleAirDevice(
  device: PurpleAirLookupDevice,
  sensors: PurpleAirLookupSensor[]
): Promise<PurpleAirCreateResult> {
  return authFetchJson<PurpleAirCreateResult>('/admin/devices/purpleair/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device, sensors }),
  });
}


export type OpenAQSensor = {
  sensor_id: number;
  name: string;
  parameter_code: string;
  parameter_display: string;
  unit: string;
  exists?: boolean;
};

export type OpenAQDeviceInfo = {
  external_id: string;
  name: string;
  external_api_id: number | null;
  latitude: number | null;
  longitude: number | null;
  timezone: string | null;
};

export type OpenAQMetadata = {
  locality?: string | null;
  country_name?: string | null;
  country_code?: string | null;
  provider_name?: string | null;
  owner_name?: string | null;
  is_monitor?: boolean | null;
  is_mobile?: boolean | null;
  datetime_first_utc?: string | null;
  datetime_last_utc?: string | null;
  
  latest_value?: number | null;
  latest_datetime_utc?: string | null;
  coverage_percent?: number | null;
  observed_count?: number | null;
  expected_count?: number | null;
  summary_min?: number | null;
  summary_max?: number | null;
  summary_avg?: number | null;
};

export type OpenAQLocation = {
  device: OpenAQDeviceInfo;
  sensors: OpenAQSensor[];
  metadata: OpenAQMetadata;
  already_exists: boolean;
};

export type OpenAQLookupResult = {
  locations: OpenAQLocation[];
};

export type OpenAQCreateResult = {
  created: { device: DeviceRecord; sensors: { sensor_id: number; parameter_code: string; external_sensor_id: string }[] }[];
  count: number;
};

export async function lookupOpenAQLocations(params: { bbox?: string; location_id?: string }): Promise<OpenAQLookupResult> {
  const res = await authFetch(`/admin/devices/openaq/lookup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });

  if (!res.ok) {
    throw await apiErrorFromResponse(res);
  }

  return res.json();
}

export async function lookupOpenAQSensor(sensor_id: string): Promise<OpenAQLookupResult> {
  const res = await authFetch(`/admin/devices/openaq/lookup/sensor`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sensor_id }),
  });

  if (!res.ok) {
    throw await apiErrorFromResponse(res);
  }

  return res.json();
}

export async function createOpenAQDevices(
  locations: OpenAQLocation[],
  selectedSensors?: Record<string, number[]>
): Promise<OpenAQCreateResult> {
  return authFetchJson<OpenAQCreateResult>('/admin/devices/openaq/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ locations, selected_sensors: selectedSensors }),
  });
}


export type EventRecord = {
  event_id: number;
  event_type: string;
  source: string;
  severity: string;
  actor_user_id?: string | null;
  actor_email?: string | null;
  actor_display_name?: string | null;
  device_id?: number | null;
  sensor_id?: number | null;
  external_sensor_id?: string | null;
  endpoint?: string | null;
  params?: Record<string, unknown> | null;
  message?: string | null;
  raw_snippet?: string | null;
  created_at?: string | null;
};

export type QCFailureOutcome = 'flag_for_review' | 'mark_invalid';
export type QCFailureStatus = 'failed' | 'indeterminate';

export type QCFailureRecord = {
  measurement_qc_result_id: number;
  qc_result_created_at: string;
  measurement_id: number;
  measurement_observed_at: string | null;
  measurement_value: number;
  measurement_is_valid: boolean;
  device_id: number;
  device_name: string;
  sensor_id: number;
  external_sensor_id: string | null;
  data_source_id: number;
  data_source_name: string;
  provider_code: string | null;
  parameter_code: string | null;
  parameter_name: string | null;
  unit_code: string | null;
  unit_symbol: string | null;
  check_code: string;
  check_name: string;
  plugin_version: string | null;
  evaluation_status: QCFailureStatus;
  failure_action: QCFailureOutcome | null;
  reason_code: string | null;
  message: string | null;
  details: Record<string, unknown> | null;
  params_snapshot: Record<string, unknown> | null;
  rule_source: string | null;
  policy_snapshot: Record<string, unknown> | null;
  policy_provenance: Record<string, unknown> | null;
};

export type QCFailureListResponse = {
  items: QCFailureRecord[];
  total: number;
  limit: number;
  offset: number;
};

export type SystemStorageStatus = {
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  percent_free: number;
  status: 'healthy' | 'needs_attention' | 'critical';
};

export type SystemPreferencesRecord = {
  geoapify_api_key?: string | null;
  default_language_code: 'en' | 'es';
  system_timezone?: string;
  created_at?: string | null;
  updated_at?: string | null;
  last_updated_by_email?: string | null;
  last_updated_by_display_name?: string | null;
  last_updated_by_user_id?: string | null;
  storage?: SystemStorageStatus;
};

export type SystemPreferencesUpdatePayload = {
  geoapify_api_key?: string | null;
  default_language_code: 'en' | 'es';
  system_timezone: string;
};

export type JobRunRecord = {
  job_run_id: number;
  job_schedule_id: number;
  task: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
  summary?: Record<string, unknown> | null;
  error_message?: string | null;
};

export async function listEvents(filters?: {
  limit?: number;
  severity?: string;
  source?: string;
  event_type?: string;
}): Promise<EventRecord[]> {
  const params = new URLSearchParams();
  if (filters?.limit) params.set('limit', String(filters.limit));
  if (filters?.severity) params.set('severity', filters.severity);
  if (filters?.source) params.set('source', filters.source);
  if (filters?.event_type) params.set('event_type', filters.event_type);
  const qs = params.toString();
  return authFetchJson<EventRecord[]>(`/admin/events${qs ? `?${qs}` : ''}`);
}

export async function listQCFailures(filters?: {
  limit?: number;
  offset?: number;
  search?: string;
  parameter?: string;
  status?: QCFailureStatus;
  outcome?: QCFailureOutcome;
  data_source?: string;
}): Promise<QCFailureListResponse> {
  const params = new URLSearchParams();
  if (filters?.limit) params.set('limit', String(filters.limit));
  if (filters?.offset) params.set('offset', String(filters.offset));
  if (filters?.search) params.set('search', filters.search);
  if (filters?.parameter) params.set('parameter', filters.parameter);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.outcome) params.set('outcome', filters.outcome);
  if (filters?.data_source) params.set('data_source', filters.data_source);
  const qs = params.toString();
  return authFetchJson<QCFailureListResponse>(`/admin/events/qc-failures${qs ? `?${qs}` : ''}`);
}

export async function getSystemPreferences(): Promise<SystemPreferencesRecord> {
  return authFetchJson<SystemPreferencesRecord>('/admin/system-preferences');
}

export async function updateSystemPreferences(
  payload: SystemPreferencesUpdatePayload,
): Promise<SystemPreferencesRecord> {
  return authFetchJson<SystemPreferencesRecord>('/admin/system-preferences', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function listAllJobRuns(filters?: {
  limit?: number;
  status?: string;
  task?: string;
}): Promise<JobRunRecord[]> {
  const params = new URLSearchParams();
  if (filters?.limit) params.set('limit', String(filters.limit));
  if (filters?.status) params.set('status', filters.status);
  if (filters?.task) params.set('task', filters.task);
  const qs = params.toString();
  return authFetchJson<JobRunRecord[]>(`/admin/jobs/runs${qs ? `?${qs}` : ''}`);
}




export type UserRecord = {
  first_name?: string | null;
  last_name?: string | null;
  display_name?: string;
  user_id: string;
  email: string;
  org_id: string;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  roles: string[];
  
  failed_login_count?: number | null;
  last_failed_login_at?: string | null;
  locked_until?: string | null;
};


export type RoleRecord = {
  role_id: string;
  name: string;
  description?: string | null;
};


export type UserCreatePayload = {
  email: string;
  password: string;
  org_id?: string;
  roles?: string[];
  is_active?: boolean;
};


export type UserUpdatePayload = {
  first_name?: string | null;
  last_name?: string | null;
  email?: string;
  password?: string;
  is_active?: boolean;
  roles?: string[];
};


export async function listUsers(): Promise<UserRecord[]> {
  return authFetchJson<UserRecord[]>('/admin/users');
}


export async function listRoles(): Promise<RoleRecord[]> {
  return authFetchJson<RoleRecord[]>('/admin/users/roles');
}


export async function getUser(userId: string): Promise<UserRecord> {
  return authFetchJson<UserRecord>(`/admin/users/${encodeURIComponent(userId)}`);
}


export async function createUser(payload: UserCreatePayload): Promise<UserRecord> {
  return authFetchJson<UserRecord>('/admin/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}


export async function updateUser(userId: string, payload: UserUpdatePayload): Promise<UserRecord> {
  return authFetchJson<UserRecord>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}


export async function unlockUser(userId: string): Promise<UserRecord> {
  return authFetchJson<UserRecord>(`/admin/users/${encodeURIComponent(userId)}/unlock`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
}


export async function deleteUser(userId: string): Promise<void> {
  const response = await authFetch(`/admin/users/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw await apiErrorFromResponse(response);
}
