import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import AdminPageLayout from '../components/AdminPageLayout';
import {
  getSensorPolicy,
  listQcChecks,
  mergeCheckOverride,
  previewQcPolicy,
  replaceSensorPolicy,
  resetSensorCheck,
  resetSensorPolicy,
} from './api';
import { sensorCustomPropertyCount, unitSymbol } from './presentation';
import QcConfirmationDialog from './QcConfirmationDialog';
import QcSensorCheckCard from './QcSensorCheckCard';
import QcStatusBadge from './QcStatusBadge';
import type {
  QcCheckMetadata,
  QcOverrideInput,
  QcPolicyResponse,
  QcPreviewResponse,
  QcResolvedCheck,
} from './types';

function unsupportedSensorCheck(metadata: QcCheckMetadata): QcResolvedCheck {
  const inherited = {
    check_code: metadata.check_code,
    status: 'unavailable' as const,
    enabled: false,
    failure_action: null,
    configured_settings: {},
    evaluation_settings: {},
    configured_unit_code: null,
    evaluation_unit_code: null,
    applicable_unit_code: null,
    unit_conversion: null,
    reason_code: 'unsupported_parameter',
    message: '',
    applicability: 'applicable' as const,
    default_profile_version: '',
    applied_layers: [],
    most_specific_source: null,
    property_provenance: {},
  };
  return { ...inherited, inherited_policy: inherited };
}

export default function AdminQcSensorPolicy() {
  const { t } = useTranslation('qualityControl');
  const { sensorId: sensorIdText } = useParams();
  const sensorId = Number(sensorIdText);
  const contextHeadingRef = useRef<HTMLHeadingElement>(null);
  const hasFocusedInitialContext = useRef(false);
  const [policy, setPolicy] = useState<QcPolicyResponse | null>(null);
  const [metadata, setMetadata] = useState<QcCheckMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [editingCheck, setEditingCheck] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  const load = async () => {
    if (!Number.isInteger(sensorId) || sensorId < 1) {
      setError(true);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      const [nextPolicy, checkMetadata] = await Promise.all([
        getSensorPolicy(sensorId),
        listQcChecks(),
      ]);
      setPolicy(nextPolicy);
      setMetadata(checkMetadata);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    hasFocusedInitialContext.current = false;
    void load();
    // The route identifier is the only load trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sensorId]);

  useEffect(() => {
    if (!loading && policy && !hasFocusedInitialContext.current) {
      hasFocusedInitialContext.current = true;
      contextHeadingRef.current?.focus();
    }
  }, [loading, policy]);

  const checks = useMemo(() => {
    if (!policy) return [];
    const byCode = new Map(policy.checks.map((check) => [check.check_code, check]));
    const ordered = metadata.map((item) => byCode.get(item.check_code) ?? unsupportedSensorCheck(item));
    const metadataCodes = new Set(metadata.map((item) => item.check_code));
    ordered.push(...policy.checks.filter((check) => !metadataCodes.has(check.check_code)));
    return ordered;
  }, [metadata, policy]);
  const metadataByCode = useMemo(
    () => new Map(metadata.map((item) => [item.check_code, item])),
    [metadata],
  );

  const saveCheck = async (check: QcResolvedCheck, replacement: QcOverrideInput | null) => {
    const latest = await getSensorPolicy(sensorId);
    const updated = await replaceSensorPolicy(
      sensorId,
      mergeCheckOverride(
        latest.overrides,
        check.check_code,
        metadataByCode.get(check.check_code)?.unit_settings ?? [],
        check.applicable_unit_code,
        replacement,
      ),
    );
    setPolicy(updated);
    setEditingCheck(null);
    setNotice(t('sensors.notices.saved'));
    setResetError(null);
  };

  const previewCheck = (checkCode: string, overrides: QcOverrideInput[]): Promise<QcPreviewResponse> => (
    previewQcPolicy({
      scope_type: 'sensor',
      sensor_id: sensorId,
      hours: 24,
      check_codes: [checkCode],
      overrides,
    })
  );

  const resetCheck = async (check: QcResolvedCheck) => {
    setPolicy(await resetSensorCheck(
      sensorId,
      check.check_code,
      check.applicable_unit_code,
    ));
    setEditingCheck(null);
    setNotice(t('sensors.notices.checkReset'));
    setResetError(null);
  };

  const resetAll = async () => {
    setResetting(true);
    setResetError(null);
    try {
      setPolicy(await resetSensorPolicy(sensorId));
      setConfirmReset(false);
      setEditingCheck(null);
      setNotice(t('sensors.notices.allReset'));
      window.requestAnimationFrame(() => contextHeadingRef.current?.focus());
    } catch {
      setResetError(t('sensors.notices.resetError'));
      setConfirmReset(false);
    } finally {
      setResetting(false);
    }
  };

  if (loading) {
    return (
      <AdminPageLayout title={t('sensors.detail.loadingTitle')} contentClassName="qc-admin-page">
        <div className="info-banner">{t('sensors.detail.loading')}</div>
      </AdminPageLayout>
    );
  }

  if (error || !policy || !policy.sensor || !policy.data_source) {
    return (
      <AdminPageLayout title={policy?.sensor?.sensor_id === sensorId ? `${policy.sensor.device_name} · ${policy.parameter.display_name}` : t('sensors.detail.sensorIdentity', { id: sensorIdText })} breadcrumbs={[
          { label: t('breadcrumbs.admin'), to: '/admin' },
          { label: t('breadcrumbs.qualityControl'), to: '/admin/qc' },
          { label: t('sensors.breadcrumb'), to: '/admin/qc/sensors' },
          { label: t('sensors.detail.errorTitle') },
        ]} contentClassName="qc-admin-page">
        <div role="alert" className="error-banner qc-state-banner">
          <span>{t('sensors.detail.loadError')}</span>
          <button className="btn shrink-0" type="button" onClick={() => void load()}>{t('actions.retry')}</button>
        </div>
      </AdminPageLayout>
    );
  }

  const sensor = policy.sensor;
  const customPropertyCount = sensorCustomPropertyCount(policy.overrides);
  const activeCheckCount = checks.filter((check) => check.enabled && check.status === 'ready').length;
  const disabledCheckCount = checks.filter((check) => check.status === 'disabled').length;
  const attentionCheckCount = checks.filter((check) => (
    check.status === 'unavailable' && check.reason_code !== 'unsupported_parameter'
  )).length;

  return (
    <AdminPageLayout
      title={t('sensors.detail.title', {
        parameter: policy.parameter.display_name,
        device: sensor.device_name,
      })}
      description={t('sensors.detail.description', {
        source: sensor.manual_data_source_name || policy.data_source.name,
        parameter: policy.parameter.display_name,
        unit: unitSymbol(sensor.unit),
      })}
      breadcrumbs={[
        { label: t('breadcrumbs.admin'), to: '/admin' },
        { label: t('breadcrumbs.qualityControl'), to: '/admin/qc' },
        { label: t('sensors.breadcrumb'), to: '/admin/qc/sensors' },
        { label: `${sensor.device_name} · ${policy.parameter.display_name}` },
      ]}
      actions={(
        <div className="qc-header-actions">
          <Link className="btn" to={`/admin/devices/${sensor.device_id}/edit`}>{t('sensors.actions.viewDevice')}</Link>
          {policy.overrides.length > 0 && (
            <button className="btn" type="button" onClick={() => setConfirmReset(true)}>{t('sensors.actions.resetAll')}</button>
          )}
        </div>
      )}
      contentClassName="qc-admin-page qc-detail-page qc-sensor-detail-page"
    >
      {notice && <div className="success-banner" role="status">{notice}</div>}
      {sensor.manual_data_source_name && <p className="info-banner">{t('sensors.detail.manualPolicySource', { source: policy.data_source.name })}</p>}
      {resetError && <div className="error-banner" role="alert">{resetError}</div>}

      <section className="card qc-sensor-context" aria-labelledby="qc-sensor-context-title">
        <div className="qc-sensor-context-identity">
          <span className="qc-eyebrow">{t('sensors.detail.sensorContext')}</span>
          <h2 id="qc-sensor-context-title" ref={contextHeadingRef} tabIndex={-1}>{sensor.device_name}</h2>
          <p>{sensor.external_sensor_id
            ? t('sensors.detail.externalIdentifier', { identifier: sensor.external_sensor_id })
            : t('sensors.detail.internalIdentifier', { identifier: sensor.sensor_id })}</p>
        </div>
        <div className="qc-sensor-context-status">
          {customPropertyCount > 0 ? (
            <>
              <QcStatusBadge tone="custom">{t('sensors.detail.customSummary', { count: customPropertyCount })}</QcStatusBadge>
              <p>{t('sensors.detail.customSummaryHelp')}</p>
            </>
          ) : policy.overrides.length > 0 ? (
            <>
              <QcStatusBadge tone="custom">{t('sensors.search.statusCustom')}</QcStatusBadge>
              <p>{t('sensors.detail.customSummaryHelp')}</p>
            </>
          ) : policy.advanced_aggregation_override_count > 0 ? (
            <>
              <QcStatusBadge tone="neutral">{t('sensors.detail.advancedSummary')}</QcStatusBadge>
              <p>{t('sensors.detail.advancedSummaryHelp')}</p>
            </>
          ) : (
            <>
              <QcStatusBadge tone="recommended">{t('sensors.detail.inheritedSummary')}</QcStatusBadge>
              <p>{t('sensors.detail.inheritedSummaryHelp')}</p>
            </>
          )}
        </div>
      </section>

      {policy.advanced_aggregation_override_count > 0 && customPropertyCount > 0 && (
        <div className="info-banner">{t('sensors.detail.advancedAlsoApplies')}</div>
      )}

      <section className="card qc-sensor-check-overview" aria-label={t('sensors.detail.checkOverview')}>
        <div><span>{t('sensors.detail.activeChecks')}</span><strong>{activeCheckCount}</strong></div>
        <div><span>{t('sensors.detail.disabledChecks')}</span><strong>{disabledCheckCount}</strong></div>
        <div><span>{t('sensors.detail.attentionChecks')}</span><strong>{attentionCheckCount}</strong></div>
      </section>

      <section className="qc-check-section" aria-labelledby="qc-sensor-checks-title">
        <div className="qc-section-heading">
          <div>
            <h2 id="qc-sensor-checks-title">{t('sensors.detail.checksTitle')}</h2>
            <p>{t('sensors.detail.checksDescription')}</p>
          </div>
        </div>
        <div className="qc-check-list">
          {checks.map((check) => (
            <QcSensorCheckCard
              key={check.check_code}
              policy={policy}
              check={check}
              metadata={metadataByCode.get(check.check_code)}
              editing={editingCheck === check.check_code}
              onStartEditing={() => { setEditingCheck(check.check_code); setNotice(null); }}
              onStopEditing={() => setEditingCheck(null)}
              onSave={(replacement) => saveCheck(check, replacement)}
              onPreview={(overrides) => previewCheck(check.check_code, overrides)}
              onResetCheck={() => resetCheck(check)}
            />
          ))}
        </div>
      </section>

      <details className="card qc-more-details">
        <summary>{t('detail.moreDetails')}</summary>
        <dl>
          <div><dt>{t('sensors.detail.internalSensorId')}</dt><dd>{sensor.sensor_id}</dd></div>
          <div><dt>{t('detail.profileVersion')}</dt><dd>{policy.default_profile_version}</dd></div>
          <div><dt>{t('sensors.detail.timeResolution')}</dt><dd>{sensor.aggregation_code || t('sensors.detail.notAvailable')}</dd></div>
          <div><dt>{t('detail.advancedOverrides')}</dt><dd>{policy.advanced_aggregation_override_count}</dd></div>
        </dl>
        {policy.advanced_aggregation_override_count > 0 && <p>{t('sensors.detail.advancedDetails')}</p>}
      </details>

      <QcConfirmationDialog
        open={confirmReset}
        title={t('sensors.confirm.resetAllTitle')}
        description={t('sensors.confirm.resetAllDescription')}
        confirmLabel={t('sensors.actions.resetAll')}
        busy={resetting}
        onCancel={() => setConfirmReset(false)}
        onConfirm={() => void resetAll()}
      />
    </AdminPageLayout>
  );
}
