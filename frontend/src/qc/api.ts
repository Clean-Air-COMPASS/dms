import { authFetchJson } from '../auth';
import type {
  QcCheckMetadata,
  QcOverride,
  QcOverrideInput,
  QcParameterListResponse,
  QcPluginsResponse,
  QcPolicyResponse,
  QcPreviewInput,
  QcPreviewResponse,
  QcSensorSearchResponse,
} from './types';
import { isUnitScopedCheck } from './presentation';

export async function listQcChecks(): Promise<QcCheckMetadata[]> {
  const response = await authFetchJson<{ items: QcCheckMetadata[] }>('/admin/qc/checks');
  return response.items;
}

export function listQcParameters(): Promise<QcParameterListResponse> {
  return authFetchJson<QcParameterListResponse>('/admin/qc/parameters');
}

export function getParameterPolicy(parameterId: number): Promise<QcPolicyResponse> {
  return authFetchJson<QcPolicyResponse>(`/admin/qc/parameters/${parameterId}/policy`);
}

export function getSourceParameterPolicy(
  externalApiId: number,
  parameterId: number,
): Promise<QcPolicyResponse> {
  return authFetchJson<QcPolicyResponse>(
    `/admin/qc/sources/${externalApiId}/parameters/${parameterId}/policy`,
  );
}

export function getSensorPolicy(sensorId: number): Promise<QcPolicyResponse> {
  return authFetchJson<QcPolicyResponse>(`/admin/qc/sensors/${sensorId}/policy`);
}

function replacementBody(overrides: QcOverrideInput[]): string {
  return JSON.stringify({ overrides });
}

export function replaceParameterPolicy(
  parameterId: number,
  overrides: QcOverrideInput[],
): Promise<QcPolicyResponse> {
  return authFetchJson<QcPolicyResponse>(`/admin/qc/parameters/${parameterId}/policy`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: replacementBody(overrides),
  });
}

export function replaceSourceParameterPolicy(
  externalApiId: number,
  parameterId: number,
  overrides: QcOverrideInput[],
): Promise<QcPolicyResponse> {
  return authFetchJson<QcPolicyResponse>(
    `/admin/qc/sources/${externalApiId}/parameters/${parameterId}/policy`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: replacementBody(overrides),
    },
  );
}

export function replaceSensorPolicy(
  sensorId: number,
  overrides: QcOverrideInput[],
): Promise<QcPolicyResponse> {
  return authFetchJson<QcPolicyResponse>(`/admin/qc/sensors/${sensorId}/policy`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: replacementBody(overrides),
  });
}

export function resetParameterPolicy(parameterId: number): Promise<QcPolicyResponse> {
  return authFetchJson<QcPolicyResponse>(`/admin/qc/parameters/${parameterId}/policy`, {
    method: 'DELETE',
  });
}

export function resetParameterCheck(
  parameterId: number,
  checkCode: string,
  unitCode?: string | null,
): Promise<QcPolicyResponse> {
  const query = unitCode ? `?unit_code=${encodeURIComponent(unitCode)}` : '';
  return authFetchJson<QcPolicyResponse>(
    `/admin/qc/parameters/${parameterId}/policy/checks/${encodeURIComponent(checkCode)}${query}`,
    { method: 'DELETE' },
  );
}

export function resetSourceParameterPolicy(
  externalApiId: number,
  parameterId: number,
): Promise<QcPolicyResponse> {
  return authFetchJson<QcPolicyResponse>(
    `/admin/qc/sources/${externalApiId}/parameters/${parameterId}/policy`,
    { method: 'DELETE' },
  );
}

export function resetSourceParameterCheck(
  externalApiId: number,
  parameterId: number,
  checkCode: string,
  unitCode?: string | null,
): Promise<QcPolicyResponse> {
  const query = unitCode ? `?unit_code=${encodeURIComponent(unitCode)}` : '';
  return authFetchJson<QcPolicyResponse>(
    `/admin/qc/sources/${externalApiId}/parameters/${parameterId}/policy/checks/${encodeURIComponent(checkCode)}${query}`,
    { method: 'DELETE' },
  );
}

export function resetSensorPolicy(sensorId: number): Promise<QcPolicyResponse> {
  return authFetchJson<QcPolicyResponse>(`/admin/qc/sensors/${sensorId}/policy`, {
    method: 'DELETE',
  });
}

export function resetSensorCheck(
  sensorId: number,
  checkCode: string,
  unitCode?: string | null,
): Promise<QcPolicyResponse> {
  const query = unitCode ? `?unit_code=${encodeURIComponent(unitCode)}` : '';
  return authFetchJson<QcPolicyResponse>(
    `/admin/qc/sensors/${sensorId}/policy/checks/${encodeURIComponent(checkCode)}${query}`,
    { method: 'DELETE' },
  );
}

export function previewQcPolicy(payload: QcPreviewInput): Promise<QcPreviewResponse> {
  return authFetchJson<QcPreviewResponse>('/admin/qc/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function countQcSensors(filters: {
  parameterId: number;
  externalApiId?: number;
  hasOverrides?: boolean;
}): Promise<QcSensorSearchResponse> {
  const search = new URLSearchParams({
    parameter_id: String(filters.parameterId),
    limit: '1',
  });
  if (filters.externalApiId !== undefined) {
    search.set('external_api_id', String(filters.externalApiId));
  }
  if (filters.hasOverrides !== undefined) {
    search.set('has_overrides', String(filters.hasOverrides));
  }
  return authFetchJson<QcSensorSearchResponse>(`/admin/qc/sensors/search?${search}`);
}

export function searchQcSensors(filters: {
  query?: string;
  parameterId?: number;
  externalApiId?: number;
  hasSensorSpecificQc?: boolean;
  limit: number;
  offset: number;
}): Promise<QcSensorSearchResponse> {
  const search = new URLSearchParams({
    limit: String(filters.limit),
    offset: String(filters.offset),
  });
  if (filters.query?.trim()) search.set('query', filters.query.trim());
  if (filters.parameterId !== undefined) {
    search.set('parameter_id', String(filters.parameterId));
  }
  if (filters.externalApiId !== undefined) {
    search.set('external_api_id', String(filters.externalApiId));
  }
  if (filters.hasSensorSpecificQc !== undefined) {
    search.set('has_sensor_specific_qc', String(filters.hasSensorSpecificQc));
  }
  return authFetchJson<QcSensorSearchResponse>(`/admin/qc/sensors/search?${search}`);
}

export function getQcPlugins(): Promise<QcPluginsResponse> {
  return authFetchJson<QcPluginsResponse>('/admin/plugins');
}

export function serializeOverride(override: QcOverride): QcOverrideInput {
  return {
    check_code: override.check_code,
    enabled_override: override.enabled_override,
    failure_action_override: override.failure_action_override,
    settings: { ...override.settings },
    policy_unit_code: override.policy_unit?.unit_code ?? null,
  };
}

export function mergeCheckOverride(
  currentOverrides: QcOverride[],
  checkCode: string,
  unitSettings: string[],
  currentUnitCode: string | null,
  replacement: QcOverrideInput | null,
): QcOverrideInput[] {
  const unitScoped = isUnitScopedCheck({ unit_settings: unitSettings });
  const replacementUnitCode = replacement?.policy_unit_code ?? null;
  const overrides = currentOverrides
    .filter((override) => {
      if (override.check_code !== checkCode) return true;
      if (!unitScoped) return false;
      const overrideUnitCode = override.policy_unit?.unit_code ?? null;
      return overrideUnitCode !== currentUnitCode
        && overrideUnitCode !== replacementUnitCode;
    })
    .map(serializeOverride);
  if (replacement) overrides.push(replacement);
  return overrides.sort((left, right) => left.check_code.localeCompare(right.check_code));
}
