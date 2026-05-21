import * as React from 'react';
import { Link } from 'react-router-dom';
import maplibregl, { Map as MapLibreMapGL, Marker as MapLibreMarker } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './App.css';
import { fetchJson } from './api';
import SensorChart from './SensorChart';
import { describeAqiResolution, formatAqiValue, getAqiColor, isAqiResolution, getAqiDisplayName, AQI_POLLUTANTS, getAqiAggregationCode, getAggregationDisplayLabel } from './aqi';
import AqiLegend from './components/AqiLegend';
import LastUpdated from './components/LastUpdated';
import DataSourceBadge from './components/DataSourceBadge';
import MapEmptyState from './components/MapEmptyState';
import CopyableCoordinates from './components/CopyableCoordinates';
import { formatTimezoneWithOffset } from './utils/timezone';


interface Measurement {
  measurement_id: number;
  sensor_id?: number | null;
  external_sensor_id?: string | null;
  value: number;
  parameter: string;
  unit: string | null;
  observed_at: string | null;
  device?: { device_id?: number | null; name?: string | null; friendly_name?: string | null; latitude?: number | null; longitude?: number | null; network?: string | null; timezone?: string | null } | null;
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
}

interface ParameterAggregationRule {
  parameter_code: string;
  aggregation_code: string;
  rounding_method?: string | null;
  rounding_precision?: number | null;
  truncation_method?: string | null;
  truncation_precision?: number | null;
}

type Props = {
  parameter: string; 
  mode?: 'pollutants' | 'devices';
  fitTrigger?: number; 
  resetTrigger?: number; 
  flyToCoords?: { lat: number; lng: number; zoom: number } | null; 
  disableAutoFit?: boolean; 
  recency?: 'all' | '24h' | '1h' | 'custom';
  timeResolution?: string;
  aggregationRules?: ParameterAggregationRule[];
  aggregationRollups?: { parameter_code: string; from_period_code: string; from_period_display: string; to_period_code: string; to_period_display: string }[];
  customStartIso?: string | null;
  customEndIso?: string | null;
  sourceFilter?: string; 
};

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'; 
const MAP_CONTROL_SAFE_PADDING = 72;  
const MAP_TOOLBAR_SAFE_PADDING = 100; 
const DEVICE_MARKER_COLOR = '#0B5FFF';


const CACHE: Record<string, Measurement[] | undefined> = {};
const INFLIGHT: Record<string, Promise<Measurement[]> | undefined> = {};
const SITES_CACHE: Record<string, DevicePoint[] | undefined> = {};
const SITES_INFLIGHT: Record<string, Promise<DevicePoint[]> | undefined> = {};
const PARAM_DEVICES_CACHE: Record<string, Set<number> | undefined> = {};
const PARAM_DEVICES_INFLIGHT: Record<string, Promise<Set<number>> | undefined> = {};
const DEVICE_SENSORS_CACHE: Record<number, DeviceSensor[] | undefined> = {};
const DEVICE_SENSORS_INFLIGHT: Record<number, Promise<DeviceSensor[]> | undefined> = {};
const ACTIVE_DEVICES_CACHE: Record<string, Set<number> | undefined> = {};
const ACTIVE_DEVICES_INFLIGHT: Record<string, Promise<Set<number>> | undefined> = {};
const AGG_CACHE: Record<string, Measurement[] | undefined> = {};
const AGG_INFLIGHT: Record<string, Promise<Measurement[]> | undefined> = {};

const MapLibreMap: React.FC<Props> = ({ parameter, mode = 'pollutants', fitTrigger, resetTrigger, flyToCoords = null, disableAutoFit = false, recency = '24h', timeResolution, aggregationRules = [], aggregationRollups = [], customStartIso = null, customEndIso = null, sourceFilter = '' }) => {
  const mapContainer = React.useRef<HTMLDivElement | null>(null);
  const mapRef = React.useRef<MapLibreMapGL | null>(null);
  const [measurements, setMeasurements] = React.useState<Measurement[]>([]);
  const [sites, setSites] = React.useState<DevicePoint[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mapReady, setMapReady] = React.useState(false);
  const userPosRef = React.useRef<{ lng: number; lat: number } | null>(null);
  const [expandedGroups, setExpandedGroups] = React.useState<Set<string>>(new Set());
  const autoCenterRef = React.useRef(false);
  const requestFitOnDataRef = React.useRef(false);
  const lastFitTriggerRef = React.useRef(fitTrigger);
  const SPIDER_LINE_SOURCE = 'aq-spider-lines';
  const SPIDER_LINE_LAYER = 'aq-spider-lines';
  const [selectedMeasurement, setSelectedMeasurement] = React.useState<Measurement | null>(null);
  const [selectedSite, setSelectedSite] = React.useState<DevicePoint | null>(null);
  const [deviceSensors, setDeviceSensors] = React.useState<DeviceSensor[] | null>(null);
  const [deviceSensorsLoading, setDeviceSensorsLoading] = React.useState(false);
  const [deviceSensorsError, setDeviceSensorsError] = React.useState<string | null>(null);
  const [activeSensorId, setActiveSensorId] = React.useState<number | null>(null); 
  
  const [aqiDeviceMeasurements, setAqiDeviceMeasurements] = React.useState<Map<string, Measurement>>(new Map());
  const [aqiDeviceMeasurementsLoading, setAqiDeviceMeasurementsLoading] = React.useState(false);
  const [activeAqiParameter, setActiveAqiParameter] = React.useState<string | null>(null); 
  
  const [lastDataUpdate, setLastDataUpdate] = React.useState<string | null>(null);
  const selectedParamCode = React.useMemo(() => (parameter || '').toLowerCase(), [parameter]);
  const isAqiActive = React.useMemo(() => isAqiResolution(timeResolution), [timeResolution]);
  
  const effectiveAggregationCode = React.useMemo(
    () => isAqiActive ? getAqiAggregationCode(timeResolution, parameter) : timeResolution,
    [isAqiActive, timeResolution, parameter]
  );
  const activeAqiLabel = React.useMemo(
    () => (isAqiActive ? describeAqiResolution(effectiveAggregationCode) : ''),
    [isAqiActive, effectiveAggregationCode]
  );
  const rollupForParam = React.useMemo(() => {
    if (!selectedParamCode || !aggregationRollups || aggregationRollups.length === 0 || !timeResolution) return null;
    const target = (timeResolution || '').toLowerCase();
    return aggregationRollups.find(
      (rollup) => (rollup.parameter_code || '').toLowerCase() === selectedParamCode && (rollup.to_period_code || '').toLowerCase() === target
    ) || null;
  }, [aggregationRollups, selectedParamCode, timeResolution]);
  const activeAggregationCode = React.useMemo(
    () => (timeResolution && timeResolution.trim() ? timeResolution.toLowerCase() : 'hour'),
    [timeResolution]
  );
  const aggregationRuleLookup = React.useMemo(() => {
    const map = new Map<string, ParameterAggregationRule>();
    aggregationRules.forEach((rule) => {
      if (!rule || !rule.parameter_code || !rule.aggregation_code) return;
      const key = `${rule.parameter_code.toLowerCase()}__${rule.aggregation_code.toLowerCase()}`;
      map.set(key, rule);
    });
    return map;
  }, [aggregationRules]);
  const normalizeAggregationCode = React.useCallback((agg?: string | null | undefined) => {
    return agg && agg.trim() ? agg.toLowerCase() : '1h';
  }, []);
  const formatValueForDisplay = React.useCallback(
    (param?: string | null, value?: number | null, aggregation?: string | null) => {
      if (value == null || Number.isNaN(value)) return '—';
      const paramCode = (param || '').toLowerCase();
      if (!paramCode) return value.toString();
      const aggCode = normalizeAggregationCode(aggregation);
      let rule =
        aggregationRuleLookup.get(`${paramCode}__${aggCode}`) ||
        (aggCode === '1h' ? undefined : aggregationRuleLookup.get(`${paramCode}__1h`));
      
      if (!rule) {
        
        if (paramCode === 'pm25' && aggCode === '1h') {
          rule = { parameter_code: 'pm25', aggregation_code: '1h', rounding_method: 'round', rounding_precision: 1, truncation_method: 'none', truncation_precision: null } as ParameterAggregationRule;
        }
      }
      let processed = value;
      if (rule) {
        const truncMethod = (rule.truncation_method || '').toLowerCase();
        const truncPrecision = typeof rule.truncation_precision === 'number' ? rule.truncation_precision : null;
        if (truncMethod && truncMethod !== 'none' && truncPrecision !== null) {
          const factor = Math.pow(10, truncPrecision);
          if (Number.isFinite(factor) && factor !== 0) {
            const scaled = processed * factor;
            if (truncMethod === 'truncate') {
              processed = Math.trunc(scaled) / factor;
            } else if (truncMethod === 'floor') {
              processed = Math.floor(scaled) / factor;
            } else if (truncMethod === 'ceil') {
              processed = Math.ceil(scaled) / factor;
            }
          }
        }

        const roundingMethod = (rule.rounding_method || '').toLowerCase();
        const roundingPrecision = typeof rule.rounding_precision === 'number' ? rule.rounding_precision : null;
        if (roundingMethod && roundingMethod !== 'none') {
          const precision = Math.max(roundingPrecision ?? 0, 0);
          const factor = Math.pow(10, precision);
          if (Number.isFinite(factor) && factor !== 0) {
            if (roundingMethod === 'round') {
              processed = Math.round(processed * factor) / factor;
            } else if (roundingMethod === 'floor') {
              processed = Math.floor(processed * factor) / factor;
            } else if (roundingMethod === 'ceil') {
              processed = Math.ceil(processed * factor) / factor;
            }
          }
        }

        const displayPrecision =
          roundingMethod && roundingMethod !== 'none' && roundingPrecision !== null
            ? Math.max(roundingPrecision, 0)
            : truncMethod && truncMethod !== 'none' && truncPrecision !== null
            ? Math.max(truncPrecision, 0)
            : null;
        if (displayPrecision !== null) {
          const str = processed.toFixed(displayPrecision);
          return str === '-0' || str === '-0.0' ? str.replace('-', '') : str;
        }
      }
      const str = processed.toString();
      return str === '-0' ? '0' : str;
    },
    [aggregationRuleLookup, normalizeAggregationCode]
  );
  const rangeStart = React.useMemo(() => {
    if (customStartIso) {
      const d = new Date(customStartIso);
      return isNaN(d.getTime()) ? null : d;
    }
    if (!recency || recency === 'all') return null;
    const now = Date.now();
    const minutes = recency === '1h' ? 120 : 24 * 60;
    return new Date(now - minutes * 60 * 1000);
  }, [recency, customStartIso]);
  const rangeEnd = React.useMemo(() => {
    if (customEndIso) {
      const d = new Date(customEndIso);
      return isNaN(d.getTime()) ? null : d;
    }
    if (recency && recency !== 'all') return new Date();
    return null; 
  }, [customEndIso, recency]);
  const withinRecency = React.useCallback((iso?: string | null) => {
    if (!iso) return false;
    const d = new Date(iso);
    if (isNaN(d.getTime())) return false;
    if (rangeStart && d < rangeStart) return false;
    if (rangeEnd && d > rangeEnd) return false;
    if (!rangeStart && !rangeEnd) return true;
    return true;
  }, [rangeStart, rangeEnd]);
  const orderedDeviceSensors = React.useMemo(() => {
    if (!deviceSensors) return null;
    
    const all = deviceSensors;
    if (!selectedParamCode) return all;
    const matches = all.filter((s) => (s.parameter || '').toLowerCase() === selectedParamCode);
    const others = all.filter((s) => (s.parameter || '').toLowerCase() !== selectedParamCode);
    
    const sortByRecency = (a: DeviceSensor, b: DeviceSensor) => {
      const ar = withinRecency(a.latest_observed_at);
      const br = withinRecency(b.latest_observed_at);
      return Number(br) - Number(ar);
    };
    return [...matches.sort(sortByRecency), ...others.sort(sortByRecency)];
  }, [deviceSensors, selectedParamCode, withinRecency]);

  const timeAgo = React.useCallback((iso: string | null | undefined) => {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const diffMs = Date.now() - d.getTime();
    if (diffMs < 0) return 'in the future';
    const sec = Math.floor(diffMs / 1000);
    if (sec < 30) return 'just now';
    if (sec < 90) return '1 min ago';
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min} min ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr} hr${hr === 1 ? '' : 's'} ago`;
    const day = Math.floor(hr / 24);
    return `${day} day${day === 1 ? '' : 's'} ago`;
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
      const sinceISO = rangeStart ? rangeStart.toISOString() : null;
      const untilISO = rangeEnd ? rangeEnd.toISOString() : null;
      
      const apiAggregation = effectiveAggregationCode || timeResolution;
      const key = `pollutants:${parameter}:${sinceISO ?? 'all'}:${untilISO ?? 'open'}:${apiAggregation || 'allres'}:${normalizedExternalApiName || 'all'}`;
      const aggKey = `agg:${parameter}:${rollupForParam?.from_period_code || ''}:${rollupForParam?.to_period_code || ''}:${sinceISO ?? 'all'}:${untilISO ?? 'open'}:${normalizedExternalApiName || 'all'}`;
      const url = buildUrlWithExternalApiName(`/measurements/${encodeURIComponent(parameter)}/latest`, {
        since: sinceISO,
        until: untilISO,
        aggregation: apiAggregation || undefined,
      });
      const applyData = (data: Measurement[]) => {
        if (cancelled) return;
        
        const filtered = rangeEnd
          ? data.filter((m) => withinRecency(m.observed_at))
          : data;
        setMeasurements(filtered);
        setSites([]);
        setError(null);
        setLoading(false);
        setLastDataUpdate(new Date().toISOString());
      };

      if (rollupForParam && timeResolution) {
        if (AGG_CACHE[aggKey]) {
          applyData(AGG_CACHE[aggKey]!);
          return () => { cancelled = true; };
        }
        if (AGG_INFLIGHT[aggKey]) {
          AGG_INFLIGHT[aggKey]!.then(applyData).catch(() => {
            if (!cancelled) setError('Unable to load air quality data. Please try again later or check your network connection.');
          });
          return () => { cancelled = true; };
        }
        const aggUrl = buildUrlWithExternalApiName(`/measurements/${encodeURIComponent(parameter)}/aggregate`, {
          from: rollupForParam.from_period_code,
          to: timeResolution,
          since: sinceISO,
          until: untilISO,
        });
        AGG_INFLIGHT[aggKey] = fetchJson<any[]>(aggUrl)
          .then((rows) => {
            const latest = new Map<number, any>();
            for (const r of rows || []) {
              const sid = r?.sensor_id;
              if (typeof sid !== 'number') continue;
              const obs = r?.observed_at ? new Date(r.observed_at).getTime() : -Infinity;
              const current = latest.get(sid);
              if (!current || obs > (current._ts || -Infinity)) {
                latest.set(sid, { ...r, _ts: obs });
              }
            }
            return Array.from(latest.values()).map((r) => ({
              measurement_id: r.measurement_id || 0,
              sensor_id: r.sensor_id,
              external_sensor_id: r.external_sensor_id || null,
              parameter: r.parameter || parameter,
              value: r.value,
              unit: r.unit || null,
              observed_at: r.observed_at,
              device: r.device || null,
            })) as Measurement[];
          })
          .finally(() => { delete AGG_INFLIGHT[aggKey]; });

        AGG_INFLIGHT[aggKey]!.then((data) => {
          AGG_CACHE[aggKey] = data;
          applyData(data);
        }).catch(() => {
          if (!cancelled) setError('Unable to load air quality data. Please try again later or check your network connection.');
        });
      } else {
        if (CACHE[key]) {
          applyData(CACHE[key]!);
          return () => { cancelled = true; };
        }
        if (INFLIGHT[key]) {
          INFLIGHT[key]!.then(applyData).catch(() => {
            if (!cancelled) setError('Unable to load air quality data. Please try again later or check your network connection.');
          });
          return () => { cancelled = true; };
        }

        INFLIGHT[key] = fetchJson<Measurement[]>(url)
          .then((data) => {
            CACHE[key] = data;
            return data;
          })
          .finally(() => { delete INFLIGHT[key]; });

        INFLIGHT[key]!.then(applyData).catch(() => {
          if (!cancelled) setError('Unable to load air quality data. Please try again later or check your network connection.');
          setLoading(false);
        });
      }
  } else {
      
      const apiAgg = effectiveAggregationCode || timeResolution;
      const devicesKey = `devices:${apiAgg || 'allres'}:${normalizedExternalApiName || 'all'}`;
      const devicesUrl = buildUrlWithExternalApiName('/devices', {
        aggregation: apiAgg || undefined,
      });
      const loadDevices = (): Promise<DevicePoint[]> => {
        if (SITES_CACHE[devicesKey]) return Promise.resolve(SITES_CACHE[devicesKey]!);
        if (SITES_INFLIGHT[devicesKey]) return SITES_INFLIGHT[devicesKey]!;
        SITES_INFLIGHT[devicesKey] = fetchJson<DevicePoint[]>(devicesUrl)
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

      
      if (!parameter) {
        if (recency === 'all') {
          loadDevices().then(applyDevices).catch(() => {
            if (!cancelled) setError('Unable to load devices. Please try again later or check your network connection.');
            setLoading(false);
          });
          return () => { cancelled = true; };
        }

        const activeKey = `active:${customStartIso || recency}:${customEndIso ? 'end' : 'now'}:${apiAgg || 'allres'}:${normalizedExternalApiName || 'all'}`;
        const loadActiveDevices = async (): Promise<Set<number>> => {
          if (ACTIVE_DEVICES_CACHE[activeKey]) return ACTIVE_DEVICES_CACHE[activeKey]!;
          if (ACTIVE_DEVICES_INFLIGHT[activeKey]) return ACTIVE_DEVICES_INFLIGHT[activeKey]!;
          ACTIVE_DEVICES_INFLIGHT[activeKey] = (async () => {
            const sinceISO = rangeStart ? rangeStart.toISOString() : null;
            const untilISO = rangeEnd ? rangeEnd.toISOString() : null;
            const unions = new Set<number>();
            try {
              const rows: any[] = await fetchJson(
                buildUrlWithExternalApiName('/measurements/latest', {
                  since: sinceISO,
                  until: untilISO,
                  aggregation: apiAgg || undefined,
                })
              );
              rows
                .filter((r) => withinRecency(r?.observed_at))
                .forEach((r) => {
                  const did = r?.device?.device_id;
                  if (typeof did === 'number') unions.add(did);
                });
            } catch {
              // ignore failures; return empty set
            }
            ACTIVE_DEVICES_CACHE[activeKey] = unions;
            return unions;
          })().finally(() => { delete ACTIVE_DEVICES_INFLIGHT[activeKey]; });
          return ACTIVE_DEVICES_INFLIGHT[activeKey]!;
        };

        Promise.all([loadDevices(), loadActiveDevices()])
          .then(([allDevices, activeIds]) => {
            if (cancelled) return;
            const filtered = allDevices.filter((d) => activeIds.has(d.device_id));
            setSites(filtered);
            setMeasurements([]);
            setError(null);
            setLoading(false);
          })
          .catch(() => {
            if (!cancelled) setError('Unable to load devices. Please try again later or check your network connection.');
            setLoading(false);
          });
        return () => { cancelled = true; };
      }

  
  const p = (parameter || '').toLowerCase();
  
  const paramApiAgg = isAqiActive ? getAqiAggregationCode(timeResolution, p) : apiAgg;
  const paramKey = `param-devices:${p}:${recency}:${paramApiAgg || 'allres'}:${normalizedExternalApiName || 'all'}`;
  const sinceISOForParam = rangeStart ? rangeStart.toISOString() : null;
  const untilISOForParam = rangeEnd ? rangeEnd.toISOString() : null;
  const paramUrl = buildUrlWithExternalApiName(`/measurements/${encodeURIComponent(p)}/latest`, {
    since: sinceISOForParam,
    until: untilISOForParam,
    aggregation: paramApiAgg || undefined,
  });
      const loadParamDeviceSet = (): Promise<Set<number>> => {
        if (PARAM_DEVICES_CACHE[paramKey]) return Promise.resolve(PARAM_DEVICES_CACHE[paramKey]!);
        if (PARAM_DEVICES_INFLIGHT[paramKey]) return PARAM_DEVICES_INFLIGHT[paramKey]!;
        if (rollupForParam && paramApiAgg) {
          const aggUrl = buildUrlWithExternalApiName(`/measurements/${encodeURIComponent(p)}/aggregate`, {
            from: rollupForParam.from_period_code,
            to: paramApiAgg,
            since: sinceISOForParam,
            until: untilISOForParam,
          });
          PARAM_DEVICES_INFLIGHT[paramKey] = fetchJson<any[]>(aggUrl)
            .then((rows) => {
              const ids = new Set<number>();
              for (const r of rows.filter((r) => withinRecency(r?.observed_at))) {
                const did = r?.device?.device_id;
                if (typeof did === 'number') ids.add(did);
              }
              PARAM_DEVICES_CACHE[paramKey] = ids;
              return ids;
            })
            .finally(() => { delete PARAM_DEVICES_INFLIGHT[paramKey]; });
        } else {
          PARAM_DEVICES_INFLIGHT[paramKey] = fetchJson<any[]>(paramUrl)
            .then((rows) => {
              const ids = new Set<number>();
              for (const r of rows.filter((r) => withinRecency(r?.observed_at))) {
                const did = r?.device?.device_id;
                if (typeof did === 'number') ids.add(did);
              }
              PARAM_DEVICES_CACHE[paramKey] = ids;
              return ids;
            })
            .finally(() => { delete PARAM_DEVICES_INFLIGHT[paramKey]; });
        }
        return PARAM_DEVICES_INFLIGHT[paramKey]!;
      };

      Promise.all([loadDevices(), loadParamDeviceSet()])
        .then(([allDevices, idSet]) => {
          if (cancelled) return;
          const filtered = allDevices.filter((d) => idSet.has(d.device_id));
          setSites(filtered);
          setMeasurements([]);
          setError(null);
          setLoading(false);
        })
        .catch(() => {
          if (!cancelled) setError('Unable to load devices. Please try again later or check your network connection.');
          setLoading(false);
        });
    }

    return () => {
      cancelled = true;
    };
  }, [parameter, mode, recency, rangeStart, rangeEnd, timeResolution, effectiveAggregationCode, customStartIso, customEndIso, withinRecency, rollupForParam, isAqiActive, normalizedExternalApiName, buildUrlWithExternalApiName]);

  
  React.useEffect(() => {
    let cancelled = false;
    setDeviceSensors(null);
    setDeviceSensorsLoading(false);
    setDeviceSensorsError(null);
    setActiveSensorId(null); 
    if (!selectedSite) return;
    const id = selectedSite.device_id;
    const applySensors = (rows: DeviceSensor[]) => {
      if (cancelled) return;
      setDeviceSensors(rows);
      setDeviceSensorsLoading(false);
      
      if (rows.length > 0) {
        const matchingParam = rows.find((s) => (s.parameter || '').toLowerCase() === selectedParamCode);
        setActiveSensorId(matchingParam ? matchingParam.sensor_id : rows[0].sensor_id);
      }
    };
    if (DEVICE_SENSORS_CACHE[id]) {
      applySensors(DEVICE_SENSORS_CACHE[id]!);
      return () => { cancelled = true; };
    }
      if (DEVICE_SENSORS_INFLIGHT[id]) {
      setDeviceSensorsLoading(true);
      DEVICE_SENSORS_INFLIGHT[id]!.then(applySensors).catch(() => {
      if (!cancelled) {
        setDeviceSensorsError('Unable to load sensors for this device.');
        setDeviceSensors([]);
      }
      setDeviceSensorsLoading(false);
    });
      return () => { cancelled = true; };
    }
    setDeviceSensorsLoading(true);
  const sinceISO = rangeStart ? rangeStart.toISOString() : null;
  const untilISO = rangeEnd ? rangeEnd.toISOString() : null;
  const url = `/devices/${id}/sensors${sinceISO ? `?since=${encodeURIComponent(sinceISO)}` : ''}${untilISO ? `${sinceISO ? '&' : '?'}until=${encodeURIComponent(untilISO)}` : ''}${timeResolution ? `${sinceISO || untilISO ? '&' : '?'}aggregation=${encodeURIComponent(timeResolution)}` : ''}`;
    DEVICE_SENSORS_INFLIGHT[id] = fetchJson<DeviceSensor[]>(url)
      .then((rows) => {
        DEVICE_SENSORS_CACHE[id] = rows;
        return rows;
      })
      .finally(() => { delete DEVICE_SENSORS_INFLIGHT[id]; });
    DEVICE_SENSORS_INFLIGHT[id]!.then(applySensors).catch(() => {
      if (!cancelled) {
        setDeviceSensorsError('Unable to load sensors for this device.');
        setDeviceSensors([]);
      }
      setDeviceSensorsLoading(false);
    });
    return () => { cancelled = true; };
  }, [selectedSite, rangeStart, rangeEnd, timeResolution, selectedParamCode]);

  
  React.useEffect(() => {
    
    if (!isAqiActive || !selectedMeasurement?.device?.device_id) {
      setAqiDeviceMeasurements(new Map());
      setAqiDeviceMeasurementsLoading(false);
      setActiveAqiParameter(null);
      return;
    }
    const deviceId = selectedMeasurement.device.device_id;
    const currentParam = (selectedMeasurement.parameter || '').toLowerCase();
    
    
    setActiveAqiParameter(currentParam);
    
    
    const initialMap = new Map<string, Measurement>();
    if (AQI_POLLUTANTS.has(currentParam)) {
      initialMap.set(currentParam, selectedMeasurement);
    }
    setAqiDeviceMeasurements(initialMap);
    
    
    let cancelled = false;
    setAqiDeviceMeasurementsLoading(true);
    
    const fetchOtherAqiParams = async () => {
      const newMap = new Map<string, Measurement>(initialMap);
      
      
      const otherParams = Array.from(AQI_POLLUTANTS).filter(p => p !== currentParam);
      
      await Promise.all(otherParams.map(async (param) => {
        try {
          
          const aqiAggCode = getAqiAggregationCode(timeResolution, param);
          const url = buildUrlWithExternalApiName(`/measurements/${param}/latest`, {
            aggregation: aqiAggCode,
          });
          const data = await fetchJson<Measurement[]>(url);
          
          const match = data.find(m => m.device?.device_id === deviceId);
          if (match && !cancelled) {
            newMap.set(param, match);
          }
        } catch {
          // Ignore errors for individual parameter fetches
        }
      }));
      
      if (!cancelled) {
        setAqiDeviceMeasurements(newMap);
        setAqiDeviceMeasurementsLoading(false);
      }
    };
    
    fetchOtherAqiParams();
    return () => { cancelled = true; };
  }, [isAqiActive, selectedMeasurement, timeResolution, buildUrlWithExternalApiName]);

  
  React.useEffect(() => {
    function waitForContainer(cb: (container: HTMLElement) => void) {
      if (mapContainer.current && mapContainer.current instanceof HTMLElement) {
        cb(mapContainer.current);
      } else {
        setTimeout(() => waitForContainer(cb), 10);
      }
    }

    if (!mapRef.current) {
      const first = measurements.find((m) => m.device && typeof m.device.longitude === 'number' && typeof m.device.latitude === 'number');
      let center: [number, number] = [0, 0];
      let zoom = 2;

      const createMap = (container: HTMLElement) => {
        mapRef.current = new maplibregl.Map({
          container,
          style: MAP_STYLE,
          center: center,
          zoom: zoom,
        });
        
        mapRef.current.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
        try {
          mapRef.current.setPadding({ top: 0, right: MAP_CONTROL_SAFE_PADDING, bottom: 0, left: 0 });
        } catch {
          void 0;
        }
        mapRef.current.on('load', () => {
          try {
            mapRef.current?.setPadding({ top: 0, right: MAP_CONTROL_SAFE_PADDING, bottom: 0, left: 0 });
          } catch {
            void 0;
          }
          setMapReady(true);
        });
      };

      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            center = [pos.coords.longitude, pos.coords.latitude];
            zoom = 10;
            userPosRef.current = { lng: pos.coords.longitude, lat: pos.coords.latitude };
            
            waitForContainer(createMap);
          },
          () => {
            if (first && first.device && typeof first.device.longitude === 'number' && typeof first.device.latitude === 'number') {
              center = [first.device.longitude, first.device.latitude];
              zoom = 6;
            } else {
              
              
              
              requestFitOnDataRef.current = true;
            }
            waitForContainer(createMap);
          }
        );
      } else {
        if (first && first.device && typeof first.device.longitude === 'number' && typeof first.device.latitude === 'number') {
          center = [first.device.longitude, first.device.latitude];
          zoom = 6;
        } else {
          
          
          requestFitOnDataRef.current = true;
        }
        waitForContainer(createMap);
      }
    }
    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
        setMapReady(false);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapContainer]);

  
  React.useEffect(() => {
    if (!mapRef.current || !mapReady) return;
  (mapRef.current as any)._aqMarkers = (mapRef.current as any)._aqMarkers || [];
    (mapRef.current as any)._aqMarkers.forEach((marker: MapLibreMarker) => marker.remove());
    (mapRef.current as any)._aqMarkers = [];

    
    if (!autoCenterRef.current) {
      let firstCenter: [number, number] | null = null;
      if (mode === 'pollutants') {
        const first = measurements.find((m) => m.device && typeof m.device.longitude === 'number' && typeof m.device.latitude === 'number');
        if (first && first.device && typeof first.device.longitude === 'number' && typeof first.device.latitude === 'number') {
          firstCenter = [first.device.longitude, first.device.latitude];
        }
      } else {
        const firstSite = sites.find((s) => typeof s.longitude === 'number' && typeof s.latitude === 'number');
        if (firstSite && typeof firstSite.longitude === 'number' && typeof firstSite.latitude === 'number') {
          firstCenter = [firstSite.longitude as number, firstSite.latitude as number];
        }
      }
      if (firstCenter) {
        try {
          mapRef.current.flyTo({ center: firstCenter, zoom: 6, essential: false });
        } catch {
          
          void 0;
        }
      }
      autoCenterRef.current = true;
    }

    
    const spiderLineFeatures: any[] = [];
  if (mode === 'pollutants') {
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
          el.title = `Click to expand ${list.length} sensors`;
          el.textContent = String(list.length);

          el.addEventListener('click', (ev) => {
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
          hub.title = 'Collapse';
          hub.textContent = '×';
          hub.addEventListener('click', (ev) => {
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
          
          const aqiColor = isAqiActive && typeof m.value === 'number'
            ? getAqiColor(m.value)
            : '#6b7280'; 
          
          el.style.border = `1px solid ${aqiColor}`;
          
          el.style.color = '#374151';
          el.style.fontWeight = '600';
          const formattedValue = isAqiActive
            ? formatAqiValue(m.value)
            : formatValueForDisplay(m.parameter, m.value, activeAggregationCode);
          const valueWithUnit = formattedValue !== '-' ? `${formattedValue} ${isAqiActive ? 'AQI' : (m.unit ?? '')}`.trim() : '-';
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
          
          el.addEventListener('click', (ev) => {
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
  el.title = s.name || `Device ${s.device_id}`;
        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([s.longitude as number, s.latitude as number])
          .addTo(mapRef.current!);
        el.addEventListener('click', (ev) => {
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

    
    
    
    try {
      if (mapRef.current && requestFitOnDataRef.current && !disableAutoFit) {
        
        const pts = mode === 'pollutants'
          ? measurements
            .map((m) => m.device)
            .filter((dev): dev is NonNullable<NonNullable<Measurement['device']>> => !!dev && typeof dev.longitude === 'number' && typeof dev.latitude === 'number')
          : sites
              .filter((s): s is DevicePoint => typeof s.longitude === 'number' && typeof s.latitude === 'number');
        if (pts.length > 0) {
            const first = pts[0];
            const firstLng = mode === 'pollutants' ? (first as any).longitude as number : (first as any).longitude as number;
            const firstLat = mode === 'pollutants' ? (first as any).latitude as number : (first as any).latitude as number;
            const bounds = pts.reduce((b: any, loc: any) => b.extend([loc.longitude as number, loc.latitude as number]), new maplibregl.LngLatBounds([firstLng, firstLat], [firstLng, firstLat]));
            try { mapRef.current.resize(); } catch { void 0; }
            try {
              mapRef.current.fitBounds(bounds, {
                padding: { top: MAP_TOOLBAR_SAFE_PADDING, bottom: 48, left: 48, right: 48 + MAP_CONTROL_SAFE_PADDING },
                duration: 500,
                maxZoom: 12,
              });
            } catch { void 0; }
            
            window.setTimeout(() => {
              try { mapRef.current?.resize(); } catch { void 0; }
              try {
                mapRef.current?.fitBounds(bounds, {
                  padding: { top: MAP_TOOLBAR_SAFE_PADDING, bottom: 48, left: 48, right: 48 + MAP_CONTROL_SAFE_PADDING },
                  duration: 500,
                  maxZoom: 12,
                });
              } catch { void 0; }
            }, 250);
            requestFitOnDataRef.current = false;
          }
      }
    } catch {
      void 0;
    }
  return () => { /* no retry cleanup necessary */ };
  }, [measurements, sites, mapReady, expandedGroups, mode, formatValueForDisplay, activeAggregationCode, disableAutoFit, isAqiActive]);

  
  React.useEffect(() => {
    autoCenterRef.current = false;
    setSelectedMeasurement(null);
    setSelectedSite(null);
  }, [parameter, mode]);

  React.useEffect(() => {
    if (!mapRef.current) return;
    try {
      mapRef.current.setPadding({ top: 0, right: MAP_CONTROL_SAFE_PADDING, bottom: 0, left: 0 });
    } catch {
      void 0;
    }
  }, [mapReady]);

  
  React.useEffect(() => {
    setExpandedGroups(new Set());
  }, [parameter, mode]);

  
  React.useEffect(() => {
    if (!mapRef.current || !mapReady) return;
    
    
    const isManualFitRequest = fitTrigger !== lastFitTriggerRef.current;
    lastFitTriggerRef.current = fitTrigger;

    
    if (disableAutoFit && !isManualFitRequest) {
      return;
    }
    
  const pts = mode === 'pollutants'
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
          padding: { top: MAP_TOOLBAR_SAFE_PADDING, bottom: 48, left: 48, right: 48 + MAP_CONTROL_SAFE_PADDING },
          duration: 500,
          maxZoom: 12,
        });
      } catch { void 0; }
      
      window.setTimeout(() => {
        try { mapRef.current?.resize(); } catch { void 0; }
        try {
          mapRef.current?.fitBounds(bounds, {
            padding: { top: MAP_TOOLBAR_SAFE_PADDING, bottom: 48, left: 48, right: 48 + MAP_CONTROL_SAFE_PADDING },
            duration: 500,
            maxZoom: 12,
          });
        } catch { void 0; }
      }, 250);
    } catch {
      
      void 0;
    }
    
    
    if (requestFitOnDataRef.current) {
      requestFitOnDataRef.current = false;
    }
  }, [fitTrigger, mode, measurements, sites, mapReady]);

  
  React.useEffect(() => {
    if (!mapRef.current || !mapReady) return;
    let center: [number, number] = [0, 0];
    let zoom = 2;
    if (userPosRef.current) {
      center = [userPosRef.current.lng, userPosRef.current.lat];
      zoom = 10;
    } else {
      const first = measurements.find((m) => m.device && typeof m.device.longitude === 'number' && typeof m.device.latitude === 'number');
      if (first && first.device) {
        center = [first.device.longitude as number, first.device.latitude as number];
        zoom = 6;
      }
    }
    try {
      mapRef.current.flyTo({ center, zoom, duration: 500 });
    } catch {
      
      void 0;
    }
  }, [resetTrigger, mapReady, measurements]);

  
  React.useEffect(() => {
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
  }, [flyToCoords, mapReady]);

  
  const aggregationLabel = React.useMemo(() => {
    if (isAqiActive) {
      return getAggregationDisplayLabel(effectiveAggregationCode);
    }
    return getAggregationDisplayLabel(timeResolution);
  }, [isAqiActive, effectiveAggregationCode, timeResolution]);

  
  const markerCount = React.useMemo(() => {
    if (mode === 'pollutants') {
      return measurements.length;
    } else {
      return sites.length;
    }
  }, [mode, measurements, sites]);

  return (
    <div className="map-container">
      {loading && <div className="map-loading">Loading map data...</div>}
      {error && <div className="map-error">Error: {error}</div>}
      <div ref={mapContainer} className="map-canvas" />
      
      
      {!loading && !error && (
        <div className="map-legend-container">
          
          {isAqiActive && <AqiLegend compact showNoData />}
          
          
          <div className="map-status-bar">
            <span className="map-status-bar__count">
              {markerCount} {mode === 'pollutants' ? 'measurement' : 'device'}{markerCount !== 1 ? 's' : ''}
            </span>
            <span className="map-status-bar__separator" />
            <LastUpdated timestamp={lastDataUpdate} showEmptyText={mode !== 'devices'} />
          </div>
        </div>
      )}
      
      
      {!loading && !error && markerCount === 0 && (
        <MapEmptyState mode={mode} parameter={parameter} />
      )}
      
      
      <div className={`slide-out-panel ${selectedMeasurement || selectedSite ? 'open' : ''}`}>
        
        {selectedMeasurement && (() => {
          const deviceName = selectedMeasurement.device?.friendly_name || selectedMeasurement.device?.name || 'Unknown Device';
          const paramDisplay = (selectedMeasurement.parameter || '').toUpperCase();
          const dataSource = (selectedMeasurement.device as any)?.external_api?.name || null;
          return (
            <>
              <div className="panel-header-compact">
                <div className="panel-title-section">
                  <h3 className="panel-title">{deviceName}</h3>
                  <span className="panel-subtitle">
                    {paramDisplay}
                    {aggregationLabel && <span className="aggregation-badge">{aggregationLabel}</span>}
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
                  aria-label="Close panel"
                >
                  ×
                </button>
              </div>
              
              <div className="panel-content-compact">
                
                {isAqiActive && aqiDeviceMeasurements.size > 1 && (
                  <div className="sensor-tabs aqi-tabs">
                    {Array.from(aqiDeviceMeasurements.keys()).map((param) => {
                      const isActive = param === activeAqiParameter;
                      return (
                        <button
                          key={param}
                          className={`sensor-tab${isActive ? ' active' : ''}`}
                          onClick={() => setActiveAqiParameter(param)}
                          title={getAqiDisplayName(param)}
                        >
                          {getAqiDisplayName(param)}
                        </button>
                      );
                    })}
                    {aqiDeviceMeasurementsLoading && (
                      <span className="loading-indicator" style={{ fontSize: '0.75rem', color: '#666' }}>Loading...</span>
                    )}
                  </div>
                )}
                
                
                {(() => {
                  
                  const displayMeasurement = (isAqiActive && activeAqiParameter && aqiDeviceMeasurements.get(activeAqiParameter)) 
                    ? aqiDeviceMeasurements.get(activeAqiParameter)! 
                    : selectedMeasurement;
                  const displayValue = isAqiActive
                    ? formatAqiValue(displayMeasurement.value)
                    : formatValueForDisplay(displayMeasurement.parameter, displayMeasurement.value, activeAggregationCode);
                  const displayHeroValue = isAqiActive && displayValue === '-'
                    ? 'No AQI available'
                    : displayValue;
                  const displayHeroUnit = isAqiActive
                    ? (displayValue === '-' ? '' : 'AQI')
                    : displayMeasurement.unit ?? '';
                  
                  return (
                    <>
                      <div className="measurement-hero">
                        <span className="hero-value">{displayHeroValue}</span>
                        <span className="hero-unit">{displayHeroUnit}</span>
                        {displayMeasurement.observed_at && (
                          <span className="hero-time">{timeAgo(displayMeasurement.observed_at)}</span>
                        )}
                      </div>
                      {isAqiActive && displayValue === '-' && (
                        <div className="text-sm text-slate-600">No AQI available for this location.</div>
                      )}
                      
                      
                      <div className="panel-chart-container">
                        {displayMeasurement.sensor_id != null ? (
                          <SensorChart 
                            sensorId={displayMeasurement.sensor_id} 
                            parameter={displayMeasurement.parameter}
                            unit={displayMeasurement.unit ?? ''}
                            aggregationRules={aggregationRules}
                            timeResolution={timeResolution}
                          />
                        ) : (
                          <div className="empty-chart">No chart data available</div>
                        )}
                      </div>

                      
                      {displayMeasurement.device && (
                        <div className="meta-row">
                          <CopyableCoordinates
                            latitude={displayMeasurement.device.latitude}
                            longitude={displayMeasurement.device.longitude}
                          />
                          {displayMeasurement.device.timezone && (
                            <span className="meta-timezone" title="Device timezone">
                              {formatTimezoneWithOffset(displayMeasurement.device.timezone)}
                            </span>
                          )}
                        </div>
                      )}

                      
                      {displayMeasurement.sensor_id != null && (
                        <div className="panel-actions">
                          <Link
                            className="btn btn-primary"
                            to={`/analytics?sensor_id=${displayMeasurement.sensor_id}&parameter=${encodeURIComponent((displayMeasurement.parameter || '').toLowerCase())}&recency=${encodeURIComponent(recency || 'all')}${timeResolution ? `&time_resolution=${encodeURIComponent(timeResolution)}` : ''}`}
                          >
                            Open Full Analytics
                          </Link>
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            </>
          );
        })()}

        
        {selectedSite && !selectedMeasurement && (() => {
          const deviceName = selectedSite.friendly_name || selectedSite.name || 'Unnamed Device';
          const dataSource = selectedSite.network || null;
          const sensors = orderedDeviceSensors ?? deviceSensors ?? [];
          const activeSensor = sensors.find((s) => s.sensor_id === activeSensorId) || sensors[0] || null;
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
                      <span>{selectedSite.sensor_count} sensor{selectedSite.sensor_count !== 1 ? 's' : ''}</span>
                    )}
                  </span>
                </div>
                <button 
                  className="close-button" 
                  onClick={() => { setSelectedMeasurement(null); setSelectedSite(null); }}
                  aria-label="Close panel"
                >
                  ×
                </button>
              </div>
              
              <div className="panel-content-compact">
                
                {deviceSensorsLoading && (
                  <div className="panel-loading">Loading sensors…</div>
                )}
                
                
                {deviceSensorsError && !deviceSensorsLoading && (
                  <div className="panel-error-msg">{deviceSensorsError}</div>
                )}
                
                
                {!deviceSensorsLoading && hasSensors === false && !deviceSensorsError && (
                  <div className="panel-empty">No sensors found for this device.</div>
                )}
                
                
                {!deviceSensorsLoading && hasSensors && activeSensor && (
                  <>
                    
                    {hasMultipleSensors && (
                      <div className="sensor-tabs">
                        {sensors.map((s) => {
                          const isActive = s.sensor_id === activeSensorId;
                          const isRecent = withinRecency(s.latest_observed_at);
                          return (
                            <button
                              key={s.sensor_id}
                              className={`sensor-tab${isActive ? ' active' : ''}${!isRecent ? ' stale' : ''}`}
                              onClick={() => setActiveSensorId(s.sensor_id)}
                              title={s.parameter_name || s.parameter || 'Unknown'}
                            >
                              {(s.parameter_name || s.parameter || 'Unknown').length > 12 
                                ? (s.parameter_name || s.parameter || 'Unknown').substring(0, 10) + '…'
                                : (s.parameter_name || s.parameter || 'Unknown')}
                              {!isRecent && <span className="tab-stale-dot" />}
                            </button>
                          );
                        })}
                      </div>
                    )}
                    
                    
                    {(() => {
                      const isRecent = withinRecency(activeSensor.latest_observed_at);
                      const sensorParam = (activeSensor.parameter || '').toLowerCase();
                      
                      
                      const canShowAqi = isAqiActive && AQI_POLLUTANTS.has(sensorParam);
                      const formattedValue = canShowAqi
                        ? formatAqiValue(activeSensor.latest_value ?? null)  
                        : formatValueForDisplay(activeSensor.parameter, activeSensor.latest_value ?? null, activeAggregationCode);
                      const displayUnit = canShowAqi ? 'AQI' : (activeSensor.unit ?? '');
                      
                      return (
                        <div className="active-sensor-display">
                          
                          {aggregationLabel && (
                            <div className="aggregation-label-row">
                              <span className="aggregation-badge">{aggregationLabel}</span>
                            </div>
                          )}
                          
                          
                          <div className="measurement-hero">
                            <span className="hero-value">{formattedValue}</span>
                            <span className="hero-unit">{displayUnit}</span>
                            {activeSensor.latest_observed_at && (
                              <span className={`hero-time${!isRecent ? ' stale' : ''}`}>
                                {timeAgo(activeSensor.latest_observed_at)}
                                {!isRecent && <span className="stale-label">outdated</span>}
                              </span>
                            )}
                          </div>
                          
                          
                          {activeSensor.latest_is_valid != null && (
                            <div className="qc-indicator">
                              {activeSensor.latest_is_valid === true && <span className="qc-dot valid" title="Valid measurement" />}
                              {activeSensor.latest_is_valid === false && <span className="qc-dot invalid" title="Invalid measurement" />}
                            </div>
                          )}
                          
                          
                          <div className="panel-chart-container">
                            <SensorChart 
                              sensorId={activeSensor.sensor_id} 
                              parameter={(activeSensor.parameter || '').toLowerCase()} 
                              unit={activeSensor.unit ?? ''} 
                              aggregationRules={aggregationRules} 
                              timeResolution={timeResolution} 
                            />
                          </div>
                          
                          
                          <div className="meta-row">
                            <CopyableCoordinates
                              latitude={selectedSite.latitude}
                              longitude={selectedSite.longitude}
                            />
                            {selectedSite.timezone && (
                              <span className="meta-timezone" title="Device timezone">
                                {formatTimezoneWithOffset(selectedSite.timezone)}
                              </span>
                            )}
                          </div>
                          
                          
                          <div className="panel-actions">
                            <Link
                              className="btn btn-primary"
                              to={`/analytics?sensor_id=${activeSensor.sensor_id}&parameter=${encodeURIComponent((activeSensor.parameter || '').toLowerCase())}&recency=${encodeURIComponent(recency || 'all')}${timeResolution ? `&time_resolution=${encodeURIComponent(timeResolution)}` : ''}`}
                            >
                              Open Full Analytics
                            </Link>
                          </div>
                        </div>
                      );
                    })()}
                  </>
                )}
              </div>
            </>
          );
        })()}
      </div>
    </div>
  );
};

export default MapLibreMap;
