import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { mockAdministration, stamp } from './fixtures/administration';
import enQc from '../src/i18n/locales/en/qualityControl.json' with { type: 'json' };
import esQc from '../src/i18n/locales/es/qualityControl.json' with { type: 'json' };
import enEmail from '../src/i18n/locales/en/emailNotifications.json' with { type: 'json' };
import esEmail from '../src/i18n/locales/es/emailNotifications.json' with { type: 'json' };
import type { QcResolvedCheck, QcParameterSummary } from '../src/qc/types';

const unit = { unit_id: 1, unit_code: 'ug_m3', symbol: 'µg/m³', name: 'Micrograms per cubic meter' };
function check(code: string, enabled: boolean, settings: Record<string, unknown>): QcResolvedCheck {
  return { check_code: code, enabled, status: enabled ? 'ready' : 'disabled', configured_settings: settings, evaluation_settings: enabled ? settings : {}, failure_action: 'flag_for_review', configured_unit_code: 'ug_m3', evaluation_unit_code: 'ug_m3', applicable_unit_code: 'ug_m3', unit_conversion: null, reason_code: enabled ? null : 'disabled', message: '', applicability: 'applicable', default_profile_version: '2026.2', applied_layers: [], property_provenance: {}, most_specific_source: { layer: 'compassaq_default', label: 'CompassAQ default', qc_rule_id: null, rule_version: null, default_profile_version: '2026.2', policy_unit_code: 'ug_m3' } };
}
const recommended = [check('min_value', true, { min: -10 }), check('max_value', true, { max: 1000 }), check('baseline_drift', false, {})];
const parameter = (id: number, name: string, checks: QcResolvedCheck[], custom = 0, supported = true): QcParameterSummary => ({ parameter_id: id, parameter_code: name, display_name: name, default_unit: unit, supported_units: [unit], supported, checks, sensor_count: 5, parameter_override_count: custom, source_override_count: 0, sensor_override_count: 0, source_exception_count: 0, sensor_exception_count: 0, baseline_drift_source_override_count: 0, baseline_drift_sensor_override_count: 0, baseline_drift_enabled_source_count: 0, baseline_drift_enabled_sensor_count: 0 });

for (const language of ['en', 'es'] as const) for (const width of [1440, 1280, 390]) {
  test(`QC native checkbox ${language} ${width}`, async ({ page }) => {
    page.setDefaultTimeout(15000);
    await mockAdministration(page, language);
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.setViewportSize({ width, height: 1000 });
    await page.route('**/api/admin/qc/checks', route => route.fulfill({ json: { items: [{
      check_code: 'baseline_drift', display_name: 'Baseline drift', description: '', available: true,
      plugin_version: '1', qc_api: 1, origin: 'built_in', required_access: 'db-read',
      unit_settings: [], overview: { visible: true, label: 'Baseline drift', order: 1, summary_setting: null },
      settings: [], failure_actions: ['flag_for_review', 'mark_invalid'],
    }] } }));
    await page.route('**/api/admin/qc/parameters/1/policy', route => route.fulfill({ json: {
      scope: { scope_type: 'parameter', parameter_id: 1, external_api_id: null, sensor_id: null },
      parameter: parameter(1, 'PM2.5', []), data_source: null, sensor: null,
      default_profile_version: '2026.2', overrides: [], checks: [check('baseline_drift', false, { lookback_hours: 168 })],
      advanced_aggregation_override_count: 0,
    } }));
    await page.goto('/admin/qc/parameters/1');
    await page.getByRole('button', { name: language === 'en' ? 'Review and enable' : 'Revisar y activar', exact: true }).click();
    const box = page.locator('.qc-switch-row input');
    await expect(box).not.toBeChecked();
    await expect(box).toHaveCSS('color-scheme', 'light');
    await expect(box).toHaveCSS('accent-color', 'rgb(6, 71, 137)');
    await page.keyboard.press('Tab');
    await box.focus();
    await expect(box).toHaveCSS('outline-style', 'solid');
    await page.screenshot({ path: `../artifacts/checkbox-acceptance/qc-empty-${language}-${width}.png`, fullPage: true });
    await box.press('Space');
    await expect(box).toBeChecked();
    await page.screenshot({ path: `../artifacts/checkbox-acceptance/qc-checked-${language}-${width}.png`, fullPage: true });
    await page.locator('.qc-switch-row strong').click();
    await expect(box).not.toBeChecked();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

for (const language of ['en', 'es'] as const) for (const width of [1440, 390]) {
  test(`QC and admin copy ${language} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const state = await mockAdministration(page, language);
    await page.route('**/api/admin/email/administrator-summary', route => route.fulfill({ json: {
      ...state.summary,
      next_due_at: state.summary.enabled ? '2026-09-08T07:00:00Z' : null,
      next_reporting_window: state.summary.enabled ? {
        period_start: '2026-09-07T00:00:00Z', period_end: '2026-09-08T00:00:00Z',
      } : null,
    } }));
    const qc = language === 'en' ? enQc : esQc;
    const email = (language === 'en' ? enEmail : esEmail).administratorSummary;
    const save = language === 'en' ? 'Save changes' : 'Guardar cambios';
    const add = language === 'en' ? 'Add device' : 'Agregar dispositivo';
    const dir = `../artifacts/qc-status-copy/${language}-${width}`;
    mkdirSync(dir, { recursive: true });
    const capture = async (name: string) => {
      await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    };
    const custom = recommended.map(policy => ({ ...policy, most_specific_source: { ...policy.most_specific_source!, layer: 'parameter_override' as const } }));
    await page.route('**/api/admin/qc/parameters', route => route.fulfill({ json: { items: [parameter(1, 'PM2.5', recommended), parameter(2, 'TVOC', [check('baseline_drift', false, {})]), parameter(3, 'Custom fixture', custom, 1), parameter(4, 'Unconfigured fixture', [], 0, false)], total: 4, default_profile_version: '2026.2' } }));
    await page.route('**/api/admin/qc/checks', route => route.fulfill({ json: { items: ['min_value', 'max_value', 'baseline_drift'].map((code, index) => ({ check_code: code, display_name: code, description: '', available: true, unit_settings: index < 2 ? [index === 0 ? 'min' : 'max'] : [], overview: { visible: true, label: (language === 'en' ? ['Minimum', 'Maximum', 'Baseline drift'] : ['Mínimo', 'Máximo', 'Deriva de línea base'])[index], order: index, summary_setting: index === 0 ? 'min' : index === 1 ? 'max' : null }, settings: [], failure_actions: [] })) } }));
    await page.goto('/admin/qc');
    await expect(page.getByText(qc.states.recommendedPreset, { exact: true })).toBeVisible();
    const noRange = page.locator('.qc-parameter-row').filter({ hasText: 'TVOC' });
    await expect(noRange.getByText(qc.states.noRecommendedRange, { exact: true })).toBeVisible();
    await expect(noRange.getByText(qc.states.notConfigured, { exact: true })).toHaveCount(2);
    await expect(noRange.getByText(qc.states.recommendedPreset, { exact: true })).toHaveCount(0);
    await expect(page.locator('.qc-parameter-row').filter({ hasText: 'Custom fixture' }).getByText(qc.states.custom, { exact: true })).toBeVisible();
    await capture('qc');

    await page.goto('/admin/sources/1');
    await expect(page.getByRole('heading', { level: 1, name: 'OpenAQ', exact: true })).toBeVisible();
    await expect(page.locator('.breadcrumbs')).toContainText('OpenAQ');
    await capture('source');
    state.sources[0].name = 'OpenAQ regional air quality monitoring network — community and research stations with extended provider identification';
    await page.goto('/admin/sources/1');
    await expect(page.getByRole('heading', { level: 1, name: state.sources[0].name })).toBeVisible();
    await capture('source-long');

    await page.goto('/admin/email');
    const summary = page.locator('.administrator-summary-section');
    await expect(summary.getByRole('heading', { name: /when enabled|cuando se habilite/ })).toBeVisible();
    await expect(summary.getByRole('button', { name: save, exact: true })).toBeVisible();
    await summary.scrollIntoViewIfNeeded();
    await summary.screenshot({ path: `${dir}/summary-disabled.png` });
    state.summary.enabled = true;
    state.summary.schedule_status = 'waiting_for_first_scheduled_period';
    await page.goto('/admin/email');
    await expect(summary.getByText(email.status.waiting_for_first_scheduled_period.label, { exact: true })).toBeVisible();
    await expect(summary.getByRole('heading', { name: /when enabled|cuando se habilite/ })).toHaveCount(0);
    await summary.screenshot({ path: `${dir}/summary-enabled.png` });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();

    await page.getByRole('button', { name: language === 'en' ? 'Edit configuration' : 'Editar configuración', exact: true }).click();
    const emailForm = page.locator('.email-configuration-form');
    await expect(emailForm.getByRole('button', { name: save, exact: true })).toBeVisible();
    await emailForm.screenshot({ path: `${dir}/email-editor.png` });

    await page.goto('/admin/devices');
    await page.getByRole('button', { name: add, exact: true }).click();
    await expect(page.getByRole('heading', { level: 1, name: add, exact: true })).toBeVisible();
    await capture('add-device');
    await page.goto('/admin/devices/manual');
    await expect(page.getByRole('button', { name: add, exact: true })).toBeVisible();
    await capture('manual-device');
    await page.route('**/api/admin/users/review-admin', route => route.fulfill({ json: { user_id: 'review-admin', email: 'administrator@example.org', roles: ['admin'], is_active: true, created_at: stamp, updated_at: stamp, failed_login_count: 0 } }));
    await page.route('**/api/admin/users/roles', route => route.fulfill({ json: [
      { role_id: '1', name: 'admin' }, { role_id: '2', name: 'viewer' },
    ] }));
    await page.goto('/admin/users/review-admin');
    await expect(page.getByRole('button', { name: save, exact: true })).toBeVisible();
    await capture('roles');
    expect(state.writes.filter(path => path !== '/auth/refresh')).toEqual([]);
  });
}
