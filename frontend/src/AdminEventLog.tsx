import { useEffect, useState, useCallback, useRef } from 'react';
import { listAllJobRuns, listEvents } from './api';
import type { JobRunRecord, EventRecord } from './api';
import AdminPageLayout from './components/AdminPageLayout';

type TabType = 'job-runs' | 'events';

export default function AdminEventLog() {
  
  const [activeTab, setActiveTab] = useState<TabType>('job-runs');

  
  const [jobRuns, setJobRuns] = useState<JobRunRecord[]>([]);
  const [jobRunsLoading, setJobRunsLoading] = useState(true);
  const [jobRunsError, setJobRunsError] = useState<string | null>(null);
  const [jobRunStatusFilter, setJobRunStatusFilter] = useState<string>('');
  const [jobRunTaskFilter, setJobRunTaskFilter] = useState<string>('');

  
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('');
  const [eventSourceFilter, setEventSourceFilter] = useState<string>('');
  const [eventSeverityFilter, setEventSeverityFilter] = useState<string>('');

  
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshInterval, setRefreshInterval] = useState(45);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  
  const fetchJobRuns = useCallback(async () => {
    setJobRunsLoading(true);
    setJobRunsError(null);
    try {
      const filters: { status?: string; task?: string; limit?: number } = { limit: 100 };
      if (jobRunStatusFilter) filters.status = jobRunStatusFilter;
      if (jobRunTaskFilter) filters.task = jobRunTaskFilter;
      const data = await listAllJobRuns(filters);
      setJobRuns(data);
      setLastRefresh(new Date());
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setJobRunsError(message);
    } finally {
      setJobRunsLoading(false);
    }
  }, [jobRunStatusFilter, jobRunTaskFilter]);

  
  const fetchEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError(null);
    try {
      const filters: { event_type?: string; source?: string; severity?: string; limit?: number } = { limit: 100 };
      if (eventTypeFilter) filters.event_type = eventTypeFilter;
      if (eventSourceFilter) filters.source = eventSourceFilter;
      if (eventSeverityFilter) filters.severity = eventSeverityFilter;
      const data = await listEvents(filters);
      setEvents(data);
      setLastRefresh(new Date());
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setEventsError(message);
    } finally {
      setEventsLoading(false);
    }
  }, [eventTypeFilter, eventSourceFilter, eventSeverityFilter]);

  
  const fetchData = useCallback(() => {
    if (activeTab === 'job-runs') {
      fetchJobRuns();
    } else {
      fetchEvents();
    }
  }, [activeTab, fetchJobRuns, fetchEvents]);

  
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  
  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (autoRefresh) {
      intervalRef.current = setInterval(fetchData, refreshInterval * 1000);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [autoRefresh, refreshInterval, fetchData]);

  
  const formatDuration = (start: string, end: string | null): string => {
    if (!end) return 'Running...';
    const startDate = new Date(start);
    const endDate = new Date(end);
    const diffMs = endDate.getTime() - startDate.getTime();
    if (diffMs < 1000) return `${diffMs}ms`;
    if (diffMs < 60000) return `${(diffMs / 1000).toFixed(1)}s`;
    return `${(diffMs / 60000).toFixed(1)}m`;
  };

  
  const StatusBadge = ({ status }: { status: string }) => {
    const getStatusClass = (s: string) => {
      switch (s.toLowerCase()) {
        case 'success': return 'status-badge status-success';
        case 'failed': case 'failure': return 'status-badge status-error';
        case 'running': return 'status-badge status-running';
        case 'skipped': return 'status-badge status-skipped';
        default: return 'status-badge status-unknown';
      }
    };
    return <span className={getStatusClass(status)}>{status}</span>;
  };

  
  const SeverityBadge = ({ severity }: { severity: string }) => {
    const getSeverityClass = (s: string) => {
      switch (s.toLowerCase()) {
        case 'info': return 'severity-badge severity-info';
        case 'warning': case 'warn': return 'severity-badge severity-warning';
        case 'error': return 'severity-badge severity-error';
        default: return 'severity-badge severity-info';
      }
    };
    return <span className={getSeverityClass(severity)}>{severity}</span>;
  };

  
  const uniqueStatuses = [...new Set(jobRuns.map(r => r.status))].filter(Boolean).sort();
  const uniqueTasks = [...new Set(jobRuns.map(r => r.task))].filter(Boolean).sort();
  const uniqueEventTypes = [...new Set(events.map(e => e.event_type))].filter(Boolean).sort();
  const uniqueSources = [...new Set(events.map(e => e.source))].filter(Boolean).sort();
  const uniqueSeverities = [...new Set(events.map(e => e.severity))].filter(Boolean).sort();

  return (
    <AdminPageLayout
      title="Events"
      description="Inspect importer job runs and system event logs."
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'Events' },
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
              <span>Auto-refresh</span>
            </label>
            {autoRefresh && (
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
            )}
          </div>
          <button className="btn btn-primary" onClick={fetchData}>
            ↻ Refresh
          </button>
          {lastRefresh && (
            <span className="last-refresh-time">
              Last: {lastRefresh.toLocaleTimeString()}
            </span>
          )}
        </div>
      }
      contentClassName="events-admin-page"
    >
      <div className="card">
        
        <div className="tab-navigation">
          <button
            className={`tab-button ${activeTab === 'job-runs' ? 'active' : ''}`}
            onClick={() => setActiveTab('job-runs')}
          >
            Job Runs
          </button>
          <button
            className={`tab-button ${activeTab === 'events' ? 'active' : ''}`}
            onClick={() => setActiveTab('events')}
          >
            Events
          </button>
        </div>

      
      {activeTab === 'job-runs' && (
        <div className="tab-content">
          
          <div className="filter-bar">
            <div className="filter-group">
              <label>Status:</label>
              <select
                value={jobRunStatusFilter}
                onChange={(e) => setJobRunStatusFilter(e.target.value)}
              >
                <option value="">All</option>
                {uniqueStatuses.map(s => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label>Task:</label>
              <select
                value={jobRunTaskFilter}
                onChange={(e) => setJobRunTaskFilter(e.target.value)}
              >
                <option value="">All</option>
                {uniqueTasks.map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <span className="result-count">{jobRuns.length} results</span>
          </div>

          
          {jobRunsLoading && <div className="loading-indicator">Loading job runs…</div>}
          {jobRunsError && <div className="error-message">{jobRunsError}</div>}
          {!jobRunsLoading && !jobRunsError && (
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Task</th>
                    <th>Status</th>
                    <th>Started</th>
                    <th>Duration</th>
                    <th>Summary</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {jobRuns.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="empty-state">No job runs found</td>
                    </tr>
                  ) : (
                    jobRuns.map(run => (
                      <tr key={run.job_run_id} className={run.status === 'failed' ? 'row-error' : ''}>
                        <td className="cell-id">{run.job_run_id}</td>
                        <td className="cell-task">{run.task}</td>
                        <td><StatusBadge status={run.status} /></td>
                        <td className="cell-time">
                          {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
                        </td>
                        <td className="cell-duration">
                          {run.started_at ? formatDuration(run.started_at, run.finished_at ?? null) : '—'}
                        </td>
                        <td className="cell-summary" title={typeof run.summary === 'string' ? run.summary : JSON.stringify(run.summary) || ''}>
                          {run.summary ? (typeof run.summary === 'string' ? run.summary : JSON.stringify(run.summary)) : '—'}
                        </td>
                        <td className="cell-error" title={run.error_message || ''}>
                          {run.error_message || '—'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      
      {activeTab === 'events' && (
        <div className="tab-content">
          
          <div className="filter-bar">
            <div className="filter-group">
              <label>Type:</label>
              <select
                value={eventTypeFilter}
                onChange={(e) => setEventTypeFilter(e.target.value)}
              >
                <option value="">All</option>
                {uniqueEventTypes.map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label>Source:</label>
              <select
                value={eventSourceFilter}
                onChange={(e) => setEventSourceFilter(e.target.value)}
              >
                <option value="">All</option>
                {uniqueSources.map(s => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label>Severity:</label>
              <select
                value={eventSeverityFilter}
                onChange={(e) => setEventSeverityFilter(e.target.value)}
              >
                <option value="">All</option>
                {uniqueSeverities.map(s => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <span className="result-count">{events.length} results</span>
          </div>

          
          {eventsLoading && <div className="loading-indicator">Loading events…</div>}
          {eventsError && <div className="error-message">{eventsError}</div>}
          {!eventsLoading && !eventsError && (
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Severity</th>
                    <th>Type</th>
                    <th>Source</th>
                    <th>Actor</th>
                    <th>Message</th>
                    <th>Device</th>
                    <th>Sensor</th>
                  </tr>
                </thead>
                <tbody>
                  {events.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="empty-state">No events found</td>
                    </tr>
                  ) : (
                    events.map(ev => (
                      <tr key={ev.event_id} className={ev.severity === 'error' ? 'row-error' : ev.severity === 'warning' ? 'row-warning' : ''}>
                        <td className="cell-time">
                          {ev.created_at ? new Date(ev.created_at).toLocaleString() : '—'}
                        </td>
                        <td><SeverityBadge severity={ev.severity || 'info'} /></td>
                        <td className="cell-type">{ev.event_type}</td>
                        <td className="cell-source">{ev.source}</td>
                        <td className="cell-message" title={ev.actor_email || ev.actor_user_id || ''}>
                          {ev.actor_email || ev.actor_user_id || '—'}
                        </td>
                        <td className="cell-message" title={ev.message || ''}>
                          {ev.message || '—'}
                        </td>
                        <td className="cell-id">{ev.device_id ?? '—'}</td>
                        <td className="cell-id">{ev.sensor_id ?? '—'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      </div>
    </AdminPageLayout>
  );
}
