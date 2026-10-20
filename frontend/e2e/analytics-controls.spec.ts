import { test, expect } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import { standards, aqiHistory } from './fixtures/uxAnalytics';

// Deliberately synthetic responses exercise failures without changing application data.
for (const language of ['en', 'es']) for (const width of [1440, 1200, 390]) for (const colorScheme of ['light', 'dark'] as const) {
  test(`Analytics controls ${language} ${width} ${colorScheme}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ colorScheme });
    await mockAdministration(page, language);
    const es = language === 'es';
    const device = { device_id: 1, name: 'Synthetic PM2.5 station', friendly_name: null, timezone: 'America/New_York', sensor_count: 1 };
    const latest = [{ sensor_id: 10, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³', value: 20,
      observed_at: '2026-08-01T02:00:00Z', device, sensor_aggregation_period: '1h' }];
    let discoveryState: 'success' | 'empty' | 'error' | 'loading' = 'success';
    let releaseDiscovery: (() => void) | undefined;
    const requests: URL[] = [];
    await page.route('**/api/measurement-aggregation-capabilities*', route => route.fulfill({ json: [{
      parameter_code: 'pm25', native_aggregation_code: '1h', native_status: 'known',
      supported_aggregations: ['1h', '24h'].map((code, index) => ({ result_aggregation_code: code,
        duration_minutes: index ? 1440 : 60, capability_kind: index ? 'direct_rollup' : 'native', supports_history: true, supports_latest: true })),
    }] }));
    await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: [device] }));
    await page.route('**/api/air-quality-index/standards', route => route.fulfill({ json: standards }));
    await page.route('**/api/air-quality-index/analytics-history', route => route.fulfill({ json: {
      ...aqiHistory, requested_series_count: 1, returned_series_count: 1, series: [aqiHistory.series[0]],
    } }));
    await page.route('**/api/measurements/pm25/latest*', async route => {
      if (discoveryState === 'loading') await new Promise<void>(resolve => { releaseDiscovery = resolve; });
      if (discoveryState === 'error') return route.fulfill({ status: 503, json: { detail: 'Synthetic failure' } });
      return route.fulfill({ json: discoveryState === 'empty' ? [] : latest });
    });
    await page.route('**/api/sensors/10/history*', route => {
      const url = new URL(route.request().url()); requests.push(url);
      return route.fulfill({ json: { sensor_id: 10, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³',
        device_name: device.name, device_timezone: device.timezone, data: [10, 20].map((value, index) => ({
          value, timestamp: new Date(Date.parse(url.searchParams.get('start')!) + (index + 1) * 3600000).toISOString(), is_valid: true,
        })) } });
    });
    const capture = async (name: string) => {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      for (const dialog of await page.locator('dialog[open]').all()) {
        expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
      }
      await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true });
    };
    await page.goto('/analytics?start=2026-08-01T00:00:00Z&end=2026-08-02T00:00:00Z');
    const dialog = page.getByRole('dialog');
    const measurement = dialog.getByRole('button', { name: es ? 'Medición' : 'Measurement', exact: true });
    const aqi = dialog.getByRole('button', { name: 'AQI', exact: true });
    const load = dialog.getByRole('button', { name: es ? 'Cargar sensores' : 'Load Sensors', exact: true });
    await dialog.getByRole('button', { name: es ? 'Cancelar' : 'Cancel', exact: true }).click();
    await capture('initial-page');
    await page.getByRole('button', { name: es ? 'Seleccionar flujo de datos' : 'Select Data Stream', exact: true }).first().click();
    await expect(measurement).toHaveAttribute('aria-pressed', 'true');
    await expect(aqi).toHaveAttribute('aria-pressed', 'false');
    const close = dialog.getByRole('button', { name: es ? 'Cerrar modal' : 'Close modal', exact: true });
    await close.focus(); await page.keyboard.press('Shift+Tab');
    await expect(dialog.getByRole('button', { name: es ? 'Cancelar' : 'Cancel', exact: true })).toBeFocused();
    await page.keyboard.press('Tab'); await expect(close).toBeFocused();
    await expect(load).toBeDisabled();
    for (const button of [measurement, aqi]) expect(await button.evaluate(el => getComputedStyle(el).borderWidth)).toBe('0px');
    const radios = dialog.getByRole('radio');
    await expect(radios.first()).toBeChecked();
    await expect(radios.nth(1)).not.toBeChecked();
    expect(await radios.nth(1).evaluate(el => getComputedStyle(el).colorScheme)).toBe('light');
    await radios.first().focus(); await page.keyboard.press('ArrowRight');
    await expect(radios.nth(1)).toBeChecked();
    await page.keyboard.press('ArrowLeft');
    await capture('measurement-selected-aqi-unselected');
    await aqi.focus(); await page.keyboard.press('Enter');
    await expect(aqi).toHaveAttribute('aria-pressed', 'true');
    await expect(measurement).toHaveAttribute('aria-pressed', 'false');
    await capture('aqi-selected-measurement-unselected');
    await measurement.focus(); await page.keyboard.press('Space');
    await dialog.locator('select').first().selectOption('pm25');
    discoveryState = 'loading'; await load.click();
    await expect(dialog.getByRole('status')).toBeVisible();
    await dialog.getByRole('status').scrollIntoViewIfNeeded();
    await capture('loading');
    await expect.poll(() => !!releaseDiscovery).toBe(true);
    discoveryState = 'empty'; releaseDiscovery!();
    await expect(dialog.getByText(es ? /No se encontraron flujos/ : /No data streams found/)).toBeVisible();
    await dialog.getByText(es ? /No se encontraron flujos/ : /No data streams found/).scrollIntoViewIfNeeded();
    await capture('empty');
    discoveryState = 'error'; await load.click();
    await expect(dialog.getByRole('alert')).toBeVisible();
    await dialog.getByRole('alert').scrollIntoViewIfNeeded();
    await capture('error-retry');
    discoveryState = 'success';
    await dialog.getByRole('button', { name: es ? 'Reintentar' : 'Retry', exact: true }).click();
    await dialog.getByRole('button', { name: /Synthetic PM2.5 station/ }).click();
    await expect(dialog).toBeHidden();
    expect(new URL(page.url()).searchParams.getAll('series')).toHaveLength(1);
    await expect(page.locator('canvas')).toBeVisible();
    await capture('selected-stream');
    const dates = page.locator('main input[type="datetime-local"]');
    await expect(dates).toHaveCount(2);
    await expect(dates.first()).toHaveValue('2026-07-31T20:00');
    await page.locator('main select').first().selectOption('utc');
    await dates.first().fill('2026-08-01T06:00');
    await dates.nth(1).fill('2026-08-02T06:00');
    await expect.poll(() => requests.at(-1)?.searchParams.get('start')).toBe('2026-08-01T06:00:00.000Z');
    await expect.poll(() => requests.at(-1)?.searchParams.get('end')).toBe('2026-08-02T06:00:00.000Z');
    await expect(page.getByRole('button', { name: /Open date range picker|Abrir selector de rango/ })).toHaveCount(0);
    await capture('date-controls');
    await dates.first().fill('2026-08-02T06:00');
    await expect(page.getByRole('alert')).toContainText(es ? 'anterior al fin' : 'before End');
    await dates.first().fill('2026-08-01T06:00');
    const selectStream = page.getByRole('button', { name: es ? 'Seleccionar flujo de datos' : 'Select Data Stream', exact: true });
    await selectStream.click(); await load.click();
    await expect(dialog.getByRole('button', { name: /Synthetic PM2.5 station/ })).toBeDisabled();
    await dialog.locator('select').last().selectOption('24h');
    await dialog.getByRole('button', { name: /Synthetic PM2.5 station/ }).click();
    await expect(page).toHaveURL(/24h/);
    await expect.poll(() => requests.some(url => url.searchParams.get('aggregation') === '24h')).toBe(true);
    expect(new URL(page.url()).searchParams.getAll('series')).toHaveLength(2);
    await selectStream.click(); await aqi.click();
    await dialog.getByRole('button', { name: /Synthetic PM2.5 station/ }).click();
    await expect(page).toHaveURL(/aqi/);
    expect(new URL(page.url()).searchParams.getAll('series')).toHaveLength(3);
    await capture('measurement-and-aqi');
  });
}

test('AQI discovery recovery, empty catalog, and language changes preserve selection', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 1000 });
  await mockAdministration(page, 'en');
  await page.route('**/api/measurement-aggregation-capabilities*', route => route.fulfill({ json: [{
    parameter_code: 'pm25', native_aggregation_code: '1h', supported_aggregations: [{
      result_aggregation_code: '1h', duration_minutes: 60, capability_kind: 'native', supports_history: true,
    }],
  }] }));
  const user = { user_id: 'review-admin', email: 'administrator@example.org', display_name: 'Synthetic Analyst',
    roles: ['admin'], scopes: ['users:write'], is_active: true, preferred_language_code: 'en', system_default_language_code: 'en' };
  await page.route('**/api/auth/me', route => route.fulfill({ json: user }));
  await page.route('**/api/auth/me/preferences', route => route.fulfill({ json: {
    ...user, preferred_language_code: route.request().postDataJSON().preferred_language_code,
  } }));
  let fail = true;
  let empty = false;
  let release: (() => void) | undefined;
  await page.route('**/api/air-quality-index/standards', route => route.fulfill({ json: standards }));
  await page.route(/\/api\/devices(?:\?.*)?$/, async route => {
    if (fail) await new Promise<void>(resolve => { release = resolve; });
    return route.fulfill(fail ? { status: 503, json: { detail: 'Synthetic catalog failure' } } : { json: empty ? [] : [{
      device_id: 1, name: 'Synthetic AQI station', timezone: 'UTC', sensor_count: 1,
    }] });
  });
  await page.goto('/analytics');
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'AQI', exact: true }).click();
  await expect(dialog.getByRole('status')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('aqi-loading.png'), fullPage: true });
  await expect.poll(() => !!release).toBe(true); release!();
  const retry = dialog.getByRole('button', { name: /Retry/ });
  await expect(retry).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('aqi-error.png'), fullPage: true });
  fail = false; empty = true; await retry.click();
  await expect(dialog.getByText('No AQI-capable devices match these filters.')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('aqi-empty.png'), fullPage: true });
  empty = false; await page.reload();
  await dialog.getByRole('button', { name: 'AQI', exact: true }).click();
  await expect(dialog.getByRole('button', { name: /Synthetic AQI station/ })).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  for (const language of ['es', 'en']) {
    await page.locator('.user-menu__trigger').click();
    await page.locator('#account-language-selector').selectOption(language);
    await expect(page.locator('html')).toHaveAttribute('lang', language);
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: language === 'es' ? 'Seleccionar flujo de datos' : 'Select Data Stream', exact: true }).first().click();
    await expect(dialog.getByRole('button', { name: 'AQI', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(dialog.getByRole('button', { name: /Synthetic AQI station/ })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`language-switch-${language}.png`), fullPage: true });
    await dialog.getByRole('button', { name: language === 'es' ? 'Medición' : 'Measurement', exact: true }).click();
    await expect(dialog.locator('select').nth(1).locator('option[value="1h"]')).toHaveText(language === 'es' ? 'Promedio de 1 hora' : '1-hour average');
    await dialog.getByRole('button', { name: 'AQI', exact: true }).click();
    await dialog.getByRole('button', { name: language === 'es' ? 'Cancelar' : 'Cancel', exact: true }).click();
  }
});
