import { test, expect } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { mapCamera } from './fixtures/map-camera';

// Requires the isolated persona database copy; no CompassAQ API routes are mocked.
for (const language of ['es', 'en']) for (const width of [390, 1440]) {
  test(`real persona station context ${language} ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = () => {};
    }, language);
    await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=1m&lat=34.05&lng=-118.25&zoom=12');
    await page.locator('.maplibregl-marker').filter({ hasText: /^4$/ }).click();
    const marker = page.locator('[data-map-marker-key$="-65"]').first();
    await expect(marker).toBeVisible();
    await marker.click();
    const details = page.locator('.slide-out-panel');
    const controls = page.locator('.map-controls-surface');
    const title = 'QA SYNTHETIC — Native and QC';
    await expect(details.getByRole('heading', { name: title, exact: true })).toBeVisible();
    const initialCamera = await mapCamera(page);
    const evidence: unknown[] = [];
    const capture = async (step: string) => {
      const camera = await mapCamera(page);
      evidence.push({ step, sensorId: 65, aggregation: new URL(page.url()).searchParams.get('time_resolution'),
        url: page.url(), camera, detailsOpen: await details.isVisible(),
        controlsOpen: await controls.isVisible(), visibleStation: await details.isVisible() ? await details.innerText() : null,
        historyLength: await page.evaluate(() => history.length) });
      await page.screenshot({ path: testInfo.outputPath(`${step}.png`), animations: 'disabled' });
      expect(camera.lng).toBeCloseTo(initialCamera.lng, 5);
      expect(camera.lat).toBeCloseTo(initialCamera.lat, 5);
      expect(camera.zoom).toBeCloseTo(initialCamera.zoom, 5);
    };
    await capture('native');
    if (width === 390) {
      await details.getByRole('button', { name: /^(Close panel|Cerrar panel)$/ }).click();
      await page.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
    }
    await page.getByLabel(/^(Time resolution|Resolución temporal)$/).selectOption('rolling_24h');
    if (width === 390) await page.getByRole('button', { name: /^(Close controls|Cerrar controles)$/ }).click();
    await expect(page.locator('.map-loading')).toBeHidden();
    await capture('original-close-change-return');
    if (width === 390) await expect(details).not.toBeVisible();
    else await expect(details.getByRole('heading', { name: title, exact: true })).toBeVisible();
    if (!process.env.MAP_CONTEXT_BASELINE) {
      // Repeat with an explicit controls transition instead of deliberate dismissal.
      await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=1m&lat=34.05&lng=-118.25&zoom=12');
      await page.locator('.maplibregl-marker').filter({ hasText: /^4$/ }).click();
      await marker.click();
      for (const resolution of ['1h', '24h', 'rolling_24h', '1m']) {
        if (width === 390) {
          await details.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
          await expect(details).not.toBeVisible();
        }
        await page.getByLabel(/^(Time resolution|Resolución temporal)$/).selectOption(resolution);
        if (width === 390) await page.getByRole('button', { name: /^(Close controls|Cerrar controles)$/ }).click();
        await expect(details.getByRole('heading', { name: title, exact: true })).toBeVisible();
        await expect(page.locator('.map-loading')).toBeHidden();
        if (resolution === 'rolling_24h') {
          await expect(details.locator('.hero-value')).toHaveCount(0);
          await expect(details.getByRole('status')).toContainText(language === 'en'
            ? 'No measurement available' : 'No hay mediciones disponibles');
        } else {
          await expect(details.locator('.hero-value')).toBeVisible();
        }
        await capture(`preserved-${resolution}`);
      }
      if (width === 390) {
        await details.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
        await page.keyboard.press('Escape');
        await expect(details.getByRole('heading', { name: title, exact: true })).toBeVisible();
        await page.keyboard.press('Escape');
        await expect(details).not.toBeVisible();
        await page.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
        await page.keyboard.press('Escape');
        await expect(details).not.toBeVisible();
        expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
      }
    }
    await writeFile(testInfo.outputPath('evidence.json'), JSON.stringify(evidence, null, 2));
  });
}


for (const language of ['en', 'es']) {
  test(`real mobile controls navigation and races ${language}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 900 });
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = () => {};
    }, language);
    await page.goto('/');
    await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=1m&lat=34.05&lng=-118.25&zoom=12');
    const details = page.locator('.slide-out-panel');
    const openControls = () => details.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
    const closeControls = () => page.getByRole('button', { name: /^(Close controls|Cerrar controles)$/ }).click();
    const resolution = page.getByLabel(/^(Time resolution|Resolución temporal)$/);
    await page.locator('.maplibregl-marker').filter({ hasText: /^4$/ }).click();
    await page.locator('[data-map-marker-key$="-65"]').click();
    await expect(details.locator('.hero-value')).toBeVisible();
    const historyLength = await page.evaluate(() => history.length);
    // Delay an actual backend response; never substitute a fabricated payload.
    let releaseHourly!: () => void;
    const hourlyGate = new Promise<void>(resolve => { releaseHourly = resolve; });
    await page.route('**/api/measurements/pm25/latest?**', async route => {
      if (new URL(route.request().url()).searchParams.get('aggregation') !== '1h') return route.continue();
      const response = await route.fetch();
      await hourlyGate;
      await route.fulfill({ response });
    });
    await openControls();
    await resolution.selectOption('1h');
    await closeControls();
    await expect(details.locator('.hero-value')).toHaveCount(0);
    await expect(details.getByRole('status').first()).toContainText(language === 'en' ? 'Loading' : 'Cargando');
    await page.screenshot({ path: testInfo.outputPath('loading.png') });
    await openControls();
    await resolution.selectOption('24h');
    await closeControls();
    await expect(details.locator('.hero-value')).toBeVisible();
    const dailyText = await details.locator('.map-measurement-context').innerText();
    releaseHourly();
    await page.unrouteAll({ behavior: 'wait' });
    await expect(page.locator('.map-loading')).toBeHidden();
    await expect(details.locator('.map-measurement-context')).toHaveText(dailyText, { useInnerText: true });
    expect(await page.evaluate(() => history.length)).toBe(historyLength);
    await openControls();
    await resolution.selectOption('1m');
    await closeControls();
    await expect(details.locator('.hero-value')).toBeVisible();
    await details.getByRole('button', { name: /^(Close panel|Cerrar panel)$/ }).click();
    await page.locator('[data-map-marker-key$="-66"]').click();
    await expect(details.getByRole('link', { name: /^(Open Full Analytics|Abrir análisis completo)$/ })).toHaveAttribute('href', /measurement%7C66%7C/);
    await openControls();
    await page.getByLabel(language === 'en' ? 'Data source filter' : 'Filtro de fuente de datos').selectOption('airgradient');
    await closeControls();
    await expect(details.locator('.hero-value')).toHaveCount(0);
    await expect(details.getByRole('status')).toContainText(language === 'en' ? 'No measurement available' : 'No hay mediciones disponibles');
    await openControls();
    await page.getByLabel(language === 'en' ? 'Data source filter' : 'Filtro de fuente de datos').selectOption('');
    await page.getByLabel(language === 'en' ? 'Parameter' : 'Parámetro', { exact: true }).selectOption('pm10');
    await closeControls();
    await expect(details).not.toBeVisible();
    await page.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
    await page.getByLabel(language === 'en' ? 'Layer' : 'Capa', { exact: true }).selectOption('aqi');
    await closeControls();
    await expect(details).not.toBeVisible();
    await page.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
    await page.getByLabel(language === 'en' ? 'Layer' : 'Capa', { exact: true }).selectOption('measurements');
    await closeControls();
    await expect(details).not.toBeVisible();
    await page.goBack();
    await expect(page).not.toHaveURL(/\/map/);
    await page.goForward();
    await expect(page).toHaveURL(/\/map/);
    await expect(details).not.toBeVisible();
    expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
  });
}

for (const language of ['en', 'es']) {
  test(`real mobile current aggregation and Analytics return ${language}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 900 });
    await page.addInitScript(lang => {
      localStorage.setItem('compassaq.language', lang);
      navigator.geolocation.getCurrentPosition = () => {};
    }, language);
    await page.goto('/map?mode=pollutants&parameter=pm25&time_resolution=1m&lat=34.05&lng=-118.25&zoom=12');
    await page.locator('.maplibregl-marker').filter({ hasText: /^4$/ }).click();
    await page.locator('[data-map-marker-key$="-70"]').click();
    const details = page.locator('.slide-out-panel');
    await expect(details.locator('canvas')).toBeVisible();
    const camera = await mapCamera(page);
    const results: unknown[] = [];
    for (const resolution of ['1h', '24h', 'rolling_24h', '1m']) {
      await details.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
      // The app reuses its native-result cache when returning to 1m. Retrieve
      // that oracle separately rather than requiring an extra application call.
      const responsePromise = resolution === '1m'
        ? page.request.get('/api/measurements/pm25/latest?all_results=true&aggregation=1m')
        : page.waitForResponse(response => response.url().includes('/measurements/pm25/latest')
          && new URL(response.url()).searchParams.get('aggregation') === resolution);
      await page.getByLabel(/^(Time resolution|Resolución temporal)$/).selectOption(resolution);
      const response = await responsePromise;
      const result = (await response.json() as { sensor_id: number; result_aggregation_code: string; value: number }[]).find(item => item.sensor_id === 70);
      expect(result).toBeDefined();
      expect(result!.result_aggregation_code).toBe(resolution);
      await page.getByRole('button', { name: /^(Close controls|Cerrar controles)$/ }).click();
      await expect(details.locator('.hero-value')).toBeVisible();
      await expect(details.getByRole('heading', { name: 'QA SYNTHETIC — Native and QC', exact: true })).toBeVisible();
      await expect(details.locator('.hero-unit')).toHaveText('µg/m³');
      if (resolution === 'rolling_24h') {
        await expect(details.getByText(language === 'en' ? 'Calculated at (UTC)' : 'Calculado el (UTC)', { exact: true })).toBeVisible();
        await expect(details.locator('.panel-chart-container [role=alert]')).toBeVisible();
      } else await expect(details.locator('canvas')).toBeVisible();
      results.push({ resolution, result, text: await details.innerText(), camera: await mapCamera(page) });
      await page.screenshot({ path: testInfo.outputPath(`${resolution}.png`), animations: 'disabled' });
    }
    // Let the existing one-minute refresh run while mobile details stay open.
    const refresh = page.waitForResponse(response => response.url().includes('/measurements/pm25/latest')
      && new URL(response.url()).searchParams.get('aggregation') === '1m');
    await refresh;
    await expect(details.locator('.hero-value')).toBeVisible();
    await expect(details.getByRole('heading', { name: 'QA SYNTHETIC — Native and QC', exact: true })).toBeVisible();
    await details.getByRole('link', { name: /^(Open Full Analytics|Abrir análisis completo)$/ }).click();
    await expect(page).toHaveURL(/\/analytics/);
    await page.goBack();
    await expect(page).toHaveURL(/\/map/);
    await expect(page.locator('.map-loading')).toBeHidden();
    expect((await mapCamera(page)).lng).toBeCloseTo(camera.lng, 5);
    expect((await mapCamera(page)).lat).toBeCloseTo(camera.lat, 5);
    expect((await mapCamera(page)).zoom).toBeCloseTo(camera.zoom, 5);
    await expect(details).not.toBeVisible(); // Existing route-return policy is unchanged.
    await writeFile(testInfo.outputPath('active-results.json'), JSON.stringify(results, null, 2));
  });
}
