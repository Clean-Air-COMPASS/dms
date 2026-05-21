import { useEffect, useState } from 'react';
import { listQcPlugins, listQcRules, createLocalPlugin, deletePlugin, uploadPlugin } from './api';
import type { QCRule as QCRuleType, PluginInfo } from './api';
import QCRuleEditDrawer from './components/QCRuleEditDrawer';
import AdminPageLayout from './components/AdminPageLayout';
import { authFetchJson } from './auth';

type QCRule = QCRuleType;

type EffectiveResp = {
  check_code: string;
  display_name: string;
  long_description: string;
  context: { sensor_id?: number | null; parameter_id?: number | null; aggregate_code?: string };
  source: 'sensor' | 'parameter' | 'global' | 'default';
  threshold: number;
  rule: QCRule | null;
};

export default function AdminQCRules() {
  const [tab, setTab] = useState<'rules' | 'effective' | 'plugins'>('rules');
  const [rules, setRules] = useState<QCRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);

  
  const [newCheckCode, setNewCheckCode] = useState<string>('min_value');
  const [newSensorId, setNewSensorId] = useState<string>('');
  const [newParameterId, setNewParameterId] = useState<string>('');
  const [newAggregate, setNewAggregate] = useState<string>('');
  const [newParams, setNewParams] = useState<Record<string,string>>({});
  const [creating, setCreating] = useState(false);

  
  const [effSensorId, setEffSensorId] = useState<string>('');
  const [effParameterId, setEffParameterId] = useState<string>('');
  const [effAggregate, setEffAggregate] = useState<string>('1h');
  const [effective, setEffective] = useState<EffectiveResp | null>(null);
  const [effectiveError, setEffectiveError] = useState<string | null>(null);
  const [effectiveLoading, setEffectiveLoading] = useState(false);

  
  const [editing, setEditing] = useState<QCRule | null>(null);

  const scopeLabel = (r: QCRule) => {
    if (r.sensor_id != null) return `sensor:${r.sensor_id}`;
    if (r.parameter_id != null) return `parameter:${r.parameter_id}`;
    return 'global';
  };

  const loadRules = async () => {
    setLoading(true); setError(null);
    try {
  const data = await listQcRules();
      setRules(data);
    } catch (e:any) {
      setError(e?.message || 'Failed to load rules');
    } finally {
      setLoading(false);
    }
  };

  const loadPlugins = async () => {
    try {
  const data = await listQcPlugins();
      setPlugins(data);
      if (!data.find(p => p.name === newCheckCode) && data.length > 0) {
        setNewCheckCode(data[0].name);
      }
    } catch {
      // ignore, default to min_value
    }
  };

  useEffect(() => {
    loadRules();
    loadPlugins();
    // We intentionally run this once on mount. loadRules/loadPlugins are stable
    // side-effect functions; disabling exhaustive-deps avoids re-running.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleRule = async (r: QCRule, enable: boolean) => {
    try {
      const path = enable ? `/admin/qc/rules/${r.qc_rule_id}/enable` : `/admin/qc/rules/${r.qc_rule_id}/disable`;
      await authFetchJson(path, { method: 'POST' });
      await loadRules();
    } catch (e:any) {
      alert(e?.message || 'Failed to toggle rule');
    }
  };

  const createRule = async () => {
    setCreating(true);
    try {
      const payload: any = {
        check_code: newCheckCode,
        enabled: true,
      };
      if (newSensorId.trim()) payload.sensor_id = Number(newSensorId.trim());
      if (newParameterId.trim()) payload.parameter_id = Number(newParameterId.trim());
      if (newAggregate.trim()) payload.aggregate_code = newAggregate.trim();
      
      const plugin = plugins.find(p=>p.name===newCheckCode);
      if (plugin?.param_schema) {
        const params: Record<string, any> = {};
        for (const [k, spec] of Object.entries(plugin.param_schema)) {
          const raw = (newParams[k] ?? '').trim();
          if (raw === '') continue;
          const t = spec?.type || 'number';
          if (t === 'number' || t === 'integer') {
            const n = t === 'integer' ? parseInt(raw, 10) : Number(raw);
            if (!Number.isFinite(n)) {
              alert(`Invalid value for ${k}: must be a number`);
              setCreating(false);
              return;
            }
            params[k] = n;
          } else if (t === 'boolean') {
            params[k] = raw === 'true' || raw === '1';
          } else {
            params[k] = raw;
          }
        }
        if (Object.keys(params).length > 0) payload.params = params;
      }
      await authFetchJson('/admin/qc/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
  
  setNewSensorId(''); setNewParameterId(''); setNewAggregate(''); setNewParams({});
      await loadRules();
    } catch (e:any) {
      alert(e?.message || 'Failed to create rule');
    } finally {
      setCreating(false);
    }
  };

  const beginEdit = (r: QCRule) => {
    setEditing(r);
  };

  
  

  const deleteRule = async (r: QCRule) => {
    if (!confirm(`Delete rule ${r.qc_rule_id}?`)) return;
    try {
      await authFetchJson(`/admin/qc/rules/${r.qc_rule_id}`, { method: 'DELETE' });
      await loadRules();
    } catch (e:any) {
      alert(e?.message || 'Failed to delete rule');
    }
  };

  const runEffective = async () => {
    setEffectiveLoading(true); setEffectiveError(null);
    try {
      const params = new URLSearchParams();
      params.set('check_code', 'min_value');
      if (effSensorId.trim()) params.set('sensor_id', String(Number(effSensorId.trim())));
      if (effParameterId.trim()) params.set('parameter_id', String(Number(effParameterId.trim())));
      if (effAggregate.trim()) params.set('aggregate_code', effAggregate.trim());
      const data = await authFetchJson<EffectiveResp>(`/admin/qc/effective?${params.toString()}`);
      setEffective(data);
    } catch (e:any) {
      setEffectiveError(e?.message || 'Failed to resolve effective rule');
      setEffective(null);
    } finally {
      setEffectiveLoading(false);
    }
  };

  return (
    <AdminPageLayout
      title="QC Rules"
      description="Review and manage quality control rules that validate incoming measurements."
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'QC Rules' },
      ]}
      contentClassName="qc-rules-page"
    >
      <div className="card">
        <div className="tablist">
          <button className={`tab ${tab==='rules'?'active':''}`} onClick={()=>setTab('rules')}>Rules</button>
          <button className={`tab ${tab==='effective'?'active':''}`} onClick={()=>setTab('effective')}>Effective</button>
          <button className={`tab ${tab==='plugins'?'active':''}`} onClick={()=>{ setTab('plugins'); loadPlugins(); }}>Plugins</button>
        </div>

        {tab === 'rules' && (
          <div className="panel-body">
            <div className="row-flex gap-8 align-end flex-wrap">
              <div className="form-label">
                <div>Check</div>
                <select className="select-input" value={newCheckCode} onChange={e=>setNewCheckCode(e.target.value)} title="QC check plugin" aria-label="QC check plugin selector">
                  {(plugins.length ? plugins : [{ name:'min_value', display_name:'Minimum Value QC Check'}]).map(p => (
                    <option key={p.name} value={p.name}>{p.display_name || p.name}</option>
                ))}
              </select>
            </div>
            <div className="form-label">
              <div>Sensor ID (optional)</div>
              <input className="text-input" value={newSensorId} onChange={e=>setNewSensorId(e.target.value)} placeholder="e.g. 1620" />
            </div>
            <div className="form-label">
              <div>Parameter ID (optional)</div>
              <input className="text-input" value={newParameterId} onChange={e=>setNewParameterId(e.target.value)} placeholder="e.g. 1" />
            </div>
            <div className="form-label">
              <div>Aggregate (optional)</div>
              <input className="text-input" value={newAggregate} onChange={e=>setNewAggregate(e.target.value)} placeholder="1h" />
            </div>
            
            {(() => {
              const plugin = plugins.find(p=>p.name===newCheckCode);
              if (!plugin || !plugin.param_schema) return null;
              return Object.entries(plugin.param_schema).map(([key, spec]) => {
                return (
                  <div className="form-label" key={key}>
                    <div>{spec.label || key}</div>
                    <input
                      className="text-input"
                      value={newParams[key] ?? ''}
                      onChange={e=>setNewParams(prev=>({ ...prev, [key]: e.target.value }))}
                      placeholder={spec.help || ''}
                    />
                  </div>
                );
              });
            })()}
            <button className="btn" onClick={createRule} disabled={creating}>Create rule</button>
            <button className="btn" onClick={loadRules} disabled={loading}>Refresh</button>
          </div>

          {plugins.length > 0 && (
            <div className="hint">
              {(plugins.find(p=>p.name===newCheckCode)?.long_description) || ''}
            </div>
          )}

          {error && <div className="error-text">{error}</div>}
          <div className="table-wrap">
            <table className="simple-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Check</th>
                  <th>Scope</th>
                  <th>Aggregate</th>
                  <th>Enabled</th>
                  <th>Params</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {rules.map(r => (
                  <tr key={r.qc_rule_id}>
                    <td>{r.qc_rule_id}</td>
                    <td>{r.check_code}</td>
                    <td>{scopeLabel(r)}</td>
                    <td>{r.aggregate_code || ''}</td>
                    <td>{r.enabled ? 'true':'false'}</td>
                    <td>
                      {r.params ? JSON.stringify(r.params) : ''}
                      {r.draft_params ? <div className="hint">draft: {JSON.stringify(r.draft_params)}</div> : null}
                      {typeof r.version !== 'undefined' && r.version !== null ? <div className="subtle">v{r.version} {r.state ? `• ${r.state}`:''}</div> : null}
                    </td>
                    <td className="table-actions">
                      {r.enabled ? (
                        <button className="btn" onClick={()=>toggleRule(r, false)}>Disable</button>
                      ) : (
                        <button className="btn" onClick={()=>toggleRule(r, true)}>Enable</button>
                      )}
                      <button className="btn small" onClick={()=>beginEdit(r)}>View</button>
                      <button className="btn" onClick={()=>deleteRule(r)}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {editing && (
            <QCRuleEditDrawer
              rule={editing}
              plugins={plugins}
              onClose={()=>setEditing(null)}
              onChanged={async ()=>{ await loadRules(); }}
            />
          )}
        </div>
      )}

      {tab === 'effective' && (
        <div className="panel-body">
          <div className="row-flex gap-8 align-end flex-wrap">
            <div className="form-label">
              <div>Sensor ID (optional)</div>
              <input className="text-input" value={effSensorId} onChange={e=>setEffSensorId(e.target.value)} placeholder="e.g. 1620" />
            </div>
            <div className="form-label">
              <div>Parameter ID (optional)</div>
              <input className="text-input" value={effParameterId} onChange={e=>setEffParameterId(e.target.value)} placeholder="e.g. 1" />
            </div>
            <div className="form-label">
              <div>Aggregate</div>
              <input className="text-input" value={effAggregate} onChange={e=>setEffAggregate(e.target.value)} placeholder="1h" />
            </div>
            <button className="btn btn-primary" onClick={runEffective} disabled={effectiveLoading}>Resolve</button>
          </div>
          {effectiveError && <div className="error-text">{effectiveError}</div>}
          {effective && (
            <div className="qc-effective-meta">
              <h3>{effective.display_name}</h3>
              <div className="qc-effective-desc">{effective.long_description}</div>
              <pre className="code-block">{JSON.stringify(effective, null, 2)}</pre>
            </div>
          )}
        </div>
      )}

      {tab === 'plugins' && (
        <div className="panel-body">
          <h3>Plugins</h3>
          <PluginManager plugins={plugins} onReload={async ()=>{ await loadPlugins(); }} />
        </div>
      )}
      </div>
    </AdminPageLayout>
  );
}

function PluginManager({ plugins, onReload }: { plugins: any[]; onReload: () => void | Promise<void> }) {
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const doCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true); setError(null);
    try {
      await createLocalPlugin(newName.trim(), newDesc.trim() || undefined);
      setNewName(''); setNewDesc('');
      await onReload();
    } catch (e:any) {
      setError(e?.message || 'Failed to create plugin');
    } finally { setCreating(false); }
  };

  const doDelete = async (p: any) => {
    if (!p.deletable) return;
    if (!confirm(`Remove plugin ${p.name}?`)) return;
    try {
      await deletePlugin(p.name);
      await onReload();
    } catch (e:any) {
      alert(e?.message || 'Failed to delete plugin');
    }
  };

  const doUpload = async () => {
    if (!file || uploading) return;
    setUploading(true); setError(null); setMessage(null);
    try {
      await uploadPlugin(file, overwrite);
      setMessage(`Uploaded plugin ${file.name}`);
      setFile(null);
      const inputEl = document.getElementById('plugin-upload-input') as HTMLInputElement | null;
      if (inputEl) inputEl.value = '';
      await onReload();
    } catch (e:any) {
      setError(e?.message || 'Failed to upload plugin');
    } finally { setUploading(false); }
  };

  return (
    <div className="panel">
      <div className="row-flex gap-12 flex-wrap align-end">
        <div className="form-label">
          <div>Name</div>
          <input className="text-input" value={newName} onChange={e=>setNewName(e.target.value)} placeholder="plugin name" />
        </div>
        <div className="form-label">
          <div>Description</div>
          <input className="text-input" value={newDesc} onChange={e=>setNewDesc(e.target.value)} placeholder="description" />
        </div>
        <button className="btn" disabled={creating || !newName.trim()} onClick={doCreate}>Create Local Plugin</button>
        <button className="btn" onClick={()=>onReload()}>Refresh</button>
        <label className="form-label" htmlFor="plugin-upload-input">
          <div>Upload .py</div>
          <input
            id="plugin-upload-input"
            type="file"
            accept=".py"
            title="Select a Python plugin file to upload"
            aria-label="Upload Python plugin file"
            placeholder="Select file"
            onChange={e=>setFile(e.target.files?.[0]||null)}
          />
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={overwrite} onChange={e=>setOverwrite(e.target.checked)} /> Overwrite existing
        </label>
        <button className="btn" disabled={!file || uploading} onClick={doUpload}>{uploading ? 'Uploading…' : 'Upload Plugin'}</button>
      </div>
      {error && <div className="error-text">{error}</div>}
      {message && <div className="success-text">{message}</div>}
      <div className="table-wrap">
        <table className="simple-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Origin</th>
              <th>Rules</th>
              <th>Description</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {plugins.map((p:any) => (
              <tr key={p.name}>
                <td>{p.name}</td>
                <td>{p.origin || 'n/a'}</td>
                <td>{p.rules_count ?? ''}</td>
                <td>{p.description || p.long_description || ''}</td>
                <td>
                  {p.deletable && (
                    <button className="btn" onClick={()=>doDelete(p)}>Remove</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
