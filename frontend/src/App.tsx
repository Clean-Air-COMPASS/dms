
import { useEffect, useState } from 'react';
import { Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import MapLibreMap from './MapLibreMap';
import AdminQCRules from './AdminQCRules';
import AdminSourcesList from './AdminSourcesList';
import AdminSourceDetail from './AdminSourceDetail';
import AdminEventLog from './AdminEventLog';
import AdminDevicesList from './AdminDevicesList';
import AdminDeviceEditor from './AdminDeviceEditor';
import AdminDeviceNew from './AdminDeviceNew';
import AdminDeviceNewOpenAQ from './AdminDeviceNewOpenAQ';
import AdminUsersList from './AdminUsersList';
import AdminUserDetail from './AdminUserDetail';
import AdminUserNew from './AdminUserNew';
import AdminHome from './AdminHome';
import AdminCsvUpload from './AdminCsvUpload';
import AdminSystemPreferences from './AdminSystemPreferences';
import { fetchJson, listPublicDataSources, type PublicDataSource } from './api';
import Analytics from './Analytics';
import LoadingSplash from './LoadingSplash';
import DateTimeRangePicker from './components/DateTimeRangePicker';
import QuickDownload from './components/QuickDownload';
import LandingPage from './LandingPage';
import LocationSearch from './LocationSearch';
import LoginPage from './LoginPage';
import UserMenu from './components/UserMenu';
import { RequireAuth, RequireScope } from './auth';
import SetupWizard from './SetupWizard';
import { API_BASE } from './apiBase';


function App() {
  const location = useLocation();

  
  const [isCheckingSetup, setIsCheckingSetup] = useState<boolean>(true);
  const [isSetupRequired, setIsSetupRequired] = useState<boolean>(false);

  type ParamItem = { code: string; display_name: string; unit_symbol?: string | null };
  const [parameters, setParameters] = useState<ParamItem[]>([]);
  type ResolutionItem = { code: string; display_name: string };
  const [resolutions, setResolutions] = useState<ResolutionItem[]>([]);
  const [publicDataSources, setPublicDataSources] = useState<PublicDataSource[]>([]);
  type AggregationRuleItem = {
    parameter_code: string;
    aggregation_code: string;
    rounding_method?: string | null;
    rounding_precision?: number | null;
    truncation_method?: string | null;
    truncation_precision?: number | null;
  };
  const [aggregationRules, setAggregationRules] = useState<AggregationRuleItem[]>([]);
  
  type AggregationRollup = {
    parameter_code: string;
    from_period_code: string;
    from_period_display: string;
    to_period_code: string;
    to_period_display: string;
  };
  const [aggregationRollups, setAggregationRollups] = useState<AggregationRollup[]>([]);
  const [timeResolution, setTimeResolution] = useState<string>(() => {
    const sp = new URLSearchParams(window.location.search);
    return (sp.get('time_resolution') || '') as string;
  });
  
  const [sourceFilter, setSourceFilter] = useState<string>(() => {
    const sp = new URLSearchParams(window.location.search);
    return sp.get('source') || '';
  });
  const [initialLoading, setInitialLoading] = useState<boolean>(true);
  const [initialError, setInitialError] = useState<string | null>(null);
  const [initialKey, setInitialKey] = useState<number>(0);
  const [parameter, setParameter] = useState<string>('');
  const [mode, setMode] = useState<'pollutants' | 'devices'>(() => {
    const sp = new URLSearchParams(window.location.search);
    const m = (sp.get('mode') || '').toLowerCase();
    return m === 'pollutants' ? 'pollutants' : 'devices';
  });
  const [fitTrigger, setFitTrigger] = useState<number>(0);
  const [resetTrigger, setResetTrigger] = useState<number>(0);
  
  const [disableAutoFit, setDisableAutoFit] = useState<boolean>(false);
  
  const [flyToCoords, setFlyToCoords] = useState<{ lat: number; lng: number; zoom: number } | null>(null);
  const [recency, setRecency] = useState<'all' | '24h' | '1h' | 'custom'>(() => {
    const sp = new URLSearchParams(window.location.search);
    const r = (sp.get('recency') || '').toLowerCase();
    
    return r === 'custom' ? 'custom' : r === '1h' ? '1h' : r === '24h' ? '24h' : '24h';
  });
  
  const [customStart, setCustomStart] = useState<string | ''>(() => {
    const sp = new URLSearchParams(window.location.search);
    
    return (sp.get('start') || sp.get('time_start') || '') as string;
  });
  const [customEnd, setCustomEnd] = useState<string | ''>(() => {
    const sp = new URLSearchParams(window.location.search);
    return (sp.get('until') || sp.get('time_end') || '') as string;
  });
  const [useCustomRange, setUseCustomRange] = useState<boolean>(() => {
    const sp = new URLSearchParams(window.location.search);
    return !!(sp.get('start') || sp.get('until') || sp.get('time_start') || sp.get('time_end'));
  });
  const [showRangePicker, setShowRangePicker] = useState<boolean>(false);
  

  
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${API_BASE}/setup/status`);
        if (resp.ok) {
          const data = await resp.json();
          if (!cancelled) {
            setIsSetupRequired(data.is_setup_required === true);
          }
        }
      } catch {
        // If we can't check setup status, assume setup is not required
        // (API might not be running yet, or setup endpoint doesn't exist)
      } finally {
        if (!cancelled) {
          setIsCheckingSetup(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  
  const handleSetupComplete = () => {
    setIsSetupRequired(false);
    
    window.location.reload();
  };

  
  
  
  
  
  
  
  
  useEffect(() => {
    
    if (isCheckingSetup || isSetupRequired) return;
    
    
    let cancelled = false;
    (async () => {
      setInitialLoading(true);
      setInitialError(null);
      try {
        const [items, version, aggs, rules, rollups, sources] = await Promise.all([
          fetchJson<ParamItem[]>('/parameters'),
          fetchJson<Record<string, any>>('/version'),
          fetchJson<{ code: string; display_name: string }[]>('/aggregation_periods'),
          fetchJson<AggregationRuleItem[]>('/parameter_aggregation_rules'),
          fetchJson<AggregationRollup[]>('/aggregation_rollups'),
          listPublicDataSources({ skipCache: true }),
        ]);

        if (cancelled) return;
        setParameters(items || []);
        
        setResolutions(aggs || []);
        setAggregationRules(rules || []);
        setAggregationRollups(rollups || []);
        setPublicDataSources(sources || []);

        
        const sp = new URLSearchParams(window.location.search);
        const urlParam = (sp.get('parameter') || '').toLowerCase();
        const urlMode = (sp.get('mode') || '').toLowerCase();
        const preferred = urlParam && items.find((p) => p.code.toLowerCase() === urlParam);
        
        if (!sp.get('parameter') && !sp.get('sensor_id')) {
          if (urlMode === 'devices') {
            setParameter(preferred ? preferred.code : '');
          } else {
            if (preferred) {
              setParameter(preferred.code);
            } else {
              const pm25 = items.find((p) => p.code.toLowerCase() === 'pm25');
              setParameter(pm25 ? pm25.code : (items[0]?.code ?? ''));
            }
          }
        }

        
        void version;
        
        if (!sp.get('time_resolution')) {
          setTimeResolution('');
        }
        
        const start = (sp.get('start') || sp.get('time_start') || '').trim();
        const end = (sp.get('until') || sp.get('time_end') || '').trim();
        if (start) setCustomStart(start);
        if (end) setCustomEnd(end);
        if (start || end) {
          setUseCustomRange(true);
          setRecency('custom');
        }
      } catch (e: any) {
        if (!cancelled) setInitialError(String(e?.message || e));
      } finally {
        if (!cancelled) setInitialLoading(false);
      }
    })();
    return () => { cancelled = true; };
  // Re-run orchestrator when mode/parameter or retry key changes, or when setup completes.
  }, [initialKey, setAggregationRollups, isCheckingSetup, isSetupRequired]);

  
  useEffect(() => {
    if (location.pathname === '/') {
      document.title = 'AQ Data Platform – Clean Air COMPASS';
    } else if (location.pathname.startsWith('/admin')) {
      document.title = 'AQ Platform – Admin';
    } else if (location.pathname.startsWith('/analytics')) {
      document.title = 'AQ Platform – Analytics';
    } else if (location.pathname.startsWith('/map')) {
      if (mode === 'devices') {
        document.title = 'AQ Platform – Devices Map';
      } else if (parameter) {
        document.title = `AQ Platform – ${parameter.toUpperCase()} Map`;
      } else {
        document.title = 'AQ Platform – Map';
      }
    } else if (mode === 'devices') {
      document.title = 'AQ Platform – Devices';
    } else if (parameter) {
      document.title = `AQ Platform – Latest ${parameter.toUpperCase()}`;
    } else {
      document.title = 'AQ Platform – Measurements';
    }
    
    const sp = new URLSearchParams(window.location.search);
    sp.set('mode', mode);
    if (parameter) sp.set('parameter', parameter); else sp.delete('parameter');
    if (sourceFilter) sp.set('source', sourceFilter); else sp.delete('source');
    sp.set('recency', recency);
    if (timeResolution) sp.set('time_resolution', timeResolution); else sp.delete('time_resolution');
    if (useCustomRange && customStart) sp.set('start', customStart); else sp.delete('start');
    if (useCustomRange && customEnd) sp.set('until', customEnd); else sp.delete('until');
    const qs = sp.toString();
    const url = qs ? `?${qs}` : window.location.pathname;
    window.history.replaceState(null, '', url);
  }, [parameter, mode, sourceFilter, recency, location.pathname, timeResolution, customStart, customEnd, useCustomRange]);

  
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    if (parameter) sp.set('parameter', parameter); else sp.delete('parameter');
    sp.set('mode', mode);
    if (sourceFilter) sp.set('source', sourceFilter); else sp.delete('source');
    sp.set('recency', recency);
    if (timeResolution) sp.set('time_resolution', timeResolution); else sp.delete('time_resolution');
    if (useCustomRange && customStart) sp.set('start', customStart); else sp.delete('start');
    if (useCustomRange && customEnd) sp.set('until', customEnd); else sp.delete('until');
    const qs = sp.toString();
    const url = qs ? `?${qs}` : window.location.pathname;
    window.history.replaceState(null, '', url);
    
    setFitTrigger((x) => x + 1);
  }, [parameter, mode, sourceFilter, recency, timeResolution, customStart, customEnd, useCustomRange]);

  
  
  
  const visibleResolutions = ((): { code: string; display_name: string }[] => {
    if (!parameter) return resolutions;
    const paramCode = parameter.toString().toLowerCase();
    const codes = new Set<string>();
    for (const r of aggregationRules) {
      if (!r || !r.parameter_code || !r.aggregation_code) continue;
      if (r.parameter_code.toLowerCase() === paramCode) codes.add(r.aggregation_code.toString().toLowerCase());
    }
    
    for (const rollup of aggregationRollups) {
      if (!rollup || !rollup.parameter_code || !rollup.to_period_code) continue;
      if (rollup.parameter_code.toLowerCase() === paramCode) {
        codes.add(rollup.to_period_code.toLowerCase());
      }
    }
    
    if (codes.size === 0) return resolutions;
    const filtered = resolutions.filter((res) => codes.has((res.code || '').toString().toLowerCase()));
    return filtered.length > 0 ? filtered : resolutions;
  })();

  useEffect(() => {
    if (initialLoading) return;
    if (!timeResolution) return; 
    const found = visibleResolutions.find((r) => (r.code || '').toString() === timeResolution);
    if (!found) {
      
      
      setTimeResolution(visibleResolutions[0]?.code ?? '');
    }
  }, [visibleResolutions, timeResolution, initialLoading]);

  

  const MapPage = () => (
    <div className="app-root">
      
      <div className="overlay-controls">
        <Link to="/map" className="overlay-title" style={{ textDecoration: 'none', color: 'inherit' }}>
          COMPASS
        </Link>
        <LocationSearch
          onLocationSelect={(lat, lng, zoom) => {
            
            setDisableAutoFit(true);
            setFlyToCoords({ lat, lng, zoom });
          }}
        />
        <div className="row-flex">
          <div role="tablist" aria-label="Data layer" className="tablist">
            <button
              role="tab"
              onClick={() => setMode('devices')}
              className={`tab ${mode === 'devices' ? 'active' : ''}`}
            >
              Devices
            </button>
            <button
              role="tab"
              onClick={() => setMode('pollutants')}
              className={`tab ${mode === 'pollutants' ? 'active' : ''}`}
            >
              Measurements
            </button>
          </div>
        </div>
        <label className="form-label">
          <span className="sr-only">Parameter</span>
          <select
            aria-label="Parameter"
            value={parameter}
            onChange={(e) => setParameter(e.target.value)}
            className="select-input"
            disabled={initialLoading}
          >
            <option value="">All Parameters</option>
            {parameters.map((p) => (
              <option key={p.code} value={p.code}>
                {p.display_name || p.code.toUpperCase()}
              </option>
            ))}
          </select>
          {initialLoading ? (
            <span className="text-sm text-slate-500 ml-2">Loading parameters…</span>
          ) : parameters.length === 0 ? (
            <span className="text-sm text-red-500 ml-2">No parameters</span>
          ) : null}
        </label>
        <label className="form-label">
          <span className="sr-only">Time resolution</span>
          <select
            aria-label="Time resolution"
            value={timeResolution}
            onChange={(e) => setTimeResolution(e.target.value)}
            className="select-input"
            disabled={initialLoading}
          >
            <option value="">All Time Resolutions</option>
            {visibleResolutions.map((r) => (
              <option key={r.code} value={r.code}>{r.display_name}</option>
            ))}
            
          </select>
          {initialLoading ? (
            <span className="text-sm text-slate-500 ml-2">Loading…</span>
          ) : resolutions.length === 0 ? (
            <span className="text-sm text-red-500 ml-2">No resolutions</span>
          ) : null}
        </label>
        <label className="form-label">
          <span className="sr-only">Source</span>
          <select
            aria-label="Data source filter"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="select-input"
            disabled={initialLoading}
          >
            <option value="">All Sources</option>
            {publicDataSources.map((source) => (
              <option key={source.filter_value} value={source.filter_value}>
                {source.name}
              </option>
            ))}
          </select>
        </label>
        
        <div className="form-label" role="group" aria-label="Time window">
          <label className="sr-only" htmlFor="time-window-select">Time window</label>
          <select
            id="time-window-select"
            aria-label="Time window presets"
            value={recency}
            onChange={(e) => {
              const val = e.target.value as 'all' | '24h' | '1h' | 'custom';
              setRecency(val);
              if (val === 'all') {
                setCustomStart('');
                setCustomEnd('');
                setUseCustomRange(false);
              } else if (val === 'custom') {
                
                setUseCustomRange(true);
                setShowRangePicker(true);
              } else {
                const now = new Date();
                const start = new Date(now.getTime() - (val === '1h' ? 1 : 24) * 60 * 60 * 1000);
                setCustomStart(start.toISOString());
                setCustomEnd(now.toISOString());
                
                setUseCustomRange(false);
              }
            }}
            className="select-input"
          >
            <option value="all">All time</option>
            <option value="24h">Last 24 hours</option>
            <option value="1h">Last 1 hour</option>
            <option value="custom">Custom</option>
          </select>
          {useCustomRange && customStart && (
            <span className="custom-range-summary" aria-live="polite">
              {new Date(customStart).toLocaleString()} – {customEnd ? new Date(customEnd).toLocaleString() : 'now'}
            </span>
          )}
          <DateTimeRangePicker
            open={showRangePicker}
            startIso={customStart}
            endIso={customEnd}
            onClose={() => setShowRangePicker(false)}
            onClear={() => { setCustomStart(''); setCustomEnd(''); setUseCustomRange(false); setShowRangePicker(false); setRecency('24h'); }}
            onApply={(s, e) => {
              setCustomStart(s);
              setCustomEnd(e);
              setUseCustomRange(true);
              setRecency('custom');
              setShowRangePicker(false);
              setFitTrigger((x) => x + 1);
            }}
          />
        </div>
        <button
          className="btn"
          aria-label="Open custom date range picker"
          title="Custom date range"
          onClick={() => setShowRangePicker((s) => !s)}
        >📅</button>
        <button
          onClick={() => setResetTrigger((x) => x + 1)}
          className="btn"
          title="Reset view to your location"
        >
          Reset view
        </button>
        <QuickDownload
          parameter={parameter}
          aggregation={timeResolution}
          startIso={(useCustomRange && customStart) ? customStart : null}
          endIso={(useCustomRange && customEnd) ? customEnd : null}
          loading={initialLoading}
          showIcon={false}
        />
        <Link to="/analytics" className="btn" title="Analytics">Analytics</Link>
        <Link to="/admin" className="btn" title="Open admin QC rules">Admin</Link>
        <UserMenu />
      </div>

      
      <div className="map-wrapper">
        <MapLibreMap
          parameter={parameter}
          mode={mode}
          fitTrigger={fitTrigger}
          resetTrigger={resetTrigger}
          flyToCoords={flyToCoords}
          disableAutoFit={disableAutoFit}
          recency={recency}
          timeResolution={timeResolution}
          aggregationRules={aggregationRules}
          aggregationRollups={aggregationRollups}
          customStartIso={(useCustomRange && customStart) ? customStart : null}
          customEndIso={(useCustomRange && customEnd) ? customEnd : null}
          sourceFilter={sourceFilter}
        />
      </div>
    </div>
  );

  
  if (isCheckingSetup) {
    return <LoadingSplash />;
  }

  
  if (isSetupRequired) {
    return <SetupWizard onSetupComplete={handleSetupComplete} />;
  }

  
  if (initialLoading) {
    return <LoadingSplash />;
  }
  if (initialError) {
    return (
      <div className="min-h-screen flex items-center justify-center flex-col gap-4">
        <div className="text-red-600 font-semibold">Failed to load initial data</div>
        <div className="text-sm text-slate-600">{initialError}</div>
        <div>
          <button
            onClick={() => { setInitialKey((k) => k + 1); }}
            className="btn"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/map" element={<MapPage />} />
      <Route path="/analytics" element={<Analytics />} />
      <Route path="/admin" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminHome />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/qc" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminQCRules />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/devices" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminDevicesList />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/devices/new" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminDeviceNew />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/devices/new/openaq" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminDeviceNewOpenAQ />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/devices/manual" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminDeviceEditor />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/devices/:deviceId/edit" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminDeviceEditor />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/sources" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminSourcesList />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/sources/:id" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminSourceDetail />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/events" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminEventLog />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/system-preferences" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminSystemPreferences />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/uploads/csv" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminCsvUpload />
          </RequireScope>
        </RequireAuth>
      } />
      
      <Route path="/admin/users" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminUsersList />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/users/new" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminUserNew />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/users/:userId" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminUserDetail />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="*" element={<Navigate to="/map" replace />} />
    </Routes>
  );
}

export default App;
