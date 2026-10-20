import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import AdminPageLayout from '../components/AdminPageLayout';
import {
  countQcSensors,
  getSourceParameterPolicy,
  listQcChecks,
  mergeCheckOverride,
  previewQcPolicy,
  replaceSourceParameterPolicy,
  resetSourceParameterCheck,
  resetSourceParameterPolicy,
} from './api';
import QcCheckCard from './QcCheckCard';
import QcConfirmationDialog from './QcConfirmationDialog';
import QcStatusBadge from './QcStatusBadge';
import { isUnitScopedCheck, unitSymbol } from './presentation';
import type {
  QcCheckMetadata,
  QcOverrideInput,
  QcPolicyResponse,
  QcPreviewResponse,
  QcResolvedCheck,
} from './types';

function sourceUnconfiguredCheck(metadata: QcCheckMetadata): QcResolvedCheck {
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
    reason_code: 'unconfigured_check',
    message: '',
    applicability: 'applicable' as const,
    default_profile_version: '',
    applied_layers: [],
    most_specific_source: null,
    property_provenance: {},
  };
  return { ...inherited, inherited_policy: inherited };
}

export default function AdminQcSourcePolicy() {
  const { t } = useTranslation('qualityControl');
  const navigate = useNavigate();
  const params = useParams();
  const parameterId = Number(params.parameterId);
  const externalApiId = Number(params.externalApiId);
  const [policy, setPolicy] = useState<QcPolicyResponse | null>(null);
  const [metadata, setMetadata] = useState<QcCheckMetadata[]>([]);
  const [sensorCount, setSensorCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [editingCheck, setEditingCheck] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [selectedUnitCode, setSelectedUnitCode] = useState<string | null>(null);

  const load = async () => {
    if (![parameterId, externalApiId].every((value) => Number.isInteger(value) && value > 0)) {
      setError(true);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      const [nextPolicy, checkMetadata, sensors] = await Promise.all([
        getSourceParameterPolicy(externalApiId, parameterId),
        listQcChecks(),
        countQcSensors({ parameterId, externalApiId }),
      ]);
      setPolicy(nextPolicy);
      setSelectedUnitCode((current) => (
        nextPolicy.parameter.supported_units.some((unit) => unit.unit_code === current)
          ? current
          : nextPolicy.parameter.default_unit?.unit_code
            ?? nextPolicy.parameter.supported_units[0]?.unit_code
            ?? null
      ));
      setMetadata(checkMetadata);
      setSensorCount(sensors.total);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // Route identifiers are the only load triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalApiId, parameterId]);

  const checks = useMemo(() => {
    if (!policy) return [];
    const selectedChecks = policy.checks.filter((check) => (
      !isUnitScopedCheck(metadata.find((item) => item.check_code === check.check_code))
      || check.applicable_unit_code === selectedUnitCode
    ));
    const byCode = new Map(selectedChecks.map((check) => [check.check_code, check]));
    const ordered = metadata.map((item) => byCode.get(item.check_code) ?? sourceUnconfiguredCheck(item));
    const metadataCodes = new Set(metadata.map((item) => item.check_code));
    ordered.push(...selectedChecks.filter((check) => !metadataCodes.has(check.check_code)));
    return ordered;
  }, [metadata, policy, selectedUnitCode]);
  const metadataByCode = useMemo(() => new Map(metadata.map((item) => [item.check_code, item])), [metadata]);

  const returnToParameter = (message?: string) => {
    navigate(`/admin/qc/parameters/${parameterId}`, { state: message ? { qcNotice: message } : undefined });
  };

  const saveCheck = async (check: QcResolvedCheck, replacement: QcOverrideInput | null) => {
    const latest = await getSourceParameterPolicy(externalApiId, parameterId);
    const updated = await replaceSourceParameterPolicy(
      externalApiId,
      parameterId,
      mergeCheckOverride(
        latest.overrides,
        check.check_code,
        metadataByCode.get(check.check_code)?.unit_settings ?? [],
        check.applicable_unit_code,
        replacement,
      ),
    );
    if (updated.overrides.length === 0) {
      returnToParameter(t('notices.sourceRemoved'));
      return;
    }
    setPolicy(updated);
    if (replacement?.policy_unit_code) setSelectedUnitCode(replacement.policy_unit_code);
    setEditingCheck(null);
    setNotice(t('notices.saved'));
  };

  const previewCheck = (checkCode: string, overrides: QcOverrideInput[]): Promise<QcPreviewResponse> => (
    previewQcPolicy({
      scope_type: 'source_parameter',
      parameter_id: parameterId,
      external_api_id: externalApiId,
      hours: 24,
      check_codes: [checkCode],
      overrides,
    })
  );

  const resetCheck = async (check: QcResolvedCheck) => {
    const updated = await resetSourceParameterCheck(
      externalApiId,
      parameterId,
      check.check_code,
      check.applicable_unit_code,
    );
    if (updated.overrides.length === 0) {
      returnToParameter(t('notices.sourceRemoved'));
      return;
    }
    setPolicy(updated);
    setEditingCheck(null);
    setNotice(t('notices.checkReset'));
  };

  const resetAll = async () => {
    setResetting(true);
    try {
      await resetSourceParameterPolicy(externalApiId, parameterId);
      returnToParameter(t('notices.sourceRemoved'));
    } finally {
      setResetting(false);
    }
  };

  if (loading) {
    return (
      <AdminPageLayout title={t('source.loadingTitle')} contentClassName="qc-admin-page">
        <div className="info-banner">{t('source.loading')}</div>
      </AdminPageLayout>
    );
  }
  if (error || !policy || !policy.data_source) {
    return (
      <AdminPageLayout title={policy?.data_source && policy.scope.parameter_id === parameterId && policy.scope.external_api_id === externalApiId ? t('source.title', { source: policy.data_source?.name, parameter: policy.parameter.display_name }) : t('source.sourceIdentity', { source: params.externalApiId, parameter: params.parameterId })} breadcrumbs={[
          { label: t('breadcrumbs.admin'), to: '/admin' },
          { label: t('breadcrumbs.qualityControl'), to: '/admin/qc' },
          { label: t('detail.parameterIdentity', { id: params.parameterId }), to: `/admin/qc/parameters/${parameterId}` },
          { label: t('source.errorTitle') },
        ]} contentClassName="qc-admin-page">
        <div role="alert" className="error-banner qc-state-banner">
          <span>{t('source.loadError')}</span>
          <button className="btn shrink-0" type="button" onClick={() => void load()}>{t('actions.retry')}</button>
        </div>
      </AdminPageLayout>
    );
  }

  const sourceName = policy.data_source.name;
  const selectedUnit = policy.parameter.supported_units.find(
    (unit) => unit.unit_code === selectedUnitCode,
  ) ?? policy.parameter.default_unit;
  return (
    <AdminPageLayout
      title={t('source.title', { source: sourceName, parameter: policy.parameter.display_name })}
      description={t('source.description', { source: sourceName, parameter: policy.parameter.display_name })}
      breadcrumbs={[
        { label: t('breadcrumbs.admin'), to: '/admin' },
        { label: t('breadcrumbs.qualityControl'), to: '/admin/qc' },
        { label: policy.parameter.display_name, to: `/admin/qc/parameters/${parameterId}` },
        { label: sourceName },
      ]}
      actions={policy.overrides.length > 0 ? (
        <button className="btn" type="button" onClick={() => setConfirmReset(true)}>{t('actions.removeException')}</button>
      ) : undefined}
      contentClassName="qc-admin-page qc-detail-page qc-source-page"
    >
      {notice && <div className="success-banner" role="status">{notice}</div>}
      <section className="card qc-source-context">
        <div>
          <span className="qc-eyebrow">{t('source.dataSourceException')}</span>
          <h2>{sourceName}</h2>
          <p>{policy.overrides.length > 0
            ? t('source.customSummary', { source: sourceName })
            : t('source.inheritedSummary', { source: sourceName, parameter: policy.parameter.display_name })}</p>
        </div>
        <div className="qc-source-context-facts">
          <div><span>{t('columns.sensors')}</span><strong>{sensorCount}</strong></div>
          <div><span>{t('source.customizedChecks')}</span><strong>{policy.overrides.length}</strong></div>
          {policy.overrides.length > 0
            ? <QcStatusBadge tone="custom">{t('states.custom')}</QcStatusBadge>
            : <QcStatusBadge tone="recommended">{t('states.inherited')}</QcStatusBadge>}
        </div>
      </section>

      {policy.overrides.length === 0 && (
        <div className="info-banner">{t('source.startHelp', { source: sourceName, parameter: policy.parameter.display_name })}</div>
      )}

      <section className="qc-check-section" aria-labelledby="source-checks-title">
        <div className="qc-section-heading">
          <div>
            <h2 id="source-checks-title">{t('source.checksTitle')}</h2>
            <p>{t('source.checksDescription', { parameter: policy.parameter.display_name })}</p>
          </div>
          <label className="qc-field qc-unit-context-select">
            <span>{t('editor.unit')}</span>
            <select
              value={selectedUnitCode ?? ''}
              onChange={(event) => {
                setSelectedUnitCode(event.target.value);
                setEditingCheck(null);
              }}
            >
              {policy.parameter.supported_units.map((unit) => (
                <option key={unit.unit_code} value={unit.unit_code}>{unit.symbol}</option>
              ))}
            </select>
          </label>
        </div>
        <p className="qc-selected-unit-note">{t('detail.editingUnit', { unit: unitSymbol(selectedUnit) })}</p>
        <div className="qc-check-list">
          {checks.map((check) => (
            <QcCheckCard
              key={`${check.check_code}:${check.applicable_unit_code ?? 'unitless'}`}
              policy={policy}
              check={check}
              metadata={metadataByCode.get(check.check_code)}
              affectedSensorCount={sensorCount}
              editing={editingCheck === `${check.check_code}:${check.applicable_unit_code ?? 'unitless'}`}
              onStartEditing={() => { setEditingCheck(`${check.check_code}:${check.applicable_unit_code ?? 'unitless'}`); setNotice(null); }}
              onStopEditing={() => setEditingCheck(null)}
              onSave={(replacement) => saveCheck(check, replacement)}
              onPreview={(overrides) => previewCheck(check.check_code, overrides)}
              onResetCheck={() => resetCheck(check)}
            />
          ))}
        </div>
      </section>

      <QcConfirmationDialog
        open={confirmReset}
        title={t('confirm.removeSourceTitle', { source: sourceName })}
        description={t('confirm.removeSourceDescription', { source: sourceName, parameter: policy.parameter.display_name })}
        confirmLabel={t('actions.removeException')}
        busy={resetting}
        onCancel={() => setConfirmReset(false)}
        onConfirm={() => void resetAll()}
      />
    </AdminPageLayout>
  );
}
