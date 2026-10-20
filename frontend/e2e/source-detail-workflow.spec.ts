import { test, expect } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import en from '../src/i18n/locales/en/dataSources.json' with { type: 'json' };
import es from '../src/i18n/locales/es/dataSources.json' with { type: 'json' };
import type { ExternalAPI } from '../src/api';

for (const language of ['en', 'es'] as const) for (const width of [1440, 390]) {
  for (const provider of ['OpenAQ', 'PurpleAir', 'AirGradient', 'Demo Data']) {
    test(`${provider} workflow ${language} ${width}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 844 });
      await mockAdministration(page, language);
      const copy = language === 'en' ? en : es;
      const demo = provider === 'Demo Data';
      const missing = provider === 'OpenAQ' || provider === 'PurpleAir';
      let source: ExternalAPI = {
        external_api_id: 1, name: provider, provider_code: demo ? 'demo' : provider.toLowerCase(),
        enabled: true, has_api_key: !missing && !demo, requires_credential: !demo,
        is_configured: !missing, is_runnable: !missing, runnable_reason: missing ? 'configuration_required' : 'ready',
        device_count: 4, base_url: 'https://provider.example.org', params: { import_authenticated_locations: false },
        latest_import: { job_run_id: 41, job_schedule_id: 1, task: `${provider.toLowerCase()}_import`, status: 'success', started_at: '2026-09-05T09:30:00Z', summary: { devices_processed: 4, measurements_inserted: 20 } },
      };
      await page.route('**/api/admin/external_apis', route => route.fulfill({ json: [source] }));
      await page.route('**/api/admin/external_apis/1', route => {
        if (route.request().method() === 'PUT') {
          const { api_key, ...patch } = route.request().postDataJSON();
          source = { ...source, ...patch };
          if (api_key) { source.has_api_key = true; source.is_configured = true; }
          source.is_runnable = source.enabled && source.is_configured;
          source.runnable_reason = !source.enabled ? 'disabled' : source.is_configured ? 'ready' : 'configuration_required';
        }
        return route.fulfill({ json: source });
      });
      const schedule = { job_schedule_id: 1, task: `${source.provider_code}_import`, cron_expr: '0 * * * *', timezone: 'UTC', enabled: true, allow_overlap: false };
      await page.route('**/api/admin/external_apis/1/schedules', route => route.fulfill({ json: [schedule] }));
      await page.route('**/api/admin/jobs/schedule-preview?*', route => route.fulfill({ json: { valid: true, next_runs: ['2026-09-23T00:00:00Z'] } }));
      await page.goto('/admin/sources/1');
      const readiness = page.locator('.source-readiness');
      await expect(readiness.getByRole('heading')).toHaveText(missing ? copy.workflow.needsConfiguration : copy.workflow.ready);
      await expect(readiness).toContainText(copy.workflow.schedule.on);
      const sections = ['.source-readiness', '#source-configuration', '#source-run-now', '#source-schedule', '#source-monitoring'];
      const positions = await Promise.all(sections.map(selector => page.locator(selector).evaluate(element => element.getBoundingClientRect().top)));
      expect(positions).toEqual([...positions].sort((a, b) => a - b));
      const shortcut = readiness.getByRole('link');
      expect((await shortcut.boundingBox())!.y).toBeLessThan(844);
      await shortcut.focus();
      await page.keyboard.press('Enter');
      await expect(page.locator(missing ? '#source-configuration' : demo ? '#source-schedule' : '#source-run-now')).toBeFocused();
      const run = page.locator('#source-run-now').getByRole('button', { name: copy.workflow.runNow, exact: true });
      if (missing || demo) await expect(run).toBeDisabled(); else await expect(run).toBeEnabled();
      if (missing) {
        await expect(readiness).toContainText(copy.workflow.missingCredential);
        await expect(run).toHaveAccessibleDescription(copy.workflow.missingCredential);
        await expect(page.locator('#source-schedule')).toContainText(copy.workflow.missingCredential);
      }
      if (demo) {
        await expect(page.locator('#source-configuration input[type=password]')).toHaveCount(0);
        await expect(readiness).toContainText(copy.workflow.demoAutomatic);
      }
      await expect(page.locator('#source-monitoring')).toContainText(copy.adminSourceForm.headings.lastImport);
      await expect(page.locator('#source-monitoring')).toContainText(copy.adminSourceForm.text.associatedDevices);
      await expect(page.locator('#source-monitoring').getByRole('link', { name: copy.adminSourceForm.actions.viewDevices })).toHaveAttribute('href', /network=/);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      for (const control of await page.locator('.source-detail-page .btn, .source-detail-page summary, .source-detail-page .text-input, .source-detail-page label:has(input[type=checkbox])').all()) {
        const box = await control.boundingBox();
        if (box) expect(box.height, await control.evaluate(element => element.outerHTML)).toBeGreaterThanOrEqual(44);
      }
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath('workflow.png'), fullPage: true });
      if (missing) {
        await page.getByLabel(copy.adminSourceForm.text.apiKey, { exact: true }).fill('fixture-credential');
        await page.locator('#source-configuration').getByRole('button', { name: /Save changes|Guardar cambios/ }).click();
        await expect(readiness.getByRole('heading')).toHaveText(copy.workflow.ready);
        await expect(run).toBeEnabled();
        const request = page.waitForRequest('**/api/admin/imports/run');
        await run.click();
        expect((await request).postDataJSON()).toEqual({ source: source.provider_code, force: false });
        await expect(page.locator('#source-run-now [role=status]')).toContainText('measurements_inserted');
      }
      if (provider === 'AirGradient') {
        const preference = page.getByLabel(copy.adminSourceForm.text.importAuthenticatedLocations);
        await expect(preference).not.toBeChecked();
        await preference.check();
        const save = page.locator('#source-configuration').getByRole('button', { name: /Save changes|Guardar cambios/ });
        await save.focus();
        await page.keyboard.press('Enter');
        await expect(page.getByText(copy.adminSourceForm.notifications.dataSourceUpdated, { exact: true })).toBeVisible();
        expect(source.params?.import_authenticated_locations).toBe(true);
        await expect(save).toBeFocused();
        await run.focus();
        await page.keyboard.press('Enter');
        await expect(page.locator('#source-run-now [role=status]')).toContainText('measurements_inserted');
        await expect(run).toBeFocused();
      }
    });
  }
}
