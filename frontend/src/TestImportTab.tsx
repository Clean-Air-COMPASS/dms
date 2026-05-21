import { useEffect, useState } from 'react';
import type { ExternalAPI, JobSchedule } from './api';
import { runImport, listSchedules, updateScheduleParams } from './api';

export default function TestImportTab({ selectedExternalAPI } : { selectedExternalAPI: ExternalAPI | null }) {
  const [importRunning, setImportRunning] = useState(false);
  const [importSource, setImportSource] = useState<string>('openaq');
  const [importTarget, setImportTarget] = useState<string>('');
  const [importApiKey, setImportApiKey] = useState<string>('');
  const [importResult, setImportResult] = useState<any | null>(null);
  const [schedule, setSchedule] = useState<JobSchedule | null>(null);

  useEffect(() => {
    (async () => {
      if (!selectedExternalAPI) {
        setSchedule(null);
        setImportSource('openaq');
        setImportTarget('');
        setImportApiKey('');
        return;
      }
      
      const sourceName = selectedExternalAPI.name?.toLowerCase() || '';
      if (sourceName.includes('purpleair')) {
        setImportSource('purpleair');
      } else {
        setImportSource('openaq');
      }
      
      setImportApiKey(selectedExternalAPI.api_key || '');
      try {
        const all = await listSchedules();
        const match = all.find(s => s.task?.toLowerCase().includes(sourceName));
        if (match) {
          setSchedule(match);
          
          const schedApiKey = (match.params as any)?.api_key;
          if (schedApiKey && !selectedExternalAPI.api_key) {
            setImportApiKey(schedApiKey);
          }
        } else {
          setSchedule(null);
        }
      } catch {
        setSchedule(null);
      }
    })();
  }, [selectedExternalAPI]);

  if (!selectedExternalAPI) return null;

  return (
    <section className="admin-section">
      <h3>Test Import Run</h3>
      <div className="import-card">
        <div className="import-fields">
          <div className="import-field">
            <div className="label">Importer</div>
            <select className="select-input" value={importSource} onChange={e=>setImportSource(e.target.value)} title="Import source" aria-label="Import source selector">
              <option value="openaq">OpenAQ importer</option>
              <option value="purpleair">PurpleAir importer</option>
            </select>
            {selectedExternalAPI && <div className="inline-hint">Linked to "{selectedExternalAPI.name}"</div>}
          </div>
          <div className="import-field">
            <div className="label">Sensor ID (optional)</div>
            <input className="text-input" value={importTarget} onChange={e=>setImportTarget(e.target.value)} placeholder="e.g. 1620" />
          </div>
          <div className="import-field stretch">
            <div className="label">API Key</div>
            <input className="text-input" value={importApiKey} onChange={e=>setImportApiKey(e.target.value)} placeholder={importSource === 'purpleair' ? 'PurpleAir API Key' : 'OpenAQ API Key'} />
          </div>
        </div>
        <div className="import-actions">
          <button className="btn" disabled={!schedule} onClick={async ()=>{
            if (!schedule) return;
            try {
              const updated = await updateScheduleParams(schedule.job_schedule_id, { api_key: importApiKey || ''});
              setSchedule(updated);
              alert('Saved API key to scheduler');
            } catch (e:any) {
              alert(e?.message || 'Failed to save');
            }
          }}>Save to Scheduler</button>
          <button className="btn primary" disabled={importRunning} onClick={async ()=>{
            setImportRunning(true); setImportResult(null);
            try {
              const res = await runImport(importSource, importTarget || undefined, false, importApiKey || undefined);
              if (res.ok) {
                setImportResult(res.data);
              } else if (res.status === 409) {
                setImportResult({ running: true, info: res.data?.detail || res.data });
              } else {
                setImportResult({ error: res.data || `Status ${res.status}` });
              }
            } catch (err:any) {
              setImportResult({ error: err?.message || String(err) });
            } finally { setImportRunning(false); }
          }}>{importRunning ? 'Running...' : 'Test run'}</button>
          <button className="btn subtle" onClick={async ()=>{ setImportResult(null); }}>Clear</button>
        </div>
      </div>

      {importResult && (
        <div className="panel">
          <h4>Result</h4>
          <pre className="code-block">{JSON.stringify(importResult, null, 2)}</pre>
          {importResult?.running && (
            <div className="row-flex gap-8">
              <div className="hint">A scheduled run appears to be in progress.</div>
              <button className="btn" onClick={async ()=>{
                if (!confirm('Cancel running job and run importer now?')) return;
                setImportRunning(true);
                try {
                  const res = await runImport(importSource, importTarget || undefined, true);
                  setImportResult(res.data);
                } catch (err:any) {
                  setImportResult({ error: err?.message || String(err) });
                } finally { setImportRunning(false); }
              }}>Cancel running and run</button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
