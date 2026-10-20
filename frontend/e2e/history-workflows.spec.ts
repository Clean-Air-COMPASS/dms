import { test, expect, type Page } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import { standards, aqiHistory } from './fixtures/uxAnalytics';

const station = { device_id: 5, name: 'Synthetic Queens history station', friendly_name: null,
  timezone: 'America/New_York', longitude: -73.822, latitude: 40.736, sensor_count: 1 };

async function fixtures(page: Page, language: string) {
  await mockAdministration(page, language);
  await page.addInitScript(() => { navigator.geolocation.getCurrentPosition = () => {}; });
  await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
    version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
  } }));
  await page.route('**/api/air-quality-index/standards', route => route.fulfill({ json: standards }));
  await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: [station] }));
  await page.route('**/api/data-sources*', route => route.fulfill({ json: [{ name: 'PurpleAir', filter_value: 'PurpleAir' }] }));
  const requests: URL[] = [];
  const state = { count: 30, excluded: false };
  await page.route('**/api/measurement-aggregation-capabilities*', route => route.fulfill({ json: [{
    parameter_code: 'pm25', native_aggregation_code: '2m', native_status: 'known', diagnostics: [],
    supported_aggregations: [
      { result_aggregation_code: '2m', display_name: '2 Minutes', duration_minutes: 2, is_rolling: false,
        capability_kind: 'native', supports_history: true, supports_latest: true },
      { result_aggregation_code: 'rolling_24h', display_name: 'Rolling 24-hour', duration_minutes: 1440, is_rolling: true,
        capability_kind: 'chained_rollup', supports_history: false, supports_latest: true },
    ],
  }] }));
  await page.route('**/api/measurements/pm25/latest*', route => {
    const aggregation = new URL(route.request().url()).searchParams.get('aggregation') || '2m';
    return route.fulfill({ json: [{ measurement_id: 1, sensor_id: 14, parameter: 'pm25', parameter_name: 'PM2.5',
      value: 10, unit: 'µg/m³', observed_at: new Date().toISOString(), device: station,
      native_aggregation_code: '2m', result_aggregation_code: aggregation }] });
  });
  await page.route('**/api/sensors/14/history*', route => {
    const url = new URL(route.request().url()); requests.push(url);
    const end = Date.parse(url.searchParams.get('end') || new Date(Date.now() - 2 * 3600000).toISOString());
    const spacing = url.searchParams.get('start') && state.count
      ? (end - Date.parse(url.searchParams.get('start')!)) / state.count : 120000;
    return route.fulfill({ json: { sensor_id: 14, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³',
      device_name: station.name, device_timezone: station.timezone, display_precision: 1,
      native_aggregation_code: '2m', result_aggregation_code: '2m', measurement_timestamp_semantics: 'interval_end',
      history_status: state.excluded ? 'no_eligible_observations' : state.count ? 'available' : 'no_observations',
      data: Array.from({ length: state.count }, (_, index) => ({ value: index % 20 + 5,
        timestamp: new Date(end - (state.count - index) * spacing).toISOString(), is_valid: true,
        interval_started_at: new Date(end - (state.count - index) * spacing - 120000).toISOString(),
        interval_ended_at: new Date(end - (state.count - index) * spacing).toISOString(),
      })) } });
  });
  return { requests, state };
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

async function settleChart(page: Page) {
  let previous = '';
  await expect.poll(async () => {
    const current = await page.locator('.sensor-chart canvas').evaluate(canvas => (canvas as HTMLCanvasElement).toDataURL());
    const stable = current === previous;
    previous = current;
    return stable;
  }, { intervals: [100, 200, 300, 500] }).toBe(true);
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`bounded Map history and QC discovery ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const { requests, state } = await fixtures(page, language);
    const es = language === 'es';
    for (const [name, count, excluded] of [['many', 30, false], ['single', 1, false], ['empty', 0, false], ['excluded', 0, true]] as const) {
      state.count = count; state.excluded = excluded;
      await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=2m');
      await page.locator('.maplibregl-marker').first().click();
      await expect(page.getByRole('heading', { name: station.name })).toBeVisible();
      if (count) {
        await expect(page.locator('.sensor-chart canvas')).toBeVisible(); await settleChart(page);
        if (count > 1) {
          const bluePlotPixels = await page.locator('.sensor-chart canvas').evaluate(canvas => {
            const element = canvas as HTMLCanvasElement;
            const pixels = element.getContext('2d')!.getImageData(40, 35, element.width - 60, element.height - 105).data;
            let blue = 0;
            for (let index = 0; index < pixels.length; index += 4) {
              if (pixels[index] < 40 && pixels[index + 1] > 80 && pixels[index + 1] < 170 && pixels[index + 2] > 180) blue++;
            }
            return blue;
          });
          expect(bluePlotPixels).toBeGreaterThan(20);
        }
      }
      if (name === 'single') await expect(page.getByText(es ? 'Solo hay una observación apta disponible en las últimas 24 horas.' : 'Only one eligible observation is available in the last 24 hours.')).toBeVisible();
      if (name === 'excluded') await expect(page.getByText(/ninguna es apta|none are eligible/)).toBeVisible();
      await noOverflow(page);
      await page.screenshot({ path: testInfo.outputPath(`map-${name}.png`) });
    }
    const before = requests.length;
    await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=rolling_24h');
    await page.locator('.maplibregl-marker').first().click();
    await expect(page.getByRole('alert')).toContainText(es ? 'solo admite resultados recientes' : 'supports latest results only');
    expect(requests.length).toBe(before);
    await page.screenshot({ path: testInfo.outputPath('map-rolling.png') });
    await page.goto('/admin/qc');
    const review = page.getByRole('link', { name: es ? 'Revisar resultados de QC' : 'Review QC results' });
    await expect(review).toHaveAttribute('href', '/admin/events?tab=qc-failures');
    await review.focus(); await expect(review).toBeFocused();
    await noOverflow(page);
    await page.screenshot({ path: testInfo.outputPath('qc-discovery.png'), fullPage: true });
    await review.press('Enter');
    await expect(page).toHaveURL(/\/admin\/events\?tab=qc-failures/);
    await expect(page.locator('.qc-failure-table')).toBeVisible();
  });

  test(`Analytics compact tooltip at edges ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const { state } = await fixtures(page, language);
    // Capture the real canvas tooltip's text geometry without replacing Chart.js.
    await page.addInitScript(() => {
      const original = CanvasRenderingContext2D.prototype.fillText;
      const clear = CanvasRenderingContext2D.prototype.clearRect;
      (window as unknown as { tooltipText: unknown[] }).tooltipText = [];
      CanvasRenderingContext2D.prototype.clearRect = function (x, y, width, height) {
        if (width >= this.canvas.clientWidth) (window as unknown as { tooltipText: unknown[] }).tooltipText = [];
        clear.call(this, x, y, width, height);
      };
      CanvasRenderingContext2D.prototype.fillText = function (text, x, y, maxWidth) {
        if (this.fillStyle === '#ffffff') (window as unknown as { tooltipText: unknown[] }).tooltipText.push({
          text, x, y, width: this.measureText(text).width, canvasWidth: this.canvas.clientWidth, canvasHeight: this.canvas.clientHeight,
        });
        if (maxWidth == null) original.call(this, text, x, y);
        else original.call(this, text, x, y, maxWidth);
      };
    });
    for (const kind of ['aqi', 'measurement']) for (const density of ['sparse', 'dense']) {
      const count = density === 'dense' ? 720 : 4;
      state.count = count;
      await page.route('**/api/air-quality-index/analytics-history', route => {
        const request = route.request().postDataJSON();
        const start = Date.parse(request.range_started_at), end = Date.parse(request.range_ended_at);
        return route.fulfill({ json: { ...aqiHistory, ...request, requested_series_count: 1, returned_series_count: 1,
          series: [{ ...aqiHistory.series[0], device_id: 5, device_name: station.name,
            points: Array.from({ length: count }, (_, index) => ({ ...aqiHistory.series[0].points[0],
              observed_at: new Date(start + (index + 1) / (count + 1) * (end - start)).toISOString(),
              numeric_value: index % 2 ? 10 : 490,
              missing_pollutants: ['o3', 'no2', 'so2'], available_pollutants: ['pm25', 'pm10'],
              ineligible_pollutants: ['co'], coverage_status: 'partial',
            })) }],
        } });
      });
      await page.goto(kind === 'aqi'
        ? '/analytics?series=aqi%7Cus_epa%7Cus_epa.pm25.nowcast%7C5&start=2026-01-01T00%3A00%3A00Z&end=2026-10-06T00%3A00%3A00Z'
        : '/analytics?series=measurement%7C14%7Cpm25%7C2m&start=2026-10-05T00%3A00%3A00Z&end=2026-10-06T00%3A00%3A00Z');
      const canvas = page.locator('.chart-wrapper canvas');
      await expect(canvas).toBeVisible();
      await settleChart(page);
      await canvas.scrollIntoViewIfNeeded();
      const box = (await canvas.boundingBox())!;
      const edges = kind === 'measurement'
        ? [['left', 0.26, 0.3], ['right', 0.91, 0.5], ['top', 0.5, 0.22], ['bottom', 0.5, 0.58]] as const
        : [['left', 0.26, 0.3], ['right', 0.91, 0.7], ['top', 0.5, 0.22], ['bottom', 0.5, 0.68]] as const;
      for (const [edge, x, y] of edges) {
        await page.mouse.move(box.x + box.width + 8, box.y);
        await page.evaluate(() => new Promise(requestAnimationFrame));
        await page.evaluate(() => { (window as unknown as { tooltipText: unknown[] }).tooltipText = []; });
        await page.mouse.move(box.x + box.width * x, box.y + box.height * y);
        await expect.poll(() => page.evaluate(() => (window as unknown as { tooltipText: unknown[] }).tooltipText.length)).toBeGreaterThan(0);
        const lines = await page.evaluate(() => (window as unknown as { tooltipText: { text: string; x: number; y: number; width: number; canvasWidth: number; canvasHeight: number }[] }).tooltipText);
        for (const line of lines) {
          expect(line.x).toBeGreaterThanOrEqual(0);
          expect(line.x + line.width).toBeLessThanOrEqual(line.canvasWidth);
          expect(line.y).toBeGreaterThanOrEqual(0);
          expect(line.y).toBeLessThan(line.canvasHeight);
        }
        const unique = [...new Map(lines.map(line => [line.text, line])).values()];
        expect(unique.length).toBeLessThanOrEqual(7);
        expect(Math.max(...unique.map(line => line.y)) - Math.min(...unique.map(line => line.y))).toBeLessThan(box.height * 0.45);
        await noOverflow(page);
        await page.screenshot({ path: testInfo.outputPath(`${kind}-${density}-${edge}.png`) });
      }
      await page.getByRole('button', { name: language === 'es' ? 'Restablecer zoom' : 'Reset Zoom' }).focus();
      await page.screenshot({ path: testInfo.outputPath(`${kind}-${density}-keyboard.png`) });
    }
  });
}
