import { expect, test } from '@playwright/test';
import { expectGeographyFillsCanvas, mapCamera } from './fixtures/map-camera';

test.beforeEach(({ page }) => { page.setDefaultTimeout(20000); });

for (const language of ['en', 'es']) for (const width of [1920, 1440, 1200, 1024, 768, 390]) {
  test(`real Map viewport and toolbar ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = () => {};
    }, language);
    await page.goto('/map');
    await expect(page.locator('.map-loading')).toBeHidden();
    await expectGeographyFillsCanvas(page);
    if (width <= 768) {
      const status = (await page.locator('.map-legend-container').boundingBox())!;
      const attribution = (await page.locator('.maplibregl-ctrl-attrib').boundingBox())!;
      expect(status.y + status.height).toBeLessThanOrEqual(attribution.y);
    }
    await page.screenshot({ path: testInfo.outputPath('initial-map.png') });
    await mapCamera(page, 'jump', 0, 0, -2);
    await expectGeographyFillsCanvas(page);
    const global = await mapCamera(page);
    if (width >= 1440) expect(global.width / global.worldWidth).toBeGreaterThan(1.4);
    await page.screenshot({ path: testInfo.outputPath('fully-zoomed-out.png') });
    for (const layer of ['devices', 'measurements', 'aqi']) {
      if (width <= 768) await page.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
      await page.locator('.map-layer-control select').selectOption(layer);
      if (layer === 'aqi') await page.locator('.aqi-product-control select').selectOption('eea_european.overall.hourly');
      await expect(page.locator('.map-loading')).toBeHidden();
      const search = page.locator('.location-search input');
      const bounds = (await search.boundingBox())!;
      if (width > 768) {
        expect(bounds.width).toBeGreaterThanOrEqual(280);
        expect(bounds.width).toBeLessThanOrEqual(360);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      // Test selected labels rather than merely testing element bounds.
      for (const select of await page.locator('.overlay-controls select').all()) {
        const fits = await select.evaluate(el => {
          const input = el as HTMLSelectElement;
          const style = getComputedStyle(input);
          const ctx = document.createElement('canvas').getContext('2d')!;
          ctx.font = style.font;
          return ctx.measureText(input.selectedOptions[0]?.text || '').width
            <= input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        });
        expect(fits).toBe(true);
      }
      await page.screenshot({ path: testInfo.outputPath(`${layer}-toolbar.png`) });
      if (width <= 768) await page.getByRole('button', { name: /^(Close controls|Cerrar controles)$/ }).click();
    }
    await mapCamera(page, 'jump', 179, 0, 2);
    await mapCamera(page, 'pan', 600);
    expect((await mapCamera(page)).lng).toBeCloseTo(-75.53125, 2);
    await mapCamera(page, 'pan', -1800);
    expect((await mapCamera(page)).lng).toBeCloseTo(-31.9375, 2);
    await expectGeographyFillsCanvas(page);
    await page.screenshot({ path: testInfo.outputPath('antimeridian.png') });
    await mapCamera(page, 'jump', -0.12, 51.5, 10);
    await expectGeographyFillsCanvas(page);
    await page.screenshot({ path: testInfo.outputPath('city.png') });
    await page.getByRole('button', { name: 'Zoom out', exact: true }).click();
    await expect.poll(async () => (await mapCamera(page)).zoom).toBeCloseTo(9, 1);
    await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
    await expect.poll(async () => (await mapCamera(page)).zoom).toBeCloseTo(10, 1);
    await expect(page.locator('.maplibregl-ctrl-attrib')).toBeVisible();
  });
}

for (const permission of ['allowed', 'denied', 'unanswered']) {
  test(`Analytics restores Map camera with geolocation ${permission}`, async ({ page }, testInfo) => {
    await page.addInitScript(state => {
      localStorage.setItem('compassaq.language', 'en');
      navigator.geolocation.getCurrentPosition = (success, failure) => {
        if (state === 'allowed') success({ coords: { latitude: 14.6, longitude: 120.98 } } as GeolocationPosition);
        if (state === 'denied') failure?.({ code: 1 } as GeolocationPositionError);
      };
    }, permission);
    await page.goto('/map?lat=51.5&lng=-0.12&zoom=10&parameter=pm25');
    await expectGeographyFillsCanvas(page);
    expect((await mapCamera(page)).lng).toBeCloseTo(-0.12, 2);
    await page.getByRole('link', { name: 'Analytics', exact: true }).click();
    await expect(page.locator('dialog[open]')).toBeVisible();
    await page.keyboard.press('Escape');
    await page.getByRole('link', { name: 'Map', exact: true }).click();
    await expectGeographyFillsCanvas(page);
    expect((await mapCamera(page)).lng).toBeCloseTo(-0.12, 2);
    expect((await mapCamera(page)).lat).toBeCloseTo(51.5, 2);
    await page.screenshot({ path: testInfo.outputPath('analytics-return.png') });
    await page.getByRole('button', { name: 'Reset view', exact: true }).click();
    await expect.poll(async () => (await mapCamera(page)).lng).toBeCloseTo(permission === 'allowed' ? 120.98 : 0, 2);
    await expect.poll(async () => (await mapCamera(page)).zoom).toBeCloseTo(permission === 'allowed' ? 10 : 2, 2);
  });
}

test('live Geoapify London and San Luis Obispo searches, clear, marker and sidebar', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem('compassaq.language', 'en');
    navigator.geolocation.getCurrentPosition = () => {};
  });
  await page.goto('/map');
  await expectGeographyFillsCanvas(page);
  for (const place of [
    { query: 'London', option: /Greater London/, lng: -0.13, lat: 51.51 },
    { query: 'San Luis Obispo', option: /San Luis Obispo/, lng: -120.66, lat: 35.28 },
  ]) {
    const response = page.waitForResponse(response => response.url().includes('/geocode/autocomplete'));
    await page.getByRole('combobox', { name: 'Search location', exact: true }).fill(place.query);
    const { results } = await (await response).json() as { results: { name: string; result_type: string }[] };
    const cityIndex = results.findIndex(result => result.result_type === 'city' && place.option.test(result.name));
    expect(cityIndex).toBeGreaterThanOrEqual(0);
    await page.getByRole('option').nth(cityIndex).click();
    await expect.poll(async () => (await mapCamera(page)).lng).toBeCloseTo(place.lng, 1);
    await expect.poll(async () => (await mapCamera(page)).lat).toBeCloseTo(place.lat, 1);
    await expectGeographyFillsCanvas(page);
    await page.screenshot({ path: testInfo.outputPath(`${place.query.replaceAll(' ', '-')}.png`) });
    await page.getByRole('button', { name: 'Clear search', exact: true }).click();
    await expect(page.getByRole('combobox', { name: 'Search location', exact: true })).toHaveValue('');
    expect((await mapCamera(page)).lng).toBeCloseTo(place.lng, 1);
  }
  await page.getByRole('button', { name: 'Reset view', exact: true }).click();
  await expect.poll(async () => (await mapCamera(page)).zoom).toBeCloseTo(2, 1);
  // Reveal northern devices that sit behind the toolbar at the equatorial Reset camera.
  await page.getByRole('button', { name: 'Zoom out', exact: true }).click();
  await expect.poll(async () => (await mapCamera(page)).zoom).toBeCloseTo(1, 1);
  const marker = page.locator('[data-map-marker-key]').first();
  await expect(marker).toBeInViewport();
  await marker.click();
  await expect(page.locator('.slide-out-panel.open')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('device-sidebar.png') });
  await page.keyboard.press('Escape');
  await expect(page.locator('.slide-out-panel.open')).toHaveCount(0);
});

for (const timing of ['immediate', 'late']) {
  test(`Analytics AQI device target beats ${timing} geolocation`, async ({ page }, testInfo) => {
    await page.addInitScript(state => {
      localStorage.setItem('compassaq.language', 'en');
      navigator.geolocation.getCurrentPosition = success => {
        const locate = () => success({ coords: { latitude: 14.6, longitude: 120.98 } } as GeolocationPosition);
        if (state === 'immediate') locate();
        else (window as unknown as { locate: () => void }).locate = locate;
      };
    }, timing);
    const device = { device_id: 901, name: 'Synthetic London target', sensor_count: 1, friendly_name: 'Synthetic London target', longitude: -0.12, latitude: 51.5, timezone: 'Europe/London' };
    await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: [device] }));
    await page.route('**/api/air-quality-index/eea_european/latest**', route => route.fulfill({ json: {
      standard_code: 'eea_european', count: 1, results: [{ device_id: 901, device_name: device.name,
        longitude: -0.12, latitude: 51.5, standard_code: 'eea_european', product_code: 'eea_european.overall.hourly',
        result_kind: 'categorical', category_code: 'fair', category_label: 'Fair', eligibility_status: 'eligible',
        observed_at: '2026-10-07T12:00:00Z', dominant_pollutants: ['pm25'], pollutant_results: [], exclusion_reasons: [], sensor_provenance: [],
        coverage: { coverage_status: 'partial', available_pollutants: ['pm25'], missing_pollutants: ['no2'], ineligible_pollutants: [], missing_or_ineligible_pollutants: ['no2'] },
      }],
    } }));
    await page.goto('/analytics?series=aqi%7Ceea_european%7Ceea_european.overall.hourly%7C901');
    await page.getByRole('link', { name: 'View primary on Map', exact: true }).click();
    await expect(page).toHaveURL(/device_id=901/);
    await expect.poll(async () => (await mapCamera(page)).lng).toBeCloseTo(-0.12, 2);
    await expect(page.locator('.slide-out-panel.open')).toContainText('Synthetic London target');
    if (timing === 'late') await page.evaluate(() => (window as unknown as { locate: () => void }).locate());
    await expectGeographyFillsCanvas(page);
    expect((await mapCamera(page)).lng).toBeCloseTo(-0.12, 2);
    await page.screenshot({ path: testInfo.outputPath('analytics-device-target.png') });
  });
}


for (const width of [1440, 390]) {
  test(`empty Map retains full geography at ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => { navigator.geolocation.getCurrentPosition = () => {}; });
    await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: [] }));
    await page.goto('/map');
    await expect(page.getByTestId('map-empty-state')).toBeVisible();
    await expectGeographyFillsCanvas(page);
    await page.screenshot({ path: testInfo.outputPath('empty-global.png') });
    // Canvas constraints are recalculated when the containing block changes.
    await page.setViewportSize({ width: width === 390 ? 1440 : 390, height: 760 });
    await expectGeographyFillsCanvas(page);
  });
}

for (const permission of ['granted', 'denied']) {
  test(`native browser geolocation ${permission} cannot replace a camera URL`, async ({ page, context }) => {
    await context.setGeolocation({ longitude: 120.98, latitude: 14.6 });
    if (permission === 'granted') await context.grantPermissions(['geolocation']);
    else await context.clearPermissions();
    await page.goto('/map?lat=51.5&lng=-0.12&zoom=10');
    await expectGeographyFillsCanvas(page);
    expect((await mapCamera(page)).lng).toBeCloseTo(-0.12, 2);
    const status = await page.evaluate(() => new Promise<string>(resolve => {
      navigator.geolocation.getCurrentPosition(() => resolve('granted'), () => resolve('denied'), { timeout: 3000 });
    }));
    expect(status).toBe(permission);
    expect((await mapCamera(page)).lng).toBeCloseTo(-0.12, 2);
  });
}

test('location search timeout is recoverable without moving the real map', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem('compassaq.language', 'en');
    navigator.geolocation.getCurrentPosition = () => {};
  });
  await page.route('**/api/geocode/autocomplete**', () => {});
  await page.goto('/map?lat=51.5&lng=-0.12&zoom=10');
  await expectGeographyFillsCanvas(page);
  await page.getByRole('combobox', { name: 'Search location', exact: true }).fill('Hanging search');
  await expect(page.locator('.location-search-error')).toBeVisible({ timeout: 20000 });
  expect((await mapCamera(page)).lng).toBeCloseTo(-0.12, 2);
  await page.screenshot({ path: testInfo.outputPath('search-timeout.png') });
  await page.getByRole('button', { name: 'Clear search', exact: true }).click();
  await expect(page.locator('.location-search-error')).toBeHidden();
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect.poll(async () => (await mapCamera(page)).zoom).toBeCloseTo(11, 1);
});
