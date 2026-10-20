import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import {
  checkDescription,
  checkHasAdvancedSensorSetting,
  checkName,
  failureActionLabel,
  formatQcNumber,
  isUnitScopedCheck,
  sensorCustomPropertyCount,
  sensorProvenanceLabel,
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
  QcPolicyLayer,
  QcPolicyResponse,
  QcPreviewResponse,
  QcResolvedCheck,
} from './types';

const UNIT_ISSUES = new Set(['unknown_unit', 'conversion_not_supported']);
const CONFIGURATION_ISSUES = new Set([
  'unconfigured_check',
  'missing_required_setting',
  'missing_policy_unit',
  'missing_failure_action',
]);

export default function QcSensorCheckCard({
  policy,
  check,
  metadata,
  editing,
  onStartEditing,
  onStopEditing,
  onSave,
  onPreview,
  onResetCheck,
}: {
  policy: QcPolicyResponse;
  check: QcResolvedCheck;
  metadata?: QcCheckMetadata;
  editing: boolean;
  onStartEditing: () => void;
  onStopEditing: () => void;
  onSave: (replacement: QcOverrideInput | null) => Promise<void>;
  onPreview: (overrides: QcOverrideInput[]) => Promise<QcPreviewResponse>;
  onResetCheck: () => Promise<void>;
}) {
  const { t } = useTranslation('qualityControl');
  const cardRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const sensor = policy.sensor;
  const unitScoped = isUnitScopedCheck(metadata);
  const applicableUnitCode = check.applicable_unit_code ?? check.evaluation_unit_code;
  const existingOverride = policy.overrides.find((override) => (
    override.check_code === check.check_code
    && (!unitScoped || override.policy_unit?.unit_code === applicableUnitCode)
  ));
  const customPropertyCount = sensorCustomPropertyCount(existingOverride ? [existingOverride] : []);
  const pluginUnavailable = !metadata || !metadata.available;
  const noDefaultForUnit = unitScoped && check.status === 'not_configured';
  const noRecommendation = check.reason_code === 'unsupported_parameter';
  const unitIssue = UNIT_ISSUES.has(check.reason_code || '');
  const needsConfiguration = !noRecommendation && (
    (!noDefaultForUnit && check.status === 'not_configured')
    || CONFIGURATION_ISSUES.has(check.reason_code || '')
  );
  const sensorSettingInvalid = Boolean(
    existingOverride
    && check.status === 'unavailable'
    && !pluginUnavailable
    && !unitIssue
    && !needsConfiguration,
  );
  const otherPolicyIssue = check.status === 'unavailable'
    && !pluginUnavailable
    && !noRecommendation
    && !unitIssue
    && !needsConfiguration
    && !sensorSettingInvalid;
  const hasAdvancedSetting = checkHasAdvancedSensorSetting(check);

  useEffect(() => {
    if (!editing) return;
    const firstControl = cardRef.current?.querySelector<HTMLElement>(
      '.qc-check-editor input:not(:disabled), .qc-check-editor select:not(:disabled)',
    );
    firstControl?.focus();
  }, [editing]);

  const provenance = (layer: QcPolicyLayer | null | undefined) => sensorProvenanceLabel(layer, {
    parameterName: policy.parameter.display_name,
    sourceName: policy.data_source?.name || '',
  });

  const displayedSetting = (settingCode: string, valueType: string): string => {
    const value = check.evaluation_settings[settingCode];
    if (value === undefined || value === null) return t('states.notConfigured');
    if (valueType === 'number' || valueType === 'integer') return formatQcNumber(value);
    if (valueType === 'boolean') return value ? t('states.on') : t('states.off');
    const choiceKey = `choices.${String(value)}`;
    return t(choiceKey as never, { defaultValue: String(value) });
  };

  const reset = async () => {
    setResetting(true);
    setResetError(null);
    try {
      await onResetCheck();
      setConfirmReset(false);
      window.requestAnimationFrame(() => headingRef.current?.focus());
    } catch {
      setResetError(t('editor.resetError'));
      setConfirmReset(false);
    } finally {
      setResetting(false);
    }
  };

  const save = async (replacement: QcOverrideInput | null) => {
    await onSave(replacement);
    window.requestAnimationFrame(() => headingRef.current?.focus());
  };

  const cancelEditing = () => {
    onStopEditing();
    window.requestAnimationFrame(() => headingRef.current?.focus());
  };

  let badge = <QcStatusBadge tone="recommended">{t('states.inherited')}</QcStatusBadge>;
  if (pluginUnavailable) badge = <QcStatusBadge tone="unavailable">{t('states.unavailable')}</QcStatusBadge>;
  else if (noDefaultForUnit) badge = <QcStatusBadge tone="neutral">{t('states.notConfigured')}</QcStatusBadge>;
  else if (unitIssue) badge = <QcStatusBadge tone="unavailable">{t('sensors.states.unitIssueBadge')}</QcStatusBadge>;
  else if (needsConfiguration) badge = <QcStatusBadge tone="attention">{t('states.needsConfiguration')}</QcStatusBadge>;
  else if (sensorSettingInvalid) badge = <QcStatusBadge tone="attention">{t('sensors.states.invalidSensorBadge')}</QcStatusBadge>;
  else if (otherPolicyIssue) badge = <QcStatusBadge tone="attention">{t('filters.needsAttention')}</QcStatusBadge>;
  else if (noRecommendation) badge = <QcStatusBadge tone="neutral">{t('states.noRecommendation')}</QcStatusBadge>;
  else if (customPropertyCount > 0) {
    badge = <QcStatusBadge tone="custom">{t('sensors.detail.customPropertyCount', { count: customPropertyCount })}</QcStatusBadge>;
  } else if (hasAdvancedSetting) {
    badge = <QcStatusBadge tone="neutral">{t('sensors.detail.advancedSetting')}</QcStatusBadge>;
  } else if (existingOverride) {
    badge = <QcStatusBadge tone="custom">{t('sensors.search.statusCustom')}</QcStatusBadge>;
  }

  return (
    <article ref={cardRef} className={`qc-check-card qc-sensor-check-card${editing ? ' qc-check-card-editing' : ''}`}>
      <div className="qc-check-card-header">
        <div>
          <div className="qc-check-heading-row">
            <h2 ref={headingRef} tabIndex={-1}>{checkName(check.check_code, metadata)}</h2>
            {badge}
          </div>
          <p>{checkDescription(check.check_code, metadata)}</p>
        </div>
        {!editing && !pluginUnavailable && (
          <button className="btn" type="button" onClick={onStartEditing}>
            {existingOverride ? t('actions.editSettings') : t('actions.customize')}
          </button>
        )}
      </div>

      {pluginUnavailable && (
        <div className="qc-unavailable-state">
          <strong>{t('unavailable.title', { check: checkName(check.check_code, metadata) })}</strong>
          <p>{t('unavailable.description')}</p>
          <div className="qc-inline-actions">
            <Link className="btn" to="/admin/qc/extensions">{t('extensions.review')}</Link>
            {existingOverride && <button className="btn ghost" type="button" onClick={() => setConfirmReset(true)}>{t('actions.resetCheck')}</button>}
          </div>
        </div>
      )}
      {!pluginUnavailable && noRecommendation && (
        <div className="qc-sensor-state qc-sensor-no-recommendation">
          <strong>{t('sensors.states.noRecommendationTitle')}</strong>
          <p>{t('sensors.states.noRecommendationDescription', { parameter: policy.parameter.display_name })}</p>
        </div>
      )}
      {!pluginUnavailable && noDefaultForUnit && (
        <div className="qc-sensor-state qc-sensor-no-recommendation">
          <strong>{t('noDefault.title', { unit: unitSymbol(sensor?.unit) })}</strong>
          <p>{t('noDefault.description', {
            parameter: policy.parameter.display_name,
            unit: unitSymbol(sensor?.unit),
          })}</p>
        </div>
      )}
      {!pluginUnavailable && needsConfiguration && (
        <div className="qc-needs-configuration">
          <strong>{t('sensors.states.inheritedNeedsConfigurationTitle')}</strong>
          <p>{t('sensors.states.inheritedNeedsConfigurationDescription')}</p>
        </div>
      )}
      {!pluginUnavailable && unitIssue && (
        <div className="qc-sensor-state qc-sensor-unit-issue">
          <strong>{t('sensors.states.unitIssueTitle')}</strong>
          <p>{t('sensors.states.unitIssueDescription')}</p>
        </div>
      )}
      {!pluginUnavailable && sensorSettingInvalid && (
        <div className="error-banner qc-sensor-card-alert" role="alert">
          <strong>{t('sensors.states.invalidSensorTitle')}</strong>
          <span>{userFacingPolicyIssue(check.reason_code)}</span>
        </div>
      )}
      {!pluginUnavailable && otherPolicyIssue && (
        <div className="error-banner qc-sensor-card-alert" role="alert">
          <strong>{t('policyIssues.title')}</strong>
          <span>{userFacingPolicyIssue(check.reason_code)}</span>
        </div>
      )}

      {!pluginUnavailable && !noDefaultForUnit && (
        <div className="qc-sensor-property-list">
          <div className="qc-sensor-property">
            <span>{t('checkCard.status')}</span>
            <strong>{check.enabled ? t('states.enabled') : t('states.disabled')}</strong>
            <small>{provenance(check.property_provenance.enabled ?? check.most_specific_source)}</small>
          </div>
          {(check.enabled || noRecommendation || needsConfiguration || unitIssue) && metadata.settings.map((setting) => {
            const isUnitSetting = metadata.unit_settings.includes(setting.setting_code);
            return (
              <div className="qc-sensor-property" key={setting.setting_code}>
                <span>{settingLabel(check.check_code, setting.setting_code, setting.label)}</span>
                <strong>
                  {displayedSetting(setting.setting_code, setting.value_type)}
                  {isUnitSetting && check.evaluation_settings[setting.setting_code] !== undefined
                    ? ` ${unitSymbol(sensor?.unit, check.evaluation_unit_code)}`
                    : ''}
                </strong>
                <small>{provenance(check.property_provenance[`settings.${setting.setting_code}`])}</small>
              </div>
            );
          })}
          {check.enabled && (
            <div className="qc-sensor-property">
              <span>{t('checkCard.whenFails')}</span>
              <strong>{failureActionLabel(check.failure_action)}</strong>
              <small>{provenance(check.property_provenance.failure_action ?? check.most_specific_source)}</small>
            </div>
          )}
        </div>
      )}

      {!pluginUnavailable && check.unit_conversion?.status === 'converted' && (
        <p className="qc-sensor-conversion-note">{t('sensors.detail.convertedUnit', {
          unit: unitSymbol(sensor?.unit, check.evaluation_unit_code),
        })}</p>
      )}

      {editing && metadata && (
        <QcCheckEditor
          policy={policy}
          check={check}
          metadata={metadata}
          affectedSensorCount={1}
          onSave={save}
          onPreview={onPreview}
          onCancel={cancelEditing}
        />
      )}

      {resetError && <div className="error-banner qc-sensor-card-alert" role="alert">{resetError}</div>}
      {!editing && existingOverride && !pluginUnavailable && (
        <button className="qc-reset-check-link" type="button" onClick={() => setConfirmReset(true)}>
          {t('sensors.actions.resetCheck', { check: checkName(check.check_code, metadata) })}
        </button>
      )}

      <QcConfirmationDialog
        open={confirmReset}
        title={t('sensors.confirm.resetCheckTitle', { check: checkName(check.check_code, metadata) })}
        description={t('sensors.confirm.resetCheckDescription')}
        confirmLabel={t('actions.resetCheck')}
        busy={resetting}
        onCancel={() => setConfirmReset(false)}
        onConfirm={() => void reset()}
      />
    </article>
  );
}
