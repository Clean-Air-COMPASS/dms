import { expect, test } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import en from '../src/i18n/locales/en/qualityControl.json' with { type: 'json' };
import es from '../src/i18n/locales/es/qualityControl.json' with { type: 'json' };

for (const language of ['en', 'es'] as const) for (const width of [1440, 390]) {
  test(`Baseline shift indicator copy ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await mockAdministration(page, language);
    const copy = language === 'en' ? en : es;
    const unit = { unit_id: 1, unit_code: 'ug_m3', symbol: 'µg/m³', name: 'Micrograms per cubic meter' };
    const settings = { lookback_hours: 168, min_samples: 72, baseline_quantile: 0.1, max_drift_per_day: 5, direction: 'both' };
    await page.route('**/api/admin/qc/checks', route => route.fulfill({ json: { items: [{
      check_code: 'baseline_drift', display_name: 'Baseline Drift', description: '', available: true,
      plugin_version: '1.1.0', qc_api: 1, origin: 'built_in', required_access: 'db-read',
      unit_settings: ['max_drift_per_day'], overview: { visible: true, label: 'Baseline Drift', order: 30, summary_setting: null },
      settings: Object.keys(settings).map(setting_code => ({ setting_code, value_type: setting_code === 'direction' ? 'string' : 'number', label: setting_code, help_text: '', required: true, choices: setting_code === 'direction' ? ['up', 'down', 'both'] : null })),
      failure_actions: ['flag_for_review', 'mark_invalid'],
    }] } }));
    await page.route('**/api/admin/qc/parameters/1/policy', route => route.fulfill({ json: {
      scope: { scope_type: 'parameter', parameter_id: 1, external_api_id: null, sensor_id: null },
      parameter: { parameter_id: 1, parameter_code: 'pm25', display_name: 'Synthetic PM2.5 fixture', default_unit: unit, supported_units: [unit] },
      data_source: null, sensor: null, default_profile_version: '2026.2', overrides: [],
      checks: [{ check_code: 'baseline_drift', enabled: false, status: 'disabled', configured_settings: settings,
        evaluation_settings: {}, failure_action: 'flag_for_review', configured_unit_code: 'ug_m3', evaluation_unit_code: 'ug_m3', applicable_unit_code: 'ug_m3', unit_conversion: null,
        reason_code: 'disabled', message: '', applicability: 'applicable', default_profile_version: '2026.2',
        applied_layers: [], property_provenance: {}, most_specific_source: { layer: 'compassaq_default', label: 'CompassAQ default', qc_rule_id: null, rule_version: null, default_profile_version: '2026.2', policy_unit_code: 'ug_m3' } }],
    } }));
    await page.goto('/admin/qc/parameters/1');
    const card = page.locator('article').filter({ has: page.getByRole('heading', { name: copy.checks.baselineDrift.name }) });
    await expect(card.getByText(copy.checks.baselineDrift.description)).toBeVisible();
    await expect(card).toContainText(copy.checks.baselineDrift.settings.max_drift_per_day.label);
    await card.screenshot({ path: `../artifacts/baseline-drift/${language}-${width}-preset.png` });
    await card.getByRole('button', { name: language === 'en' ? 'Review and enable' : 'Revisar y activar', exact: true }).click();
    const enableCheck = card.getByRole('checkbox', { name: new RegExp(copy.editor.enableCheck) });
    await expect(enableCheck).not.toBeChecked();
    await enableCheck.focus();
    await expect(enableCheck).toBeFocused();
    await enableCheck.press('Space');
    await expect(enableCheck).toBeChecked();
    await expect(page.getByLabel(copy.checks.baselineDrift.settings.max_drift_per_day.label, { exact: true })).toHaveValue('5');
    await expect(page.getByText(copy.checks.baselineDrift.settings.max_drift_per_day.help, { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator('.qc-check-editor').screenshot({ path: `../artifacts/baseline-drift/${language}-${width}-editor.png` });

    const issue = {
      measurement_qc_result_id: 1, measurement_id: 1, qc_result_created_at: '2026-10-06T12:00:00Z',
      measurement_observed_at: '2026-10-06T12:00:00Z', measurement_value: 18.4, measurement_is_valid: true,
      device_id: 1, device_name: 'Synthetic baseline fixture', sensor_id: 1, external_sensor_id: 'synthetic-pm25',
      data_source_id: 1, data_source_name: 'Synthetic source', provider_code: 'test', parameter_code: 'pm25',
      parameter_name: 'PM2.5', unit_code: 'ug_m3', unit_symbol: 'µg/m³', check_code: 'baseline_drift',
      check_name: 'Baseline Drift', evaluation_status: 'failed', failure_action: 'flag_for_review',
      reason_code: null, message: '', details: { drift_per_day: 6 }, params_snapshot: { max_drift_per_day: 5, direction: 'both' },
      rule_source: 'sensor_override', policy_snapshot: {}, policy_provenance: {}, plugin_version: '1.1.0',
    };
    await page.route('**/api/admin/events/qc-failures*', route => route.fulfill({ json: {
      items: [issue, { ...issue, measurement_qc_result_id: 2, evaluation_status: 'indeterminate', reason_code: 'insufficient_history', details: {} }],
      total: 2, limit: 25, offset: 0,
    } }));
    await page.goto('/admin/events?tab=qc-failures');
    await page.locator('.qc-failure-provenance summary').first().click();
    await expect(page.getByText(language === 'en' ? 'Baseline shift indicator' : 'Indicador de cambio de línea base', { exact: true }).first()).toBeVisible();
    await expect(page.getByText(language === 'en' ? /enough valid history/ : /suficiente historial válido/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator('.qc-failure-table-container').evaluate(element => { element.scrollLeft = element.scrollWidth; });
    await page.locator('.qc-failure-table').screenshot({ path: `../artifacts/baseline-drift/${language}-${width}-events.png` });
    expect(state.writes.filter(path => path !== '/auth/refresh')).toEqual([]);
  });
}
