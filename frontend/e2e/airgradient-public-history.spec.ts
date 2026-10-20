import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { mockAdministration } from './fixtures/administration';
import en from '../src/i18n/locales/en/dataSources.json' with { type: 'json' };
import es from '../src/i18n/locales/es/dataSources.json' with { type: 'json' };
import enSetup from '../src/i18n/locales/en/setup.json' with { type: 'json' };
import esSetup from '../src/i18n/locales/es/setup.json' with { type: 'json' };

for (const language of ['en', 'es'] as const) for (const width of [1440, 390]) {
  test(`public history, source activation and setup ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const state = await mockAdministration(page, language);
    const copy = language === 'en' ? en : es;
    const setupCopy = language === 'en' ? enSetup : esSetup;
    const source = { ...state.sources[2], requires_credential: false, has_api_key: false,
      is_configured: true, is_runnable: true, runnable_reason: 'ready',
      params: { import_authenticated_locations: false } };
    state.sources[2] = source;
    Object.assign(state.device, { external_api_id: 3, external_api_name: 'AirGradient', network: 'AirGradient',
      name: 'Synthetic QA — São Paulo', friendly_name: null, external_id: '175911' });
    await page.route('**/api/admin/external_apis/3', route => route.fulfill({ json: source }));
    await page.route('**/api/admin/external_apis/3/schedules', route => route.fulfill({ json: [
      { job_schedule_id: 3, task: 'airgradient_import', cron_expr: '0 * * * *', timezone: 'UTC', enabled: true, allow_overlap: false },
    ] }));
    await page.route(/\/api\/(?:admin\/)?devices\/123\/sensors(?:\?.*)?$/, route => route.fulfill({ json: [
      { sensor_id: 77, parameter_code: 'pm25', parameter_name: 'PM2.5', aggregation_code: '1m',
        external_sensor_id: '175911:pm02', value: 7, unit_symbol: 'µg/m³', observed_at: '2026-10-10T00:00:00Z',
        expected_frequency_seconds: 60, measurement_duration_seconds: 12, is_valid: true },
      { sensor_id: 78, parameter_code: 'pm25', parameter_name: 'PM2.5', aggregation_code: '15m',
        external_sensor_id: 'map:14699912:pm25:15m', value: 5, unit_symbol: 'µg/m³', observed_at: '2026-10-10T00:00:00Z',
        expected_frequency_seconds: 900, measurement_duration_seconds: null, source_aggregation_duration_seconds: 900,
        measurement_timestamp_semantics: 'interval_start', is_valid: true,
        acquisition_metadata: { acquisition_method: 'map_processed_history', underlying_sample_count: null, underlying_coverage_seconds: null } },
    ] }));
    const directory = `../artifacts/airgradient-public-history/${language}-${width}`;
    mkdirSync(directory, { recursive: true });
    const capture = async (name: string) => {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      await page.screenshot({ path: `${directory}/${name}.png`, fullPage: true });
    };
    await page.goto('/admin/devices/123/edit');
    await expect(page.getByText(copy.airgradientHistoryStream)).toBeVisible();
    await expect(page.getByText('175911:pm02', { exact: false })).toBeVisible();
    await expect(page.getByText('map:14699912:pm25:15m', { exact: false })).toBeVisible();
    await capture('separate-streams');
    await page.goto('/admin/sources/3');
    await expect(page.getByText(copy.airgradientPublicHelp)).toBeVisible();
    await expect(page.locator('.source-readiness').getByRole('heading')).toHaveText(copy.workflow.ready);
    await expect(page.getByRole('checkbox', { name: copy.adminSourceForm.text.importAuthenticatedLocations })).not.toBeChecked();
    await expect(page.locator('#source-configuration input[type=password]')).toHaveCount(1);
    await expect(page.getByText(copy.airgradientOptionalCredential)).toBeVisible();
    await expect(page.getByText(copy.workflow.deploymentCredential)).toHaveCount(0);
    await capture('public-source-ready');

    await page.route('**/api/setup/status', route => route.fulfill({ json: {
      is_setup_required: true, has_users: true, default_language_code: language,
    } }));
    await page.route('**/api/setup/data-sources', route => route.fulfill({ json: { data_sources: [{ ...source, enabled: false }] } }));
    const writes: Array<Record<string, unknown>> = [];
    await page.route('**/api/setup/data-source', route => {
      writes.push(route.request().postDataJSON());
      return route.fulfill({ json: { success: true, is_configured: true } });
    });
    await page.goto('/');
    await expect(page.getByText(copy.airgradientPublicHelp)).toBeVisible();
    const enable = page.getByRole('checkbox', { name: copy.enableSource.replace('{{name}}', 'AirGradient') });
    // This established control waits for the save before updating checked state.
    await enable.click();
    await expect(enable).toBeChecked();
    await expect(page.getByRole('checkbox', { name: copy.adminSourceForm.text.importAuthenticatedLocations })).not.toBeChecked();
    await capture('public-setup');
    await page.getByRole('button', { name: setupCopy.setupWizard.actions.saveSourcesContinue }).click();
    await expect.poll(() => writes.length).toBe(2);
    expect(writes[1]).toMatchObject({ external_api_id: 3, enabled: true, api_key: null, import_authenticated_locations: false });
    expect(writes[0]).toMatchObject({ external_api_id: 3, enabled: true, import_authenticated_locations: false });
    await page.getByRole('button', { name: setupCopy.setupWizard.actions.skipNow2 }).click();
    await expect(page.getByText(setupCopy.setupWizard.text.dataSourceConfiguredAndEnabled)).toBeVisible();
    await expect(page.getByText(setupCopy.setupWizard.text.dataSourceNotConfiguredCanDone)).toHaveCount(0);
    await expect(page.locator('.setup-step')).toHaveCSS('opacity', '1');
    await capture('public-setup-complete');
  });
}
