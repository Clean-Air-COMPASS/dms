import { expect, test, type Page } from '@playwright/test';

async function mockMapDependencies(page: Page, language: string) {
  await page.addInitScript((lang) => {
    localStorage.setItem('compassaq.language', lang);
    navigator.geolocation.getCurrentPosition = (_success, error) => error?.({
      code: 1,
      message: 'Synthetic test location unavailable',
      PERMISSION_DENIED: 1,
      POSITION_UNAVAILABLE: 2,
      TIMEOUT: 3,
    } as GeolocationPositionError);
  }, language);
  await page.route('**/api/health/readiness', route => route.fulfill({ json: { status: 'ready' } }));
  await page.route('**/api/setup/status', route => route.fulfill({ json: { is_setup_required: false, has_users: true } }));
  await page.route('**/api/parameters', route => route.fulfill({ json: [{ code: 'pm25', display_name: 'PM2.5' }] }));
  await page.route('**/api/version', route => route.fulfill({ json: { postgres_version: 'synthetic' } }));
  await page.route('**/api/measurement-aggregation-capabilities**', route => route.fulfill({ json: [] }));
  await page.route('**/api/data-sources', route => route.fulfill({ json: [] }));
  await page.route('**/api/air-quality-index/standards', route => route.fulfill({ json: [] }));
  await page.route('**/api/devices**', route => route.fulfill({ json: [] }));
  await page.route('**/api/measurements/**/latest**', route => route.fulfill({ json: [] }));
  await page.route('**/api/air-quality-index/**/latest**', route => route.fulfill({ json: { results: [], count: 0 } }));
  await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
    version: 8,
    sources: {},
    layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
  } }));
}

async function expectHome(page: Page) {
  await expect(page.locator('.landing-page')).toBeVisible();
  const url = new URL(page.url());
  expect(url.pathname + url.search + url.hash).toBe('/');
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`Map brand navigation remains usable at ${width}px in ${language}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await mockMapDependencies(page, language);
    await page.goto('/map?mode=devices&parameter=pm25&recency=custom&start=2020-01-01&until=2020-02-01');
    await expect(page.locator('.maplibregl-canvas')).toBeVisible();
    await expect(page.locator('.map-loading')).toBeHidden();
    await expect(page.locator('.overlay-controls')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('map-header.png') });

    if (width === 1440) {
      const brandLink = page.getByRole('link', { name: 'COMPASS', exact: true });
      await expect(brandLink).toHaveAttribute('href', '/');
      await expect(brandLink).toBeVisible();
      await brandLink.focus();
      await expect(brandLink).toBeFocused();
      await expect.poll(() => brandLink.evaluate((element) => {
        const style = getComputedStyle(element);
        return `${style.outlineStyle}/${style.outlineWidth}/${style.outlineColor}`;
      })).toBe('solid/2px/rgb(6, 71, 137)');
      await brandLink.click();
      await expectHome(page);

      await page.goBack();
      await expect(page.locator('.maplibregl-canvas')).toBeVisible();
      await brandLink.focus();
      await page.keyboard.press('Enter');
      await expectHome(page);
    } else {
      // The existing narrow Map shell intentionally hides the wordmark to keep
      // the compact controls uncluttered; preserve that layout while retaining
      // the same link destination in the rendered header markup.
      const brandLink = page.locator('.map-page .overlay-title');
      await expect(brandLink).toHaveAttribute('href', '/');
      await expect(brandLink).toBeHidden();
      await expect(page.getByRole('button', { name: language === 'es' ? 'Controles del mapa' : 'Map controls' })).toBeVisible();
    }
  });
}
