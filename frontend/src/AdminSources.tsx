import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { listExternalAPIs } from './api';
import AdminSourceForm from './AdminSourceForm';
import TestImportTab from './TestImportTab';
import SchedulesTab from './SchedulesTab';
import SourceMonitoring from './SourceMonitoring';
import SourceReadiness, { type ScheduleState } from './SourceReadiness';
import type { ExternalAPI } from './api';
import { authFetchJson } from './auth';

interface AdminSourcesProps {
  onClose: () => void;
  showTitle?: boolean;
  showSourceHeading?: boolean;
  forceSourceName?: string | null;
  preselectExternalApiId?: number | null;
  onSourceChange?: (source: ExternalAPI | null) => void;
}

export default function AdminSources({
  onClose, showTitle = true, showSourceHeading = true,
  forceSourceName, preselectExternalApiId, onSourceChange,
}: AdminSourcesProps) {
  const navigate = useNavigate();
  const [externalAPIs, setExternalAPIs] = useState<ExternalAPI[]>([]);
  const [selectedExternalAPI, setSelectedExternalAPI] = useState<ExternalAPI | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [scheduleState, setScheduleState] = useState<ScheduleState>('loading');
  const [monitoringLoadError, setMonitoringLoadError] = useState(false);
  

  const location = useLocation();

  
  
  
  useEffect(() => {
    const hasFreshQuery = /(?:^|[?&])(fresh|refresh)=/i.test(location.search || '');
    (async () => {
      setLoading(true);
      setLoadError(false);
      try {
        const apis = await listExternalAPIs((preselectExternalApiId || hasFreshQuery) ? { skipCache: true } : undefined);
        
        if (preselectExternalApiId) {
          setExternalAPIs(apis || []);
          let selected = apis?.find(api => api.external_api_id === preselectExternalApiId) || null;
          try {
            const detail = await authFetchJson<ExternalAPI>(`/admin/external_apis/${preselectExternalApiId}`);
            if (detail?.external_api_id === preselectExternalApiId) selected = detail;
          } catch {
            // Keep the matching list entry if the detail request is unavailable.
          }
          setSelectedExternalAPI(selected);
          if (!selected) setLoadError(true);
        } else if (!apis || apis.length === 0) {
          const fallback = [
            { external_api_id: -1, name: 'OpenAQ', base_url: '', description: '', enabled: false },
            { external_api_id: -2, name: 'PurpleAir', base_url: '', description: '', enabled: false },
            { external_api_id: -3, name: 'AirGradient', base_url: '', description: '', enabled: false },
          ];
          setExternalAPIs(fallback as ExternalAPI[]);
          setSelectedExternalAPI(prev => prev || (fallback[0] as ExternalAPI));
        } else {
          setExternalAPIs(apis);
          if (forceSourceName) {
            const found = apis.find(a => a.name === forceSourceName) || null;
            setSelectedExternalAPI(found || (apis[0] || null));
          } else {
            if (apis.length) {
              setSelectedExternalAPI(prev => prev ?? (apis[0] || null));
            }
          }
        }
      } catch {
        setLoadError(true);
      } finally {
        setLoading(false);
      }
    })();
  // Only re-run when these inputs change. Do NOT depend on `selectedExternalAPI` here
  // because that could prevent re-fetching when navigating between routes.
  }, [forceSourceName, preselectExternalApiId, location.search]);

  
  useEffect(() => {
    onSourceChange?.(loading || loadError ? null : selectedExternalAPI);
  }, [selectedExternalAPI, loading, loadError, onSourceChange]);

  async function refreshImportMonitoring() {
    setMonitoringLoadError(false);
    try {
      const apis = await listExternalAPIs({ skipCache: true });
      if (!apis.some(api => api.external_api_id === selectedExternalAPI?.external_api_id)) {
        throw new Error('Imported source is unavailable');
      }
      setExternalAPIs(apis);
      setSelectedExternalAPI(current =>
        apis.find(api => api.external_api_id === current?.external_api_id) || current,
      );
    } catch {
      // A previous Success must not masquerade as the just-completed result.
      setMonitoringLoadError(true);
    }
  }

  
  return (
    <div className="admin-panel">
      {showTitle && (
        <div className="admin-header">
          <h2><Trans ns="dataSources" i18nKey="adminSources.headings.adminDataSources" /></h2>
          <button className="btn" onClick={onClose}><Trans ns="common" i18nKey="actions.close" /></button>
        </div>
      )}
      <div className="panel-body">
        {loading && <div className="info-banner" role="status"><Trans ns="common" i18nKey="states.loading" /></div>}
        {loadError && <div className="error-banner" role="alert"><Trans ns="common" i18nKey="errors.loadDataSources" /></div>}
        <section className="admin-section">
          
          {!preselectExternalApiId && (
            <div className="row-flex source-row">
              <div className="form-field source-field">
                <div>
                  <Trans ns="dataSources" i18nKey="adminSources.text.selectDataSource" />{forceSourceName && (
                    <span className="hint" style={{marginLeft:8, fontSize:'0.9em', color:'#555'}}><Trans ns="dataSources" i18nKey="adminSources.text.showingOnly" />{forceSourceName}<Trans ns="dataSources" i18nKey="adminSources.text.sources" /></span>
                  )}
                </div>
                <select className="select-input" value={selectedExternalAPI?.external_api_id || ''} onChange={e=>{
                  const id = Number(e.target.value);
                  const found = externalAPIs.find(a=>a.external_api_id === id) || null;
                  setSelectedExternalAPI(found);
                  setMonitoringLoadError(false);
                }} title={i18n.t('dataSources:adminSources.tooltips.selectExternalApiSource')} aria-label={i18n.t('dataSources:adminSources.accessibility.externalApiSelector')}>
                  {(forceSourceName ? externalAPIs.filter(a => a.name === forceSourceName) : externalAPIs).map(a=> (
                    <option key={a.external_api_id} value={a.external_api_id}>{a.name} {a.external_api_id > 0 ? `(id ${a.external_api_id})` : ''}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          
          {selectedExternalAPI && (
            <div>
              {showSourceHeading && <h2>{selectedExternalAPI.name}</h2>}
              <SourceReadiness source={selectedExternalAPI} scheduleState={scheduleState} />
              <div className="source-workflow">
                <section id="source-configuration" tabIndex={-1} aria-labelledby="source-configuration-heading">
                  <h2 id="source-configuration-heading">{i18n.t('dataSources:workflow.configuration')}</h2>
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
                </section>
                <TestImportTab selectedExternalAPI={selectedExternalAPI} onImportCompleted={refreshImportMonitoring} />
                <SchedulesTab selectedExternalAPI={selectedExternalAPI} onStateChange={setScheduleState} />
                {monitoringLoadError
                  ? <div className="error-banner" role="alert"><Trans ns="common" i18nKey="errors.loadDataSources" /></div>
                  : <SourceMonitoring selectedExternalAPI={selectedExternalAPI} />}
              </div>
            </div>
          )}
        </section>

        
      </div>
    </div>
  );
}
