import { expect, test, type Page } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';
import type { Chart } from 'chart.js';

// Opt-in: requires the real isolated DEF-004 fixture, never mocked API data.
const sensorId = process.env.PRECISION_SENSOR_ID;
const baseline = process.env.PRECISION_BASELINE === '1';
test.skip(!sensorId, 'Set PRECISION_SENSOR_ID for the isolated real-backend fixture.');
const start = '2026-10-15T03:50:00Z';
const end = '2026-10-15T04:13:00Z';

async function chartEvidence(page: Page) {
  return page.locator('.sensor-chart canvas').evaluate(element => {
    type Hook = { memoizedState?: { current?: Chart }; next?: Hook };
    type Fiber = { memoizedState?: Hook; return?: Fiber };
    const key = Object.keys(element).find(key => key.startsWith('__reactFiber'))!;
    let fiber = (element as unknown as Record<string, Fiber>)[key];
    while (fiber) {
      let hook = fiber.memoizedState;
      while (hook) {
        const chart = hook.memoizedState?.current;
        if (chart?.canvas === element && chart.getDatasetMeta(0).data.length) {
          const point = chart.getDatasetMeta(0).data[0];
          return {
            values: chart.data.datasets[0].data.map(value => (value as { y: number }).y),
            x: point.x, y: point.y,
            tooltip: chart.tooltip?.body?.flatMap(body => body.lines).join(' ') ?? '',
          };
        }
        hook = hook.next;
      }
      fiber = fiber.return!;
    }
    throw new Error('Mounted chart unavailable');
  });
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`${language === 'en' ? 'P3-04' : 'P6-04'} native scientific export ${width}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    // External map tiles are unrelated to the numeric contract. Keep the real
    // MapLibre controls/markers, while avoiding third-party tile-load timing.
    // Every application API request, including measurements, goes to the backend.
    await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({
      json: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }] },
    }));
    const email = `${language === 'en' ? 'alex' : 'daniela'}.precision@example.com`;
    await page.goto('/login');
    await page.getByLabel('Email').fill(email);
    await page.getByRole('textbox', { name: 'Password' }).fill('Isolated-Precision-QA-2026!');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/map/);
    if (language === 'es' && await page.locator('html').getAttribute('lang') !== 'es') {
      const select = page.getByRole('combobox', { name: 'Language', exact: true });
      if (!await select.isVisible()) await page.getByRole('button', { name: /Account menu for/ }).click();
      await select.selectOption('es');
      await expect(page.locator('html')).toHaveAttribute('lang', 'es');
    }

    const query = new URLSearchParams({ series: `measurement|${sensorId}|pm25|1m`, start, end, timezone: 'utc' });
    await page.goto('/analytics?' + query);
    await expect(page.locator('.sensor-chart canvas')).toBeVisible();
    const displayed = language === 'es' ? '10,1' : '10.1';
    await expect(page.locator('tbody').getByText(displayed, { exact: true }).first()).toBeVisible();
    const canvas = page.locator('.sensor-chart canvas');
    await canvas.scrollIntoViewIfNeeded();
    await expect.poll(async () => (await chartEvidence(page)).values[0]).toBe(baseline ? 10.1 : 10.123456789);
    const chart = await chartEvidence(page);
    const bounds = (await canvas.boundingBox())!;
    await page.mouse.move(bounds.x + chart.x, bounds.y + chart.y);
    await expect.poll(async () => (await chartEvidence(page)).tooltip).toContain(`${displayed} µg/m³`);
    await writeFile(info.outputPath('chart.json'), JSON.stringify(await chartEvidence(page), null, 2));
    await page.screenshot({ path: info.outputPath('tooltip.png') });
    const response = await page.request.get(`/api/sensors/${sensorId}/history?` + new URLSearchParams({ aggregation: '1m', start, end, include_qc: 'true' }));
    expect(response.ok()).toBe(true);
    const history = await response.json();
    expect(history.data).toHaveLength(24);
    expect(history.data[0].value).toBe(baseline ? 10.1 : 10.123456789);
    expect(history.display_precision).toBe(1);
    expect(history.qc_scope).toBe('native');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /Download CSV|Descargar CSV/i }).click();
    const download = await downloadPromise;
    const csvPath = info.outputPath('native.csv');
    await download.saveAs(csvPath);
    const csv = await readFile(csvPath, 'utf8');
    const rows = csv.trim().split(/\r?\n/).map(row => row.split(','));
    expect(rows).toHaveLength(25);
    expect(rows[0]).toHaveLength(18);
    const valueColumn = rows[0].indexOf('Value');
    const values = rows.slice(1).map(row => Number(row[valueColumn]));
    const originalRow = rows.slice(1).find(row => row.includes('2026-10-15T03:50:00.000Z'))!;
    expect(Number(originalRow[valueColumn])).toBe(baseline ? 10.1 : 10.123456789);
    expect(values.reduce((sum, value) => sum + value, 0) / values.length)
      .toBeCloseTo(baseline ? 11.154166666666667 : 11.155144032875, 12);
    expect(csv).toContain('SYNTHETIC-D01');
    expect(csv).toContain('2026-10-15T03:50:00.000Z');
    expect(csv).toContain('µg/m³');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath('analytics.png'), fullPage: true });
    await writeFile(info.outputPath('history.json'), JSON.stringify(history, null, 2));
    await page.goto(`/map?mode=pollutants&parameter=pm25&time_resolution=1m&device_id=${history.device_id}&lat=34.05&lng=-118.25&zoom=10`);
    // The map marker and latest-value panel are independent of the drawer's
    // selected history window, which may not include this fixed fixture date.
    const mapLatest = language === 'es' ? '12,3' : '12.3';
    await expect(page.getByRole('button', { name: /Map marker/ })).toContainText(`${mapLatest} µg/m³`);
    await expect(page.getByText(mapLatest, { exact: true }).first()).toBeVisible();
    await page.screenshot({ path: info.outputPath('map.png'), fullPage: true });
  });
}
