import { afterEach, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import SourceReadiness from '../SourceReadiness';
import { sourceReadinessKey } from '../sourceReadinessPresentation';
import type { ExternalAPI } from '../api';
import i18n from '../i18n';

const source: ExternalAPI = { external_api_id: 1, name: 'OpenAQ', provider_code: 'openaq', enabled: true, requires_credential: true, has_api_key: false, is_configured: false, is_runnable: false, runnable_reason: 'configuration_required' };
afterEach(async () => { await i18n.changeLanguage('en'); });
it.each(['en', 'es'])('separates missing credentials from enablement and scheduling in %s', async language => {
  await i18n.changeLanguage(language);
  render(<SourceReadiness source={{ ...source, enabled: false, runnable_reason: 'disabled' }} scheduleState="on" />);
  expect(screen.getByRole('heading')).toHaveTextContent(i18n.t('dataSources:workflow.needsConfiguration'));
  expect(screen.getByRole('status')).toHaveTextContent(i18n.t('dataSources:workflow.missingCredential'));
  expect(screen.getByRole('status')).toHaveTextContent(i18n.t('dataSources:workflow.schedule.on'));
  expect(screen.getByRole('link')).toHaveAttribute('href', '#source-configuration');
});
it.each([
  [{ is_configured: false, has_api_key: false, runnable_reason: 'unsupported_provider' }, 'unsupported'],
  [{ is_configured: false, has_api_key: true }, 'needsConfiguration'],
  [{ is_configured: true, has_api_key: true, enabled: false }, 'disabled'],
  [{ is_configured: true, has_api_key: true, is_runnable: false, runnable_reason: 'paid_provider_requests_disabled' }, 'operatorBlocked'],
  [{ is_configured: true, has_api_key: true, is_runnable: true }, 'ready'],
  [{ provider_code: 'demo', requires_credential: false, has_api_key: false, is_configured: true, is_runnable: true }, 'ready'],
] as const)('preserves the backend readiness decision and provider differences', (patch, expected) => {
  expect(sourceReadinessKey({ ...source, ...patch })).toBe(expected);
});
it('suggests automation after a successful import when the schedule is off', () => {
  render(<SourceReadiness source={{ ...source, has_api_key: true, is_configured: true, is_runnable: true, latest_import: { job_run_id: 1, job_schedule_id: 1, task: 'openaq_import', status: 'success' } }} scheduleState="off" />);
  expect(screen.getByRole('link', { name: 'Configure automatic imports' })).toHaveAttribute('href', '#source-schedule');
});
it('uses a noun phrase for Spanish import settings', () => {
  expect(i18n.getFixedT('es', 'dataSources')('adminSources.actions.importSettings')).toBe('Configuración de importación');
});

it('accepts deployment credentials using authoritative backend readiness', () => {
  const deployment = { ...source, has_api_key: false, is_configured: true, is_runnable: true, runnable_reason: 'ready' as const };
  expect(sourceReadinessKey(deployment)).toBe('ready');
  render(<SourceReadiness source={deployment} scheduleState="on" />);
  expect(screen.getByRole('status')).toHaveTextContent('Credential supplied by the deployment');
  expect(screen.queryByText(/Missing API key/)).not.toBeInTheDocument();
});
