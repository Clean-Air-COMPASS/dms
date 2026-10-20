import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { mockAdministration } from './fixtures/administration';
import en from '../src/i18n/locales/en/devices.json' with { type: 'json' };
import es from '../src/i18n/locales/es/devices.json' with { type: 'json' };

for (const language of ['en', 'es'] as const) for (const width of [1440, 390]) {
  test(`AirGradient selection, states and navigation ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const state = await mockAdministration(page, language);
    Object.assign(state.device, {
      name: 'Demo fixture — Community library roof', friendly_name: 'Demo fixture — Library roof',
      external_id: '70001', external_api_id: 3, external_api_name: 'AirGradient', network: 'AirGradient',
      latitude: 34.0522, longitude: -118.2437,
    });
    const text = (language === 'en' ? en : es).airgradient;
    const deviceText = language === 'en' ? en : es;
    const dir = `../artifacts/airgradient-add/${language}-${width}`;
    mkdirSync(dir, { recursive: true });
    const capture = async (name: string) => {
      await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      expect(await page.locator('body').innerText()).not.toContain('provider-secret');
    };
    let mode = 'loading';
    let saveMode = 'success';
    await page.route(/\/api\/(?:admin\/)?devices\/123\/sensors(?:\?.*)?$/, route => route.fulfill({
      json: saveMode === 'noReadings' ? [] : [{
        sensor_id: 77, parameter_code: 'pm25', parameter_name: 'PM2.5', aggregation_code: '1m',
        external_sensor_id: '70001:pm02', value: 12.5, unit_symbol: 'µg/m³',
        observed_at: '2026-09-05T09:30:00Z', is_valid: true,
      }],
    }));
    let release: (() => void) | undefined;
    const location = { location_id: '70001', name: 'Demo fixture — Community library roof and neighborhood monitoring location', latitude: 34.0522, longitude: -118.2437, timezone: 'America/Los_Angeles', existing_device_id: null };
    const calls: string[] = [];
    await page.route('**/api/admin/devices/airgradient/locations', async route => {
      const request = route.request();
      calls.push(`${request.url()} ${request.postData() || ''}`);
      if (request.method() === 'POST') {
        expect(request.postDataJSON()).toEqual({ location_id: '70001' });
        if (saveMode === 'error') return route.fulfill({ status: 500, json: { detail: { error_code: 'operation_failed' } } });
        return route.fulfill({ json: { device_id: 123, already_exists: saveMode === 'duplicate', measurements_imported: saveMode === 'noReadings' ? 0 : 4 } });
      }
      if (mode === 'loading') await new Promise<void>(resolve => { release = resolve; });
      if (mode === 'error') return route.fulfill({ status: 422, json: { detail: { error_code: 'authentication_failed', message: 'provider-secret' } } });
      return route.fulfill({ json: { locations: mode === 'empty' ? [] : [{ ...location, existing_device_id: mode === 'duplicate' ? 123 : null }], automatic_imports_enabled: false } });
    });

    await page.goto('/admin/devices');
    await page.getByRole('button', { name: deviceText.adminDevicesList.actions.newDevice, exact: true }).click();
    await expect(page.getByRole('link', { name: text.configure })).toBeVisible();
    await capture('unconfigured');
    state.sources[2].has_api_key = true;
    state.sources[2].is_configured = true;
    await page.reload();
    await page.getByRole('button', { name: `AirGradient ${text.choose}` }).click();
    await expect(page.getByRole('status')).toHaveText(text.loading);
    await capture('loading');
    mode = 'list';
    release!();
    await page.getByRole('radio').check();
    await expect(page.getByText(text.automaticOff)).toBeVisible();
    await capture('preview');
    saveMode = 'error';
    await page.getByRole('button', { name: text.add, exact: true }).click();
    await expect(page.getByRole('alert')).toContainText(text.errors.operation_failed);
    await capture('creation-error');
    saveMode = 'duplicate';
    await page.getByRole('button', { name: text.add, exact: true }).click();
    await expect(page.getByText(text.duplicate)).toBeVisible();
    await capture('duplicate-race');
    await page.getByRole('link', { name: text.viewDevice }).click();
    await expect(page).toHaveURL(/\/admin\/devices\/123\/edit$/);

    for (const nextMode of ['empty', 'error', 'duplicate']) {
      mode = nextMode;
      await page.goto('/admin/devices/new/airgradient');
      if (mode === 'empty') await expect(page.getByText(text.empty)).toBeVisible();
      if (mode === 'error') await expect(page.getByRole('alert')).toContainText(text.errors.authentication_failed);
      if (mode === 'duplicate') {
        await page.getByRole('radio').check();
        await expect(page.getByText(text.duplicate)).toBeVisible();
      }
      await capture(mode);
    }
    mode = 'list';
    saveMode = 'success';
    await page.goto('/admin/devices/new/airgradient');
    await page.getByRole('radio').check();
    await page.getByRole('button', { name: text.add, exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/devices\/123\/edit$/);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByText('AirGradient', { exact: true }).first()).toBeVisible();
    await capture('success');
    saveMode = 'noReadings';
    Object.assign(state.device, { status: 'unknown', last_seen_at: null });
    await page.goto('/admin/devices/new/airgradient');
    await page.getByRole('radio').check();
    await page.getByRole('button', { name: text.add, exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/devices\/123\/edit$/);
    await expect(page.getByText(text.noReadings)).toBeVisible();
    await capture('no-readings');
    expect(calls.join('\n')).not.toMatch(/api_key|token|provider-secret/);
  });
}
