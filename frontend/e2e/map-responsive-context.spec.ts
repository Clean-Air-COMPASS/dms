import { test, expect, type Page } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';

async function expectNoPageOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
}

for (const width of [1440, 390]) {
  test(`shared shells preserve gutters and bounded scrolling at ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await mockAdministration(page);
    for (const path of ['/admin', '/admin/devices', '/admin/sources', '/admin/uploads/csv', '/admin/qc', '/admin/system-preferences', '/analytics']) {
      await page.goto(path);
      await expect(page.locator('.page-header, header').first()).toBeVisible();
      // A reserved scrollbar exercises the containing-block width even for short fixtures.
      await page.addStyleTag({ content: 'html { overflow-y: scroll; scrollbar-gutter: stable; }' });
      await expectNoPageOverflow(page);
      const shellWidth = await page.locator('.admin-page').evaluateAll(shells => shells.map(shell => ({
        width: shell.getBoundingClientRect().width,
        containerWidth: shell.parentElement!.getBoundingClientRect().width,
      })));
      for (const shell of shellWidth) expect(shell.width).toBeLessThanOrEqual(shell.containerWidth);
      await page.screenshot({ path: testInfo.outputPath(`${path.replaceAll('/', '-')}.png`), fullPage: true });
      if (path === '/admin/qc') {
        // A browser-only wide table exercises intentional container scrolling.
        await page.locator('.page-content').evaluate(element => {
          const container = document.createElement('div');
          container.className = 'table-wrap';
          container.dataset.testid = 'synthetic-scroll-container';
          const table = document.createElement('table');
          table.style.minWidth = '1800px';
          table.innerHTML = '<tbody><tr><td>Synthetic scrolling test</td></tr></tbody>';
          container.appendChild(table);
          element.appendChild(container);
          container.scrollLeft = 200;
        });
        const list = page.getByTestId('synthetic-scroll-container');
        expect(await list.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
        await expectNoPageOverflow(page);
      }
      if (path === '/analytics') {
        await page.getByRole('button', { name: 'Cancel', exact: true }).click();
        await expectNoPageOverflow(page);
        await page.screenshot({ path: testInfo.outputPath('analytics-page.png'), fullPage: true });
      }
    }
  });

  test(`Map toolbar and measurement context at ${width}`, async ({ page }, testInfo) => {
    page.setDefaultTimeout(20000);
    await page.setViewportSize({ width, height: 844 });
    // Product metadata comes from the running backend; observations are browser-only fixtures.
    const observedAt = '2026-09-05T09:30:12Z';
    const device = { device_id: 901, name: 'Synthetic UX test station', friendly_name: 'Synthetic UX test station', longitude: 0, latitude: 0, sensor_count: 1, timezone: 'UTC' };
    await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: [device] }));
    await page.route('**/api/devices/901/sensors**', route => route.fulfill({ json: [{ sensor_id: 902, parameter: 'pm25', parameter_name: 'PM2.5', latest_value: 12.5, unit: 'µg/m³', latest_observed_at: observedAt, latest_is_valid: false, native_aggregation_code: '2m', result_aggregation_code: '2m' }] }));
    await page.route('**/api/measurements/pm25/latest**', route => route.fulfill({ json: [{ measurement_id: 903, sensor_id: 902, parameter: 'pm25', value: 12.5, unit: 'µg/m³', observed_at: observedAt, device, native_aggregation_code: '2m', result_aggregation_code: '2m' }] }));
    await page.route('**/api/sensors/902/history**', route => route.fulfill({ json: { sensor_id: 902, parameter: 'pm25', unit: 'µg/m³', data: [], native_aggregation_code: '2m', result_aggregation_code: '2m' } }));
    await page.addInitScript(() => {
      navigator.geolocation.getCurrentPosition = (_success, error) => error?.({ code: 1, message: 'Location unavailable in visual test', PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
    });
    // Keep basemap network availability separate from toolbar and drawer verification.
    await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
      version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
    } }));
    await page.goto('/map');
    await expect(page.getByRole('button', { name: 'Zoom in', exact: true })).toBeVisible();
    const capture = async (name: string) => {
      await expectNoPageOverflow(page);
      await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
    };
    await capture('devices-compact');
    if (width === 390) {
      await page.getByRole('button', { name: 'Map controls' }).click();
      await expect(page.getByRole('dialog', { name: 'Map controls' })).toBeVisible();
      await expect(page.locator('dialog[open]')).toHaveJSProperty('scrollWidth', 390);
      await capture('devices-expanded');
    }
    await page.getByLabel('Parameter', { exact: true }).selectOption('pm25');
    await expect(page.locator('.maplibregl-marker').first()).toBeVisible();
    if (width === 390) await page.getByRole('button', { name: 'Close controls' }).click();
    await page.getByTitle('Synthetic UX test station', { exact: true }).click();
    await expect(page.getByText('Observed at (UTC)', { exact: true })).toBeVisible();
    await expect(page.getByText('QC status', { exact: true })).toBeVisible();
    await expect(page.locator('.map-measurement-context time')).toBeVisible();
    await capture('device-measurement-context');
    await page.getByRole('button', { name: 'Close panel', exact: true }).click();
    if (width === 390) await page.getByRole('button', { name: 'Map controls' }).click();
    await page.getByLabel('Layer', { exact: true }).selectOption('measurements');
    if (width === 390) await page.getByRole('button', { name: 'Close controls' }).click();
    await page.locator('.maplibregl-marker').first().click();
    await expect(page.getByText('QC status').locator('..')).toContainText('Not provided');
    await expect(page.locator('.map-measurement-context time')).toBeVisible();
    await capture('measurement-context');
    await page.getByRole('button', { name: 'Close panel', exact: true }).click();
    if (width === 390) await page.getByRole('button', { name: 'Map controls' }).click();
    await page.getByLabel('Layer', { exact: true }).selectOption('aqi');
    await expect(page.getByLabel('AQI product', { exact: true })).toBeVisible();
    await expect(page.locator('.map-loading')).toBeHidden();
    await capture('aqi-expanded');
    if (width === 390) {
      await page.getByRole('button', { name: 'Close controls' }).click();
      await capture('aqi-compact');
      await page.addInitScript(() => localStorage.setItem('compassaq.language', 'es'));
      await page.reload();
      await page.getByRole('button', { name: 'Controles del mapa' }).click();
      await page.locator('.map-layer-control select').selectOption('aqi');
      const longestProduct = await page.locator('.aqi-product-control select option').evaluateAll(options =>
        options.filter(option => !(option as HTMLOptionElement).disabled)
          .sort((a, b) => (b.textContent?.length ?? 0) - (a.textContent?.length ?? 0))
          .map(option => (option as HTMLOptionElement).value)[0]);
      await page.locator('.aqi-product-control select').selectOption(longestProduct);
      await capture('aqi-spanish-long-label');
      await page.setViewportSize({ width: 768, height: 844 });
      await capture('aqi-spanish-intermediate');
    }
  });
}
