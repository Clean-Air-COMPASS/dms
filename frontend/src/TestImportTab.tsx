import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useRef, useState } from 'react';
import type { ExternalAPI } from './api';
import { runImport } from './api';
import { sourceReadinessKey } from './sourceReadinessPresentation';

export default function TestImportTab({ selectedExternalAPI, onImportCompleted } : {
  selectedExternalAPI: ExternalAPI | null;
  onImportCompleted?: () => Promise<void>;
}) {
  const [importRunning, setImportRunning] = useState(false);
  const runButtonRef = useRef<HTMLButtonElement>(null);
  const restoreRunFocus = useRef(false);
  useEffect(() => {
    if (!importRunning && restoreRunFocus.current) {
      if (document.activeElement === document.body) runButtonRef.current?.focus();
      restoreRunFocus.current = false;
    }
  }, [importRunning]);
  const importSource = selectedExternalAPI?.provider_code;
  const supportedImporter = importSource === 'openaq' || importSource === 'purpleair' || importSource === 'airgradient';
  const [importTarget, setImportTarget] = useState<string>('');
  const [importResult, setImportResult] = useState<any | null>(null);

  useEffect(() => {
    setImportTarget('');
    setImportResult(null);
  }, [selectedExternalAPI?.external_api_id]);

  if (!selectedExternalAPI) return null;

  const readiness = sourceReadinessKey(selectedExternalAPI);
  return (
    <section id="source-run-now" tabIndex={-1} className="admin-section" aria-labelledby="source-run-heading">
      <h2 id="source-run-heading"><Trans ns="admin" i18nKey="testImportTab.headings.testImportRun" /></h2>
      <p>{selectedExternalAPI.provider_code === 'demo' ? i18n.t('dataSources:workflow.demoAutomatic') : i18n.t('admin:testImportTab.text.liveImportExplanation')}</p>
      {!supportedImporter && <p role="note"><Trans ns="admin" i18nKey="testImportTab.text.unsupportedImporter" /></p>}
      {readiness !== 'ready' && <p id="source-run-blocker" className="muted" role="note">{i18n.t(`dataSources:workflow.${readiness}`)}</p>}
      <div className="import-card">
        {supportedImporter && <div className="import-fields">
          <div className="import-field">
            <div className="label"><Trans ns="admin" i18nKey="testImportTab.text.dataSource" /></div>
            <strong>{selectedExternalAPI.name}</strong>
          </div>
          <div className="import-field">
            <div className="label"><Trans ns="admin" i18nKey="testImportTab.text.sensorIdOptional" /></div>
            <input aria-label={i18n.t('admin:testImportTab.text.sensorIdOptional')} className="text-input" value={importTarget} onChange={e=>setImportTarget(e.target.value)} placeholder="e.g. 1620" />
          </div>
        </div>}
        <div className="import-actions">
          <button ref={runButtonRef} className="btn primary" aria-describedby={readiness !== 'ready' ? 'source-run-blocker' : undefined} disabled={importRunning || !selectedExternalAPI.is_runnable || readiness !== 'ready' || !supportedImporter} onClick={async ()=>{
            if (!supportedImporter) return;
            restoreRunFocus.current = document.activeElement === runButtonRef.current;
            setImportRunning(true); setImportResult(null);
            try {
              const res = await runImport(importSource, importTarget || undefined, false);
              if (res.ok) {
                setImportResult(res.data);
                await onImportCompleted?.();
              } else if (res.status === 409) {
                setImportResult({ running: true, info: res.data?.detail || res.data });
              } else {
                setImportResult({ error: res.data || i18n.t('admin:testImportTab.dynamic.status', { status: res.status }) });
              }
            } catch (err:any) {
              setImportResult({ error: err?.message || String(err) });
            } finally { setImportRunning(false); }
          }}>{importRunning ? i18n.t('admin:testImportTab.actions.running') : i18n.t('admin:testImportTab.actions.testRun')}</button>
          {supportedImporter && <button className="btn subtle" onClick={async ()=>{ setImportResult(null); }}><Trans ns="admin" i18nKey="testImportTab.actions.clear" /></button>}
        </div>
      </div>

      {importResult && (
        <div className="panel" role="status">
          <h3><Trans ns="admin" i18nKey="testImportTab.headings.result" /></h3>
          <pre className="code-block">{JSON.stringify(importResult, null, 2)}</pre>
          {importResult?.running && (
            <div className="row-flex gap-8">
              <div className="hint"><Trans ns="admin" i18nKey="testImportTab.text.scheduledRunAppearsProgress" /></div>
              <button className="btn" onClick={async ()=>{
                if (!supportedImporter) return;
                if (!confirm(i18n.t('admin:testImportTab.dialogs.cancelRunningJobRunImporterNow'))) return;
                setImportRunning(true);
                try {
                  const res = await runImport(importSource, importTarget || undefined, true);
                  setImportResult(res.data);
                  if (res.ok) await onImportCompleted?.();
                } catch (err:any) {
                  setImportResult({ error: err?.message || String(err) });
                } finally { setImportRunning(false); }
              }}><Trans ns="admin" i18nKey="testImportTab.actions.cancelRunningRun" /></button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
