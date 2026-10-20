import { expect, test } from '@playwright/test';

import { mockAdministration } from './fixtures/administration';

const PAGE_SIZE = 20;

for (const language of ['en', 'es'] as const) {
  for (const width of [1440, 390] as const) {
    test(`CSV device reference lookup supports pagination and explicit states (${language}, ${width}px)`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await mockAdministration(page, language);

      const devices = Array.from({ length: PAGE_SIZE }, (_, index) => ({
        device_id: index + 1001,
        name: `Synthetic reference device ${String(index + 1).padStart(2, '0')}`,
        friendly_name: `First page device ${String(index + 1).padStart(2, '0')}`,
        external_id: `synthetic-external-${index + 1}`,
        external_api_id: 1,
        external_api_name: 'OpenAQ',
        network: 'OpenAQ',
        status: 'active',
        timezone: 'UTC',
        is_external: true,
        last_seen_at: null,
      }));
      devices.push({
        device_id: 1021,
        name: 'Synthetic reference device 21',
        friendly_name: 'Second page device',
        external_id: 'synthetic-external-21',
        external_api_id: 1,
        external_api_name: 'OpenAQ',
        network: 'OpenAQ',
        status: 'active',
        timezone: 'UTC',
        is_external: true,
        last_seen_at: null,
      });

      const requests: Array<{ name: string; page: number }> = [];
      await page.route(/\/api\/admin\/devices(?:\?.*)?$/, async route => {
        const url = new URL(route.request().url());
        const name = url.searchParams.get('search') ?? '';
        const apiPage = Number(url.searchParams.get('page') ?? '0');
        requests.push({ name, page: apiPage });

        if (name.toLowerCase() === 'error') {
          await route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } });
          return;
        }

        const matches = devices.filter(device => `${device.name} ${device.friendly_name}`.toLowerCase().includes(name.toLowerCase()));
        await route.fulfill({ json: matches.slice(apiPage * PAGE_SIZE, (apiPage + 1) * PAGE_SIZE) });
      });
      await page.route(/\/api\/devices\/1001\/sensors(?:\?.*)?$/, async route => {
        await route.fulfill({ json: [{
          sensor_id: 777,
          parameter_code: 'pm25',
          parameter_name: 'PM2.5',
          aggregation_code: '1h',
          external_sensor_id: 'synthetic-external-sensor-777',
          unit: 'µg/m³',
        }] });
      });

      const copy = language === 'en'
        ? {
            search: 'Device name or identifier',
            firstDevice: 'First page device 01',
            secondDevice: 'Second page device',
            pageOne: 'Page 1',
            pageTwo: 'Page 2',
            previous: 'Previous',
            next: 'Next',
            deviceId: 'Device ID: 1001',
            sensorId: 'Sensor ID: 777 · Unit: µg/m³',
            externalSensorId: 'External Sensor ID: synthetic-external-sensor-777',
            empty: 'No devices or sensors match this search.',
            error: 'Sensor reference could not be loaded. Try again.',
          }
        : {
            search: 'Nombre o identificador del dispositivo',
            firstDevice: 'First page device 01',
            secondDevice: 'Second page device',
            pageOne: 'Página 1',
            pageTwo: 'Página 2',
            previous: 'Anterior',
            next: 'Siguiente',
            deviceId: 'ID del dispositivo: 1001',
            sensorId: 'ID del sensor: 777 · Unidad: µg/m³',
            externalSensorId: 'ID externo del sensor: synthetic-external-sensor-777',
            empty: 'Ningún dispositivo o sensor coincide con esta búsqueda.',
            error: 'No se pudo cargar la referencia de sensores. Inténtelo de nuevo.',
          };

      await page.goto('/admin/uploads/csv');
      const search = page.getByRole('searchbox', { name: copy.search });
      await expect(page.getByRole('button', { name: copy.firstDevice })).toBeVisible();
      expect(requests.at(-1)).toEqual({ name: '', page: 0 });
      await page.screenshot({ path: testInfo.outputPath(`reference-page-one-${language}-${width}.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();

      await page.getByRole('button', { name: copy.next }).click();
      await expect(page.getByRole('button', { name: copy.secondDevice })).toBeVisible();
      expect(requests.at(-1)).toEqual({ name: '', page: 1 });
      await expect(page.getByText(copy.pageTwo)).toBeVisible();

      await page.getByRole('button', { name: copy.previous }).click();
      await expect(page.getByRole('button', { name: copy.firstDevice })).toBeVisible();
      expect(requests.at(-1)).toEqual({ name: '', page: 0 });
      await expect(page.getByText(copy.pageOne)).toBeVisible();

      await search.fill('reference device 01');
      await expect(page.getByRole('button', { name: copy.firstDevice })).toBeVisible();
      await expect.poll(() => requests.at(-1)).toEqual({ name: 'reference device 01', page: 0 });
      await search.fill('');
      await expect(page.getByRole('button', { name: copy.firstDevice })).toBeVisible();
      await expect.poll(() => requests.at(-1)).toEqual({ name: '', page: 0 });

      await page.getByRole('button', { name: copy.firstDevice }).click();
      await expect(page.getByText(copy.deviceId)).toBeVisible();
      await expect(page.getByText(copy.sensorId)).toBeVisible();
      await expect(page.getByText(copy.externalSensorId)).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath(`reference-success-${language}-${width}.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();

      await search.fill('no matching device');
      await expect(page.getByText(copy.empty)).toBeVisible();
      await expect(page.getByRole('alert')).toHaveCount(0);
      await page.screenshot({ path: testInfo.outputPath(`reference-empty-${language}-${width}.png`), fullPage: true });

      await search.fill('error');
      await expect(page.getByRole('alert')).toContainText(copy.error);
      await expect(page.getByText(copy.empty)).toHaveCount(0);
      await page.screenshot({ path: testInfo.outputPath(`reference-error-${language}-${width}.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    });
  }
}
