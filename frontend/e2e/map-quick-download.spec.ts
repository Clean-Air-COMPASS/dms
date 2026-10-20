import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const measurementHeader = 'Measurement ID,Sensor ID,External Sensor ID,Parameter,Parameter Name,Value,Unit,Observed At (UTC),Device ID,Device Name,Latitude,Longitude,Data Provider,Contributor,Contributor URL,Provider URL,License,License URL';
const deviceHeader = 'Device ID,Device Name,Friendly Name,External Device ID,Data Provider,Latitude,Longitude,Timezone,Sensor Count';

async function downloadCsv(page: Page) {
  const downloadPromise = page.waitForEvent('download');
  const button = page.getByRole('button', { name: /^(Download CSV|Descargar CSV)$/ });
  await button.focus();
  await button.press('Enter');
  const download = await downloadPromise;
  const bytes = await readFile((await download.path())!);
  expect([...bytes.subarray(0, 3)]).toEqual([239, 187, 191]);
  return { filename: download.suggestedFilename(), lines: bytes.toString('utf8').replace(/^\uFEFF/, '').split('\n') };
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`Map device inventory and complete measurement export ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = () => {};
    }, language);
    const devices = [
      { device_id: 1, name: 'Synthetic Estación Niño', friendly_name: 'Área Norte', external_id: 'site-1', network: 'Other', latitude: 38.5, longitude: -122.8, timezone: 'UTC', sensor_count: 135, parameters: ['pm25'] },
      { device_id: 2, name: 'Synthetic no observations', network: 'Fixture Provider', latitude: null, longitude: null, sensor_count: 1, parameters: ['pm10'] },
      { device_id: 3, name: 'Synthetic second provider', network: 'Fixture Provider', latitude: 38.6, longitude: -122.9, sensor_count: 100, parameters: ['pm25'] },
    ];
    const exportRequests: URL[] = [];
    let failSecondPage = false;
    let releasePage!: () => void;
    const pendingPage = new Promise<void>(resolve => { releasePage = resolve; });
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url());
      const path = url.pathname.replace(/^\/api/, '');
      if (path === '/data-sources') {
        await route.fulfill({ json: [{ name: 'Other', filter_value: 'other' }, { name: 'Fixture Provider', filter_value: 'fixture provider' }] });
      } else if (path === '/measurement-aggregation-capabilities') {
        await route.fulfill({ json: ['pm25', 'pm10'].map(parameter_code => ({
          parameter_code, native_aggregation_code: '1h', native_status: 'known',
          supported_aggregations: ['1h', '24h'].map(code => ({ result_aggregation_code: code, display_name: code,
            duration_minutes: code === '1h' ? 60 : 1440, is_rolling: false, capability_kind: 'native',
            rollup_path: [code], supports_latest: true, supports_history: true, formatting_status: 'not_configured' })),
        })) });
      } else if (path === '/devices') {
        const filtered = devices.filter(device => (!url.searchParams.get('parameter') || device.parameters.includes(url.searchParams.get('parameter')!))
          && (!url.searchParams.get('external_api_name') || device.network.toLowerCase() === url.searchParams.get('external_api_name')));
        await route.fulfill({ json: filtered });
      } else if (/^\/measurements\/.+\/latest$/.test(path)) {
        const source = url.searchParams.get('external_api_name');
        const resolution = url.searchParams.get('aggregation');
        const rows = Array.from({ length: 235 }, (_, index) => ({
          measurement_id: index + 1, sensor_id: index + 1, external_sensor_id: `synthetic-${index + 1}`,
          parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³', value: resolution === '24h' ? 24 : 1,
          observed_at: '2020-01-01T00:00:00Z', result_aggregation_code: resolution || '1h',
          device: devices[index < 135 ? 0 : 2],
        })).filter(row => !source || row.device.network.toLowerCase() === source);
        if (url.searchParams.has('offset')) {
          exportRequests.push(url);
          const offset = Number(url.searchParams.get('offset'));
          if (offset === 100 && failSecondPage) await pendingPage;
          if (offset === 100 && failSecondPage) {
            await route.fulfill({ status: 502, json: { detail: 'Synthetic later-page failure' } });
            return;
          }
          await route.fulfill({ json: rows.slice(offset, offset + 100) });
        } else await route.fulfill({ json: rows });
      } else await route.continue();
    });
    await page.goto('/map');
    await expect(page.locator('.maplibregl-canvas')).toBeVisible();
    if (width === 390) await page.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
    await page.locator('.map-download summary').click();
    const explanation = page.locator('.map-download-panel p');
    await expect(explanation).toContainText(language === 'en' ? 'device inventory' : 'inventario de dispositivos');
    const allDevices = await downloadCsv(page);
    expect(allDevices.filename).toMatch(/^compassaq-devices-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(allDevices.lines[0]).toBe(deviceHeader);
    expect(allDevices.lines).toHaveLength(4);
    expect(allDevices.lines.join('\n')).toContain('Synthetic Estación Niño,Área Norte');
    expect(allDevices.lines.join('\n')).toContain('Synthetic no observations');
    await page.locator('.map-parameter-control select').selectOption('pm25');
    await page.locator('.map-source-control select').selectOption('other');
    await expect(page.locator('.map-loading')).toBeHidden();
    await expect(explanation).toContainText('PM2.5');
    await expect(explanation).toContainText('Other');
    const filteredDevices = await downloadCsv(page);
    expect(filteredDevices.lines).toHaveLength(2);
    expect(filteredDevices.lines[1]).toMatch(/^1,Synthetic Estación Niño,/);
    await page.screenshot({ path: testInfo.outputPath('device-export.png'), fullPage: true });
    await page.locator('.map-parameter-control select').selectOption('pm10');
    await page.getByRole('button', { name: /^(Download CSV|Descargar CSV)$/ }).click();
    await expect(page.locator('.map-download [role=alert]')).toContainText(language === 'en' ? 'No records match' : 'No hay registros');
    await page.screenshot({ path: testInfo.outputPath('export-empty.png'), fullPage: true });

    await page.locator('.map-layer-control select').selectOption('measurements');
    await page.locator('.map-source-control select').selectOption('');
    await page.locator('.map-time-resolution-control select').selectOption('1h');
    await expect(page.locator('.map-loading')).toBeHidden();
    await expect(explanation).toContainText(language === 'en' ? 'every sensor' : 'cada sensor');
    await expect(explanation).not.toContainText('100');
    exportRequests.length = 0;
    const allMeasurements = await downloadCsv(page);
    expect(allMeasurements.lines[0]).toBe(measurementHeader);
    expect(allMeasurements.lines).toHaveLength(236);
    expect(new Set(allMeasurements.lines.slice(1).map(line => line.split(',')[1])).size).toBe(235);
    expect(exportRequests.map(url => url.searchParams.get('offset'))).toEqual(['0', '100', '200']);
    await page.locator('.map-source-control select').selectOption('other');
    await page.locator('.map-time-resolution-control select').selectOption('24h');
    await expect(page.locator('.map-loading')).toBeHidden();
    exportRequests.length = 0;
    const filteredMeasurements = await downloadCsv(page);
    expect(filteredMeasurements.lines).toHaveLength(136);
    for (const line of filteredMeasurements.lines.slice(1)) {
      const fields = line.split(',');
      expect(fields[5]).toBe('24');
      expect(fields[12]).toBe('Other');
    }
    for (const url of exportRequests) {
      expect(url.pathname).toMatch(/\/measurements\/pm25\/latest$/);
      expect(url.searchParams.get('external_api_name')).toBe('other');
      expect(url.searchParams.get('aggregation')).toBe('24h');
      expect(url.searchParams.has('bbox')).toBe(false);
      expect(url.searchParams.has('since')).toBe(false);
    }
    await page.screenshot({ path: testInfo.outputPath('measurement-export.png'), fullPage: true });
    failSecondPage = true;
    let downloaded = false;
    page.on('download', () => { downloaded = true; });
    await page.getByRole('button', { name: /^(Download CSV|Descargar CSV)$/ }).click();
    await expect(page.locator('.quick-download-btn')).toBeDisabled();
    await expect(page.locator('.map-download [role=status]')).toContainText(language === 'en' ? 'Downloading CSV' : 'Descargando CSV');
    await page.screenshot({ path: testInfo.outputPath('export-loading.png'), fullPage: true });
    releasePage();
    await expect(page.locator('.map-download [role=alert]')).toContainText(language === 'en' ? 'No file was downloaded' : 'No se descargó ningún archivo');
    expect(downloaded).toBe(false);
    await expect(page.locator('.quick-download-btn')).toBeEnabled();
    await page.screenshot({ path: testInfo.outputPath('export-error.png'), fullPage: true });
    failSecondPage = false;
    const retry = await downloadCsv(page);
    expect(retry.lines).toHaveLength(136);
    await expect(page.locator('.map-download [role=alert]')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    for (const dialog of await page.locator('dialog[open]').all()) {
      expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    }
    await page.locator('.map-layer-control select').selectOption('aqi');
    await expect(page.locator('.map-download')).toHaveCount(1);
    await expect(page.locator('.maplibregl-canvas')).toHaveCount(1);
  });
}
