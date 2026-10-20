import { test, expect } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import type { Chart } from 'chart.js';

// Inspect the existing chart ref in tests; do not add a production debug API.
async function chartState(canvas: import('@playwright/test').Locator) {
  return canvas.evaluate(element => {
    type Hook = { memoizedState?: { current?: Chart<'line'> }; next?: Hook };
    type Fiber = { memoizedState?: Hook; return?: Fiber };
    const key = Object.keys(element).find(key => key.startsWith('__reactFiber'))!;
    let fiber: Fiber | undefined = (element as unknown as Record<string, Fiber>)[key];
    while (fiber) {
      let hook = fiber.memoizedState;
      while (hook) {
        const chart = hook.memoizedState?.current;
        if (chart?.canvas === element) {
          const points = chart.data.datasets[0].data;
          const last = points.at(-1) as { y: number };
          const point = chart.getDatasetMeta(0).data.at(-1)!;
          return { value: last.y, label: chart.data.datasets[0].label,
            animationRemaining: Math.abs(point.y - point.getProps(['y'], true).y) };
        }
        hook = hook.next;
      }
      fiber = fiber.return;
    }
    return null;
  });
}

const evaluated = '2026-10-09T04:50:00Z';
const sourceObserved = '2026-10-09T04:00:00Z';
const device = { device_id: 901, name: 'Synthetic rolling station', friendly_name: 'Synthetic rolling station',
  latitude: 0, longitude: 0, timezone: 'UTC', network: 'Synthetic provider', external_api: { name: 'Synthetic provider' } };
const values: Record<string, number> = { '2m': 4.9, '1h': 12.5, '24h': 22.5, rolling_24h: 32.5 };
const capabilities = [{ parameter_code: 'pm25', native_aggregation_code: '2m', native_status: 'known',
  supported_aggregations: Object.keys(values).map(code => ({ result_aggregation_code: code, display_name: code,
    duration_minutes: code === '2m' ? 2 : code === '1h' ? 60 : 1440, is_rolling: code === 'rolling_24h',
    capability_kind: code === '2m' ? 'native' : 'chained_rollup', rollup_path: ['2m', code],
    supports_latest: true, supports_history: code !== 'rolling_24h', formatting_status: 'configured', display_precision: 1 })) }];

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`measurement synchronization preserves Map presentation ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await mockAdministration(page, language);
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = () => {};
    }, language);
    let unavailable = false;
    let refreshed = false;
    const historyRequests: string[] = [];
    await page.route('**/api/measurement-aggregation-capabilities**', route => route.fulfill({ json: capabilities }));
    await page.route('**/api/data-sources', route => route.fulfill({ json: [{ name: 'Synthetic provider', filter_value: 'synthetic provider' }] }));
    await page.route('**/api/measurements/pm25/latest**', route => {
      const code = new URL(route.request().url()).searchParams.get('aggregation') || '2m';
      return route.fulfill({ json: unavailable ? [] : [{ measurement_id: code === '2m' ? 903 : 0, sensor_id: 902,
        parameter: 'pm25', parameter_name: 'PM2.5', value: refreshed ? 6.1 : values[code], unit: 'µg/m³',
        native_aggregation_code: '2m', result_aggregation_code: code, display_precision: 1,
        result_is_rolling: code === 'rolling_24h', observed_at: evaluated,
        interval_started_at: '2026-10-08T04:50:00Z', interval_ended_at: evaluated,
        latest_source_observed_at: sourceObserved, device }] });
    });
    await page.route('**/api/sensors/902/history**', route => {
      const code = new URL(route.request().url()).searchParams.get('aggregation')!;
      historyRequests.push(code);
      return route.fulfill({ json: { sensor_id: 902, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³',
        native_aggregation_code: '2m', result_aggregation_code: code, display_precision: 1, device_timezone: 'UTC',
        data: [{ timestamp: new Date(Date.now() - 7200_000).toISOString(), value: 3.2, is_valid: true },
          { timestamp: new Date(Date.now() - 3600_000).toISOString(), value: refreshed ? 6.1 : values[code], is_valid: true }] } });
    });
    await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
      version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
    } }));
    await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=2m');
    const closePanel = page.getByRole('button', { name: language === 'en' ? 'Close panel' : 'Cerrar panel', exact: true });
    const capture = async (name: string) => {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(await page.locator('.slide-out-panel.open').evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
      const canvas = page.locator('.panel-chart-container canvas');
      if (await canvas.count()) await expect.poll(async () => (await chartState(canvas))?.animationRemaining).toBeLessThan(0.1);
      await page.screenshot({ path: testInfo.outputPath(`${name}.png`), animations: 'disabled' });
    };
    const selectResolution = async (code: string) => {
      if (width === 390) {
        await closePanel.click();
        await page.getByRole('button', { name: language === 'en' ? 'Map controls' : 'Controles del mapa', exact: true }).click();
      }
      await page.getByLabel(language === 'en' ? 'Time resolution' : 'Resolución temporal', { exact: true }).selectOption(code);
      if (width === 390) {
        await page.getByRole('button', { name: language === 'en' ? 'Close controls' : 'Cerrar controles', exact: true }).click();
        await page.locator('.maplibregl-marker').first().click();
      }
    };
    await page.locator('.maplibregl-marker').first().focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('.hero-value')).toHaveText(language === 'es' ? '4,9' : '4.9');
    await expect(page.getByText(language === 'en' ? 'Observed at (UTC)' : 'Observado el (UTC)', { exact: true })).toBeVisible();
    await expect(page.locator('.panel-chart-container canvas')).toBeVisible();
    await capture('native');
    for (const code of ['1h', '24h', 'rolling_24h', '2m']) {
      await selectResolution(code);
      await expect(page.locator('.hero-value')).toHaveText((language === 'es'
        ? { '2m': '4,9', '1h': '12,5', '24h': '22,5', rolling_24h: '32,5' }
        : { '2m': '4.9', '1h': '12.5', '24h': '22.5', rolling_24h: '32.5' })[code]);
      await expect(page.getByRole('heading', { name: device.name, exact: true })).toBeVisible();
      await expect(page.locator('.hero-unit')).toHaveText('µg/m³');
      if (code === 'rolling_24h') {
        await expect(page.getByText(language === 'en' ? 'Calculated at (UTC)' : 'Calculado el (UTC)', { exact: true })).toBeVisible();
        await expect(page.getByText(language === 'en' ? 'Observed at (UTC)' : 'Observado el (UTC)', { exact: true })).toHaveCount(0);
        await expect(page.locator('.map-measurement-context time').last()).toHaveAttribute('datetime', '2026-10-09T04:00:00.000Z');
        await expect(page.locator('.panel-chart-container [role=alert]')).toContainText(language === 'en' ? 'latest results only' : 'resultados recientes');
        expect(historyRequests).not.toContain('rolling_24h');
      } else {
        await expect(page.locator('.panel-chart-container canvas')).toBeVisible();
        await expect.poll(async () => (await chartState(page.locator('.panel-chart-container canvas')))?.value).toBe(values[code]);
        expect(historyRequests.at(-1)).toBe(code);
      }
      await capture(code);
    }
    // Desktop retains the selected sensor through a missing response and refresh.
    // Mobile preserves its established modal interaction: close details to use Map controls.
    if (width === 1440) {
      unavailable = true;
      await selectResolution('1h');
      await page.getByRole('button', { name: language === 'en' ? 'Refresh now' : 'Actualizar ahora', exact: true }).click();
      await expect(page.getByText(language === 'en'
        ? 'No measurement available for this sensor with the selected filters.'
        : 'No hay mediciones disponibles para este sensor con los filtros seleccionados.', { exact: true })).toBeVisible();
      await expect(page.locator('.hero-value')).toHaveCount(0);
      await capture('unavailable');
      unavailable = false;
      refreshed = true;
      await page.getByRole('button', { name: language === 'en' ? 'Refresh now' : 'Actualizar ahora', exact: true }).click();
      await expect(page.locator('.hero-value')).toHaveText(language === 'es' ? '6,1' : '6.1');
      await expect(page.locator('.panel-chart-container canvas')).toBeVisible();
      await capture('refreshed');
    } else {
      await closePanel.click();
      unavailable = true;
      await page.getByRole('button', { name: language === 'en' ? 'Refresh now' : 'Actualizar ahora', exact: true }).click();
      await expect(page.getByTestId('map-empty-state')).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath('unavailable.png'), animations: 'disabled' });
    }
  });
}
