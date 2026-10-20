import { expect, test } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import { mapCamera } from './fixtures/map-camera';

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`Map attribution strips consecutive event attributes ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await mockAdministration(page, language);
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = () => {};
    }, language);
    await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
      version: 8,
      sources: {
        synthetic: {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [0, 0] } }] },
          attribution: '<details open onload="0" ontoggle="document.body.dataset.syntheticAttributionEvent = 1">Synthetic attribution regression</details>',
        },
      },
      layers: [
        { id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } },
        { id: 'synthetic', type: 'circle', source: 'synthetic', paint: { 'circle-radius': 4 } },
      ],
    } }));
    await page.goto('/map');
    await expect(page.locator('.maplibregl-canvas')).toBeVisible();
    await expect.poll(async () => (await mapCamera(page)).loaded).toBe(true);
    expect((await mapCamera(page)).renderedFeatures).toBeGreaterThan(0);
    const attribution = page.locator('.maplibregl-ctrl-attrib-inner details');
    await expect(attribution).toHaveText('Synthetic attribution regression');
    await expect(attribution).toHaveAttribute('open', '');
    expect(await attribution.evaluate(element => element.getAttributeNames().filter(name => name.startsWith('on')))).toEqual([]);
    await expect(page.locator('body')).not.toHaveAttribute('data-synthetic-attribution-event');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('sanitized-attribution.png') });
  });
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`Map explains unavailable WebGL2 and preserves navigation ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await mockAdministration(page, language);
    const pageErrors: string[] = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = () => {};
      const getContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (contextId: string, ...args: unknown[]) {
        if (contextId === 'webgl2') return null;
        return Reflect.apply(getContext, this, [contextId, ...args]);
      };
    }, language);
    await page.goto('/map');
    const message = page.locator('.map-error[role="alert"]');
    await expect(message).toContainText(language === 'en' ? 'cannot use WebGL2' : 'no puede usar WebGL2');
    await expect(page.locator('.map-loading, .map-legend-container')).toHaveCount(0);
    await expect(page.getByTestId('map-empty-state')).toHaveCount(0);
    await expect(page.locator('.maplibregl-canvas')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('webgl2-unavailable.png') });
    if (width === 390) await page.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
    await page.locator('.map-layer-control select').selectOption('measurements');
    await expect(message).toBeAttached();
    await page.locator('.map-download summary').click();
    await expect(page.getByRole('button', { name: /^(Download CSV|Descargar CSV)$/ })).toBeVisible();
    await page.locator('a[href^="/analytics"]').first().click();
    await expect(page).toHaveURL(/\/analytics/);
    expect(pageErrors).toEqual([]);
  });
}
