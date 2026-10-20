import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { mockAdministration } from './fixtures/administration';

const ADMIN_EMAIL = process.env.EMAIL_E2E_ADMIN_EMAIL
  ?? process.env.QC_E2E_ADMIN_EMAIL
  ?? 'qc-acceptance@example.com';
const ADMIN_PASSWORD = process.env.EMAIL_E2E_ADMIN_PASSWORD
  ?? process.env.QC_E2E_ADMIN_PASSWORD
  ?? 'CompassAQ-QC-Phase3!2026';
const ARTIFACT_DIRECTORY = resolve('../artifacts/email-phase1b3');

type EmailStatus = 'not_configured' | 'disabled' | 'needs_attention' | 'ready';

interface MockEmailConfiguration {
  enabled: boolean;
  status: EmailStatus;
  status_reason_codes: string[];
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_security_mode: 'starttls' | 'ssl_tls' | 'none' | null;
  smtp_username: string | null;
  password_configured: boolean;
  from_email: string | null;
  from_display_name: string | null;
  reply_to_email: string | null;
  administrator_recipients: string[];
  last_test_status: 'success' | 'failed' | null;
  last_test_error_code: string | null;
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
}

type SummaryStatus = 'summary_off' | 'blocked_email_delivery'
  | 'waiting_for_first_scheduled_period' | 'last_summary_sent'
  | 'last_summary_failed' | 'delivery_unknown';

interface MockAdministratorSummaryConfiguration {
  enabled: boolean;
  cadence: 'daily' | 'hourly' | 'every_15_minutes';
  daily_send_time: string;
  reporting_timezone: string;
  reporting_timezone_source: 'system_preferences' | 'summary_override';
  reporting_timezone_override: string | null;
  system_timezone: string;
  effective_at: string | null;
  schedule_status: SummaryStatus;
  blocker_codes: string[];
  email_delivery_ready: boolean;
  next_due_at: string | null;
  next_reporting_window: { period_start: string; period_end: string } | null;
  last_scheduled_delivery: {
    status: 'sent' | 'failed' | 'delivery_unknown';
    period_start: string;
    period_end: string;
    last_attempted_at: string | null;
    sent_at: string | null;
    error_code: string | null;
  } | null;
}

function freshAdministratorSummary(): MockAdministratorSummaryConfiguration {
  return {
    enabled: false,
    cadence: 'daily',
    daily_send_time: '07:00:00',
    reporting_timezone: 'UTC',
    reporting_timezone_source: 'system_preferences',
    reporting_timezone_override: null,
    system_timezone: 'UTC',
    effective_at: null,
    schedule_status: 'summary_off',
    blocker_codes: [],
    email_delivery_ready: true,
    next_due_at: null,
    next_reporting_window: null,
    last_scheduled_delivery: null,
  };
}

function freshConfiguration(): MockEmailConfiguration {
  return {
    enabled: false,
    status: 'not_configured',
    status_reason_codes: ['email_not_configured'],
    smtp_host: null,
    smtp_port: null,
    smtp_security_mode: null,
    smtp_username: null,
    password_configured: false,
    from_email: null,
    from_display_name: null,
    reply_to_email: null,
    administrator_recipients: [],
    last_test_status: null,
    last_test_error_code: null,
    last_tested_at: null,
    created_at: '2026-08-21T08:00:00Z',
    updated_at: '2026-08-21T08:00:00Z',
  };
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  mkdirSync(ARTIFACT_DIRECTORY, { recursive: true });
  const path = resolve(ARTIFACT_DIRECTORY, `${name}.png`);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

async function ensureFreshInstallation(page: Page) {
  const statusResponse = await page.request.get('/api/setup/status');
  expect(statusResponse.ok()).toBeTruthy();
  const setupStatus = await statusResponse.json();
  if (!setupStatus.is_setup_required) return;

  const adminResponse = await page.request.post('/api/setup/admin', {
    data: {
      email: ADMIN_EMAIL,
      password: ADMIN_PASSWORD,
      confirm_password: ADMIN_PASSWORD,
    },
  });
  expect(adminResponse.ok(), await adminResponse.text()).toBeTruthy();
  const completeResponse = await page.request.post('/api/setup/complete', {
    data: { default_language_code: 'en' },
  });
  expect(completeResponse.ok(), await completeResponse.text()).toBeTruthy();
}

async function signIn(page: Page) {
  await page.goto('/login');
  await page.locator('input[type="email"]').fill(ADMIN_EMAIL);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/map(?:\?|$)/);

  const accountMenu = page.locator('button[aria-controls="user-menu-dropdown"]');
  await accountMenu.click();
  await page.locator('#account-language-selector').selectOption('en');
  await expect(page.getByRole('link', { name: 'Admin', exact: true })).toBeVisible();
}

test('administrator understands, configures, and verifies email delivery', async ({ page }, testInfo) => {
  const evidence: Array<{ checkpoint: string; result: 'passed' }> = [];
  const passed = (checkpoint: string) => evidence.push({ checkpoint, result: 'passed' });
  let emailConfiguration = freshConfiguration();
  let failNextConfigurationRead = true;
  let failNextConfigurationWrite = true;
  let testAttempts = 0;
  let summaryTestAttempts = 0;
  let summaryPreviewAttempts = 0;
  let lastConfigurationUpdate: Record<string, unknown> | null = null;
  let administratorSummary = freshAdministratorSummary();
  let systemPreferences = {
    geoapify_api_key: null,
    default_language_code: 'en',
    system_timezone: 'UTC',
    updated_at: '2026-08-21T08:00:00Z',
    last_updated_by_email: 'qc-acceptance@example.com',
  };

  if (process.env.EMAIL_E2E_MOCK_AUTH === '1') {
    // Exercise the same email scenarios without requiring a local acceptance account.
    await mockAdministration(page);
    await page.route('**/api/auth/me/preferences', async (route) => {
      await route.fulfill({ json: {
        user_id: 'review-admin', email: ADMIN_EMAIL, roles: ['admin'], scopes: ['users:write'],
        preferred_language_code: route.request().postDataJSON().preferred_language_code,
      } });
    });
  } else {
    await ensureFreshInstallation(page);
    await signIn(page);
  }

  await page.route('**/api/admin/email/configuration', async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      if (failNextConfigurationRead) {
        failNextConfigurationRead = false;
        await new Promise((resolveDelay) => setTimeout(resolveDelay, 350));
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: { error_code: 'service_unavailable' } }),
        });
        return;
      }
      await route.fulfill({ json: emailConfiguration });
      return;
    }

    if (failNextConfigurationWrite) {
      failNextConfigurationWrite = false;
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 350));
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { error_code: 'service_unavailable' } }),
      });
      return;
    }

    const update = route.request().postDataJSON() as Record<string, unknown>;
    lastConfigurationUpdate = update;
    const materialFieldNames = [
      'smtp_host',
      'smtp_port',
      'smtp_security_mode',
      'smtp_username',
      'from_email',
      'from_display_name',
      'reply_to_email',
    ];
    const materialChanged = materialFieldNames.some((fieldName) => (
      JSON.stringify(update[fieldName]) !== JSON.stringify(
        emailConfiguration[fieldName as keyof MockEmailConfiguration],
      )
    )) || Object.hasOwn(update, 'smtp_password');
    const passwordConfigured = Object.hasOwn(update, 'smtp_password')
      ? update.smtp_password !== null
      : emailConfiguration.password_configured;
    const safeUpdate = { ...update };
    delete safeUpdate.smtp_password;
    const enabled = update.enabled === true;
    const keepsSuccessfulTest = !materialChanged && emailConfiguration.last_test_status === 'success';
    emailConfiguration = {
      ...emailConfiguration,
      ...safeUpdate,
      enabled,
      password_configured: passwordConfigured,
      status: enabled
        ? keepsSuccessfulTest ? 'ready' : 'needs_attention'
        : 'disabled',
      status_reason_codes: enabled
        ? keepsSuccessfulTest ? [] : ['test_required']
        : ['email_disabled'],
      last_test_status: materialChanged ? null : emailConfiguration.last_test_status,
      last_test_error_code: materialChanged ? null : emailConfiguration.last_test_error_code,
      last_tested_at: materialChanged ? null : emailConfiguration.last_tested_at,
      updated_at: '2026-08-21T09:00:00Z',
    } as MockEmailConfiguration;
    await route.fulfill({ json: emailConfiguration });
  });

  await page.route('**/api/admin/system-preferences', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: systemPreferences });
      return;
    }
    const update = route.request().postDataJSON() as typeof systemPreferences;
    systemPreferences = {
      ...systemPreferences,
      ...update,
      updated_at: '2026-08-21T08:30:00Z',
    };
    administratorSummary = {
      ...administratorSummary,
      system_timezone: systemPreferences.system_timezone,
      reporting_timezone: administratorSummary.reporting_timezone_source === 'system_preferences'
        ? systemPreferences.system_timezone
        : administratorSummary.reporting_timezone,
    };
    await route.fulfill({ json: systemPreferences });
  });

  await page.route('**/api/admin/email/test', async (route) => {
    testAttempts += 1;
    if (testAttempts === 1) {
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 350));
      emailConfiguration = {
        ...emailConfiguration,
        status: 'needs_attention',
        status_reason_codes: ['smtp_authentication_failed'],
        last_test_status: 'failed',
        last_test_error_code: 'smtp_authentication_failed',
        last_tested_at: '2026-08-21T09:05:00Z',
      };
      await route.fulfill({
        status: 502,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: {
            error_code: 'smtp_authentication_failed',
            error_context: { smtp_code: 535 },
            message: 'sanitized diagnostic',
          },
        }),
      });
      return;
    }
    emailConfiguration = {
      ...emailConfiguration,
      status: 'ready',
      status_reason_codes: [],
      last_test_status: 'success',
      last_test_error_code: null,
      last_tested_at: '2026-08-21T09:07:00Z',
    };
    await route.fulfill({
      json: {
        delivery_status: 'sent',
        recipient: emailConfiguration.administrator_recipients[0],
        sent_at: '2026-08-21T09:07:00Z',
      },
    });
  });

  await page.route('**/api/admin/email/administrator-summary', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: administratorSummary });
      return;
    }
    const update = route.request().postDataJSON() as {
      enabled: boolean;
      cadence: MockAdministratorSummaryConfiguration['cadence'];
      daily_send_time: string;
      reporting_timezone_mode: 'system' | 'override';
      reporting_timezone_override: string | null;
    };
    const effectiveTimezone = update.reporting_timezone_mode === 'system'
      ? administratorSummary.system_timezone
      : update.reporting_timezone_override ?? administratorSummary.reporting_timezone;
    administratorSummary = {
      ...administratorSummary,
      enabled: update.enabled,
      cadence: update.cadence,
      daily_send_time: update.daily_send_time,
      reporting_timezone: effectiveTimezone,
      reporting_timezone_source: update.reporting_timezone_mode === 'system'
        ? 'system_preferences'
        : 'summary_override',
      reporting_timezone_override: update.reporting_timezone_mode === 'system'
        ? null
        : update.reporting_timezone_override,
      effective_at: '2026-08-21T18:07:00Z',
      schedule_status: update.enabled ? 'waiting_for_first_scheduled_period' : 'summary_off',
      email_delivery_ready: true,
      blocker_codes: [],
      next_due_at: update.enabled ? (
        update.cadence === 'every_15_minutes'
          ? '2026-08-21T18:15:00Z'
          : update.cadence === 'hourly'
            ? '2026-08-21T19:00:00Z'
            : '2026-08-22T14:30:00Z'
      ) : null,
      next_reporting_window: update.enabled ? {
        period_start: update.cadence === 'daily' ? '2026-08-21T07:00:00Z' : '2026-08-21T18:00:00Z',
        period_end: update.cadence === 'daily' ? '2026-08-22T07:00:00Z' : '2026-08-21T18:15:00Z',
      } : null,
    };
    await route.fulfill({ json: administratorSummary });
  });

  await page.route('**/api/admin/email/administrator-summary/preview', async (route) => {
    summaryPreviewAttempts += 1;
    const needsAttention = summaryPreviewAttempts === 1;
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 300));
    await route.fulfill({
      json: {
        reporting_window: {
          period_start: '2026-08-21T18:00:00Z',
          period_end: '2026-08-21T18:15:00Z',
        },
        overall_status: needsAttention ? 'needs_attention' : 'all_systems_normal',
        attention_count: needsAttention ? 3 : 0,
        subject: needsAttention
          ? '[CompassAQ] Summary — 3 issues need attention'
          : '[CompassAQ] Summary — All systems normal',
        html_body: `<!doctype html><html><head><style>body{font:16px Arial;color:#172033;padding:24px}h1{color:#064789}section{border-top:1px solid #dbe4ed;padding-top:12px;margin-top:20px}.attention{padding:12px;background:#fff8e7;border-left:4px solid #d48a1f}</style></head><body><h1>CompassAQ Administrator Summary</h1><p>Reporting period: Aug 21, 11:00–11:15 PDT</p><div class="${needsAttention ? 'attention' : ''}">${needsAttention ? '3 issues need attention' : 'All systems normal'}</div>${needsAttention ? '<section><h2>Needs attention</h2><p>Two measurements were flagged for review with technical QC details.</p></section>' : ''}<section><h2>Data imports</h2><p>${needsAttention ? 'One scheduled import did not run.' : 'All scheduled imports completed.'}</p></section><section><h2>System events</h2><p>No additional significant system events.</p></section></body></html>`,
        text_body: `CompassAQ Administrator Summary\n\n${needsAttention ? '3 issues need attention' : 'All systems normal'}${needsAttention ? '\n\nNeeds attention\nTwo measurements were flagged for review with technical QC details.' : ''}\n\nData imports\nSystem events`,
      },
    });
  });

  await page.route('**/api/admin/email/administrator-summary/test', async (route) => {
    summaryTestAttempts += 1;
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 450));
    if (summaryTestAttempts === 1) {
      await route.fulfill({
        status: 504,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { error_code: 'smtp_connection_timeout' } }),
      });
      return;
    }
    const request = route.request().postDataJSON() as { recipient?: string };
    await route.fulfill({
      json: {
        delivery_status: 'sent',
        recipient: request.recipient ?? emailConfiguration.administrator_recipients[0],
        sent_at: '2026-08-21T18:09:00Z',
        subject: '[TEST] [CompassAQ] Summary',
        reporting_window: {
          period_start: '2026-08-21T18:00:00Z',
          period_end: '2026-08-21T18:15:00Z',
        },
      },
    });
  });

  await page.goto('/admin');
  const emailTile = page.getByRole('link', { name: /Email & notifications/ });
  await expect(emailTile).toBeVisible();
  await capture(page, testInfo, '00-admin-home-en-desktop');
  passed('Email & notifications is a first-class Admin destination');

  await page.getByRole('link', { name: /System Preferences/ }).click();
  await expect(page.getByRole('heading', { name: 'System Preferences' })).toBeVisible();
  const systemTimezone = page.getByLabel('System timezone');
  await expect(systemTimezone).toHaveValue('UTC');
  await expect(systemTimezone.locator('option', { hasText: 'Pacific Time' })).toHaveCount(1);
  await systemTimezone.selectOption('Asia/Manila');
  await page.locator('.preferences-save-actions').getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByText('System preferences updated.')).toBeVisible();
  await capture(page, testInfo, '00a-system-preferences-en-desktop');
  await page.setViewportSize({ width: 390, height: 844 });
  const systemPreferencesOverflow = await page.evaluate(() => (
    document.documentElement.scrollWidth - document.documentElement.clientWidth
  ));
  expect(systemPreferencesOverflow).toBeLessThanOrEqual(1);
  await capture(page, testInfo, '00b-system-preferences-en-mobile');
  passed('system timezone preference is readable, selectable, saved, and stable at mobile width');
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto('/admin');
  await expect(emailTile).toBeVisible();
  await emailTile.click();
  await expect(page.getByText('Loading email configuration…')).toBeVisible();
  await capture(page, testInfo, '01a-loading-en-desktop');
  passed('loading state is stable and clearly labeled');
  await expect(page.getByRole('alert')).toContainText('could not be loaded');
  await capture(page, testInfo, '01-load-error-en-desktop');
  passed('load failure is actionable');

  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(
    page.getByLabel('Overall status').getByText('Not configured', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('Port', { exact: true })).toHaveValue('587');
  await expect(page.getByLabel('Security')).toHaveValue('starttls');
  await capture(page, testInfo, '02-fresh-edit-en-desktop');
  passed('fresh state opens a grouped configuration editor');

  await page.getByLabel('SMTP server').fill('smtp.example.com');
  await page.getByLabel('SMTP username').fill('smtp-user');
  await page.getByLabel('SMTP password').fill('browser-only-secret');
  await page.getByLabel('From email').fill('sender@example.com');
  await page.getByLabel('From display name').fill('CompassAQ Alerts');
  await page.getByLabel('Reply-To email').fill('support@example.com');
  await page.getByRole('textbox', { name: 'Recipient 1', exact: true }).fill('primary@example.com');
  await expect(page.getByRole('button', { name: 'Send test email' })).toBeDisabled();
  await page.locator('.email-configuration-form').getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  await capture(page, testInfo, '02a-saving-en-desktop');
  passed('saving state prevents duplicate configuration writes');
  await expect(page.getByRole('alert')).toContainText('could not be saved');
  await capture(page, testInfo, '02b-save-failure-en-desktop');
  passed('save failure keeps the editor and entered values available for retry');
  await page.locator('.email-configuration-form').getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(
    page.getByLabel('Overall status').getByText('Needs attention', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('Overall status')).toContainText('Send a test email to verify delivery');
  await capture(page, testInfo, '03-test-required-en-desktop');
  passed('saved configuration clearly requires a delivery test');

  await page.getByRole('button', { name: 'Send test email' }).click();
  await expect(page.getByRole('button', { name: 'Sending test…' })).toBeDisabled();
  await capture(page, testInfo, '03a-test-sending-en-desktop');
  passed('test delivery shows a stable in-progress state');
  await expect(page.getByRole('alert')).toContainText('rejected the saved username or password');
  await page.getByText('More details').click();
  await expect(page.getByText('SMTP response code: 535')).toBeVisible();
  await capture(page, testInfo, '04-auth-failure-en-desktop');
  passed('authentication failure is actionable and sanitized');

  await page.getByRole('button', { name: 'Retry test' }).click();
  await expect(page.getByLabel('Overall status').getByText('Ready', { exact: true })).toBeVisible();
  await expect(page.locator('.email-test-result[role="status"]')).toContainText('Test email sent');
  await capture(page, testInfo, '05-ready-en-desktop');
  passed('successful retry produces the backend-owned ready state');

  const summarySection = page.locator('.administrator-summary-section');
  await summarySection.getByRole('heading', { name: 'Administrator summary' }).scrollIntoViewIfNeeded();
  await expect(summarySection.getByText('Summary off', { exact: true })).toBeVisible();
  await capture(page, testInfo, '06-summary-off-en-desktop');
  passed('fresh administrator summary is clearly off');

  await summarySection.getByLabel('Enable administrator summary').check();
  await summarySection.getByText('Advanced / Testing', { exact: true }).click();
  await summarySection.getByLabel('Testing — every 15 minutes').check();
  await expect(summarySection.getByRole('note')).toContainText('frequent email');
  await capture(page, testInfo, '07-summary-testing-unsaved-en-desktop');
  await summarySection.getByRole('button', { name: 'Save changes' }).click();
  await expect(summarySection.getByText('Waiting for first period', { exact: true })).toBeVisible();
  await expect(summarySection.getByText('Aug 22, 2026, 2:15 AM', { exact: true })).toBeVisible();
  await capture(page, testInfo, '08-summary-testing-scheduled-en-desktop');
  passed('15-minute commissioning schedule is explicit and has a backend-owned next due time');

  await summarySection.getByRole('button', { name: 'Preview summary' }).click();
  await expect(summarySection.getByRole('button', { name: 'Building preview…' })).toBeDisabled();
  await expect(summarySection.getByRole('heading', { name: 'Summary preview' })).toBeVisible();
  const previewFrame = summarySection.frameLocator('iframe[title="Rendered administrator summary email"]');
  await expect(previewFrame.getByRole('heading', { name: 'Needs attention' })).toBeVisible();
  await expect(previewFrame.getByRole('heading', { name: 'Data imports' })).toBeVisible();
  await expect(previewFrame.getByRole('heading', { name: 'QC activity' })).toHaveCount(0);
  await expect(previewFrame.getByRole('heading', { name: 'System events' })).toBeVisible();
  const previewContentPath = resolve(ARTIFACT_DIRECTORY, '09a-summary-email-content-en-desktop.png');
  await summarySection.locator('iframe[title="Rendered administrator summary email"]').scrollIntoViewIfNeeded();
  await page.screenshot({ path: previewContentPath, fullPage: false });
  await testInfo.attach('09a-summary-email-content-en-desktop', {
    path: previewContentPath,
    contentType: 'image/png',
  });
  await capture(page, testInfo, '09-summary-preview-attention-en-desktop');
  await page.setViewportSize({ width: 390, height: 844 });
  const mobilePreviewOverflow = await previewFrame.locator('html').evaluate((element) => (
    element.scrollWidth - element.clientWidth
  ));
  expect(mobilePreviewOverflow).toBeLessThanOrEqual(1);
  await capture(page, testInfo, '09b-summary-preview-attention-en-mobile');
  await page.setViewportSize({ width: 1280, height: 720 });
  passed('preview renders actual representative summary sections without sending');

  await summarySection.getByRole('button', { name: 'Send test summary' }).click();
  let summaryTestDialog = page.getByRole('dialog', { name: 'Send a test administrator summary?' });
  await summaryTestDialog.getByLabel('Test summary recipient').fill('one-time@example.com');
  await summaryTestDialog.getByRole('button', { name: 'Send test summary' }).click();
  await expect(summaryTestDialog.getByRole('button', { name: 'Sending test summary…' })).toBeDisabled();
  await capture(page, testInfo, '10-summary-test-sending-en-desktop');
  await expect(summarySection.getByRole('alert')).toContainText('did not respond in time');
  await capture(page, testInfo, '11-summary-test-failure-en-desktop');

  await summarySection.getByRole('button', { name: 'Send test summary' }).click();
  summaryTestDialog = page.getByRole('dialog', { name: 'Send a test administrator summary?' });
  await expect(summaryTestDialog.getByLabel('Test summary recipient')).toHaveValue('primary@example.com');
  await summaryTestDialog.getByLabel('Test summary recipient').fill('one-time@example.com');
  await summaryTestDialog.getByRole('button', { name: 'Send test summary' }).click();
  await expect(summarySection.getByRole('status')).toContainText('Test summary sent to one-time@example.com');
  await capture(page, testInfo, '12-summary-test-success-en-desktop');
  passed('test-summary confirmation, progress, failure, retry, and one-time recipient are deterministic');

  await summarySection.getByLabel('Daily').check();
  await summarySection.getByLabel('Send time').fill('07:30');
  await summarySection.getByLabel('Reporting timezone').selectOption('America/Los_Angeles');
  await summarySection.getByRole('button', { name: 'Save changes' }).click();
  await expect(summarySection.getByText('Daily at 7:30 AM', { exact: true })).toBeVisible();
  await summarySection.getByRole('button', { name: 'Preview summary' }).click();
  await expect(summarySection.getByText('All systems normal', { exact: true })).toBeVisible();
  await capture(page, testInfo, '13-summary-daily-preview-normal-en-desktop');
  passed('Daily production schedule and all-normal preview are readable');

  administratorSummary = {
    ...administratorSummary,
    schedule_status: 'blocked_email_delivery',
    email_delivery_ready: false,
    blocker_codes: ['test_required'],
  };
  await page.reload();
  await expect(page.locator('.administrator-summary-section').getByText('Blocked', { exact: true })).toBeVisible();
  await page.locator('.administrator-summary-section').scrollIntoViewIfNeeded();
  await capture(page, testInfo, '14-summary-blocked-en-desktop');

  administratorSummary = {
    ...administratorSummary,
    schedule_status: 'last_summary_failed',
    email_delivery_ready: true,
    blocker_codes: [],
    last_scheduled_delivery: {
      status: 'failed',
      period_start: '2026-08-20T07:00:00Z',
      period_end: '2026-08-21T07:00:00Z',
      last_attempted_at: '2026-08-21T14:31:00Z',
      sent_at: null,
      error_code: 'smtp_connection_timeout',
    },
  };
  await page.reload();
  await expect(page.locator('.administrator-summary-section').getByText('Last summary failed', { exact: true })).toBeVisible();
  await page.locator('.administrator-summary-section').scrollIntoViewIfNeeded();
  await capture(page, testInfo, '15-summary-last-failed-en-desktop');

  administratorSummary = {
    ...administratorSummary,
    schedule_status: 'delivery_unknown',
    last_scheduled_delivery: {
      ...administratorSummary.last_scheduled_delivery!,
      status: 'delivery_unknown',
      error_code: 'smtp_server_disconnected',
    },
  };
  await page.reload();
  await expect(page.locator('.administrator-summary-section')).toContainText(
    'It will not resend it automatically to avoid a duplicate.',
  );
  await page.locator('.administrator-summary-section').scrollIntoViewIfNeeded();
  await capture(page, testInfo, '16-summary-delivery-unknown-en-desktop');
  passed('blocked, failed, and ambiguous delivery states use distinct human wording');

  administratorSummary = {
    ...administratorSummary,
    schedule_status: 'waiting_for_first_scheduled_period',
    last_scheduled_delivery: null,
  };
  await page.reload();

  const successfulTransportTestedAt = emailConfiguration.last_tested_at;
  await page.getByRole('button', { name: 'Edit configuration' }).click();
  await expect(page.getByLabel('SMTP server')).toHaveValue('smtp.example.com');
  await expect(page.getByLabel('Port', { exact: true })).toHaveValue('587');
  await expect(page.getByLabel('Security')).toHaveValue('starttls');
  await expect(page.getByLabel('SMTP username')).toHaveValue('smtp-user');
  await expect(page.getByLabel('From email')).toHaveValue('sender@example.com');
  await expect(page.getByLabel('From display name')).toHaveValue('CompassAQ Alerts');
  await expect(page.getByLabel('Reply-To email')).toHaveValue('support@example.com');
  await page.getByRole('textbox', { name: 'Recipient 1', exact: true }).fill('updated@example.com');
  await page.locator('.email-configuration-form').getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByLabel('Overall status').getByText('Ready', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Test delivery', exact: true }).getByText('Last test succeeded', { exact: true }),
  ).toBeVisible();
  expect(lastConfigurationUpdate).toMatchObject({
    enabled: true,
    smtp_host: 'smtp.example.com',
    smtp_port: 587,
    smtp_security_mode: 'starttls',
    smtp_username: 'smtp-user',
    from_email: 'sender@example.com',
    from_display_name: 'CompassAQ Alerts',
    reply_to_email: 'support@example.com',
    administrator_recipients: ['updated@example.com'],
  });
  expect(lastConfigurationUpdate).not.toHaveProperty('smtp_password');
  expect(emailConfiguration.last_test_status).toBe('success');
  expect(emailConfiguration.last_tested_at).toBe(successfulTransportTestedAt);
  passed('recipient-only changes preserve the successful transport verification');

  await page.getByRole('button', { name: 'Edit configuration' }).click();
  await page.getByLabel('Enable email delivery').uncheck();
  await page.locator('.email-configuration-form').getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByLabel('Overall status').getByText('Disabled', { exact: true })).toBeVisible();
  await capture(page, testInfo, '17-disabled-en-desktop');
  passed('disabled state preserves readable saved configuration');

  await page.getByRole('button', { name: 'Edit configuration' }).click();
  await page.getByLabel('Enable email delivery').check();
  await page.locator('.email-configuration-form').getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByLabel('Overall status').getByText('Ready', { exact: true })).toBeVisible();

  await page.locator('button[aria-controls="user-menu-dropdown"]').click();
  await page.locator('#account-language-selector').selectOption('es');
  await expect(page.getByRole('heading', { name: 'Correo y notificaciones' })).toBeVisible();
  await expect(page.locator('.email-admin-page').getByRole('status')).toHaveText('Se guardó la configuración de correo.');
  await page.locator('button[aria-controls="user-menu-dropdown"]').click();
  await page.setViewportSize({ width: 768, height: 1024 });
  await capture(page, testInfo, '18-summary-daily-es-tablet');
  passed('Spanish tablet ready state is readable');

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel('Estado general').getByText('Listo', { exact: true })).toBeVisible();
  const horizontalOverflow = await page.evaluate(() => (
    document.documentElement.scrollWidth - document.documentElement.clientWidth
  ));
  expect(horizontalOverflow).toBeLessThanOrEqual(1);
  await capture(page, testInfo, '19-summary-daily-es-mobile');
  passed('Spanish 390px mobile state has no horizontal overflow');

  mkdirSync(ARTIFACT_DIRECTORY, { recursive: true });
  writeFileSync(
    resolve(ARTIFACT_DIRECTORY, 'browser-acceptance.json'),
    `${JSON.stringify({ schema_version: 1, result: 'passed', checkpoints: evidence }, null, 2)}\n`,
    'utf8',
  );
});
