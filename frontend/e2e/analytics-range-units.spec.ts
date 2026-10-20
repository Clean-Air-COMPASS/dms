import { test, expect, type Page } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import { standards, aqiHistory } from './fixtures/uxAnalytics';

async function mockAnalytics(page: Page, language: string) {
  await mockAdministration(page, language);
  const requests: URL[] = [];
  const devices = [10, 11].map(id => ({ device_id: id, name: `Synthetic range station ${id}`, friendly_name: null,
    timezone: 'America/New_York', longitude: id === 10 ? 0 : 0.01, latitude: 0, sensor_count: 1 }));
  const latest = devices.map(device => ({ sensor_id: device.device_id, parameter: 'pm25', parameter_name: 'PM2.5',
    unit: 'µg/m³', value: 20, observed_at: '2026-08-01T02:00:00Z', device, sensor_aggregation_period: '1h' }));
  await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
    version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
  } }));
  await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: devices }));
  await page.route('**/api/measurement-aggregation-capabilities*', route => route.fulfill({ json: [{
    parameter_code: 'pm25', native_aggregation_code: '1h', native_status: 'known', diagnostics: [],
    supported_aggregations: [{ result_aggregation_code: '1h', display_name: 'Hourly', duration_minutes: 60,
      capability_kind: 'native', supports_history: true, supports_latest: true }],
  }] }));
  await page.route(/\/api\/measurements\/(?:pm25\/)?latest(?:\?.*)?$/, route => route.fulfill({ json: latest }));
  await page.route('**/api/devices/10/sensors*', route => route.fulfill({ json: [{ ...latest[0], latest_value: 20,
    latest_observed_at: latest[0].observed_at, native_aggregation_code: '1h', result_aggregation_code: '1h' }] }));
  await page.route('**/api/sensors/*/history*', route => {
    const url = new URL(route.request().url()); requests.push(url);
    const id = Number(url.pathname.split('/')[3]);
    return route.fulfill({ json: { sensor_id: id, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³',
      device_name: `Synthetic range station ${id}`, device_timezone: 'America/New_York', display_precision: 1,
      data: [10, 20].map((value, index) => ({ value, timestamp: new Date(Date.parse(url.searchParams.get('start') || '2026-08-01T00:00:00Z') + (index + 1) * 3600000).toISOString(), is_valid: true })) } });
  });
  await page.route('**/api/air-quality-index/standards', route => route.fulfill({ json: standards }));
  await page.route('**/api/air-quality-index/analytics-history', route => route.fulfill({ json: {
    ...aqiHistory, requested_series_count: 1, returned_series_count: 1, series: [aqiHistory.series[0]],
  } }));
  return { requests };
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`Analytics range and summary units ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const { requests } = await mockAnalytics(page, language);
    const es = language === 'es';
    const selectName = es ? 'Seleccionar flujo de datos' : 'Select Data Stream';
    const capture = async (name: string) => {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      for (const dialog of await page.locator('dialog[open]').all()) {
        expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
      }
      await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true });
    };
    await page.goto('/analytics');
    const dialog = page.getByRole('dialog', { name: selectName });
    await expect(dialog).toBeVisible();
    const modalDates = dialog.locator('input[type="datetime-local"]');
    await expect(modalDates.first()).toBeEnabled(); await expect(modalDates.nth(1)).toBeEnabled();
    await expect(modalDates.first()).not.toHaveValue('');
    await modalDates.first().fill('2026-08-01T00:00'); await modalDates.nth(1).fill('2026-08-02T00:00');
    await capture('direct-modal');
    await dialog.locator('select').first().selectOption('pm25');
    const load = dialog.getByRole('button', { name: es ? 'Cargar sensores' : 'Load Sensors', exact: true });
    await load.click();
    await dialog.getByRole('button', { name: /Synthetic range station 10/ }).click();
    await expect(dialog).toBeHidden();
    const dates = page.locator('main input[type="datetime-local"]');
    await expect(dates.first()).toHaveValue('2026-07-31T20:00'); // Device timezone, same UTC instant.
    await expect(dates.nth(1)).toBeEnabled();
    await page.locator('main select').first().selectOption('utc');
    await dates.first().fill('2026-08-01T06:00'); await dates.nth(1).fill('2026-08-02T06:00');
    await expect.poll(() => requests.at(-1)?.searchParams.get('end')).toBe('2026-08-02T06:00:00.000Z');
    await page.getByRole('button', { name: selectName, exact: true }).click();
    await expect(modalDates.first()).toHaveValue('2026-08-01T06:00');
    await load.click(); await dialog.getByRole('button', { name: /Synthetic range station 11/ }).click();
    await expect(dialog).toBeHidden();
    await expect(page.locator('canvas')).toBeVisible();
    const before = requests.length;
    await dates.first().fill('2026-08-01T07:00');
    await expect.poll(() => new Set(requests.slice(before).filter(url => url.searchParams.get('start') === '2026-08-01T07:00:00.000Z').map(url => url.pathname)).size).toBe(2);
    await expect(dates.nth(1)).toHaveValue('2026-08-02T06:00');
    await capture('measurement-multiple');
    await page.getByRole('button', { name: /(?:Remove|Eliminar).*Synthetic range station 11/ }).click();
    await expect(dates.first()).toHaveValue('2026-08-01T07:00');
    await expect(dates.nth(1)).toHaveValue('2026-08-02T06:00');
    await page.reload();
    await expect(dates.first()).toHaveValue('2026-08-01T07:00');
    await expect(page.locator('canvas')).toBeVisible();
    const latest = page.getByText(es ? 'Más reciente' : 'Latest', { exact: true }).locator('..');
    const average = page.getByText(es ? 'Promedio' : 'Average', { exact: true }).locator('..');
    const minMax = page.getByText(es ? 'Mín./Máx.' : 'Min / Max', { exact: true }).locator('..');
    await expect(latest).toContainText('µg/m³'); await expect(average).toContainText('µg/m³');
    await expect(minMax).toContainText('µg/m³'); await expect(minMax.getByText('µg/m³', { exact: true })).toHaveCount(1);
    const requestCount = requests.length;
    await dates.first().fill('2026-08-02T06:00');
    await expect(page.getByRole('alert')).toContainText(es ? 'anterior al fin' : 'before End');
    await dates.nth(1).fill('');
    await capture('invalid-range');
    expect(requests.length).toBe(requestCount);
    await dates.nth(1).fill('2026-08-03T06:00');
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect.poll(() => requests.at(-1)?.searchParams.get('end')).toBe('2026-08-03T06:00:00.000Z');

    // Follow the actual Map link, including its generated recency/default range.
    await page.goto('/map');
    const marker = page.getByTitle('Synthetic range station 10', { exact: true });
    await marker.focus(); await page.keyboard.press('Enter');
    await page.locator('.slide-out-panel.open').getByRole('link', { name: /Open Full Analytics|Abrir análisis completo/ }).click();
    await expect(page).toHaveURL(/analytics\?/);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(dates.first()).toBeEnabled(); await expect(dates.nth(1)).toBeEnabled();
    await dates.first().fill('2026-08-01T00:00');
    await expect.poll(() => requests.at(-1)?.searchParams.get('start')).toBe('2026-08-01T04:00:00.000Z');
    await capture('map-entry');

    // Scientific symbols are returned by the series, including a longer non-PM unit.
    await page.route('**/api/sensors/10/history*', route => route.fulfill({ json: {
      sensor_id: 10, parameter: 'pressure', parameter_name: 'Pressure', unit: 'kg·m⁻¹·s⁻²', device_name: 'Synthetic unit test', device_timezone: 'UTC',
      data: [{ timestamp: '2026-08-01T01:00:00Z', value: 101325, is_valid: true }],
    } }));
    await page.goto('/analytics?series=measurement%7C10%7Cpressure%7C1h&start=2026-08-01T00:00:00Z&end=2026-08-02T00:00:00Z');
    await expect(average).toContainText('kg·m⁻¹·s⁻²');
    await capture('long-unit');

    await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: aqiHistory.series.map(series => ({ device_id: series.device_id, name: `Synthetic AQI ${series.device_id}`, sensor_count: 1, timezone: 'UTC' })) }));
    const aqi = aqiHistory.series.find(series => series.result_kind === 'numeric')!;
    const query = new URLSearchParams({ series: `aqi|${aqi.standard_code}|${aqi.product_code}|${aqi.device_id}`, start: aqiHistory.range_started_at, end: aqiHistory.range_ended_at });
    await page.goto(`/analytics?${query}`);
    await expect(latest).toContainText('AQI');
    for (const card of [latest, average, minMax]) await expect(card).not.toContainText('µg/m³');
    await capture('aqi');
  });
}
