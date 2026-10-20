import i18n from '../i18n';
import type {
  QcCheckMetadata,
  QcFailureAction,
  QcOverride,
  QcParameterSummary,
  QcPolicyLayer,
  QcResolvedCheck,
  QcUnit,
} from './types';

export function isUnitScopedCheck(metadata?: Pick<QcCheckMetadata, 'unit_settings'>): boolean {
  return Boolean(metadata?.unit_settings.length);
}

type QcCheckPresentationMetadata = Pick<QcCheckMetadata, 'display_name' | 'description'>;

const UNIT_SYMBOLS: Record<string, string> = {
  ug_m3: 'µg/m³',
  mg_m3: 'mg/m³',
  c: '°C',
  percent: '%',
  ppm: 'ppm',
  ppb: 'ppb',
  index: 'index',
};

export function checkName(checkCode: string, metadata?: QcCheckPresentationMetadata): string {
  if (checkCode === 'min_value') return i18n.t('qualityControl:checks.minimum.name');
  if (checkCode === 'max_value') return i18n.t('qualityControl:checks.maximum.name');
  if (checkCode === 'baseline_drift') return i18n.t('qualityControl:checks.baselineDrift.name');
  return metadata?.display_name || i18n.t('qualityControl:checks.unavailable.name');
}

export function checkDescription(checkCode: string, metadata?: QcCheckPresentationMetadata): string {
  if (checkCode === 'min_value') return i18n.t('qualityControl:checks.minimum.description');
  if (checkCode === 'max_value') return i18n.t('qualityControl:checks.maximum.description');
  if (checkCode === 'baseline_drift') return i18n.t('qualityControl:checks.baselineDrift.description');
  return metadata?.description || i18n.t('qualityControl:checks.unavailable.description');
}

export function failureActionLabel(action: QcFailureAction | null): string {
  if (action === 'mark_invalid') {
    return i18n.t('qualityControl:failureActions.markInvalid.label');
  }
  return i18n.t('qualityControl:failureActions.flagForReview.label');
}

export function failureActionDescription(action: QcFailureAction | null): string {
  if (action === 'mark_invalid') {
    return i18n.t('qualityControl:failureActions.markInvalid.description');
  }
  return i18n.t('qualityControl:failureActions.flagForReview.description');
}

export function unitSymbol(unit: QcUnit | null | undefined, unitCode?: string | null): string {
  if (unitCode && unitCode !== unit?.unit_code) return UNIT_SYMBOLS[unitCode] || unitCode;
  if (unit?.symbol) return unit.symbol;
  if (!unitCode) return '';
  return UNIT_SYMBOLS[unitCode] || unitCode;
}

export function formatQcNumber(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat(i18n.resolvedLanguage || 'en', {
    maximumSignificantDigits: 12,
  }).format(value);
}

export function primarySettingCode(metadata?: QcCheckMetadata): string | null {
  return metadata?.overview.summary_setting ?? null;
}

export function checkValue(check: QcResolvedCheck, metadata?: QcCheckMetadata): unknown {
  const settingCode = primarySettingCode(metadata);
  if (!settingCode) return null;
  return check.evaluation_settings[settingCode]
    ?? check.configured_settings[settingCode]
    ?? null;
}

export function isCheckCustomizedAtLayer(
  check: QcResolvedCheck,
  scopeType: 'parameter' | 'source_parameter',
): boolean {
  const expectedLayer = scopeType === 'parameter' ? 'parameter_override' : 'source_override';
  return Object.values(check.property_provenance).some(
    (provenance) => provenance.layer === expectedLayer,
  );
}

export function provenanceLabel(
  layer: QcPolicyLayer | null | undefined,
  options: { scopeType: 'parameter' | 'source_parameter'; parameterName: string; sourceName?: string },
): string {
  if (!layer || layer.layer === 'compassaq_default') {
    return options.scopeType === 'source_parameter'
      ? i18n.t('qualityControl:provenance.usesParameter', { parameter: options.parameterName })
      : i18n.t('qualityControl:provenance.recommended');
  }
  if (layer.layer === 'parameter_override') {
    return options.scopeType === 'parameter'
      ? i18n.t('qualityControl:provenance.customParameter', { parameter: options.parameterName })
      : i18n.t('qualityControl:provenance.usesParameter', { parameter: options.parameterName });
  }
  if (layer.layer === 'source_override') {
    return i18n.t('qualityControl:provenance.customSource', { source: options.sourceName || '' });
  }
  if (layer.layer === 'sensor_override') {
    return i18n.t('qualityControl:provenance.customSensor');
  }
  return i18n.t('qualityControl:provenance.custom');
}

export function sensorProvenanceLabel(
  layer: QcPolicyLayer | null | undefined,
  options: { parameterName: string; sourceName: string },
): string {
  if (!layer) return i18n.t('qualityControl:sensors.provenance.notConfigured');
  if (layer.layer === 'compassaq_default') {
    return i18n.t('qualityControl:sensors.provenance.compassaq', {
      parameter: options.parameterName,
    });
  }
  if (layer.layer === 'parameter_override') {
    return i18n.t('qualityControl:sensors.provenance.parameter', {
      parameter: options.parameterName,
    });
  }
  if (layer.layer === 'parameter_aggregate_override') {
    return i18n.t('qualityControl:sensors.provenance.advancedParameter', {
      parameter: options.parameterName,
    });
  }
  if (layer.layer === 'source_override') {
    return i18n.t('qualityControl:sensors.provenance.source', {
      source: options.sourceName,
      parameter: options.parameterName,
    });
  }
  if (layer.layer === 'source_aggregate_override') {
    return i18n.t('qualityControl:sensors.provenance.advancedSource', {
      source: options.sourceName,
      parameter: options.parameterName,
    });
  }
  if (layer.layer === 'sensor_aggregate_override') {
    return i18n.t('qualityControl:sensors.provenance.advancedSensor');
  }
  return i18n.t('qualityControl:sensors.provenance.customSensor');
}

export function sensorCustomPropertyCount(overrides: QcOverride[]): number {
  return overrides.reduce((count, override) => (
    count
    + (override.enabled_override === null ? 0 : 1)
    + (override.failure_action_override === null ? 0 : 1)
    + Object.keys(override.settings).length
  ), 0);
}

export function checkHasAdvancedSensorSetting(check: QcResolvedCheck): boolean {
  return Object.values(check.property_provenance).some(
    (provenance) => provenance.layer === 'sensor_aggregate_override',
  );
}

export function settingLabel(checkCode: string, settingCode: string, fallback: string): string {
  const translatedKey = `qualityControl:checks.${checkCode === 'baseline_drift' ? 'baselineDrift' : checkCode === 'max_value' ? 'maximum' : 'minimum'}.settings.${settingCode}.label`;
  return ['min_value', 'max_value', 'baseline_drift'].includes(checkCode)
    && i18n.exists(translatedKey as never)
    ? i18n.t(translatedKey as never)
    : fallback;
}

export function settingHelp(checkCode: string, settingCode: string, fallback: string): string {
  const translatedKey = `qualityControl:checks.${checkCode === 'baseline_drift' ? 'baselineDrift' : checkCode === 'max_value' ? 'maximum' : 'minimum'}.settings.${settingCode}.help`;
  return ['min_value', 'max_value', 'baseline_drift'].includes(checkCode)
    && i18n.exists(translatedKey as never)
    ? i18n.t(translatedKey as never)
    : fallback;
}

export function userFacingPolicyIssue(reasonCode: string | null): string {
  const knownReasons = new Set([
    'missing_required_setting',
    'missing_policy_unit',
    'unknown_unit',
    'conversion_not_supported',
    'ambiguous_policy',
    'invalid_policy_setting',
    'missing_failure_action',
  ]);
  const key = knownReasons.has(reasonCode || '') ? reasonCode : 'generic';
  return i18n.t(`qualityControl:policyIssues.${key}` as never);
}

export function rangeConfigurationState(parameter: QcParameterSummary) {
  const rangeChecks = ['min_value', 'max_value'].map(code => parameter.checks.find(check => (
    check.check_code === code && check.applicable_unit_code === parameter.default_unit?.unit_code
  )));
  // `supported` includes disabled, non-range defaults. Only resolved range
  // policies can establish a recommended range in the displayed unit.
  // The API omits check codes when neither a default nor a saved rule exists.
  if (!parameter.checks.some(check => ['min_value', 'max_value'].includes(check.check_code))
    || rangeChecks.every(check => check?.status === 'not_configured')) return 'noRecommendedRange';
  if (rangeChecks.every((check, index) => check?.status === 'ready'
    && check.enabled
    && check.applicability === 'applicable'
    && check.most_specific_source?.layer === 'compassaq_default'
    && typeof check.configured_settings[index === 0 ? 'min' : 'max'] === 'number'
    && Number.isFinite(check.configured_settings[index === 0 ? 'min' : 'max']))) {
    return 'recommendedPreset';
  }
  return 'defaultConfiguration';
}
