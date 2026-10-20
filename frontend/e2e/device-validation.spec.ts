import { test, expect } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import en from '../src/i18n/locales/en/devices.json' with { type: 'json' };
import es from '../src/i18n/locales/es/devices.json' with { type: 'json' };
import enCommon from '../src/i18n/locales/en/common.json' with { type: 'json' };
import esCommon from '../src/i18n/locales/es/common.json' with { type: 'json' };

for (const language of ['en', 'es'] as const) for (const width of [1440, 390]) {
  test(`add device conditional source and coordinate validation ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const state = await mockAdministration(page, language);
    const resource = language === 'en' ? en : es;
    const copy = resource.adminDeviceEditor;
    const common = language === 'en' ? enCommon : esCommon;
    const payloads: Record<string, unknown>[] = [];
    await page.route('**/api/admin/devices', route => {
      if (route.request().method() === 'POST') {
        const payload = route.request().postDataJSON();
        payloads.push(payload);
        // Match the API's creation semantics instead of retaining the fixture's provider ID.
        Object.assign(state.device, {
          external_id: payload.external_id || '',
          manual_data_source_name: payload.network || null,
          network: payload.network || state.sources.find(source => source.external_api_id === payload.external_api_id)?.name || state.device.external_api_name,
        });
      }
      return route.fallback();
    });
    const capture = async (name: string) => {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      await page.screenshot({ path: `../artifacts/device-qa/${name}-${language}-${width}.png`, fullPage: true });
    };

    await page.goto('/admin/devices/new');
    await capture('add-choice');
    await page.getByRole('button', { name: new RegExp(resource.adminDeviceNew.text.manualEntry) }).click();
    const source = page.locator('#external_api_id');
    const other = page.locator('#custom_external_api_name');
    const latitude = page.locator('#latitude');
    const longitude = page.locator('#longitude');
    const add = page.getByRole('button', { name: copy.clarity.addDevice, exact: true });
    await expect(other).toHaveCount(0);
    await expect(page.locator('#name')).toHaveAttribute('required', '');
    await page.locator('#name').fill('QA manual station');
    await source.selectOption('__other__');
    await expect(other).toHaveAttribute('required', '');
    await expect(other).toHaveAccessibleDescription(copy.clarity.otherSourceHelp);
    await add.click();
    await expect(other).toBeFocused();
    await expect(other).toHaveAttribute('aria-invalid', 'true');
    await expect(other).toHaveAccessibleDescription(new RegExp(copy.validation.otherSourceRequired));
    expect(payloads).toHaveLength(0);
    await capture('other-required');

    await other.fill('Neighborhood Lab');
    await latitude.fill('2000');
    await longitude.fill('3000');
    await longitude.press('Tab');
    await expect(latitude).toHaveAccessibleDescription(new RegExp(copy.validation.latitudeRange));
    await expect(longitude).toHaveAccessibleDescription(new RegExp(copy.validation.longitudeRange));
    await add.click();
    await expect(latitude).toBeFocused();
    expect(payloads).toHaveLength(0);
    await capture('coordinates-invalid');
    await latitude.fill('-35.1234');
    await longitude.fill('-120.1234');
    await page.keyboard.press('Control+s');
    await expect(page).toHaveURL(/123\/edit/);
    await expect(page.getByText(copy.messages.deviceSavedSuccessfully, { exact: true })).toBeVisible();
    expect(payloads[0]).toMatchObject({ network: 'Neighborhood Lab', latitude: -35.1234, longitude: -120.1234 });
    expect(payloads[0]).not.toHaveProperty('external_api_id');
    await expect(page.locator('.device-overview')).toContainText(copy.workflow.manualDevice);
    await capture('manual-saved');

    await page.goto('/admin/devices/manual');
    await page.locator('#name').fill('QA selected source station');
    await source.selectOption('1');
    await expect(other).toHaveCount(0);
    await add.click();
    await expect(page).toHaveURL(/123\/edit/);
    expect(payloads[1]).toMatchObject({ external_api_id: 1, latitude: null, longitude: null });
    expect(payloads[1]).not.toHaveProperty('network');
    expect(state.writes.filter(path => path === '/admin/devices')).toHaveLength(2);

    // Cancel still works by keyboard and retains the existing discard confirmation.
    await page.locator('#friendly_name').fill('Discard this edit');
    page.once('dialog', dialog => dialog.accept());
    await page.keyboard.press('Escape');
    await expect(page).toHaveURL(/\/admin\/devices$/);
    await expect(page.locator('tbody')).toContainText(copy.workflow.manualDevice);
    await capture('device-list');
    await expect(page.getByRole('button', { name: common.actions.reset })).toBeVisible();
  });

  test(`manual location edits and sensor clarity ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const state = await mockAdministration(page, language);
    Object.assign(state.device, { is_external: false, external_id: '', external_api_name: 'Local', network: 'Local' });
    const copy = (language === 'en' ? en : es).adminDeviceEditor;
    const common = language === 'en' ? enCommon : esCommon;
    const payloads: Record<string, unknown>[] = [];
    await page.route('**/api/admin/devices/123', route => {
      if (route.request().method() === 'PUT') payloads.push(route.request().postDataJSON());
      return route.fallback();
    });
    await page.route('**/api/admin/devices/123/sensors', route => route.request().method() === 'POST'
      ? route.fulfill({ json: { sensor_id: 88, device_id: 123, ...route.request().postDataJSON() } }) : route.fallback());
    await page.goto('/admin/devices/123/edit');
    const latitude = page.locator('#latitude');
    const longitude = page.locator('#longitude');
    const save = page.getByRole('button', { name: common.actions.saveChanges, exact: true });
    await expect(page.locator('.device-overview')).toContainText(copy.workflow.manualDevice);
    await expect(page.locator('#external_id')).toHaveAttribute('readonly', '');
    for (const [lat, lon] of [[-90, -180], [90, 180], [-35.1234, -120.1234]]) {
      await latitude.fill(String(lat));
      await longitude.fill(String(lon));
      await save.click();
      await expect(page.locator('.device-save-feedback')).toContainText(copy.messages.deviceSavedSuccessfully);
      expect(payloads.at(-1)).toMatchObject({ latitude: lat, longitude: lon });
    }
    for (const [lat, lon, invalidField, message] of [
      ['-90.001', '0', 'latitude', copy.validation.latitudeRange],
      ['90.001', '0', 'latitude', copy.validation.latitudeRange],
      ['0', '-180.001', 'longitude', copy.validation.longitudeRange],
      ['0', '180.001', 'longitude', copy.validation.longitudeRange],
      ['0', '360', 'longitude', copy.validation.longitudeRange],
      ['invalid', '0', 'latitude', copy.validation.coordinateNumber],
      ['0', '', 'longitude', copy.validation.coordinatePair],
    ]) {
      await latitude.fill(lat);
      await longitude.fill(lon);
      await save.click();
      await expect(page.locator(`#${invalidField}`)).toBeFocused();
      await expect(page.locator(`#${invalidField}`)).toHaveAccessibleDescription(new RegExp(message));
      expect(payloads).toHaveLength(3);
    }
    await latitude.fill('');
    await longitude.fill('');
    await save.click();
    await expect(page.locator('.device-save-feedback')).toContainText(copy.messages.deviceSavedSuccessfully);
    expect(payloads.at(-1)).toMatchObject({ latitude: null, longitude: null });
    await page.reload();
    await expect(latitude).toHaveValue('');
    await expect(longitude).toHaveValue('');

    await expect(page.locator('#device-sensors')).toContainText(copy.workflow.sensorHelp);
    await expect(page.locator('.device-add-sensor')).toContainText(copy.workflow.sensorQcInheritance);
    await page.locator('#new_sensor_parameter_code').selectOption('pm25');
    await page.locator('#new_sensor_aggregation_code').selectOption('1h');
    await page.getByRole('button', { name: copy.actions.addSensor, exact: true }).click();
    await expect(page.locator('#device-sensors').getByRole('status')).toHaveText(copy.messages.sensorAdded.replace('{{id}}', '88'));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: `../artifacts/device-qa/sensor-added-${language}-${width}.png`, fullPage: true });
  });
}

for (const colorScheme of ['light', 'dark'] as const) for (const touch of [false, true]) {
  test(`Local Settings hover and focus ${colorScheme} ${touch ? 'touch' : 'desktop'}`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({ baseURL, colorScheme, hasTouch: touch, isMobile: touch, viewport: { width: touch ? 390 : 1440, height: 1000 } });
    const page = await context.newPage();
    await mockAdministration(page);
    await page.goto('/admin/devices/123/edit');
    const card = page.locator('.form-section');
    const appearance = () => card.evaluate(element => {
      const style = getComputedStyle(element);
      return { background: style.backgroundColor, color: style.color, border: style.borderColor, transform: style.transform };
    });
    const before = await appearance();
    await card.hover({ position: { x: 10, y: 10 } });
    expect(await appearance()).toEqual(before);
    const policy = page.locator('#allow_updates');
    await policy.hover();
    expect(await appearance()).toEqual(before);
    await page.locator('#friendly_name').focus();
    await page.keyboard.press('Tab');
    await expect(policy).toBeFocused();
    expect(await policy.evaluate(element => getComputedStyle(element).outlineStyle)).toBe('solid');
    await policy.press('ArrowDown');
    await expect(policy).toHaveValue('allow');
    const save = page.getByRole('button', { name: 'Save changes', exact: true });
    await save.hover();
    expect(await save.evaluate(element => getComputedStyle(element).color)).toBe('rgb(255, 255, 255)');
    await save.click();
    await expect(page.locator('.device-save-feedback')).toContainText(en.adminDeviceEditor.messages.deviceSavedSuccessfully);
    await page.screenshot({ path: `../artifacts/device-qa/local-settings-${colorScheme}-${touch}.png`, fullPage: true });
    await context.close();
  });
}
