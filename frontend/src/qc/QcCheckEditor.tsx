import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ApiError } from '../apiError';
import { mergeCheckOverride } from './api';
import {
  checkName,
  failureActionDescription,
  isUnitScopedCheck,
  sensorProvenanceLabel,
  settingHelp,
  settingLabel,
  unitSymbol,
  userFacingPolicyIssue,
} from './presentation';
import QcPreviewPanel from './QcPreviewPanel';
import type {
  QcCheckMetadata,
  QcFailureAction,
  QcOverrideInput,
  QcPolicyResponse,
  QcPreviewResponse,
  QcResolvedCheck,
} from './types';

function overrideHasValues(override: QcOverrideInput): boolean {
  return override.enabled_override !== null
    || override.failure_action_override !== null
    || Object.keys(override.settings).length > 0;
}

export default function QcCheckEditor({
  policy,
  check,
  metadata,
  affectedSensorCount,
  onSave,
  onPreview,
  onCancel,
}: {
  policy: QcPolicyResponse;
  check: QcResolvedCheck;
  metadata: QcCheckMetadata;
  affectedSensorCount: number;
  onSave: (replacement: QcOverrideInput | null) => Promise<void>;
  onPreview: (overrides: QcOverrideInput[]) => Promise<QcPreviewResponse>;
  onCancel: () => void;
}) {
  const { t } = useTranslation('qualityControl');
  const unitScoped = isUnitScopedCheck(metadata);
  const applicableUnitCode = check.applicable_unit_code ?? check.evaluation_unit_code;
  const existing = policy.overrides.find((override) => (
    override.check_code === check.check_code
    && (!unitScoped || override.policy_unit?.unit_code === applicableUnitCode)
  ));
  const inherited = check.inherited_policy;
  const sensorScope = policy.scope.scope_type === 'sensor';
  const sensor = policy.sensor;
  const existingCustomUnitSetting = metadata.unit_settings.some(
    (settingCode) => existing?.settings[settingCode] !== undefined,
  );
  const initialSettingValue = (settingCode: string): unknown => {
    if (
      (sensorScope || unitScoped)
      && metadata.unit_settings.includes(settingCode)
      && !existingCustomUnitSetting
    ) {
      return check.evaluation_settings[settingCode]
        ?? check.configured_settings[settingCode];
    }
    return check.configured_settings[settingCode];
  };
  const [enabledOverride, setEnabledOverride] = useState<boolean | null>(
    existing?.enabled_override ?? (check.status === 'not_configured' ? true : null),
  );
  const [failureOverride, setFailureOverride] = useState<QcFailureAction | null>(existing?.failure_action_override ?? null);
  const [policyUnitOverride, setPolicyUnitOverride] = useState<string | null>(
    existing?.policy_unit?.unit_code ?? (unitScoped ? applicableUnitCode : null),
  );
  const [settingValues, setSettingValues] = useState<Record<string, string>>(() => Object.fromEntries(
    metadata.settings.map((setting) => [
      setting.setting_code,
      initialSettingValue(setting.setting_code) === undefined
        ? ''
        : String(initialSettingValue(setting.setting_code)),
    ]),
  ));
  const [customSettings, setCustomSettings] = useState<Set<string>>(
    () => new Set(Object.keys(existing?.settings ?? {})),
  );
  const [changed, setChanged] = useState(false);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<QcPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const unitOptions = sensorScope
    ? (sensor?.unit ? [sensor.unit] : [])
    : policy.parameter.supported_units;

  const effectiveEnabled = enabledOverride ?? inherited?.enabled ?? check.enabled;
  const effectiveFailureAction = failureOverride ?? inherited?.failure_action ?? check.failure_action ?? 'flag_for_review';
  const disablingEnabledCheck = check.enabled && !effectiveEnabled;

  const currentOverride = useMemo<QcOverrideInput>(() => ({
    check_code: check.check_code,
    enabled_override: enabledOverride,
    failure_action_override: failureOverride,
    settings: {},
    policy_unit_code: policyUnitOverride,
  }), [check.check_code, enabledOverride, failureOverride, policyUnitOverride]);

  const sensorSource = (propertyCode: string) => sensorProvenanceLabel(
    inherited?.property_provenance[propertyCode],
    {
      parameterName: policy.parameter.display_name,
      sourceName: policy.data_source?.name || '',
    },
  );

  const inheritedActionLabel = (propertyCode: string): string => {
    if (sensorScope) {
      if (!inherited?.property_provenance[propertyCode]) {
        return t('sensors.actions.removeCustomSetting');
      }
      return t('sensors.actions.useInheritedSetting', { source: sensorSource(propertyCode) });
    }
    return policy.scope.scope_type === 'parameter'
      ? check.check_code === 'baseline_drift'
        ? t('actions.useSuggestedScreeningSetting')
        : t('actions.useRecommended')
      : t('actions.useParameterSetting', { parameter: policy.parameter.display_name });
  };

  const buildOverride = (): { valid: boolean; override: QcOverrideInput | null } => {
    const nextErrors: Record<string, string> = {};
    const settings: Record<string, unknown> = {};

    if (unitScoped && !policyUnitOverride) {
      nextErrors.unit = t('validation.unitRequired');
    }

    for (const setting of metadata.settings) {
      const rawValue = settingValues[setting.setting_code]?.trim() ?? '';
      const inheritedValue = inherited?.configured_settings[setting.setting_code];
      const candidateValue = customSettings.has(setting.setting_code) ? rawValue : inheritedValue;
      if (effectiveEnabled && setting.required && (candidateValue === undefined || candidateValue === '')) {
        nextErrors[setting.setting_code] = t('validation.required');
      }
      if (!customSettings.has(setting.setting_code)) continue;
      if (setting.value_type === 'number' || setting.value_type === 'integer') {
        const numericValue = Number(rawValue);
        if (!Number.isFinite(numericValue)) {
          nextErrors[setting.setting_code] = t('validation.number');
          continue;
        }
        if (setting.value_type === 'integer' && !Number.isInteger(numericValue)) {
          nextErrors[setting.setting_code] = t('validation.integer');
          continue;
        }
        if (setting.minimum !== undefined && numericValue < setting.minimum) {
          nextErrors[setting.setting_code] = t('validation.minimum', { minimum: setting.minimum });
        }
        if (setting.maximum !== undefined && numericValue > setting.maximum) {
          nextErrors[setting.setting_code] = t('validation.maximum', { maximum: setting.maximum });
        }
        settings[setting.setting_code] = numericValue;
      } else if (setting.value_type === 'boolean') {
        settings[setting.setting_code] = rawValue === 'true';
      } else {
        settings[setting.setting_code] = rawValue;
      }
    }

    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return { valid: false, override: null };

    const unitSettingCustomized = metadata.unit_settings.some((settingCode) => customSettings.has(settingCode));
    const inheritedUnit = inherited?.configured_unit_code ?? check.configured_unit_code;
    const policyUnitCode = unitScoped
      ? policyUnitOverride
      : currentOverride.policy_unit_code
      ?? (sensorScope && unitSettingCustomized
        ? sensor?.unit?.unit_code ?? null
        : (unitSettingCustomized && !inheritedUnit ? policy.parameter.default_unit?.unit_code ?? null : null));
    // A newly configured check has no inherited failure action. Persist the
    // plainly displayed default so the backend receives a complete policy.
    const failureActionOverride = effectiveEnabled
      && !inherited?.failure_action
      && !check.failure_action
      && failureOverride === null
      ? effectiveFailureAction
      : failureOverride;
    const override: QcOverrideInput = {
      ...currentOverride,
      failure_action_override: failureActionOverride,
      settings,
      policy_unit_code: policyUnitCode,
    };
    return { valid: true, override: overrideHasValues(override) ? override : null };
  };

  const describeError = (caught: unknown, fallback: string): string => {
    if (caught instanceof ApiError && caught.errorCode) return userFacingPolicyIssue(caught.errorCode);
    return fallback;
  };

  const save = async () => {
    const candidate = buildOverride();
    if (!candidate.valid) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(candidate.override);
    } catch (caught) {
      setError(describeError(caught, t('editor.saveError')));
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async () => {
    const candidate = buildOverride();
    if (!candidate.valid) return;
    setPreviewing(true);
    setError(null);
    try {
      const candidateOverrides = mergeCheckOverride(
        policy.overrides,
        check.check_code,
        metadata.unit_settings,
        applicableUnitCode,
        candidate.override,
      );
      setPreview(await onPreview(candidateOverrides));
    } catch (caught) {
      setError(describeError(caught, t('preview.error')));
      setPreview(null);
    } finally {
      setPreviewing(false);
    }
  };

  const resetSetting = (settingCode: string) => {
    const remainingCustomSettings = new Set(customSettings);
    remainingCustomSettings.delete(settingCode);
    setCustomSettings(remainingCustomSettings);
    if (
      !unitScoped
      && metadata.unit_settings.includes(settingCode)
      && !metadata.unit_settings.some((unitSettingCode) => remainingCustomSettings.has(unitSettingCode))
    ) {
      setPolicyUnitOverride(null);
    }
    const inheritedValue = sensorScope && metadata.unit_settings.includes(settingCode)
      ? inherited?.evaluation_settings[settingCode]
      : inherited?.configured_settings[settingCode];
    setSettingValues((current) => ({
      ...current,
      [settingCode]: inheritedValue === undefined ? '' : String(inheritedValue),
    }));
    setChanged(true);
    setPreview(null);
  };

  const customizeSetting = (settingCode: string, value: string) => {
    setSettingValues((current) => ({ ...current, [settingCode]: value }));
    if (
      sensorScope
      && metadata.unit_settings.includes(settingCode)
      && !metadata.unit_settings.some((unitSettingCode) => customSettings.has(unitSettingCode))
    ) {
      setPolicyUnitOverride(sensor?.unit?.unit_code ?? null);
    }
    setCustomSettings((current) => new Set(current).add(settingCode));
    setChanged(true);
    setPreview(null);
  };

  return (
    <div className="qc-check-editor">
      <div className="qc-editor-impact info-banner">
        {sensorScope
          ? t('sensors.editor.impact', {
              check: checkName(check.check_code, metadata),
              device: sensor?.device_name || '',
            })
          : policy.scope.scope_type === 'parameter'
          ? t(disablingEnabledCheck ? 'editor.parameterDisableImpact' : 'editor.parameterImpact', {
              check: checkName(check.check_code, metadata),
              count: affectedSensorCount,
              parameter: policy.parameter.display_name,
            })
          : t(disablingEnabledCheck ? 'editor.sourceDisableImpact' : 'editor.sourceImpact', {
              check: checkName(check.check_code, metadata),
              count: affectedSensorCount,
              source: policy.data_source?.name || '',
            })}
      </div>
      {unitScoped && (
        <div className="qc-editor-settings qc-editor-unit-settings">
          <div className="qc-editor-field">
            <div className="qc-editor-label-row">
              <label htmlFor={`qc-${policy.scope.scope_type}-${check.check_code}-unit`}>
                {t('editor.unit')}
              </label>
            </div>
            <select
              id={`qc-${policy.scope.scope_type}-${check.check_code}-unit`}
              value={policyUnitOverride ?? ''}
              onChange={(event) => {
                setPolicyUnitOverride(event.target.value || null);
                setChanged(true);
                setPreview(null);
              }}
              aria-describedby={fieldErrors.unit ? `qc-${check.check_code}-unit-error` : undefined}
            >
              {unitOptions.map((unit) => (
                <option value={unit.unit_code} key={unit.unit_code}>{unit.symbol}</option>
              ))}
            </select>
            <small>{sensorScope ? t('editor.sensorUnitHelp') : t('editor.unitHelp')}</small>
            {fieldErrors.unit && (
              <div id={`qc-${check.check_code}-unit-error`} className="field-error">{fieldErrors.unit}</div>
            )}
          </div>
        </div>
      )}
      {sensorScope && check.unit_conversion?.status === 'converted' && (
        <p className="qc-editor-conversion-note">{t('sensors.editor.convertedUnitNote', {
          unit: unitSymbol(sensor?.unit, check.evaluation_unit_code),
        })}</p>
      )}

      <fieldset className="qc-editor-fieldset">
        <legend>{t('editor.checkState')}</legend>
        {sensorScope && (
          <p className="qc-editor-property-source">
            {enabledOverride !== null
              ? t('sensors.provenance.customSensor')
              : sensorSource('enabled')}
          </p>
        )}
        <label className="qc-switch-row">
          <input
            type="checkbox"
            checked={effectiveEnabled}
            onChange={(event) => { setEnabledOverride(event.target.checked); setChanged(true); setPreview(null); }}
          />
          <span>
            <strong>{t('editor.enableCheck')}</strong>
            <small>{effectiveEnabled ? t('editor.enabledHelp') : t('editor.disabledHelp')}</small>
          </span>
        </label>
        {existing?.enabled_override !== null && existing?.enabled_override !== undefined && (
          <button className="btn ghost small" type="button" onClick={() => { setEnabledOverride(null); setChanged(true); setPreview(null); }}>
            {inheritedActionLabel('enabled')}
          </button>
        )}
      </fieldset>

      {effectiveEnabled && metadata.settings.length > 0 && (
        <div className="qc-editor-settings">
          {metadata.settings.map((setting) => {
            const isCustom = customSettings.has(setting.setting_code);
            const isUnitSetting = metadata.unit_settings.includes(setting.setting_code);
            const inheritedValue = sensorScope && isUnitSetting
              ? inherited?.evaluation_settings[setting.setting_code]
              : inherited?.configured_settings[setting.setting_code];
            const fieldId = `qc-${policy.scope.scope_type}-${check.check_code}-${setting.setting_code}`;
            const hasCurrentCustomUnitSetting = metadata.unit_settings.some(
              (unitSettingCode) => customSettings.has(unitSettingCode),
            );
            const unitCode = unitScoped
              ? policyUnitOverride
              : sensorScope && !hasCurrentCustomUnitSetting
              ? sensor?.unit?.unit_code ?? check.evaluation_unit_code
              : policyUnitOverride ?? check.configured_unit_code;
            const propertyCode = `settings.${setting.setting_code}`;
            return (
              <div className="qc-editor-field" key={setting.setting_code}>
                <div className="qc-editor-label-row">
                  <label htmlFor={fieldId}>{settingLabel(check.check_code, setting.setting_code, setting.label)}</label>
                  <span className={sensorScope ? `qc-property-source${isCustom ? ' qc-property-source-custom' : ''}` : (isCustom ? 'qc-property-custom' : 'qc-property-inherited')}>
                    {sensorScope
                      ? (isCustom ? t('sensors.provenance.customSensor') : sensorSource(propertyCode))
                      : (isCustom ? t('states.custom') : t('states.inherited'))}
                  </span>
                </div>
                <div className="qc-input-with-unit">
                  {setting.choices ? (
                    <select
                      id={fieldId}
                      value={settingValues[setting.setting_code] ?? ''}
                      onChange={(event) => customizeSetting(setting.setting_code, event.target.value)}
                      disabled={sensorScope && isUnitSetting && !sensor?.unit}
                      aria-describedby={`${fieldId}-help${fieldErrors[setting.setting_code] ? ` ${fieldId}-error` : ''}`}
                    >
                      {setting.choices.map((choice) => <option value={choice} key={choice}>{t(`choices.${choice}`, { defaultValue: choice })}</option>)}
                    </select>
                  ) : (
                    <input
                      id={fieldId}
                      type={setting.value_type === 'number' || setting.value_type === 'integer' ? 'number' : 'text'}
                      step={setting.value_type === 'integer' ? '1' : 'any'}
                      value={settingValues[setting.setting_code] ?? ''}
                      onChange={(event) => customizeSetting(setting.setting_code, event.target.value)}
                      disabled={sensorScope && isUnitSetting && !sensor?.unit}
                      aria-describedby={`${fieldId}-help${fieldErrors[setting.setting_code] ? ` ${fieldId}-error` : ''}`}
                    />
                  )}
                  {isUnitSetting && (
                    <span>{unitSymbol(sensorScope ? sensor?.unit : policy.parameter.default_unit, unitCode)}</span>
                  )}
                </div>
                <small id={`${fieldId}-help`}>
                  {settingHelp(check.check_code, setting.setting_code, setting.help_text)}
                  {isCustom && inheritedValue !== undefined && (
                    <> · {t('editor.resetValue', { value: String(inheritedValue) })}</>
                  )}
                </small>
                {sensorScope && isUnitSetting && !sensor?.unit && (
                  <div className="field-error">{t('sensors.editor.sensorUnitMissing')}</div>
                )}
                {fieldErrors[setting.setting_code] && <div id={`${fieldId}-error`} className="field-error">{fieldErrors[setting.setting_code]}</div>}
                {isCustom && (
                  <button className="qc-property-reset" type="button" onClick={() => resetSetting(setting.setting_code)}>
                    {inheritedActionLabel(propertyCode)}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {effectiveEnabled && (
        <fieldset className="qc-editor-fieldset qc-failure-fieldset">
          <legend>{t('editor.whenFails')}</legend>
          {sensorScope && (
            <p className="qc-editor-property-source qc-failure-property-source">
              {failureOverride !== null
                ? t('sensors.provenance.customSensor')
                : sensorSource('failure_action')}
            </p>
          )}
          {(['flag_for_review', 'mark_invalid'] as QcFailureAction[]).map((action) => (
            <label className="qc-radio-option" key={action}>
              <input
                type="radio"
                name={`${check.check_code}-failure-action`}
                checked={effectiveFailureAction === action}
                onChange={() => { setFailureOverride(action); setChanged(true); setPreview(null); }}
              />
              <span><strong>{t(`failureActions.${action === 'mark_invalid' ? 'markInvalid' : 'flagForReview'}.label`)}</strong><small>{failureActionDescription(action)}</small></span>
            </label>
          ))}
          {existing?.failure_action_override && (
            <button className="btn ghost small" type="button" onClick={() => { setFailureOverride(null); setChanged(true); setPreview(null); }}>
              {inheritedActionLabel('failure_action')}
            </button>
          )}
        </fieldset>
      )}

      {error && <div className="error-banner" role="alert">{error}</div>}
      {preview && <QcPreviewPanel preview={preview} />}

      <div className="qc-editor-actions">
        <button className="btn" type="button" onClick={onCancel} disabled={saving || previewing}>{t('actions.cancel')}</button>
        {effectiveEnabled && (
          <button className="btn" type="button" onClick={() => void runPreview()} disabled={saving || previewing}>
            {previewing ? t('actions.previewing') : t('actions.preview')}
          </button>
        )}
        <button className="btn btn-primary" type="button" onClick={() => void save()} disabled={!changed || saving || previewing}>
          {saving ? t('actions.saving') : t('actions.saveChanges')}
        </button>
      </div>
    </div>
  );
}
