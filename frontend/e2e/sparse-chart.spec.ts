import { test, expect, type Page } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { mockAdministration } from './fixtures/administration';
import { history, start, end } from './fixtures/sparseChart';
import { standards, aqiHistory } from './fixtures/uxAnalytics';

const baseline = process.env.CHART_BASELINE === '1';
test.use({ timezoneId: 'America/Los_Angeles' });

// Test-only access to the existing React ref; no production debugging interface.
async function inspect(page: Page, action = 'state') {
  if (action === 'settle') await page.waitForTimeout(1100);
  return page.locator('.sensor-chart canvas').evaluate((element, action) => {
    let fiber: any = (element as any)[Object.keys(element).find(key => key.startsWith('__reactFiber'))!];
    while (fiber) {
      let hook = fiber.memoizedState;
      while (hook) {
        const chart = hook.memoizedState?.current;
        if (chart?.canvas === element) {
          if (action === 'settle') { chart.stop(); chart.options.animation = false; chart.update('none'); }
          if (action === 'update') {
            const began = performance.now(); chart.update('none'); return { ms: performance.now() - began };
          }
          return {
            datasets: chart.data.datasets.map((dataset: any, index: number) => ({
              label: dataset.label, axis: dataset.yAxisID, color: dataset.borderColor,
              radii: dataset.pointRadius, styles: dataset.pointStyle, spanGaps: dataset.spanGaps,
              values: dataset.data.map((p: any) => [p.x, p.y]),
              segments: chart.getDatasetMeta(index).dataset.segments.map((s: any) => ({ start: s.start, end: s.end, color: s.style?.borderColor })),
              hidden: !chart.isDatasetVisible(index),
            })),
            points: chart.getDatasetMeta(0).data.map((p: any) => ({ x: p.x, y: p.y, radius: p.options.radius, skip: p.skip })),
            tooltip: chart.tooltip?.title, tooltipBody: chart.tooltip?.body,
            min: chart.scales.x.min, max: chart.scales.x.max,
            axes: Object.values(chart.scales).map((s: any) => ({ id: s.id, min: s.min, max: s.max, title: s.options.title.text, ticks: s.ticks.map((t: any) => t.label) })),
            legend: chart.legend.legendHitBoxes,
          };
        }
        hook = hook.next;
      }
      fiber = fiber.return;
    }
    throw new Error('Chart ref unavailable');
  }, action);
}

async function setup(page: Page, language: string, scenario: string, count = 100) {
  // Optional original-source replay for deterministic before/after comparisons.
  // Generate this local file from the baseline git revision (see regression report).
  if (process.env.CHART_REPLAY_BASELINE === '1') await page.route(/\/src\/SensorChart\.tsx(?:\?.*)?$/, async route => {
    const response = await route.fetch({ url: route.request().url().replace('SensorChart.tsx', 'SensorChart.baseline.tsx') });
    await route.fulfill({ response });
  });
  await mockAdministration(page, language);
  await page.clock.install({ time: new Date('2026-08-02T00:00:00Z') });
  await page.addInitScript(lang => {
    localStorage.setItem('compassaq.language', lang);
    navigator.geolocation.getCurrentPosition = () => {};
  }, language);
  const device = { device_id: 901, name: 'Synthetic chart station', friendly_name: 'Synthetic chart station',
    latitude: 0, longitude: 0, timezone: 'America/New_York', sensor_count: 1 };
  const requests: string[] = [];
  await page.route('**/api/measurement-aggregation-capabilities**', route => route.fulfill({ json: [{
    parameter_code: 'pm25', native_aggregation_code: '2m', native_status: 'known',
    supported_aggregations: ['2m', '1h', '24h', 'rolling_24h'].map(code => ({
      result_aggregation_code: code, display_name: code, supports_latest: true, supports_history: code !== 'rolling_24h',
      duration_minutes: code === '2m' ? 2 : code === '1h' ? 60 : 1440, is_rolling: code === 'rolling_24h', capability_kind: 'native',
    })),
  }] }));
  await page.route('**/api/data-sources', route => route.fulfill({ json: [] }));
  await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: scenario === 'aqi'
    ? aqiHistory.series.map(series => ({ ...device, device_id: series.device_id })) : [device] }));
  await page.route(/\/api\/measurements\/(?:pm25\/)?latest(?:\?.*)?$/, route => route.fulfill({ json: [{
    sensor_id: 902, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³', value: 15,
    observed_at: '2026-08-01T04:00:00Z', native_aggregation_code: '2m', result_aggregation_code: '2m', device,
  }] }));
  await page.route('**/api/sensors/*/history**', route => {
    requests.push(route.request().url());
    const url = new URL(route.request().url());
    const result = history(scenario, count);
    result.sensor_id = Number(url.pathname.split('/')[3]);
    result.result_aggregation_code = url.searchParams.get('aggregation') || '2m';
    if (result.sensor_id === 903) { result.unit = '°C'; result.parameter = 'temperature'; result.parameter_name = 'Temperature'; }
    if (!url.searchParams.has('include_invalid')) result.data = result.data.filter(p => p.is_valid);
    return route.fulfill({ json: result });
  });
  await page.route('**/api/air-quality-index/standards', route => route.fulfill({ json: standards }));
  await page.route('**/api/air-quality-index/analytics-history', route => route.fulfill({ json: {
    ...aqiHistory, series: aqiHistory.series.map(series => ({ ...series, points: [series.points[0],
      { ...series.points[0], observed_at: '2026-08-01T02:00:00Z', calculation_status: 'unavailable', numeric_value: null },
      { ...series.points[0], observed_at: '2026-08-01T03:00:00Z' }] })),
  } }));
  await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
    version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
  } }));
  return requests;
}

function analyticsUrl(scenario: string, count: number) {
  const series = scenario === 'aqi' ? 'aqi|us_epa|us_epa.pm25.nowcast|1,aqi|eea_european|eea_european.overall.hourly|2'
    : scenario === 'multiple' ? 'measurement|902|pm25|2m,measurement|903|temperature|2m' : 'measurement|902|pm25|2m';
  const query = new URLSearchParams({ start,
    end: count > 100 ? new Date(Date.parse(start) + count * 120_000).toISOString() : end, timezone: 'utc' });
  series.split(',').forEach(value => query.append('series', value));
  return '/analytics?' + query;
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  for (const context of ['map', 'analytics']) {
    test(`sparse interactions ${context} ${language} ${width}`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      await setup(page, language, 'sparse');
      await page.goto(context === 'map' ? '/map?mode=pollutants&parameter=pm25&time_resolution=2m' : analyticsUrl('sparse', 100));
      if (context === 'map') { await page.locator('.maplibregl-marker').first().focus(); await page.keyboard.press('Enter'); }
      await expect(page.locator('.sensor-chart canvas')).toBeVisible();
      const state = await inspect(page, 'settle');
      expect(state.datasets[0].radii).toEqual(Array(4).fill(baseline ? 0 : 2.5));
      expect(state.points[3].y).toBeLessThan(state.points[0].y);
      expect(state.datasets[0].segments.every((s: { color: string }) => s.color === 'transparent')).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath('sparse.png'), fullPage: true, animations: 'disabled' });
      const canvas = page.locator('.sensor-chart canvas');
      await canvas.scrollIntoViewIfNeeded();
      const box = (await canvas.boundingBox())!;
      const point = state.points[1];
      await page.mouse.move(box.x + point.x, box.y + point.y);
      await expect.poll(async () => (await inspect(page)).tooltip?.length).toBeGreaterThan(0);
      const hovered = await inspect(page);
      await page.screenshot({ path: info.outputPath('tooltip.png'), fullPage: true });
      await page.mouse.click(box.x + state.legend[0].left + 8, box.y + state.legend[0].top + 5);
      await expect.poll(async () => (await inspect(page)).datasets[0].hidden).toBe(true);
      await page.mouse.click(box.x + state.legend[0].left + 8, box.y + state.legend[0].top + 5);
      await expect.poll(async () => (await inspect(page)).datasets[0].hidden).toBe(false);
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.keyboard.down('Control'); await page.mouse.wheel(0, -300); await page.keyboard.up('Control');
      await expect.poll(async () => { const s = await inspect(page); return s.max - s.min; }).toBeLessThan(state.max - state.min);
      const zoomed = await inspect(page);
      await page.keyboard.down('Shift'); await page.mouse.down(); await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2, { steps: 8 }); await page.mouse.up(); await page.keyboard.up('Shift');
      expect((await inspect(page)).min).not.toBe(zoomed.min);
      await page.locator('.chart-action-btn').focus(); await page.keyboard.press('Enter');
      await expect.poll(async () => (await inspect(page)).min).toBe(state.min);
      await writeFile(info.outputPath('configuration.json'), JSON.stringify({ state, hovered }, null, 2));
    });
  }
}

for (const scenario of ['dense', 'mixed', 'qc', 'aqi', 'multiple', 'single', 'two']) {
  test(`deterministic ${scenario}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const requests = await setup(page, 'en', scenario);
    await page.goto(analyticsUrl(scenario, 100));
    await expect(page.locator('.sensor-chart canvas')).toBeVisible();
    if (scenario === 'qc') await page.getByRole('checkbox', { name: 'Include invalid measurements', exact: true }).check();
    const state = await inspect(page, 'settle');
    if (scenario === 'dense') expect(state.datasets[0].radii.every((r: number) => r === 0)).toBe(true);
    if (scenario === 'mixed') expect(state.datasets[0].radii).toEqual([0, 0, 0, 0, 0, 0, baseline ? 0 : 2.5]);
    if (scenario === 'single' || scenario === 'two') expect(state.datasets[0].radii.every((r: number) => r === 2.5)).toBe(true);
    if (scenario === 'aqi') expect(state.datasets.every((d: { spanGaps: boolean }) => d.spanGaps === false)).toBe(true);
    await page.screenshot({ path: info.outputPath('chart.png'), fullPage: true, animations: 'disabled' });
    if (scenario === 'qc') {
      expect(state.datasets[0].styles).toEqual(['circle', 'triangle', 'crossRot', 'circle', 'crossRot', 'circle', 'circle']);
      expect(state.datasets[0].radii[1]).toBe(4); expect(state.datasets[0].radii[2]).toBe(4);
      const before = requests.length;
      await page.getByRole('checkbox', { name: 'Show invalid points' }).uncheck();
      const hidden = await inspect(page, 'settle');
      expect(hidden.datasets[0].values[2][1]).toBeNull(); expect(hidden.datasets[0].radii[2]).toBe(0);
      expect(requests).toHaveLength(before);
      await writeFile(info.outputPath('hidden.json'), JSON.stringify(hidden, null, 2));
    }
    await writeFile(info.outputPath('configuration.json'), JSON.stringify(state, null, 2));
  });
}

for (const count of [100, 1000, 3000]) {
  test(`performance ${count}`, async ({ page }, info) => {
    await setup(page, 'en', 'dense', count);
    const began = Date.now();
    await page.goto(analyticsUrl('dense', count));
    await expect(page.locator('.sensor-chart canvas')).toBeVisible();
    const initialMs = Date.now() - began;
    const state = await inspect(page, 'settle');
    const updates = [];
    for (let i = 0; i < 7; i++) updates.push((await inspect(page, 'update')).ms);
    await page.locator('.sensor-chart canvas').scrollIntoViewIfNeeded();
    const box = (await page.locator('.sensor-chart canvas').boundingBox())!;
    const hoverBegan = Date.now();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await expect.poll(async () => (await inspect(page)).tooltip?.length).toBeGreaterThan(0);
    const hoverMs = Date.now() - hoverBegan;
    const zoomBegan = Date.now();
    await page.keyboard.down('Control'); await page.mouse.wheel(0, -300); await page.keyboard.up('Control');
    await expect.poll(async () => { const s = await inspect(page); return s.max - s.min; }).toBeLessThan(state.max - state.min);
    await writeFile(info.outputPath('performance.json'), JSON.stringify({ count, initialMs, updates, hoverMs, zoomMs: Date.now() - zoomBegan,
      markers: state.datasets[0].radii.filter((r: number) => r > 0).length }, null, 2));
  });
}
