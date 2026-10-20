import { expect, test } from '@playwright/test';
import { mockAdministration } from './fixtures/administration';
import en from '../src/i18n/locales/en/qualityControl.json' with { type: 'json' };
import es from '../src/i18n/locales/es/qualityControl.json' with { type: 'json' };
import type { QcCheckMetadata, QcPolicyResponse, QcResolvedCheck, QcUnit } from '../src/qc/types';

const units: Record<string, QcUnit> = Object.fromEntries([
  ['ug_m3', 'µg/m³'], ['mg_m3', 'mg/m³'], ['ppm', 'ppm'], ['ppb', 'ppb'], ['percent', '%'],
].map(([unit_code, symbol], index) => [unit_code, { unit_id: index + 1, unit_code, symbol, name: symbol }]));

function resolved(check_code: string, unit: string, settings: Record<string, unknown>, custom = false): QcResolvedCheck {
  const enabled = check_code !== 'baseline_drift';
  const source = { layer: custom ? 'parameter_override' as const : 'compassaq_default' as const, label: '', qc_rule_id: custom ? 1 : null, rule_version: null, default_profile_version: '2026.2', policy_unit_code: unit };
  return { check_code, enabled, status: enabled ? 'ready' : 'disabled', configured_settings: settings,
    evaluation_settings: enabled ? settings : {}, failure_action: 'flag_for_review',
    configured_unit_code: unit, evaluation_unit_code: unit, applicable_unit_code: unit, unit_conversion: null,
    reason_code: enabled ? null : 'disabled', message: '', applicability: 'applicable', default_profile_version: '2026.2',
    applied_layers: [source], most_specific_source: source, property_provenance: custom ? { 'settings.max': source } : {},
  };
}

for (const language of ['en', 'es'] as const) for (const width of [390, 1440]) {
  for (const parameter of [
    { code: 'pm25', name: 'PM2.5', unit: 'ug_m3', other: 'mg_m3', custom: false },
    { code: 'o3', name: 'Ozone', unit: 'ppm', other: 'ppb', custom: true },
    { code: 'rh', name: 'Relative humidity', unit: 'percent', other: null, custom: false },
  ]) {
    test(`${parameter.code} parameter workflow ${language} ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      const state = await mockAdministration(page, language);
      const copy = language === 'en' ? en : es;
      const metadata: QcCheckMetadata[] = ['min_value', 'max_value', 'baseline_drift'].map((check_code, index) => {
        const setting = ['min', 'max', 'max_drift_per_day'][index];
        return { check_code, display_name: ['Minimum', 'Maximum', 'Baseline Drift'][index], description: '', available: parameter.code !== 'rh' || index !== 2,
          plugin_version: '1', qc_api: 1, origin: 'built_in', required_access: 'api-only', unit_settings: [setting],
          overview: { visible: true, label: ['Minimum', 'Maximum', 'Baseline Drift'][index], order: index, summary_setting: index < 2 ? setting : null },
          settings: [{ setting_code: setting, value_type: 'number', label: setting, help_text: '', required: true, choices: null }], failure_actions: ['flag_for_review', 'mark_invalid'] };
      });
      const policy: QcPolicyResponse = {
        scope: { scope_type: 'parameter', parameter_id: 1, external_api_id: null, sensor_id: null },
        parameter: { parameter_id: 1, parameter_code: parameter.code, display_name: parameter.name, default_unit: units[parameter.unit], supported_units: [units[parameter.unit], ...(parameter.other ? [units[parameter.other]] : [])] },
        data_source: null, sensor: null, default_profile_version: '2026.2', advanced_aggregation_override_count: 0,
        overrides: parameter.custom ? [{ qc_rule_id: 1, check_code: 'max_value', enabled_override: null, failure_action_override: null, settings: { max: 0.2 }, policy_unit: units[parameter.unit], version: 1, overridden_properties: ['settings.max'], updated_at: null }] : [],
        checks: [resolved('min_value', parameter.unit, { min: 0 }), resolved('max_value', parameter.unit, { max: parameter.custom ? 0.2 : 100 }, parameter.custom), resolved('baseline_drift', parameter.unit, parameter.code === 'rh' ? {} : { max_drift_per_day: parameter.code === 'o3' ? 0.003 : 5 })],
      };
      if (parameter.code === 'o3') {
        policy.checks.push({ ...resolved('baseline_drift', 'ppm', { max_drift_per_day: 0.003 }), applicable_unit_code: 'ppb', evaluation_unit_code: 'ppb' });
      }
      await page.route('**/api/admin/qc/checks', route => route.fulfill({ json: { items: metadata } }));
      await page.route('**/api/admin/qc/parameters', route => route.fulfill({ json: { items: [{ ...policy.parameter, sensor_count: 5, source_exception_count: 1, sensor_exception_count: 2 }], total: 1 } }));
      await page.route('**/api/admin/qc/parameters/1/policy', route => route.fulfill({ json: policy }));
      await page.route('**/api/admin/qc/sources/*/parameters/1/policy', route => route.fulfill({ json: { ...policy, overrides: route.request().url().includes('/sources/1/') ? [{ check_code: 'max_value' }] : [] } }));
      await page.goto('/admin/qc/parameters/1');
      const unit = page.getByRole('combobox', { name: copy.detail.effectiveUnit });
      await expect(unit).toHaveValue(parameter.unit);
      await expect(page.getByRole('heading', { level: 1, name: parameter.name })).toBeVisible();
      const firstAction = page.getByRole('button', { name: copy.actions.customize, exact: true }).first();
      const actionBox = (await firstAction.boundingBox())!;
      expect(actionBox.y + actionBox.height).toBeLessThan(844);
      expect(actionBox.height).toBeGreaterThanOrEqual(44);
      const shortcuts = page.locator('.qc-exception-shortcuts');
      await expect(shortcuts).toContainText(`${copy.detail.dataSourceExceptions} · 1`);
      await expect(shortcuts).toContainText(`${copy.detail.sensorExceptions} · 2`);
      expect((await shortcuts.boundingBox())!.y).toBeLessThan(actionBox.y);
      await expect(shortcuts.locator('a').last()).toHaveAttribute('href', '/admin/qc/sensors?parameter_id=1');
      await expect(page.getByRole('heading', { level: 3, name: copy.checks.maximum.name })).toBeVisible();
      const drift = page.locator('article').filter({ has: page.getByRole('heading', { name: copy.checks.baselineDrift.name }) });
      await expect(drift).toContainText(parameter.code === 'rh' ? copy.states.unavailable : copy.states.disabled);
      if (parameter.custom) await expect(page.locator('.qc-parameter-policy')).toContainText(copy.detail.customPolicy);
      else await expect(page.locator('.qc-parameter-policy')).toContainText(copy.detail.inheritedPolicy);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: `../artifacts/qc-parameter-workflow/${parameter.code}-${language}-${width}.png`, fullPage: true });
      await unit.focus();
      await page.keyboard.press('Tab');
      await expect(shortcuts.locator('a').first()).toBeFocused();
      await expect(shortcuts.locator('a').first()).toHaveCSS('outline-style', 'solid');
      await page.keyboard.press('Enter');
      await expect(page.locator('#source-exceptions-title')).toBeFocused();
      await expect(page.locator('.qc-exception-list').getByRole('link').first()).toBeVisible();
      const reference = page.locator('.qc-unit-defaults');
      await expect(reference).not.toHaveAttribute('open');
      await reference.locator('summary').focus();
      await page.keyboard.press('Enter');
      await expect(reference).toHaveAttribute('open');
      if (parameter.other) await expect(reference).toContainText(units[parameter.other].symbol);
      await page.locator('.qc-more-details').last().locator('summary').click();
      await expect(page.getByText(copy.detail.unitLimitations)).toBeVisible();
      if (parameter.code === 'o3') {
        await unit.selectOption('ppb');
        await expect(drift).toContainText(`${language === 'es' ? '0,003' : '0.003'} ppm`);
        await unit.selectOption('ppm');
      }
      await firstAction.click();
      await expect(page.locator('.qc-check-editor')).toBeVisible();
      await page.screenshot({ path: `../artifacts/qc-parameter-workflow/${parameter.code}-${language}-${width}-editor.png`, fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(state.writes.filter(path => path !== '/auth/refresh')).toEqual([]);
    });
  }
}
