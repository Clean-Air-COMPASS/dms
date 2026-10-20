import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { listExternalAPIs } from '../api';
import type { ExternalAPI } from '../api';
import AdminPageLayout from '../components/AdminPageLayout';
import {
  getParameterPolicy,
  getSourceParameterPolicy,
  listQcChecks,
  listQcParameters,
  mergeCheckOverride,
  previewQcPolicy,
  replaceParameterPolicy,
  resetParameterCheck,
  resetParameterPolicy,
} from './api';
import { checkName, checkValue, formatQcNumber, isUnitScopedCheck, unitSymbol } from './presentation';
import QcCheckCard from './QcCheckCard';
import QcConfirmationDialog from './QcConfirmationDialog';
import QcStatusBadge from './QcStatusBadge';
import type {
  QcCheckMetadata,
  QcOverrideInput,
  QcParameterSummary,
  QcPolicyResponse,
  QcPreviewResponse,
  QcResolvedCheck,
} from './types';

type SourceException = {
  source: ExternalAPI;
  policy: QcPolicyResponse;
};

function unconfiguredCheck(metadata: QcCheckMetadata): QcResolvedCheck {
  const emptyPolicy = {
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
  return { ...emptyPolicy, inherited_policy: emptyPolicy };
}

export default function AdminQcParameterDetail() {
  const { t } = useTranslation('qualityControl');
  const location = useLocation();
  const navigate = useNavigate();
  const { parameterId: parameterIdText } = useParams();
  const parameterId = Number(parameterIdText);
  const [policy, setPolicy] = useState<QcPolicyResponse | null>(null);
  const [summary, setSummary] = useState<QcParameterSummary | null>(null);
  const [metadata, setMetadata] = useState<QcCheckMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [editingCheck, setEditingCheck] = useState<string | null>(null);
  const [confirmFullReset, setConfirmFullReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [notice, setNotice] = useState<string | null>(() => {
    const navigationState = location.state as { qcNotice?: unknown } | null;
    return typeof navigationState?.qcNotice === 'string' ? navigationState.qcNotice : null;
  });
  const [sources, setSources] = useState<ExternalAPI[]>([]);
  const [sourceExceptions, setSourceExceptions] = useState<SourceException[]>([]);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState(false);
  const [showSourcePicker, setShowSourcePicker] = useState(false);
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [selectedUnitCode, setSelectedUnitCode] = useState<string | null>(null);

  const load = async () => {
    if (!Number.isInteger(parameterId) || parameterId < 1) {
      setError(true);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      const [nextPolicy, checkMetadata, parameterResponse] = await Promise.all([
        getParameterPolicy(parameterId),
        listQcChecks(),
        listQcParameters(),
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
      const nextSummary = parameterResponse.items.find((item) => item.parameter_id === parameterId) ?? null;
      setSummary(nextSummary);
      if ((nextSummary?.source_exception_count ?? 0) > 0) {
        void loadSourceExceptions();
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  const loadSourceExceptions = async () => {
    setSourceLoading(true);
    setSourceError(false);
    try {
      const sourceList = await listExternalAPIs({ skipCache: true });
      setSources(sourceList);
      const results = await Promise.allSettled(
        sourceList.map(async (source) => ({
          source,
          policy: await getSourceParameterPolicy(source.external_api_id, parameterId),
        })),
      );
      const fulfilled = results
        .filter((result): result is PromiseFulfilledResult<SourceException> => result.status === 'fulfilled')
        .map((result) => result.value)
        .filter((item) => item.policy.overrides.length > 0)
        .sort((left, right) => left.source.name.localeCompare(right.source.name));
      setSourceExceptions(fulfilled);
      setSourceError(results.some((result) => result.status === 'rejected'));
    } catch {
      setSourceError(true);
    } finally {
      setSourceLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // The route identifier is the only load trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parameterId]);

  const checks = useMemo(() => {
    if (!policy) return [];
    const selectedChecks = policy.checks.filter((check) => (
      !isUnitScopedCheck(metadata.find((item) => item.check_code === check.check_code))
      || check.applicable_unit_code === selectedUnitCode
    ));
    const policyByCode = new Map(selectedChecks.map((check) => [check.check_code, check]));
    const ordered = metadata.map((item) => policyByCode.get(item.check_code) ?? unconfiguredCheck(item));
    const metadataCodes = new Set(metadata.map((item) => item.check_code));
    ordered.push(...selectedChecks.filter((check) => !metadataCodes.has(check.check_code)));
    return ordered;
  }, [metadata, policy, selectedUnitCode]);
  const metadataByCode = useMemo(() => new Map(metadata.map((item) => [item.check_code, item])), [metadata]);

  const saveCheck = async (check: QcResolvedCheck, replacement: QcOverrideInput | null) => {
    const latest = await getParameterPolicy(parameterId);
    const updated = await replaceParameterPolicy(
      parameterId,
      mergeCheckOverride(
        latest.overrides,
        check.check_code,
        metadataByCode.get(check.check_code)?.unit_settings ?? [],
        check.applicable_unit_code,
        replacement,
      ),
    );
    setPolicy(updated);
    if (replacement?.policy_unit_code) setSelectedUnitCode(replacement.policy_unit_code);
    setEditingCheck(null);
    setNotice(t('notices.saved'));
  };

  const previewCheck = (checkCode: string, overrides: QcOverrideInput[]): Promise<QcPreviewResponse> => (
    previewQcPolicy({
      scope_type: 'parameter',
      parameter_id: parameterId,
      hours: 24,
      check_codes: [checkCode],
      overrides,
    })
  );

  const resetCheck = async (check: QcResolvedCheck) => {
    setPolicy(await resetParameterCheck(
      parameterId,
      check.check_code,
      check.applicable_unit_code,
    ));
    setEditingCheck(null);
    setNotice(t('notices.checkReset'));
  };

  const resetAll = async () => {
    setResetting(true);
    try {
      setPolicy(await resetParameterPolicy(parameterId));
      setConfirmFullReset(false);
      setEditingCheck(null);
      setNotice(t('notices.parameterReset'));
    } finally {
      setResetting(false);
    }
  };

  const openSourcePicker = async () => {
    setShowSourcePicker(true);
    if (sources.length > 0) return;
    setSourceLoading(true);
    setSourceError(false);
    try {
      setSources(await listExternalAPIs({ skipCache: true }));
    } catch {
      setSourceError(true);
    } finally {
      setSourceLoading(false);
    }
  };

  const contextName = policy?.scope.parameter_id === parameterId ? policy.parameter.display_name
    : (location.state as { parameterName?: string } | null)?.parameterName || t('detail.parameterIdentity', { id: parameterIdText });
  const contextBreadcrumbs = [
    { label: t('breadcrumbs.admin'), to: '/admin' },
    { label: t('breadcrumbs.qualityControl'), to: '/admin/qc' },
    { label: contextName },
  ];
  if (loading) {
    return (
      <AdminPageLayout title={contextName} breadcrumbs={contextBreadcrumbs} contentClassName="qc-admin-page">
        <div className="info-banner">{t('detail.loading')}</div>
      </AdminPageLayout>
    );
  }

  if (error || !policy) {
    return (
      <AdminPageLayout title={contextName} breadcrumbs={contextBreadcrumbs} contentClassName="qc-admin-page">
        <div role="alert" className="error-banner qc-state-banner">
          <span>{t('detail.loadError')}</span>
          <button className="btn shrink-0" type="button" onClick={() => void load()}>{t('actions.retry')}</button>
        </div>
      </AdminPageLayout>
    );
  }

  const exceptionSourceIds = new Set(sourceExceptions.map((item) => item.source.external_api_id));
  const availableSources = sources.filter((source) => !exceptionSourceIds.has(source.external_api_id));
  const unitSummaryChecks = metadata.filter((checkMetadata) => (
    checkMetadata.overview.visible
    && Boolean(checkMetadata.overview.summary_setting)
    && checkMetadata.unit_settings.includes(checkMetadata.overview.summary_setting || '')
  ));

  return (
    <AdminPageLayout
      title={policy.parameter.display_name}
      description={policy.parameter.parameter_code}
      breadcrumbs={[
        { label: t('breadcrumbs.admin'), to: '/admin' },
        { label: t('breadcrumbs.qualityControl'), to: '/admin/qc' },
        { label: policy.parameter.display_name },
      ]}
      actions={policy.overrides.length > 0 ? (
        <button className="btn" type="button" onClick={() => setConfirmFullReset(true)}>{t('actions.resetParameter')}</button>
      ) : undefined}
      contentClassName="qc-admin-page qc-detail-page qc-parameter-page"
    >
      {notice && <div className="success-banner" role="status">{notice}</div>}
      <section className="card qc-parameter-context" aria-label={t('detail.policyContext')}>
        <label className="qc-field qc-unit-context-select">
          <span>{t('detail.effectiveUnit')}</span>
          <select
            value={selectedUnitCode ?? ''}
            onChange={(event) => {
              setSelectedUnitCode(event.target.value);
              setEditingCheck(null);
            }}
          >
            {!selectedUnitCode && <option value="">{t('states.unavailable')}</option>}
            {policy.parameter.supported_units.map((unit) => (
              <option key={unit.unit_code} value={unit.unit_code}>{unit.symbol}</option>
            ))}
          </select>
        </label>
        <div className="qc-parameter-policy">
          <strong>{t('detail.parameterScope')}</strong>
          <span>{t(policy.overrides.length ? 'detail.customPolicy' : 'detail.inheritedPolicy')}</span>
        </div>
        <nav className="qc-exception-shortcuts" aria-label={t('columns.exceptions')}>
          <a className="btn" href="#source-exceptions-title">{t('detail.dataSourceExceptions')} · {summary?.source_exception_count ?? t('states.unavailable')}</a>
          <Link className="btn" to={`/admin/qc/sensors?parameter_id=${parameterId}`}>{t('detail.sensorExceptions')} · {summary?.sensor_exception_count ?? t('states.unavailable')}</Link>
        </nav>
      </section>

      <section className="qc-check-section" aria-labelledby="qc-checks-title">
        <div className="qc-section-heading">
          <div>
            <h2 id="qc-checks-title">{t('detail.checksTitle')}</h2>
          </div>
        </div>
        <div className="qc-check-list">
          {checks.map((check) => (
            <QcCheckCard
              key={`${check.check_code}:${check.applicable_unit_code ?? 'unitless'}`}
              headingLevel={3}
              policy={policy}
              check={check}
              metadata={metadataByCode.get(check.check_code)}
              affectedSensorCount={summary?.sensor_count ?? 0}
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

      <section className="card qc-exceptions-section" aria-labelledby="source-exceptions-title">
        <div className="qc-section-heading">
          <div>
            <h2 id="source-exceptions-title" tabIndex={-1}>{t('exceptions.title')}</h2>
            <p>{t('exceptions.description', { parameter: policy.parameter.display_name })}</p>
          </div>
          <button className="btn" type="button" onClick={() => void openSourcePicker()}>{t('exceptions.add')}</button>
        </div>

        {sourceLoading && <div className="qc-inline-loading">{t('exceptions.loading')}</div>}
        {sourceError && <div className="warning-banner">{t('exceptions.partialError')}</div>}
        {!sourceLoading && sourceExceptions.length === 0 && !sourceError && (
          <div className="qc-quiet-empty">{t('exceptions.none')}</div>
        )}
        {sourceExceptions.length > 0 && (
          <div className="qc-exception-list">
            {sourceExceptions.map(({ source, policy: sourcePolicy }) => (
              <Link
                to={`/admin/qc/parameters/${parameterId}/sources/${source.external_api_id}`}
                className="qc-exception-row"
                key={source.external_api_id}
              >
                <div>
                  <strong>{source.name}</strong>
                  <span>{t('exceptions.customizedChecks', {
                    checks: sourcePolicy.overrides.map((override) => checkName(override.check_code, metadataByCode.get(override.check_code))).join(', '),
                  })}</span>
                </div>
                <span>{t('actions.edit')}</span>
              </Link>
            ))}
          </div>
        )}

        {showSourcePicker && (
          <div className="qc-source-picker">
            <label className="qc-field">
              <span>{t('exceptions.selectSource')}</span>
              <select value={selectedSourceId} onChange={(event) => setSelectedSourceId(event.target.value)}>
                <option value="">{t('exceptions.selectPlaceholder')}</option>
                {availableSources.map((source) => <option key={source.external_api_id} value={source.external_api_id}>{source.name}</option>)}
              </select>
            </label>
            <div className="qc-inline-actions">
              <button className="btn" type="button" onClick={() => { setShowSourcePicker(false); setSelectedSourceId(''); }}>{t('actions.cancel')}</button>
              <button
                className="btn btn-primary"
                type="button"
                disabled={!selectedSourceId}
                onClick={() => navigate(`/admin/qc/parameters/${parameterId}/sources/${selectedSourceId}`)}
              >
                {t('exceptions.continue')}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="card qc-sensor-awareness">
        <div>
          <h2>{t('sensorOverrides.title')}</h2>
          <p>{summary?.sensor_exception_count
            ? t('sensorOverrides.exists', { count: summary.sensor_exception_count })
            : t('sensorOverrides.none')}</p>
        </div>
        <div className="qc-sensor-awareness-actions">
          {summary?.sensor_exception_count ? <QcStatusBadge tone="custom">{t('sensorOverrides.badge')}</QcStatusBadge> : null}
          <Link className="btn" to={`/admin/qc/sensors?parameter_id=${parameterId}`}>{t('sensors.actions.findSensor')}</Link>
        </div>
      </section>

      <details className="card qc-unit-defaults qc-more-details">
        <summary>{t('detail.unitDefaultsTitle')}</summary>
        <div className="qc-section-heading">
          <div>
            <p>{t('detail.unitDefaultsDescription')}</p>
          </div>
        </div>
        <div className="qc-unit-default-grid">
          {policy.parameter.supported_units.map((unit) => {
            const summaries = unitSummaryChecks.map((checkMetadata) => ({
              metadata: checkMetadata,
              check: policy.checks.find((check) => (
                check.check_code === checkMetadata.check_code
                && check.applicable_unit_code === unit.unit_code
              )),
            }));
            const noDefault = summaries.every(({ check }) => !check || check.status === 'not_configured');
            return (
              <div className="qc-unit-default-card" key={unit.unit_code}>
                <strong>{unit.symbol}</strong>
                {noDefault ? (
                  <p>{t('noDefault.description', { parameter: policy.parameter.display_name, unit: unit.symbol })}</p>
                ) : (
                  <dl>
                    {summaries.map(({ metadata: checkMetadata, check }) => {
                      const summaryValue = check ? checkValue(check, checkMetadata) : null;
                      let displayValue = t('states.notConfigured');
                      if (!checkMetadata.available || check?.status === 'unavailable') displayValue = t('states.unavailable');
                      else if (check && !check.enabled) displayValue = t('states.off');
                      else if (summaryValue !== null && summaryValue !== undefined) {
                        displayValue = `${formatQcNumber(summaryValue)} ${unit.symbol}`;
                      }
                      return (
                        <div key={checkMetadata.check_code}>
                          <dt>{['min_value', 'max_value', 'baseline_drift'].includes(checkMetadata.check_code)
                            ? checkName(checkMetadata.check_code, checkMetadata) : checkMetadata.overview.label}</dt>
                          <dd>{displayValue}</dd>
                        </div>
                      );
                    })}
                  </dl>
                )}
              </div>
            );
          })}
        </div>
      </details>

      <details className="card qc-more-details">
        <summary>{t('detail.contextTitle')}</summary>
        <p>{t('detail.hierarchy')}</p>
        <p>{t('detail.unitLimitations')}</p>
        <dl>
          <div><dt>{t('detail.normalUnit')}</dt><dd>{unitSymbol(policy.parameter.default_unit) || t('states.unavailable')}</dd></div>
          <div><dt>{t('columns.sensors')}</dt><dd>{summary?.sensor_count ?? t('states.unavailable')}</dd></div>
          <div><dt>{t('detail.profileVersion')}</dt><dd>{policy.default_profile_version}</dd></div>
          <div><dt>{t('detail.advancedOverrides')}</dt><dd>{policy.advanced_aggregation_override_count}</dd></div>
        </dl>
        {policy.advanced_aggregation_override_count > 0 && <p>{t('detail.advancedHelp')}</p>}
      </details>

      <QcConfirmationDialog
        open={confirmFullReset}
        title={t('confirm.resetParameterTitle', { parameter: policy.parameter.display_name })}
        description={t('confirm.resetParameterDescription', { parameter: policy.parameter.display_name })}
        confirmLabel={t('actions.resetParameter')}
        busy={resetting}
        onCancel={() => setConfirmFullReset(false)}
        onConfirm={() => void resetAll()}
      />
    </AdminPageLayout>
  );
}
