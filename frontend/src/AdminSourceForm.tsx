import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { ExternalAPI } from './api';
import { updateExternalAPI, createExternalAPI, deleteExternalAPI } from './api';
import OpenAQFields from './OpenAQFields';
import PurpleAirFields from './PurpleAirFields';

export default function AdminSourceForm(props: { selectedExternalAPI: ExternalAPI | null; externalAPIs?: ExternalAPI[]; onSaved?: (api: ExternalAPI)=>void; onCreated?: (api: ExternalAPI)=>void; onDeleted?: ()=>void }) {
  const { selectedExternalAPI, onSaved, onCreated, onDeleted } = props;

  const [apiEditing, setApiEditing] = useState<{ base_url?: string; description?: string; api_key?: string }>({});
  const [apiKeyTouched, setApiKeyTouched] = useState(false);
  const [apiKeyError, setApiKeyError] = useState<string | null>(null);
  const [isActive, setIsActive] = useState(true);
  const [apiParamsText, setApiParamsText] = useState<string>('');
  const [purpleairLookback, setPurpleairLookback] = useState<number | undefined>(undefined);
  const [skipParamsSync, setSkipParamsSync] = useState(false);
  const syncTimerRef = ({} as { current: ReturnType<typeof setTimeout> | null });
  

  useEffect(() => {
    if (!selectedExternalAPI) {
      setApiEditing({});
      setApiKeyTouched(false);
      setApiKeyError(null);
      setIsActive(true);
      setPurpleairLookback(undefined);
      return;
    }
    setApiEditing({
      base_url: selectedExternalAPI.base_url || '',
      description: selectedExternalAPI.description || '',
      api_key: selectedExternalAPI.api_key || '',
    });
    setIsActive(selectedExternalAPI.is_active ?? true);
    
    if (!skipParamsSync && selectedExternalAPI.name !== 'PurpleAir') {
      try {
        setApiParamsText(selectedExternalAPI.params ? JSON.stringify(selectedExternalAPI.params, null, 2) : '{}');
      } catch {
        setApiParamsText('{}');
      }
    }
    
    if (selectedExternalAPI.name === 'PurpleAir') {
      try {
        const p = selectedExternalAPI.params || {};
        const v = p?.max_lookback_hours;
        setPurpleairLookback(v != null ? Number(v) : 24);
      } catch {
        setPurpleairLookback(24);
      }
    }
    setApiKeyTouched(false);
    setApiKeyError(null);
  // `skipParamsSync` intentionally excluded so recently-saved values are not overwritten
  // when the flag toggles; the early-return logic above handles that case.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedExternalAPI]);

  const handleValidatePurpleAirKey = async (key: string) => {
    try {
      const res = await fetch('https://api.purpleair.com/v1/keys', { headers: { 'X-API-Key': key } });
      if (res.status === 402) {
        const err = await res.json().catch(() => ({}));
        const desc = err.description || 'Payment Required';
        return { ok: false, msg: `PurpleAir API Error (402): ${desc}` };
      } else if (!res.ok) {
        return { ok: false, msg: 'PurpleAir API key validation failed (server returned error).' };
      }
      return { ok: true };
    } catch {
      return { ok: false, msg: 'PurpleAir API key validation failed (network/CORS error).' };
    }
  };

  if (!selectedExternalAPI) return null;
  const requiresApiKey = ['purpleair', 'airgradient'].includes((selectedExternalAPI?.name || '').toLowerCase());
  const requiredApiKeyMessage = requiresApiKey ? `API Key is required for ${selectedExternalAPI.name}` : null;

  return (
    <div className="admin-sources-form">
      {selectedExternalAPI.external_api_id > 0 && (
        <div className="card" style={{ marginBottom: 16, background: 'linear-gradient(135deg, #f8fbff 0%, #eef6ff 100%)', borderColor: '#cfe3fb' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <div>
              <div className="muted small" style={{ textTransform: 'uppercase', letterSpacing: '0.06em' }}>Associated Devices</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <strong style={{ fontSize: 32, lineHeight: 1 }}>{selectedExternalAPI.device_count ?? 0}</strong>
                <span className="muted">{(selectedExternalAPI.device_count ?? 0) === 1 ? 'device linked to this source' : 'devices linked to this source'}</span>
              </div>
            </div>
            <Link
              to={`/admin/devices?network=${encodeURIComponent(selectedExternalAPI.name)}&fresh=${Date.now()}`}
              className="btn btn-secondary"
            >
              View Devices
            </Link>
          </div>
        </div>
      )}

      <div className="form-field">
        <div>Base URL</div>
        <input className="text-input" value={apiEditing.base_url || ''} onChange={e=>setApiEditing({...apiEditing, base_url: e.target.value})} placeholder="https://api.example.com" />
      </div>

      

      <div className="form-field admin-extapi-desc">
        <div>Description</div>
        <input className="text-input" value={apiEditing.description || ''} onChange={e=>setApiEditing({...apiEditing, description: e.target.value})} placeholder="API description" />
      </div>

      
      {selectedExternalAPI?.name === 'OpenAQ' && (
        <OpenAQFields
          apiEditing={apiEditing}
          setApiEditing={setApiEditing}
          selectedExternalAPI={selectedExternalAPI}
          apiParamsText={apiParamsText}
          setApiParamsText={setApiParamsText}
        />
      )}
      {selectedExternalAPI?.name === 'PurpleAir' && (
        <>
          <PurpleAirFields />
          <div className="form-field">
            <div>
              Max lookback (hours)
              <span className="hint" style={{ marginLeft: 8, fontSize: '0.85em', color: '#666' }}>Limits importer history fetch window</span>
            </div>
            <input
              type="number"
              className="text-input"
              value={purpleairLookback ?? ''}
              onChange={e => setPurpleairLookback(e.target.value ? Number(e.target.value) : undefined)}
              min={1}
              max={168}
              step={1}
            />
          </div>
        </>
      )}

      <div className="form-field">
        <div>
          API Key
          {requiresApiKey && (
            <span className="required-indicator" aria-hidden style={{color:'#c00', marginLeft:6}}>*</span>
          )}
        </div>
        <input
          className={`text-input api-key-input ${apiKeyError ? 'input-invalid' : ''}`}
          value={apiEditing.api_key || ''}
          onChange={e=>{ setApiEditing({...apiEditing, api_key: e.target.value}); if (e.target.value) { setApiKeyError(null); } }}
          onBlur={async ()=>{ setApiKeyTouched(true); if (!apiEditing.api_key && requiresApiKey) setApiKeyError(requiredApiKeyMessage); }}
          placeholder="API Key"
          aria-required={requiresApiKey ? true : undefined}
          aria-invalid={apiKeyError ? true : undefined}
        />
        {apiKeyError && apiKeyTouched && (
          <div className="field-error" role="alert" style={{color:'#b00020', marginTop:6}}>{apiKeyError}</div>
        )}
      </div>

      <div className="form-field">
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
          />
          <span>Active</span>
        </label>
        <div className="muted" style={{ marginTop: 4 }}>
          Inactive data sources stay on existing devices but are hidden from new device source pickers.
        </div>
      </div>

        

      <div className="save-actions">
        <button className="btn btn-small primary" disabled={!(selectedExternalAPI && selectedExternalAPI.external_api_id > 0)} onClick={async ()=>{
          if (!selectedExternalAPI || selectedExternalAPI.external_api_id <= 0) return;

          if (requiresApiKey && !apiEditing.api_key) {
            setApiKeyTouched(true);
            setApiKeyError(requiredApiKeyMessage);
            return;
          }

          if (selectedExternalAPI.name === 'PurpleAir' && apiEditing.api_key) {
            const valid = await handleValidatePurpleAirKey(apiEditing.api_key);
            if (!valid.ok) {
              if (!confirm(`${valid.msg}\n\nSave anyway?`)) return;
            }
          }

          try {
            
            
            let paramsPayload: any = {};
            if (selectedExternalAPI.name === 'PurpleAir') {
              const existing = selectedExternalAPI.params || {};
              paramsPayload = { ...existing };
              if (purpleairLookback != null) paramsPayload.max_lookback_hours = Number(purpleairLookback);
            } else {
              try { paramsPayload = JSON.parse(apiParamsText || '{}'); } catch { paramsPayload = {}; }
            }

            const updated = await updateExternalAPI(selectedExternalAPI.external_api_id, {
              base_url: apiEditing.base_url || undefined,
              description: apiEditing.description || undefined,
              api_key: apiEditing.api_key || undefined,
              params: paramsPayload,
              is_active: isActive,
            });
            
            try {
              const p = updated.params;
              if (selectedExternalAPI.name !== 'PurpleAir') {
                try { setApiParamsText(p ? JSON.stringify(p, null, 2) : '{}'); } catch { setApiParamsText('{}'); }
              }
            } catch {
              // ignore UI sync errors
            }
            onSaved?.(updated);
            alert('Data Source updated');
          } catch (e:any) { alert(e?.message || 'Failed to update'); }
          finally {
            
            
            if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
            setSkipParamsSync(true);
            syncTimerRef.current = setTimeout(() => setSkipParamsSync(false), 1500);
          }
        }}>Save</button>

        {selectedExternalAPI && selectedExternalAPI.external_api_id <= 0 && (
          <div className="create-button-wrap">
            <button className="btn" onClick={async ()=>{
              if (!selectedExternalAPI) return;
              if (requiresApiKey) {
                if (!apiEditing.api_key) {
                  setApiKeyTouched(true);
                  setApiKeyError(requiredApiKeyMessage);
                  return;
                }
              }
              if (selectedExternalAPI.name === 'PurpleAir') {
                const valid = await handleValidatePurpleAirKey(apiEditing.api_key || '');
                if (!valid.ok) {
                  if (!confirm(`${valid.msg}\n\nCreate anyway?`)) return;
                }
              }

              try {
                let paramsPayload: any = {};
                if (selectedExternalAPI.name === 'PurpleAir') {
                  paramsPayload = {};
                  if (purpleairLookback != null) paramsPayload.max_lookback_hours = Number(purpleairLookback);
                } else {
                  try { paramsPayload = JSON.parse(apiParamsText || '{}'); } catch { paramsPayload = {}; }
                }

                const created = await createExternalAPI({
                  name: selectedExternalAPI.name,
                  base_url: apiEditing.base_url || undefined,
                  
                  description: apiEditing.description || undefined,
                  api_key: apiEditing.api_key || undefined,
                  params: paramsPayload,
                  is_active: isActive,
                });
                
                try {
                  const p = created.params;
                  if (selectedExternalAPI.name !== 'PurpleAir') {
                    try { setApiParamsText(p ? JSON.stringify(p, null, 2) : '{}'); } catch { setApiParamsText('{}'); }
                  }
                } catch { /* ignore UI sync errors */ }
                onCreated?.(created);
                alert('Created external API');
              } catch (e:any) { alert(e?.message || 'Failed to create'); }
                finally {
                  if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
                  setSkipParamsSync(true);
                  syncTimerRef.current = setTimeout(() => setSkipParamsSync(false), 1500);
                }
            }}>Create Source</button>
          </div>
        )}

        {selectedExternalAPI && selectedExternalAPI.external_api_id > 0 && (
          <button
            className="btn btn-danger"
            type="button"
            onClick={async () => {
              if (!selectedExternalAPI) return;
              if (!confirm(`Delete data source "${selectedExternalAPI.name}"?`)) return;
              try {
                await deleteExternalAPI(selectedExternalAPI.external_api_id);
                onDeleted?.();
              } catch (e: any) {
                alert(e?.message || 'Failed to delete data source');
              }
            }}
          >
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

