import { test, expect } from '@playwright/test';
import { mockAdministration, stamp } from './fixtures/administration';

test.use({ timezoneId: 'America/Los_Angeles' });

for (const width of [1440, 390]) {
  for (const language of ['en', 'es']) {
    test(`explicit display timezones ${language} ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      const state = await mockAdministration(page, language);
      // Synthetic fixtures only: no system settings or meaningful measurements are written.
      Object.assign(state.sources[0], { latest_import: { started_at: stamp, status: 'success' } });
      const capture = async (name: string) => {
        await page.screenshot({ path: `../artifacts/display-timezone/${name}-${language}-${width}.png`, fullPage: true });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
      };
      await page.route('**/api/sensors/10/history*', route => route.fulfill({ json: {
        sensor_id: 10, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³',
        device_name: 'Synthetic timezone test station', device_timezone: 'America/New_York', external_sensor_id: 'TEST-10',
        data: [
          { timestamp: '2026-03-08T06:30:00Z', value: 12, is_valid: true },
          { timestamp: '2026-03-08T07:30:00Z', value: 15, is_valid: true },
          { timestamp: '2026-03-08T08:30:00Z', value: 14, is_valid: true },
        ],
      } }));
      const query = new URLSearchParams({ series: 'measurement|10|pm25|1h', start: '2026-03-08T06:30:00Z', end: '2026-03-08T08:30:00Z', timezone: 'utc' });
      await page.goto(`/analytics?${query}`);
      const inputs = page.locator('main input[type="datetime-local"]');
      await expect(inputs.first()).toHaveValue('2026-03-08T06:30');
      await expect(page.locator('tbody')).toContainText('UTC');
      await expect(page.locator('canvas')).toBeVisible();
      await capture('analytics-utc');
      await page.locator('canvas').scrollIntoViewIfNeeded();
      const canvas = await page.locator('canvas').boundingBox();
      await page.mouse.move(canvas!.x + canvas!.width / 2, canvas!.y + canvas!.height / 2);
      await page.waitForTimeout(400); // Let the canvas tooltip fade-in finish for visual review.
      await capture('analytics-utc-tooltip');
      await page.getByRole('button', { name: language === 'en' ? 'Open date range picker' : 'Abrir selector de rango de fechas' }).click();
      await expect(page.getByRole('dialog').locator('input').first()).toHaveValue('2026-03-08T06:30');
      await capture('analytics-picker');
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await page.locator('main select').first().selectOption('stream');
      await expect(inputs.first()).toHaveValue('2026-03-08T01:30');
      await expect(inputs.nth(1)).toHaveValue('2026-03-08T04:30');
      await expect(page.locator('tbody')).toContainText(language === 'en' ? 'EDT' : 'GMT-4');
      await capture('analytics-device');
      await inputs.first().fill('2026-03-08T02:30');
      await expect(page.getByRole('alert')).toBeVisible();
      expect(new URL(page.url()).searchParams.get('start')).toBe('2026-03-08T06:30:00Z');
      await capture('analytics-dst-gap');
      await page.locator('main select').first().selectOption('local');
      await expect(inputs.first()).toHaveValue('2026-03-07T22:30');
      await capture('analytics-browser');
      await page.getByRole('button', { name: language === 'en' ? 'Select Data Stream' : 'Seleccionar flujo de datos', exact: true }).click();
      await expect(page.getByRole('dialog').locator('input[type="datetime-local"]').first()).toHaveValue('2026-03-07T22:30');
      await capture('analytics-stream-selection');
      await page.getByRole('dialog').getByRole('button', { name: language === 'en' ? 'Cancel' : 'Cancelar', exact: true }).click();
      await inputs.first().fill('2026-03-07T23:30');
      await expect.poll(() => new URL(page.url()).searchParams.get('start')).toBe('2026-03-08T07:30:00.000Z');
      for (const path of ['devices', 'devices/123/edit', 'sources', 'sources/1', 'events', 'system-preferences']) {
        await page.goto(`/admin/${path}`);
        await expect(page.getByText(/09:30:00.*UTC/).first()).toBeVisible();
        if (path === 'devices/123/edit') {
          await expect(page.locator('.sensor-item')).toContainText('UTC');
        }
        await capture(`admin-${path.replaceAll('/', '-')}`);
        if (path === 'events') {
          await page.getByRole('tab', { name: language === 'en' ? 'System events' : 'Eventos del sistema' }).click();
          await expect(page.locator('tbody')).toContainText('UTC');
          await capture('admin-system-events');
        }
      }
      expect(state.writes.filter(path => path !== '/auth/refresh')).toEqual([]);
    });
  }
}
