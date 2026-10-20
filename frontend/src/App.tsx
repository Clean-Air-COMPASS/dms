import { Trans, useTranslation } from 'react-i18next';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import MapLibreMap from './MapLibreMap';
import MapSurface from './components/MapSurface';
import { useNarrowMap } from './useNarrowMap';
import AdminQcOverview from './qc/AdminQcOverview';
import AdminQcParameterDetail from './qc/AdminQcParameterDetail';
import AdminQcSourcePolicy from './qc/AdminQcSourcePolicy';
import AdminQcExtensions from './qc/AdminQcExtensions';
import AdminQcSensorSearch from './qc/AdminQcSensorSearch';
import AdminQcSensorPolicy from './qc/AdminQcSensorPolicy';
import AdminSourcesList from './AdminSourcesList';
import AdminSourceDetail from './AdminSourceDetail';
import AdminEventLog from './AdminEventLog';
import AdminDevicesList from './AdminDevicesList';
import AdminDeviceEditor from './AdminDeviceEditor';
import AdminDeviceNew from './AdminDeviceNew';
import AdminDeviceNewOpenAQ from './AdminDeviceNewOpenAQ';
import AdminDeviceNewAirGradient from './AdminDeviceNewAirGradient';
import AdminUsersList from './AdminUsersList';
import AdminUserDetail from './AdminUserDetail';
import AdminUserNew from './AdminUserNew';
import AdminHome from './AdminHome';
import AdminCsvUpload from './AdminCsvUpload';
import AdminSystemPreferences from './AdminSystemPreferences';
import AdminEmail from './email/AdminEmail';
import { fetchJson, listPublicDataSources, type PublicDataSource } from './api';
import Analytics from './Analytics';
import LoadingSplash from './LoadingSplash';
import QuickDownload from './components/QuickDownload';
import LandingPage from './LandingPage';
import LocationSearch from './LocationSearch';
import LoginPage from './LoginPage';
import ResetPasswordPage from './ResetPasswordPage';
import MyAccount from './account/MyAccount';
import UserMenu from './components/UserMenu';
import { RequireAuth, RequireScope, useAuth } from './auth';
import { getAggregationDisplayLabel } from './aqi';
import { getParameterDisplayName } from './parameterPresentation';
import SetupWizard from './SetupWizard';
import StartupStatus from './StartupStatus';
import { API_BASE } from './apiBase';
import i18n, {
  normalizeBrowserLanguage,
  readAnonymousLanguagePreference,
  resolveAnonymousLanguage,
  isSupportedLanguageCode,
  type SupportedLanguageCode,
} from './i18n';
import {
  findAirQualityIndexStandard,
  listAirQualityIndexStandards,
  type AirQualityIndexProductMetadata,
  type AirQualityIndexStandardMetadata,
  type MapDisplayMode,
} from './airQualityIndex';
import {
  EEA_EUROPEAN_STANDARD_CODE,
  getAirQualityIndexProductLabel,
  getAirQualityIndexStandardLabel,
} from './airQualityIndexPresentation';
import {
  createRequestedMapSelection,
  findAirQualityIndexProduct,
  findStandardForProduct,
  listValidAggregationPeriods,
  normalizeSelectedDataProduct,
  type MapSelectionMetadata,
  type RequestedMapSelection,
  type SelectedDataProduct,
} from './mapLayerSelection';
import { readMapViewport, withoutMapQueryState, type MapViewport } from './mapUrlState';
import type { MeasurementAggregationCapability } from './measurementAggregations';

const US_EPA_STANDARD_CODE = 'us_epa';
const PHILIPPINES_DENR_STANDARD_CODE = 'philippines_denr';
const READINESS_RETRY_DELAYS_MS = [1000, 2000, 4000, 5000] as const;
const READINESS_FAILURE_AFTER_MS = 20_000;
const STARTUP_REQUEST_TIMEOUT_MS = 8000;


async function fetchStartupResponse(path: string): Promise<Response> {
  const abortController = new AbortController();
  const timeout = window.setTimeout(
    () => abortController.abort(),
    STARTUP_REQUEST_TIMEOUT_MS,
  );
  try {
    return await fetch(`${API_BASE}${path}`, { signal: abortController.signal });
  } finally {
    window.clearTimeout(timeout);
  }
}


function App() {
  const narrowMap = useNarrowMap();
  const [mapFiltersExpanded, setMapFiltersExpanded] = useState(false);
  const mapToolbarRef = useRef<HTMLDivElement>(null);
  useTranslation();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const location = useLocation();
  const mapSearch = location.pathname === '/map' ? location.search : '';
  const lastMapViewportRef = useRef<MapViewport | null>(null);
  const rememberMapViewport = useCallback((viewport: MapViewport) => {
    lastMapViewportRef.current = viewport;
  }, []);
  const [hydratedMapLocation, setHydratedMapLocation] = useState<typeof location | null>(null);
  const [initialSelectionRequest] = useState<RequestedMapSelection>(() => (
    createRequestedMapSelection(mapSearch)
  ));

  
  const [isCheckingSetup, setIsCheckingSetup] = useState<boolean>(true);
  const [hasPersistentStartupFailure, setHasPersistentStartupFailure] = useState<boolean>(false);
  const [startupRetryKey, setStartupRetryKey] = useState<number>(0);
  const [isSetupRequired, setIsSetupRequired] = useState<boolean>(false);
  const [hasSetupUsers, setHasSetupUsers] = useState<boolean>(false);
  const [setupDefaultLanguageCode, setSetupDefaultLanguageCode] = useState<SupportedLanguageCode | null>(null);

  type ParamItem = { code: string; display_name: string; unit_symbol?: string | null };
  const [parameters, setParameters] = useState<ParamItem[]>([]);
  type ResolutionItem = { code: string; display_name: string };
  const [resolutions, setResolutions] = useState<ResolutionItem[]>([]);
  const [publicDataSources, setPublicDataSources] = useState<PublicDataSource[]>([]);
  const [airQualityIndexStandards, setAirQualityIndexStandards] = useState<AirQualityIndexStandardMetadata[]>([]);
  const [airQualityIndexStandardsError, setAirQualityIndexStandardsError] = useState<string | null>(null);
  const [measurementAggregationCapabilities, setMeasurementAggregationCapabilities] = useState<MeasurementAggregationCapability[]>([]);
  const loadedCapabilitySourceRef = useRef<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string>(() => {
    const sp = new URLSearchParams(mapSearch);
    return (sp.get('source') || '').trim().toLowerCase();
  });
  const initialSourceFilterRef = useRef(sourceFilter);
  const [initialLoading, setInitialLoading] = useState<boolean>(true);
  const [initialError, setInitialError] = useState<string | null>(null);
  const [initialKey, setInitialKey] = useState<number>(0);
  const [selection, setSelection] = useState<SelectedDataProduct>({
    layer: initialSelectionRequest.layer,
    parameter_code: initialSelectionRequest.parameter_code,
    aggregation_period: initialSelectionRequest.aggregation_period,
    air_quality_index_product_code: initialSelectionRequest.air_quality_index_product_code,
  });
  const [selectionUnavailableReason, setSelectionUnavailableReason] = useState<string | null>(null);
  const [resetTrigger, setResetTrigger] = useState<number>(0);
  
  const [disableAutoFit, setDisableAutoFit] = useState<boolean>(false);
  
  const [flyToCoords, setFlyToCoords] = useState<{ lat: number; lng: number; zoom: number } | null>(null);
  useEffect(() => {
    if (location.pathname !== '/map') {
      // A completed search is not a new navigation target on return from Analytics.
      setFlyToCoords(null);
      setDisableAutoFit(false);
    }
  }, [location.pathname]);
  const selectionMetadata: MapSelectionMetadata = {
    parameters,
    measurement_aggregation_capabilities: measurementAggregationCapabilities,
    air_quality_index_standards: airQualityIndexStandards,
  };
  const selectedAirQualityIndexProduct = findAirQualityIndexProduct(
    airQualityIndexStandards,
    selection.air_quality_index_product_code,
  );
  const selectedAirQualityIndexStandard = selectedAirQualityIndexProduct
    ? findStandardForProduct(
        airQualityIndexStandards,
        selectedAirQualityIndexProduct.product_code,
      )
    : null;
  const parameter = selection.parameter_code;
  const timeResolution = selection.aggregation_period;
  const mode: 'pollutants' | 'devices' = selection.layer === 'devices'
    ? 'devices'
    : 'pollutants';
  const displayMode: MapDisplayMode = selection.layer !== 'aqi'
    ? 'measurements'
    : selectedAirQualityIndexStandard?.standard_code === EEA_EUROPEAN_STANDARD_CODE
      ? 'eea_european'
      : selectedAirQualityIndexStandard?.standard_code === PHILIPPINES_DENR_STANDARD_CODE
        ? 'philippines_denr'
      : 'us_epa';

  const applySelection = (requestedSelection: RequestedMapSelection) => {
    const normalized = normalizeSelectedDataProduct(requestedSelection, selectionMetadata);
    setSelection(normalized.selection);
    setSelectionUnavailableReason(normalized.unavailable_reason);
  };
  

  
  useEffect(() => {
    let cancelled = false;
    let retryTimeout: number | undefined;
    const startedAt = Date.now();
    let retryCount = 0;

    async function checkReadinessAndSetup() {
      try {
        const readinessResponse = await fetchStartupResponse('/health/readiness');
        const readiness = readinessResponse.ok ? await readinessResponse.json() : null;
        if (!readinessResponse.ok || readiness?.status !== 'ready') {
          throw new Error('core_system_not_ready');
        }

        const setupResponse = await fetchStartupResponse('/setup/status');
        const setupStatus = setupResponse.ok ? await setupResponse.json() : null;
        if (
          !setupResponse.ok
          || typeof setupStatus?.is_setup_required !== 'boolean'
          || typeof setupStatus?.has_users !== 'boolean'
        ) {
          throw new Error('setup_status_unavailable');
        }

        if (cancelled) return;
        setIsSetupRequired(setupStatus.is_setup_required);
        setHasSetupUsers(setupStatus.has_users);
        setSetupDefaultLanguageCode(
          isSupportedLanguageCode(setupStatus.default_language_code)
            ? setupStatus.default_language_code
            : null,
        );
        setHasPersistentStartupFailure(false);
        setIsCheckingSetup(false);
      } catch {
        if (cancelled) return;
        if (Date.now() - startedAt >= READINESS_FAILURE_AFTER_MS) {
          setHasPersistentStartupFailure(true);
          return;
        }

        const retryDelay = READINESS_RETRY_DELAYS_MS[
          Math.min(retryCount, READINESS_RETRY_DELAYS_MS.length - 1)
        ];
        retryCount += 1;
        retryTimeout = window.setTimeout(checkReadinessAndSetup, retryDelay);
      }
    }

    void checkReadinessAndSetup();
    return () => {
      cancelled = true;
      if (retryTimeout !== undefined) window.clearTimeout(retryTimeout);
    };
  }, [startupRetryKey]);

  useEffect(() => {
    if (isCheckingSetup || authLoading || isAuthenticated) return;
    void i18n.changeLanguage(resolveAnonymousLanguage(
      readAnonymousLanguagePreference(window.localStorage),
      setupDefaultLanguageCode,
      normalizeBrowserLanguage(window.navigator.language),
    ));
  }, [authLoading, isAuthenticated, isCheckingSetup, setupDefaultLanguageCode]);

  const retryStartup = () => {
    setHasPersistentStartupFailure(false);
    setStartupRetryKey((currentKey) => currentKey + 1);
  };

  
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
        const initialCapabilitySource = initialSourceFilterRef.current;
        const capabilityQuery = initialCapabilitySource
          ? `?source=${encodeURIComponent(initialCapabilitySource)}`
          : '';
        const [items, version, capabilities, sources] = await Promise.all([
          fetchJson<ParamItem[]>('/parameters'),
          fetchJson<Record<string, any>>('/version'),
          fetchJson<MeasurementAggregationCapability[]>(`/measurement-aggregation-capabilities${capabilityQuery}`),
          listPublicDataSources({ skipCache: true }),
        ]);

        if (cancelled) return;
        setParameters(items || []);
        
        setMeasurementAggregationCapabilities(capabilities || []);
        loadedCapabilitySourceRef.current = initialCapabilitySource;
        const capabilityPeriods = new Map<string, ResolutionItem>();
        (capabilities || []).forEach((capability) => capability.supported_aggregations.forEach((option) => {
          capabilityPeriods.set(option.result_aggregation_code, {
            code: option.result_aggregation_code,
            display_name: option.display_name,
          });
        }));
        setResolutions([...capabilityPeriods.values()]);
        setPublicDataSources(sources || []);

        let loadedStandards: AirQualityIndexStandardMetadata[] = [];
        try {
          loadedStandards = await listAirQualityIndexStandards();
          if (!cancelled) {
            setAirQualityIndexStandards(loadedStandards);
            setAirQualityIndexStandardsError(null);
          }
        } catch (standardsError: any) {
          if (!cancelled) {
            setAirQualityIndexStandards([]);
            setAirQualityIndexStandardsError(String(standardsError?.message || standardsError));
          }
        }

        const normalizedSelection = normalizeSelectedDataProduct(initialSelectionRequest, {
          parameters: items || [],
          measurement_aggregation_capabilities: capabilities || [],
          air_quality_index_standards: loadedStandards,
        });
        setSelection(normalizedSelection.selection);
        setSelectionUnavailableReason(normalizedSelection.unavailable_reason);

        
        void version;
      } catch (e: any) {
        if (!cancelled) setInitialError(String(e?.message || e));
      } finally {
        if (!cancelled) setInitialLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [initialKey, initialSelectionRequest, isCheckingSetup, isSetupRequired]);

  useEffect(() => {
    if (initialLoading) return;
    if (loadedCapabilitySourceRef.current === sourceFilter) return;
    let cancelled = false;
    const query = sourceFilter ? `?source=${encodeURIComponent(sourceFilter)}` : '';
    fetchJson<MeasurementAggregationCapability[]>(`/measurement-aggregation-capabilities${query}`, { skipCache: true })
      .then((capabilities) => {
        if (!cancelled) {
          setMeasurementAggregationCapabilities(capabilities || []);
          loadedCapabilitySourceRef.current = sourceFilter;
        }
      })
      .catch(() => {
        if (!cancelled) setMeasurementAggregationCapabilities([]);
      });
    return () => { cancelled = true; };
  }, [initialLoading, sourceFilter]);

  
  useEffect(() => {
    // Keep the first-run setup URL clean until setup status is known and complete.
    if (isCheckingSetup || isSetupRequired) return;

    if (location.pathname === '/') {
      document.title = i18n.t('map:app.documentTitles.aqDataPlatformCleanAirCompass');
    } else if (location.pathname === '/account') {
      document.title = i18n.t('auth:account.title');
    } else if (location.pathname.startsWith('/admin')) {
      document.title = i18n.t('map:app.documentTitles.aqPlatformAdmin');
    } else if (location.pathname.startsWith('/analytics')) {
      document.title = i18n.t('map:app.documentTitles.aqPlatformAnalytics');
    } else if (location.pathname.startsWith('/map')) {
      if (displayMode === 'eea_european') {
        document.title = i18n.t('map:app.documentTitles.aqPlatformEuropeanAirQualityIndex');
      } else if (mode === 'devices') {
        document.title = i18n.t('map:app.documentTitles.aqPlatformDevicesMap');
      } else if (parameter) {
        document.title = i18n.t('map:app.documentTitles.parameterMap', { parameter: parameter.toUpperCase() });
      } else {
        document.title = i18n.t('map:app.documentTitles.aqPlatformMap');
      }
    } else if (mode === 'devices') {
      document.title = i18n.t('map:app.documentTitles.aqPlatformDevices');
    } else if (parameter) {
      document.title = i18n.t('map:app.documentTitles.latestParameter', { parameter: parameter.toUpperCase() });
    } else {
      document.title = i18n.t('map:app.documentTitles.aqPlatformMeasurements');
    }
    
  }, [location.pathname, displayMode, mode, parameter, isCheckingSetup, isSetupRequired]);

  // Home owns no Map query state. Preserve unrelated query keys and the hash.
  useEffect(() => {
    if (location.pathname !== '/') return;
    const search = withoutMapQueryState(location.search);
    if (search !== location.search) {
      window.history.replaceState(window.history.state, '', `/${search}${location.hash}`);
    }
  }, [location.pathname, location.search, location.hash]);

  // Read each router navigation (including Back/Forward) before writing controls.
  useEffect(() => {
    if (location.pathname !== '/map' || initialLoading || initialError
      || hydratedMapLocation === location) return;
    const requested = createRequestedMapSelection(location.search);
    const normalized = normalizeSelectedDataProduct(requested, {
      parameters,
      measurement_aggregation_capabilities: measurementAggregationCapabilities,
      air_quality_index_standards: airQualityIndexStandards,
    });
    setSelection(normalized.selection);
    setSelectionUnavailableReason(normalized.unavailable_reason);
    const sp = new URLSearchParams(location.search);
    setSourceFilter((sp.get('source') || '').trim().toLowerCase());
    setHydratedMapLocation(location);
  }, [location, hydratedMapLocation, initialLoading, initialError, parameters,
    measurementAggregationCapabilities, airQualityIndexStandards]);

  useEffect(() => {
    // Map controls may synchronize only the exact route that owns them.
    if (location.pathname !== '/map' || window.location.pathname !== '/map'
      || hydratedMapLocation !== location
      || isCheckingSetup || isSetupRequired || initialLoading) return;
    const sp = new URLSearchParams(window.location.search);
    if (mode !== 'devices') sp.set('mode', mode); else sp.delete('mode');
    if (displayMode !== 'measurements') sp.set('display_mode', displayMode); else sp.delete('display_mode');
    if (displayMode === 'eea_european') {
      sp.set('standard_code', EEA_EUROPEAN_STANDARD_CODE);
    } else if (displayMode === 'philippines_denr') {
      sp.set('standard_code', PHILIPPINES_DENR_STANDARD_CODE);
    } else if (displayMode === 'us_epa') {
      sp.set('standard_code', US_EPA_STANDARD_CODE);
    } else {
      sp.delete('standard_code');
    }
    if (parameter) sp.set('parameter', parameter); else sp.delete('parameter');
    if (sourceFilter) sp.set('source', sourceFilter); else sp.delete('source');
    for (const key of ['recency', 'start', 'until', 'time_start', 'time_end', 'aggregation']) sp.delete(key);
    if (selection.layer === 'aqi' && selection.air_quality_index_product_code) {
      sp.set('product_code', selection.air_quality_index_product_code);
      sp.delete('time_resolution');
    } else {
      sp.delete('product_code');
      if (selection.layer === 'measurements' && timeResolution) sp.set('time_resolution', timeResolution); else sp.delete('time_resolution');
    }
    const qs = sp.toString();
    const search = qs ? `?${qs}` : '';
    if (search !== window.location.search) {
      window.history.replaceState(window.history.state, '', `/map${search}${location.hash}`);
    }
  }, [location, hydratedMapLocation, initialLoading, parameter, mode, displayMode, sourceFilter, timeResolution, selection.layer, selection.air_quality_index_product_code, isCheckingSetup, isSetupRequired]);

  
  const visibleResolutions = listValidAggregationPeriods(selectionMetadata, 'measurements', selection.parameter_code);
  const airQualityIndexStandardsWithAvailableProducts = airQualityIndexStandards
    .map((standard) => ({
      ...standard,
      products: standard.products.filter((product) => product.availability_status === 'available'),
    }))
    .filter((standard) => standard.products.length > 0);

  

  useEffect(() => {
    const toolbar = mapToolbarRef.current;
    if (!toolbar || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      toolbar.parentElement?.style.setProperty('--map-toolbar-bottom', `${toolbar.offsetTop + toolbar.offsetHeight}px`);
    });
    observer.observe(toolbar);
    return () => observer.disconnect();
  }, [location.pathname, isCheckingSetup, isSetupRequired, initialLoading, initialError]);

  const hasActiveMapControls = selection.layer !== 'devices'
    || Boolean(selection.parameter_code || selection.aggregation_period || sourceFilter);

  // A nested component function would get a new identity on every toolbar
  // update and would remount the MapLibre map. Keep the route content as JSX
  // so React can reconcile the existing map instance.
  const mapPage = (
    <div className="app-root map-page">
      
      <div className="overlay-controls" ref={mapToolbarRef}>
        <Link to="/" className="overlay-title" style={{ textDecoration: 'none', color: 'inherit' }}>
          COMPASS
        </Link>
        {narrowMap && <button type="button" className="btn map-controls-trigger"
          aria-expanded={mapFiltersExpanded} aria-haspopup="dialog"
          aria-label={i18n.t('map:app.actions.mapControls')}
          aria-describedby={hasActiveMapControls ? 'map-controls-active' : undefined}
          onClick={() => setMapFiltersExpanded(true)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="3" fill="white" /><circle cx="15" cy="17" r="3" fill="white" />
          </svg>
          {i18n.t('map:app.actions.mapControls')}
          {hasActiveMapControls && <span id="map-controls-active" className="map-controls-active" role="img" aria-label={i18n.t('map:app.text.activeControls')}>•</span>}
        </button>}
        <MapSurface narrow={narrowMap} open={mapFiltersExpanded}
          onClose={() => { setMapFiltersExpanded(false); }}
          label={i18n.t('map:app.actions.mapControls')} className="map-controls-surface map-secondary-controls">
          {narrowMap && <div className="map-controls-heading">
            <h2>{i18n.t('map:app.actions.mapControls')}</h2>
            <button type="button" className="close-button" onClick={() => { setMapFiltersExpanded(false); }}
              aria-label={i18n.t('map:app.actions.closeControls')}>×</button>
          </div>}
        <LocationSearch
          onLocationSelect={(lat, lng, zoom) => {
            
            setDisableAutoFit(true);
            setFlyToCoords({ lat, lng, zoom });
          }}
        />
        <label className="form-label map-layer-control">
          <span className="sr-only"><Trans ns="map" i18nKey="app.text.layer" /></span>
          <select
            aria-label={i18n.t('map:app.accessibility.layer')}
            value={selection.layer}
            onChange={(event) => {
              applySelection({
                layer: event.target.value as SelectedDataProduct['layer'],
                parameter_code: '',
                aggregation_period: '',
                air_quality_index_product_code: '',
                standard_code: '',
              });
            }}
            className="select-input"
          >
            <option value="devices"><Trans ns="map" i18nKey="app.options.devices" /></option>
            <option value="measurements"><Trans ns="map" i18nKey="app.options.measurements" /></option>
            <option value="aqi"><Trans ns="map" i18nKey="app.options.aqi" /></option>
          </select>
        </label>
        <label className={`${selection.layer === 'aqi' ? 'form-label aqi-product-control' : 'form-label'} map-parameter-control`}>
          <span className="sr-only"><Trans ns="map" i18nKey="app.text.parameter" /></span>
          <select
            aria-label={selection.layer === 'aqi' ? i18n.t('map:app.text.aqiProduct') : i18n.t('map:app.text.parameter2')}
            value={selection.layer === 'aqi'
              ? selection.air_quality_index_product_code
              : selection.parameter_code}
            onChange={(event) => {
              if (selection.layer === 'aqi') {
                applySelection({
                  ...selection,
                  air_quality_index_product_code: event.target.value,
                  standard_code: '',
                });
                return;
              }
              applySelection({
                ...selection,
                parameter_code: event.target.value,
                standard_code: '',
              });
            }}
            className="select-input"
            disabled={initialLoading || (
              selection.layer === 'aqi' && airQualityIndexStandardsWithAvailableProducts.length === 0
            )}
          >
            {selection.layer === 'devices' && <option value=""><Trans ns="map" i18nKey="app.options.allParameters" /></option>}
            {selection.layer === 'aqi' && !selection.air_quality_index_product_code && (
              <option value="" disabled><Trans ns="map" i18nKey="app.options.selectAqiProduct" /></option>
            )}
            {selection.layer === 'aqi'
              ? airQualityIndexStandardsWithAvailableProducts.map((standard) => (
                  <optgroup key={standard.standard_code} label={getAirQualityIndexStandardLabel(standard.standard_code)}>
                    {standard.products.map((product: AirQualityIndexProductMetadata) => (
                      <option key={product.product_code} value={product.product_code}>
                        {getAirQualityIndexProductLabel(product.product_code)}
                      </option>
                    ))}
                  </optgroup>
                ))
              : parameters.map((configuredParameter) => (
                  <option key={configuredParameter.code} value={configuredParameter.code}>
                    {getParameterDisplayName(configuredParameter.code, configuredParameter.display_name)}
                  </option>
                ))}
          </select>
          {selection.layer === 'aqi' && selection.air_quality_index_product_code && (
            <span className="map-product-label">{getAirQualityIndexProductLabel(selection.air_quality_index_product_code)}</span>
          )}
          {initialLoading ? (
            <span className="text-sm text-slate-500 ml-2"><Trans ns="map" i18nKey="app.text.loadingParameters" /></span>
          ) : selection.layer !== 'aqi' && parameters.length === 0 ? (
            <span className="text-sm text-red-500 ml-2"><Trans ns="map" i18nKey="app.text.noParameters" /></span>
          ) : null}
        </label>
        {selection.layer === 'measurements' && <label className="form-label map-time-resolution-control">
          <span className="sr-only"><Trans ns="map" i18nKey="app.text.timeResolution" /></span>
          <select
            aria-label={i18n.t('map:app.accessibility.timeResolution')}
            value={timeResolution}
            onChange={(event) => applySelection({
              ...selection,
              aggregation_period: event.target.value,
              standard_code: selectedAirQualityIndexStandard?.standard_code || '',
            })}
            className="select-input"
            disabled={initialLoading || visibleResolutions.length === 0}
          >
            {<option value=""><Trans ns="map" i18nKey="app.options.allTimeResolutions" /></option>}
            {visibleResolutions.map((r) => (
              <option key={r.code} value={r.code}>{r.display_name}</option>
            ))}
          </select>
          {initialLoading ? (
            <span className="text-sm text-slate-500 ml-2"><Trans ns="common" i18nKey="states.loading" /></span>
          ) : resolutions.length === 0 ? (
            <span className="text-sm text-red-500 ml-2"><Trans ns="map" i18nKey="app.text.noResolutions" /></span>
          ) : null}
        </label>}
        {selectionUnavailableReason && (
          <span className="map-hour-note" role="status">{selectionUnavailableReason}</span>
        )}
        {displayMode === 'eea_european' && (
          <span className="map-hour-note"><Trans ns="map" i18nKey="app.text.latestCompletedUtcHour" /></span>
        )}
        <label className="form-label map-source-control">
          <span className="sr-only"><Trans ns="map" i18nKey="app.text.source" /></span>
          <select
            aria-label={i18n.t('map:app.accessibility.dataSourceFilter')}
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="select-input"
            disabled={initialLoading}
          >
            <option value=""><Trans ns="map" i18nKey="app.options.allSources" /></option>
            {publicDataSources.map((source) => (
              <option key={source.filter_value} value={source.filter_value}>
                {source.name}
              </option>
            ))}
          </select>
        </label>
        
        <div className="map-toolbar-actions">
        <button
          type="button"
          onClick={() => setResetTrigger((x) => x + 1)}
          className="btn"
          title={i18n.t('map:app.tooltips.resetViewLocation')}
        >
          <Trans ns="map" i18nKey="app.actions.resetView" /></button>
        <QuickDownload
          mode={selection.layer}
          standardCode={selectedAirQualityIndexStandard?.standard_code}
          productCode={selectedAirQualityIndexProduct?.product_code}
          aqiParameterCode={selectedAirQualityIndexProduct?.parameter_code}
          source={sourceFilter}
          parameter={parameter}
          aggregation={timeResolution}
          loading={initialLoading || (selection.layer === 'aqi' && (!selectedAirQualityIndexStandard || !selectedAirQualityIndexProduct))}
          explanation={i18n.t(selection.layer === 'aqi' ? 'map:app.text.aqiDownloadExplanation' : selection.layer === 'devices' ? 'map:app.text.deviceDownloadExplanation' : 'map:app.text.downloadExplanation', {
            product: selectedAirQualityIndexProduct ? getAirQualityIndexProductLabel(selectedAirQualityIndexProduct.product_code) : '',
            parameter: parameter ? getParameterDisplayName(parameter, parameters.find(item => item.code === parameter)?.display_name) : i18n.t('map:app.options.allParameters'),
            aggregation: timeResolution ? getAggregationDisplayLabel(timeResolution) : i18n.t('map:app.text.nativeResolution'),
            source: publicDataSources.find(item => item.filter_value === sourceFilter)?.name || sourceFilter || i18n.t('map:app.options.allSources'),
          })}
        />
        {displayMode === 'measurements' && <Link to="/analytics" className="btn" title={i18n.t('map:app.tooltips.analytics')}><Trans ns="map" i18nKey="app.actions.analytics" /></Link>}
        </div>
        </MapSurface>
        <div className="map-account-control"><UserMenu /></div>
      </div>

      
      <div className="map-wrapper">
        <MapLibreMap
          controlsOpen={mapFiltersExpanded}
          onOpenControls={() => setMapFiltersExpanded(true)}
          initialViewport={readMapViewport(mapSearch) ?? lastMapViewportRef.current}
          onViewportLeave={rememberMapViewport}
          parameter={parameter}
          mode={mode}
          measurementAggregationCapabilities={measurementAggregationCapabilities}
          resetTrigger={resetTrigger}
          flyToCoords={flyToCoords}
          disableAutoFit={disableAutoFit}
          timeResolution={selection.layer === 'measurements' ? timeResolution : undefined}
          sourceFilter={sourceFilter}
          displayMode={displayMode}
          selectedAirQualityIndexProduct={selectedAirQualityIndexProduct}
          usEpaStandardMetadata={findAirQualityIndexStandard(airQualityIndexStandards, US_EPA_STANDARD_CODE)}
          numericStandardMetadata={selectedAirQualityIndexStandard?.result_kind === 'numeric'
            ? selectedAirQualityIndexStandard
            : null}
          europeanStandardMetadata={findAirQualityIndexStandard(airQualityIndexStandards, EEA_EUROPEAN_STANDARD_CODE)}
          airQualityIndexStandardsError={airQualityIndexStandardsError}
          initialDeviceId={Number(new URLSearchParams(mapSearch).get('device_id')) || null}
        />
      </div>
    </div>
  );

  
  if (location.pathname === '/reset-password') return <ResetPasswordPage />;

  if (isCheckingSetup || authLoading) {
    return (
      <StartupStatus
        persistentFailure={hasPersistentStartupFailure}
        onRetry={retryStartup}
      />
    );
  }

  
  if (isSetupRequired) {
    return (
      <SetupWizard
        onSetupComplete={handleSetupComplete}
        initialAdminCreated={hasSetupUsers}
      />
    );
  }

  
  if (initialLoading) {
    return <LoadingSplash />;
  }
  if (initialError) {
    return (
      <div className="min-h-screen flex items-center justify-center flex-col gap-4">
        <div className="text-red-600 font-semibold"><Trans ns="map" i18nKey="app.text.failedLoadInitialData" /></div>
        <div className="text-sm text-slate-600">{initialError}</div>
        <div>
          <button
            onClick={() => { setInitialKey((k) => k + 1); }}
            className="btn"
          >
            <Trans ns="common" i18nKey="actions.retry" /></button>
        </div>
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/account" element={<RequireAuth><MyAccount /></RequireAuth>} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/map" element={mapPage} />
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
            <AdminQcOverview />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/email" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminEmail />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/qc/parameters/:parameterId" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminQcParameterDetail />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/qc/parameters/:parameterId/sources/:externalApiId" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminQcSourcePolicy />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/qc/extensions" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminQcExtensions />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/qc/sensors" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminQcSensorSearch />
          </RequireScope>
        </RequireAuth>
      } />
      <Route path="/admin/qc/sensors/:sensorId" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminQcSensorPolicy />
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
      <Route path="/admin/devices/new/airgradient" element={
        <RequireAuth>
          <RequireScope scopes={["users:write"]}>
            <AdminDeviceNewAirGradient />
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
