import { formatOperationalTimestamp } from './utils/timezone';
import { Trans, useTranslation } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useState, useCallback, useRef } from 'react';
import { listQCFailures } from './api';
import { listJobHistory, listEventHistory, HISTORY_PAGE_SIZE, initialHistoryWindow, historyDates, type HistoryFilters } from './eventsHistory';
import EventHistoryControls from './EventHistoryControls';
import type {
  EventRecord,
  JobRunRecord,
  QCFailureListResponse,
  QCFailureOutcome,
  QCFailureRecord,
  QCFailureStatus,
} from './api';
import AdminPageLayout from './components/AdminPageLayout';
import { formatJobRunEventSummary, formatJobRunStatus } from './jobRunPresentation';
import { useSearchParams } from 'react-router-dom';
import { checkName, failureActionLabel, formatQcNumber } from './qc/presentation';

type TabType = 'job-runs' | 'events' | 'qc-failures';

const QC_FAILURE_PAGE_SIZE = 25;

const INDETERMINATE_REASON_KEYS: Record<string, string> = {
  conversion_not_supported: 'conversionNotSupported',
  invalid_measurement_value: 'invalidMeasurementValue',
  invalid_plugin_result: 'invalidPluginResult',
  missing_effective_policy: 'missingEffectivePolicy',
  missing_required_setting: 'missingRequiredSetting',
  insufficient_history: 'insufficientHistory',
  plugin_error: 'pluginError',
  plugin_result_missing: 'pluginResultMissing',
  plugin_unavailable: 'pluginUnavailable',
};

function ruleSourceLabel(ruleSource: string | null): string {
  const knownSourceKeys: Record<string, string> = {
    compassaq_default: 'compassAQDefault',
    parameter_override: 'parameterOverride',
    parameter_aggregate_override: 'parameterAggregateOverride',
    source_override: 'sourceOverride',
    source_aggregate_override: 'sourceAggregateOverride',
    sensor_override: 'sensorOverride',
    sensor_aggregate_override: 'sensorAggregateOverride',
  };
  const key = ruleSource ? knownSourceKeys[ruleSource] : null;
  return key
    ? i18n.t(`events:adminEventLog.qcFailures.ruleSources.${key}` as never)
    : ruleSource || i18n.t('events:adminEventLog.text.notAvailable');
}

function policyVersion(qcFailure: QCFailureRecord): string {
  const version = qcFailure.policy_snapshot?.default_profile_version;
  return typeof version === 'string'
    ? version
    : i18n.t('events:adminEventLog.text.notAvailable');
}

function policySnapshotValue(qcFailure: QCFailureRecord, key: string): string {
  const value = qcFailure.policy_snapshot?.[key];
  return typeof value === 'string'
    ? value
    : i18n.t('events:adminEventLog.text.notAvailable');
}

function numericSnapshotValue(
  snapshot: Record<string, unknown> | null,
  key: string,
): string {
  const value = snapshot?.[key];
  return typeof value === 'number' && Number.isFinite(value)
    ? formatQcNumber(value)
    : i18n.t('events:adminEventLog.text.notAvailable');
}

function textSnapshotValue(
  snapshot: Record<string, unknown> | null,
  key: string,
): string {
  const value = snapshot?.[key];
  return typeof value === 'string'
    ? i18n.t(`qualityControl:choices.${value}`, { defaultValue: value })
    : i18n.t('events:adminEventLog.text.notAvailable');
}

function qcFailureStatusLabel(qcFailure: QCFailureRecord): string {
  if (qcFailure.evaluation_status === 'indeterminate') {
    return i18n.t('events:adminEventLog.qcFailures.status.unableToEvaluate');
  }
  const action = qcFailure.failure_action === 'mark_invalid'
    ? i18n.t('events:adminEventLog.qcFailures.status.markedInvalid')
    : qcFailure.failure_action
      ? failureActionLabel(qcFailure.failure_action)
      : i18n.t('events:adminEventLog.text.notAvailable');
  return `${i18n.t('events:adminEventLog.qcFailures.status.failed')} — ${action}`;
}

function qcFailureExplanation(qcFailure: QCFailureRecord): string {
  if (qcFailure.evaluation_status !== 'indeterminate') {
    return qcFailure.message
      || qcFailure.reason_code
      || i18n.t('events:adminEventLog.text.notAvailable');
  }

  const reasonKey = qcFailure.reason_code
    ? INDETERMINATE_REASON_KEYS[qcFailure.reason_code]
    : undefined;
  if (reasonKey) {
    return i18n.t(
      `events:adminEventLog.qcFailures.indeterminateReasons.${reasonKey}` as never,
    );
  }
  return qcFailure.message
    || qcFailure.reason_code
    || i18n.t('events:adminEventLog.qcFailures.indeterminateFallback');
}

function formatDuration(start: string, end: string | null): string {
  if (!end) return i18n.t('events:adminEventLog.text.running');
  const startDate = new Date(start);
  const endDate = new Date(end);
  const diffMs = endDate.getTime() - startDate.getTime();
  if (diffMs < 1000) return `${diffMs}ms`;
  if (diffMs < 60000) return `${(diffMs / 1000).toFixed(1)}s`;
  return `${(diffMs / 60000).toFixed(1)}m`;
}

function StatusBadge({ status, language }: { status: string; language?: string }) {
  const getStatusClass = (s: string) => {
    switch (s.toLowerCase()) {
      case 'success': return 'status-badge status-success';
      case 'failed': case 'failure': return 'status-badge status-error';
      case 'running': return 'status-badge status-running';
      case 'skipped': return 'status-badge status-skipped';
      case 'interrupted': return 'status-badge status-interrupted';
      default: return 'status-badge status-unknown';
    }
  };
  return <span className={getStatusClass(status)}>{formatJobRunStatus(status, language)}</span>;
}

function SeverityBadge({ severity }: { severity: string }) {
  const getSeverityClass = (s: string) => {
    switch (s.toLowerCase()) {
      case 'info': return 'severity-badge severity-info';
      case 'warning': case 'warn': return 'severity-badge severity-warning';
      case 'error': return 'severity-badge severity-error';
      default: return 'severity-badge severity-info';
    }
  };
  return <span className={getSeverityClass(severity)}>{i18n.t(`events:history.severity.${severity}`, { defaultValue: severity })}</span>;
}

function codeLabel(group: string, code: string): string {
  return i18n.t(`events:history.labels.${group}.${code.replaceAll('.', '_')}`, {
    defaultValue: i18n.t('events:history.unknown'),
  });
}

function codeDetails(code: string) {
  return <details className="history-code"><summary>{i18n.t('events:history.technicalCode')}</summary><code>{code}</code></details>;
}

function JobRunRows({ runs, language }: { runs: JobRunRecord[]; language?: string }) {
  return (
    <>
      {runs.map(run => (
        <tr key={run.job_run_id} className={run.status === 'failed' || run.status === 'interrupted' ? 'row-error' : ''}>
          <td data-label={i18n.t('events:adminEventLog.columns.id')} className="cell-id">{run.job_run_id}</td>
          <td data-label={i18n.t('events:adminEventLog.columns.task')} className="cell-task">{codeLabel('task', run.task)}{codeDetails(run.task)}</td>
          <td data-label={i18n.t('common:fields.status')}><StatusBadge status={run.status} language={language} /></td>
          <td data-label={i18n.t('events:adminEventLog.columns.started')} className="cell-time">
            {run.started_at ? formatOperationalTimestamp(run.started_at) : '—'}
          </td>
          <td data-label={i18n.t('events:adminEventLog.columns.duration')} className="cell-duration">
            {run.started_at ? formatDuration(run.started_at, run.finished_at ?? null) : '—'}
          </td>
          <td data-label={i18n.t('events:adminEventLog.columns.summary')} className="cell-summary" title={formatJobRunEventSummary(run.summary)}>
            {formatJobRunEventSummary(run.summary)}
          </td>
          <td data-label={i18n.t('events:adminEventLog.columns.error')} className="cell-error" title={run.error_message || ''}>
            {run.error_message || '—'}
          </td>
        </tr>
      ))}
    </>
  );
}

function EventRows({ items }: { items: EventRecord[] }) {
  return (
    <>
      {items.map(ev => (
        <tr key={ev.event_id} className={ev.severity === 'error' ? 'row-error' : ev.severity === 'warning' ? 'row-warning' : ''}>
          <td data-label={i18n.t('events:adminEventLog.columns.time')} className="cell-time">
            {ev.created_at ? formatOperationalTimestamp(ev.created_at) : '—'}
          </td>
          <td data-label={i18n.t('events:adminEventLog.columns.severity')}><SeverityBadge severity={ev.severity || 'info'} /></td>
          <td data-label={i18n.t('events:adminEventLog.columns.type')} className="cell-type">{codeLabel('event', ev.event_type)}{codeDetails(ev.event_type)}</td>
          <td data-label={i18n.t('events:adminEventLog.columns.source')} className="cell-source">{ev.event_type === 'csv.upload' ? i18n.t('events:csvUpload.source') : ev.source}</td>
          <td data-label={i18n.t('events:adminEventLog.columns.actor')} className="cell-message" title={ev.actor_email || ev.actor_user_id || ''}>
            <span>{ev.actor_display_name || ev.actor_email || ev.actor_user_id || '—'}</span>
            {ev.actor_display_name && ev.actor_email && ev.actor_display_name !== ev.actor_email && <small className="block muted">{ev.actor_email}</small>}
          </td>
          <td data-label={i18n.t('events:adminEventLog.columns.message')} className="cell-message">
            {ev.event_type === 'csv.upload' && ev.params ? <>
              <p>{i18n.t(`events:csvUpload.outcomes.${String(ev.params.outcome)}`, { defaultValue: i18n.t('events:csvUpload.outcomes.failed') })}</p>
              <p>{i18n.t('events:csvUpload.counts', ev.params)}</p>
              {typeof ev.params.completed_at === 'string' && <p className="muted">{i18n.t('events:csvUpload.completed', { time: formatOperationalTimestamp(ev.params.completed_at) })}</p>}
              {typeof ev.params.error_code === 'string' && codeDetails(ev.params.error_code)}
            </> : ev.message || '—'}
          </td>
          <td data-label={i18n.t('events:adminEventLog.columns.device')} className="cell-id">{ev.device_id ?? '—'}</td>
          <td data-label={i18n.t('events:adminEventLog.columns.sensor')} className="cell-id">{ev.sensor_id ?? '—'}</td>
        </tr>
      ))}
    </>
  );
}

function QcFailureDetails({ qcFailure }: { qcFailure: QCFailureRecord }) {
  return (
    <details className="qc-failure-provenance">
      <summary><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.show" /></summary>
      <dl>
        <div>
          <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.policySource" /></dt>
          <dd>{ruleSourceLabel(qcFailure.rule_source)}</dd>
        </div>
        <div>
          <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.reasonCode" /></dt>
          <dd>{qcFailure.reason_code || i18n.t('events:adminEventLog.text.notAvailable')}</dd>
        </div>
        <div>
          <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.policyStatus" /></dt>
          <dd>{policySnapshotValue(qcFailure, 'status')}</dd>
        </div>
        <div>
          <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.persistedMessage" /></dt>
          <dd>{qcFailure.message || i18n.t('events:adminEventLog.text.notAvailable')}</dd>
        </div>
        <div>
          <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.pluginVersion" /></dt>
          <dd>{qcFailure.plugin_version || i18n.t('events:adminEventLog.text.notAvailable')}</dd>
        </div>
        <div>
          <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.policyVersion" /></dt>
          <dd>{policyVersion(qcFailure)}</dd>
        </div>
        <div>
          <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.measurementId" /></dt>
          <dd>{qcFailure.measurement_id}</dd>
        </div>
        {qcFailure.check_code === 'baseline_drift' && (
          <>
            <div>
              <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.observedDrift" /></dt>
              <dd>{i18n.t('events:adminEventLog.qcFailures.provenance.perDayValue', {
                value: numericSnapshotValue(qcFailure.details, 'drift_per_day'),
                unit: qcFailure.unit_symbol || qcFailure.unit_code || '',
              })}</dd>
            </div>
            <div>
              <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.maximumDrift" /></dt>
              <dd>{i18n.t('events:adminEventLog.qcFailures.provenance.perDayValue', {
                value: numericSnapshotValue(qcFailure.params_snapshot, 'max_drift_per_day'),
                unit: qcFailure.unit_symbol || qcFailure.unit_code || '',
              })}</dd>
            </div>
            <div>
              <dt><Trans ns="events" i18nKey="adminEventLog.qcFailures.provenance.direction" /></dt>
              <dd>{textSnapshotValue(qcFailure.params_snapshot, 'direction')}</dd>
            </div>
          </>
        )}
      </dl>
    </details>
  );
}

export default function AdminEventLog() {
  const { i18n: activeI18n } = useTranslation();
  const [searchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<TabType>(
    requestedTab === 'events' || requestedTab === 'qc-failures'
      ? requestedTab
      : 'job-runs',
  );

  
  const [jobWindow, setJobWindow] = useState(initialHistoryWindow);
  const [eventWindow, setEventWindow] = useState(initialHistoryWindow);
  const [jobTotal, setJobTotal] = useState(0);
  const [eventTotal, setEventTotal] = useState(0);
  const [jobOptions, setJobOptions] = useState<Record<string, string[]>>({});
  const [eventOptions, setEventOptions] = useState<Record<string, string[]>>({});
  const jobRequest = useRef(0);
  const eventRequest = useRef(0);
  const qcRequest = useRef(0);
  const [jobRuns, setJobRuns] = useState<JobRunRecord[]>([]);
  const [jobRunsLoading, setJobRunsLoading] = useState(true);
  const [jobRunsError, setJobRunsError] = useState<string | null>(null);
  const [jobRunStatusFilter, setJobRunStatusFilter] = useState<string>('');
  const [jobRunTaskFilter, setJobRunTaskFilter] = useState<string>(searchParams.get('task') || '');

  
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('');
  const [eventSourceFilter, setEventSourceFilter] = useState<string>('');
  const [eventSeverityFilter, setEventSeverityFilter] = useState<string>('');

  const [qcFailures, setQcFailures] = useState<QCFailureListResponse>({
    items: [],
    total: 0,
    limit: QC_FAILURE_PAGE_SIZE,
    offset: 0,
  });
  const [qcFailuresLoading, setQcFailuresLoading] = useState(false);
  const [qcFailuresError, setQcFailuresError] = useState<string | null>(null);
  const [qcFailureSearch, setQcFailureSearch] = useState('');
  const [qcFailureParameter, setQcFailureParameter] = useState('');
  const [qcFailureStatus, setQcFailureStatus] = useState<QCFailureStatus | ''>('');
  const [qcFailureOutcome, setQcFailureOutcome] = useState<QCFailureOutcome | ''>('');
  const [qcFailureDataSource, setQcFailureDataSource] = useState('');
  const [qcFailureOffset, setQcFailureOffset] = useState(0);

  
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshInterval, setRefreshInterval] = useState(45);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  
  const fetchJobRuns = useCallback(async () => {
    const request = ++jobRequest.current;
    setJobRunsLoading(true);
    setJobRunsError(null);
    try {
      const filters: HistoryFilters = { limit: HISTORY_PAGE_SIZE, offset: jobWindow.offset, ...historyDates(jobWindow) };
      if (jobRunStatusFilter) filters.status = jobRunStatusFilter;
      if (jobRunTaskFilter) filters.task = jobRunTaskFilter;
      const data = await listJobHistory(filters);
      if (request !== jobRequest.current) return;
      if (jobWindow.offset > 0 && jobWindow.offset >= data.total) {
        setJobWindow(value => ({ ...value, offset: 0 }));
        return;
      }
      setJobRuns(data.items);
      setJobTotal(data.total);
      setJobOptions(data.options);
      setLastRefresh(new Date());
    } catch (err: unknown) {
      if (request !== jobRequest.current) return;
      const message = err instanceof Error ? err.message : String(err);
      setJobRunsError(message);
    } finally {
      if (request === jobRequest.current) setJobRunsLoading(false);
    }
  }, [jobRunStatusFilter, jobRunTaskFilter, jobWindow]);

  
  const fetchEvents = useCallback(async () => {
    const request = ++eventRequest.current;
    setEventsLoading(true);
    setEventsError(null);
    try {
      const filters: HistoryFilters = { limit: HISTORY_PAGE_SIZE, offset: eventWindow.offset, ...historyDates(eventWindow) };
      if (eventTypeFilter) filters.event_type = eventTypeFilter;
      if (eventSourceFilter) filters.source = eventSourceFilter;
      if (eventSeverityFilter) filters.severity = eventSeverityFilter;
      const data = await listEventHistory(filters);
      if (request !== eventRequest.current) return;
      if (eventWindow.offset > 0 && eventWindow.offset >= data.total) {
        setEventWindow(value => ({ ...value, offset: 0 }));
        return;
      }
      setEvents(data.items);
      setEventTotal(data.total);
      setEventOptions(data.options);
      setLastRefresh(new Date());
    } catch (err: unknown) {
      if (request !== eventRequest.current) return;
      const message = err instanceof Error ? err.message : String(err);
      setEventsError(message);
    } finally {
      if (request === eventRequest.current) setEventsLoading(false);
    }
  }, [eventTypeFilter, eventSourceFilter, eventSeverityFilter, eventWindow]);

  const fetchQCFailures = useCallback(async () => {
    const request = ++qcRequest.current;
    setQcFailuresLoading(true);
    setQcFailuresError(null);
    try {
      const data = await listQCFailures({
        limit: QC_FAILURE_PAGE_SIZE,
        offset: qcFailureOffset,
        search: qcFailureSearch.trim() || undefined,
        parameter: qcFailureParameter.trim() || undefined,
        status: qcFailureStatus || undefined,
        outcome: qcFailureOutcome || undefined,
        data_source: qcFailureDataSource.trim() || undefined,
      });
      if (request !== qcRequest.current) return;
      setQcFailures(data);
      setLastRefresh(new Date());
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      if (request !== qcRequest.current) return;
      setQcFailuresError(message);
    } finally {
      if (request === qcRequest.current) setQcFailuresLoading(false);
    }
  }, [
    qcFailureDataSource,
    qcFailureOffset,
    qcFailureOutcome,
    qcFailureParameter,
    qcFailureSearch,
    qcFailureStatus,
  ]);

  
  const fetchData = useCallback(() => {
    if (activeTab === 'job-runs') {
      fetchJobRuns();
    } else if (activeTab === 'events') {
      fetchEvents();
    } else {
      fetchQCFailures();
    }
  }, [activeTab, fetchJobRuns, fetchEvents, fetchQCFailures]);

  
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  
  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    const browsingHistory = activeTab === 'job-runs' ? jobWindow.offset > 0 || Boolean(jobWindow.from || jobWindow.to) : activeTab === 'events' ? eventWindow.offset > 0 || Boolean(eventWindow.from || eventWindow.to) : false;
    if (autoRefresh && !browsingHistory) {
      intervalRef.current = setInterval(() => {
        if (activeTab === 'job-runs') setJobWindow(initialHistoryWindow());
        else if (activeTab === 'events') setEventWindow(initialHistoryWindow());
        else fetchQCFailures();
      }, refreshInterval * 1000);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [autoRefresh, refreshInterval, fetchData, activeTab, jobWindow, eventWindow, fetchQCFailures]);

  
  const uniqueStatuses = jobOptions.status || [];
  const uniqueTasks = [...new Set([...(jobOptions.task || []), jobRunTaskFilter])].filter(Boolean);
  const uniqueEventTypes = eventOptions.event_type || [];
  const uniqueSources = eventOptions.source || [];
  const uniqueSeverities = eventOptions.severity || [];
  const handleTabKey = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    const tabs: TabType[] = ['job-runs', 'events', 'qc-failures'];
    const index = tabs.indexOf(activeTab);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : event.key === 'ArrowRight' ? (index + 1) % 3 : event.key === 'ArrowLeft' ? (index + 2) % 3 : -1;
    if (next >= 0) {
      event.preventDefault();
      setActiveTab(tabs[next]);
      document.getElementById(`tab-${tabs[next]}`)?.focus();
    }
  };


  return (
    <AdminPageLayout
      title={i18n.t('events:adminEventLog.tooltips.events')}
      description={i18n.t('events:adminEventLog.accessibility.inspectImporterJobRunsSystemEvent')}
      breadcrumbs={[
        { label: i18n.t('events:adminEventLog.content.admin'), to: '/admin' },
        { label: i18n.t('events:adminEventLog.content.events') },
      ]}
      actions={
        <div className="header-actions">
          <div className="auto-refresh-controls">
            <label className="refresh-toggle">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              <span><Trans ns="events" i18nKey="adminEventLog.text.autoRefresh" /></span>
            </label>
            {autoRefresh && (
              <label className="flex flex-wrap items-center gap-2">
              <span>{i18n.t('events:adminEventLog.text.refreshInterval')}</span>
              <select
                value={refreshInterval}
                onChange={(e) => setRefreshInterval(Number(e.target.value))}
                className="refresh-interval-select"
              >
                <option value={15}>15s</option>
                <option value={30}>30s</option>
                <option value={45}>45s</option>
                <option value={60}>60s</option>
              </select>
              </label>
            )}
          </div>
          <button className="btn btn-primary" onClick={() => {
            if (activeTab === 'job-runs') setJobWindow({ ...jobWindow, offset: 0, snapshot: new Date().toISOString() });
            else if (activeTab === 'events') setEventWindow({ ...eventWindow, offset: 0, snapshot: new Date().toISOString() });
            else fetchData();
          }}>
            <Trans ns="events" i18nKey="adminEventLog.actions.refresh" /></button>
          {lastRefresh && (
            <span className="last-refresh-time">
              <Trans ns="events" i18nKey="adminEventLog.text.last" />{formatOperationalTimestamp(lastRefresh)}
            </span>
          )}
        </div>
      }
      contentClassName="admin-workspace events-admin-page"
    >
      <div className="card">
        
        <div className="tab-navigation" role="tablist" aria-label={i18n.t('events:adminEventLog.accessibility.eventViews')}>
          <button
            className={`tab-button ${activeTab === 'job-runs' ? 'active' : ''}`}
            onClick={() => setActiveTab('job-runs')}
            role="tab"
            aria-selected={activeTab === 'job-runs'}
            id="tab-job-runs"
            aria-controls="panel-job-runs"
            tabIndex={activeTab === 'job-runs' ? 0 : -1}
            onKeyDown={handleTabKey}
          >
            <Trans ns="events" i18nKey="adminEventLog.actions.jobRuns" /></button>
          <button
            className={`tab-button ${activeTab === 'events' ? 'active' : ''}`}
            onClick={() => setActiveTab('events')}
            role="tab"
            aria-selected={activeTab === 'events'}
            id="tab-events"
            aria-controls="panel-events"
            tabIndex={activeTab === 'events' ? 0 : -1}
            onKeyDown={handleTabKey}
          >
            <Trans ns="events" i18nKey="adminEventLog.actions.systemEvents" /></button>
          <button
            className={`tab-button ${activeTab === 'qc-failures' ? 'active' : ''}`}
            onClick={() => setActiveTab('qc-failures')}
            role="tab"
            aria-selected={activeTab === 'qc-failures'}
            id="tab-qc-failures"
            aria-controls="panel-qc-failures"
            tabIndex={activeTab === 'qc-failures' ? 0 : -1}
            onKeyDown={handleTabKey}
          >
            <Trans ns="events" i18nKey="adminEventLog.actions.qcFailures" /></button>
        </div>

      
      {activeTab === 'job-runs' && (
        <div className="tab-content" role="tabpanel" id="panel-job-runs" aria-labelledby="tab-job-runs" tabIndex={0}>
          <EventHistoryControls window={jobWindow} onChange={setJobWindow} total={jobTotal} loading={jobRunsLoading} error={Boolean(jobRunsError)} firstTime={jobRuns[0]?.started_at} lastTime={jobRuns.at(-1)?.started_at} />
          {autoRefresh && (jobWindow.offset > 0 || jobWindow.from || jobWindow.to) && <p className="muted">{i18n.t('events:history.refreshPaused')}</p>}
          
          <div className="filter-bar">
            <div className="filter-group">
              <label htmlFor="jobRunStatusFilter"><Trans ns="events" i18nKey="adminEventLog.fields.status" /></label>
              <select
                id="jobRunStatusFilter"
                value={jobRunStatusFilter}
                onChange={(e) => { setJobRunStatusFilter(e.target.value); setJobWindow(value => ({ ...value, offset: 0 })); }}
              >
                <option value=""><Trans ns="events" i18nKey="adminEventLog.options.all" /></option>
                {uniqueStatuses.map(s => (
                  <option key={s} value={s}>{formatJobRunStatus(s, activeI18n.resolvedLanguage)}</option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label htmlFor="jobRunTaskFilter"><Trans ns="events" i18nKey="adminEventLog.fields.task" /></label>
              <select
                id="jobRunTaskFilter"
                value={jobRunTaskFilter}
                onChange={(e) => { setJobRunTaskFilter(e.target.value); setJobWindow(value => ({ ...value, offset: 0 })); }}
              >
                <option value=""><Trans ns="events" i18nKey="adminEventLog.options.all2" /></option>
                {uniqueTasks.map(t => (
                  <option key={t} value={t}>{codeLabel('task', t)}{i18n.exists(`events:history.labels.task.${t}`) ? '' : ` (${t})`}</option>
                ))}
              </select>
            </div>
          </div>

          
          {jobRunsLoading && <div className="loading-indicator"><Trans ns="events" i18nKey="adminEventLog.text.loadingJobRuns" /></div>}
          {jobRunsError && <div className="error-message" role="alert">{i18n.t('events:history.loadError')}<details><summary>{i18n.t('events:history.errorDetails')}</summary>{jobRunsError}</details></div>}
          {!jobRunsLoading && !jobRunsError && (
            <div className="table-container">
              <table className="data-table job-runs-table">
                <thead>
                  <tr>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.id" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.task" /></th>
                    <th><Trans ns="common" i18nKey="fields.status" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.started" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.duration" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.summary" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.error" /></th>
                  </tr>
                </thead>
                <tbody>
                  {jobRuns.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="empty-state"><Trans ns="events" i18nKey="adminEventLog.text.noJobRunsFound" /></td>
                    </tr>
                  ) : (
                    <JobRunRows runs={jobRuns} language={activeI18n.resolvedLanguage} />
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      
      {activeTab === 'events' && (
        <div className="tab-content" role="tabpanel" id="panel-events" aria-labelledby="tab-events" tabIndex={0}>
          <EventHistoryControls window={eventWindow} onChange={setEventWindow} total={eventTotal} loading={eventsLoading} error={Boolean(eventsError)} firstTime={events[0]?.created_at} lastTime={events.at(-1)?.created_at} />
          {autoRefresh && (eventWindow.offset > 0 || eventWindow.from || eventWindow.to) && <p className="muted">{i18n.t('events:history.refreshPaused')}</p>}
          
          <div className="filter-bar">
            <div className="filter-group">
              <label htmlFor="eventTypeFilter"><Trans ns="events" i18nKey="adminEventLog.fields.type" /></label>
              <select
                id="eventTypeFilter"
                value={eventTypeFilter}
                onChange={(e) => { setEventTypeFilter(e.target.value); setEventWindow(value => ({ ...value, offset: 0 })); }}
              >
                <option value=""><Trans ns="events" i18nKey="adminEventLog.options.all3" /></option>
                {uniqueEventTypes.map(t => (
                  <option key={t} value={t}>{codeLabel('event', t)}{i18n.exists(`events:history.labels.event.${t.replaceAll('.', '_')}`) ? '' : ` (${t})`}</option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label htmlFor="eventSourceFilter"><Trans ns="events" i18nKey="adminEventLog.fields.source" /></label>
              <select
                id="eventSourceFilter"
                value={eventSourceFilter}
                onChange={(e) => { setEventSourceFilter(e.target.value); setEventWindow(value => ({ ...value, offset: 0 })); }}
              >
                <option value=""><Trans ns="events" i18nKey="adminEventLog.options.all4" /></option>
                {uniqueSources.map(s => (
                  <option key={s} value={s}>{s === 'CSV upload' ? i18n.t('events:csvUpload.source') : s}</option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label htmlFor="eventSeverityFilter"><Trans ns="events" i18nKey="adminEventLog.fields.severity" /></label>
              <select
                id="eventSeverityFilter"
                value={eventSeverityFilter}
                onChange={(e) => { setEventSeverityFilter(e.target.value); setEventWindow(value => ({ ...value, offset: 0 })); }}
              >
                <option value=""><Trans ns="events" i18nKey="adminEventLog.options.all5" /></option>
                {uniqueSeverities.map(s => (
                  <option key={s} value={s}>{i18n.t(`events:history.severity.${s}`, { defaultValue: s })}</option>
                ))}
              </select>
            </div>
          </div>

          
          {eventsLoading && <div className="loading-indicator"><Trans ns="events" i18nKey="adminEventLog.text.loadingEvents" /></div>}
          {eventsError && <div className="error-message" role="alert">{i18n.t('events:history.loadError')}<details><summary>{i18n.t('events:history.errorDetails')}</summary>{eventsError}</details></div>}
          {!eventsLoading && !eventsError && (
            <div className="table-container">
              <table className="data-table system-events-table">
                <thead>
                  <tr>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.time" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.severity" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.type" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.source" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.actor" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.message" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.device" /></th>
                    <th><Trans ns="events" i18nKey="adminEventLog.columns.sensor" /></th>
                  </tr>
                </thead>
                <tbody>
                  {events.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="empty-state"><Trans ns="events" i18nKey="adminEventLog.text.noEventsFound" /></td>
                    </tr>
                  ) : (
                    <EventRows items={events} />
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'qc-failures' && (
        <div className="tab-content" role="tabpanel" id="panel-qc-failures" aria-labelledby="tab-qc-failures" tabIndex={0}>
          <div className="filter-bar qc-failure-filter-bar">
            <div className="filter-group qc-failure-search-filter">
              <label htmlFor="qc-failure-search">
                <Trans ns="events" i18nKey="adminEventLog.fields.search" />
              </label>
              <input
                id="qc-failure-search"
                type="search"
                value={qcFailureSearch}
                placeholder={i18n.t('events:adminEventLog.qcFailures.placeholders.search')}
                onChange={(event) => {
                  setQcFailureOffset(0);
                  setQcFailureSearch(event.target.value);
                }}
              />
            </div>
            <div className="filter-group">
              <label htmlFor="qc-failure-parameter">
                <Trans ns="events" i18nKey="adminEventLog.fields.parameter" />
              </label>
              <input
                id="qc-failure-parameter"
                value={qcFailureParameter}
                placeholder={i18n.t('events:adminEventLog.qcFailures.placeholders.parameter')}
                onChange={(event) => {
                  setQcFailureOffset(0);
                  setQcFailureParameter(event.target.value);
                }}
              />
            </div>
            <div className="filter-group">
              <label htmlFor="qc-failure-status">
                <Trans ns="events" i18nKey="adminEventLog.fields.status" />
              </label>
              <select
                id="qc-failure-status"
                value={qcFailureStatus}
                onChange={(event) => {
                  setQcFailureOffset(0);
                  setQcFailureStatus(event.target.value as QCFailureStatus | '');
                }}
              >
                <option value=""><Trans ns="events" i18nKey="adminEventLog.qcFailures.status.allIssues" /></option>
                <option value="failed"><Trans ns="events" i18nKey="adminEventLog.qcFailures.status.failed" /></option>
                <option value="indeterminate"><Trans ns="events" i18nKey="adminEventLog.qcFailures.status.unableToEvaluate" /></option>
              </select>
            </div>
            <div className="filter-group">
              <label htmlFor="qc-failure-outcome">
                <Trans ns="events" i18nKey="adminEventLog.fields.effect" />
              </label>
              <select
                id="qc-failure-outcome"
                value={qcFailureOutcome}
                onChange={(event) => {
                  setQcFailureOffset(0);
                  setQcFailureOutcome(event.target.value as QCFailureOutcome | '');
                }}
              >
                <option value=""><Trans ns="events" i18nKey="adminEventLog.options.allEffects" /></option>
                <option value="flag_for_review">{failureActionLabel('flag_for_review')}</option>
                <option value="mark_invalid">{failureActionLabel('mark_invalid')}</option>
              </select>
            </div>
            <div className="filter-group">
              <label htmlFor="qc-failure-data-source">
                <Trans ns="events" i18nKey="adminEventLog.fields.dataSource" />
              </label>
              <input
                id="qc-failure-data-source"
                value={qcFailureDataSource}
                placeholder={i18n.t('events:adminEventLog.qcFailures.placeholders.dataSource')}
                onChange={(event) => {
                  setQcFailureOffset(0);
                  setQcFailureDataSource(event.target.value);
                }}
              />
            </div>
            {!qcFailuresLoading && !qcFailuresError && (
              <span className="result-count" role="status" aria-live="polite">
                <Trans
                  ns="events"
                  i18nKey="adminEventLog.qcFailures.resultCount"
                  values={{ count: qcFailures.total }}
                  count={qcFailures.total}
                />
              </span>
            )}
          </div>

          {qcFailuresLoading && (
            <div className="loading-indicator">
              <Trans ns="events" i18nKey="adminEventLog.qcFailures.loading" />
            </div>
          )}
          {qcFailuresError && <div className="error-message" role="alert">{qcFailuresError}</div>}
          {!qcFailuresLoading && !qcFailuresError && (
            <>
              <div className="table-container qc-failure-table-container">
                <table className="data-table qc-failure-table">
                  <thead>
                    <tr>
                      <th><Trans ns="events" i18nKey="adminEventLog.qcFailures.columns.resultTime" /></th>
                      <th><Trans ns="events" i18nKey="adminEventLog.columns.device" /></th>
                      <th><Trans ns="events" i18nKey="adminEventLog.qcFailures.columns.dataSource" /></th>
                      <th><Trans ns="events" i18nKey="adminEventLog.qcFailures.columns.parameter" /></th>
                      <th><Trans ns="events" i18nKey="adminEventLog.qcFailures.columns.measurement" /></th>
                      <th><Trans ns="events" i18nKey="adminEventLog.qcFailures.columns.check" /></th>
                      <th><Trans ns="events" i18nKey="adminEventLog.qcFailures.columns.statusEffect" /></th>
                      <th><Trans ns="events" i18nKey="adminEventLog.qcFailures.columns.reason" /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {qcFailures.items.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="empty-state">
                          <Trans ns="events" i18nKey="adminEventLog.qcFailures.empty" />
                        </td>
                      </tr>
                    ) : (
                      qcFailures.items.map((qcFailure) => (
                        <tr key={qcFailure.measurement_qc_result_id}>
                          <td
                            className="cell-time"
                            data-label={i18n.t('events:adminEventLog.qcFailures.columns.resultTime')}
                          >
                            {formatOperationalTimestamp(qcFailure.qc_result_created_at)}
                          </td>
                          <td data-label={i18n.t('events:adminEventLog.columns.device')}>
                            <strong>{qcFailure.device_name}</strong>
                            <span className="qc-failure-secondary">
                              {qcFailure.external_sensor_id || `${i18n.t('events:adminEventLog.columns.sensor')} ${qcFailure.sensor_id}`}
                            </span>
                          </td>
                          <td data-label={i18n.t('events:adminEventLog.qcFailures.columns.dataSource')}>
                            {qcFailure.data_source_name}
                            {qcFailure.provider_code && qcFailure.provider_code !== qcFailure.data_source_name && (
                              <span className="qc-failure-secondary">{qcFailure.provider_code}</span>
                            )}
                          </td>
                          <td data-label={i18n.t('events:adminEventLog.qcFailures.columns.parameter')}>
                            {qcFailure.parameter_name || qcFailure.parameter_code || '—'}
                            {qcFailure.parameter_name && qcFailure.parameter_code && (
                              <span className="qc-failure-secondary">{qcFailure.parameter_code}</span>
                            )}
                          </td>
                          <td data-label={i18n.t('events:adminEventLog.qcFailures.columns.measurement')}>
                            <strong>
                              {formatQcNumber(qcFailure.measurement_value)} {qcFailure.unit_symbol || qcFailure.unit_code || ''}
                            </strong>
                            <span className="qc-failure-secondary">
                              {qcFailure.measurement_observed_at
                                ? formatOperationalTimestamp(qcFailure.measurement_observed_at)
                                : i18n.t('events:adminEventLog.text.notAvailable')}
                            </span>
                          </td>
                          <td data-label={i18n.t('events:adminEventLog.qcFailures.columns.check')}>
                            {checkName(qcFailure.check_code, {
                              display_name: qcFailure.check_name,
                              description: '',
                            })}
                          </td>
                          <td data-label={i18n.t('events:adminEventLog.qcFailures.columns.statusEffect')}>
                            <span className={`qc-effect-badge qc-effect-${qcFailure.evaluation_status === 'indeterminate' ? 'indeterminate' : qcFailure.failure_action || 'unknown'}`}>
                              {qcFailureStatusLabel(qcFailure)}
                            </span>
                          </td>
                          <td
                            className="qc-failure-reason"
                            data-label={i18n.t('events:adminEventLog.qcFailures.columns.reason')}
                          >
                            <span className={qcFailure.evaluation_status === 'indeterminate' ? 'qc-failure-explanation' : undefined}>
                              {qcFailureExplanation(qcFailure)}
                            </span>
                            <QcFailureDetails qcFailure={qcFailure} />
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              {qcFailures.total > 0 && (
                <div className="qc-failure-pagination">
                  <span>
                    <Trans
                      ns="events"
                      i18nKey="adminEventLog.qcFailures.range"
                      values={{
                        first: qcFailures.offset + 1,
                        last: qcFailures.offset + qcFailures.items.length,
                        total: qcFailures.total,
                      }}
                    />
                  </span>
                  <div>
                    <button
                      type="button"
                      className="btn small"
                      disabled={qcFailureOffset === 0}
                      onClick={() => setQcFailureOffset(Math.max(0, qcFailureOffset - QC_FAILURE_PAGE_SIZE))}
                    >
                      <Trans ns="events" i18nKey="adminEventLog.qcFailures.previous" />
                    </button>
                    <button
                      type="button"
                      className="btn small"
                      disabled={qcFailureOffset + QC_FAILURE_PAGE_SIZE >= qcFailures.total}
                      onClick={() => setQcFailureOffset(qcFailureOffset + QC_FAILURE_PAGE_SIZE)}
                    >
                      <Trans ns="events" i18nKey="adminEventLog.qcFailures.next" />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
      </div>
    </AdminPageLayout>
  );
}
