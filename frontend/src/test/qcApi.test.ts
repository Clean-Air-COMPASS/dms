import { describe, expect, it } from 'vitest';

import { mergeCheckOverride } from '../qc/api';
import { sensorCustomPropertyCount, sensorProvenanceLabel, unitSymbol } from '../qc/presentation';
import { apiErrorFromResponse } from '../apiError';
import type { QcOverride } from '../qc/types';

const override: QcOverride = {
  qc_rule_id: 1,
  check_code: 'min_value',
  enabled_override: null,
  failure_action_override: null,
  settings: { min: -10 },
  policy_unit: { unit_id: 1, unit_code: 'ug_m3', symbol: 'µg/m³', name: 'micrograms per cubic metre' },
  version: 1,
  overridden_properties: ['settings.min'],
  updated_at: null,
};

describe('QC sparse override serialization', () => {
  it('preserves the backend policy reason code for a user-facing validation message', async () => {
    const error = await apiErrorFromResponse(new Response(JSON.stringify({
      detail: { reason_code: 'missing_required_setting', message: 'technical detail' },
    }), { status: 422, headers: { 'Content-Type': 'application/json' } }));
    expect(error.errorCode).toBe('missing_required_setting');
  });

  it('shows a custom policy unit instead of relabeling it as the parameter unit', () => {
    expect(unitSymbol({
      unit_id: 1,
      unit_code: 'ppb',
      symbol: 'ppb',
      name: 'parts per billion',
    }, 'ppm')).toBe('ppm');
  });

  it('replaces one check without copying inherited properties or changing other checks', () => {
    expect(mergeCheckOverride([
      override,
      { ...override, qc_rule_id: 2, check_code: 'max_value', settings: { max: 1000 } },
    ], 'min_value', ['min'], 'ug_m3', {
      check_code: 'min_value',
      enabled_override: false,
      failure_action_override: null,
      settings: {},
      policy_unit_code: 'ug_m3',
    })).toEqual([
      {
        check_code: 'max_value',
        enabled_override: null,
        failure_action_override: null,
        settings: { max: 1000 },
        policy_unit_code: 'ug_m3',
      },
      {
        check_code: 'min_value',
        enabled_override: false,
        failure_action_override: null,
        settings: {},
        policy_unit_code: 'ug_m3',
      },
    ]);
  });

  it('removes only the selected check when its final custom property is reset', () => {
    expect(mergeCheckOverride([
      override,
      { ...override, qc_rule_id: 2, check_code: 'max_value', settings: { max: 1000 } },
    ], 'min_value', ['min'], 'ug_m3', null)).toEqual([{
      check_code: 'max_value',
      enabled_override: null,
      failure_action_override: null,
      settings: { max: 1000 },
      policy_unit_code: 'ug_m3',
    }]);
  });

  it('counts human-editable sensor properties without double-counting policy unit metadata', () => {
    expect(sensorCustomPropertyCount([{
      ...override,
      enabled_override: true,
      failure_action_override: 'mark_invalid',
      settings: { min: -5, tolerance: 1 },
      policy_unit: { unit_id: 2, unit_code: 'ug_m3', symbol: 'µg/m³', name: 'micrograms per cubic metre' },
    }])).toBe(4);
  });

  it('presents sensor provenance without exposing backend layer labels', () => {
    expect(sensorProvenanceLabel({
      layer: 'source_override',
      label: 'technical backend label',
      qc_rule_id: 8,
      rule_version: 1,
      default_profile_version: null,
      policy_unit_code: 'ug_m3',
    }, { parameterName: 'PM2.5', sourceName: 'AirGradient' })).toBe('AirGradient PM2.5 setting');
    expect(sensorProvenanceLabel({
      layer: 'sensor_aggregate_override',
      label: 'technical advanced label',
      qc_rule_id: 9,
      rule_version: 1,
      default_profile_version: null,
      policy_unit_code: null,
    }, { parameterName: 'PM2.5', sourceName: 'AirGradient' })).toBe('Advanced sensor setting');
  });
});
