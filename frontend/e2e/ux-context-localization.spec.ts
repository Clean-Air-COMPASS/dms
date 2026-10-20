import { test, expect } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import { standards, aqiHistory } from './fixtures/uxAnalytics';
import enAdmin from '../src/i18n/locales/en/admin.json' with { type: 'json' };
import esAdmin from '../src/i18n/locales/es/admin.json' with { type: 'json' };
import enAuth from '../src/i18n/locales/en/auth.json' with { type: 'json' };
import esAuth from '../src/i18n/locales/es/auth.json' with { type: 'json' };

for (const language of ['en', 'es'] as const) for (const width of [1440, 390]) {
  test(`focused UX context and localization ${language} ${width}`, async ({ page }) => {
    await page.addInitScript(() => {
      if (window.PublicKeyCredential) PublicKeyCredential.isConditionalMediationAvailable = async () => false;
    });
    await page.setViewportSize({ width, height: 844 });
    await mockAdministration(page, language);
    const csv = (language === 'en' ? enAdmin : esAdmin).adminCsvUpload;
    const capture = async (name: string) => {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: `../artifacts/ux-context/${language}-${width}/${name}.png`, fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    };
    await page.route('**/api/devices/123/sensors', route => route.fulfill({ json: [{ sensor_id: 77, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³' }] }));
    await page.goto('/admin/uploads/csv');
    await expect(page.getByText(csv.text.unitRequirement)).toBeVisible();
    await page.getByRole('button', { name: 'Central Library', exact: true }).click();
    await expect(page.getByText(/77 ·/)).toBeVisible();
    await expect(page.getByText(/America\/Los_Angeles/)).toBeVisible();
    await capture('csv-instructions-reference');
    await page.getByRole('button', { name: csv.actions.uploadCsv, exact: true }).click();
    await expect(page.getByRole('alert')).toContainText(csv.messages.pleaseChooseCsvFileFirst);
    await capture('csv-validation');
    await page.locator('input[type=file]').setInputFiles({ name: 'fixture.csv', mimeType: 'text/csv', buffer: Buffer.from('internalsensorid,datetime,value\n77,2026-09-05T00:00:00Z,12.5') });
    await page.getByRole('button', { name: csv.actions.uploadCsv, exact: true }).click();
    await expect(page.getByText(csv.summary.partial)).toBeVisible();
    await capture('csv-partial-summary');
    await page.route('**/api/admin/imports/upload-csv', route => route.fulfill({ json: { success: true, message: 'English backend summary', total_records: 1, inserted_records: 1, failed_records: 0, errors: [] } }));
    await page.getByRole('button', { name: csv.actions.uploadCsv, exact: true }).click();
    await expect(page.getByText(csv.summary.success)).toBeVisible();
    await capture('csv-success');

    await page.goto('/admin/sources/1');
    const minute = page.getByRole('spinbutton', { name: /Rate limit.*minute|Límite.*minuto/i });
    await minute.focus();
    await expect(minute).toBeFocused();
    await page.keyboard.press('ArrowUp');
    await page.keyboard.press('Tab');
    await expect(page.getByRole('spinbutton', { name: /Rate limit.*hour|Límite.*hora/i })).toBeFocused();
    await capture('openaq-keyboard-focus');

    await page.goto('/admin/events');
    const refresh = page.getByRole('combobox', { name: language === 'en' ? 'Refresh interval' : 'Intervalo de actualización' });
    await refresh.focus();
    await expect(refresh).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(refresh).toHaveValue('60');
    await capture('events-keyboard-focus');

    await page.route('**/api/admin/qc/parameters/1/policy', route => route.fulfill({ status: 503, json: { detail: 'Fixture failure' } }));
    await page.goto('/admin/qc/parameters/1');
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.locator('.breadcrumbs a[href="/admin/qc"]')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('1');
    await page.getByRole('button', { name: /Try again|Reintentar/ }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await capture('qc-failure');
    for (const [routePath, apiPath, name] of [
      ['/admin/qc/sensors/77', '/admin/qc/sensors/77/policy', 'qc-sensor-failure'],
      ['/admin/qc/parameters/1/sources/1', '/admin/qc/sources/1/parameters/1/policy', 'qc-source-failure'],
    ]) {
      await page.route('**/api' + apiPath, route => route.fulfill({ status: 503, json: {} }));
      await page.goto(routePath);
      await expect(page.getByRole('alert')).toBeVisible();
      await expect(page.locator('.breadcrumbs a[href="/admin/qc"]')).toBeVisible();
      await capture(name);
    }

    await page.route('**/api/air-quality-index/standards', route => route.fulfill({ json: standards }));
    await page.route('**/api/devices', route => route.fulfill({ json: [{ device_id: 1, name: 'Synthetic AQI station', timezone: 'UTC', sensor_count: 1 }] }));
    const history = structuredClone(aqiHistory);
    history.series = [history.series[0]];
    history.series[0].points = history.series[0].points.map(point => ({ ...point, numeric_value: null, category_code: null, category_label: null, normalized_concentration: null, preprocessed_concentration: null, calculation_status: 'unavailable', coverage_status: 'none', exclusion_reason: 'unsupported_unit' }));
    await page.route('**/api/air-quality-index/analytics-history', route => route.fulfill({ json: history }));
    const query = new URLSearchParams({ series: 'aqi|us_epa|us_epa.pm25.nowcast|1', start: '2026-08-01T00:00:00Z', end: '2026-08-02T00:00:00Z', timezone: 'utc' });
    await page.goto(`/analytics?${query}`);
    await expect(page.getByText(language === 'en' ? 'AQI history is unavailable for this series in the selected time range.' : 'El historial de ICA no está disponible para esta serie en el intervalo seleccionado.')).toBeVisible();
    const value = page.getByRole('columnheader').filter({ has: page.getByRole('button', { name: /^Value|^Valor/ }) });
    await value.getByRole('button').focus();
    await page.keyboard.press('Enter');
    await expect(value).toHaveAttribute('aria-sort', 'ascending');
    await page.keyboard.press('Space');
    await expect(value).toHaveAttribute('aria-sort', 'descending');
    await expect(value.getByRole('button')).toBeFocused();
    await capture('analytics-unavailable-keyboard-sort');

    await page.route('**/api/admin/users/roles', route => route.fulfill({ json: ['admin', 'analyst', 'viewer'].map((name, index) => ({ role_id: String(index), name, description: 'English backend description' })) }));
    await page.goto('/admin/users/new');
    await expect(page.getByRole('checkbox', { name: /^Administrator|^Administrador/ })).toBeVisible();
    await capture('translated-roles');

    // Map is the latest/current spatial view; historical date exploration belongs in Analytics.
    await page.goto('/map?mode=pollutants');
    if (width === 390) await page.getByRole('button', { name: /^(Map controls|Controles del mapa)$/ }).click();
    await expect(page.getByRole('combobox', { name: language === 'en' ? 'Layer' : 'Capa', exact: true })).toHaveValue('measurements');
    await expect(page.locator('.map-canvas')).toBeVisible();
    await expect(page.getByLabel(language === 'en' ? 'Time resolution' : 'Resolución temporal', { exact: true })).toBeVisible();
    await expect(page.locator('.map-loading')).toHaveCount(0);
    await expect(page.getByTestId('map-empty-state')).toBeVisible();
    await expect(page.getByRole('button', { name: /Open custom date range picker|Abrir selector.*personalizado/i })).toHaveCount(0);
    await expect(page.getByLabel(/Time window presets|Opciones de ventana de tiempo/i)).toHaveCount(0);
    const analyticsLink = page.getByRole('link', { name: language === 'en' ? 'Analytics' : 'Análisis', exact: true });
    await expect(analyticsLink).toBeVisible();
    await capture('map-current-view');
    await analyticsLink.click();
    await expect(page).toHaveURL(/\/analytics(?:\?|$)/);
    const analyticsUrl = new URL(page.url());
    expect(analyticsUrl.pathname).toBe('/analytics');
    expect(analyticsUrl.searchParams.get('start')).toBeTruthy();
    expect(analyticsUrl.searchParams.get('end')).toBeTruthy();

    await page.route('**/api/auth/refresh', route => route.fulfill({ status: 401, json: {} }));
    await page.route('**/api/auth/me', route => route.fulfill({ status: 401, json: {} }));
    await page.goto('/login');
    const auth = (language === 'en' ? enAuth : esAuth).loginPage;
    for (const status of [401, 503, 429]) {
      await page.route('**/api/auth/login', route => route.fulfill({ status, json: { detail: 'Private backend diagnostic' } }));
      await page.locator('#email').fill('fixture@example.org');
      await page.locator('#password').fill('fixture-password');
      await page.getByRole('button', { name: auth.actions.signIn, exact: true }).click();
      await expect(page.getByRole('alert')).toHaveText(status === 401 ? auth.messages.invalidCredentials : status === 429 ? auth.messages.tooManyAttempts : auth.messages.serviceUnavailable);
      await capture(`login-${status}`);
    }
  });
}
