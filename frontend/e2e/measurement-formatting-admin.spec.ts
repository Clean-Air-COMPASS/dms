import { test, expect } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import en from '../src/i18n/locales/en/devices.json' with { type: 'json' };
import es from '../src/i18n/locales/es/devices.json' with { type: 'json' };
const before = process.env.FORMATTING_BASELINE === '1';
for (const lang of ['en', 'es'] as const) for (const width of [1440, 390]) {
  test(`related measurement displays ${lang} ${width}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    const state = await mockAdministration(page, lang);
    state.device.name = 'Synthetic formatting station'; state.device.friendly_name = 'Synthetic formatting station';
    const copy = lang === 'en' ? en : es;
    const value = 0.0049;
    const sensor = { sensor_id: 77, parameter_code: 'pm25', parameter_name: 'PM2.5', aggregation_code: '1h', external_sensor_id: 'synthetic-77', value, display_precision: 4, unit_symbol: 'µg/m³', observed_at: '2026-08-01T00:00:00Z', is_valid: true };
    await page.route('**/api/devices/123/sensors**', route => route.fulfill({ json: [sensor] }));
    await page.goto('/admin/devices/123/edit');
    await expect(page.locator('.sensor-value')).toContainText(before || lang === 'en' ? '0.0049' : '0,0049');
    await page.screenshot({ path: info.outputPath('editor.png'), fullPage: true });
    await page.route('**/api/admin/devices/purpleair/lookup', route => route.fulfill({ json: { device: state.device, sensors: [{ external_sensor_id: '77', parameter_code: 'pm25', latest_value: value, unit_code: 'ug_m3' }] } }));
    await page.goto('/admin/devices/new');
    await page.locator('.source-option-card').filter({ hasText: 'PurpleAir' }).click();
    await page.getByPlaceholder('e.g., 12345').fill('77');
    await page.getByRole('button', { name: copy.adminDeviceNew.actions.lookup, exact: true }).click();
    await page.getByRole('button', { name: copy.adminDeviceNew.actions.proceedLookup, exact: true }).click();
    await expect(page.locator('td').getByText(before ? '0.00' : lang === 'en' ? '0.0049' : '0,0049', { exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath('purpleair.png'), fullPage: true });
    await page.route('**/api/admin/devices/openaq/lookup/sensor', route => route.fulfill({ json: { locations: [{ device: { ...state.device, external_id: '77' }, sensors: [{ sensor_id: 77, parameter_code: 'pm25', parameter_display: 'PM2.5', unit: 'µg/m³', exists: false }], metadata: { latest_value: value, latest_datetime_utc: '2026-08-01T00:00:00Z' }, already_exists: false }] } }));
    await page.goto('/admin/devices/new/openaq');
    await page.getByRole('button', { name: copy.adminDeviceNewOpenAQ.actions.sensorId, exact: true }).click();
    await page.locator('input[type="text"]').last().fill('77');
    await page.getByRole('button', { name: copy.adminDeviceNewOpenAQ.actions.lookup, exact: true }).click();
    await page.getByRole('button', { name: copy.adminDeviceNewOpenAQ.actions.proceed, exact: true }).click();
    await expect(page.locator('.cell-primary').getByText((before ? '0.00' : lang === 'en' ? '0.0049' : '0,0049') + ' µg/m³', { exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath('openaq.png'), fullPage: true });
  });
}
