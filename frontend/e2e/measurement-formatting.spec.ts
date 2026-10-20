import { test, expect, type Page } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { mockAdministration } from './fixtures/administration';
import { history, start, end } from './fixtures/sparseChart';

const before = process.env.FORMATTING_BASELINE === '1';
const values = [17.141666666666666, 0.0049, 0, -0, 999.995, -0.0049, null];
test.use({ timezoneId: 'America/Los_Angeles' });
async function chartState(page: Page, hover = false) {
  return page.locator('.sensor-chart canvas').evaluate((element, hover) => {
    // Inspect the actual Chart.js ref, as in sparse-chart.spec.ts.
    let fiber: any = (element as any)[Object.keys(element).find(key => key.startsWith('__reactFiber'))!];
    while (fiber) {
      let hook = fiber.memoizedState;
      while (hook) {
        const chart = hook.memoizedState?.current;
        if (chart?.canvas === element) {
          chart.stop(); chart.options.animation = false; chart.update('none');
          if (hover) {
            const p = chart.getDatasetMeta(0).data[0];
            chart.tooltip.setActiveElements([{ datasetIndex: 0, index: 0 }], { x: p.x, y: p.y });
            chart.update('none');
          }
          return {
            values: chart.data.datasets[0].data.map((p: any) => p.y),
            radii: chart.data.datasets[0].pointRadius,
            axes: Object.values(chart.scales).map((s: any) => ({ id: s.id, min: s.min, max: s.max, ticks: s.ticks.map((t: any) => t.label) })),
            tooltip: chart.tooltip?.body,
          };
        }
        hook = hook.next;
      }
      fiber = fiber.return;
    }
    throw new Error('Chart ref unavailable');
  }, hover);
}

for (const lang of ['en', 'es']) for (const width of [1440, 390]) {
  test(`measurement presentation ${lang} ${width}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockAdministration(page, lang);
    await page.clock.install({ time: new Date('2026-08-02T00:00:00Z') });
    await page.addInitScript(language => { localStorage.setItem('compassaq.language', language); navigator.geolocation.getCurrentPosition = () => {}; }, lang);
    const device = { device_id: 901, name: 'Synthetic formatting station', friendly_name: 'Synthetic formatting station', latitude: 0, longitude: 0, timezone: 'UTC', sensor_count: 1 };
    await page.route('**/api/measurement-aggregation-capabilities**', route => route.fulfill({ json: [{ parameter_code: 'pm25', native_aggregation_code: '2m', native_status: 'known', supported_aggregations: ['2m', '1h', '24h', 'rolling_24h'].map(code => ({ result_aggregation_code: code, display_name: code, duration_minutes: code === '2m' ? 2 : 60, supports_latest: true, supports_history: code !== 'rolling_24h', is_rolling: code === 'rolling_24h', capability_kind: 'native' })) }] }));
    await page.route('**/api/data-sources', route => route.fulfill({ json: [] }));
    await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: [device] }));
    await page.route(/\/api\/measurements\/(?:pm25\/)?latest(?:\?.*)?$/, route => route.fulfill({ json: [{ sensor_id: 902, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³', value: values[0], observed_at: '2026-08-01T01:00:00Z', native_aggregation_code: '2m', result_aggregation_code: '2m', display_precision: null, device }] }));
    await page.route('**/api/sensors/*/history**', route => {
      const data = history('sparse');
      return route.fulfill({ json: { ...data, display_precision: null, device_name: device.name, data: values.map((value, index) => ({ timestamp: new Date(Date.parse(start) + (index + 1) * 3600000).toISOString(), value, is_valid: true })) } });
    });
    await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }] } }));
    await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=2m');
    await page.locator('.maplibregl-marker').first().focus(); await page.keyboard.press('Enter');
    await expect(page.locator('.sensor-chart canvas')).toBeVisible();
    await page.waitForTimeout(1200);
    const map = await chartState(page, true);
    const expected = before ? '17.141666666666666' : lang === 'es' ? '17,1416666667' : '17.1416666667';
    await expect(page.getByText(expected, { exact: true }).first()).toBeVisible();
    await page.screenshot({ path: info.outputPath('map.png'), fullPage: true });
    const query = new URLSearchParams({ series: 'measurement|902|pm25|2m', start, end, timezone: 'utc' });
    await page.goto('/analytics?' + query);
    await expect(page.locator('.sensor-chart canvas')).toBeVisible();
    await page.waitForTimeout(1200);
    const analytics = await chartState(page, true);
    await expect(page.locator('tbody').getByText(expected, { exact: true })).toBeVisible();
    await expect(page.locator('tbody').getByText(before || lang === 'en' ? '0.0049' : '0,0049', { exact: true })).toBeVisible();
    const rows = await page.locator('tbody').innerText();
    await page.screenshot({ path: info.outputPath('analytics.png'), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /Download CSV|Descargar CSV/i }).click();
    const download = await downloadPromise;
    await download.saveAs(info.outputPath('measurements.csv'));
    await writeFile(info.outputPath('values.json'), JSON.stringify({ map, analytics, rows }, null, 2));
  });
}

// Backend-shaped products: expected strings are literal, independently specified.
// Rolling remains latest-only; it is covered by map-measurement-synchronization.
for (const lang of ['en', 'es']) {
  test(`pollutant and aggregation precision ${lang}`, async ({ page }, info) => {
    await mockAdministration(page, lang);
    await page.setViewportSize({ width: 1440, height: 1000 });
    const cases: [string, string, string, number, number | null, string, string][] = [
      ['pm25', '1m', 'µg/m³', 17.1, 1, '17.1', '17,1'],
      ['pm25', '1h', 'µg/m³', 17, 1, '17.0', '17,0'],
      ['pm25', '24h', 'µg/m³', 17, 1, '17.0', '17,0'],
      ['pm10', '1h', 'µg/m³', 17, 0, '17', '17'],
      ['o3', '1h', 'ppm', 0.005, 3, '0.005', '0,005'],
      ['no2', '1h', 'ppm', 1, 1, '1.0', '1,0'],
      ['so2', '1h', 'ppm', 2, 1, '2.0', '2,0'],
      ['co', '1h', 'ppm', 3, 1, '3.0', '3,0'],
      ['no', '1h', 'ppb', 4, 1, '4.0', '4,0'],
      ['nox', '1h', 'ppm', 0.0049, null, '0.0049', '0,0049'],
      ['pm1', '1m', 'µg/m³', 12.3456, null, '12.3456', '12,3456'],
      ['co2', '1m', 'ppm', 401.234, null, '401.234', '401,234'],
      ['temperature', '1m', '°C', -0.0049, null, '-0.0049', '-0,0049'],
      ['tvoc', '1m', 'ppb', 0.0049, null, '0.0049', '0,0049'],
      ['tvoc_index', '1m', 'index', 12.3456, null, '12.3456', '12,3456'],
      ['nox_index', '1m', 'index', 99.995, null, '99.995', '99,995'],
      ['pressure', '1m', 'hPa', 1013.251, null, '1013.251', '1013,251'],
      ['relative_humidity', '1m', '%', 45.1234, null, '45.1234', '45,1234'],
    ];
    const evidence = [];
    for (const [parameter, aggregation, unit, value, precision, en, es] of cases) {
      const response = { ...history('single'), parameter, parameter_name: parameter, unit,
        result_aggregation_code: aggregation, display_precision: precision,
        data: [{ timestamp: '2026-08-01T01:00:00Z', value, is_valid: true }] };
      await page.route('**/api/sensors/*/history**', route => route.fulfill({ json: response }));
      const query = new URLSearchParams({ series: `measurement|902|${parameter}|${aggregation}`, start, end, timezone: 'utc' });
      await page.goto('/analytics?' + query);
      await expect(page.locator('.sensor-chart canvas')).toBeVisible();
      const expected = lang === 'es' ? es : en;
      const table = page.locator('tbody');
      await expect(table.getByText(expected, { exact: true })).toBeVisible();
      const state = await chartState(page, true);
      expect(state.values).toEqual([value]);
      expect(state.tooltip[0].lines.join(' ')).toContain(`${expected} ${unit}`);
      await table.locator('summary').first().click();
      await expect(table.locator('details p.font-medium').first()).toContainText(`${expected} ${unit}`);
      evidence.push({ parameter, aggregation, unit, precision, value, displayed: expected, state });
    }
    await writeFile(info.outputPath('pollutants.json'), JSON.stringify(evidence, null, 2));
  });
}
