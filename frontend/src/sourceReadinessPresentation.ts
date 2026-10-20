import type { ExternalAPI } from './api';

// Present the backend readiness decision; credential presence is a separate fact.
export function sourceReadinessKey(source: ExternalAPI) {
  if (source.runnable_reason === 'unsupported_provider') return 'unsupported';
  if (source.provider_code !== 'demo' && source.requires_credential !== false && source.has_api_key === false && source.is_configured !== true && source.is_runnable !== true) return 'missingCredential';
  if (source.is_configured === false) return 'needsConfiguration';
  if (!source.enabled) return 'disabled';
  if (source.is_runnable === true) return 'ready';
  if (source.runnable_reason === 'paid_provider_requests_disabled') return 'operatorBlocked';
  if (source.runnable_reason === 'configuration_required') return 'needsConfiguration';
  return 'unknown';
}
