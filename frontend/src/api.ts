import { API_BASE } from './apiBase';
import { authFetch, authFetchJson } from './auth';

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
        throw new Error(`Request failed: ${res.status} ${res.statusText}`);
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
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}


export type PluginInfo = {
  name: string;
  display_name?: string;
  long_description?: string;
  version?: string;
  qc_api?: string;
  param_schema?: Record<string, any> | null;
  origin?: 'local' | 'entry_point';
  file_path?: string | null;
  deletable?: boolean;
};

export type QCRule = {
  qc_rule_id: number;
  check_code: string;
  sensor_id?: number | null;
  parameter_id?: number | null;
  aggregate_code?: string | null;
  enabled: boolean;
  params?: Record<string, any> | null;
  version?: number | null;
  state?: string | null;
  draft_params?: Record<string, any> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export async function listQcPlugins(): Promise<PluginInfo[]> {
  
  try {
    const meta = await authFetchJson<{ plugins: PluginInfo[] }>("/admin/plugins");
    return meta.plugins as PluginInfo[];
  } catch {
    return authFetchJson<PluginInfo[]>("/admin/qc/plugins");
  }
}

export async function listQcRules(): Promise<QCRule[]> {
  return authFetchJson<QCRule[]>("/admin/qc/rules");
}

export async function saveRuleDraft(qc_rule_id: number, draft_params: Record<string, any>): Promise<QCRule> {
  return authFetchJson<QCRule>(`/admin/qc/rules/${qc_rule_id}/draft`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft_params }),
  });
}

export type PreviewResult = {
  qc_rule_id: number;
  check_code: string;
  threshold: number;
  since: string;
  samples: number;
  would_fail: number;
  would_pass: number;
};

export async function previewRule(qc_rule_id: number, hours: number = 24): Promise<PreviewResult> {
  return authFetchJson<PreviewResult>(`/admin/qc/rules/${qc_rule_id}/preview?hours=${encodeURIComponent(hours)}`, {
    method: 'POST',
  });
}

export async function activateRule(qc_rule_id: number): Promise<QCRule> {
  return authFetchJson<QCRule>(`/admin/qc/rules/${qc_rule_id}/activate`, {
    method: 'POST',
  });
}


export async function createLocalPlugin(name: string, description?: string): Promise<any> {
  return authFetchJson(`/admin/plugins/local`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
}

export async function deletePlugin(name: string): Promise<any> {
  return authFetchJson(`/admin/plugins/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export async function uploadPlugin(file: File, overwrite = false): Promise<any> {
  const fd = new FormData();
  fd.append('file', file);
  const sep = overwrite ? '?overwrite=true' : '';
  return authFetchJson(`/admin/plugins/upload${sep}`, {
    method: 'POST',
    body: fd,
  });
}

export async function runImport(source: string, target_sensor_id?: string, force = false, api_key?: string): Promise<{ status: number; ok: boolean; data: any }> {
  const res = await authFetch(`/admin/imports/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, target_sensor_id, force, api_key }),
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
  failed_records: number;
  errors?: string[];
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


export type DeviceRecord = {
  device_id: number;
  name: string;
  friendly_name?: string | null;
  external_id?: string | null;
  external_api_id?: number | null;
  external_api_name?: string | null;
  manual_data_source_name?: string | null;
  device_type?: string | null;
  model?: string | null;
  network?: string | null;
  status?: string | null;
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
  last_seen_at?: string | null;
  created_at?: string | null;
  is_external?: boolean;
};

export type DevicePayload = Partial<Omit<DeviceRecord, 'device_id' | 'created_at' | 'last_seen_at'>>;

export type DeviceSensorSummary = {
  sensor_id: number;
  external_sensor_id?: string | null;
  aggregation_code?: string | null;
  parameter_code?: string | null;
  parameter_name?: string | null;
  unit_symbol?: string | null;
  value?: number | null;
  observed_at?: string | null;
  is_valid?: boolean | null;
  
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

export async function listDevicesAdmin(filters?: Partial<{ name: string; type: string; status: string; network: string; last_seen_from: string; last_seen_to: string; page: number; page_size: number; external_device_id?: string; external_sensor_id?: string; sensor_id?: number; }>): Promise<DeviceRecord[]> {
  const params = new URLSearchParams();
  if (filters?.name) params.set('name', filters.name);
  if (filters?.type) params.set('type', filters.type);
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
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
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
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
}


export type ExternalAPI = {
  external_api_id: number;
  name: string;
  base_url?: string | null;
  description?: string | null;
  api_key?: string | null;
  params?: Record<string, any> | null;
  is_active?: boolean;
  device_count?: number;
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

export async function updateExternalAPI(external_api_id: number, payload: Partial<{ base_url: string; description: string; api_key: string; params: Record<string, any>; is_active: boolean; }>): Promise<ExternalAPI> {
  return authFetchJson<ExternalAPI>(`/admin/external_apis/${external_api_id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function createExternalAPI(payload: { name: string; base_url?: string; description?: string; api_key?: string; params?: Record<string, any>; is_active?: boolean; }): Promise<ExternalAPI> {
  return authFetchJson<ExternalAPI>(`/admin/external_apis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function deleteExternalAPI(external_api_id: number): Promise<void> {
  const res = await authFetch(`/admin/external_apis/${external_api_id}`, { method: 'DELETE' });
  if (!res.ok) {
    let errorMessage = `Request failed: ${res.status} ${res.statusText}`;
    try {
      const errorData = await res.json();
      if (errorData.detail) errorMessage = errorData.detail;
    } catch {
      // keep default error
    }
    throw new Error(errorMessage);
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

export async function lookupPurpleAirSensor(sensor_index: string): Promise<PurpleAirLookupResult> {
  return authFetchJson<PurpleAirLookupResult>('/admin/devices/purpleair/lookup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sensor_index }),
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

  if (res.status === 429) {
    throw new Error('OpenAQ rate limit reached. Please try again later.');
  }

  if (!res.ok) {
    let detail = `Request failed: ${res.status}`;
    try {
      const err = await res.json();
      if (err.detail) detail = err.detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  return res.json();
}

export async function lookupOpenAQSensor(sensor_id: string): Promise<OpenAQLookupResult> {
  const res = await authFetch(`/admin/devices/openaq/lookup/sensor`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sensor_id }),
  });

  if (res.status === 429) {
    throw new Error('OpenAQ rate limit reached. Please try again later.');
  }

  if (res.status === 404) {
    throw new Error('Sensor not found.');
  }

  if (!res.ok) {
    let detail = `Request failed: ${res.status}`;
    try {
      const err = await res.json();
      if (err.detail) detail = err.detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
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
  device_id?: number | null;
  sensor_id?: number | null;
  external_sensor_id?: string | null;
  endpoint?: string | null;
  params?: Record<string, unknown> | null;
  message?: string | null;
  raw_snippet?: string | null;
  created_at?: string | null;
};

export type SystemPreferencesRecord = {
  geoapify_api_key?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type SystemPreferencesUpdatePayload = {
  geoapify_api_key?: string | null;
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
  await authFetchJson(`/admin/users/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
}
