import { test, expect, type Page, type Locator, type TestInfo } from '@playwright/test';
import type { Chart } from 'chart.js';
import { writeFile } from 'node:fs/promises';
import { mockAdministration } from './fixtures/administration';

// Set only when capturing the unmodified a4fe6a6 Map consumer.
const baseline = process.env.MAP_TIMEZONE_BASELINE === '1';
const observed = '2026-10-09T04:50:00Z';
const sourceObserved = '2026-10-09T04:00:00Z';
const intervalStart = '2026-10-08T04:50:00Z';
const timestamps = ['2026-10-09T01:50:00Z', '2026-10-09T02:50:00Z', '2026-10-09T03:50:00Z', observed];
const device = { device_id: 901, name: 'Synthetic timezone station', friendly_name: 'Synthetic timezone station',
  latitude: 0, longitude: 0, timezone: 'America/New_York', sensor_count: 1 };

// Read the existing React chart ref, without adding a production debugging API.
async function chartState(canvas: Locator, settle = false) {
  if (settle) await canvas.page().waitForTimeout(1100);
  return canvas.evaluate((element, settle) => {
    type Hook = { memoizedState?: { current?: Chart<'line'> }; next?: Hook };
    type Fiber = { memoizedState?: Hook; return?: Fiber };
    const key = Object.keys(element).find(key => key.startsWith('__reactFiber'))!;
    let fiber: Fiber | undefined = (element as unknown as Record<string, Fiber>)[key];
    while (fiber) {
      let hook = fiber.memoizedState;
      while (hook) {
        const chart = hook.memoizedState?.current;
        if (chart?.canvas === element) {
          if (settle) { chart.stop(); chart.options.animation = false; chart.update('none'); }
          return {
            datasets: chart.data.datasets.map((dataset, index) => ({
              label: dataset.label, color: dataset.borderColor, radii: dataset.pointRadius,
              styles: dataset.pointStyle, spanGaps: dataset.spanGaps, values: dataset.data,
              hidden: !chart.isDatasetVisible(index),
              segments: (chart.getDatasetMeta(index).dataset as unknown as {
                segments?: { start: number; end: number; style?: { borderColor?: string } }[];
              })?.segments,
            })),
            points: chart.getDatasetMeta(0).data.map(point => ({ x: point.x, y: point.y })),
            area: chart.chartArea, width: chart.width, height: chart.height,
            min: chart.scales.x.min, max: chart.scales.x.max,
            axes: Object.values(chart.scales).map(scale => ({ id: scale.id, min: scale.min, max: scale.max,
              title: (scale.options as { title?: unknown }).title,
              ticks: scale.ticks.map(tick => ({ value: tick.value, label: tick.label })) })),
            tooltip: chart.tooltip?.title, tooltipBody: chart.tooltip?.body,
            tooltipIndex: chart.tooltip?.dataPoints?.[0]?.dataIndex,
            legend: (chart.legend as unknown as {
              legendHitBoxes: { left: number; top: number }[];
            })?.legendHitBoxes,
          };
        }
        hook = hook.next;
      }
      fiber = fiber.return;
    }
    throw new Error('Chart ref unavailable');
  }, settle);
}

async function setup(page: Page, language: string, times = timestamps) {
  await mockAdministration(page, language);
  await page.clock.install({ time: new Date('2026-10-09T05:00:00Z') });
  await page.addInitScript(lang => {
    localStorage.setItem('compassaq.language', lang);
    navigator.geolocation.getCurrentPosition = () => {};
  }, language);
  const requests: string[] = [];
  await page.route('**/api/measurement-aggregation-capabilities**', route => route.fulfill({ json: [{
    parameter_code: 'pm25', native_aggregation_code: '2m', native_status: 'known',
    supported_aggregations: ['2m', '1h', '24h', 'rolling_24h'].map(code => ({
      result_aggregation_code: code, display_name: code, supports_latest: true, supports_history: code !== 'rolling_24h',
      duration_minutes: code === '2m' ? 2 : code === '1h' ? 60 : 1440, is_rolling: code === 'rolling_24h', capability_kind: 'native',
    })),
  }] }));
  await page.route('**/api/data-sources', route => route.fulfill({ json: [] }));
  await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: [device] }));
  await page.route(/\/api\/measurements\/(?:pm25\/)?latest(?:\?.*)?$/, route => {
    const code = new URL(route.request().url()).searchParams.get('aggregation') || '2m';
    return route.fulfill({ json: [{ sensor_id: 902, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³',
      value: 15, display_precision: 1, is_valid: true, observed_at: times.at(-1),
      native_aggregation_code: '2m', result_aggregation_code: code, result_is_rolling: code === 'rolling_24h',
      interval_started_at: intervalStart, interval_ended_at: observed, latest_source_observed_at: sourceObserved, device }] });
  });
  await page.route('**/api/sensors/902/history**', route => {
    requests.push(route.request().url());
    const code = new URL(route.request().url()).searchParams.get('aggregation') || '2m';
    return route.fulfill({ json: { sensor_id: 902, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³',
      device_name: device.name, device_timezone: device.timezone, native_aggregation_code: '2m',
      result_aggregation_code: code, display_precision: 1, history_status: 'available',
      data: times.map((timestamp, index) => ({ timestamp, value: 12 + index, is_valid: index !== 2,
        ...(index === 1 || index === 2 ? { qc_results: [{ check_code: 'max_value', evaluation_status: 'failed',
          passed: false, failure_action: index === 1 ? 'flag_for_review' : 'mark_invalid', reason_code: null }] } : {}),
      })) } });
  });
  await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
    version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
  } }));
  return requests;
}

async function capture(page: Page, info: TestInfo, name: string) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`${name}.png`), animations: 'disabled' });
}

// Independent clock expectations: fixed known UTC offsets for these October fixtures.
function checkTicks(state: Awaited<ReturnType<typeof chartState>>, offsetHours: number, language = 'en', month = 'Oct') {
  const ticks = state.axes.find(axis => axis.id === 'x')!.ticks;
  expect(ticks.length).toBeGreaterThan(0);
  for (const tick of ticks) {
    const date = new Date(tick.value + offsetHours * 3_600_000);
    const clock = date.toISOString().slice(11, 16);
    expect(tick.label).toContain(clock);
    expect(tick.label).toContain(language === 'en' ? `${month} ${date.getUTCDate()}` : `${date.getUTCDate()} ${month.toLowerCase()}`);
  }
}

async function hover(page: Page, canvas: Locator, index: number) {
  await canvas.scrollIntoViewIfNeeded();
  const state = await chartState(canvas);
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + state.points[index].x, box.y + state.points[index].y);
  await expect.poll(async () => (await chartState(canvas)).tooltipIndex).toBe(index);
  return chartState(canvas);
}

for (const timezoneId of ['America/Los_Angeles', 'America/New_York']) {
  test.describe(timezoneId, () => {
    test.use({ timezoneId });
    for (const language of ['en', 'es']) for (const width of [1440, 390]) {
      test(`Map UTC history ${language} ${width}`, async ({ page }, info) => {
        await page.setViewportSize({ width, height: 1000 });
        const requests = await setup(page, language);
        await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=2m');
        await page.locator('.maplibregl-marker').first().focus();
        await page.keyboard.press('Enter');
        const canvas = page.locator('.panel-chart-container canvas');
        await expect(canvas).toBeVisible();
        const details = page.locator('.map-measurement-context');
        await expect(details.locator('time')).toHaveAttribute('datetime', '2026-10-09T04:50:00.000Z');
        await expect(details).toContainText('04:50:00 UTC');
        await expect(details).toContainText(language === 'en' ? 'Observed at (UTC)' : 'Observado el (UTC)');
        await expect(page.locator('.hero-value')).toHaveText(language === 'en' ? '15.0' : '15,0');
        const state = await chartState(canvas, true);
        const offset = baseline ? timezoneId === 'America/Los_Angeles' ? -7 : -4 : 0;
        checkTicks(state, offset, language);
        expect(JSON.stringify(state.axes[0].title)).toContain(baseline ? timezoneId : 'UTC');
        expect(state.datasets[0].values.map(point => (point as { x: number; y: number }).x)).toEqual(timestamps.map(Date.parse));
        expect(state.datasets[0].values.map(point => (point as { x: number; y: number }).y)).toEqual([12, 13, 14, 15]);
        expect(state.datasets[0].radii).toEqual([2.5, 4, 4, 2.5]);
        expect(state.datasets[0].styles).toEqual(['circle', 'triangle', 'crossRot', 'circle']);
        await capture(page, info, 'map');
        const hovered = await hover(page, canvas, 3);
        const expected = baseline
          ? timezoneId === 'America/Los_Angeles' ? ['10/8/2026, 09:50:00 PM PDT', '8/10/2026, 21:50:00 GMT-7']
            : ['10/9/2026, 12:50:00 AM EDT', '9/10/2026, 00:50:00 GMT-4']
          : ['10/9/2026, 04:50:00 AM UTC', '9/10/2026, 04:50:00 UTC'];
        expect(hovered.tooltip).toEqual([expected[language === 'en' ? 0 : 1]]);
        await capture(page, info, 'tooltip');
        const box = (await canvas.boundingBox())!;
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await page.keyboard.down('Control'); await page.mouse.wheel(0, -300); await page.keyboard.up('Control');
        await expect.poll(async () => { const current = await chartState(canvas); return current.max - current.min; }).toBeLessThan(state.max - state.min);
        const zoomed = await chartState(canvas);
        checkTicks(zoomed, offset, language);
        await capture(page, info, 'zoom');
        await page.keyboard.down('Shift'); await page.mouse.down();
        await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2, { steps: 8 });
        await page.mouse.up(); await page.keyboard.up('Shift');
        expect((await chartState(canvas)).min).not.toBe(zoomed.min);
        await page.locator('.chart-action-btn').focus(); await page.keyboard.press('Enter');
        await expect.poll(async () => (await chartState(canvas)).min).toBe(state.min);
        const legend = state.legend![0];
        await page.mouse.click(box.x + legend.left + 8, box.y + legend.top + 5);
        await expect.poll(async () => (await chartState(canvas)).datasets[0].hidden).toBe(true);
        await page.mouse.click(box.x + legend.left + 8, box.y + legend.top + 5);
        await expect.poll(async () => (await chartState(canvas)).datasets[0].hidden).toBe(false);
        const selectResolution = async (code: string) => {
          if (width === 390) {
            await page.getByRole('button', { name: language === 'en' ? 'Close panel' : 'Cerrar panel', exact: true }).click();
            await page.getByRole('button', { name: language === 'en' ? 'Map controls' : 'Controles del mapa', exact: true }).click();
          }
          await page.getByLabel(language === 'en' ? 'Time resolution' : 'Resolución temporal', { exact: true }).selectOption(code);
          if (width === 390) {
            await page.getByRole('button', { name: language === 'en' ? 'Close controls' : 'Cerrar controles', exact: true }).click();
            await page.locator('.maplibregl-marker').first().click();
          }
        };
        for (const code of ['1h', '24h', 'rolling_24h', '2m']) {
          await selectResolution(code);
          await expect(page.getByRole('heading', { name: device.name, exact: true })).toBeVisible();
          await expect(page.locator('.hero-value')).toHaveText(language === 'en' ? '15.0' : '15,0');
          if (code === 'rolling_24h') {
            await expect(details).toContainText(language === 'en' ? 'Calculated at (UTC)' : 'Calculado el (UTC)');
            await expect(details).toContainText(language === 'en' ? 'Rolling window (UTC)' : 'Ventana móvil (UTC)');
            await expect(details).toContainText(language === 'en' ? 'Latest source observation (UTC)' : 'Última observación de origen (UTC)');
            await expect(details.locator('time')).toHaveText([language === 'en' ? 'Oct 9, 2026, 04:50:00 UTC' : '9 oct 2026, 04:50:00 UTC',
              language === 'en' ? 'Oct 8, 2026, 04:50:00 UTC' : '8 oct 2026, 04:50:00 UTC',
              language === 'en' ? 'Oct 9, 2026, 04:50:00 UTC' : '9 oct 2026, 04:50:00 UTC',
              language === 'en' ? 'Oct 9, 2026, 04:00:00 UTC' : '9 oct 2026, 04:00:00 UTC']);
            expect(await details.locator('time').evaluateAll(elements => elements.map(element => element.getAttribute('datetime')))).toEqual([
              '2026-10-09T04:50:00.000Z', '2026-10-08T04:50:00.000Z', '2026-10-09T04:50:00.000Z', '2026-10-09T04:00:00.000Z']);
            expect(requests.some(url => url.includes('rolling_24h'))).toBe(false);
            await expect(canvas).toHaveCount(0);
            await capture(page, info, 'rolling');
          } else {
            await expect(canvas).toBeVisible();
            expect(requests.at(-1)).toContain(`aggregation=${code}`);
            checkTicks(await chartState(canvas, true), offset, language);
          }
        }
        await writeFile(info.outputPath('evidence.json'), JSON.stringify({ state, hovered, zoomed, requests }, null, 2));
        await page.getByRole('link', { name: language === 'en' ? 'Open Full Analytics' : 'Abrir análisis completo', exact: true }).click();
        await expect(page).toHaveURL(/\/analytics\?/);
        expect(new URL(page.url()).searchParams.getAll('series')).toEqual(['measurement|902|pm25|2m']);
        await expect(page.locator('main select').first()).toHaveValue('stream');
      });
    }

    test('Map preserves UTC instants across the New York DST overlap', async ({ page }, info) => {
      const times = ['2026-11-01T05:30:00Z', '2026-11-01T06:30:00Z'];
      await setup(page, 'en', times);
      await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=2m');
      await page.locator('.maplibregl-marker').first().click();
      const canvas = page.locator('.panel-chart-container canvas');
      await expect(canvas).toBeVisible();
      const state = await chartState(canvas, true);
      if (!baseline) checkTicks(state, 0, 'en', 'Nov');
      expect(state.datasets[0].values.map(point => (point as { x: number }).x)).toEqual([1793511000000, 1793514600000]);
      await expect(page.locator('.map-measurement-context')).toContainText('06:30:00 UTC');
      for (let index = 0; index < 2; index++) {
        const result = await hover(page, canvas, index);
        const expected = baseline ? timezoneId === 'America/New_York'
          ? ['11/1/2026, 01:30:00 AM EDT', '11/1/2026, 01:30:00 AM EST']
          : ['10/31/2026, 10:30:00 PM PDT', '10/31/2026, 11:30:00 PM PDT']
          : ['11/1/2026, 05:30:00 AM UTC', '11/1/2026, 06:30:00 AM UTC'];
        expect(result.tooltip).toEqual([expected[index]]);
      }
      await capture(page, info, 'dst');
    });

    for (const language of ['en', 'es']) for (const width of [1440, 390]) {
      test(`Analytics modes unchanged ${language} ${width}`, async ({ page }, info) => {
        await page.setViewportSize({ width, height: 1000 });
        const requests = await setup(page, language);
        const query = new URLSearchParams({ series: 'measurement|902|pm25|2m', timezone: 'utc', start: timestamps[0], end: observed });
        await page.goto(`/analytics?${query}`);
        const canvas = page.locator('.sensor-chart canvas');
        await expect(canvas).toBeVisible();
        const evidence: Record<string, unknown> = {};
        for (const mode of ['utc', 'local', 'stream']) {
          await page.locator('main select').first().selectOption(mode);
          const offset = mode === 'utc' ? 0 : mode === 'stream' || timezoneId === 'America/New_York' ? -4 : -7;
          const state = await chartState(canvas, true);
          checkTicks(state, offset, language);
          const hovered = await hover(page, canvas, 3);
          const expected = offset === 0 ? ['10/9/2026, 04:50:00 AM UTC', '9/10/2026, 04:50:00 UTC']
            : offset === -4 ? ['10/9/2026, 12:50:00 AM EDT', '9/10/2026, 00:50:00 GMT-4']
            : ['10/8/2026, 09:50:00 PM PDT', '8/10/2026, 21:50:00 GMT-7'];
          expect(hovered.tooltip).toEqual([expected[language === 'en' ? 0 : 1]]);
          await expect(page.locator('tbody')).toContainText(expected[language === 'en' ? 0 : 1]);
          await expect(page.locator('main input[type="datetime-local"]').first()).toHaveValue(offset === 0
            ? '2026-10-09T01:50' : offset === -4 ? '2026-10-08T21:50' : '2026-10-08T18:50');
          evidence[mode] = { state, hovered };
          await capture(page, info, mode);
        }
        // Analytics currently refetches on selector changes; preserve its request
        // contract and range instead of asserting a new caching policy.
        expect(new Set(requests).size).toBe(1);
        evidence.requests = requests;
        await writeFile(info.outputPath('evidence.json'), JSON.stringify(evidence, null, 2));
      });
    }
  });
}
