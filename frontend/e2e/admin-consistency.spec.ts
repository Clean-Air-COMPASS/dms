import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';

import { mockAdministration, stamp } from './fixtures/administration';
import enAdmin from '../src/i18n/locales/en/admin.json' with { type: 'json' };

const runImportNowLabel = enAdmin.testImportTab.actions.testRun;

for (const width of [1440, 390]) {
  test(`Admin task workflows ${width}`, async ({ page }) => {
    page.setDefaultTimeout(15000);
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const state = await mockAdministration(page);
    page.on('dialog', dialog => dialog.accept());
    const capture = async (name: string) => {
      await page.screenshot({ path: `../artifacts/admin-consistency/after/${name}-en-${width}.png`, fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    };
    await page.goto('/admin');
    await page.getByRole('link', { name: /^Devices/ }).click();
    await page.getByPlaceholder('Search name…').fill('missing');
    await expect(page.getByText('No devices found.')).toBeVisible();
    await capture('devices-empty');
    await page.getByRole('button', { name: 'Reset', exact: true }).click();
    await page.getByRole('link', { name: /Open Central Library/ }).click();
    await page.getByLabel('Friendly Name').fill('Library review');
    await page.getByRole('button', { name: 'Save changes', exact: true }).click();
    await expect.poll(() => state.device.friendly_name).toBe('Library review');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/devices(?:\?|$)/);
    await page.getByRole('button', { name: 'Add device' }).click();
    await page.getByRole('button', { name: /Manual Entry/ }).click();
    await page.getByRole('textbox', { name: /^Name/ }).fill('Manual review station');
    await page.getByLabel('Data Source', { exact: false }).selectOption('1');
    await page.getByRole('button', { name: 'Add device', exact: true }).click();
    await expect.poll(() => state.writes.includes('/admin/devices')).toBeTruthy();

    await page.goto('/admin/devices/new');
    await page.getByRole('button', { name: /PurpleAir/ }).click();
    await page.getByRole('textbox').fill('12345');
    await page.getByRole('button', { name: 'Lookup', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await capture('purpleair-confirmation');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: 'Lookup', exact: true }).click();
    await page.getByRole('button', { name: /Proceed/ }).click();
    await expect(page.getByRole('heading', { name: 'Device Preview' })).toBeVisible();
    await capture('purpleair-preview');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page).toHaveURL(/123\/edit/);

    await page.goto('/admin/devices/new/openaq');
    await page.getByRole('button', { name: /Sensor ID/i }).click();
    await page.getByRole('textbox').fill('77');
    await page.getByRole('button', { name: /Lookup/i }).click();
    await capture('openaq-confirmation');
    await page.getByRole('button', { name: 'Proceed', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Search Results' })).toBeVisible();
    await capture('openaq-results');
    await page.getByRole('button', { name: /Save Selected/ }).click();
    await expect(page).toHaveURL(/123\/edit/);

    await page.goto('/admin/sources/1');
    await page.getByLabel('Enabled', { exact: true }).uncheck();
    await page.locator('#source-configuration').getByRole('button', { name: 'Save changes', exact: true }).click();
    await expect.poll(() => state.sources[0].enabled).toBe(false);
    await page.getByRole('button', { name: 'Replace credential' }).click();
    await capture('source-credential-replace');
    await page.getByRole('button', { name: /Keep.*credential/ }).click();

    await capture('source-import-settings');
    await page.locator('#source-schedule').getByRole('button', { name: /Save/ }).click();
    await expect.poll(() => state.writes.includes('/admin/jobs/schedules/1')).toBeTruthy();
    await expect(page.getByRole('button', { name: runImportNowLabel, exact: true })).toBeDisabled();

    await page.getByLabel('Enabled', { exact: true }).check();
    await page.locator('#source-configuration').getByRole('button', { name: 'Save changes', exact: true }).click();

    await page.getByRole('button', { name: runImportNowLabel, exact: true }).click();
    await expect.poll(() => state.writes.includes('/admin/imports/run')).toBeTruthy();
    await capture('source-test-import-result');

    await page.goto('/admin/email');
    await page.getByRole('button', { name: 'Send test email', exact: true }).click();
    await expect.poll(() => state.writes.includes('/admin/email/test')).toBeTruthy();
    await capture('email-test-result');
    await page.getByRole('button', { name: 'Edit configuration' }).click();
    await capture('email-editor');
    for (const field of await page.locator('.email-form-section input, .email-form-section select').all()) {
      const contained = await field.evaluate(element => {
        const bounds = element.getBoundingClientRect();
        const card = element.closest('.card')!.getBoundingClientRect();
        return bounds.left >= card.left && bounds.right <= card.right;
      });
      expect(contained, 'Email controls must remain inside their form section').toBeTruthy();
    }
    await page.getByRole('textbox', { name: 'SMTP server', exact: true }).fill('smtp.review.example.org');
    await page.locator('.email-configuration-form').getByRole('button', { name: 'Save changes', exact: true }).click();
    await expect.poll(() => state.email.smtp_host).toBe('smtp.review.example.org');
    await page.getByRole('checkbox', { name: 'Enable administrator summary', exact: true }).check();
    await page.locator('.administrator-summary-form').getByRole('button', { name: 'Save changes', exact: true }).click();
    await expect.poll(() => state.summary.enabled).toBe(true);

    await page.goto('/admin/uploads/csv');
    await page.getByRole('button', { name: 'Upload CSV' }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await page.locator('input[type=file]').setInputFiles({ name: 'review.csv', mimeType: 'text/csv', buffer: Buffer.from('InternalSensorId,DateTime,Value\n77,2026-09-05T10:00:00Z,12\n999999,2026-09-05T10:00:00Z,15') });
    await page.getByRole('button', { name: 'Upload CSV' }).click();
    await expect(page.getByText('Row 3: Unknown sensor 999999')).toBeVisible();
    await capture('csv-partial-result');

    await page.goto('/admin/events?tab=events');
    await page.getByLabel('Severity:').selectOption('info');
    await capture('event-filter');
    await page.getByRole('tab', { name: 'QC failures' }).click();
    await capture('event-qc-empty');
    await page.route('**/api/admin/events/qc-failures*', route => route.fulfill({ json: {
      total: 1, limit: 25, offset: 0,
      items: [{ measurement_qc_result_id: 41, qc_result_created_at: stamp, measurement_id: 9301, measurement_observed_at: stamp, measurement_value: 18.4, measurement_is_valid: true, device_id: 123, device_name: 'Central Library', sensor_id: 77, external_sensor_id: 'central-library-pm25-77', data_source_id: 1, data_source_name: 'OpenAQ', provider_code: 'openaq', parameter_code: 'pm25', parameter_name: 'PM2.5', unit_code: 'ug_m3', unit_symbol: 'µg/m³', check_code: 'max_value', evaluation_status: 'failed', failure_action: 'flag_for_review', reason_code: 'above_maximum', message: 'Value 18.4 exceeds maximum 10', details: { value: 18.4 }, params_snapshot: { max: 10 }, rule_source: 'sensor_override', policy_snapshot: { default_profile_version: '2026.1' }, policy_provenance: {} }],
    } }));
    await page.goto('/admin/events?tab=qc-failures');
    await page.locator('.qc-failure-provenance summary').click();
    await expect(page.getByText('above_maximum', { exact: true })).toBeVisible();
    await capture('event-qc-details');
    await page.goto('/admin/system-preferences');
    const topPreferencesSave = page.locator('.admin-page-actions').getByRole('button', { name: 'Save changes', exact: true });
    const bottomPreferencesSave = page.locator('.preferences-save-actions').getByRole('button', { name: 'Save changes', exact: true });
    await expect(page.getByRole('button', { name: 'Save changes', exact: true })).toHaveCount(2);
    await page.getByLabel('Geoapify API Key').fill('review-fixture-key');
    await topPreferencesSave.click();
    await expect.poll(() => state.preferences.geoapify_api_key).toBe('review-fixture-key');
    await page.getByLabel('Geoapify API Key').fill('');
    await bottomPreferencesSave.click();
    await expect.poll(() => state.preferences.geoapify_api_key).toBe('');
    await capture('preferences-saved');
  });
}

const routes = [
  ['home', '/admin'], ['devices', '/admin/devices'], ['device-editor', '/admin/devices/123/edit'],
  ['add-device', '/admin/devices/new'], ['manual-device', '/admin/devices/manual'], ['openaq-device', '/admin/devices/new/openaq'],
  ['sources', '/admin/sources'], ['openaq-source', '/admin/sources/1'], ['purpleair-source', '/admin/sources/2'], ['airgradient-source', '/admin/sources/3'],
  ['email', '/admin/email'], ['csv', '/admin/uploads/csv'], ['job-runs', '/admin/events'], ['events', '/admin/events?tab=events'], ['preferences', '/admin/system-preferences'],
  ['qc-reference', '/admin/qc'], ['users-reference', '/admin/users'],
];
const phase = process.env.ADMIN_REVIEW_PHASE ?? 'after';
test('Admin loading, error and unavailable states', async ({ page }) => {
  page.setDefaultTimeout(15000);
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAdministration(page);
  for (const [name, url, endpoint] of [
    ['devices', '/admin/devices', '**/api/admin/devices'],
    ['sources', '/admin/sources', '**/api/admin/external_apis'],
    ['source-detail', '/admin/sources/1', '**/api/admin/external_apis'],
    ['email', '/admin/email', '**/api/admin/email/configuration'],
    ['preferences', '/admin/system-preferences', '**/api/admin/system-preferences'],
    ['events', '/admin/events', '**/api/admin/jobs/runs*'],
  ]) {
    let release: () => void = () => {};
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route(endpoint, async route => {
      await pending;
      await route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } });
    });
    await page.goto(url);
    await expect(page.getByText(/Loading/i).first()).toBeVisible();
    await page.screenshot({ path: `../artifacts/admin-consistency/after/${name}-loading-en-390.png`, fullPage: true });
    release();
    await expect(page.getByRole('alert').first()).toBeVisible();
    await page.screenshot({ path: `../artifacts/admin-consistency/after/${name}-error-en-390.png`, fullPage: true });
    await page.unroute(endpoint);
  }
});

for (const [width, height, language] of [[1440, 1000, 'en'], [820, 1180, 'en'], [390, 844, 'en'], [390, 844, 'es']] as const) {
  test(`Admin rendered review ${width} ${language}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await mockAdministration(page, language);
    const directory = `../artifacts/admin-consistency/${phase}`;
    mkdirSync(directory, { recursive: true });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const [name, route] of routes) {
      await page.goto(route);
      await expect(page.locator('h1')).toBeVisible();
      await page.waitForTimeout(250);
      await page.screenshot({ path: `${directory}/${name}-${language}-${width}.png`, fullPage: true });
      if (phase !== 'before') expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${name} overflows`).toBeTruthy();
    }
    expect(errors).toEqual([]);
  });
}
