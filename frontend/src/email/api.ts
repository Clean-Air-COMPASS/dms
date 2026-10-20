import { authFetchJson } from '../auth';
import type {
  AdministratorSummaryConfiguration,
  AdministratorSummaryPreview,
  AdministratorSummaryPreviewOptions,
  AdministratorSummaryScheduleUpdate,
  AdministratorSummaryTestOptions,
  AdministratorSummaryTestResult,
  EmailConfiguration,
  EmailConfigurationUpdate,
  EmailTestResult,
} from './types';

export function getAdministratorSummaryConfiguration(): Promise<AdministratorSummaryConfiguration> {
  return authFetchJson<AdministratorSummaryConfiguration>('/admin/email/administrator-summary');
}

export function updateAdministratorSummaryConfiguration(
  update: AdministratorSummaryScheduleUpdate,
): Promise<AdministratorSummaryConfiguration> {
  return authFetchJson<AdministratorSummaryConfiguration>('/admin/email/administrator-summary', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  });
}

export function previewAdministratorSummary(
  options: AdministratorSummaryPreviewOptions,
): Promise<AdministratorSummaryPreview> {
  return authFetchJson<AdministratorSummaryPreview>(
    '/admin/email/administrator-summary/preview',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options),
    },
  );
}

export function sendAdministratorSummaryTest(
  options: AdministratorSummaryTestOptions,
): Promise<AdministratorSummaryTestResult> {
  return authFetchJson<AdministratorSummaryTestResult>(
    '/admin/email/administrator-summary/test',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options),
    },
  );
}

export function getEmailConfiguration(): Promise<EmailConfiguration> {
  return authFetchJson<EmailConfiguration>('/admin/email/configuration');
}

export function updateEmailConfiguration(
  update: EmailConfigurationUpdate,
): Promise<EmailConfiguration> {
  return authFetchJson<EmailConfiguration>('/admin/email/configuration', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  });
}

export function sendEmailTest(recipient?: string): Promise<EmailTestResult> {
  return authFetchJson<EmailTestResult>('/admin/email/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(recipient ? { recipient } : {}),
  });
}
