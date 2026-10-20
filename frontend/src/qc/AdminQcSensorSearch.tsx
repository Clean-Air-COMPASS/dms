import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { listExternalAPIs, type ExternalAPI } from '../api';
import AdminPageLayout from '../components/AdminPageLayout';
import { listQcParameters, searchQcSensors } from './api';
import QcSensorSearchResult from './QcSensorSearchResult';
import type { QcParameter, QcSensorSearchResponse } from './types';

const PAGE_SIZE = 25;

function positiveInteger(value: string | null): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

export default function AdminQcSensorSearch() {
  const { t } = useTranslation('qualityControl');
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get('q') ?? '';
  const parameterId = positiveInteger(searchParams.get('parameter_id'));
  const externalApiId = positiveInteger(searchParams.get('external_api_id'));
  const showCustom = searchParams.get('show') === 'custom';
  const offset = Math.max(0, Number(searchParams.get('offset')) || 0);
  const hasActiveFilters = parameterId !== undefined || externalApiId !== undefined || showCustom;
  const [queryInput, setQueryInput] = useState(query);
  const [results, setResults] = useState<QcSensorSearchResponse | null>(null);
  const [parameters, setParameters] = useState<QcParameter[]>([]);
  const [sources, setSources] = useState<ExternalAPI[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [filterError, setFilterError] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(hasActiveFilters);
  const [retryNonce, setRetryNonce] = useState(0);
  const requestSequence = useRef(0);

  useEffect(() => {
    setQueryInput(query);
  }, [query]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (queryInput.trim() === query) return;
      const next = new URLSearchParams(searchParams);
      if (queryInput.trim()) next.set('q', queryInput.trim());
      else next.delete('q');
      next.delete('offset');
      setSearchParams(next, { replace: true });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, queryInput, searchParams, setSearchParams]);

  useEffect(() => {
    let cancelled = false;
    const loadFilters = async () => {
      setFilterError(false);
      try {
        const [parameterResponse, sourceResponse] = await Promise.all([
          listQcParameters(),
          listExternalAPIs({ skipCache: true }),
        ]);
        if (cancelled) return;
        setParameters(parameterResponse.items.map((item) => ({
          parameter_id: item.parameter_id,
          parameter_code: item.parameter_code,
          display_name: item.display_name,
          default_unit: item.default_unit,
          supported_units: item.supported_units,
        })));
        setSources(sourceResponse);
      } catch {
        if (!cancelled) setFilterError(true);
      }
    };
    void loadFilters();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    setLoading(true);
    setError(false);
    void searchQcSensors({
      query,
      parameterId,
      externalApiId,
      hasSensorSpecificQc: showCustom ? true : undefined,
      limit: PAGE_SIZE,
      offset,
    }).then((response) => {
      if (requestSequence.current === sequence) setResults(response);
    }).catch(() => {
      if (requestSequence.current === sequence) setError(true);
    }).finally(() => {
      if (requestSequence.current === sequence) setLoading(false);
    });
  }, [externalApiId, offset, parameterId, query, retryNonce, showCustom]);

  const sortedParameters = useMemo(
    () => [...parameters].sort((left, right) => left.display_name.localeCompare(right.display_name)),
    [parameters],
  );
  const sortedSources = useMemo(
    () => [...sources].sort((left, right) => left.name.localeCompare(right.name)),
    [sources],
  );

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete('offset');
    setSearchParams(next);
  };

  const clearFilters = () => {
    setQueryInput('');
    setSearchParams(new URLSearchParams());
  };

  const movePage = (nextOffset: number) => {
    const next = new URLSearchParams(searchParams);
    if (nextOffset > 0) next.set('offset', String(nextOffset));
    else next.delete('offset');
    setSearchParams(next);
  };

  const firstShown = results && results.total > 0 ? results.offset + 1 : 0;
  const lastShown = results ? Math.min(results.offset + results.items.length, results.total) : 0;
  const noCriteria = !query && !hasActiveFilters;

  return (
    <AdminPageLayout
      title={t('sensors.search.title')}
      description={t('sensors.search.description')}
      breadcrumbs={[
        { label: t('breadcrumbs.admin'), to: '/admin' },
        { label: t('breadcrumbs.qualityControl'), to: '/admin/qc' },
        { label: t('sensors.breadcrumb') },
      ]}
      contentClassName="qc-admin-page qc-sensor-search-page"
    >
      <section className="card qc-sensor-search-controls" aria-labelledby="qc-sensor-search-label">
        <label className="qc-field qc-search-field">
          <span id="qc-sensor-search-label">{t('sensors.search.searchLabel')}</span>
          <input
            type="search"
            value={queryInput}
            onChange={(event) => setQueryInput(event.target.value)}
            placeholder={t('sensors.search.searchPlaceholder')}
          />
        </label>
        <details open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)}>
          <summary>{t('sensors.search.filters')}</summary>
          <div className="qc-sensor-filter-grid">
            <label className="qc-field">
              <span>{t('sensors.search.parameterFilter')}</span>
              <select value={parameterId ?? ''} onChange={(event) => setFilter('parameter_id', event.target.value)}>
                <option value="">{t('sensors.search.allParameters')}</option>
                {sortedParameters.map((parameter) => (
                  <option key={parameter.parameter_id} value={parameter.parameter_id}>{parameter.display_name}</option>
                ))}
              </select>
            </label>
            <label className="qc-field">
              <span>{t('sensors.search.sourceFilter')}</span>
              <select value={externalApiId ?? ''} onChange={(event) => setFilter('external_api_id', event.target.value)}>
                <option value="">{t('sensors.search.allSources')}</option>
                {sortedSources.map((source) => (
                  <option key={source.external_api_id} value={source.external_api_id}>{source.name}</option>
                ))}
              </select>
            </label>
            <label className="qc-field">
              <span>{t('sensors.search.statusFilter')}</span>
              <select value={showCustom ? 'custom' : 'all'} onChange={(event) => setFilter('show', event.target.value === 'custom' ? 'custom' : '')}>
                <option value="all">{t('sensors.search.allSensors')}</option>
                <option value="custom">{t('sensors.search.customSensors')}</option>
              </select>
            </label>
          </div>
        </details>
      </section>

      {filterError && <div className="warning-banner">{t('sensors.search.filterLoadError')}</div>}
      {loading && <div className="info-banner" role="status">{t('sensors.search.loading')}</div>}
      {error && (
        <div className="error-banner qc-state-banner" role="alert">
          <span>{t('sensors.search.loadError')}</span>
          <button type="button" className="btn" onClick={() => setRetryNonce((current) => current + 1)}>{t('actions.retry')}</button>
        </div>
      )}

      {!loading && !error && results && results.total === 0 && (
        <section className="card qc-empty-state">
          <h2>{t(noCriteria ? 'sensors.search.emptyTitle' : 'sensors.search.noMatchesTitle')}</h2>
          <p>{t(noCriteria ? 'sensors.search.emptyDescription' : 'sensors.search.noMatchesDescription')}</p>
          {!noCriteria && <button type="button" className="btn" onClick={clearFilters}>{t('overview.clearFilters')}</button>}
        </section>
      )}

      {!loading && !error && results && results.items.length > 0 && (
        <section className="qc-sensor-results" aria-label={t('sensors.search.resultsLabel')} aria-busy={loading}>
          <div className="qc-sensor-results-heading" role="status" aria-live="polite">
            <strong>{t('sensors.search.resultRange', { first: firstShown, last: lastShown, total: results.total })}</strong>
          </div>
          <div className="card qc-sensor-result-list">
            {results.items.map((sensor) => <QcSensorSearchResult key={sensor.sensor_id} sensor={sensor} />)}
          </div>
          <div className="qc-sensor-pagination">
            <button type="button" className="btn" disabled={offset === 0} onClick={() => movePage(Math.max(0, offset - PAGE_SIZE))}>
              {t('sensors.search.previous')}
            </button>
            <button type="button" className="btn" disabled={offset + PAGE_SIZE >= results.total} onClick={() => movePage(offset + PAGE_SIZE)}>
              {t('sensors.search.next')}
            </button>
          </div>
        </section>
      )}
    </AdminPageLayout>
  );
}
