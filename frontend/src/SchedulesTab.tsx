import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { JobSchedule, ExternalAPI, SchedulePreview } from './api';
import { listExternalAPISchedules, previewSchedule, updateSchedule } from './api';
import { sourceReadinessKey } from './sourceReadinessPresentation';
import type { ScheduleState } from './SourceReadiness';
import { ApiError } from './apiError';
import { formatOperationalTimestamp, getSelectableIanaTimezones } from './utils/timezone';

// Summarize common cadences only. The backend cron parser validates all expressions
// and supplies upcoming times for advanced syntax; this is presentation, not execution.
// eslint-disable-next-line react-refresh/only-export-components
export function scheduleCadence(cron: string): { key: 'everyMinute' | 'everyMinutes' | 'hourly' | 'daily' | 'custom'; values?: { count?: number; minute?: string; time?: string } } {
  const fields = cron.trim().split(/\s+/);
  if (fields.length === 5 && fields.slice(1).every(field => field === '*')) {
    if (fields[0] === '*') return { key: 'everyMinute' };
    const step = /^\*\/(\d+)$/.exec(fields[0]);
    if (step && Number(step[1]) > 0 && 60 % Number(step[1]) === 0) return { key: 'everyMinutes', values: { count: Number(step[1]) } };
    if (/^\d+$/.test(fields[0]) && Number(fields[0]) < 60) return { key: 'hourly', values: { minute: fields[0].padStart(2, '0') } };
  }
  if (fields.length === 5 && fields.slice(2).every(field => field === '*') && /^\d+$/.test(fields[0]) && /^\d+$/.test(fields[1]) && Number(fields[0]) < 60 && Number(fields[1]) < 24) {
    return { key: 'daily', values: { time: `${fields[1].padStart(2, '0')}:${fields[0].padStart(2, '0')}` } };
  }
  return { key: 'custom' };
}

function ScheduleCard({ schedule, source, onSaved }: { schedule: JobSchedule; source: ExternalAPI; onSaved: (schedule: JobSchedule) => void }) {
  const { t } = useTranslation(['dataSources', 'common']);
  const [edit, setEdit] = useState(schedule);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const saveButtonRef = useRef<HTMLButtonElement>(null);
  const restoreSaveFocus = useRef(false);
  useEffect(() => {
    if (!saving && restoreSaveFocus.current) {
      if (document.activeElement === document.body) saveButtonRef.current?.focus();
      restoreSaveFocus.current = false;
    }
  }, [saving]);
  const [notice, setNotice] = useState<'saved' | 'error' | 'invalidCron' | null>(null);
  const [preview, setPreview] = useState<{ cron: string; result: SchedulePreview | null } | null>(null);
  const [saved, setSaved] = useState(schedule);
  const prefix = `schedule-${schedule.job_schedule_id}`;
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      previewSchedule(edit.cron_expr).then(
        result => { if (!cancelled) setPreview({ cron: edit.cron_expr, result }); },
        () => { if (!cancelled) setPreview({ cron: edit.cron_expr, result: null }); },
      );
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [edit.cron_expr]);
  const currentPreview = preview?.cron === edit.cron_expr ? preview : null;
  const invalid = currentPreview?.result?.valid === false || notice === 'invalidCron';
  const cadence = scheduleCadence(edit.cron_expr);
  const taskName = t(schedule.task.endsWith('_import') ? 'schedulesTab.clarity.importTask' : 'schedulesTab.clarity.sourceTask', { name: source.name });
  const stateKey = !saved.enabled ? 'off' : !source.enabled ? 'blockedDisabled' : source.is_runnable === true ? 'ready' : source.is_runnable === false ? 'blocked' : 'unknown';
  const change = (patch: Partial<JobSchedule>) => { setEdit(previous => ({ ...previous, ...patch })); setNotice(null); };

  return <form className="schedule-card" aria-label={taskName} aria-busy={saving} onSubmit={async event => {
    event.preventDefault();
    if (savingRef.current || invalid) return;
    restoreSaveFocus.current = document.activeElement === saveButtonRef.current;
    savingRef.current = true;
    setSaving(true);
    setNotice(null);
    try {
      const updated = await updateSchedule(schedule.job_schedule_id, { cron_expr: edit.cron_expr, timezone: edit.timezone, enabled: edit.enabled, allow_overlap: edit.allow_overlap });
      setSaved(updated);
      onSaved(updated);
      setEdit(updated);
      setNotice('saved');
    } catch (error) {
      setNotice(error instanceof ApiError && error.errorCode === 'invalid_cron' ? 'invalidCron' : 'error');
    } finally { savingRef.current = false; setSaving(false); }
  }}>
    <h3>{taskName}</h3>
    <div className="info-banner" role="status">
      {t(`schedulesTab.clarity.${stateKey}`)}
      {sourceReadinessKey(source) !== 'ready' && <> {t(`workflow.${sourceReadinessKey(source)}`)}</>}
    </div>
    <fieldset className="schedule-edit-fields" disabled={saving}>
      <legend className="sr-only">{taskName}</legend>
      <p id={`${prefix}-preview`} aria-live="polite">
        {!currentPreview ? t('schedulesTab.clarity.checking') : !currentPreview.result ? t('schedulesTab.clarity.previewUnavailable') : invalid ? t('schedulesTab.clarity.invalidCron') : t(`schedulesTab.clarity.${cadence.key}`, cadence.values ?? {})}
      </p>
      {currentPreview?.result?.valid && <div className="schedule-next-runs">
        <span>{t('schedulesTab.clarity.nextTimes')}</span>
        {currentPreview.result.next_runs.length > 0 ? <ul>{currentPreview.result.next_runs.map(time => <li key={time}>{formatOperationalTimestamp(time)}</li>)}</ul> : <p>{t('schedulesTab.clarity.noUpcomingTimes')}</p>}
      </div>}
      <p>{t('schedulesTab.clarity.utcHelp')}</p>
      <div className="schedule-flags">
        <label className="flag-check"><input type="checkbox" checked={edit.enabled} onChange={event => change({ enabled: event.target.checked })} />{t('schedulesTab.clarity.enableSchedule')}</label>
      </div>
      <details>
        <summary>{t('schedulesTab.clarity.advanced')}</summary>
        <div className="schedule-fields">
          <div className="schedule-field stretch">
            <label htmlFor={`${prefix}-cron`}>{t('schedulesTab.clarity.cronLabel')}</label>
            <input id={`${prefix}-cron`} className="text-input" required maxLength={64} value={edit.cron_expr} onChange={event => change({ cron_expr: event.target.value })} aria-invalid={invalid} aria-describedby={`${prefix}-cron-help ${prefix}-preview`} />
            <p id={`${prefix}-cron-help`}>{t('schedulesTab.clarity.cronHelp')}</p>
          </div>
          <div className="schedule-field stretch">
            <label htmlFor={`${prefix}-timezone`}>{t('schedulesTab.clarity.storedTimezone')}</label>
            <select id={`${prefix}-timezone`} className="select-input" value={edit.timezone} onChange={event => change({ timezone: event.target.value })} aria-describedby={`${prefix}-timezone-help`}>
              {getSelectableIanaTimezones(schedule.timezone).map(timezone => <option key={timezone}>{timezone}</option>)}
            </select>
            <p id={`${prefix}-timezone-help`}>{t('schedulesTab.clarity.timezoneHelp')}</p>
          </div>
        </div>
        <p>{t('schedulesTab.clarity.taskIdentifier')}: <code>{schedule.task}</code></p>
        <div className="schedule-flags">
          <label className="flag-check"><input type="checkbox" checked={edit.allow_overlap} onChange={event => change({ allow_overlap: event.target.checked })} aria-describedby={`${prefix}-overlap-help`} />{t('schedulesTab.clarity.overlapLabel')}</label>
        </div>
        <p id={`${prefix}-overlap-help`}>{t('schedulesTab.clarity.overlapHelp')}</p>
      </details>
    </fieldset>
    {invalid && <div className="error-banner" role="alert">{t('schedulesTab.clarity.invalidCron')}</div>}
    {notice === 'error' && <div className="error-banner" role="alert">{t('common:errors.updateSchedule')}</div>}
    {notice === 'saved' && <div className="success-banner" role="status">{t('schedulesTab.notifications.scheduleUpdated')}</div>}
    <div className="admin-form-save-actions"><button ref={saveButtonRef} className="btn btn-primary" type="submit" disabled={saving || invalid}>{saving ? t('common:actions.savingChanges') : t('common:actions.saveChanges')}</button></div>
  </form>;
}

export default function SchedulesTab({ selectedExternalAPI, onStateChange }: { selectedExternalAPI: ExternalAPI | null; onStateChange?: (state: ScheduleState) => void }) {
  const { t } = useTranslation(['dataSources', 'common', 'admin']);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [schedules, setSchedules] = useState<JobSchedule[]>([]);
  const sourceId = selectedExternalAPI?.external_api_id;
  useEffect(() => {
    let cancelled = false;
    setSchedules([]);
    if (!sourceId) { setLoading(false); return; }
    setLoading(true);
    setError(false);
    listExternalAPISchedules(sourceId).then(
      rows => { if (!cancelled) setSchedules(rows); },
      () => { if (!cancelled) setError(true); },
    ).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sourceId]);
  useEffect(() => {
    onStateChange?.(loading ? 'loading' : error ? 'unavailable' : schedules.length === 0 ? 'none' : schedules.some(schedule => schedule.enabled) ? 'on' : 'off');
  }, [loading, error, schedules, onStateChange]);
  if (!selectedExternalAPI) return null;
  return <section id="source-schedule" tabIndex={-1} className="admin-section" aria-labelledby="source-schedule-heading">
    <h2 id="source-schedule-heading">{t('workflow.scheduleHeading')}</h2>
    {loading && <div className="info-banner" role="status">{t('common:states.loading')}</div>}
    {error && <div className="error-banner" role="alert">{t('admin:workspace.loadSchedules')}</div>}
    {!loading && !error && schedules.length === 0 && <p>{t('schedulesTab.clarity.empty')}</p>}
    <div className="schedule-list">{schedules.map(schedule => <ScheduleCard key={`${sourceId}-${schedule.job_schedule_id}`} schedule={schedule} source={selectedExternalAPI} onSaved={updated => setSchedules(rows => rows.map(row => row.job_schedule_id === updated.job_schedule_id ? updated : row))} />)}</div>
  </section>;
}
