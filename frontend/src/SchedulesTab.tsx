import { useEffect, useState } from 'react';
import type { JobSchedule, ExternalAPI } from './api';
import { listExternalAPISchedules, updateSchedule } from './api';

export default function SchedulesTab({ selectedExternalAPI } : { selectedExternalAPI: ExternalAPI | null }) {
  const [apiSchedules, setApiSchedules] = useState<JobSchedule[]>([]);
  const [scheduleEditing, setScheduleEditing] = useState<Record<number, Partial<{ cron_expr: string; timezone: string; enabled: boolean; allow_overlap: boolean; api_key: string }>>>({});

  useEffect(() => {
    (async () => {
      if (!selectedExternalAPI) {
        setApiSchedules([]);
        setScheduleEditing({});
        return;
      }

      try {
        const schedules = await listExternalAPISchedules(selectedExternalAPI.external_api_id);
        setApiSchedules(schedules || []);
        
        const editState: Record<number, Partial<{ cron_expr: string; timezone: string; enabled: boolean; allow_overlap: boolean; api_key: string }>> = {};
        for (const sch of (schedules || [])) {
          editState[sch.job_schedule_id] = {
            cron_expr: sch.cron_expr || '',
            timezone: sch.timezone || 'UTC',
            enabled: sch.enabled ?? false,
            allow_overlap: sch.allow_overlap ?? false,
            api_key: (sch.params as any)?.api_key || '',
          };
        }
        setScheduleEditing(editState);
      } catch {
        setApiSchedules([]);
      }
    })();
  }, [selectedExternalAPI]);

  if (!selectedExternalAPI) return null;

  return (
    <section className="admin-section">
      <h3>Linked Schedules</h3>
      <div className="schedule-list">
        {apiSchedules.length === 0 && <div className="hint">No schedules matched this source name pattern.</div>}
        {apiSchedules.map(sch => {
          const edit = scheduleEditing[sch.job_schedule_id] || {};
          return (
            <div key={sch.job_schedule_id} className="schedule-card">
              <div className="schedule-heading">
                <span className="pill">{sch.task}</span>
              </div>
              <div className="schedule-fields">
                <div className="schedule-field">
                  <div className="label">Cron</div>
                  <input className="text-input" value={edit.cron_expr || ''} onChange={e=>setScheduleEditing({...scheduleEditing, [sch.job_schedule_id]: {...edit, cron_expr: e.target.value}})} placeholder="0 * * * *" />
                </div>
                <div className="schedule-field">
                  <div className="label">Timezone</div>
                  <input className="text-input" value={edit.timezone || ''} onChange={e=>setScheduleEditing({...scheduleEditing, [sch.job_schedule_id]: {...edit, timezone: e.target.value}})} placeholder="UTC" />
                </div>
                <div className="schedule-field stretch">
                  <div className="label">API Key</div>
                  <input className="text-input" value={edit.api_key || ''} onChange={e=>setScheduleEditing({...scheduleEditing, [sch.job_schedule_id]: {...edit, api_key: e.target.value}})} />
                </div>
              </div>
              <div className="schedule-actions">
                <div className="schedule-flags">
                  <label className="flag-check">
                    <input type="checkbox" checked={!!edit.enabled} onChange={e=>setScheduleEditing({...scheduleEditing, [sch.job_schedule_id]: {...edit, enabled: e.target.checked}})} /> Enabled
                  </label>
                  <label className="flag-check">
                    <input type="checkbox" checked={!!edit.allow_overlap} onChange={e=>setScheduleEditing({...scheduleEditing, [sch.job_schedule_id]: {...edit, allow_overlap: e.target.checked}})} /> Allow overlap
                  </label>
                </div>
                <button className="btn primary" onClick={async ()=>{
                  
                  if (selectedExternalAPI.name === 'PurpleAir' && edit.api_key) {
                    try {
                      const res = await fetch('https://api.purpleair.com/v1/keys', {
                        headers: { 'X-API-Key': edit.api_key }
                      });
                      if (res.status === 402) {
                        const err = await res.json().catch(() => ({}));
                        const desc = err.description || 'Payment Required';
                        if (!confirm(`PurpleAir API Error (402): ${desc}\n\nSave schedule anyway?`)) return;
                      } else if (!res.ok) {
                        if (!confirm('PurpleAir API key validation failed (server returned error). Save schedule anyway?')) return;
                      }
                    } catch {
                      if (!confirm('PurpleAir API key validation failed (network/CORS error). Save schedule anyway?')) return;
                    }
                  }

                  try {
                    const payload: any = {
                      cron_expr: edit.cron_expr,
                      timezone: edit.timezone,
                      enabled: edit.enabled,
                      allow_overlap: edit.allow_overlap,
                      params: { ...(sch.params||{}), api_key: edit.api_key || undefined },
                    };
                    const updated = await updateSchedule(sch.job_schedule_id, payload);
                    setApiSchedules(apiSchedules.map(x=>x.job_schedule_id===sch.job_schedule_id?updated:x));
                    alert('Schedule updated');
                  } catch (e:any) { alert(e?.message || 'Failed to update schedule'); }
                }}>Save</button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
