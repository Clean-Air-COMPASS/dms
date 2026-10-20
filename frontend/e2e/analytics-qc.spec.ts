import { test, expect } from '@playwright/test';

// Run against the explicitly synthetic, database-backed fixture created by
// backend/scripts/seed_analytics_qc_acceptance.py. No API responses are mocked
// except the one deliberately exercised detail-request failure.
const sensorId = process.env.ANALYTICS_QC_SENSOR_ID;
test.skip(!sensorId, 'Set ANALYTICS_QC_SENSOR_ID to the seeded synthetic sensor');
const url = (aggregation = '2m', dense = false) => `/analytics?series=measurement%7C${sensorId}%7Cpm25%7C${aggregation}&start=2026-10-01T00:00:00Z&end=${dense ? '2026-10-06' : '2026-10-01'}T${dense ? '00' : '01'}:00:00Z&timezone=utc`;

for (const language of ['en', 'es']) for (const width of [1440, 1200, 390]) {
  test(`recorded Analytics QC ${language} ${width}`, async ({ page }, testInfo) => {
    const es = language === 'es';
    await page.setViewportSize({ width, height: 1000 });
    await page.addInitScript(lang => localStorage.setItem('compassaq.language', lang), language);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const historyRequests: URL[] = [];
    const detailRequests: string[] = [];
    page.on('request', request => {
      if (request.url().includes(`/sensors/${sensorId}/history`)) historyRequests.push(new URL(request.url()));
      if (request.url().endsWith('/qc')) detailRequests.push(request.url());
    });
    const capture = async (name: string) => {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      // Wait for Chart.js's existing one-second animation before visual review.
      await page.waitForTimeout(1100);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true });
    };
    await page.goto(url());
    await expect(page.locator('canvas')).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', language);
    expect(detailRequests).toHaveLength(0);
    const include = page.getByRole('checkbox', { name: es ? 'Incluir mediciones no válidas' : 'Include invalid measurements' });
    const show = page.getByRole('checkbox', { name: es ? 'Mostrar puntos no válidos' : 'Show invalid points' });
    const filter = page.getByRole('combobox', { name: es ? 'Filtro de QC · tabla de resultados' : 'QC filter · results table' });
    await expect(show).toHaveCount(0);
    await filter.selectOption('flagged');
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await expect(page.locator('tbody')).toContainText(es ? 'Marcada para revisión · Válida' : 'Flagged for review · Valid');
    await capture('flagged-collapsed');
    const summary = page.locator('tbody summary').first();
    await summary.focus(); await page.keyboard.press('Enter');
    await expect(page.locator('tbody')).toContainText('Synthetic recorded maximum exceeded.');
    expect(detailRequests).toHaveLength(1);
    await page.keyboard.press('Tab');
    await expect(page.locator('tbody details details summary')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('tbody')).toContainText('synthetic-historical-1');
    await expect(page.locator('tbody')).toContainText(es ? 'Configuración del sensor' : 'Sensor setting');
    await capture('flagged-provenance');
    await filter.selectOption('indeterminate');
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await page.locator('tbody summary').first().click();
    await expect(page.locator('tbody')).toContainText('Synthetic insufficient history');
    await capture('indeterminate');
    await filter.selectOption('invalid');
    await expect(page.locator('tbody tr')).toHaveCount(0);
    await capture('invalid-excluded-empty');
    await include.check();
    await expect(page.locator('tbody tr')).toHaveCount(2);
    await expect(show).toBeChecked();
    expect(historyRequests.at(-1)?.searchParams.get('include_invalid')).toBe('true');
    await page.locator('tbody summary').first().click();
    await expect(page.locator('tbody')).toContainText('Synthetic insufficient history');
    await expect(page.locator('tbody')).toContainText('Synthetic recorded maximum exceeded.');
    await expect(page.locator('tbody')).toContainText('Synthetic recorded minimum not reached.');
    await capture('invalid-multiple-outcomes');
    const count = historyRequests.length;
    await show.uncheck();
    await expect(page.locator('tbody tr')).toHaveCount(2);
    expect(historyRequests).toHaveLength(count);
    await capture('invalid-hidden-chart');
    await show.check();
    await filter.selectOption('all');
    await page.locator('tbody summary').first().click();
    await expect(page.locator('tbody')).toContainText(es ? 'no demuestra' : 'does not establish');
    await capture('missing-record');
    await include.uncheck();
    await expect(show).toHaveCount(0);

    await page.goto(url('1h'));
    await expect(page.locator('tbody tr')).toHaveCount(2);
    await include.check();
    await filter.selectOption('invalid');
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await expect(page.locator('tbody')).toContainText(es ? '21,6' : '21.6');
    await page.locator('tbody summary').first().click();
    await expect(page.locator('tbody')).toContainText(es ? 'Fuentes incluidas: 28 válidas · 2 inválidas' : 'Included sources: 28 valid · 2 invalid');
    await expect(page.locator('tbody')).toContainText(es ? 'resolución nativa' : 'native resolution');
    await expect(page.locator('tbody')).not.toContainText(es ? 'Guardada como' : 'Stored as');
    await capture('aggregate-source-limitation');

    await page.goto(url('2m', true));
    await expect(page.locator('canvas')).toBeVisible();
    await include.check();
    const began = Date.now();
    await filter.selectOption('flagged');
    await expect(page.locator('tbody tr')).toHaveCount(3);
    console.log(`QC filter ${language}/${width}: ${Date.now()-began} ms`);
    await capture('dense-series');

    await page.goto(url('1h').replace('T00:00:00Z', 'T00:04:00Z').replace('T01:00:00Z', 'T00:05:00Z'));
    await expect(page.getByRole('status')).toContainText(es ? 'ninguna es apta' : 'none are eligible');
    await expect(page.getByText(es ? '0% válido' : '0% valid', { exact: true })).toHaveCount(0);
    await capture('no-eligible-aggregate');
    await include.check();
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await expect(page.locator('tbody')).toContainText('80');
    expect(errors).toEqual([]);
  });
}

test('recorded detail loading and failure recover without changing the selection', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('compassaq.language', 'en'));
  let release: (() => void) | undefined;
  await page.route('**/measurements/*/qc', async route => {
    await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ status: 503, json: { detail: 'Synthetic temporary failure' } });
  });
  await page.goto(url());
  await page.getByRole('combobox', { name: 'QC filter · results table' }).selectOption('flagged');
  await page.locator('tbody summary').first().click();
  await expect(page.getByText('Loading recorded QC…')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('loading.png'), fullPage: true });
  await expect.poll(() => Boolean(release)).toBe(true); release!();
  await expect(page.getByRole('alert')).toContainText('could not be loaded');
  await page.screenshot({ path: testInfo.outputPath('error.png'), fullPage: true });
  await page.unroute('**/measurements/*/qc');
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.locator('tbody')).toContainText('Synthetic recorded maximum exceeded.');
  await expect(page).toHaveURL(/series=measurement/);
});
