import { API_BASE } from './apiBase';

export type ComponentBuild = {
  commit_sha: string | null;
  build_time_utc: string | null;
};

export type FrontendVersion = {
  application_version: string;
  frontend: ComponentBuild;
};

export type BackendVersion = {
  application_version: string;
  backend: ComponentBuild;
  environment: 'development' | 'test' | 'staging' | 'production' | null;
};

declare const __FRONTEND_BUILD__: FrontendVersion;
export const frontendVersion = __FRONTEND_BUILD__;

export async function getBackendVersion(): Promise<BackendVersion> {
  const response = await fetch(`${API_BASE}/version`, { cache: 'no-store', signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error('Build metadata unavailable');
  const payload = await response.json() as Partial<BackendVersion> | null;
  if (!payload || typeof payload.application_version !== 'string' || !payload.backend
    || !(payload.backend.commit_sha === null || typeof payload.backend.commit_sha === 'string' && /^[0-9a-f]{40}$/.test(payload.backend.commit_sha))
    || !(payload.backend.build_time_utc === null || typeof payload.backend.build_time_utc === 'string' && Number.isFinite(Date.parse(payload.backend.build_time_utc)))
    || !(payload.environment === null || ['development', 'test', 'staging', 'production'].includes(payload.environment ?? ''))) {
    throw new Error('Build metadata contract unavailable');
  }
  return payload as BackendVersion;
}

export function compareBuilds(frontend: ComponentBuild, backend?: ComponentBuild): 'matching' | 'different' | 'unknown' {
  if (!frontend.commit_sha || !backend?.commit_sha) return 'unknown';
  return frontend.commit_sha === backend.commit_sha ? 'matching' : 'different';
}
