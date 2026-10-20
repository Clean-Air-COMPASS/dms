import { test, expect, type Page } from '@playwright/test';

async function mockMap(page: Page, language: string) {
  const observedAt = new Date().toISOString();
  const flagged = { check_code: 'max_value', evaluation_status: 'failed', passed: false, failure_action: 'flag_for_review', reason_code: null };
  const invalid = { ...flagged, failure_action: 'mark_invalid' };
  const devices = [0, 1].map(index => ({ device_id: 901 + index, name: `Synthetic mobile station ${index + 1}`, friendly_name: `Synthetic mobile station ${index + 1}`, longitude: index * 0.01, latitude: 0, sensor_count: 2, timezone: 'UTC' }));
  await page.addInitScript(language => {
    localStorage.setItem('compassaq.language', language);
    navigator.geolocation.getCurrentPosition = (_success, error) => error?.({ code: 1, message: 'Synthetic test', PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
  }, language);
  await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
    version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
  } }));
  await page.route(/\/api\/devices(?:\?.*)?$/, route => route.fulfill({ json: devices }));
  await page.route(/\/api\/measurements\/(?:pm25\/)?latest(?:\?.*)?$/, route => route.fulfill({ json: devices.map((device, index) => ({ measurement_id: 920 + index, sensor_id: 910 + index, value: 12, parameter: 'pm25', unit: 'µg/m³', observed_at: observedAt, device })) }));
  await page.route('**/api/devices/901/sensors**', route => route.fulfill({ json: ['pm25', 'pm10'].map((parameter, index) => ({ sensor_id: 910 + index, parameter, latest_value: 12 + index, unit: 'µg/m³', latest_observed_at: observedAt, latest_is_valid: true, native_aggregation_code: '2m', result_aggregation_code: '2m' })) }));
  await page.route('**/api/sensors/91*/history**', route => route.fulfill({ json: {
    sensor_id: Number(new URL(route.request().url()).pathname.split('/')[3]), parameter: route.request().url().includes('/911/') ? 'pm10' : 'pm25', unit: 'µg/m³', native_aggregation_code: '2m', result_aggregation_code: '2m',
    data: [
      { timestamp: new Date(Date.now() - 8 * 60_000).toISOString(), value: 10, is_valid: true, failed_checks: [], qc_results: [] },
      { timestamp: new Date(Date.now() - 6 * 60_000).toISOString(), value: 12, is_valid: true, failed_checks: [{ check_code: 'max_value' }], qc_results: [flagged] },
      { timestamp: new Date(Date.now() - 4 * 60_000).toISOString(), value: 80, is_valid: false, failed_checks: [{ check_code: 'max_value' }], qc_results: [invalid] },
      { timestamp: new Date(Date.now() - 2 * 60_000).toISOString(), value: 14, is_valid: true, failed_checks: [], qc_results: [] },
    ],
  } }));
}

async function markerPositions(page: Page) {
  return page.locator('.maplibregl-marker').evaluateAll(markers => markers.map(marker => {
    const { x, y } = marker.getBoundingClientRect(); return { x, y };
  }));
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  for (const dialog of await page.locator('dialog[open]').all()) {
    expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
}

for (const language of ['en', 'es']) for (const width of [1440, 390]) {
  test(`Map overlays preserve interaction and camera ${language} ${width}`, async ({ page }, testInfo) => {
    page.setDefaultTimeout(15000);
    await page.setViewportSize({ width, height: 844 });
    await mockMap(page, language);
    const es = language === 'es'; const mobile = width === 390;
    const controlsName = es ? 'Controles del mapa' : 'Map controls';
    const closeName = es ? 'Cerrar controles' : 'Close controls';
    await page.goto('/map');
    await expect(page.locator('.maplibregl-marker')).toHaveCount(2);
    await expect(page.locator('.map-loading')).toBeHidden();
    // Initial fitBounds uses a 500ms transition and one delayed sizing retry.
    await expect.poll(async () => {
      const before = await markerPositions(page);
      await page.waitForTimeout(300);
      return JSON.stringify(await markerPositions(page)) === JSON.stringify(before);
    }).toBe(true);
    const trigger = page.getByRole('button', { name: controlsName, exact: true });
    if (mobile) {
      await expect(trigger).toBeVisible();
      await expect(page.locator('.map-layer-control select')).toBeHidden();
      expect((await page.locator('.map-canvas').boundingBox())!.height).toBe(844);
      await expect(page.locator('.map-controls-active')).toHaveCount(0);
      await trigger.click();
      await expect(page.getByRole('dialog', { name: controlsName })).toBeVisible();
      await expect(page.getByRole('button', { name: closeName })).toBeFocused();
      await expect(page.locator('body')).toHaveCSS('overflow', 'hidden');
      // The modal's top layer intercepts pointer and wheel input above the sheet too.
      expect(await page.evaluate(() => document.elementFromPoint(150, 100)?.tagName)).toBe('DIALOG');
      const before = await markerPositions(page);
      await page.mouse.move(150, 100); await page.mouse.wheel(0, 350);
      expect(await markerPositions(page)).toEqual(before);
    } else {
      await expect(trigger).toHaveCount(0);
      await expect(page.locator('.map-layer-control select')).toBeVisible();
    }
    await expect(page.locator('.map-recency-control, .toolbar-icon-btn')).toHaveCount(0);
    await page.locator('.map-parameter-control select').selectOption('pm25');
    await expect(page).toHaveURL(/parameter=pm25/);
    await expect(page.locator('.map-loading')).toBeHidden();
    await noOverflow(page);
    await page.screenshot({ path: testInfo.outputPath('controls.png') });
    const position = await markerPositions(page);
    const canvas = await page.locator('.maplibregl-canvas').elementHandle();
    if (mobile) {
      await page.getByRole('button', { name: closeName }).click();
      await expect(trigger).toBeFocused();
      await expect(page.locator('.map-controls-active')).toBeVisible();
      expect(await markerPositions(page)).toEqual(position);
      await trigger.click();
      await expect(page.locator('.map-parameter-control select')).toHaveValue('pm25');
      await page.keyboard.press('Escape');
      await expect(page.locator('dialog[open]')).toHaveCount(0);
      await expect(page.locator('body')).not.toHaveCSS('overflow', 'hidden');
      await trigger.click();
      await page.mouse.click(150, 100);
      await expect(page.locator('dialog[open]')).toHaveCount(0);
    }
    await page.screenshot({ path: testInfo.outputPath('map.png') });
    const marker = page.getByTitle('Synthetic mobile station 1', { exact: true });
    await marker.focus(); await page.keyboard.press('Enter');
    const panel = page.locator('.slide-out-panel.open');
    await expect(panel.locator('canvas')).toBeVisible();
    await expect(panel.getByRole('button', { name: /Close panel|Cerrar panel/ })).toBeVisible();
    if (mobile) {
      await expect(panel).toHaveAttribute('open', '');
      expect(await panel.boundingBox()).toEqual({ x: 0, y: 0, width: 390, height: 844 });
      expect(await page.evaluate(() => document.elementFromPoint(1, 400)?.closest('dialog') !== null)).toBe(true);
      await expect(page.locator('body')).toHaveCSS('overflow', 'hidden');
    } else {
      expect((await panel.boundingBox())!.width).toBe(400);
      expect((await panel.boundingBox())!.x).toBe(1040);
    }
    await panel.getByRole('button', { name: 'PM10', exact: true }).click();
    await expect(panel.locator('.hero-value')).toHaveText('13');
    const invalidPoints = panel.getByRole('checkbox', { name: es ? 'Mostrar puntos no válidos' : 'Show invalid points', exact: true });
    await invalidPoints.check(); await expect(invalidPoints).toBeChecked();
    await invalidPoints.uncheck();
    await panel.locator('.chart-action-btn').click();
    await expect(panel.locator('canvas')).toBeVisible();
    await noOverflow(page);
    await page.screenshot({ path: testInfo.outputPath('details.png') });
    if (mobile) {
      await page.setViewportSize({ width, height: 568 });
      expect((await panel.boundingBox())!.height).toBe(568);
      await panel.evaluate(element => { element.scrollTop = element.scrollHeight; });
      expect(await panel.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
      await expect(panel.getByRole('link', { name: /Open Full Analytics|Abrir análisis completo/i })).toBeInViewport();
      await expect(panel.getByRole('button', { name: /Close panel|Cerrar panel/ })).toBeInViewport();
      await noOverflow(page);
      await page.screenshot({ path: testInfo.outputPath('details-short-scrolled.png') });
      await page.setViewportSize({ width, height: 844 });
    }
    await panel.getByRole('button', { name: /Close panel|Cerrar panel/ }).click();
    expect(await markerPositions(page)).toEqual(position);
    expect(await canvas!.evaluate(element => element.isConnected)).toBe(true);
    if (mobile) await expect(marker).toBeFocused();
    // Gestures work again after dismissal; two separated markers reveal scale changes.
    const oldPositions = await markerPositions(page);
    await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
    await expect.poll(() => markerPositions(page)).not.toEqual(oldPositions);
    await noOverflow(page);
  });
}
