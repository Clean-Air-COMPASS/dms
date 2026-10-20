import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { mockAdministration } from './fixtures/administration';
import enCommon from '../src/i18n/locales/en/common.json' with { type: 'json' };
import esCommon from '../src/i18n/locales/es/common.json' with { type: 'json' };
import enSources from '../src/i18n/locales/en/dataSources.json' with { type: 'json' };
import esSources from '../src/i18n/locales/es/dataSources.json' with { type: 'json' };
import enDevices from '../src/i18n/locales/en/devices.json' with { type: 'json' };
import esDevices from '../src/i18n/locales/es/devices.json' with { type: 'json' };

for (const language of ['en', 'es'] as const) for (const width of [1440, 390]) {
  test(`administrative workflow clarity ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const state = await mockAdministration(page, language);
    const common = language === 'en' ? enCommon : esCommon;
    const sources = language === 'en' ? enSources : esSources;
    const devices = (language === 'en' ? enDevices : esDevices).adminDeviceEditor;
    const schedule = { job_schedule_id: 1, task: 'openaq_import', cron_expr: '0 * * * *', timezone: 'UTC', enabled: true, allow_overlap: false };
    let releaseSave: (() => void) | undefined;
    let failSave = false;
    let saveCount = 0;
    let holdSave = false;
    await page.route('**/api/admin/external_apis/1/schedules', route => route.fulfill({ json: [schedule] }));
    await page.route('**/api/admin/jobs/schedule-preview?*', route => {
      const cron = new URL(route.request().url()).searchParams.get('cron_expr');
      const nextRuns = cron === '*/15 * * * *'
        ? ['2026-09-08T08:00:00Z', '2026-09-08T08:15:00Z', '2026-09-08T08:30:00Z']
        : ['2026-09-08T08:00:00Z', '2026-09-08T09:00:00Z', '2026-09-08T10:00:00Z'];
      return route.fulfill({ json: { valid: cron !== 'not cron', next_runs: cron === 'not cron' ? [] : nextRuns } });
    });
    await page.route(/\/api\/admin\/(jobs\/schedules\/1|external_apis\/1|devices(?:\/123)?)$/, async route => {
      if (route.request().method() === 'GET') return route.fallback();
      saveCount++;
      if (holdSave) await new Promise<void>(resolve => { releaseSave = resolve; });
      if (failSave) return route.fulfill({ status: 422, json: { detail: 'Fixture validation failure' } });
      return route.fallback();
    });
    const dir = `../artifacts/admin-workflow-clarity/${language}-${width}`;
    mkdirSync(dir, { recursive: true });
    const capture = async (name: string) => {
      await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    };
    let saveScope = page.locator('#source-configuration');
    const savingButton = () => saveScope.getByRole('button', { name: common.actions.savingChanges, exact: true });
    const saveButton = () => saveScope.getByRole('button', { name: common.actions.saveChanges, exact: true });

    await page.goto('/admin/sources/1');
    const description = page.getByLabel(sources.adminSourceForm.text.description, { exact: true });
    await description.fill('Fixture configuration retained after validation failure');
    holdSave = true;
    failSave = true;
    await saveButton().click();
    await expect(savingButton()).toBeDisabled();
    await expect(description).toBeDisabled();
    await capture('source-saving');
    releaseSave!();
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(description).toHaveValue('Fixture configuration retained after validation failure');
    await capture('source-error');
    holdSave = false;
    failSave = false;
    await saveButton().click();
    await expect(page.getByText(sources.adminSourceForm.notifications.dataSourceUpdated, { exact: true })).toBeVisible();
    await capture('source-saved');

    saveScope = page.locator('#source-schedule');
    // Enable a configured schedule while its source is disabled, without writing live data.
    state.sources[0].enabled = false;
    state.sources[0].is_runnable = false;
    state.sources[0].runnable_reason = 'disabled';
    await page.goto('/admin/sources/1');

    await expect(page.getByText(sources.schedulesTab.clarity.blockedDisabled, { exact: false })).toBeVisible();
    await expect(page.getByText(sources.schedulesTab.clarity.hourly.replace('{{minute}}', '00'), { exact: true })).toBeVisible();
    await capture('schedule-blocked');
    await page.getByText(sources.schedulesTab.clarity.advanced, { exact: true }).click();
    const cron = page.getByLabel(sources.schedulesTab.clarity.cronLabel, { exact: true });
    await cron.fill('not cron');
    await expect(cron).toHaveAttribute('aria-invalid', 'true');
    await expect(saveButton()).toBeDisabled();
    await capture('schedule-invalid');
    await cron.fill('*/15 * * * *');
    await expect(saveButton()).toBeEnabled();
    holdSave = true;
    await saveButton().click();
    await expect(savingButton()).toBeDisabled();
    await capture('schedule-saving');
    releaseSave!();
    holdSave = false;
    await expect(page.getByText(sources.schedulesTab.notifications.scheduleUpdated, { exact: true })).toBeVisible();
    await capture('schedule-saved');

    state.sources[0].enabled = true;
    state.sources[0].is_runnable = true;
    state.sources[0].runnable_reason = 'ready';
    await page.goto('/admin/sources/1');

    await expect(page.getByText(sources.schedulesTab.clarity.ready, { exact: true })).toBeVisible();
    await expect(page.getByText(sources.schedulesTab.clarity.hourly.replace('{{minute}}', '00'), { exact: true })).toBeVisible();
    await capture('schedule-ready');

    saveScope = page.locator('body');
    await page.goto('/admin/devices/manual');
    const name = page.getByRole('textbox', { name: /^Name|^Nombre/ }).first();
    await expect(name).toHaveAttribute('required', '');
    await expect(page.getByLabel(devices.fields.dataSource, { exact: true })).not.toHaveAttribute('required');
    const timezone = page.getByRole('combobox', { name: devices.fields.timezone, exact: true });
    await expect(timezone).toHaveValue('');
    await timezone.selectOption('Asia/Manila');
    await expect(page.getByText(devices.clarity.inheritUnavailable, { exact: true })).toBeVisible();
    await timezone.focus();
    await page.keyboard.press('Tab');
    await expect(page.getByLabel(devices.fields.measurementUpdatesPolicy)).toBeFocused();
    const policy = page.getByLabel(devices.fields.measurementUpdatesPolicy);
    const policyBounds = await policy.boundingBox();
    const actionsBounds = await page.locator('.device-form .admin-form-save-actions').boundingBox();
    expect(actionsBounds!.y).toBeGreaterThan(policyBounds!.y + policyBounds!.height);
    await capture('device-form');
    await name.fill('Fixture manual device');
    failSave = true;
    holdSave = true;
    const beforeSave = saveCount;
    await page.getByRole('button', { name: devices.clarity.addDevice, exact: true }).click();
    await expect(savingButton()).toBeDisabled();
    await page.keyboard.press('Control+s');
    expect(saveCount).toBe(beforeSave + 1);
    await capture('device-saving');
    releaseSave!();
    holdSave = false;
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(name).toHaveValue('Fixture manual device');
    await expect(timezone).toHaveValue('Asia/Manila');
    await capture('device-error');
    failSave = false;
    await page.getByRole('button', { name: devices.clarity.addDevice, exact: true }).click();
    await expect(page).toHaveURL(/123\/edit/);
    await expect(page.getByText(devices.messages.deviceSavedSuccessfully, { exact: true })).toBeVisible();
    await capture('device-saved');
  });
}
