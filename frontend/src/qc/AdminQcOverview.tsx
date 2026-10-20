import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import AdminPageLayout from '../components/AdminPageLayout';
import { listQcChecks, listQcParameters } from './api';
import { formatQcNumber, isUnitScopedCheck, rangeConfigurationState, unitSymbol } from './presentation';
import QcStatusBadge from './QcStatusBadge';
import type { QcCheckMetadata, QcParameterSummary, QcResolvedCheck } from './types';

type StatusFilter = 'all' | 'custom' | 'exceptions' | 'attention' | 'unavailable' | 'no_recommendation';

function findCheck(parameter: QcParameterSummary, metadata: QcCheckMetadata): QcResolvedCheck | undefined {
  return parameter.checks.find((check) => (
    check.check_code === metadata.check_code
    && (!isUnitScopedCheck(metadata) || check.applicable_unit_code === parameter.default_unit?.unit_code)
  ));
}

function checkIsUnavailable(check: QcResolvedCheck | undefined, metadata?: QcCheckMetadata): boolean {
  if (!check) return false;
  return metadata?.available === false || (check.status === 'unavailable' && check.enabled);
}

function parameterNeedsConfiguration(
  parameter: QcParameterSummary,
  metadata: QcCheckMetadata[],
): boolean {
  // Missing CompassAQ defaults are expected for unsupported parameters. They
  // are not incomplete supported policies and must not be presented as such.
  if (!parameter.supported) return false;
  return metadata.some((checkMetadata) => {
    const settingCode = checkMetadata.overview.summary_setting;
    const check = findCheck(parameter, checkMetadata);
    return Boolean(
      settingCode
      && check
      && check.status === 'unavailable'
      && check.configured_settings[settingCode] === undefined,
    );
  });
}

function parameterHasUnavailableCheck(
  parameter: QcParameterSummary,
  metadataByCode: Map<string, QcCheckMetadata>,
): boolean {
  return parameter.checks.some((check) => checkIsUnavailable(check, metadataByCode.get(check.check_code)));
}

function parameterNeedsAttention(
  parameter: QcParameterSummary,
  metadataByCode: Map<string, QcCheckMetadata>,
  metadata: QcCheckMetadata[],
): boolean {
  return parameterNeedsConfiguration(parameter, metadata)
    || parameterHasUnavailableCheck(parameter, metadataByCode);
}

function CheckSummary({
  parameter,
  metadata,
}: {
  parameter: QcParameterSummary;
  metadata: QcCheckMetadata;
}) {
  const { t } = useTranslation('qualityControl');
  const check = findCheck(parameter, metadata);
  if (!check) return <span className="qc-summary-muted">{t('states.notConfigured')}</span>;
  if (checkIsUnavailable(check, metadata)) {
    return <span className="qc-summary-unavailable">{t('states.unavailable')}</span>;
  }
  if (check.status === 'not_configured') {
    return <span className="qc-summary-muted">{t('states.notConfigured')}</span>;
  }
  if (!check.enabled) {
    return <span className="qc-summary-muted">{t('states.off')}</span>;
  }
  const summarySetting = metadata.overview.summary_setting;
  if (!summarySetting) return <span>{t('states.on')}</span>;
  const summaryValue = check.configured_settings[summarySetting]
    ?? check.evaluation_settings[summarySetting];
  if (summaryValue === undefined || summaryValue === null) {
    return <span className="qc-summary-muted">{t('states.notConfigured')}</span>;
  }
  const displayedValue = typeof summaryValue === 'number'
    ? formatQcNumber(summaryValue)
    : String(summaryValue);
  const displayedUnit = metadata.unit_settings.includes(summarySetting)
    ? unitSymbol(parameter.default_unit, check.configured_unit_code)
    : '';
  return (
    <strong>
      {displayedValue}{displayedUnit && ' '}
      {displayedUnit && <span className="qc-unit">{displayedUnit}</span>}
    </strong>
  );
}

function BaselineDriftSummary({
  parameter,
  metadata,
}: {
  parameter: QcParameterSummary;
  metadata?: QcCheckMetadata;
}) {
  const { t } = useTranslation('qualityControl');
  if (!metadata) return <span className="qc-summary-muted">{t('states.notConfigured')}</span>;
  const check = findCheck(parameter, metadata);
  if (!check) return <span className="qc-summary-muted">{t('states.notConfigured')}</span>;
  if (checkIsUnavailable(check, metadata)) {
    return <span className="qc-summary-unavailable">{t('states.unavailable')}</span>;
  }

  const enabledSourceCount = parameter.baseline_drift_enabled_source_count;
  const enabledSensorCount = parameter.baseline_drift_enabled_sensor_count;
  if (!check.enabled && enabledSourceCount === 0 && enabledSensorCount === 0) {
    return <span className="qc-summary-muted">{t('states.off')}</span>;
  }
  if (!check.enabled) {
    return (
      <span className="qc-drift-summary">
        <span className="qc-summary-muted">{t('overview.driftOffByDefault')}</span>
        {enabledSourceCount > 0 && (
          <span>{t('overview.driftEnabledSourceCount', { count: enabledSourceCount })}</span>
        )}
        {enabledSensorCount > 0 && (
          <span>{t('overview.driftEnabledSensorCount', { count: enabledSensorCount })}</span>
        )}
      </span>
    );
  }

  const overrideCount = parameter.baseline_drift_source_override_count
    + parameter.baseline_drift_sensor_override_count;
  if (overrideCount === 0) return <span>{t('states.on')}</span>;
  return <span>{t('overview.driftOnWithOverrides', { count: overrideCount })}</span>;
}

export default function AdminQcOverview() {
  const { t } = useTranslation('qualityControl');
  const [parameters, setParameters] = useState<QcParameterSummary[]>([]);
  const [checks, setChecks] = useState<QcCheckMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  const load = async () => {
    setLoading(true);
    setError(false);
    try {
      const [parameterResponse, checkResponse] = await Promise.all([
        listQcParameters(),
        listQcChecks(),
      ]);
      setParameters(parameterResponse.items);
      setChecks(checkResponse);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const metadataByCode = useMemo(
    () => new Map(checks.map((check) => [check.check_code, check])),
    [checks],
  );
  const overviewChecks = useMemo(
    () => checks
      .filter((check) => check.overview.visible)
      .sort((left, right) => left.overview.order - right.overview.order
        || left.check_code.localeCompare(right.check_code)),
    [checks],
  );
  const overviewGridStyle = {
    '--qc-overview-check-count': overviewChecks.length,
  } as CSSProperties;

  const attentionCount = useMemo(
    () => parameters.filter((parameter) => parameterNeedsAttention(
      parameter,
      metadataByCode,
      overviewChecks,
    )).length,
    [metadataByCode, overviewChecks, parameters],
  );

  const visibleParameters = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase();
    return parameters.filter((parameter) => {
      if (normalizedSearch && !`${parameter.display_name} ${parameter.parameter_code}`.toLocaleLowerCase().includes(normalizedSearch)) {
        return false;
      }
      const hasExceptions = parameter.source_exception_count + parameter.sensor_exception_count > 0;
      const hasUnavailable = parameterHasUnavailableCheck(parameter, metadataByCode);
      if (statusFilter === 'custom') return parameter.parameter_override_count > 0;
      if (statusFilter === 'exceptions') return hasExceptions;
      if (statusFilter === 'attention') return parameterNeedsAttention(
        parameter,
        metadataByCode,
        overviewChecks,
      );
      if (statusFilter === 'unavailable') return hasUnavailable;
      if (statusFilter === 'no_recommendation') return !parameter.supported
        || rangeConfigurationState(parameter) === 'noRecommendedRange';
      return true;
    });
  }, [metadataByCode, overviewChecks, parameters, search, statusFilter]);

  return (
    <AdminPageLayout
      title={t('overview.title')}
      description={t('overview.description')}
      breadcrumbs={[
        { label: t('breadcrumbs.admin'), to: '/admin' },
        { label: t('breadcrumbs.qualityControl') },
      ]}
      actions={(
        <div className="qc-header-actions">
          <Link className="btn btn-primary" to="/admin/qc/sensors">{t('sensors.actions.findSensor')}</Link>
          <Link className="btn" to="/admin/qc/extensions">{t('extensions.link')}</Link>
          <Link className="btn" to="/admin/events?tab=qc-failures">{t('overview.reviewResults')}</Link>
        </div>
      )}
      contentClassName="qc-admin-page qc-overview-page"
    >
      <p className="mb-4 text-sm text-slate-600">{t('overview.resultsHelp')}</p>
      {!loading && !error && attentionCount > 0 && (
        <button
          type="button"
          className="warning-banner qc-attention-banner"
          onClick={() => {
            setSearch('');
            setStatusFilter('attention');
          }}
        >
          <span>{t('overview.attention', { count: attentionCount })}</span>
          <span className="qc-banner-action">{t('overview.viewAttention')}</span>
        </button>
      )}

      <div className="card qc-filter-card">
        <label className="qc-field qc-search-field">
          <span>{t('overview.searchLabel')}</span>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('overview.searchPlaceholder')}
          />
        </label>
        <label className="qc-field">
          <span>{t('overview.filterLabel')}</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
            <option value="all">{t('filters.all')}</option>
            <option value="custom">{t('filters.customized')}</option>
            <option value="exceptions">{t('filters.hasExceptions')}</option>
            <option value="attention">{t('filters.needsAttention')}</option>
            <option value="unavailable">{t('filters.unavailable')}</option>
            <option value="no_recommendation">{t('filters.noRecommendation')}</option>
          </select>
        </label>
      </div>

      {loading && <div className="info-banner">{t('overview.loading')}</div>}
      {error && (
        <div className="error-banner qc-state-banner">
          <span>{t('overview.loadError')}</span>
          <button className="btn" type="button" onClick={() => void load()}>{t('actions.retry')}</button>
        </div>
      )}
      {!loading && !error && parameters.length === 0 && (
        <div className="card qc-empty-state">
          <h2>{t('overview.emptyTitle')}</h2>
          <p>{t('overview.emptyDescription')}</p>
        </div>
      )}
      {!loading && !error && parameters.length > 0 && visibleParameters.length === 0 && (
        <div className="card qc-empty-state">
          <h2>{t('overview.noMatchesTitle')}</h2>
          <p>{t('overview.noMatchesDescription')}</p>
          <button className="btn" type="button" onClick={() => { setSearch(''); setStatusFilter('all'); }}>
            {t('overview.clearFilters')}
          </button>
        </div>
      )}

      {!loading && !error && visibleParameters.length > 0 && (
        <section
          className="card qc-parameter-list"
          aria-label={t('overview.parameterListLabel')}
          style={overviewGridStyle}
        >
          <div className="qc-parameter-list-header" aria-hidden="true">
            <span>{t('columns.parameter')}</span>
            {overviewChecks.map((check) => (
              <span key={check.check_code}>{check.overview.label}</span>
            ))}
            <span>{t('columns.sensors')}</span>
            <span>{t('columns.exceptions')}</span>
            <span>{t('columns.status')}</span>
          </div>
          {visibleParameters.map((parameter) => {
            const hasUnavailable = parameterHasUnavailableCheck(parameter, metadataByCode);
            const needsConfiguration = parameterNeedsConfiguration(parameter, overviewChecks);
            const customized = parameter.parameter_override_count > 0;
            const rangeState = rangeConfigurationState(parameter);
            return (
              <Link
                className="qc-parameter-row"
                to={`/admin/qc/parameters/${parameter.parameter_id}`}
                state={{ parameterName: parameter.display_name }}
                key={parameter.parameter_id}
                aria-label={t('overview.openParameter', { parameter: parameter.display_name })}
              >
                <div className="qc-parameter-name">
                  <strong>{parameter.display_name}</strong>
                  <span>{unitSymbol(parameter.default_unit)}</span>
                </div>
                {overviewChecks.map((checkMetadata) => (
                  <div data-label={checkMetadata.overview.label} key={checkMetadata.check_code}>
                    {checkMetadata.check_code === 'baseline_drift'
                      ? <BaselineDriftSummary parameter={parameter} metadata={checkMetadata} />
                      : <CheckSummary parameter={parameter} metadata={checkMetadata} />}
                  </div>
                ))}
                <div data-label={t('columns.sensors')}>{parameter.sensor_count}</div>
                <div data-label={t('columns.exceptions')} className="qc-exception-counts">
                  {parameter.source_exception_count + parameter.sensor_exception_count === 0
                    ? t('overview.none')
                    : `${t('overview.sourceExceptionCount', { count: parameter.source_exception_count })} · ${t('overview.sensorExceptionCount', { count: parameter.sensor_exception_count })}`}
                </div>
                <div data-label={t('columns.status')} className="qc-row-statuses">
                  {hasUnavailable && <QcStatusBadge tone="unavailable">{t('states.unavailable')}</QcStatusBadge>}
                  {needsConfiguration && <QcStatusBadge tone="attention">{t('states.needsConfiguration')}</QcStatusBadge>}
                  {customized && <QcStatusBadge tone="custom">{t('states.custom')}</QcStatusBadge>}
                  {!hasUnavailable && !needsConfiguration && !customized && parameter.supported && (
                    <>
                      <QcStatusBadge tone="neutral">{t('states.defaultConfiguration')}</QcStatusBadge>
                      {rangeState !== 'defaultConfiguration' && (
                        <QcStatusBadge tone="neutral">{t(`states.${rangeState}`)}</QcStatusBadge>
                      )}
                    </>
                  )}
                  {!parameter.supported && !customized && (
                    <QcStatusBadge tone="neutral">{t('states.noRecommendation')}</QcStatusBadge>
                  )}
                </div>
              </Link>
            );
          })}
        </section>
      )}
    </AdminPageLayout>
  );
}
