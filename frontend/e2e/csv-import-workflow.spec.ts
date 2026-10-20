import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

// Provision only synthetic local data with the acceptance seed script. No
// provider credentials or existing administrator credentials are needed.
const fixturePath = process.env.CSV_QA_FIXTURE;
type Fixture = {
  email: string; password: string; device_id: number; device_name: string;
  external_device_id: string; sensors: { id: number; name: string }[];
};

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
}

test('real CSV upload applies policies, QC and activity on localhost', async ({ page }, testInfo) => {
  test.skip(!fixturePath, 'Set CSV_QA_FIXTURE to a provisioned synthetic localhost fixture');
  const fixture: Fixture = JSON.parse(readFileSync(fixturePath!, 'utf8'));
  await page.goto('/login');
  await page.getByLabel('Email').fill(fixture.email);
  await page.getByRole('textbox', { name: 'Password' }).fill(fixture.password);
  const loginResponse = page.waitForResponse(response => response.url().endsWith('/api/auth/login') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in' }).click();
  const signedIn = await loginResponse;
  expect(signedIn.ok()).toBeTruthy();
  const token = (await signedIn.json()).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  await expect(page).toHaveURL(/\/map(?:\?|$)/);
  if (await page.locator('html').getAttribute('lang') === 'es') {
    await page.getByRole('button', { name: /Synthetic CSV QA/ }).click();
    await page.getByLabel('Idioma').selectOption('en');
    await page.keyboard.press('Escape');
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  const flag = fixture.sensors.find(sensor => sensor.name === 'flag')!.id;
  const invalid = fixture.sensors.find(sensor => sensor.name === 'invalid')!.id;
  const drift = fixture.sensors.find(sensor => sensor.name === 'drift')!.id;
  const policyResponse = await page.request.put(`/api/admin/devices/${fixture.device_id}`, { headers, data: { allow_updates: 'deny' } });
  expect(policyResponse.ok()).toBeTruthy();
  const timestamp = new Date(Date.now() - 86400000);
  timestamp.setMilliseconds(0);
  const at = (minutes: number) => new Date(timestamp.getTime() + minutes * 60000).toISOString();
  const future = new Date(Date.now() + 86400000).toISOString();
  const csv = `internalsensorid,datetime,value\n${flag},${at(0)},12\n${flag},${at(0)},15\n${flag},${at(2)},35000\n${invalid},${at(2)},40000\n${flag},${future},20\n`;
  const uploadCsv = async (contents: string) => {
    await page.getByLabel('CSV file').setInputFiles({ name: 'synthetic-qa.csv', mimeType: 'text/csv', buffer: Buffer.from(contents) });
    const responsePromise = page.waitForResponse(response => response.url().includes('/admin/imports/upload-csv'));
    await page.getByRole('button', { name: 'Upload CSV', exact: true }).click();
    const response = await responsePromise;
    expect(response.ok()).toBeTruthy();
    return response.json();
  };
  await page.goto('/admin/uploads/csv');
  for (const query of [String(fixture.device_id), String(flag), fixture.external_device_id, fixture.device_name]) {
    await page.getByRole('searchbox', { name: 'Device name or identifier' }).fill(query);
    await expect(page.getByRole('button', { name: fixture.device_name, exact: true })).toBeVisible();
  }
  await page.getByRole('button', { name: fixture.device_name, exact: true }).click();
  await expect(page.getByText('Timestamp meaning: Interval start')).toHaveCount(3);
  const result = await uploadCsv(csv);
  expect(result).toMatchObject({ total_records: 5, inserted_records: 3, updated_records: 0, skipped_records: 1, failed_records: 1, qc: { evaluated: 3, flagged: 2 } });
  await expect(page.getByText(/Line 6: Timestamp is later/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('csv-partial-en-desktop.png'), fullPage: true });
  await noOverflow(page);
  const history = await page.request.get(`/api/sensors/${flag}/history?hours=48&aggregate=raw&include_qc=true`);
  const points = (await history.json()).data;
  expect(points.some((row: { value: number }) => row.value === 12)).toBeTruthy();
  expect(points.some((row: { value: number; is_valid: boolean }) => row.value === 35000 && row.is_valid)).toBeTruthy();
  expect(points.some((row: { timestamp: string }) => Date.parse(row.timestamp) > Date.now() + 300000)).toBeFalsy();

  expect((await page.request.put(`/api/admin/devices/${fixture.device_id}`, { headers, data: { allow_updates: 'allow' } })).ok()).toBeTruthy();
  const replacement = await uploadCsv(`internalsensorid,datetime,value\n${flag},${at(0)},40000\n`);
  expect(replacement).toMatchObject({ inserted_records: 0, updated_records: 1, skipped_records: 0, failed_records: 0, qc: { evaluated: 1, flagged: 1 } });
  const replacedHistory = await page.request.get(`/api/sensors/${flag}/history?hours=48&aggregate=raw&include_qc=true`);
  expect((await replacedHistory.json()).data.some((row: { value: number }) => row.value === 40000)).toBeTruthy();

  const driftRows = Array.from({ length: 8 }, (_, index) => `${drift},${new Date(timestamp.getTime() - (8-index)*86400000).toISOString()},${index*20}\n`).join('');
  const driftImport = await uploadCsv(`internalsensorid,datetime,value\n${driftRows}${drift},${at(0)},180\n`);
  expect(driftImport.inserted_records).toBe(9);
  expect(driftImport.qc.flagged).toBeGreaterThan(0);
  await page.getByRole('link', { name: 'Review QC failures' }).click();
  const search = page.getByRole('searchbox', { name: 'Search:' });
  await search.fill(fixture.device_name);
  await expect(page.getByText('Failed — Flag for review', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Failed — Marked invalid', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Baseline drift', exact: true }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('csv-qc-en-desktop.png'), fullPage: true });
  await noOverflow(page);
  const qc = await page.request.get(`/api/admin/events/qc-failures?search=${encodeURIComponent(fixture.device_name)}&status=failed&limit=100`, { headers });
  expect((await qc.json()).items.some((row: { check_code: string; evaluation_status: string }) => row.check_code === 'baseline_drift' && row.evaluation_status === 'failed')).toBeTruthy();
  await page.goto('/admin/events?tab=events');
  await page.getByLabel('Source:').selectOption('CSV upload');
  await expect(page.getByText('CSV upload completed with rejected lines').first()).toBeVisible();
  await expect(page.getByText('Synthetic CSV QA', { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('csv-events-en-desktop.png'), fullPage: true });
  await noOverflow(page);
  const events = await page.request.get('/api/admin/events?event_type=csv.upload', { headers });
  const activity = (await events.json()).find((row: { event_id: number }) => row.event_id === result.event_id);
  expect(activity.params).toMatchObject({ outcome: 'partial', inserted_records: 3, updated_records: 0, skipped_records: 1, failed_records: 1 });
  expect(activity.actor_email).toBe(fixture.email);

  await page.getByRole('button', { name: 'Account menu for Synthetic CSV QA' }).click();
  await page.getByLabel('Language').selectOption('es');
  await expect(page.locator('html')).toHaveAttribute('lang', 'es');
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText('Carga de CSV completada con líneas rechazadas').first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('csv-events-es-mobile.png'), fullPage: true });
  await noOverflow(page);
  await page.goto('/admin/uploads/csv');
  await page.getByRole('searchbox', { name: 'Nombre o identificador del dispositivo' }).fill(String(flag));
  await page.getByRole('button', { name: fixture.device_name, exact: true }).click();
  await expect(page.getByText('Significado temporal: Inicio del intervalo')).toHaveCount(3);
  await page.getByLabel('Archivo CSV').setInputFiles({ name: 'synthetic-future.csv', mimeType: 'text/csv', buffer: Buffer.from(`internalsensorid,datetime,value\n${flag},${future},12\n`) });
  await page.getByRole('button', { name: 'Subir CSV', exact: true }).click();
  await expect(page.getByText(/Línea 2: La marca de tiempo supera/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('csv-failed-es-mobile.png'), fullPage: true });
  await noOverflow(page);
});
