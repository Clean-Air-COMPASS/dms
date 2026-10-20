import { test, expect } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import en from '../src/i18n/locales/en/devices.json' with { type: 'json' };
import es from '../src/i18n/locales/es/devices.json' with { type: 'json' };
import enCommon from '../src/i18n/locales/en/common.json' with { type: 'json' };
import esCommon from '../src/i18n/locales/es/common.json' with { type: 'json' };

for (const language of ['en', 'es'] as const) for (const width of [390, 1440]) {
  for (const provider of ['Local', 'OpenAQ', 'PurpleAir', 'AirGradient', 'Demo Data']) {
    test(`device ownership workflow ${provider} ${language} ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      const state = await mockAdministration(page, language);
      const external = provider !== 'Local';
      Object.assign(state.device, { external_api_name: provider, network: provider, is_external: external, external_id: external ? 'provider-location-123456789' : '', name: `${provider} monitoring station`, friendly_name: provider === 'Demo Data' ? 'Demo Data Library' : 'Central Library' });
      if (!external) {
        state.sources.push({ ...state.sources[0], external_api_id: 4, name: 'Local', provider_code: 'local' });
        state.device.external_api_id = 4;
      }
      const copy = (language === 'en' ? en : es).adminDeviceEditor;
      const common = language === 'en' ? enCommon : esCommon;
      await page.goto('/admin/devices/123/edit');
      const settings = page.getByRole('form', { name: copy.headings.localSettings });
      const sensors = page.locator('#device-sensors');
      const metadata = page.locator('.meta-card');
      const save = settings.getByRole('button', { name: common.actions.saveChanges, exact: true });
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(state.device.friendly_name);
      await expect(page.locator('.device-overview')).toContainText(external ? copy.workflow.providerDevice : copy.workflow.manualDevice);
      await expect(settings).toBeVisible();
      await expect(sensors.getByRole('link', { name: copy.actions.manageQc })).toHaveAttribute('href', '/admin/qc/sensors/77');
      const order = await page.locator('.device-editor-layout').evaluate(element => [...element.children].map(child => child.id || child.className));
      expect(order[0]).toBe('device-settings');
      expect(order[1]).toBe('device-sensors');
      expect(order.at(-1)).toContain('meta-card');
      if (external) {
        const reference = page.getByRole('region', { name: copy.workflow.providerDetails });
        await expect(reference.locator('input, select, textarea')).toHaveCount(0);
        await expect(reference).toContainText(copy.workflow.managedBy.replace('{{provider}}', provider));
        await expect(reference).toContainText('America/Los_Angeles');
        await expect(sensors.getByRole('button', { name: copy.actions.addSensor })).toHaveCount(0);
        await expect(sensors).toContainText(copy.workflow.providerSensors.replace('{{provider}}', provider));
        expect((await save.boundingBox())!.y).toBeLessThan(1000);
      } else {
        await expect(settings.getByLabel(copy.fields.latitude, { exact: true })).toBeEditable();
        await expect(settings.getByLabel(copy.fields.timezone, { exact: true })).toBeEnabled();
        await expect(sensors.getByRole('button', { name: copy.actions.addSensor })).toBeVisible();
      }
      await expect(sensors).toContainText('12.5');
      await expect(sensors.locator('time')).toHaveAttribute('datetime', '2026-09-05T09:30:00Z');
      await metadata.locator('summary').click();
      await expect(metadata).toContainText('123');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      for (const control of await page.locator('.device-editor-page :is(button, input, select, summary), .device-overview a, .sensor-item-qc-link').all()) {
        const box = await control.boundingBox();
        if (box) expect(box.height).toBeGreaterThanOrEqual(44);
      }
      await page.screenshot({ path: `../artifacts/device-detail/${provider}-${language}-${width}.png`, fullPage: true });
      const friendly = settings.getByLabel(copy.fields.friendlyName);
      await friendly.fill('Saved library name');
      await expect(settings).toContainText(copy.text.unsavedChanges);
      await friendly.focus();
      await page.keyboard.press('Tab');
      if (external) await expect(settings.getByLabel(copy.fields.measurementUpdatesPolicy)).toBeFocused();
      await page.keyboard.press('Control+s');
      await expect(settings.getByRole('status')).toHaveText(copy.messages.deviceSavedSuccessfully);
      await expect(page.locator('.device-save-feedback')).toBeFocused();
      await expect(friendly).toHaveValue('Saved library name');
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Saved library name');
      await expect.poll(() => state.writes.filter(path => path === '/admin/devices/123').length).toBe(1);
      await expect(sensors.getByRole('link', { name: copy.actions.manageQc })).toBeVisible();
    });
  }
}

test('device save failure preserves input and keyboard focus; sensor empty/error states remain visible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAdministration(page);
  let failSensors = false;
  await page.route('**/api/devices/123/sensors', route => failSensors ? route.fulfill({ status: 500, json: { detail: 'Fixture failure' } }) : route.fulfill({ json: [] }));
  await page.route('**/api/admin/devices/123', route => route.request().method() === 'PUT' ? route.fulfill({ status: 422, json: { detail: 'Fixture failure' } }) : route.fallback());
  await page.goto('/admin/devices/123/edit');
  await expect(page.getByText(en.adminDeviceEditor.text.noSensorsFoundDevice)).toBeVisible();
  await page.getByLabel('Friendly Name').fill('Keep my change');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.locator('#device-settings').getByRole('alert')).toBeVisible();
  await expect(page.getByLabel('Friendly Name')).toHaveValue('Keep my change');
  await expect(page.locator('.device-save-feedback')).toBeFocused();
  await page.screenshot({ path: '../artifacts/device-detail/save-error-en-390.png', fullPage: true });
  failSensors = true;
  page.on('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(page.locator('#device-sensors .error-banner')).toBeVisible();
  await page.screenshot({ path: '../artifacts/device-detail/sensors-error-en-390.png', fullPage: true });
});

test('long provider references and unavailable location wrap at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await mockAdministration(page, 'es');
  state.device.name = 'Estación de monitoreo comunitario con una identificación extensa para verificar la lectura en pantallas pequeñas';
  state.device.friendly_name = state.device.name;
  state.device.external_id = 'provider-location-'.repeat(7);
  state.device.timezone = '';
  await page.goto('/admin/devices/123/edit');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(state.device.name);
  await expect(page.locator('.device-provider-details')).toContainText(state.device.external_id);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../artifacts/device-detail/long-reference-es-390.png', fullPage: true });
});

test('loading and failed device requests cannot expose or save an empty editor', async ({ page }) => {
  await mockAdministration(page);
  const deviceWrites: string[] = [];
  page.on('request', request => {
    if (request.method() === 'PUT' && new URL(request.url()).pathname === '/api/admin/devices/123') deviceWrites.push(request.url());
  });
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/admin/devices/123', async route => {
    await pending;
    return route.fulfill({ status: 500, json: { detail: 'Fixture failure' } });
  });
  await page.goto('/admin/devices/123/edit');
  await expect(page.getByText(en.adminDeviceEditor.text.loadingDevice)).toBeVisible();
  await expect(page.locator('#device-settings')).toHaveCount(0);
  await page.keyboard.press('Control+s');
  expect(deviceWrites).toEqual([]);
  await page.screenshot({ path: '../artifacts/device-detail/device-loading.png', fullPage: true });
  release();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.locator('#device-settings')).toHaveCount(0);
  await page.keyboard.press('Control+s');
  expect(deviceWrites).toEqual([]);
  await page.screenshot({ path: '../artifacts/device-detail/device-load-error.png', fullPage: true });
});
