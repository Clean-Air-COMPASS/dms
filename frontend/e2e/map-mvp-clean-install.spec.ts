import { expect, test } from '@playwright/test';

test.skip(process.env.MAP_CLEAN_INSTALL_ACCEPTANCE !== '1', 'Requires the fresh compassaq-map-mvp-clean Compose project on port 28580');

test('fresh built-in references, geolocation fallback, and intentional navigation', async ({ page, baseURL }, testInfo) => {
  expect(baseURL).toBe('http://127.0.0.1:28580');
  await page.addInitScript(() => {
    navigator.geolocation.getCurrentPosition = success => success({ coords: { latitude: 37.77, longitude: -122.42 } } as GeolocationPosition);
  });
  const setup = await (await page.request.get('/api/setup/status')).json();
  if (setup.is_setup_required) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.locator('#admin-email').fill('map-review@example.org');
  await page.locator('#admin-password').fill('MapReview2026!Strong');
  await page.locator('#admin-confirm-password').fill('MapReview2026!Strong');
  await page.locator('button[type=submit]').click();
  await page.getByRole('button', { name: 'Set up later' }).click();
  await expect(page.getByRole('checkbox', { name: 'Enable Demo Data' })).toBeChecked();
  await page.getByRole('button', { name: 'Save Sources & Continue' }).click();
  await page.getByRole('button', { name: 'Skip for Now →' }).click();
  await page.getByRole('button', { name: 'Complete Setup & Start Using Platform' }).click();
  await expect(page.locator('.landing-page')).toBeVisible();
  } else {
    expect(process.env.MAP_CLEAN_INSTALL_REUSE).toBe('1');
    await page.goto('/');
  }
  const devices = await (await page.request.get('/api/devices')).json() as Array<{ device_id: number; name: string; latitude: number; longitude: number; external_id: string }>;
  expect(devices).toHaveLength(8);
  expect(devices.filter(device => device.longitude < -70)).toHaveLength(3);
  expect(devices.filter(device => device.latitude < -20)).toHaveLength(2);
  expect(devices.filter(device => device.longitude > 120)).toHaveLength(2);
  expect(devices.filter(device => device.name.startsWith('DEMO'))).toHaveLength(1);
  expect(devices.some(device => device.latitude >= 45.8 && device.latitude <= 47.9 && device.longitude >= 5.9 && device.longitude <= 10.5)).toBe(false);
  await page.request.get('/api/devices?parameter=pm25').then(async response => expect((await response.json()).length).toBe(7));

  for (const language of ['en', 'es']) for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.evaluate(lang => localStorage.setItem('compassaq.language', lang), language);
    await page.goto('/map');
    await expect(page.locator('.maplibregl-marker')).toHaveCount(8);
    // Remote reference markers entering the viewport proves the initial empty
    // San Francisco view was fitted using the genuine fresh database response.
    for (const marker of await page.locator('.maplibregl-marker').all()) await expect(marker).toBeInViewport();
    await expect(page.getByTestId('map-empty-state')).toHaveCount(0);
    await page.waitForTimeout(2500); // Allow the real basemap tiles to settle for visual review.
    await page.screenshot({ path: testInfo.outputPath(`${language}-${width}-world-references.png`) });
    const mobile = width === 390;
    const open = async () => { if (mobile) await page.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click(); };
    const close = async () => { if (mobile) await page.getByRole('button', { name: /^(Close controls|Cerrar controles)$/ }).click(); };
    await open();
    await expect(page.locator('.map-recency-control, .toolbar-icon-btn')).toHaveCount(0);
    await page.getByRole('button', { name: /^(Reset view|Restablecer vista)$/ }).click();
    await close();
    await expect(page.getByTestId('map-empty-state')).toBeVisible();
    await page.waitForTimeout(700);
    for (const marker of await page.locator('.maplibregl-marker').all()) await expect(marker).not.toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`${language}-${width}-intentional-location-empty.png`) });
    await open();
    for (const layer of ['measurements', 'aqi', 'devices']) {
      await page.locator('.map-layer-control select').selectOption(layer);
      await expect(page.locator('.map-loading')).toHaveCount(0);
      await page.screenshot({ path: testInfo.outputPath(`${language}-${width}-${layer}-controls.png`) });
      await close();
      await expect(page.getByTestId('map-empty-state')).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath(`${language}-${width}-${layer}-empty.png`) });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await open();
    }
    await close();
  }
});
