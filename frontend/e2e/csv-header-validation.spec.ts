import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { getDatabaseMeasurementCount, getIsolatedDatabaseContainerId } from './isolated-qa-preflight';

function requiredEnvironment(name: string) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Set ${name} for isolated CSV browser acceptance.`);
  return value;
}

type Fixture = {
  email: string;
  password: string;
  device_name: string;
  device_id: number;
  sensors: { id: number; name: string }[];
};

type HistoryPoint = {
  timestamp: string;
  value: number;
  is_valid?: boolean;
  qc_flags?: string[] | null;
  qc_provenance_status?: 'recorded' | 'not_recorded' | 'source_details_unavailable';
  qc_results?: {
    check_code: string;
    evaluation_status: 'failed' | 'indeterminate';
    passed: boolean | null;
    failure_action: string;
    reason_code: string | null;
  }[];
};

async function setLanguage(page: Page, language: 'en' | 'es') {
  const current = await page.locator('html').getAttribute('lang');
  if (current === language) return;

  await page.locator('.user-menu__trigger').click();
  const label = language === 'en' ? 'Idioma' : 'Language';
  await page.getByLabel(label).selectOption(language);
  await expect(page.locator('html')).toHaveAttribute('lang', language);
  await page.keyboard.press('Escape');
}

async function selectDestinationDevice(page: Page, fixture: Fixture, language: 'en' | 'es') {
  const changeDevice = language === 'en' ? 'Choose another device' : 'Elegir otro dispositivo';
  const changeButton = page.getByRole('button', { name: changeDevice, exact: true });
  if (await changeButton.isVisible().catch(() => false)) await changeButton.click();

  const searchLabel = language === 'en' ? 'Device name or identifier' : 'Nombre o identificador del dispositivo';
  await page.getByRole('searchbox', { name: searchLabel }).fill(fixture.device_name);
  await page.getByRole('button', { name: fixture.device_name, exact: true }).click();
  await expect(page.getByText(fixture.device_name, { exact: true }).first()).toBeVisible();
}

async function uploadFile(page: Page, path: string, language: 'en' | 'es', useKeyboard: boolean) {
  if (useKeyboard) {
    const chooseLabel = language === 'en' ? 'Choose CSV File' : 'Elija el archivo CSV';
    const chooserPromise = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: chooseLabel, exact: true }).focus();
    await page.keyboard.press('Enter');
    const chooser = await chooserPromise;
    await chooser.setFiles(path);
  } else {
    const inputLabel = language === 'en' ? 'CSV file' : 'Archivo CSV';
    await page.getByLabel(inputLabel).setInputFiles(path);
  }

  const uploadLabel = language === 'en' ? 'Upload CSV' : 'Subir CSV';
  const responsePromise = page.waitForResponse(response =>
    response.url().includes('/api/admin/imports/upload-csv') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: uploadLabel, exact: true }).click();
  return responsePromise;
}

async function getMeasurementSnapshot(page: Page, sensorIds: number[], headers: Record<string, string>) {
  const points: {
    sensorId: number;
    timestamp: string;
    value: number;
    is_valid?: boolean;
    qc_flags?: string[] | null;
    qc_provenance_status?: HistoryPoint['qc_provenance_status'];
    qc_results?: HistoryPoint['qc_results'];
  }[] = [];
  for (const sensorId of sensorIds) {
    const response = await page.request.get(
      `/api/sensors/${sensorId}/history?hours=72&aggregate=raw&include_qc=true`,
      { headers },
    );
    expect(response.ok()).toBeTruthy();
    const body = await response.json() as { data: HistoryPoint[] };
    points.push(...body.data.map(point => ({
      sensorId,
      timestamp: new Date(point.timestamp).toISOString(),
      value: point.value,
      is_valid: point.is_valid,
      qc_flags: point.qc_flags,
      qc_provenance_status: point.qc_provenance_status,
      qc_results: point.qc_results,
    })));
  }
  return points.sort((left, right) =>
    left.sensorId - right.sensorId || left.timestamp.localeCompare(right.timestamp),
  );
}

async function assertNoPageOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
}

async function verifyMapAndAnalyticsAfterRecovery(
  page: Page,
  fixture: Fixture,
  testInfo: { outputPath: (path: string) => string },
  screenshotPrefix = 'recovery',
  expectedNativeValues: number[] = [],
) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const devicesResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith('/api/devices') && response.request().method() === 'GET',
  );
  await page.goto('/map?mode=devices&parameter=pm25');
  const devicesResponse = await devicesResponsePromise;
  expect(devicesResponse.ok()).toBeTruthy();
  const devices = await devicesResponse.json() as { device_id: number; name: string; latitude: number | null; longitude: number | null }[];
  expect(devices).toEqual(expect.arrayContaining([
    expect.objectContaining({
      device_id: fixture.device_id,
      name: fixture.device_name,
      latitude: expect.any(Number),
      longitude: expect.any(Number),
    }),
  ]));
  await expect(page.locator('.maplibregl-canvas')).toBeVisible();
  await expect(page.getByTitle(fixture.device_name, { exact: true })).toBeVisible();
  await assertNoPageOverflow(page);
  await page.screenshot({ path: testInfo.outputPath(`${screenshotPrefix}-map-device-marker.png`), fullPage: true });

  await page.goto('/analytics');
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.locator('select').first().selectOption('pm25');
  await dialog.getByRole('button', { name: /^(Load Sensors|Cargar sensores)$/ }).click();
  await dialog.getByLabel(/^(Search data streams|Buscar flujos de datos)$/).fill(fixture.device_name);
  const streamButton = dialog.getByRole('button', { name: new RegExp(fixture.device_name) }).first();
  await expect(streamButton).toBeVisible();
  const historyResponsePromise = page.waitForResponse(response =>
    /\/api\/sensors\/\d+\/history(?:\?|$)/.test(response.url()) && response.request().method() === 'GET',
  );
  await streamButton.click();
  const historyResponse = await historyResponsePromise;
  expect(historyResponse.ok()).toBeTruthy();
  const historyBody = await historyResponse.json() as { data: HistoryPoint[] };
  expect(historyBody.data.length).toBeGreaterThan(0);
  for (const value of expectedNativeValues) {
    expect(historyBody.data.map(point => point.value)).toContain(value);
    await expect(page.locator('tbody').getByText(String(value), { exact: true })).toBeVisible();
  }
  await expect(page.locator('canvas')).toBeVisible();
  await expect(page.getByText(fixture.device_name).first()).toBeVisible();
  await assertNoPageOverflow(page);
  await page.screenshot({ path: testInfo.outputPath(`${screenshotPrefix}-analytics-measurements.png`), fullPage: true });

  return {
    map: { deviceId: fixture.device_id, markerVisible: true, measurementsEndpoint: devicesResponse.status() },
    analytics: {
      points: historyBody.data.length,
      historyEndpoint: historyResponse.status(),
      importedValuesVisible: expectedNativeValues,
    },
  };
}

test('rejects the original malformed header accurately and accepts its corrected CSV in English and Spanish', async ({ page }, testInfo) => {
  const qaBaseUrl = requiredEnvironment('CSV_QA_BASE_URL');
  const { dockerContext, databaseContainerId } = getIsolatedDatabaseContainerId();
  const fixturePath = requiredEnvironment('CSV_QA_FIXTURE');
  const invalidCsvPath = requiredEnvironment('CSV_INVALID_FIXTURE');
  const correctedCsvPath = requiredEnvironment('CSV_CORRECTED_FIXTURE');
  const acceptanceReportPath = requiredEnvironment('CSV_HEADER_ACCEPTANCE_REPORT');
  const fixture = JSON.parse(readFileSync(fixturePath, 'utf8')) as Fixture;
  if (
    !fixture.email.startsWith('synthetic-csv-qa-') || !fixture.email.endsWith('@example.com') ||
    !fixture.password || fixture.sensors.length !== 3
  ) {
    throw new Error('CSV browser credentials and sensors must come from the synthetic QA fixture.');
  }
  const sensorIdByName = Object.fromEntries(fixture.sensors.map(sensor => [sensor.name, sensor.id])) as Record<string, number>;
  const sensorIdsByOriginal = new Map([
    ['72', sensorIdByName.flag],
    ['73', sensorIdByName.invalid],
    ['74', sensorIdByName.drift],
  ]);
  if ([...sensorIdsByOriginal.values()].some(sensorId => !sensorId)) {
    throw new Error('The synthetic QA fixture is missing a required sensor.');
  }
  const correctedCsvLines = readFileSync(correctedCsvPath, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/);
  if (correctedCsvLines[0] !== 'internalsensorid,datetime,value') {
    throw new Error('The corrected CSV fixture must use the canonical CompassAQ header.');
  }
  for (let index = 1; index < correctedCsvLines.length; index += 1) {
    const line = correctedCsvLines[index];
    if (!line.trim()) continue;
    const separator = line.indexOf(',');
    const originalSensorId = line.slice(0, separator);
    const seededSensorId = sensorIdsByOriginal.get(originalSensorId);
    if (separator < 1 || !seededSensorId) {
      throw new Error(`The corrected CSV fixture contains an unexpected sensor ID: ${originalSensorId}.`);
    }
    correctedCsvLines[index] = `${seededSensorId}${line.slice(separator)}`;
  }
  const correctedCsvForSeededSensors = testInfo.outputPath('corrected-csv-for-seeded-sensors.csv');
  mkdirSync(dirname(correctedCsvForSeededSensors), { recursive: true });
  writeFileSync(correctedCsvForSeededSensors, correctedCsvLines.join('\n'));
  const databaseMeasurementsAtStart = getDatabaseMeasurementCount(databaseContainerId, dockerContext);
  const scenarios = [
    { language: 'en' as const, width: 1440, height: 1000, name: 'en-desktop' },
    { language: 'en' as const, width: 390, height: 844, name: 'en-mobile' },
    { language: 'es' as const, width: 1440, height: 1000, name: 'es-desktop' },
    { language: 'es' as const, width: 390, height: 844, name: 'es-mobile' },
  ];

  await page.route('https://basemaps.cartocdn.com/gl/positron-gl-style/style.json', route => route.fulfill({ json: {
    version: 8,
    sources: {},
    layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e8eef0' } }],
  } }));
  await page.goto('/login');
  await page.getByLabel('Email').fill(fixture.email);
  await page.getByRole('textbox', { name: 'Password' }).fill(fixture.password);
  const loginResponsePromise = page.waitForResponse(response =>
    response.url().endsWith('/api/auth/login') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.ok()).toBeTruthy();
  const login = await loginResponse.json() as { access_token: string };
  const headers = { Authorization: `Bearer ${login.access_token}` };
  await expect(page).toHaveURL(/\/map(?:\?|$)/);
  const recoverySmoke = await verifyMapAndAnalyticsAfterRecovery(page, fixture, testInfo);
  await page.goto('/admin/uploads/csv');

  const startingEventsResponse = await page.request.get('/api/admin/events?event_type=csv.upload', { headers });
  expect(startingEventsResponse.ok()).toBeTruthy();
  const startingEvents = await startingEventsResponse.json() as { event_id: number }[];
  const startingEventIds = new Set(startingEvents.map(event => event.event_id));

  const sensorIds = fixture.sensors.map(sensor => sensor.id);
  let csvAnalyticsSmoke: unknown = null;
  const scenarioResults: Record<string, unknown>[] = [];
  for (const [index, scenario] of scenarios.entries()) {
    await setLanguage(page, scenario.language);
    await page.setViewportSize({ width: scenario.width, height: scenario.height });
    await selectDestinationDevice(page, fixture, scenario.language);

    const databaseCountBeforeRejection = getDatabaseMeasurementCount(databaseContainerId, dockerContext);
    const beforeRejectedUpload = await getMeasurementSnapshot(page, sensorIds, headers);
    const rejectResponse = await uploadFile(
      page,
      invalidCsvPath,
      scenario.language,
      index === 0,
    );
    expect(rejectResponse.status()).toBe(400);
    const rejectBody = await rejectResponse.json() as { detail: string };
    expect(rejectBody.detail).toBe('missing required CSV columns: internalsensorid, datetime');

    const errorBanner = page.locator('.error-banner[role="alert"]');
    if (scenario.language === 'en') {
      await expect(errorBanner).toContainText('The CSV header must use these required column names: internalsensorid, datetime.');
      await expect(errorBanner).toContainText('Use the supported header: internalsensorid,datetime,value.');
      await expect(errorBanner).toContainText('The file was rejected before any measurements were imported.');
      await expect(errorBanner).not.toContainText('some rows may already have been saved');
    } else {
      await expect(errorBanner).toContainText('El encabezado CSV debe usar estos nombres de columna obligatorios: internalsensorid, datetime.');
      await expect(errorBanner).toContainText('Use el encabezado admitido: internalsensorid,datetime,value.');
      await expect(errorBanner).toContainText('El archivo se rechazó antes de importar mediciones.');
      await expect(errorBanner).not.toContainText('es posible que algunas filas ya se hayan guardado');
    }
    await expect(errorBanner).not.toContainText(rejectBody.detail);
    await expect(errorBanner).not.toContainText(/(?:C:\\|\/app\/|password|credential|secret)/i);
    await expect(page.getByText('D07-wrong-header.csv')).toBeVisible();
    await expect(page.getByRole('button', { name: scenario.language === 'en' ? 'Upload CSV' : 'Subir CSV', exact: true })).toBeEnabled();
    const afterRejectedUpload = await getMeasurementSnapshot(page, sensorIds, headers);
    expect(afterRejectedUpload).toEqual(beforeRejectedUpload);
    expect(getDatabaseMeasurementCount(databaseContainerId, dockerContext)).toBe(databaseCountBeforeRejection);
    await assertNoPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`header-${scenario.name}-rejected.png`), fullPage: true });

    const correctedResponse = await uploadFile(page, correctedCsvForSeededSensors, scenario.language, false);
    expect(correctedResponse.ok()).toBeTruthy();
    const correctedBody = await correctedResponse.json() as {
      success: boolean;
      total_records: number;
      inserted_records: number;
      updated_records: number;
      skipped_records: number;
      failed_records: number;
      qc?: { evaluated: number; passed: number; flagged: number; indeterminate: number };
      event_id?: number;
    };
    expect(correctedBody).toMatchObject({ success: true, total_records: 7, failed_records: 0 });
    if (index === 0) {
      expect(correctedBody).toMatchObject({ inserted_records: 7, updated_records: 0, skipped_records: 0 });
      // The isolated drift sensor has an active baseline rule with an eight-sample
      // minimum and no prior history. Preserve its two explicit warm-up outcomes.
      expect(correctedBody.qc).toMatchObject({ evaluated: 7, passed: 4, flagged: 1, indeterminate: 2 });
      expect(getDatabaseMeasurementCount(databaseContainerId, dockerContext)).toBe(databaseCountBeforeRejection + 7);
      const imported = await getMeasurementSnapshot(page, sensorIds, headers);
      expect(imported).toHaveLength(beforeRejectedUpload.length + 7);
      expect(imported).toEqual(expect.arrayContaining([
        expect.objectContaining({ sensorId: sensorIdByName.flag, timestamp: '2026-10-16T20:00:00.000Z', value: 1.23456789, is_valid: true }),
        expect.objectContaining({ sensorId: sensorIdByName.flag, timestamp: '2026-10-16T20:02:00.000Z', value: 2.34567891, is_valid: true }),
        expect.objectContaining({ sensorId: sensorIdByName.flag, timestamp: '2026-10-16T20:04:00.000Z', value: -11, is_valid: true }),
        expect.objectContaining({ sensorId: sensorIdByName.invalid, timestamp: '2026-10-16T20:00:00.000Z', value: 41.123456789, is_valid: true }),
        expect.objectContaining({ sensorId: sensorIdByName.invalid, timestamp: '2026-10-16T21:00:00.000Z', value: 42.987654321, is_valid: true }),
        expect.objectContaining({ sensorId: sensorIdByName.drift, timestamp: '2026-10-15T00:00:00.000Z', value: 90.123456789, is_valid: true }),
        expect.objectContaining({ sensorId: sensorIdByName.drift, timestamp: '2026-10-16T00:00:00.000Z', value: 98.765432109, is_valid: true }),
      ]));
      const flaggedMeasurement = imported.find(point =>
        point.sensorId === sensorIdByName.flag && point.value === -11,
      );
      expect(flaggedMeasurement?.qc_flags).toContain('min_value');
      expect(flaggedMeasurement?.qc_results).toEqual(expect.arrayContaining([
        expect.objectContaining({
          check_code: 'min_value',
          evaluation_status: 'failed',
          passed: false,
          failure_action: 'flag_for_review',
        }),
      ]));
      const driftWarmup = imported.find(point =>
        point.sensorId === sensorIdByName.drift && point.value === 90.123456789,
      );
      expect(driftWarmup?.qc_results).toEqual(expect.arrayContaining([
        expect.objectContaining({
          check_code: 'baseline_drift',
          evaluation_status: 'indeterminate',
          reason_code: 'insufficient_history',
        }),
      ]));
    } else {
      expect(correctedBody).toMatchObject({ inserted_records: 0, updated_records: 0, skipped_records: 7 });
      expect(getDatabaseMeasurementCount(databaseContainerId, dockerContext)).toBe(databaseCountBeforeRejection);
    }

    const summary = page.locator('.csv-result[role="status"]');
    await expect(summary).toBeVisible();
    await expect(summary).toContainText(scenario.language === 'en' ? 'CSV processing completed.' : 'Se completó el procesamiento del CSV.');
    await assertNoPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`header-${scenario.name}-corrected.png`), fullPage: true });
    if (index === 0) {
      csvAnalyticsSmoke = await verifyMapAndAnalyticsAfterRecovery(
        page,
        fixture,
        testInfo,
        'csv-imported',
        [1.23456789, 2.34567891, -11],
      );
      await page.goto('/admin/uploads/csv');
    }
    scenarioResults.push({
      scenario: scenario.name,
      rejectedStatus: rejectResponse.status(),
      rejectedBeforeMeasurements: beforeRejectedUpload.length,
      rejectedAfterMeasurements: afterRejectedUpload.length,
      correctedStatus: correctedResponse.status(),
      inserted: correctedBody.inserted_records,
      updated: correctedBody.updated_records,
      skipped: correctedBody.skipped_records,
      failed: correctedBody.failed_records,
      eventId: correctedBody.event_id,
    });
  }

  const eventsResponse = await page.request.get('/api/admin/events?event_type=csv.upload', { headers });
  expect(eventsResponse.ok()).toBeTruthy();
  const events = await eventsResponse.json() as { event_id: number; params: Record<string, unknown> }[];
  const newEvents = events.filter(event => !startingEventIds.has(event.event_id));
  expect(newEvents).toHaveLength(8);
  const rejectedEvents = newEvents.filter(event => event.params.error_code === 'csv_file_invalid');
  expect(rejectedEvents).toHaveLength(4);
  for (const event of rejectedEvents) {
    expect(event.params).toMatchObject({ outcome: 'failed', inserted_records: 0, updated_records: 0, skipped_records: 0, failed_records: 0 });
  }
  const successfulEvents = newEvents.filter(event => event.params.outcome === 'success');
  expect(successfulEvents).toHaveLength(4);
  const successfulScenarioEventIds = scenarioResults
    .map(result => result.eventId)
    .filter((eventId): eventId is number => typeof eventId === 'number');
  expect(successfulScenarioEventIds).toHaveLength(4);
  expect(successfulEvents.map(event => event.event_id).sort((left, right) => left - right))
    .toEqual([...successfulScenarioEventIds].sort((left, right) => left - right));
  for (const event of successfulEvents) {
    expect(event.params).toMatchObject({
      outcome: 'success',
      total_records: 7,
      updated_records: 0,
      failed_records: 0,
    });
    if (event.event_id === successfulScenarioEventIds[0]) {
      expect(event.params).toMatchObject({ inserted_records: 7, skipped_records: 0 });
      expect(event.params.qc).toMatchObject({ evaluated: 7, passed: 4, flagged: 1, indeterminate: 2 });
    } else {
      expect(event.params).toMatchObject({ inserted_records: 0, skipped_records: 7 });
    }
  }
  const eventRows = newEvents.map(event => ({
    event_id: event.event_id,
    outcome: event.params.outcome,
    error_code: event.params.error_code ?? null,
    total_records: event.params.total_records,
    inserted_records: event.params.inserted_records,
    updated_records: event.params.updated_records,
    skipped_records: event.params.skipped_records,
    failed_records: event.params.failed_records,
    qc: event.params.qc ?? null,
  }));
  writeFileSync(acceptanceReportPath!, JSON.stringify({
    appBaseUrl: qaBaseUrl,
    recoverySmoke,
    csvAnalyticsSmoke,
    databaseMeasurementsAtStart,
    databaseMeasurementsAfterAllScenarios: getDatabaseMeasurementCount(databaseContainerId, dockerContext),
    measurementsAfterAllScenarios: (await getMeasurementSnapshot(page, sensorIds, headers)).length,
    rejectedEvents: rejectedEvents.length,
    successfulEvents: successfulEvents.length,
    eventRows,
    uploadEventsAtStart: startingEvents.length,
    scenarios: scenarioResults,
  }, null, 2));
});
