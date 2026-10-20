import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import {
  checkDescription,
  checkName,
  checkValue,
  failureActionDescription,
  failureActionLabel,
  formatQcNumber,
  isCheckCustomizedAtLayer,
  isUnitScopedCheck,
  primarySettingCode,
  provenanceLabel,
  settingLabel,
  unitSymbol,
  userFacingPolicyIssue,
} from './presentation';
import QcCheckEditor from './QcCheckEditor';
import QcConfirmationDialog from './QcConfirmationDialog';
import QcStatusBadge from './QcStatusBadge';
import type {
  QcCheckMetadata,
  QcOverrideInput,
  QcPolicyResponse,
  QcPreviewResponse,
  QcResolvedCheck,
} from './types';

export default function QcCheckCard({
  headingLevel = 2,
  policy,
  check,
  metadata,
  affectedSensorCount,
  editing,
  onStartEditing,
  onStopEditing,
  onSave,
  onPreview,
  onResetCheck,
}: {
  headingLevel?: 2 | 3;
  policy: QcPolicyResponse;
  check: QcResolvedCheck;
  metadata?: QcCheckMetadata;
  affectedSensorCount: number;
  editing: boolean;
  onStartEditing: () => void;
  onStopEditing: () => void;
  onSave: (replacement: QcOverrideInput | null) => Promise<void>;
  onPreview: (overrides: QcOverrideInput[]) => Promise<QcPreviewResponse>;
  onResetCheck: () => Promise<void>;
}) {
  const { t } = useTranslation('qualityControl');
  const Heading = headingLevel === 3 ? 'h3' : 'h2';
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const scopeType = policy.scope.scope_type === 'source_parameter' ? 'source_parameter' : 'parameter';
  const unitScoped = isUnitScopedCheck(metadata);
  const applicableUnitCode = check.applicable_unit_code ?? check.evaluation_unit_code;
  const applicableUnit = policy.parameter.supported_units.find(
    (unit) => unit.unit_code === applicableUnitCode,
  ) ?? policy.sensor?.unit ?? policy.parameter.default_unit;
  const existingOverride = policy.overrides.find((override) => (
    override.check_code === check.check_code
    && (!unitScoped || override.policy_unit?.unit_code === applicableUnitCode)
  ));
  const pluginUnavailable = !metadata || !metadata.available;
  const noDefaultForUnit = unitScoped && check.status === 'not_configured';
  const needsConfiguration = !pluginUnavailable && (
    (!noDefaultForUnit && check.status === 'not_configured')
    || check.reason_code === 'unconfigured_check'
    || check.reason_code === 'unsupported_parameter'
    || (check.status === 'disabled' && metadata.settings.some((setting) => (
      setting.required && check.configured_settings[setting.setting_code] === undefined
    )))
  );
  const policyIssue = !pluginUnavailable && check.status === 'unavailable' && !needsConfiguration;
  const customized = isCheckCustomizedAtLayer(check, scopeType);
  const suggestedScreeningPreset = (
    scopeType === 'parameter'
    && check.check_code === 'baseline_drift'
    && !customized
    && Object.keys(check.configured_settings).length > 0
  );
  const primaryValue = checkValue(check, metadata);
  const primaryCode = primarySettingCode(metadata);
  const displayedValueSource = primaryCode
    ? check.property_provenance[`settings.${primaryCode}`] ?? check.most_specific_source
    : check.most_specific_source;

  const displayedSetting = (settingCode: string, valueType: string): string => {
    const value = check.evaluation_settings[settingCode]
      ?? check.configured_settings[settingCode];
    if (value === undefined || value === null) return t('states.notConfigured');
    if (valueType === 'number' || valueType === 'integer') return formatQcNumber(value);
    return t(`choices.${String(value)}`, { defaultValue: String(value) });
  };

  const reset = async () => {
    setResetting(true);
    setResetError(null);
    try {
      await onResetCheck();
      setConfirmReset(false);
    } catch {
      setResetError(t('editor.resetError'));
      setConfirmReset(false);
    } finally {
      setResetting(false);
    }
  };

  return (
    <article className={`qc-check-card${editing ? ' qc-check-card-editing' : ''}`}>
      <div className="qc-check-card-header">
        <div>
          <div className="qc-check-heading-row">
            <Heading>{checkName(check.check_code, metadata)}</Heading>
            {pluginUnavailable && <QcStatusBadge tone="unavailable">{t('states.unavailable')}</QcStatusBadge>}
            {noDefaultForUnit && <QcStatusBadge tone="neutral">{t('states.notConfigured')}</QcStatusBadge>}
            {needsConfiguration && <QcStatusBadge tone="attention">{t('states.needsConfiguration')}</QcStatusBadge>}
            {!pluginUnavailable && !noDefaultForUnit && !needsConfiguration && customized && <QcStatusBadge tone="custom">{t('states.custom')}</QcStatusBadge>}
            {!pluginUnavailable && !noDefaultForUnit && !needsConfiguration && !customized && (
              <QcStatusBadge tone="recommended">
                {suggestedScreeningPreset
                  ? t('states.screeningPreset')
                  : scopeType === 'parameter' ? t('states.recommended') : t('states.inherited')}
              </QcStatusBadge>
            )}
          </div>
          <p>{checkDescription(check.check_code, metadata)}</p>
        </div>
        {!editing && !pluginUnavailable && (
          <button className="btn" type="button" onClick={onStartEditing}>
            {existingOverride
              ? t('actions.editSettings')
              : suggestedScreeningPreset ? t('actions.reviewScreeningPreset') : t('actions.customize')}
          </button>
        )}
      </div>

      {pluginUnavailable ? (
        <div className="qc-unavailable-state">
          <strong>{t('unavailable.title', { check: checkName(check.check_code, metadata) })}</strong>
          <p>{t('unavailable.description')}</p>
          <div className="qc-inline-actions">
            <Link className="btn" to="/admin/qc/extensions">{t('extensions.review')}</Link>
            {existingOverride && (
              <button className="btn ghost" type="button" onClick={() => setConfirmReset(true)}>{t('actions.resetCheck')}</button>
            )}
          </div>
        </div>
      ) : noDefaultForUnit ? (
        <div className="qc-needs-configuration qc-no-default-state">
          <strong>{t('noDefault.title', { unit: unitSymbol(applicableUnit) })}</strong>
          <p>{t('noDefault.description', {
            parameter: policy.parameter.display_name,
            unit: unitSymbol(applicableUnit),
          })}</p>
        </div>
      ) : needsConfiguration ? (
        <div className="qc-needs-configuration">
          <strong>{t('needsConfiguration.title')}</strong>
          <p>{t('needsConfiguration.description', { parameter: policy.parameter.display_name })}</p>
        </div>
      ) : policyIssue ? (
        <div className="error-banner">
          <strong>{t('policyIssues.title')}</strong>
          <span>{userFacingPolicyIssue(check.reason_code)}</span>
        </div>
      ) : (
        <div className="qc-check-summary">
          <div className="qc-effective-value">
            <span>{t('checkCard.currentSetting')}</span>
            <strong>
              {!check.enabled
                ? t('states.off')
                : primaryValue !== null
                  ? `${formatQcNumber(primaryValue)} ${unitSymbol(applicableUnit)}`.trim()
                  : t('states.on')}
            </strong>
          </div>
          <div className="qc-check-facts">
            <div><span>{t('checkCard.status')}</span><strong>{check.enabled ? t('states.enabled') : t('states.disabled')}</strong></div>
            <div>
              <span>{t('checkCard.uses')}</span>
              <strong>{suggestedScreeningPreset
                ? t('provenance.screeningPreset')
                : provenanceLabel(displayedValueSource, {
                    scopeType,
                    parameterName: policy.parameter.display_name,
                    sourceName: policy.data_source?.name,
                  })}
              </strong>
            </div>
          </div>
          {check.enabled && check.failure_action && (
            <div className="qc-failure-summary">
              <span>{t('checkCard.whenFails')}</span>
              <strong>{failureActionLabel(check.failure_action)}</strong>
              <p>{failureActionDescription(check.failure_action)}</p>
            </div>
          )}
        </div>
      )}

      {check.check_code === 'baseline_drift' && (check.enabled || suggestedScreeningPreset) && metadata && (
        <div className={suggestedScreeningPreset ? 'qc-screening-preset' : undefined}>
          {suggestedScreeningPreset && (
            <div className="qc-screening-preset-intro">
              <strong>{t('checks.baselineDrift.suggestedSettings')}</strong>
              <p>{t('checks.baselineDrift.suggestedDescription')}</p>
              {check.failure_action && (
                <p>{t('checks.baselineDrift.suggestedFailureAction', {
                  action: failureActionLabel(check.failure_action),
                })}</p>
              )}
            </div>
          )}
          <div
            className="qc-sensor-property-list"
            aria-label={t(suggestedScreeningPreset
              ? 'checks.baselineDrift.suggestedSettings'
              : 'checks.baselineDrift.effectiveSettings')}
          >
            {metadata.settings.map((setting) => {
              const isUnitSetting = metadata.unit_settings.includes(setting.setting_code);
              // Disabled presets may have only configured values, in the original
              // policy unit. Do not relabel them as the selected evaluation unit.
              const settingUnitCode = check.evaluation_settings[setting.setting_code] == null
                ? check.configured_unit_code
                : check.evaluation_unit_code;
              return (
                <div className="qc-sensor-property" key={setting.setting_code}>
                  <span>{settingLabel(check.check_code, setting.setting_code, setting.label)}</span>
                  <strong>
                    {displayedSetting(setting.setting_code, setting.value_type)}
                    {isUnitSetting ? ` ${unitSymbol(applicableUnit, settingUnitCode)}` : ''}
                  </strong>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {editing && metadata && (
        <QcCheckEditor
          policy={policy}
          check={check}
          metadata={metadata}
          affectedSensorCount={affectedSensorCount}
          onSave={onSave}
          onPreview={onPreview}
          onCancel={onStopEditing}
        />
      )}

      {resetError && <div className="error-banner" role="alert">{resetError}</div>}
      {!editing && existingOverride && !pluginUnavailable && (
        <button className="qc-reset-check-link" type="button" onClick={() => setConfirmReset(true)}>
          {scopeType === 'parameter'
            ? check.check_code === 'baseline_drift'
              ? t('actions.resetCheckScreeningPreset')
              : t('actions.resetCheckRecommended')
            : t('actions.resetCheckParameter', { parameter: policy.parameter.display_name })}
        </button>
      )}
      <QcConfirmationDialog
        open={confirmReset}
        title={t('confirm.resetCheckTitle', { check: checkName(check.check_code, metadata) })}
        description={scopeType === 'parameter'
          ? check.check_code === 'baseline_drift'
            ? t('confirm.resetParameterBaselineDriftDescription', { parameter: policy.parameter.display_name })
            : t('confirm.resetParameterCheckDescription', { parameter: policy.parameter.display_name })
          : t('confirm.resetSourceCheckDescription', { source: policy.data_source?.name || '', parameter: policy.parameter.display_name })}
        confirmLabel={t('actions.resetCheck')}
        busy={resetting}
        onCancel={() => setConfirmReset(false)}
        onConfirm={() => void reset()}
      />
    </article>
  );
}
