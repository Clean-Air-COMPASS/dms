import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ADMIN_EMAIL = process.env.QC_E2E_ADMIN_EMAIL ?? 'qc-acceptance@example.com';
const ADMIN_PASSWORD = process.env.QC_E2E_ADMIN_PASSWORD ?? 'CompassAQ-QC-Phase3!2026';
const ARTIFACT_DIRECTORY = resolve('../artifacts/qc-phase3');

async function capture(page: Page, testInfo: TestInfo, name: string) {
  mkdirSync(ARTIFACT_DIRECTORY, { recursive: true });
  const path = resolve(ARTIFACT_DIRECTORY, `${name}.png`);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

async function ensureFreshInstallation(page: Page) {
  const statusResponse = await page.request.get('/api/setup/status');
  expect(statusResponse.ok()).toBeTruthy();
  const status = await statusResponse.json();
  if (!status.is_setup_required) return;

  const adminResponse = await page.request.post('/api/setup/admin', {
    data: {
      email: ADMIN_EMAIL,
      password: ADMIN_PASSWORD,
      confirm_password: ADMIN_PASSWORD,
    },
  });
  expect(adminResponse.ok(), await adminResponse.text()).toBeTruthy();

  const completeResponse = await page.request.post('/api/setup/complete', {
    data: { default_language_code: 'en' },
  });
  expect(completeResponse.ok(), await completeResponse.text()).toBeTruthy();
}

async function signIn(page: Page) {
  await page.goto('/login');
  await page.getByLabel('Email').fill(ADMIN_EMAIL);
  await page.getByRole('textbox', { name: 'Password' }).fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/map(?:\?|$)/);
}

async function changeLanguage(page: Page, language: 'en' | 'es') {
  const currentLanguage = await page.locator('html').getAttribute('lang');
  if (currentLanguage === language) return;
  const accountMenuName = currentLanguage === 'es'
    ? `Menú de cuenta para ${ADMIN_EMAIL}`
    : `Account menu for ${ADMIN_EMAIL}`;
  const languageLabel = currentLanguage === 'es' ? 'Idioma' : 'Language';
  const languageSelect = page.getByLabel(languageLabel);
  if (!await languageSelect.isVisible()) {
    await page.getByRole('button', { name: accountMenuName }).click();
  }
  await languageSelect.selectOption(language);
  await expect(page.locator('html')).toHaveAttribute('lang', language);
}

function checkCard(page: Page, heading: string) {
  return page.locator('article.qc-check-card').filter({
    has: page.getByRole('heading', { name: heading, exact: true }),
  });
}

test('Baseline Drift default posture is explicit and responsive', async ({ page }, testInfo) => {
  await ensureFreshInstallation(page);
  await signIn(page);
  await changeLanguage(page, 'en');

  await page.goto('/admin/qc');
  const pm25Link = page.getByRole('link', { name: 'Open PM2.5 quality control settings' });
  await expect(pm25Link).toContainText('Off by default');
  await expect(pm25Link).toContainText(/\d+ sensors? On/);
  await expect(pm25Link).toContainText(/\d+ sources? · \d+ sensors?/);
  await expect(page.getByText('Maximum', { exact: true })).toBeVisible();
  await capture(page, testInfo, 'baseline-overview-en-desktop');

  await page.setViewportSize({ width: 820, height: 1180 });
  await expect(pm25Link.getByText(/\d+ sensors? On/)).toBeVisible();
  await capture(page, testInfo, 'baseline-overview-en-tablet');

  await pm25Link.click();
  const parameterPolicyUrl = page.url();
  const baselineDrift = checkCard(page, 'Baseline drift');
  await expect(baselineDrift).toContainText('CompassAQ screening preset');
  await expect(baselineDrift).toContainText('Suggested screening settings');
  await expect(baselineDrift).toContainText('5 µg/m³');
  await page.setViewportSize({ width: 1280, height: 720 });
  await capture(page, testInfo, 'baseline-preset-en-desktop');

  await page.setViewportSize({ width: 820, height: 1180 });
  await expect(baselineDrift.getByText('Suggested screening settings')).toBeVisible();
  await capture(page, testInfo, 'baseline-preset-en-tablet');

  await baselineDrift.getByRole('button', { name: 'Review and enable' }).click();
  await baselineDrift.getByRole('checkbox').check();
  await baselineDrift.getByRole('button', { name: 'Save changes' }).click();
  await expect(baselineDrift).toContainText('On');
  await baselineDrift.getByRole('button', { name: 'Reset this check to the disabled CompassAQ screening preset' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Reset check' }).click();
  await expect(baselineDrift).toContainText('Off');

  await page.getByRole('button', { name: `Account menu for ${ADMIN_EMAIL}` }).click();
  await page.getByLabel('Language').selectOption('es');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/admin/qc');
  const spanishPm25Link = page.getByRole('link', {
    name: 'Abrir la configuración de control de calidad de PM2.5',
  });
  await expect(spanishPm25Link).toContainText('Desactivada de forma predeterminada');
  await expect(spanishPm25Link).toContainText(/\d+ (?:sensor activado|sensores activados)/);
  await capture(page, testInfo, 'baseline-overview-es-mobile');

  await page.goto(parameterPolicyUrl);
  const spanishBaselineDrift = checkCard(page, 'Deriva de línea base');
  await expect(spanishBaselineDrift).toContainText('Desactivada');
  await expect(spanishBaselineDrift).toContainText('Preajuste de detección de CompassAQ');
  await expect(spanishBaselineDrift).toContainText('Configuración de detección sugerida');
  await expect(spanishBaselineDrift).toContainText('5 µg/m³');
  await capture(page, testInfo, 'baseline-preset-es-mobile');

  await page.getByRole('button', { name: `Menú de cuenta para ${ADMIN_EMAIL}` }).click();
  await page.getByLabel('Idioma').selectOption('en');
});

test('administrator completes the production QC policy workflow', async ({ page }, testInfo) => {
  const evidence: Array<{ checkpoint: string; result: 'passed' }> = [];
  const passed = (checkpoint: string) => evidence.push({ checkpoint, result: 'passed' });

  await ensureFreshInstallation(page);
  await signIn(page);
  await changeLanguage(page, 'en');

  await page.goto('/admin/qc');
  await expect(page.getByRole('heading', { name: 'Quality control', exact: true })).toBeVisible();
  const pm25Link = page.getByRole('link', { name: 'Open PM2.5 quality control settings' });
  await expect(pm25Link).toBeVisible();
  await expect(pm25Link).toContainText('Off');
  await capture(page, testInfo, '01-parameter-default-en-desktop');
  passed('parameter recommendation visible');

  await pm25Link.click();
  await expect(page.getByRole('heading', { name: 'PM2.5', exact: true })).toBeVisible();
  const parameterPolicyUrl = page.url();
  await expect(checkCard(page, 'Maximum plausible value')).toContainText('CompassAQ recommended value');
  const baselineDrift = checkCard(page, 'Baseline drift');
  await expect(baselineDrift).toContainText('CompassAQ screening preset');
  await expect(baselineDrift).toContainText('Suggested screening settings');
  await expect(baselineDrift).toContainText('5 µg/m³');
  await capture(page, testInfo, '01b-baseline-preset-en-desktop');
  await page.setViewportSize({ width: 820, height: 1180 });
  await expect(baselineDrift.getByText('Suggested screening settings')).toBeVisible();
  await capture(page, testInfo, '01c-baseline-preset-en-tablet');
  await page.setViewportSize({ width: 1280, height: 720 });
  await baselineDrift.getByRole('button', { name: 'Review and enable' }).click();
  await expect(baselineDrift.getByRole('checkbox')).not.toBeChecked();
  await baselineDrift.getByRole('checkbox').check();
  await expect(baselineDrift.getByLabel('Lookback hours')).toHaveValue('168');
  await expect(baselineDrift.getByLabel('Minimum measurements')).toHaveValue('72');
  await expect(baselineDrift.getByLabel('Maximum drift per day')).toHaveValue('5');
  await baselineDrift.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('status')).toContainText('Quality control settings saved.');
  await expect(baselineDrift).toContainText('On');
  passed('Baseline Drift screening preset was visible Off and deliberately enabled');

  await baselineDrift.getByRole('button', { name: 'Reset this check to the disabled CompassAQ screening preset' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Reset check' }).click();
  await expect(page.getByRole('status')).toContainText('The check now uses its inherited settings.');
  await expect(baselineDrift).toContainText('Off');
  passed('Baseline Drift reset restored the disabled shipped state');

  const existingOpenAqException = page.getByRole('link', { name: /OpenAQ/ });
  if (await existingOpenAqException.count()) {
    await existingOpenAqException.first().click();
    await page.getByRole('button', { name: 'Remove exception' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Remove exception' }).click();
    await page.goto(parameterPolicyUrl);
  }
  await page.getByRole('button', { name: 'Add data-source exception' }).click();
  await page.getByLabel('Data source').selectOption({ label: 'OpenAQ' });
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('heading', { name: 'OpenAQ PM2.5' })).toBeVisible();
  const sourcePolicyUrl = page.url();
  await expect(page.getByText('OpenAQ currently uses all PM2.5 settings.')).toBeVisible();

  const sourceMaximum = checkCard(page, 'Maximum plausible value');
  await sourceMaximum.getByRole('button', { name: 'Customize' }).click();
  await sourceMaximum.getByLabel('Maximum plausible value').fill('125');
  await sourceMaximum.getByRole('button', { name: 'Preview impact' }).click();
  await expect(sourceMaximum.getByRole('heading', { name: 'Preview impact' })).toBeVisible();
  await expect(sourceMaximum.getByText(
    /Based on \d+ measurements from the last 24 hours|No recent measurements are available to preview this change\./,
  )).toBeVisible();
  await sourceMaximum.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('status')).toContainText('Quality control settings saved.');
  await expect(sourceMaximum).toContainText('Customized for OpenAQ');
  await capture(page, testInfo, '02-source-exception-en-desktop');
  passed('source exception previewed, saved, and attributed');

  await page.getByRole('link', { name: 'PM2.5', exact: true }).click();
  await page.getByRole('link', { name: 'Find a sensor' }).click();
  await expect(page.getByRole('heading', { name: 'Find a sensor' })).toBeVisible();
  const referenceSensor = page.getByRole('link', {
    name: 'Open PM2.5 quality control for Elizabeth Trailer',
  });
  await expect(referenceSensor).toBeVisible();
  await referenceSensor.click();
  await expect(page.getByRole('heading', { name: 'PM2.5 QC for Elizabeth Trailer' })).toBeVisible();
  await expect(page.getByText('Uses normal inherited QC')).toBeVisible();
  await expect(checkCard(page, 'Maximum plausible value')).toContainText('OpenAQ PM2.5 setting');
  await capture(page, testInfo, '03-sensor-inherited-en-desktop');
  passed('reference sensor inherited effective policy is visible');

  const sensorMinimum = checkCard(page, 'Minimum plausible value');
  await sensorMinimum.getByRole('button', { name: 'Customize' }).click();
  await sensorMinimum.getByLabel('Minimum plausible value').fill('-12');
  await sensorMinimum.getByRole('button', { name: 'Preview impact' }).click();
  await expect(sensorMinimum.getByRole('heading', { name: 'Preview impact' })).toBeVisible();
  await sensorMinimum.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('status')).toContainText('Sensor quality control saved.');
  await expect(sensorMinimum).toContainText('Custom for this sensor');
  await expect(checkCard(page, 'Maximum plausible value')).toContainText('OpenAQ PM2.5 setting');
  await capture(page, testInfo, '04-sensor-custom-en-desktop');
  passed('one sensor property previewed, saved, and attributed without changing inherited properties');

  await sensorMinimum.getByRole('button', { name: 'Edit settings' }).click();
  await sensorMinimum.getByRole('button', { name: /Use CompassAQ PM2\.5 recommendation/ }).click();
  await sensorMinimum.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('status')).toContainText('Sensor quality control saved.');
  passed('sensor property reset restored inheritance');

  await sensorMinimum.getByRole('button', { name: 'Customize' }).click();
  await sensorMinimum.getByLabel('Minimum plausible value').fill('-11');
  await sensorMinimum.getByRole('button', { name: 'Save changes' }).click();
  await sensorMinimum.getByRole('button', { name: 'Reset custom settings for Minimum plausible value' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Reset check' }).click();
  await expect(page.getByRole('status')).toContainText('This check now uses its inherited settings.');
  passed('sensor check reset restored inheritance');

  await sensorMinimum.getByRole('button', { name: 'Customize' }).click();
  await sensorMinimum.getByLabel('Minimum plausible value').fill('-9');
  await sensorMinimum.getByRole('button', { name: 'Save changes' }).click();
  await page.getByRole('button', { name: 'Reset all custom QC' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Reset all custom QC' }).click();
  await expect(page.getByRole('status')).toContainText('All ordinary sensor-specific QC settings were reset.');
  passed('full sensor reset restored inheritance');

  await page.goto(sourcePolicyUrl);
  await page.getByRole('button', { name: 'Remove exception' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Remove exception' }).click();
  await expect(page.getByRole('status')).toContainText('The data-source exception was removed.');
  passed('source exception reset restored parameter behavior');

  await page.goto('/admin/qc/extensions');
  await expect(page.getByRole('heading', { name: 'QC extensions' })).toBeVisible();
  const maximumExtension = page.locator('article.qc-extension-card').filter({
    has: page.getByRole('heading', { name: 'Maximum plausible value', exact: true }),
  });
  await expect(maximumExtension).toContainText('Installed package');
  await expect(page.getByText('No extension discovery issues were reported.')).toBeVisible();
  passed('installed max_value entry-point plugin is visible');

  await page.route('**/api/admin/plugins', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: {
        ...body,
        plugins: body.plugins.filter((plugin: { name: string }) => plugin.name !== 'max_value'),
        unavailable_checks: [{
          check_code: 'max_value',
          display_name: 'Maximum value',
          reason_code: 'plugin_unavailable',
          configured_rule_count: 1,
        }],
      },
    });
  });
  await page.reload();
  await expect(page.getByText('Maximum plausible value is unavailable')).toBeVisible();
  await expect(page.getByText('plugin_unavailable')).toBeVisible();
  await capture(page, testInfo, '05-unavailable-plugin-en-desktop');
  passed('unavailable plugin is human-readable in deployment diagnostics');

  await page.getByRole('button', { name: `Account menu for ${ADMIN_EMAIL}` }).click();
  await page.getByLabel('Language').selectOption('es');
  await expect(page.getByRole('heading', { name: 'Extensiones de calidad' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText('Valor plausible máximo no está disponible')).toBeVisible();
  await page.getByRole('button', { name: `Menú de cuenta para ${ADMIN_EMAIL}` }).click();
  await capture(page, testInfo, '06-unavailable-plugin-es-mobile');
  passed('Spanish mobile unavailable-plugin state is readable');

  await page.unroute('**/api/admin/plugins');
  await page.goto(parameterPolicyUrl);
  const spanishBaselineDrift = checkCard(page, 'Deriva de línea base');
  await expect(spanishBaselineDrift).toContainText('Desactivada');
  await expect(spanishBaselineDrift).toContainText('Preajuste de detección de CompassAQ');
  await expect(spanishBaselineDrift).toContainText('Configuración de detección sugerida');
  await expect(spanishBaselineDrift).toContainText('5 µg/m³');
  await capture(page, testInfo, '07-baseline-preset-es-mobile');
  passed('Baseline Drift disabled screening preset is readable in Spanish mobile');
  await changeLanguage(page, 'en');

  mkdirSync(ARTIFACT_DIRECTORY, { recursive: true });
  writeFileSync(
    resolve(ARTIFACT_DIRECTORY, 'browser-acceptance.json'),
    `${JSON.stringify({ schema_version: 1, result: 'passed', checkpoints: evidence }, null, 2)}\n`,
    'utf8',
  );
});

test('application-unknown QC provenance is readable in Events', async ({ page }, testInfo) => {
  await ensureFreshInstallation(page);
  await signIn(page);
  await changeLanguage(page, 'en');
  await page.route('**/api/admin/events/qc-failures**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      json: {
        items: [{
          measurement_qc_result_id: 99001,
          qc_result_created_at: '2026-08-27T20:01:00Z',
          measurement_id: 88001,
          measurement_observed_at: '2026-08-27T20:00:00Z',
          measurement_value: 55,
          measurement_is_valid: true,
          device_id: 12,
          device_name: 'Reference plugin sensor',
          sensor_id: 812,
          external_sensor_id: 'reference:pm25',
          data_source_id: 2,
          data_source_name: 'Test data source',
          provider_code: 'test-provider',
          parameter_code: 'pm25',
          parameter_name: 'PM2.5',
          unit_code: 'ug_m3',
          unit_symbol: 'µg/m³',
          check_code: 'reference_threshold',
          check_name: 'Reference Threshold QC Check',
          plugin_version: '1.0.0',
          evaluation_status: 'failed',
          failure_action: 'flag_for_review',
          reason_code: 'above_reference_threshold',
          message: 'Value 55 exceeds the configured threshold 42',
          details: { value: 55, threshold: 42 },
          params_snapshot: { limit: 42 },
          rule_source: 'parameter_override',
          policy_snapshot: { default_profile_version: '2026.2', status: 'ready' },
          policy_provenance: { 'settings.limit': { layer: 'parameter_override' } },
        }],
        total: 1,
        limit: 25,
        offset: 0,
      },
    });
  });

  await page.goto('/admin/events?tab=qc-failures');
  await expect(page.getByRole('tab', { name: 'QC failures' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('Reference Threshold QC Check')).toBeVisible();
  await page.getByText('View QC provenance').click();
  await expect(page.getByText('Plugin version')).toBeVisible();
  await expect(page.getByText('1.0.0')).toBeVisible();
  await capture(page, testInfo, '08-reference-plugin-events-en-desktop');

  await changeLanguage(page, 'es');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('tab', { name: 'Fallas de CC' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('Reference Threshold QC Check')).toBeVisible();
  await expect(page.getByText('Versión del plugin')).toBeVisible();
  if (await page.getByLabel('Idioma').isVisible()) {
    await page.getByRole('button', { name: `Menú de cuenta para ${ADMIN_EMAIL}` }).click();
  }
  const mobileLayout = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    scrollX: window.scrollX,
  }));
  expect(mobileLayout.documentWidth).toBeLessThanOrEqual(mobileLayout.viewportWidth);
  expect(mobileLayout.scrollX).toBe(0);
  await capture(page, testInfo, '09-reference-plugin-events-es-mobile');

  await changeLanguage(page, 'en');
});
