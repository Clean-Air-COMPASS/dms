import { expect, test, type Page } from '@playwright/test';

async function controls(page: Page, width: number, open: boolean) {
  if (width !== 390) return;
  await page.getByRole('button', { name: open ? /^(Map controls|Controles del mapa)$/ : /^(Close controls|Cerrar controles)$/ }).click();
}

for (const language of ['en', 'es']) for (const width of [1440, 1280, 390]) {
  test(`Map MVP controls and states ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = success => success({ coords: { latitude: 37, longitude: -122 } } as GeolocationPosition);
    }, language);
    await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
      version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
    } }));
    await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: [] }));
    await page.route(/\/api\/measurements\/[^/]+\/latest(?:\?.*)?$/, route => route.fulfill({ json: [] }));
    await page.route(/\/api\/air-quality-index\/[^/]+\/latest(?:\?.*)?$/, route => route.fulfill({ json: { results: [], count: 0 } }));
    await page.goto('/map?recency=custom&start=2020-01-01&until=2020-02-01&time_start=2019-01-01&time_end=2019-02-01');
    await expect(page.locator('.maplibregl-canvas')).toBeVisible();
    await controls(page, width, true);
    for (const layer of ['devices', 'measurements', 'aqi']) {
      const select = page.locator('.map-layer-control select');
      await select.selectOption(layer);
      await expect(page.locator('.map-time-resolution-control')).toHaveCount(layer === 'measurements' ? 1 : 0);
      await expect(page.locator('.map-recency-control, #time-window-select, .toolbar-icon-btn')).toHaveCount(0);
      const dimensions = await select.evaluate(element => {
        const input = element as HTMLSelectElement;
        const style = getComputedStyle(input);
        const context = document.createElement('canvas').getContext('2d')!;
        context.font = style.font;
        return { available: input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
          text: context.measureText(input.selectedOptions[0].textContent!).width };
      });
      expect(dimensions.available).toBeGreaterThanOrEqual(dimensions.text);
      const layerBox = (await select.boundingBox())!;
      const nextBox = (await page.locator('.map-parameter-control select').boundingBox())!;
      expect(layerBox.x + layerBox.width <= nextBox.x || layerBox.y + layerBox.height <= nextBox.y).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      for (const dialog of await page.locator('dialog[open]').all()) {
        expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
      }
      for (const key of ['recency', 'start', 'until', 'time_start', 'time_end']) expect(new URL(page.url()).searchParams.has(key)).toBe(false);
      await page.screenshot({ path: testInfo.outputPath(`${layer}-controls.png`) });
      await controls(page, width, false);
      await expect(page.getByTestId('map-empty-state')).toBeVisible();
      await expect(page.locator('.maplibregl-marker')).toHaveCount(0);
      await page.screenshot({ path: testInfo.outputPath(`${layer}-empty.png`) });
      await controls(page, width, true);
    }
  });
}


test('explicit place search keeps an empty viewport with available data elsewhere', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('compassaq.language', 'en');
    navigator.geolocation.getCurrentPosition = success => success({ coords: { latitude: 37, longitude: -122 } } as GeolocationPosition);
  });
  await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
    version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
  } }));
  await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: [{ device_id: 901, name: 'Synthetic remote station', longitude: 0, latitude: 0 }] }));
  await page.route('**/api/geocode/autocomplete**', route => route.fulfill({ json: { cached: true, results: [{ place_id: 'synthetic-empty', name: 'Synthetic empty place', formatted: 'Synthetic empty place', lat: 40, lon: 80, result_type: 'city' }] } }));
  await page.goto('/map');
  const marker = page.getByTitle('Synthetic remote station', { exact: true });
  await expect(marker).toBeInViewport();
  await page.locator('.location-search input').fill('Synthetic empty');
  await page.getByRole('option', { name: /Synthetic empty place/ }).click();
  await expect(page.getByTestId('map-empty-state')).toBeVisible();
  await expect(marker).not.toBeInViewport();
  await page.waitForTimeout(1600);
  await expect(marker).not.toBeInViewport();
});

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`shared loading and error presentation ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = success => success({ coords: { latitude: 0, longitude: 0 } } as GeolocationPosition);
    }, language);
    await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
      version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
    } }));
    let release: () => void = () => {};
    let pending = new Promise<void>(resolve => { release = resolve; });
    await page.route(/\/api\/(?:devices|measurements\/[^/]+\/latest|air-quality-index\/[^/]+\/latest)(?:\?.*)?$/, async route => {
      await pending;
      await route.fulfill({ status: 500, json: { detail: 'Synthetic acceptance failure' } });
    });
    await page.goto('/map');
    for (const layer of ['devices', 'measurements', 'aqi']) {
      if (layer !== 'devices') {
        pending = new Promise<void>(resolve => { release = resolve; });
        await controls(page, width, true);
        await page.locator('.map-layer-control select').selectOption(layer);
        await controls(page, width, false);
      }
      await expect(page.locator('.map-loading')).toHaveAttribute('role', 'status');
      await page.screenshot({ path: testInfo.outputPath(`${layer}-loading.png`) });
      release();
      await expect(page.locator('.map-error')).toHaveAttribute('role', 'alert');
      await expect(page.getByTestId('map-empty-state')).toHaveCount(0);
      await expect(page.locator('.maplibregl-marker')).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`${layer}-error.png`) });
    }
  });
}
