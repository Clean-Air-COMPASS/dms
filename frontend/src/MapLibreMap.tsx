import { formatMeasurementValue } from './measurementFormatting';
import type { MapViewport } from './mapUrlState';
import MapSurface from './components/MapSurface';
import { isMapWebGl2Available } from './mapWebGlSupport';
import { useNarrowMap } from './useNarrowMap';
import MapMeasurementContext from './components/MapMeasurementContext';
import { Trans, useTranslation } from 'react-i18next';
import i18n, { formatDisplayRelativeTimeFromNow } from './i18n';
import * as React from 'react';
import { Link } from 'react-router-dom';
import * as maplibregl from 'maplibre-gl';
import type { Map as MapLibreMapGL, Marker as MapLibreMarker } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import './App.css';
import { fetchJson } from './api';
import { ApiError } from './apiError';
import type { MeasurementAggregationCapability } from './measurementAggregations';
import { fetchMeasurementHistory, type MeasurementHistoryResponse } from './measurementHistory';
import SensorChart from './SensorChart';
import { formatAqiValue, getAqiColor } from './aqi';
import { normalizeMeasurementAggregationCode } from './analyticsSeries';
import AqiLegend from './components/AqiLegend';
import LastUpdated from './components/LastUpdated';
import DataSourceBadge from './components/DataSourceBadge';
import DataAttribution from './components/DataAttribution';
import type { DataAttribution as DataAttributionValue } from './dataAttribution';
import MapEmptyState from './components/MapEmptyState';
import CopyableCoordinates from './components/CopyableCoordinates';
import { formatTimezoneWithOffset } from './utils/timezone';
import {
  buildAirQualityIndexAnalyticsPath,
  getLatestAirQualityIndex,
  type AirQualityIndexProductMetadata,
  type AirQualityIndexStandardMetadata,
  type DeviceAirQualityIndexResult,
  type MapDisplayMode,
} from './airQualityIndex';
import {
  EEA_EUROPEAN_STANDARD_CODE,
  getPhilippineAqiCategoryOnlyMessage,
  formatUtcInterval,
  getAirQualityIndexCategoryLabel,
  getAirQualityIndexCoverageStatusLabel,
  getAirQualityIndexProductLabel,
  getAirQualityIndexStandardLabel,
  getEuropeanAqiMarkerPresentation,
  getExclusionReasonLabel,
} from './airQualityIndexPresentation';
import EuropeanAqiLegend from './components/EuropeanAqiLegend';
import EuropeanAqiDetails from './components/EuropeanAqiDetails';
import AqiTrendCard from './components/AqiTrendCard';
import UsEpaOzoneDetails from './components/UsEpaOzoneDetails';
import UsEpaGasDetails from './components/UsEpaGasDetails';
import UsEpaSo2Details from './components/UsEpaSo2Details';
import { getParameterDisplayName } from './parameterPresentation';


interface Measurement {
  measurement_id: number;
  sensor_id?: number | null;
  external_sensor_id?: string | null;
  value: number;
  parameter: string;
  parameter_name?: string | null;
  unit: string | null;
  observed_at: string | null;
  interval_started_at?: string | null;
  interval_ended_at?: string | null;
  latest_source_observed_at?: string | null;
  result_is_rolling?: boolean;
  is_valid?: boolean | null;
  native_aggregation_code?: string | null;
  result_aggregation_code?: string | null;
  formatting_status?: 'configured' | 'not_configured' | null;
  display_precision?: number | null;
  device?: { device_id?: number | null; name?: string | null; friendly_name?: string | null; latitude?: number | null; longitude?: number | null; network?: string | null; timezone?: string | null; data_attribution?: DataAttributionValue | null } | null;
  air_quality_index_result?: DeviceAirQualityIndexResult | null;
}

interface DevicePoint {
  device_id: number;
  name?: string | null;
  friendly_name?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  sensor_count?: number | null;
  network?: string | null;
  timezone?: string | null;
  data_attribution?: DataAttributionValue | null;
}

interface DeviceSensor {
  sensor_id: number;
  external_sensor_id?: string | null;
  parameter?: string | null; 
  parameter_name?: string | null;
  unit?: string | null;
  latest_value?: number | null;
  latest_observed_at?: string | null;
  latest_is_valid?: boolean | null;
  interval_started_at?: string | null;
  interval_ended_at?: string | null;
  latest_source_observed_at?: string | null;
  result_is_rolling?: boolean;
  native_aggregation_code?: string | null;
  result_aggregation_code?: string | null;
  display_precision?: number | null;
}

type MeasurementHistoryTarget = {
  sensorId: number;
  parameterCode: string;
  unit: string;
  aggregationCode: string;
  targetKey: string;
  nativeAggregationCode?: string | null;
};

type MeasurementHistoryState = {
  requestKey: string | null;
  response: MeasurementHistoryResponse | null;
  loading: boolean;
  error: string | null;
  retryable?: boolean;
};

type Props = {
  initialViewport?: MapViewport | null;
  onViewportLeave?: (viewport: MapViewport) => void;
  parameter: string; 
  mode?: 'pollutants' | 'devices';
  fitTrigger?: number; 
  resetTrigger?: number; 
  flyToCoords?: { lat: number; lng: number; zoom: number } | null; 
  disableAutoFit?: boolean; 
  timeResolution?: string;
  sourceFilter?: string; 
  displayMode?: MapDisplayMode;
  selectedAirQualityIndexProduct?: AirQualityIndexProductMetadata | null;
  usEpaStandardMetadata?: AirQualityIndexStandardMetadata | null;
  numericStandardMetadata?: AirQualityIndexStandardMetadata | null;
  europeanStandardMetadata?: AirQualityIndexStandardMetadata | null;
  airQualityIndexStandardsError?: string | null;
  initialDeviceId?: number | null;
  measurementAggregationCapabilities?: MeasurementAggregationCapability[];
  controlsOpen?: boolean;
  onOpenControls?: () => void;
};

// Vite must bundle the v6 module worker and its shared module into one asset.
maplibregl.setWorkerUrl(mapWorkerUrl);

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'; 
const MAP_CONTROL_SAFE_PADDING = 72;  
const MAP_TOOLBAR_SAFE_PADDING = 100; 
const DEVICE_MARKER_COLOR = '#0B5FFF';

const formatCompletedLocalDate = (representedLocalDate: string): string => {
  const dateParts = representedLocalDate.split('-').map(Number);
  if (dateParts.length !== 3 || dateParts.some((part) => !Number.isInteger(part))) {
    return representedLocalDate;
  }
  const [year, month, day] = dateParts;
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month - 1, day)));
};


const MapLibreMap: React.FC<Props> = ({ initialViewport = null, onViewportLeave, parameter, mode = 'pollutants', fitTrigger, resetTrigger, flyToCoords = null, disableAutoFit = false, timeResolution, sourceFilter = '', displayMode = 'measurements', selectedAirQualityIndexProduct = null, usEpaStandardMetadata = null, numericStandardMetadata = null, europeanStandardMetadata = null, airQualityIndexStandardsError = null, initialDeviceId = null, measurementAggregationCapabilities = [], controlsOpen = false, onOpenControls }) => {
  const CACHE = React.useRef<Record<string, Measurement[] | undefined>>({}).current;
  const INFLIGHT = React.useRef<Record<string, Promise<Measurement[]> | undefined>>({}).current;
  const SITES_CACHE = React.useRef<Record<string, DevicePoint[] | undefined>>({}).current;
  const SITES_INFLIGHT = React.useRef<Record<string, Promise<DevicePoint[]> | undefined>>({}).current;
  const DEVICE_SENSORS_CACHE = React.useRef<Record<string, DeviceSensor[] | undefined>>({}).current;
  const DEVICE_SENSORS_INFLIGHT = React.useRef<Record<string, Promise<DeviceSensor[]> | undefined>>({}).current;
  const mapContainer = React.useRef<HTMLDivElement | null>(null);
  const getMapControlPadding = React.useCallback(() => (
    (mapContainer.current?.clientWidth ?? 0) <= 768 ? 0 : MAP_CONTROL_SAFE_PADDING
  ), []);
  const mapRef = React.useRef<MapLibreMapGL | null>(null);
  const [measurements, setMeasurements] = React.useState<Measurement[]>([]);
  const [measurementsRequestKey, setMeasurementsRequestKey] = React.useState<string | null>(null);
  const [sites, setSites] = React.useState<DevicePoint[]>([]);
  const [europeanAirQualityIndexResults, setEuropeanAirQualityIndexResults] = React.useState<DeviceAirQualityIndexResult[]>([]);
  const [selectedEuropeanAirQualityIndexResult, setSelectedEuropeanAirQualityIndexResult] = React.useState<DeviceAirQualityIndexResult | null>(null);
  const [mapBoundingBox, setMapBoundingBox] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mapReady, setMapReady] = React.useState(false);
  const [mapUnavailable, setMapUnavailable] = React.useState(false);
  const userPosRef = React.useRef<{ lng: number; lat: number } | null>(null);
  const [expandedGroups, setExpandedGroups] = React.useState<Set<string>>(new Set());
  const initiallyCenteredDeviceIdRef = React.useRef<number | null>(null);
  // Capture entry context once; later data/filter renders must not reinitialize it.
  const entryViewportRef = React.useRef(initialDeviceId == null ? initialViewport : null);
  const initialViewportPendingRef = React.useRef(!initialDeviceId && !initialViewport && !flyToCoords && !disableAutoFit);
  const onViewportLeaveRef = React.useRef(onViewportLeave);
  onViewportLeaveRef.current = onViewportLeave;
  // Block even an immediate permission callback when navigation supplies a target.
  if (initialDeviceId != null || flyToCoords || disableAutoFit) initialViewportPendingRef.current = false;
  const initialFilterRef = React.useRef({ parameter, mode, displayMode, sourceFilter, timeResolution, productCode: selectedAirQualityIndexProduct?.product_code });
  React.useEffect(() => {
    const initial = initialFilterRef.current;
    if (initial.parameter !== parameter || initial.mode !== mode || initial.displayMode !== displayMode
      || initial.sourceFilter !== sourceFilter || initial.timeResolution !== timeResolution
      || initial.productCode !== selectedAirQualityIndexProduct?.product_code) {
      initialViewportPendingRef.current = false;
    }
  }, [parameter, mode, displayMode, sourceFilter, timeResolution, selectedAirQualityIndexProduct?.product_code]);
  const lastFitTriggerRef = React.useRef(fitTrigger);
  const lastResetTriggerRef = React.useRef(resetTrigger);
  const SPIDER_LINE_SOURCE = 'aq-spider-lines';
  const SPIDER_LINE_LAYER = 'aq-spider-lines';
  const narrowMap = useNarrowMap();
  const detailTriggerRef = React.useRef<HTMLElement | null>(null);
  // Keep identity/context for an unavailable sensor; values belong to the current response.
  const [measurementSelection, setSelectedMeasurement] = React.useState<Pick<Measurement, 'sensor_id' | 'parameter' | 'parameter_name' | 'device'> | null>(null);
  const [selectedSite, setSelectedSite] = React.useState<DevicePoint | null>(null);
  const [deviceSensors, setDeviceSensors] = React.useState<DeviceSensor[] | null>(null);
  const [deviceSensorsRequestLoading, setDeviceSensorsLoading] = React.useState(false);
  const [deviceSensorsRequestKey, setDeviceSensorsRequestKey] = React.useState<string | null>(null);
  const previousSensorDeviceIdRef = React.useRef<number | null>(null);
  const [deviceSensorsError, setDeviceSensorsError] = React.useState<string | null>(null);
  const [activeSensorId, setActiveSensorId] = React.useState<number | null>(null); 
  const [measurementHistoryState, setMeasurementHistoryState] = React.useState<MeasurementHistoryState>({
    requestKey: null,
    response: null,
    loading: false,
    error: null,
  });
  const [measurementHistoryRetryToken, setMeasurementHistoryRetryToken] = React.useState(0);
  const [dataRefreshToken, setDataRefreshToken] = React.useState(0);
  const activeDeviceSensorsRequestKey = `${selectedSite?.device_id ?? ''}:${timeResolution || 'allres'}:${dataRefreshToken}`;
  const currentDeviceSensors = deviceSensorsRequestKey === activeDeviceSensorsRequestKey ? deviceSensors : null;
  const deviceSensorsLoading = deviceSensorsRequestLoading
    || Boolean(selectedSite && deviceSensorsRequestKey !== activeDeviceSensorsRequestKey);
  const [lastDataUpdate, setLastDataUpdate] = React.useState<string | null>(null);
  const previousSelectionContextRef = React.useRef({ parameter, mode, displayMode });
  const selectedParamCode = React.useMemo(() => (parameter || '').toLowerCase(), [parameter]);
  const isAqiActive = displayMode === 'us_epa' || displayMode === 'philippines_denr';
  const isEuropeanAqiActive = displayMode === 'eea_european';
  const activeMeasurementsRequestKey = [parameter, mode, displayMode, timeResolution ?? '', sourceFilter,
    selectedAirQualityIndexProduct?.product_code ?? '', dataRefreshToken].join('|');
  const selectedMeasurement = measurementsRequestKey === activeMeasurementsRequestKey
    ? measurements.find((measurement) => measurementSelection && (isAqiActive
      ? measurement.device?.device_id === measurementSelection.device?.device_id
      : measurement.sensor_id != null && measurement.sensor_id === measurementSelection.sensor_id)) ?? null
    : null;
  const effectiveNumericStandardMetadata = numericStandardMetadata ?? usEpaStandardMetadata;
  const effectiveEuropeanAirQualityIndexProduct = React.useMemo(
    () => selectedAirQualityIndexProduct ?? europeanStandardMetadata?.products.find(
      (product) => product.product_code === europeanStandardMetadata.default_product_code,
    ) ?? null,
    [selectedAirQualityIndexProduct, europeanStandardMetadata],
  );
  
  const effectiveAggregationCode = timeResolution;
  const activeAqiLabel = React.useMemo(
    () => (isAqiActive && selectedAirQualityIndexProduct
      ? getAirQualityIndexProductLabel(selectedAirQualityIndexProduct.product_code)
      : ''),
    [isAqiActive, selectedAirQualityIndexProduct]
  );
  const activeAggregationCode = React.useMemo(
    () => (timeResolution && timeResolution.trim() ? timeResolution.toLowerCase() : 'hour'),
    [timeResolution]
  );
  const { i18n: activeI18n } = useTranslation();
  const measurementLocale = activeI18n.resolvedLanguage || 'en';
  const formatValueForDisplay = React.useCallback(
    (_param?: string | null, value?: number | null, _aggregation?: string | null, displayPrecision?: number | null) =>
      formatMeasurementValue(value, displayPrecision, measurementLocale),
    [measurementLocale]
  );
  const refreshMapData = React.useCallback(() => {
    [CACHE, SITES_CACHE, DEVICE_SENSORS_CACHE]
      .forEach((cache) => Object.keys(cache).forEach((key) => delete cache[key]));
    setDataRefreshToken((current) => current + 1);
    setMeasurementHistoryRetryToken((current) => current + 1);
  }, [CACHE, SITES_CACHE, DEVICE_SENSORS_CACHE]);
  const orderedDeviceSensors = React.useMemo(() => {
    if (!currentDeviceSensors) return null;
    
    const all = currentDeviceSensors;
    if (!selectedParamCode) return all;
    const matches = all.filter((s) => (s.parameter || '').toLowerCase() === selectedParamCode);
    const others = all.filter((s) => (s.parameter || '').toLowerCase() !== selectedParamCode);
    
    return [...matches, ...others];
  }, [currentDeviceSensors, selectedParamCode]);

  const activeDeviceSensor = React.useMemo(() => {
    const sensors = orderedDeviceSensors ?? [];
    return activeSensorId != null ? sensors.find((sensor) => sensor.sensor_id === activeSensorId) ?? null : sensors[0] ?? null;
  }, [activeSensorId, orderedDeviceSensors]);

  const getMeasurementHistoryAggregation = React.useCallback(
    (candidate: { result_aggregation_code?: string | null; native_aggregation_code?: string | null }): string => {
      const requested = timeResolution?.trim()
        || candidate.result_aggregation_code?.trim()
        || candidate.native_aggregation_code?.trim()
        || 'raw';
      return normalizeMeasurementAggregationCode(requested) || 'raw';
    },
    [timeResolution],
  );

  const measurementHistoryTarget = React.useMemo<MeasurementHistoryTarget | null>(() => {
    if (isAqiActive || isEuropeanAqiActive) return null;
    if (selectedMeasurement?.sensor_id != null) {
      const parameterCode = (selectedMeasurement.parameter || '').toLowerCase();
      const aggregationCode = normalizeMeasurementAggregationCode(selectedMeasurement.result_aggregation_code
        || getMeasurementHistoryAggregation(selectedMeasurement));
      return {
        sensorId: selectedMeasurement.sensor_id,
        parameterCode,
        unit: selectedMeasurement.unit ?? '',
        aggregationCode,
        nativeAggregationCode: selectedMeasurement.native_aggregation_code,
        targetKey: `${selectedMeasurement.sensor_id}|${parameterCode}|${aggregationCode}`,
      };
    }
    if (selectedSite && activeDeviceSensor) {
      const parameterCode = (activeDeviceSensor.parameter || '').toLowerCase();
      const aggregationCode = getMeasurementHistoryAggregation(activeDeviceSensor);
      return {
        sensorId: activeDeviceSensor.sensor_id,
        parameterCode,
        unit: activeDeviceSensor.unit ?? '',
        aggregationCode,
        nativeAggregationCode: activeDeviceSensor.native_aggregation_code,
        targetKey: `${activeDeviceSensor.sensor_id}|${parameterCode}|${aggregationCode}`,
      };
    }
    return null;
  }, [
    activeDeviceSensor,
    getMeasurementHistoryAggregation,
    isAqiActive,
    isEuropeanAqiActive,
    selectedMeasurement,
    selectedSite,
  ]);

  // Detail charts retain a bounded preview; historical exploration lives in Analytics.
  const measurementHistoryRange = { start: null, end: null, hours: 24 };

  const measurementHistoryRequestKey = measurementHistoryTarget
    ? [
        measurementHistoryTarget.targetKey,
        measurementHistoryRange.start ?? 'default',
        measurementHistoryRange.end ?? 'now',
        measurementHistoryRange.hours ?? 'bounded',
        sourceFilter,
        dataRefreshToken,
      ].join('|')
    : null;
  const measurementHistorySensorId = measurementHistoryTarget?.sensorId ?? null;
  const measurementHistoryParameterCode = measurementHistoryTarget?.parameterCode ?? '';
  const measurementHistoryAggregationCode = measurementHistoryTarget?.aggregationCode ?? '';
  const historyCapability = measurementAggregationCapabilities.find((capability) => (
    capability.parameter_code === measurementHistoryParameterCode
    && capability.native_aggregation_code === measurementHistoryTarget?.nativeAggregationCode
  ))?.supported_aggregations.find((option) => option.result_aggregation_code === measurementHistoryAggregationCode);
  const historyUnsupported = historyCapability?.supports_history === false;

  React.useEffect(() => {
    if (measurementHistorySensorId == null || !measurementHistoryRequestKey) {
      setMeasurementHistoryState({ requestKey: null, response: null, loading: false, error: null });
      return;
    }

    const controller = new AbortController();
    const requestKey = measurementHistoryRequestKey;
    if (historyUnsupported) {
      setMeasurementHistoryState({ requestKey, response: null, loading: false,
        error: i18n.t('map:mapLibreMap.text.latestOnlyHistory'), retryable: false });
      return () => controller.abort();
    }
    setMeasurementHistoryState({ requestKey, response: null, loading: true, error: null });
    fetchMeasurementHistory({
      sensorId: measurementHistorySensorId,
      parameterCode: measurementHistoryParameterCode,
      aggregation: measurementHistoryAggregationCode,
      start: measurementHistoryRange.start,
      end: measurementHistoryRange.end,
      hours: measurementHistoryRange.hours ?? undefined,
      signal: controller.signal,
    }).then((response) => {
      if (controller.signal.aborted) return;
      setMeasurementHistoryState({ requestKey, response, loading: false, error: null });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      const reason = error instanceof ApiError ? error.errorCode : null;
      const unsupported = reason === 'rolling_history_not_supported'
        || reason === 'unsupported_measurement_aggregation'
        || reason === 'unknown_native_aggregation'
        || reason === 'unknown_result_aggregation';
      setMeasurementHistoryState({
        requestKey,
        response: null,
        loading: false,
        error: reason === 'rolling_history_not_supported'
          ? i18n.t('map:mapLibreMap.text.latestOnlyHistory')
          : unsupported ? i18n.t('map:mapLibreMap.text.unsupportedHistory')
            : i18n.t('map:mapLibreMap.text.unableLoadMeasurementHistory'),
        retryable: !unsupported,
      });
    });
    return () => controller.abort();
  }, [
    measurementHistoryRange.end,
    measurementHistoryRange.hours,
    measurementHistoryRange.start,
    measurementHistoryRequestKey,
    measurementHistoryRetryToken,
    measurementHistoryAggregationCode,
    measurementHistoryParameterCode,
    measurementHistorySensorId,
    historyUnsupported,
  ]);

  const currentMeasurementHistory = measurementHistoryState.requestKey === measurementHistoryRequestKey
    ? measurementHistoryState.response
    : null;
  const measurementHistoryLoading = measurementHistoryRequestKey != null
    && (measurementHistoryState.requestKey !== measurementHistoryRequestKey || measurementHistoryState.loading);
  const measurementHistoryError = measurementHistoryState.requestKey === measurementHistoryRequestKey
    ? measurementHistoryState.error
    : null;
  const measurementHistoryChart = measurementHistoryTarget ? (
    measurementHistoryLoading ? (
      <div className="panel-loading" role="status"><Trans ns="map" i18nKey="mapLibreMap.text.loadingMeasurementHistory" /></div>
    ) : measurementHistoryError ? (
      <div className={measurementHistoryState.retryable === false ? 'empty-chart' : 'panel-error-msg'} role="alert">
        <div>{measurementHistoryError}</div>
        {measurementHistoryState.retryable !== false && <button
          type="button"
          className="btn"
          onClick={() => setMeasurementHistoryRetryToken((current) => current + 1)}
        >
          <Trans ns="common" i18nKey="actions.retry" /></button>}
      </div>
    ) : currentMeasurementHistory?.data.length === 0 ? (
      <div className="empty-chart" role="status"><Trans ns="map" i18nKey={currentMeasurementHistory.history_status === 'no_eligible_observations' ? 'mapLibreMap.text.noEligibleHistory' : 'mapLibreMap.text.noDataAvailableSelectedWindow'} /></div>
    ) : currentMeasurementHistory ? (
      <>
      {currentMeasurementHistory.data.length === 1 && <p className="mb-3 text-sm text-slate-600" role="status"><Trans ns="map" i18nKey="mapLibreMap.text.singleHistoryPoint" /></p>}
      <SensorChart
        sensorId={measurementHistoryTarget.sensorId}
        parameter={measurementHistoryTarget.parameterCode}
        unit={measurementHistoryTarget.unit}
        data={currentMeasurementHistory}
        hours={measurementHistoryRange.hours ?? 24}
        rangeStartedAt={measurementHistoryRange.start}
        rangeEndedAt={measurementHistoryRange.end}
        timeResolution={currentMeasurementHistory._displayAggregate}
        timezoneMode="utc"
      />
      </>
    ) : (
      <div className="panel-loading" role="status"><Trans ns="map" i18nKey="mapLibreMap.text.loadingMeasurementHistory2" /></div>
    )
  ) : (
    <div className="empty-chart"><Trans ns="map" i18nKey="mapLibreMap.text.noChartDataAvailable" /></div>
  );

  const timeAgo = React.useCallback((iso: string | null | undefined) => {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return formatDisplayRelativeTimeFromNow(
      d,
      Date.now(),
      i18n.resolvedLanguage === 'es' ? 'es' : 'en',
    );
  }, []);

  const normalizedExternalApiName = React.useMemo(() => {
    const trimmed = (sourceFilter || '').trim();
    return trimmed ? trimmed.toLowerCase() : '';
  }, [sourceFilter]);

  const buildUrlWithExternalApiName = React.useCallback(
    (path: string, queryValues: Record<string, string | null | undefined>) => {
      const queryParams = new URLSearchParams();
      if (normalizedExternalApiName) {
        queryParams.set('external_api_name', normalizedExternalApiName);
      }
      Object.entries(queryValues).forEach(([key, value]) => {
        if (value === null || value === undefined || value === '') return;
        queryParams.set(key, value);
      });
      const queryString = queryParams.toString();
      return queryString ? `${path}?${queryString}` : path;
    },
    [normalizedExternalApiName]
  );

  
  React.useEffect(() => {
    let cancelled = false;
    
    setError(null);
    setLoading(true);
    setMeasurements([]);
    setMeasurementsRequestKey(activeMeasurementsRequestKey);
    setSites([]);
    setEuropeanAirQualityIndexResults([]);

    if (isAqiActive) {
      setEuropeanAirQualityIndexResults([]);
      setSites([]);

      if (!effectiveNumericStandardMetadata || !selectedAirQualityIndexProduct) {
        setMeasurements([]);
        setError(
          airQualityIndexStandardsError
            ? i18n.t('map:mapLibreMap.messages.productMetadataUnavailable', {
                product: selectedAirQualityIndexProduct
                  ? getAirQualityIndexProductLabel(selectedAirQualityIndexProduct.product_code)
                  : i18n.t('map:app.options.aqi'),
              })
            : i18n.t('map:mapLibreMap.messages.standardUnsupported'),
        );
        setLoading(false);
        return () => { cancelled = true; };
      }

      getLatestAirQualityIndex({
        standard_code: effectiveNumericStandardMetadata.standard_code,
        product_code: selectedAirQualityIndexProduct.product_code,
        external_api_name: normalizedExternalApiName || null,
        all_results: true,
      }).then((collection) => {
        if (cancelled) return;
        const currentConditionMeasurements = (collection.results || []).map((result) => ({
          measurement_id: 0,
          sensor_id: result.sensor_id,
          external_sensor_id: result.external_sensor_id,
          parameter: selectedAirQualityIndexProduct.parameter_code || '',
          value: result.numeric_value ?? Number.NaN,
          unit: 'AQI',
          observed_at: result.observed_at,
          device: {
            device_id: result.device_id,
            name: result.device_name,
            friendly_name: result.device_friendly_name,
            latitude: result.latitude,
            longitude: result.longitude,
            network: result.source_name,
            timezone: result.device_timezone,
          },
          air_quality_index_result: result,
        } satisfies Measurement));
        setMeasurements(currentConditionMeasurements);
        setMeasurementsRequestKey(activeMeasurementsRequestKey);
        setError(null);
        setLoading(false);
        setLastDataUpdate(new Date().toISOString());
      }).catch(() => {
        if (cancelled) return;
        setMeasurements([]);
        setError(i18n.t('map:mapLibreMap.messages.unableLoadStandardResults', {
          standard: getAirQualityIndexStandardLabel(effectiveNumericStandardMetadata.standard_code),
        }));
        setLoading(false);
      });

      return () => { cancelled = true; };
    }

    if (isEuropeanAqiActive) {
      // A mode change must immediately remove markers from the previous data model.
      setMeasurements([]);
      setSites([]);

      if (!europeanStandardMetadata || !effectiveEuropeanAirQualityIndexProduct) {
        setError(
          airQualityIndexStandardsError
            ? i18n.t('map:mapLibreMap.messages.europeanMetadataUnavailable')
            : i18n.t('map:mapLibreMap.messages.europeanUnsupported'),
        );
        setLoading(false);
        return () => { cancelled = true; };
      }

      getLatestAirQualityIndex({
        standard_code: EEA_EUROPEAN_STANDARD_CODE,
        product_code: effectiveEuropeanAirQualityIndexProduct.product_code,
        external_api_name: normalizedExternalApiName || null,
        all_results: true,
      }).then((collection) => {
        if (cancelled) return;
        const results = collection.results || [];
        setEuropeanAirQualityIndexResults(results);
        setError(null);
        setLoading(false);
        setLastDataUpdate(new Date().toISOString());
      }).catch(() => {
        if (cancelled) return;
        setEuropeanAirQualityIndexResults([]);
        setError(i18n.t('map:mapLibreMap.messages.unableLoadEuropeanAirQualityIndex'));
        setLoading(false);
      });

      return () => { cancelled = true; };
    }

    setEuropeanAirQualityIndexResults([]);
  if (mode === 'pollutants') {
      
      if (!parameter) {
        if (!cancelled) {
          setMeasurements([]);
          setLoading(false);
        }
        return () => {
          cancelled = true;
        };
      }
      
      const apiAggregation = effectiveAggregationCode || timeResolution;
      const key = `pollutants:${parameter}:${apiAggregation || 'allres'}:${normalizedExternalApiName || 'all'}:${dataRefreshToken}`;
      const url = buildUrlWithExternalApiName(`/measurements/${encodeURIComponent(parameter)}/latest`, {
        all_results: 'true',
        aggregation: apiAggregation || undefined,
      });
      const applyData = (data: Measurement[]) => {
        if (cancelled) return;
        
        setMeasurements(data);
        setMeasurementsRequestKey(activeMeasurementsRequestKey);
        setSites([]);
        setError(null);
        setLoading(false);
        setLastDataUpdate(new Date().toISOString());
      };

      if (CACHE[key]) {
        applyData(CACHE[key]!);
        return () => { cancelled = true; };
      }
      if (INFLIGHT[key]) {
        INFLIGHT[key]!.then(applyData).catch(() => {
          if (cancelled) return;
          setError(i18n.t('map:mapLibreMap.messages.unableLoadAirQualityDataPlease'));
          setLoading(false);
        });
        return () => { cancelled = true; };
      }

      INFLIGHT[key] = fetchJson<Measurement[]>(url, { skipCache: true })
        .then((data) => {
          CACHE[key] = data;
          return data;
        })
        .finally(() => { delete INFLIGHT[key]; });

      INFLIGHT[key]!.then(applyData).catch(() => {
        if (cancelled) return;
        setError(i18n.t('map:mapLibreMap.messages.unableLoadAirQualityDataPlease2'));
        setLoading(false);
      });
  } else {
      
      const devicesKey = `devices:${parameter}:${normalizedExternalApiName || 'all'}:${dataRefreshToken}`;
      const devicesUrl = buildUrlWithExternalApiName('/devices', {
        parameter: parameter || undefined,
      });
      const loadDevices = (): Promise<DevicePoint[]> => {
        if (SITES_CACHE[devicesKey]) return Promise.resolve(SITES_CACHE[devicesKey]!);
        if (SITES_INFLIGHT[devicesKey]) return SITES_INFLIGHT[devicesKey]!;
        SITES_INFLIGHT[devicesKey] = fetchJson<DevicePoint[]>(devicesUrl, { skipCache: true })
          .then((data) => {
            SITES_CACHE[devicesKey] = data;
            return data;
          })
          .finally(() => { delete SITES_INFLIGHT[devicesKey]; });
        return SITES_INFLIGHT[devicesKey]!;
      };

      const applyDevices = (data: DevicePoint[]) => {
        if (cancelled) return;
        setSites(data);
        setMeasurements([]);
        setError(null);
        setLoading(false);
        setLastDataUpdate(new Date().toISOString());
      };

      
      loadDevices().then(applyDevices).catch(() => {
        if (cancelled) return;
        setError(i18n.t('map:mapLibreMap.messages.unableLoadDevicesPleaseTryAgain2'));
        setLoading(false);
      });
    }

    return () => {
      cancelled = true;
    };
  }, [CACHE, INFLIGHT, SITES_CACHE, SITES_INFLIGHT, parameter, mode, timeResolution, effectiveAggregationCode, isAqiActive, isEuropeanAqiActive, effectiveNumericStandardMetadata, europeanStandardMetadata, selectedAirQualityIndexProduct, effectiveEuropeanAirQualityIndexProduct, airQualityIndexStandardsError, normalizedExternalApiName, buildUrlWithExternalApiName, initialDeviceId, dataRefreshToken, activeMeasurementsRequestKey]);

  
  React.useEffect(() => {
    let cancelled = false;
    setDeviceSensors(null);
    setDeviceSensorsLoading(false);
    setDeviceSensorsError(null);
    setDeviceSensorsRequestKey(activeDeviceSensorsRequestKey);
    const deviceChanged = previousSensorDeviceIdRef.current !== (selectedSite?.device_id ?? null);
    previousSensorDeviceIdRef.current = selectedSite?.device_id ?? null;
    if (deviceChanged) setActiveSensorId(null);
    if (!selectedSite) {
      setActiveSensorId(null);
      return;
    }
    const id = selectedSite.device_id;
    const deviceSensorsCacheKey = `${id}:${timeResolution || 'allres'}:${dataRefreshToken}`;
    const applySensors = (rows: DeviceSensor[]) => {
      if (cancelled) return;
      setDeviceSensors(rows);
      setDeviceSensorsLoading(false);
      
      if (rows.length > 0) {
        const matchingParam = rows.find((s) => (s.parameter || '').toLowerCase() === selectedParamCode);
        setActiveSensorId((current) => !deviceChanged && current != null
          ? current : matchingParam ? matchingParam.sensor_id : rows[0].sensor_id);
      }
    };
    if (DEVICE_SENSORS_CACHE[deviceSensorsCacheKey]) {
      applySensors(DEVICE_SENSORS_CACHE[deviceSensorsCacheKey]!);
      return () => { cancelled = true; };
    }
      if (DEVICE_SENSORS_INFLIGHT[deviceSensorsCacheKey]) {
      setDeviceSensorsLoading(true);
      DEVICE_SENSORS_INFLIGHT[deviceSensorsCacheKey]!.then(applySensors).catch(() => {
      if (!cancelled) {
        setDeviceSensorsError(i18n.t('map:mapLibreMap.messages.unableLoadSensorsDevice'));
        setDeviceSensors([]);
        setDeviceSensorsLoading(false);
      }
    });
      return () => { cancelled = true; };
    }
    setDeviceSensorsLoading(true);
    const url = `/devices/${id}/sensors${timeResolution ? `?aggregation=${encodeURIComponent(timeResolution)}` : ''}`;
    DEVICE_SENSORS_INFLIGHT[deviceSensorsCacheKey] = fetchJson<DeviceSensor[]>(url, { skipCache: true })
      .then((rows) => {
        DEVICE_SENSORS_CACHE[deviceSensorsCacheKey] = rows;
        return rows;
      })
      .finally(() => { delete DEVICE_SENSORS_INFLIGHT[deviceSensorsCacheKey]; });
    DEVICE_SENSORS_INFLIGHT[deviceSensorsCacheKey]!.then(applySensors).catch(() => {
      if (!cancelled) {
        setDeviceSensorsError(i18n.t('map:mapLibreMap.messages.unableLoadSensorsDevice2'));
        setDeviceSensors([]);
        setDeviceSensorsLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [DEVICE_SENSORS_CACHE, DEVICE_SENSORS_INFLIGHT, selectedSite, timeResolution, selectedParamCode, dataRefreshToken, activeDeviceSensorsRequestKey]);

  React.useEffect(() => {
    // A URL-selected device should be centered once. Re-centering after every
    // bounding-box refresh creates a move/fetch loop.
    initiallyCenteredDeviceIdRef.current = null;
  }, [initialDeviceId]);

  React.useEffect(() => {
    let disposed = false;
    function waitForContainer(cb: (container: HTMLElement) => void) {
      if (disposed) return;
      if (mapContainer.current && mapContainer.current instanceof HTMLElement) {
        cb(mapContainer.current);
      } else {
        setTimeout(() => waitForContainer(cb), 10);
      }
    }

    if (!mapRef.current) {
      const entry = entryViewportRef.current;
      let center: [number, number] = entry ? [entry.lng, entry.lat] : [0, 0];
      let zoom = entry?.zoom ?? 2;

      const createMap = (container: HTMLElement) => {
        if (!isMapWebGl2Available()) {
          setMapUnavailable(true);
          return;
        }
        mapRef.current = new maplibregl.Map({
          container,
          style: MAP_STYLE,
          center: center,
          zoom: zoom,
          renderWorldCopies: true,
          // Native Mercator constraints keep geography filling the canvas height,
          // including portrait layouts. Wrapping leaves longitude unconstrained.
          minZoom: 0,
          bearing: entry?.bearing ?? 0,
          pitch: entry?.pitch ?? 0,
        });
        
        mapRef.current.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
        try {
          mapRef.current.setPadding({ top: 0, right: getMapControlPadding(), bottom: 0, left: 0 });
        } catch {
          void 0;
        }
        mapRef.current.on('load', () => {
          try {
            mapRef.current?.setPadding({ top: 0, right: getMapControlPadding(), bottom: 0, left: 0 });
          } catch {
            void 0;
          }
          setMapReady(true);
          const bounds = mapRef.current?.getBounds();
          if (bounds) {
            setMapBoundingBox(`${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`);
          }
        });
        // MapLibre marks physical pointer/keyboard navigation with originalEvent.
        // Programmatic initial centering must not consume this guard.
        mapRef.current.on('movestart', (event) => {
          if (event.originalEvent) initialViewportPendingRef.current = false;
        });
        mapRef.current.on('moveend', () => {
          const bounds = mapRef.current?.getBounds();
          if (!bounds) return;
          const nextBoundingBox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
          setMapBoundingBox((currentBoundingBox) => currentBoundingBox === nextBoundingBox ? currentBoundingBox : nextBoundingBox);
        });
      };

      // The map must exist even while a browser permission prompt is unanswered.
      waitForContainer(createMap);
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            if (disposed) return;
            userPosRef.current = { lng: pos.coords.longitude, lat: pos.coords.latitude };
            if (!initialViewportPendingRef.current) return;
            center = [pos.coords.longitude, pos.coords.latitude];
            zoom = 10;
            mapRef.current?.jumpTo({ center, zoom });
          },
          () => { /* The default map remains usable when location is unavailable. */ },
          { timeout: 5000 },
        );
      }
    }
    return () => {
      disposed = true;
      if (mapRef.current) {
        if (onViewportLeaveRef.current) {
          const center = mapRef.current.getCenter();
          onViewportLeaveRef.current({ lat: center.lat, lng: center.lng,
            zoom: mapRef.current.getZoom(), bearing: mapRef.current.getBearing(), pitch: mapRef.current.getPitch() });
        }
        mapRef.current.remove();
        mapRef.current = null;
        setMapReady(false);
      }
    };
  }, [mapContainer, getMapControlPadding]);

  React.useEffect(() => {
    if (!mapReady || !mapContainer.current || typeof ResizeObserver === 'undefined') return;
    // Keep the canvas sized to its containing block, including responsive changes.
    const observer = new ResizeObserver(() => mapRef.current?.resize());
    observer.observe(mapContainer.current);
    return () => observer.disconnect();
  }, [mapReady, getMapControlPadding]);

  
  React.useEffect(() => {
    if (!mapRef.current || !mapReady) return;
    const markerMap = mapRef.current;
  (mapRef.current as any)._aqMarkers = (mapRef.current as any)._aqMarkers || [];
    (mapRef.current as any)._aqMarkers.forEach((marker: MapLibreMarker) => marker.remove());
    (mapRef.current as any)._aqMarkers = [];

    
    if (markerMap.getLayer(SPIDER_LINE_LAYER)) markerMap.removeLayer(SPIDER_LINE_LAYER);
    if (markerMap.getSource(SPIDER_LINE_SOURCE)) markerMap.removeSource(SPIDER_LINE_SOURCE);
    if (loading || error) return;

    const spiderLineFeatures: any[] = [];
  if (isEuropeanAqiActive) {
      europeanAirQualityIndexResults.forEach((result) => {
        if (typeof result.longitude !== 'number' || typeof result.latitude !== 'number') return;
        if (!europeanStandardMetadata || !effectiveEuropeanAirQualityIndexProduct) return;
        const presentation = getEuropeanAqiMarkerPresentation(
          result,
          europeanStandardMetadata,
          effectiveEuropeanAirQualityIndexProduct,
        );
        const markerElement = document.createElement('button');
        markerElement.type = 'button';
        markerElement.className = `european-aqi-marker${presentation.isPartial ? ' european-aqi-marker--partial' : ''}${presentation.isAvailable ? '' : ' european-aqi-marker--unavailable'}`;
        markerElement.style.backgroundColor = presentation.color;
        markerElement.textContent = presentation.markerText;
        markerElement.title = presentation.accessibleLabel;
        markerElement.setAttribute('aria-label', presentation.accessibleLabel);
        markerElement.dataset.mapMarkerKey = `european-${result.device_id}`;
        markerElement.tabIndex = 0;
        markerElement.setAttribute('role', 'button');
        markerElement.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); markerElement.click(); } });
        markerElement.addEventListener('click', (event) => {
          detailTriggerRef.current = markerElement;
          markerElement.focus({ preventScroll: true });
          event.stopPropagation();
          setSelectedEuropeanAirQualityIndexResult(result);
          setSelectedMeasurement(null);
          setSelectedSite(null);
        });
        const marker = new maplibregl.Marker({ element: markerElement })
          .setLngLat([result.longitude, result.latitude])
          .addTo(mapRef.current!);
        (mapRef.current as any)._aqMarkers.push(marker);
      });
    } else if (mode === 'pollutants') {
      const valid = measurements.filter((m) => {
        const dev = m.device;
        return !!dev && typeof dev.latitude === 'number' && Number.isFinite(dev.latitude as number) && typeof dev.longitude === 'number' && Number.isFinite(dev.longitude as number);
      });
      const groups = new Map<string, Measurement[]>();
      valid.forEach((m) => {
        const key = `${m.device!.longitude},${m.device!.latitude}`;
        const arr = groups.get(key) || [];
        arr.push(m);
        groups.set(key, arr);
      });

      const computeSpiderPositions = (center: [number, number], n: number): Array<[number, number]> => {
        
        const [lng, lat] = center;
        if (!mapRef.current || n <= 1) return [[lng, lat]];
        const map = mapRef.current;
        const centerPx = map.project({ lng, lat });
        const r = Math.min(90, Math.max(36, 14 + n * 8)); 
        const positions: Array<[number, number]> = [];
        for (let i = 0; i < n; i++) {
          const angle = (2 * Math.PI * i) / n;
          const px: [number, number] = [centerPx.x + r * Math.cos(angle), centerPx.y + r * Math.sin(angle)];
          const ll = map.unproject(px as any);
          positions.push([ll.lng, ll.lat]);
        }
        return positions;
      };

      groups.forEach((list, key) => {
        const dev = list[0].device!;
        const isExpanded = expandedGroups.has(key);

        if (!isExpanded && list.length > 1) {
          
          const el = document.createElement('div');
          el.style.background = '#ffffff';
          el.style.borderRadius = '999px';
          el.style.width = '28px';
          el.style.height = '28px';
          el.style.display = 'flex';
          el.style.alignItems = 'center';
          el.style.justifyContent = 'center';
          el.style.fontSize = '12px';
          el.style.fontWeight = '600';
          const groupAqiColor =
            isAqiActive && typeof list[0]?.value === 'number'
              ? getAqiColor(list[0].value)
              : '#6b7280'; 
          el.style.color = groupAqiColor;
          
          el.style.border = `1px solid ${DEVICE_MARKER_COLOR}`;
          el.style.boxShadow = '0 2px 6px #0003';
          el.style.cursor = 'pointer';
          el.title = i18n.t('map:mapLibreMap.dynamic.expandSensors', { count: list.length });
          el.textContent = String(list.length);

          el.tabIndex = 0;
          el.setAttribute('role', 'button');
          el.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); el.click(); } });
          el.addEventListener('click', (ev) => {
            detailTriggerRef.current = el;
            el.focus({ preventScroll: true });
            ev.preventDefault();
            ev.stopPropagation();
            setExpandedGroups((prev) => new Set([...prev, key]));
            setSelectedMeasurement(null);
            setSelectedSite(null);
          });

          const marker = new maplibregl.Marker({ element: el })
            .setLngLat([dev.longitude as number, dev.latitude as number])
            .addTo(mapRef.current!);
          (mapRef.current as any)._aqMarkers.push(marker);
          return;
        }

        
  const centerLngLat: [number, number] = [dev.longitude as number, dev.latitude as number];
        const positions = computeSpiderPositions(centerLngLat, list.length);

        if (list.length > 1 && isExpanded) {
          
          const hub = document.createElement('div');
          hub.style.background = '#f7f7f7';
          hub.style.border = '1px solid #888';
          hub.style.borderRadius = '999px';
          hub.style.width = '18px';
          hub.style.height = '18px';
          hub.style.display = 'flex';
          hub.style.alignItems = 'center';
          hub.style.justifyContent = 'center';
          hub.style.fontSize = '12px';
          hub.style.color = '#444';
          hub.style.cursor = 'pointer';
          hub.title = i18n.t('map:mapLibreMap.tooltips.collapse');
          hub.textContent = '×';
          hub.tabIndex = 0;
          hub.setAttribute('role', 'button');
          hub.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); hub.click(); } });
          hub.addEventListener('click', (ev) => {
            hub.focus({ preventScroll: true });
            ev.stopPropagation();
            setExpandedGroups((prev) => {
              const next = new Set(prev);
              next.delete(key);
              return next;
            });
            setSelectedMeasurement(null);
            setSelectedSite(null);
          });
          const hubMarker = new maplibregl.Marker({ element: hub })
            .setLngLat(centerLngLat)
            .addTo(mapRef.current!);
          (mapRef.current as any)._aqMarkers.push(hubMarker);
        }

        list.forEach((m, idx) => {
          const el = document.createElement('div');
          el.style.background = 'white';
          el.style.borderRadius = '4px';
          el.style.padding = '2px 6px';
          el.style.fontSize = '12px';
          el.style.boxShadow = '0 1px 4px #0002';
          
          const categoryOnlyColor = m.air_quality_index_result?.calculation_status === 'category_only'
            ? effectiveNumericStandardMetadata?.categories.find(
                (category) => category.code === m.air_quality_index_result?.category_code,
              )?.color
            : null;
          const aqiColor = categoryOnlyColor
            ?? (isAqiActive && typeof m.value === 'number' ? getAqiColor(m.value) : '#6b7280');
          
          el.style.border = `1px solid ${aqiColor}`;
          
          el.style.color = '#374151';
          el.style.fontWeight = '600';
          const formattedValue = m.air_quality_index_result?.calculation_status === 'category_only'
            ? m.air_quality_index_result.category_label ?? 'Unavailable'
            : isAqiActive
            ? formatAqiValue(m.value, displayMode === 'philippines_denr' ? 2 : 0)
            : formatValueForDisplay(m.parameter, m.value, activeAggregationCode, m.display_precision);
          const valueWithUnit = formattedValue !== '-'
            ? `${formattedValue} ${isAqiActive && m.air_quality_index_result?.calculation_status !== 'category_only' ? 'AQI' : (!isAqiActive ? m.unit ?? '' : '')}`.trim()
            : '-';
          el.innerText = valueWithUnit;
          el.title = isAqiActive
            ? `${(m.parameter || '').toUpperCase()} ${activeAqiLabel}: ${valueWithUnit}`.trim()
            : `${(m.parameter || '').toUpperCase()} ${valueWithUnit}`.trim();
          (el.style as any).zIndex = String(200 + idx);

          const childLngLat = positions[idx] || centerLngLat;
          if (list.length > 1 && isExpanded) {
            spiderLineFeatures.push({
              type: 'Feature',
              geometry: { type: 'LineString', coordinates: [centerLngLat, childLngLat] },
              properties: {},
            });
          }

          const marker = new maplibregl.Marker({ element: el })
            .setLngLat(childLngLat)
            .addTo(mapRef.current!);
          
          el.dataset.mapMarkerKey = `measurement-${m.device?.device_id ?? 0}-${m.measurement_id}-${m.sensor_id ?? idx}`;
          el.tabIndex = 0;
          el.setAttribute('role', 'button');
          el.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); el.click(); } });
          el.addEventListener('click', (ev) => {
            detailTriggerRef.current = el;
            el.focus({ preventScroll: true });
            ev.stopPropagation();
            setSelectedMeasurement(m);
            setSelectedSite(null);
          });
          
          (mapRef.current as any)._aqMarkers.push(marker);
        });
      });
    } else {
  
      sites.forEach((s) => {
        if (typeof s.longitude !== 'number' || typeof s.latitude !== 'number') return;
        const el = document.createElement('div');
        el.style.background = '#ffffff';
        el.style.border = `2px solid ${DEVICE_MARKER_COLOR}`;
        el.style.borderRadius = '999px';
        el.style.width = '14px';
        el.style.height = '14px';
        el.style.boxShadow = '0 2px 6px #0003';
        el.title = s.name || i18n.t('map:mapLibreMap.dynamic.device', { id: s.device_id });
        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([s.longitude as number, s.latitude as number])
          .addTo(mapRef.current!);
        el.dataset.mapMarkerKey = `device-${s.device_id}`;
        el.tabIndex = 0;
        el.setAttribute('role', 'button');
        el.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); el.click(); } });
        el.addEventListener('click', (ev) => {
          detailTriggerRef.current = el;
          el.focus({ preventScroll: true });
          ev.stopPropagation();
          setSelectedSite(s);
          setSelectedMeasurement(null);
        });
        (mapRef.current as any)._aqMarkers.push(marker);
      });
    }

  
  if (mapRef.current && mode === 'pollutants') {
      const map = mapRef.current;
      const data = { type: 'FeatureCollection', features: spiderLineFeatures } as any;
      const src = map.getSource(SPIDER_LINE_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) {
        try { (src as any).setData(data); } catch { void 0; }
      } else {
        try {
          map.addSource(SPIDER_LINE_SOURCE, { type: 'geojson', data });
          map.addLayer({
            id: SPIDER_LINE_LAYER,
            type: 'line',
            source: SPIDER_LINE_SOURCE,
            paint: { 'line-color': '#4A6CF7', 'line-width': 1.5, 'line-opacity': 0.75 },
            layout: { 'line-cap': 'round', 'line-join': 'round' },
          });
        } catch {
          
          void 0;
        }
      }
    } else if (mapRef.current && mode === 'devices') {
      
      try {
        const map = mapRef.current;
        if (map.getLayer(SPIDER_LINE_LAYER)) map.removeLayer(SPIDER_LINE_LAYER);
        if (map.getSource(SPIDER_LINE_SOURCE)) map.removeSource(SPIDER_LINE_SOURCE);
      } catch {
        void 0;
      }
    }

    
    
    
    return () => {
      (markerMap as any)._aqMarkers.forEach((marker: MapLibreMarker) => marker.remove());
      (markerMap as any)._aqMarkers = [];
    };
  }, [loading, error, measurements, sites, europeanAirQualityIndexResults, mapReady, expandedGroups, mode, formatValueForDisplay, activeAggregationCode, activeAqiLabel, disableAutoFit, isAqiActive, isEuropeanAqiActive, europeanStandardMetadata, effectiveEuropeanAirQualityIndexProduct, effectiveNumericStandardMetadata, displayMode]);

  
  React.useEffect(() => {
    // A filter change replaces marker data but must not re-arm the one-time
    // initial camera positioning.
    const previousContext = previousSelectionContextRef.current;
    previousSelectionContextRef.current = { parameter, mode, displayMode };
    const isUsEpaProductSwitch = previousContext.displayMode === 'us_epa'
      && displayMode === 'us_epa'
      && previousContext.mode === mode;
    if (isUsEpaProductSwitch) return;
    setSelectedMeasurement(null);
    setSelectedSite(null);
    setSelectedEuropeanAirQualityIndexResult(null);
  }, [parameter, mode, displayMode]);

  React.useEffect(() => {
    if (!mapRef.current) return;
    try {
      mapRef.current.setPadding({ top: 0, right: getMapControlPadding(), bottom: 0, left: 0 });
    } catch {
      void 0;
    }
  }, [mapReady, getMapControlPadding]);

  
  React.useEffect(() => {
    setExpandedGroups(new Set());
  }, [parameter, mode]);

  
  React.useEffect(() => {
    if (!mapRef.current || !mapReady) return;
    
    
    const isManualFitRequest = fitTrigger !== lastFitTriggerRef.current;
    lastFitTriggerRef.current = fitTrigger;
    // Refreshed data stays in the current viewport. Only an explicit fit
    // trigger may change the camera after initial map positioning.
    if (!isManualFitRequest) return;
    
  const pts = isEuropeanAqiActive
    ? europeanAirQualityIndexResults.filter((result) => typeof result.longitude === 'number' && typeof result.latitude === 'number')
    : mode === 'pollutants'
    ? measurements
      .map((m) => m.device)
      .filter((dev): dev is NonNullable<NonNullable<Measurement['device']>> => !!dev && typeof dev.longitude === 'number' && typeof dev.latitude === 'number')
      : sites
          .filter((s): s is DevicePoint => typeof s.longitude === 'number' && typeof s.latitude === 'number');
    if (pts.length < 1) return;
    const first = pts[0];
    const firstLng = mode === 'pollutants' ? (first as any).longitude as number : (first as any).longitude as number;
    const firstLat = mode === 'pollutants' ? (first as any).latitude as number : (first as any).latitude as number;
    const bounds = pts.reduce((b: any, loc: any) => b.extend([loc.longitude as number, loc.latitude as number]), new maplibregl.LngLatBounds([firstLng, firstLat], [firstLng, firstLat]));
    try {
      try { mapRef.current.resize(); } catch { void 0; }
      try {
        mapRef.current.fitBounds(bounds, {
          padding: { top: MAP_TOOLBAR_SAFE_PADDING, bottom: 48, left: 48, right: 48 + getMapControlPadding() },
          duration: 500,
          maxZoom: 12,
        });
      } catch { void 0; }
      
      window.setTimeout(() => {
        try { mapRef.current?.resize(); } catch { void 0; }
        try {
          mapRef.current?.fitBounds(bounds, {
            padding: { top: MAP_TOOLBAR_SAFE_PADDING, bottom: 48, left: 48, right: 48 + getMapControlPadding() },
            duration: 500,
            maxZoom: 12,
          });
        } catch { void 0; }
      }, 250);
    } catch {
      
      void 0;
    }
    
    
    initialViewportPendingRef.current = false;
  }, [fitTrigger, mode, measurements, sites, europeanAirQualityIndexResults, mapReady, isEuropeanAqiActive, disableAutoFit, getMapControlPadding]);

  
  React.useEffect(() => {
    if (!mapReady || loading || initialDeviceId == null
      || initiallyCenteredDeviceIdRef.current === initialDeviceId) return;
    const aqiResult = europeanAirQualityIndexResults.find(result => result.device_id === initialDeviceId);
    const measurement = measurements.find(result => result.device?.device_id === initialDeviceId);
    const site = sites.find(result => result.device_id === initialDeviceId);
    const point = isEuropeanAqiActive ? aqiResult : mode === 'devices' ? site : measurement?.device;
    if (!point || point.longitude == null || point.latitude == null) return;
    initiallyCenteredDeviceIdRef.current = initialDeviceId;
    if (isEuropeanAqiActive && aqiResult) setSelectedEuropeanAirQualityIndexResult(aqiResult);
    else if (mode === 'devices' && site) setSelectedSite(site);
    else if (measurement) setSelectedMeasurement(measurement);
    mapRef.current?.easeTo({ center: [point.longitude, point.latitude], zoom: 10 });
  }, [initialDeviceId, mapReady, loading, europeanAirQualityIndexResults, measurements, sites, isEuropeanAqiActive, mode]);

  React.useEffect(() => {
    const isResetRequest = resetTrigger !== lastResetTriggerRef.current;
    // Reset uses location/default camera only, never mode-specific result data.
    if (!isResetRequest) return;
    if (!mapRef.current || !mapReady) return;
    lastResetTriggerRef.current = resetTrigger;
    initialViewportPendingRef.current = false;
    let center: [number, number] = [0, 0];
    let zoom = 2;
    if (userPosRef.current) {
      center = [userPosRef.current.lng, userPosRef.current.lat];
      zoom = 10;
    }
    try {
      mapRef.current.flyTo({ center, zoom, duration: 500 });
    } catch {
      
      void 0;
    }
  }, [resetTrigger, mapReady]);

  
  React.useEffect(() => {
    if (flyToCoords || disableAutoFit) initialViewportPendingRef.current = false;
    if (!mapRef.current || !mapReady || !flyToCoords) return;
    
    
    try {
      mapRef.current.flyTo({
        center: [flyToCoords.lng, flyToCoords.lat],
        zoom: flyToCoords.zoom,
        duration: 1200,
        essential: true, // this animation is essential with respect to prefers-reduced-motion
      });
    } catch {
      
      void 0;
    }
  }, [flyToCoords, mapReady, disableAutoFit]);

  
  // These lists have no viewport constraint; panning does not refetch them.
  // Keep unavailable AQI markers: their backend-provided reasons are meaningful.
  const locations = React.useMemo(() => {
    const candidates = isEuropeanAqiActive ? europeanAirQualityIndexResults
      : mode === 'pollutants' ? measurements.map(measurement => measurement.device) : sites;
    return candidates.filter((point): point is { longitude: number; latitude: number } =>
      point != null && typeof point.longitude === 'number' && Number.isFinite(point.longitude)
      && typeof point.latitude === 'number' && Number.isFinite(point.latitude));
  }, [isEuropeanAqiActive, europeanAirQualityIndexResults, mode, measurements, sites]);
  const markerCount = React.useMemo(() => {
    // Reading the current bounds after moveend also handles antimeridian wrapping.
    void mapBoundingBox;
    const bounds = mapRef.current?.getBounds();
    if (!bounds) return locations.length;
    return locations.filter(point => {
      const west = bounds.getWest();
      const east = bounds.getEast();
      const longitude = ((point.longitude - west) % 360 + 360) % 360 + west;
      return point.latitude >= bounds.getSouth() && point.latitude <= bounds.getNorth()
        && (east - west >= 360 || longitude <= east);
    }).length;
  }, [locations, mapBoundingBox]);

  React.useEffect(() => {
    if (!initialViewportPendingRef.current || !mapReady || loading || error) return;
    initialViewportPendingRef.current = false;
    if (disableAutoFit || flyToCoords || initialDeviceId != null) return;
    const map = mapRef.current;
    if (!map || (userPosRef.current && markerCount > 0)) return;
    if (locations.length === 0) {
      map.fitBounds(new maplibregl.LngLatBounds([-180, -85], [180, 85]), {
        padding: 48, duration: 0,
      });
      return;
    }
    const first = locations[0];
    const bounds = new maplibregl.LngLatBounds([first.longitude, first.latitude], [first.longitude, first.latitude]);
    locations.forEach(point => bounds.extend([point.longitude, point.latitude]));
    const singleLocation = locations.every(point => point.longitude === first.longitude && point.latitude === first.latitude);
    map.fitBounds(bounds, {
      padding: { top: MAP_TOOLBAR_SAFE_PADDING, bottom: 48, left: 48, right: 48 + getMapControlPadding() },
      duration: 500,
      maxZoom: singleLocation ? 5 : 12,
    });
  }, [mapReady, loading, error, locations, markerCount, disableAutoFit, flyToCoords, initialDeviceId, getMapControlPadding]);


  return (
    <div className="map-container">
      {loading && !mapUnavailable && (
        <div className="map-loading" role="status">
          {isAqiActive
            ? i18n.t('map:mapLibreMap.dynamic.loadingAqi', { label: activeAqiLabel })
            : isEuropeanAqiActive
              ? i18n.t('map:mapLibreMap.text.loadingEuropeanAirQualityIndex')
              : i18n.t('map:mapLibreMap.text.loadingMapData')}
        </div>
      )}
      {mapUnavailable && <div className="map-error" role="alert"><Trans ns="map" i18nKey="mapLibreMap.text.webGl2Unavailable" /></div>}
      {!mapUnavailable && error && <div className="map-error" role="alert"><Trans ns="map" i18nKey="mapLibreMap.text.error" />{' '}{error}</div>}
      <div ref={mapContainer} className="map-canvas" />
      
      
      {(!loading || (isEuropeanAqiActive && europeanAirQualityIndexResults.length > 0)) && !error && !mapUnavailable && (
        <div className="map-legend-container">
          
          {isAqiActive && (
            <AqiLegend compact showNoData standardMetadata={effectiveNumericStandardMetadata} />
          )}
          {isEuropeanAqiActive && europeanStandardMetadata && effectiveEuropeanAirQualityIndexProduct && (
            <EuropeanAqiLegend
              standardMetadata={europeanStandardMetadata}
              product={effectiveEuropeanAirQualityIndexProduct}
            />
          )}
          
          
          <div className="map-status-bar">
            <span className="map-status-bar__count">
              {isEuropeanAqiActive
                ? i18n.t('map:mapLibreMap.counts.europeanAqiResult', { count: markerCount })
                : isAqiActive
                  ? i18n.t('map:mapLibreMap.counts.aqiResult', { count: markerCount })
                  : mode === 'pollutants'
                    ? i18n.t('map:mapLibreMap.counts.measurement', { count: markerCount })
                    : i18n.t('map:mapLibreMap.counts.device', { count: markerCount })}
            </span>
            <span className="map-status-bar__separator" />
            <LastUpdated
              timestamp={lastDataUpdate}
              autoRefresh
              refreshInterval={60}
              onRefresh={refreshMapData}
              showEmptyText={mode !== 'devices'}
            />
          </div>
        </div>
      )}
      
      
      {!loading && !error && !mapUnavailable && markerCount === 0 && (
        <MapEmptyState layer={isAqiActive || isEuropeanAqiActive ? 'aqi' : mode === 'devices' ? 'devices' : 'measurements'} />
      )}
      
      
      {/* Visiting controls temporarily hides the mobile sheet. Only explicit
          dismissal or an incompatible context change clears its selection. */}
      <MapSurface narrow={narrowMap} returnFocusRef={detailTriggerRef}
        open={Boolean(measurementSelection || selectedSite || selectedEuropeanAirQualityIndexResult) && !(narrowMap && controlsOpen)}
        onClose={() => { setSelectedMeasurement(null); setSelectedSite(null); setSelectedEuropeanAirQualityIndexResult(null); }}
        label={i18n.t('map:mapLibreMap.accessibility.deviceDetails')}
        className={`slide-out-panel ${measurementSelection || selectedSite || selectedEuropeanAirQualityIndexResult ? 'open' : ''}`}>

        {selectedEuropeanAirQualityIndexResult && europeanStandardMetadata && effectiveEuropeanAirQualityIndexProduct && (
          <EuropeanAqiDetails
            result={selectedEuropeanAirQualityIndexResult}
            standardMetadata={europeanStandardMetadata}
            product={effectiveEuropeanAirQualityIndexProduct}
            onClose={() => setSelectedEuropeanAirQualityIndexResult(null)}
          />
        )}
        
        {measurementSelection && !selectedEuropeanAirQualityIndexResult && (() => {
          const panelContext = selectedMeasurement ?? measurementSelection;
          const deviceName = panelContext.device?.friendly_name
            || panelContext.device?.name
            || i18n.t('map:mapLibreMap.states.unknownDevice');
          const paramDisplay = getParameterDisplayName(panelContext.parameter, panelContext.parameter_name);
          const panelContextDisplay = isAqiActive
            ? selectedAirQualityIndexProduct
              ? getAirQualityIndexProductLabel(selectedAirQualityIndexProduct.product_code)
              : i18n.t('map:app.options.aqi')
            : paramDisplay;
          const dataSource = isAqiActive
            ? selectedMeasurement?.device?.network ?? null
            : (selectedMeasurement?.device as any)?.external_api?.name || null;
          return (
            <>
              <div className="panel-header-compact">
                <div className="panel-title-section">
                  <h3 className="panel-title">{deviceName}</h3>
                  <span className="panel-subtitle">
                    {panelContextDisplay}
                  </span>
                  {dataSource && (
                    <div style={{ marginTop: '6px' }}>
                      <DataSourceBadge source={dataSource} size="sm" />
                    </div>
                  )}
                </div>
                <button 
                  className="close-button" 
                  onClick={() => { setSelectedMeasurement(null); setSelectedSite(null); }}
                  aria-label={i18n.t('map:mapLibreMap.accessibility.closePanel')}
                >
                  ×
                </button>
              </div>
              
              <div className="panel-content-compact">
                {narrowMap && displayMode === 'measurements' && onOpenControls && (
                  <button type="button" className="btn" aria-haspopup="dialog" onClick={onOpenControls}>
                    {i18n.t('map:app.actions.mapControls')}
                  </button>
                )}
                {(() => {
                  const displayMeasurement = selectedMeasurement;
                  const resultPending = loading || measurementsRequestKey !== activeMeasurementsRequestKey;
                  const resultError = measurementsRequestKey === activeMeasurementsRequestKey ? error : null;
                  if (!displayMeasurement) return (
                    <div className={resultError ? 'panel-error-msg' : resultPending ? 'panel-loading' : 'empty-chart'} role={resultError ? 'alert' : 'status'}>
                      {resultError || i18n.t(resultPending
                        ? 'map:mapLibreMap.text.loadingMeasurements' : 'map:mapLibreMap.text.selectedMeasurementUnavailable')}
                    </div>
                  );
                  const airQualityIndexResult = displayMeasurement.air_quality_index_result;
                  const isCompletedDayProductSelected = isAqiActive
                    && selectedAirQualityIndexProduct?.product_kind === 'completed_day';
                  const isCompletedDayResult = isAqiActive
                    && airQualityIndexResult?.product_kind === 'completed_day';
                  const historyLatestRepresentedLocalDate = isCompletedDayProductSelected
                    && airQualityIndexResult?.product_code === selectedAirQualityIndexProduct?.product_code
                    ? airQualityIndexResult.represented_local_date ?? null
                    : null;
                  const historyLatestObservedAt = airQualityIndexResult?.product_code === 'us_epa.o3.latest'
                    ? airQualityIndexResult.ozone_8_hour_candidate?.interval_ended_at
                      ?? displayMeasurement.observed_at
                    : displayMeasurement.observed_at;
                  const isCategoryOnly = airQualityIndexResult?.calculation_status === 'category_only';
                  const displayValue = isCategoryOnly
                    ? airQualityIndexResult?.category_label ?? '-'
                    : isAqiActive
                    ? formatAqiValue(
                        displayMeasurement.value,
                        displayMode === 'philippines_denr' ? 2 : 0,
                      )
                    : formatValueForDisplay(displayMeasurement.parameter, displayMeasurement.value, activeAggregationCode, displayMeasurement.display_precision);
                  const displayHeroValue = isAqiActive && displayValue === '-'
                    ? i18n.t('map:mapLibreMap.states.noAqiAvailable')
                    : displayValue;
                  const displayHeroUnit = isAqiActive
                    ? (displayValue === '-' || isCategoryOnly ? '' : 'AQI')
                    : displayMeasurement.unit ?? '';
                  const airQualityIndexAnalyticsPath = airQualityIndexResult
                    && selectedAirQualityIndexProduct
                    ? buildAirQualityIndexAnalyticsPath({
                        standard_code: airQualityIndexResult.standard_code,
                        product_code: selectedAirQualityIndexProduct.product_code,
                        device_id: airQualityIndexResult.device_id,
                        parameter_code: selectedAirQualityIndexProduct.parameter_code,
                        sensor_id: airQualityIndexResult.sensor_id,
                        external_api_name: airQualityIndexResult.source_name,
                        completed_day: isCompletedDayProductSelected,
                      })
                    : null;
                  
                  return (
                    <>
                      <div className={`measurement-hero${isAqiActive ? ' aqi-hero' : ''}`}>
                        <span className="hero-value">{displayHeroValue}</span>
                        <span className="hero-unit">{displayHeroUnit}</span>
                        {isAqiActive && !isCategoryOnly && airQualityIndexResult?.category_label && (
                          <span className="aqi-category-label">
                            {airQualityIndexResult.aqi_scale_status === 'above_500'
                              ? i18n.t('map:mapLibreMap.text.categoryAboveAqi500', {
                                  category: getAirQualityIndexCategoryLabel(airQualityIndexResult.category_code!),
                                })
                              : getAirQualityIndexCategoryLabel(airQualityIndexResult.category_code!)}
                          </span>
                        )}
                        {!isAqiActive && <MapMeasurementContext
                          resultAggregation={displayMeasurement.result_aggregation_code}
                          nativeAggregation={displayMeasurement.native_aggregation_code}
                          observedAt={displayMeasurement.observed_at}
                          isValid={displayMeasurement.is_valid}
                          isRolling={displayMeasurement.result_is_rolling}
                          intervalStartedAt={displayMeasurement.interval_started_at}
                          intervalEndedAt={displayMeasurement.interval_ended_at}
                          latestSourceObservedAt={displayMeasurement.latest_source_observed_at}
                        />}
                        {displayMeasurement.observed_at && !displayMeasurement.result_is_rolling && (
                          <span className="hero-time">{timeAgo(displayMeasurement.observed_at)}</span>
                        )}
                      </div>
                      {isAqiActive && isCategoryOnly && (
                        <div className="aqi-unavailable-message" role="status">
                          {getPhilippineAqiCategoryOnlyMessage()}
                        </div>
                      )}
                      {isAqiActive && displayValue === '-' && !isCategoryOnly && (
                        <div className="aqi-unavailable-message" role="status">
                          {isCompletedDayResult ? i18n.t('map:mapLibreMap.text.dailyAqiUnavailable') : i18n.t('map:mapLibreMap.text.aqiUnavailable')}: {getExclusionReasonLabel(
                            airQualityIndexResult?.exclusion_reason ?? 'missing_measurements',
                          )}.
                        </div>
                      )}
                      {isAqiActive && airQualityIndexResult && selectedAirQualityIndexProduct && effectiveNumericStandardMetadata && (
                        <div className="panel-chart-container">
                          <AqiTrendCard
                            standardMetadata={effectiveNumericStandardMetadata}
                            product={selectedAirQualityIndexProduct}
                            deviceId={displayMeasurement.device?.device_id ?? null}
                            deviceName={deviceName}
                            sourceName={airQualityIndexResult.source_name}
                            latestObservedAt={historyLatestObservedAt}
                            latestRepresentedLocalDate={historyLatestRepresentedLocalDate}
                          />
                        </div>
                      )}

                      {isAqiActive && airQualityIndexResult && (
                        <details className="aqi-secondary-details">
                          <summary><Trans ns="map" i18nKey="mapLibreMap.text.aqiDetails" /></summary>
                          <div className="aqi-secondary-details__content">
                            {airQualityIndexResult.exclusion_reason && (
                              <p>{getExclusionReasonLabel(airQualityIndexResult.exclusion_reason)}</p>
                            )}
                            {isCompletedDayResult && airQualityIndexResult.represented_local_date && (
                              <div className="text-sm text-slate-700" data-testid="completed-day-date">
                                {i18n.t('map:mapLibreMap.dynamic.completedDay', {
                                  date: formatCompletedLocalDate(airQualityIndexResult.represented_local_date),
                                })}
                              </div>
                            )}
                            {airQualityIndexResult.product_kind === 'nowcast'
                              && airQualityIndexResult.expected_observation_count != null && (
                              <div className="text-sm text-slate-600">
                                {i18n.t('map:mapLibreMap.dynamic.nowcastCoverage', {
                                  valid: airQualityIndexResult.valid_observation_count ?? 0,
                                  expected: airQualityIndexResult.expected_observation_count,
                                  status: getAirQualityIndexCoverageStatusLabel(airQualityIndexResult.coverage_status ?? null),
                                })}
                              </div>
                            )}
                            {(airQualityIndexResult.product_kind === 'nowcast'
                              || airQualityIndexResult.product_kind === 'completed_day')
                              && airQualityIndexResult.preprocessed_concentration != null
                              && airQualityIndexResult.normalized_unit && (
                              <div className="text-sm text-slate-700" data-testid="aqi-selected-concentration">
                                {i18n.t('map:mapLibreMap.dynamic.selectedConcentration', {
                                  value: airQualityIndexResult.preprocessed_concentration,
                                  unit: airQualityIndexResult.normalized_unit,
                                })}
                              </div>
                            )}
                            {(airQualityIndexResult.product_kind === 'nowcast'
                              || airQualityIndexResult.product_kind === 'completed_day')
                              && airQualityIndexResult.window_started_at
                              && airQualityIndexResult.window_ended_at && (
                              <div className="text-sm text-slate-600" data-testid="aqi-selected-interval">
                                {i18n.t('map:mapLibreMap.dynamic.selectedInterval', {
                                  interval: formatUtcInterval(
                                    airQualityIndexResult.window_started_at,
                                    airQualityIndexResult.window_ended_at,
                                  ),
                                })}
                              </div>
                            )}
                            {airQualityIndexResult.product_kind === 'latest_window'
                              && airQualityIndexResult.product_code === 'us_epa.o3.latest' && (
                              <UsEpaOzoneDetails result={airQualityIndexResult} />
                            )}
                            {airQualityIndexResult.product_kind === 'latest_window'
                              && (airQualityIndexResult.product_code === 'us_epa.co.latest'
                                || airQualityIndexResult.product_code === 'us_epa.no2.latest') && (
                              <UsEpaGasDetails result={airQualityIndexResult} />
                            )}
                            {airQualityIndexResult.product_kind === 'latest_window'
                              && airQualityIndexResult.product_code === 'us_epa.so2.latest' && (
                              <UsEpaSo2Details result={airQualityIndexResult} />
                            )}
                            {isCompletedDayResult
                              && airQualityIndexResult.expected_hour_count != null
                              && airQualityIndexResult.required_valid_hour_count != null && (
                              <div className="text-sm text-slate-600" data-testid="completed-day-completeness">
                                {i18n.t('map:mapLibreMap.dynamic.completedDayCompleteness', {
                                  valid: airQualityIndexResult.valid_hour_count ?? 0,
                                  expected: airQualityIndexResult.expected_hour_count,
                                  required: airQualityIndexResult.required_valid_hour_count,
                                })}
                              </div>
                            )}
                            {airQualityIndexResult.latest_completed_hour_valid_observation_count != null
                              && airQualityIndexResult.latest_completed_hour_expected_observation_count != null
                              && airQualityIndexResult.latest_completed_hour_required_observation_count != null && (
                              <div className="text-sm text-slate-600" data-testid="aqi-hourly-completeness">
                                {i18n.t('map:mapLibreMap.dynamic.latestHourCompleteness', {
                                  valid: airQualityIndexResult.latest_completed_hour_valid_observation_count,
                                  expected: airQualityIndexResult.latest_completed_hour_expected_observation_count,
                                  required: airQualityIndexResult.latest_completed_hour_required_observation_count,
                                })}
                              </div>
                            )}
                          </div>
                        </details>
                      )}
                      
                      
                      {!isAqiActive && <div className="panel-chart-container">
                        {displayMeasurement.sensor_id != null ? (
                          measurementHistoryChart
                        ) : (
                          <div className="empty-chart"><Trans ns="map" i18nKey="mapLibreMap.text.noChartDataAvailable2" /></div>
                        )}
                      </div>}

                      
                      {displayMeasurement.device && (
                        <div className="meta-row">
                          <CopyableCoordinates
                            latitude={displayMeasurement.device.latitude}
                            longitude={displayMeasurement.device.longitude}
                          />
                          {displayMeasurement.device.timezone && (
                            <span className="meta-timezone" title={i18n.t('map:mapLibreMap.tooltips.deviceTimezone')}>
                              {formatTimezoneWithOffset(displayMeasurement.device.timezone)}
                            </span>
                          )}
                        </div>
                      )}

                      
                      {!isAqiActive && displayMeasurement.sensor_id != null && (
                        <div className="panel-actions">
                          <Link
                            className="btn btn-primary"
                            to={historyUnsupported ? '/analytics' : `/analytics?series=${encodeURIComponent(`measurement|${displayMeasurement.sensor_id}|${(displayMeasurement.parameter || '').toLowerCase()}|${timeResolution || displayMeasurement.result_aggregation_code || displayMeasurement.native_aggregation_code || 'raw'}`)}&recency=24h`}
                          >
                            <Trans ns="map" i18nKey="mapLibreMap.actions.openFullAnalytics" /></Link>
                        </div>
                      )}

                      <DataAttribution value={displayMeasurement.device?.data_attribution} />
                      {isAqiActive && airQualityIndexAnalyticsPath && (
                        <div className="panel-actions">
                          <Link className="btn btn-primary" to={airQualityIndexAnalyticsPath}>
                            <Trans ns="map" i18nKey="mapLibreMap.actions.openFullAnalytics2" /></Link>
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            </>
          );
        })()}

        
        {selectedSite && !selectedMeasurement && !selectedEuropeanAirQualityIndexResult && (() => {
          const deviceName = selectedSite.friendly_name
            || selectedSite.name
            || i18n.t('map:mapLibreMap.states.unnamedDevice');
          const dataSource = selectedSite.network || null;
          const sensors = orderedDeviceSensors ?? [];
          const activeSensor = activeDeviceSensor;
          const hasSensors = sensors.length > 0;
          const hasMultipleSensors = sensors.length > 1;
          
          return (
            <>
              <div className="panel-header-compact">
                <div className="panel-title-section">
                  <h3 className="panel-title">{deviceName}</h3>
                  <span className="panel-subtitle">
                    {dataSource && <DataSourceBadge source={dataSource} size="sm" />}
                    {typeof selectedSite.sensor_count === 'number' && (
                      <span>{selectedSite.sensor_count} {' '}<Trans ns="map" i18nKey="mapLibreMap.text.sensor" />{selectedSite.sensor_count !== 1 ? 's' : ''}</span>
                    )}
                  </span>
                </div>
                <button 
                  className="close-button" 
                  onClick={() => { setSelectedMeasurement(null); setSelectedSite(null); }}
                  aria-label={i18n.t('map:mapLibreMap.accessibility.closePanel2')}
                >
                  ×
                </button>
              </div>
              
              <div className="panel-content-compact">
                
                {deviceSensorsLoading && (
                  <div className="panel-loading"><Trans ns="map" i18nKey="mapLibreMap.text.loadingSensors" /></div>
                )}
                
                
                {deviceSensorsError && !deviceSensorsLoading && (
                  <div className="panel-error-msg">{deviceSensorsError}</div>
                )}
                
                
                {!deviceSensorsLoading && hasSensors === false && !deviceSensorsError && (
                  <div className="panel-empty" role="status"><Trans ns="map" i18nKey={activeSensorId != null
                    ? 'mapLibreMap.text.selectedMeasurementUnavailable' : 'mapLibreMap.text.noSensorsFoundDevice'} /></div>
                )}
                {!deviceSensorsLoading && hasSensors && !activeSensor && !deviceSensorsError && (
                  <div className="panel-empty" role="status"><Trans ns="map" i18nKey="mapLibreMap.text.selectedMeasurementUnavailable" /></div>
                )}
                
                
                {!deviceSensorsLoading && hasSensors && activeSensor && (
                  <>
                    
                    {hasMultipleSensors && (
                      <div className="sensor-tabs">
                        {sensors.map((s) => {
                          const isActive = s.sensor_id === activeSensorId;
                          return (
                            <button
                              key={s.sensor_id}
                              className={`sensor-tab${isActive ? ' active' : ''}`}
                              onClick={() => setActiveSensorId(s.sensor_id)}
                              title={getParameterDisplayName(s.parameter, s.parameter_name)}
                            >
                              {getParameterDisplayName(s.parameter, s.parameter_name).length > 12
                                ? getParameterDisplayName(s.parameter, s.parameter_name).substring(0, 10) + '…'
                                : getParameterDisplayName(s.parameter, s.parameter_name)}
                            </button>
                          );
                        })}
                      </div>
                    )}
                    
                    
                    {(() => {
                      const formattedValue = formatValueForDisplay(
                        activeSensor.parameter,
                        activeSensor.latest_value ?? null,
                        activeAggregationCode,
                        activeSensor.display_precision,
                      );
                      const displayUnit = activeSensor.unit ?? '';
                      
                      return (
                        <div className="active-sensor-display">
                          <h4 className="map-active-parameter">{getParameterDisplayName(activeSensor.parameter, activeSensor.parameter_name)}</h4>
                          
                          <div className="measurement-hero">
                            <span className="hero-value">{formattedValue}</span>
                            <span className="hero-unit">{displayUnit}</span>
                            <MapMeasurementContext
                              resultAggregation={activeSensor.result_aggregation_code}
                              nativeAggregation={activeSensor.native_aggregation_code}
                              observedAt={activeSensor.latest_observed_at}
                              isValid={activeSensor.latest_is_valid}
                              isRolling={activeSensor.result_is_rolling}
                              intervalStartedAt={activeSensor.interval_started_at}
                              intervalEndedAt={activeSensor.interval_ended_at}
                              latestSourceObservedAt={activeSensor.latest_source_observed_at}
                            />
                            {activeSensor.latest_observed_at && !activeSensor.result_is_rolling && (
                              <span className={`hero-time`}>
                                {timeAgo(activeSensor.latest_observed_at)}
                              </span>
                            )}
                          </div>
                          
                          
                          <div className="panel-chart-container">
                            {measurementHistoryChart}
                          </div>
                          
                          
                          <div className="meta-row">
                            <CopyableCoordinates
                              latitude={selectedSite.latitude}
                              longitude={selectedSite.longitude}
                            />
                            {selectedSite.timezone && (
                              <span className="meta-timezone" title={i18n.t('map:mapLibreMap.tooltips.deviceTimezone2')}>
                                {formatTimezoneWithOffset(selectedSite.timezone)}
                              </span>
                            )}
                          </div>
                          
                          
                          <div className="panel-actions">
                            <Link
                              className="btn btn-primary"
                              to={historyUnsupported ? '/analytics' : `/analytics?series=${encodeURIComponent(`measurement|${activeSensor.sensor_id}|${(activeSensor.parameter || '').toLowerCase()}|${timeResolution || activeSensor.result_aggregation_code || activeSensor.native_aggregation_code || 'raw'}`)}&recency=24h`}
                            >
                              <Trans ns="map" i18nKey="mapLibreMap.actions.openFullAnalytics3" /></Link>
                          </div>
                        </div>
                      );
                    })()}
                  </>
                )}
                <DataAttribution value={selectedSite.data_attribution} />
              </div>
            </>
          );
        })()}
      </MapSurface>
    </div>
  );
};

export default MapLibreMap;
