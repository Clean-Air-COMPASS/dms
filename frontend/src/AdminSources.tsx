import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { listExternalAPIs } from './api';
import AdminSourceForm from './AdminSourceForm';
import TestImportTab from './TestImportTab';
import SchedulesTab from './SchedulesTab';
import type { ExternalAPI } from './api';
import { authFetchJson } from './auth';

export default function AdminSources({ onClose, showTitle = true, forceSourceName, preselectExternalApiId }: { onClose: () => void; showTitle?: boolean; forceSourceName?: string | null; preselectExternalApiId?: number | null }) {
  const navigate = useNavigate();
  const [externalAPIs, setExternalAPIs] = useState<ExternalAPI[]>([]);
  const [selectedExternalAPI, setSelectedExternalAPI] = useState<ExternalAPI | null>(null);
  
  const [activeTab, setActiveTab] = useState<'modify' | 'import'>('modify');
  const location = useLocation();

  
  
  
  useEffect(() => {
    const hasFreshQuery = /(?:^|[?&])(fresh|refresh)=/i.test(location.search || '');
    (async () => {
      try {
        const apis = await listExternalAPIs((preselectExternalApiId || hasFreshQuery) ? { skipCache: true } : undefined);
        
        if (!apis || apis.length === 0) {
          const fallback = [
            { external_api_id: -1, name: 'OpenAQ', base_url: '', rate_limit_per_minute: null, rate_limit_per_hour: null, description: '' },
            { external_api_id: -2, name: 'PurpleAir', base_url: '', rate_limit_per_minute: null, rate_limit_per_hour: null, description: '' },
            { external_api_id: -3, name: 'AirGradient', base_url: '', rate_limit_per_minute: null, rate_limit_per_hour: null, description: '' },
          ];
          setExternalAPIs(fallback as ExternalAPI[]);
          setSelectedExternalAPI(prev => prev || (fallback[0] as ExternalAPI));
        } else {
          setExternalAPIs(apis);
          if (preselectExternalApiId) {
            
            
            try {
              const detailRaw = await authFetchJson(`/admin/external_apis/${preselectExternalApiId}`);
              const detailApi = detailRaw as ExternalAPI | null;
              setSelectedExternalAPI(detailApi || (apis.find(a => a.external_api_id === preselectExternalApiId) || (apis[0] || null)));
            } catch {
              const foundById = apis.find(a => a.external_api_id === preselectExternalApiId) || null;
              setSelectedExternalAPI(foundById || (apis[0] || null));
            }
          } else if (forceSourceName) {
            const found = apis.find(a => a.name === forceSourceName) || null;
            setSelectedExternalAPI(found || (apis[0] || null));
          } else {
            if (apis.length) {
              setSelectedExternalAPI(prev => prev ?? (apis[0] || null));
            }
          }
        }
      } catch {
        // swallow fetch errors
      }
    })();
  // Only re-run when these inputs change. Do NOT depend on `selectedExternalAPI` here
  // because that could prevent re-fetching when navigating between routes.
  }, [forceSourceName, preselectExternalApiId, location.search]);

  
  useEffect(() => {
    // Previously this effect populated schedule-related state. That logic has moved
    // into the Schedules and Test Import tab components; keep a noop effect so
    // selection changes still re-render consumers.
  }, [selectedExternalAPI]);

  
  return (
    <div className="admin-panel">
      {showTitle && (
        <div className="admin-header">
          <h2>Admin • Data Sources</h2>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      )}
      <div className="panel-body">
        <section className="admin-section">
          
          {!preselectExternalApiId && (
            <div className="row-flex source-row">
              <div className="form-field source-field">
                <div>
                  Select Data Source
                  {forceSourceName && (
                    <span className="hint" style={{marginLeft:8, fontSize:'0.9em', color:'#555'}}>Showing only "{forceSourceName}" sources</span>
                  )}
                </div>
                <select className="select-input" value={selectedExternalAPI?.external_api_id || ''} onChange={e=>{
                  const id = Number(e.target.value);
                  const found = externalAPIs.find(a=>a.external_api_id === id) || null;
                  setSelectedExternalAPI(found);
                }} title="Select external API source" aria-label="External API selector">
                  {(forceSourceName ? externalAPIs.filter(a => a.name === forceSourceName) : externalAPIs).map(a=> (
                    <option key={a.external_api_id} value={a.external_api_id}>{a.name} {a.external_api_id > 0 ? `(id ${a.external_api_id})` : ''}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          
          {selectedExternalAPI && (
            <div>
              <div className="tabs">
                <button className={`btn ${activeTab === 'modify' ? 'active' : ''}`} onClick={() => setActiveTab('modify')}>Modify Settings</button>
                <button className={`btn ${activeTab === 'import' ? 'active' : ''}`} onClick={() => setActiveTab('import')}>Import Settings</button>
              </div>

              <div className="tab-panel">
                {activeTab === 'modify' && (
                  <AdminSourceForm
                    selectedExternalAPI={selectedExternalAPI}
                    externalAPIs={externalAPIs}
                    onSaved={(updated) => {
                      setSelectedExternalAPI(updated);
                      setExternalAPIs(externalAPIs.map(a=>a.external_api_id===updated.external_api_id?updated:a));
                    }}
                    onCreated={async (created) => {
                      try {
                        const apis = await listExternalAPIs({ skipCache: true });
                        setExternalAPIs(apis);
                        const found = apis.find(a=>a.external_api_id===created?.external_api_id) || null;
                        setSelectedExternalAPI(found);
                      } catch {
                        // ignore
                      }
                    }}
                    onDeleted={() => navigate(`/admin/sources?fresh=${Date.now()}`)}
                  />
                )}

                {activeTab === 'import' && (
                  <div>
                    <SchedulesTab selectedExternalAPI={selectedExternalAPI} />
                    <TestImportTab selectedExternalAPI={selectedExternalAPI} />
                  </div>
                )}
              </div>
            </div>
          )}
        </section>

        
      </div>
    </div>
  );
}
