import { expect, test } from '@playwright/test';

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`Map attribution ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = success => success({ coords: { latitude: 0, longitude: 0 } } as GeolocationPosition);
    }, language);
    await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
      version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
    } }));
    let provider = 'PurpleAir';
    let optionalFields = true;
    const longUrl = `https://example.org/${'synthetic-community-monitoring-'.repeat(12)}`;
    const device = () => ({
      device_id: 901, name: `Synthetic ${provider} station`, latitude: 0, longitude: 0,
      network: provider, sensor_count: 1, timezone: 'UTC', api_key: 'synthetic-private-token',
      data_attribution: {
        data_provider_name: provider, hardware_provider_name: provider === 'AirGradient' ? 'AirGradient' : null,
        acquisition_path: provider === 'AirGradient' ? 'airgradient_public_reference' : 'unspecified',
        provider_url: optionalFields ? longUrl : null,
        contributor_name: optionalFields ? `Synthetic Community Monitoring Organization ${'LongName'.repeat(10)}` : null,
        contributor_url: optionalFields ? `${longUrl}/contributor` : null,
        license_code: optionalFields ? 'CC-BY-4.0' : null,
        license_url: optionalFields ? 'https://creativecommons.org/licenses/by/4.0/' : null,
        license_share_alike: false,
      },
    });
    const observedAt = new Date().toISOString();
    // Metadata is served locally; provider observations are exclusively synthetic.
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url());
      let json: unknown;
      if (url.pathname === '/api/devices') json = [device()];
      else if (url.pathname === '/api/devices/901/sensors') json = [{ sensor_id: 902, parameter: 'pm25', parameter_name: 'PM2.5', latest_value: 12.5, unit: 'µg/m³', latest_observed_at: observedAt, native_aggregation_code: '2m', result_aggregation_code: '2m' }];
      else if (/\/measurements\/[^/]+\/latest$/.test(url.pathname)) json = [{ measurement_id: 903, sensor_id: 902, parameter: 'pm25', value: 12.5, unit: 'µg/m³', observed_at: observedAt, device: device(), native_aggregation_code: '2m', result_aggregation_code: '2m' }];
      else if (url.pathname === '/api/sensors/902/history') json = { sensor_id: 902, parameter: 'pm25', unit: 'µg/m³', data: [], native_aggregation_code: '2m', result_aggregation_code: '2m' };
      else {
        // Use the explicitly selected test server, including its isolated API
        // proxy, rather than reading metadata from development localhost.
        const response = await route.fetch();
        await route.fulfill({ response });
        return;
      }
      await route.fulfill({ json });
    });
    for (provider of ['PurpleAir', 'OpenAQ', 'AirGradient']) {
      for (const layer of ['devices', 'measurements']) {
        await page.goto(`/map?mode=${layer === 'devices' ? 'devices' : 'pollutants'}&parameter=pm25`);
        await expect(page.locator('.maplibregl-marker').first()).toBeVisible();
        await page.locator('.maplibregl-marker').first().click();
        const section = page.getByRole('complementary', { name: language === 'en' ? 'Data attribution' : 'Atribución de datos' });
        await expect(section).toHaveCount(1);
        await section.scrollIntoViewIfNeeded();
        await expect(section).toBeVisible();
        await expect(section).toContainText(`${language === 'es' ? 'Datos proporcionados por' : 'Data provided by'} ${provider}`);
        await expect(section.getByRole('link', { name: provider, exact: true })).toHaveAttribute('href', longUrl);
        await expect(section.getByRole('link', { name: /^Synthetic Community/ })).toHaveAttribute('href', `${longUrl}/contributor`);
        await expect(section.getByRole('link', { name: 'CC-BY-4.0' })).toHaveAttribute('href', 'https://creativecommons.org/licenses/by/4.0/');
        expect(await page.locator('body').innerHTML()).not.toContain('synthetic-private-token');
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(await section.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
        if (width === 390) {
          const dialog = page.getByRole('dialog');
          await expect(dialog).toBeVisible();
          expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
        }
        await page.screenshot({ path: testInfo.outputPath(`${provider}-${layer}.png`) });
        await page.getByRole('button', { name: /^(Close panel|Cerrar panel)$/ }).click();
        await expect(section).toHaveCount(0);
      }
    }
    provider = 'PurpleAir';
    optionalFields = false;
    await page.goto('/map?mode=devices&parameter=pm25');
    await page.locator('.maplibregl-marker').first().click();
    const section = page.getByRole('complementary');
    await expect(section).toHaveText(`${language === 'es' ? 'Datos proporcionados por' : 'Data provided by'} PurpleAir.`);
    await expect(section.getByRole('link')).toHaveCount(0);
    await section.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('PurpleAir-provider-only.png') });
  });
}
