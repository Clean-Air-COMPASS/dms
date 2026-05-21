import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import UserMenu from './components/UserMenu';
import SensorChart from './SensorChart';
import { fetchJson } from './api';
import DataStreamSelectionModal from './components/DataStreamSelectionModal';
import DataStreamSummaryPanel, { type DataStreamInfo } from './components/DataStreamSummaryPanel';
import DateTimeRangePicker from './components/DateTimeRangePicker';
import { isAqiResolution, getAggregationDisplayLabel } from './aqi';
import { calculateTotalPages, calculateDisplayRange, slicePage, DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from './utils/pagination';
import { type TimezoneMode, TIMEZONE_OPTIONS, formatTimestamp, getTimezoneLabel } from './utils/timezone';

type ParameterAggregationRule = {
  parameter_code: string;
  aggregation_code: string;
  rounding_method?: string | null;
  rounding_precision?: number | null;
  truncation_method?: string | null;
  truncation_precision?: number | null;
};

type HistoryDataPoint = {
  timestamp: string;
  value: number;
  is_valid?: boolean;
  qc_flags?: Record<string, any> | null;
  failed_checks?: { check_code: string; severity?: string; message?: string | null }[];
};


type HistoryResponse = {
  sensor_id: number;
  parameter: string;
  parameter_name: string;
  unit: string;
  hours?: number;
  aggregate?: string;
  start?: string;
  end?: string;
  data: HistoryDataPoint[];
  device_name?: string;
  device_timezone?: string | null;
  external_sensor_id?: string | number;
  
  external_api?: { name: string | null } | null;
};


type MeasurementTableRow = {
  
  rowKey: string;
  
  sensorId: number;
  
  sensorName: string;
  
  externalSensorId: string | number | null;
  
  source: string | null;
  
  parameterCode: string;
  
  parameterDisplayName: string;
  
  unit: string;
  
  shownDuration: string;
  
  chartColor: string;
  
  isPrimary: boolean;
  
  timestamp: string;
  
  value: number;
  
  isValid: boolean;
  
  qcFlags?: Record<string, any> | null;
  
  failedChecks?: { check_code: string; severity?: string; message?: string | null }[];
};


type TableSortColumn = 'timestamp' | 'value' | 'status' | 'sensorName' | 'source' | 'parameter';

export default function Analytics() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sensorId = Number(searchParams.get('sensor_id') || '') || NaN;
  const param = (searchParams.get('parameter') || '').toLowerCase();
  const aggregate = (searchParams.get('aggregate') || 'hour').toLowerCase();
  const urlStart = searchParams.get('start') || '';
  const urlEnd = searchParams.get('end') || '';
  const recencyParamRaw = searchParams.get('recency');
  const toLocalInput = (iso: string) => {
    if (!iso) return '';
    const d = new Date(iso);
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  };
  const toIso = (localVal: string) => {
    if (!localVal) return '';
    return new Date(localVal).toISOString();
  };
  const start = toLocalInput(urlStart);
  const end = toLocalInput(urlEnd);
  const recency = (searchParams.get('recency') || '24h').toLowerCase();
  const recencyToHours = (r: string) => {
    if (r === 'all') return 168;
    const m = r.match(/^(\d+)\s*([hd])$/);
    if (m) {
      const n = Number(m[1]);
      if (!Number.isFinite(n) || n <= 0) return 24;
      return m[2] === 'd' ? n * 24 : n;
    }
    return 24;
  };
  const hours = recencyToHours(recency);
  const backendAggregate = useMemo(() => {
    const code = (aggregate || '').toLowerCase();
    if (code === 'raw' || code === 'latest' || code === 'minute' || code === '1m') return 'raw';
    if (code === 'day' || code === 'daily' || code === '24h') return 'day';
    if (code === 'hour' || code === '1h' || isAqiResolution(code)) return 'hour';
    if (/^\d+\s*d$/.test(code)) return 'day';
    if (/^\d+\s*h$/.test(code)) return 'hour';
    return 'hour';
  }, [aggregate]);
  const [includeInvalid, setIncludeInvalid] = useState<boolean>(false);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [overlayHistories, setOverlayHistories] = useState<HistoryResponse[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [aggregationRules, setAggregationRules] = useState<ParameterAggregationRule[] | null>(null);
  const [sortColumn, setSortColumn] = useState<TableSortColumn>('timestamp');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const autoRangeForRecencyRef = useRef<string | null>(null);
  const [dataStreamModalOpen, setDataStreamModalOpen] = useState(false);
  const [showRangePicker, setShowRangePicker] = useState(false);
  const [showSensorFilterDropdown, setShowSensorFilterDropdown] = useState(false);
  
  
  const [tableFilteredSensorIds, setTableFilteredSensorIds] = useState<number[] | null>(null);
  
  
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  
  
  const [timezoneMode, setTimezoneMode] = useState<TimezoneMode>('stream');

  
  const streamTimezone = useMemo(() => {
    if (history?.device_timezone) return history.device_timezone;
    if (overlayHistories.length > 0) {
      const first = overlayHistories.find((o) => o.device_timezone);
      if (first?.device_timezone) return first.device_timezone;
    }
    return null;
  }, [history?.device_timezone, overlayHistories]);

  
  const chartColorPalette = useMemo(() => [
    '#0074D9', '#FF4136', '#2ECC40', '#FF851B', '#7FDBFF', 
    '#B10DC9', '#85144b', '#3D9970', '#39CCCC', '#F012BE'
  ], []);

  
  const computeShownDuration = useCallback((aggregationCode: string | null | undefined): string => {
    const code = (aggregationCode || 'hour').toLowerCase();
    
    const label = getAggregationDisplayLabel(code);
    
    if (!label || label === code) {
      
      if (code === 'raw' || code === 'latest') return 'Raw/latest';
      if (code === 'hour' || code === '1h') return 'Hourly';
      if (code === 'day' || code === '24h' || code === 'daily') return 'Daily';
      if (code === '1m') return '1-minute';
      return code;
    }
    return label;
  }, []);

  
  const dataStreamInfos: DataStreamInfo[] = useMemo(() => {
    const streams: DataStreamInfo[] = [];
    const primaryShownDuration = computeShownDuration(aggregate);

    
    if (history) {
      streams.push({
        sensorId: history.sensor_id,
        sensorName: history.device_name || `Sensor ${history.sensor_id}`,
        externalSensorId: history.external_sensor_id ?? null,
        parameterCode: history.parameter || '',
        parameterDisplayName: history.parameter_name || history.parameter?.toUpperCase() || '',
        unit: history.unit || '',
        aggregateCode: aggregate,
        shownDuration: primaryShownDuration,
        source: history.external_api?.name ?? null,
        isPrimary: true,
        chartColor: chartColorPalette[0],
        // Primary streams don't have overlayKey - they're not removable via overlay mechanism
      });
    }

    
    
    const overlayParams = searchParams.getAll('overlay');
    overlayHistories.forEach((overlay, index) => {
      
      const overlayDisplayAggregate = (overlay as any)._displayAggregate || aggregate;
      const overlayShownDuration = computeShownDuration(overlayDisplayAggregate);
      
      
      
      const overlayParam = overlay.parameter || param;
      const matchingOverlayKey = overlayParams.find(op => {
        const parts = op.split(':');
        return Number(parts[0]) === overlay.sensor_id && 
               (parts[1] || param).toLowerCase() === overlayParam.toLowerCase() &&
               (parts[2] || aggregate).toLowerCase() === overlayDisplayAggregate.toLowerCase();
      }) || `${overlay.sensor_id}:${overlayParam}:${overlayDisplayAggregate}`;
      
      streams.push({
        sensorId: overlay.sensor_id,
        sensorName: overlay.device_name || `Sensor ${overlay.sensor_id}`,
        externalSensorId: overlay.external_sensor_id ?? null,
        parameterCode: overlay.parameter || '',
        parameterDisplayName: overlay.parameter_name || overlay.parameter?.toUpperCase() || '',
        unit: overlay.unit || '',
        aggregateCode: overlayDisplayAggregate,
        shownDuration: overlayShownDuration,
        source: overlay.external_api?.name ?? null,
        isPrimary: false,
        
        chartColor: chartColorPalette[(index + 1) % chartColorPalette.length],
        
        overlayKey: matchingOverlayKey,
      });
    });

    return streams;
  }, [history, overlayHistories, aggregate, param, searchParams, computeShownDuration, chartColorPalette]);

  
  const existingDataStreamSelections = useMemo(() => {
    const selections: { sensor_id: number; parameter: string; aggregate: string }[] = [];
    
    
    if (Number.isFinite(sensorId) && sensorId > 0) {
      selections.push({
        sensor_id: sensorId,
        parameter: param,
        aggregate: aggregate,
      });
    }
    
    
    const overlays = searchParams.getAll('overlay');
    overlays.forEach((overlay) => {
      const parts = overlay.split(':');
      const overlayId = Number(parts[0]);
      const overlayParam = parts[1] || param;
      const overlayAggregate = parts[2] || aggregate; 
      if (Number.isFinite(overlayId)) {
        selections.push({
          sensor_id: overlayId,
          parameter: overlayParam,
          aggregate: overlayAggregate,
        });
      }
    });
    
    return selections;
  }, [sensorId, param, aggregate, searchParams]);

  
  const handleRemoveOverlay = useCallback((overlayKeyToRemove: string) => {
    const newSearchParams = new URLSearchParams(searchParams.toString());
    const existingOverlays = searchParams.getAll('overlay');
    
    newSearchParams.delete('overlay');
    existingOverlays.forEach((overlayParam) => {
      if (overlayParam !== overlayKeyToRemove) {
        newSearchParams.append('overlay', overlayParam);
      }
    });
    setSearchParams(newSearchParams);
  }, [searchParams, setSearchParams]);

  
  const aggregationRuleLookup = useMemo(() => {
    const map = new Map<string, ParameterAggregationRule>();
    if (aggregationRules) {
      aggregationRules.forEach((rule) => {
        if (!rule || !rule.parameter_code || !rule.aggregation_code) return;
        const key = `${rule.parameter_code.toLowerCase()}__${rule.aggregation_code.toLowerCase()}`;
        map.set(key, rule);
      });
    }
    return map;
  }, [aggregationRules]);

  
  const normalizeAggregationCode = useCallback((agg?: string | null | undefined) => {
    return agg && agg.trim() ? agg.toLowerCase() : '1h';
  }, []);

  
  const formatValueForDisplay = useCallback(
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
          rule = { parameter_code: 'pm25', aggregation_code: '1h', rounding_method: 'round', rounding_precision: 1, truncation_method: 'none', truncation_precision: null };
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

  
  
  useEffect(() => {
    if (!recencyParamRaw) return;
    if (urlStart || urlEnd) return;

    const recencyKey = recencyParamRaw.toLowerCase();
    if (autoRangeForRecencyRef.current === recencyKey) return;
    if (!Number.isFinite(hours) || hours <= 0) return;

    autoRangeForRecencyRef.current = recencyKey;

    const floorToHour = (d: Date) => {
      const dd = new Date(d);
      dd.setMinutes(0, 0, 0);
      return dd;
    };
    const ceilToHour = (d: Date) => {
      const dd = new Date(d);
      if (dd.getMinutes() === 0 && dd.getSeconds() === 0 && dd.getMilliseconds() === 0) return dd;
      dd.setHours(dd.getHours() + 1, 0, 0, 0);
      return dd;
    };

    const now = new Date();
    const endDate = ceilToHour(now);
    const startBase = new Date(now.getTime() - hours * 60 * 60 * 1000);
    const startDate = floorToHour(startBase);

    const np = new URLSearchParams(searchParams.toString());
    np.set('start', startDate.toISOString());
    np.set('end', endDate.toISOString());
    setSearchParams(np);
  }, [recencyParamRaw, urlStart, urlEnd, hours, searchParams, setSearchParams]);

  const hasValidDataStreamSelection = useMemo(() => {
    const currentSensorId = Number(searchParams.get('sensor_id') || '');
    const currentParameter = (searchParams.get('parameter') || '').toLowerCase();
    return Number.isFinite(currentSensorId) && currentSensorId > 0 && currentParameter.length > 0;
  }, [searchParams]);

  useEffect(() => {
    if (!hasValidDataStreamSelection) {
      setDataStreamModalOpen(true);
    }
  }, [hasValidDataStreamSelection]);

  
  useEffect(() => {
    if (!hasValidDataStreamSelection) {
      setHistory(null);
      setLoading(false);
      return;
    }
    const currentSensorId = Number(searchParams.get('sensor_id') || '');
    const currentParameter = (searchParams.get('parameter') || '').toLowerCase();
    if (!Number.isFinite(currentSensorId) || !currentParameter) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const queryParams = new URLSearchParams();
    queryParams.set('aggregate', backendAggregate);
    if (urlStart) {
      queryParams.set('start', urlStart);
      if (urlEnd) queryParams.set('end', urlEnd);
    } else {
      queryParams.set('hours', String(hours));
    }
    if (includeInvalid) queryParams.set('include_invalid', 'true');
    queryParams.set('include_qc', 'true');
    (async () => {
      try {
        const data = await fetchJson<HistoryResponse>(`/sensors/${currentSensorId}/history?${queryParams.toString()}`);
        if (cancelled) return;
        setHistory(data);
        setLoading(false);
      } catch (fetchError: any) {
        if (cancelled) return;
        setError(fetchError?.message || 'Failed to load history');
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [searchParams, hours, includeInvalid, backendAggregate, start, end, urlStart, urlEnd, hasValidDataStreamSelection]);

  
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rules = await fetchJson<any[]>('/parameter_aggregation_rules');
        if (cancelled) return;
        setAggregationRules(rules || null);
      } catch {
        if (!cancelled) setAggregationRules(null);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  
  
  useEffect(() => {
    let cancelled = false;
    const overlays = searchParams.getAll('overlay');
    if (!overlays || overlays.length === 0) { setOverlayHistories([]); return; }
    
    (async () => {
      try {
        const results = await Promise.all(
          overlays.map(async (o) => {
            const parts = (o || '').split(':');
            const sidStr = parts[0];
            const overlayAggregate = parts[2] || aggregate || 'hour'; 
            const idn = Number(sidStr);
            if (!Number.isFinite(idn)) return null;
            
            
            const params = new URLSearchParams();
            
            const overlayAggCode = (overlayAggregate || '').toLowerCase();
            let overlayBackendAgg = 'hour';
            if (overlayAggCode === 'raw' || overlayAggCode === 'latest' || overlayAggCode === 'minute' || overlayAggCode === '1m') overlayBackendAgg = 'raw';
            else if (overlayAggCode === 'day' || overlayAggCode === 'daily' || overlayAggCode === '24h') overlayBackendAgg = 'day';
            else if (overlayAggCode === 'hour' || overlayAggCode === '1h' || isAqiResolution(overlayAggCode)) overlayBackendAgg = 'hour';
            params.set('aggregate', overlayBackendAgg);
            
            if (urlStart) {
              params.set('start', urlStart);
              if (urlEnd) params.set('end', urlEnd);
            } else {
              params.set('hours', String(hours));
            }
            if (includeInvalid) params.set('include_invalid', 'true');
            params.set('include_qc', 'true');
            
            try {
              const response = await fetchJson<HistoryResponse>(`/sensors/${idn}/history?${params.toString()}`);
              
              if (response) {
                (response as any)._displayAggregate = overlayAggregate;
              }
              return response;
            } catch {
              return null;
            }
          })
        );
        if (cancelled) return;
        const valid = (results || []).filter((r): r is HistoryResponse => !!(r && r.sensor_id));
        setOverlayHistories(valid);
      } catch {
        if (cancelled) return;
        setOverlayHistories([]);
      }
    })();
    return () => { cancelled = true; };
  }, [searchParams, hours, includeInvalid, aggregate, urlStart, urlEnd]);

  const setStartParam = (v: string) => {
    const np = new URLSearchParams(searchParams);
    if (v) np.set('start', toIso(v)); else np.delete('start');
    setSearchParams(np);
  };
  const setEndParam = (v: string) => {
    const np = new URLSearchParams(searchParams);
    if (v) np.set('end', toIso(v)); else np.delete('end');
    setSearchParams(np);
  };
  const clearRange = () => {
    const np = new URLSearchParams(searchParams);
    np.delete('start');
    np.delete('end');
    setSearchParams(np);
  };

  const unit = history?.unit || '';
  const parameter = param || history?.parameter || '';

  
  const summary = useMemo(() => {
    if (!history || !history.data) return null;
    const total = history.data.length;
    const validCount = history.data.filter(d => d.is_valid !== false).length; 
    const considered = history.data.filter(d => (includeInvalid ? true : d.is_valid !== false));
    const values = considered.map(d => Number(d.value)).filter(v => Number.isFinite(v));
    if (values.length === 0) {
      return {
        latest: null,
        avg: null,
        min: null,
        max: null,
        completeness: total === 0 ? 0 : Math.round((validCount / total) * 100),
      };
    }
    
    const latestPoint = history.data.reduce((a, b) => (new Date(a.timestamp) > new Date(b.timestamp) ? a : b));
    const sum = values.reduce((s, v) => s + v, 0);
    const avg = sum / values.length;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const completeness = total === 0 ? 0 : Math.round((validCount / total) * 100);

    return {
      latest: { value: Number(latestPoint.value), ts: latestPoint.timestamp },
      avg,
      min,
      max,
      completeness,
    };
  }, [history, includeInvalid]);

  
  const allMeasurementRows: MeasurementTableRow[] = useMemo(() => {
    const rows: MeasurementTableRow[] = [];
    const primaryShownDuration = computeShownDuration(aggregate);
    
    
    const convertDataPoints = (
      historyData: HistoryResponse,
      isPrimary: boolean,
      chartColor: string,
      shownDuration: string
    ): MeasurementTableRow[] => {
      const sensorName = historyData.device_name || `Sensor ${historyData.sensor_id}`;
      const externalSensorId = historyData.external_sensor_id ?? null;
      const source = historyData.external_api?.name ?? null;
      const parameterCode = historyData.parameter || '';
      const parameterDisplayName = historyData.parameter_name || historyData.parameter?.toUpperCase() || '';
      const unit = historyData.unit || '';
      
      const streamAggregate = isPrimary ? aggregate : ((historyData as any)._displayAggregate || aggregate);
      
      return historyData.data.map((dataPoint, index) => ({
        rowKey: `${historyData.sensor_id}-${streamAggregate}-${index}-${dataPoint.timestamp}`,
        sensorId: historyData.sensor_id,
        sensorName,
        externalSensorId,
        source,
        parameterCode,
        parameterDisplayName,
        unit,
        shownDuration,
        chartColor,
        isPrimary,
        timestamp: dataPoint.timestamp,
        value: dataPoint.value,
        isValid: dataPoint.is_valid !== false, // treat undefined as valid
        qcFlags: dataPoint.qc_flags,
        failedChecks: dataPoint.failed_checks,
      }));
    };
    
    
    if (history && history.data) {
      rows.push(...convertDataPoints(history, true, chartColorPalette[0], primaryShownDuration));
    }
    
    
    overlayHistories.forEach((overlay, index) => {
      if (overlay && overlay.data) {
        const color = chartColorPalette[(index + 1) % chartColorPalette.length];
        const overlayAggregate = (overlay as any)._displayAggregate || aggregate;
        const overlayShownDuration = computeShownDuration(overlayAggregate);
        rows.push(...convertDataPoints(overlay, false, color, overlayShownDuration));
      }
    });
    
    return rows;
  }, [history, overlayHistories, aggregate, computeShownDuration, chartColorPalette]);

  
  const filteredMeasurementRows: MeasurementTableRow[] = useMemo(() => {
    let filtered = allMeasurementRows;
    
    
    if (tableFilteredSensorIds !== null && tableFilteredSensorIds.length > 0) {
      filtered = filtered.filter(row => tableFilteredSensorIds.includes(row.sensorId));
    } else if (tableFilteredSensorIds !== null && tableFilteredSensorIds.length === 0) {
      
      filtered = [];
    }
    
    
    if (!includeInvalid) {
      filtered = filtered.filter(row => row.isValid);
    }
    
    return filtered;
  }, [allMeasurementRows, tableFilteredSensorIds, includeInvalid]);

  
  const sortedTableData: MeasurementTableRow[] = useMemo(() => {
    const data = [...filteredMeasurementRows];
    data.sort((a, b) => {
      let cmp = 0;
      switch (sortColumn) {
        case 'timestamp':
          cmp = new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
          break;
        case 'value':
          cmp = Number(a.value) - Number(b.value);
          break;
        case 'status':
          cmp = (a.isValid ? 0 : 1) - (b.isValid ? 0 : 1);
          break;
        case 'sensorName':
          cmp = (a.sensorName || '').localeCompare(b.sensorName || '');
          break;
        case 'source':
          cmp = (a.source || '').localeCompare(b.source || '');
          break;
        case 'parameter':
          cmp = (a.parameterDisplayName || '').localeCompare(b.parameterDisplayName || '');
          break;
      }
      return sortDirection === 'asc' ? cmp : -cmp;
    });
    return data;
  }, [filteredMeasurementRows, sortColumn, sortDirection]);

  
  useEffect(() => {
    setCurrentPage(1);
  }, [sortedTableData, pageSize]);

  
  const totalPages = useMemo(() => calculateTotalPages(sortedTableData.length, pageSize), [sortedTableData.length, pageSize]);
  const displayRange = useMemo(() => calculateDisplayRange(currentPage, pageSize, sortedTableData.length), [currentPage, pageSize, sortedTableData.length]);
  const paginatedTableData = useMemo(() => slicePage(sortedTableData, currentPage, pageSize), [sortedTableData, currentPage, pageSize]);

  
  const handlePreviousPage = useCallback(() => {
    setCurrentPage((p) => Math.max(1, p - 1));
  }, []);

  const handleNextPage = useCallback(() => {
    setCurrentPage((p) => Math.min(totalPages, p + 1));
  }, [totalPages]);

  const handlePageSizeChange = useCallback((newSize: number) => {
    setPageSize(newSize);
    setCurrentPage(1);
  }, []);

  
  const toggleSort = (col: TableSortColumn) => {
    if (sortColumn === col) {
      setSortDirection(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(col);
      
      setSortDirection(col === 'timestamp' ? 'desc' : 'asc');
    }
  };

  
  const SortIndicator = ({ column }: { column: TableSortColumn }) => {
    if (sortColumn !== column) return <span className="text-slate-300 ml-1">↕</span>;
    return <span className="text-blue-600 ml-1">{sortDirection === 'asc' ? '↑' : '↓'}</span>;
  };

  
  const handleDownloadCSV = () => {
    if (sortedTableData.length === 0) return;
    
    
    const escapeCSVField = (value: string | number | null | undefined): string => {
      if (value == null) return '';
      const stringValue = String(value);
      
      if (stringValue.includes(',') || stringValue.includes('"') || stringValue.includes('\n')) {
        return `"${stringValue.replace(/"/g, '""')}"`;
      }
      return stringValue;
    };
    
    const headerRow = [
      'Sensor Name',
      'External Sensor ID',
      'Source',
      'Parameter',
      'Shown Duration',
      'Timestamp',
      'Value',
      'Unit',
      'Status',
      'Failed Checks'
    ].join(',');
    
    const dataRows = sortedTableData.map(row => [
      escapeCSVField(row.sensorName),
      escapeCSVField(row.externalSensorId),
      escapeCSVField(row.source),
      escapeCSVField(row.parameterDisplayName),
      escapeCSVField(row.shownDuration),
      new Date(row.timestamp).toISOString(),
      row.value,
      escapeCSVField(row.unit),
      row.isValid ? 'Valid' : 'Invalid',
      escapeCSVField(row.failedChecks?.map(c => c.check_code).join('; ') || '')
    ].join(','));
    
    const csvContent = [headerRow, ...dataRows].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    
    
    const timestamp = new Date().toISOString().slice(0, 10);
    const streamCount = dataStreamInfos.length;
    link.download = `measurements_${timestamp}_${streamCount}_streams.csv`;
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  
  function MetricCard({ title, children }: { title: string; children: React.ReactNode }) {
    const [visible, setVisible] = useState(true);
    useEffect(() => {
      
      setVisible(false);
      const id = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(id);
    }, [children]);
    return (
      <div className={`flex-1 min-w-[10rem] max-w-xs p-3 rounded-lg shadow-sm bg-white border border-slate-100 transition transform ${visible ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1'} hover:shadow-md`}>
        <div className="text-xs text-slate-400">{title}</div>
        <div className="mt-1 text-2xl font-semibold tracking-tight">{children}</div>
      </div>
    );
  }

  return (
    
  <div className="min-h-screen bg-[#f9fafb] font-sans text-slate-800">
      
      <header className="sticky top-0 z-10 bg-white/90 border-b border-slate-200 shadow-sm flex items-center justify-between px-6 py-3">
        <Link to="/map" className="text-lg font-semibold tracking-wide select-none" style={{ textDecoration: 'none', color: 'inherit' }}>COMPASS</Link>
        <div className="flex items-center gap-2">
          <Link
            className="btn"
            to="/map"
            title="Back to Map"
          >
            Map
          </Link>
          <Link
            className="btn"
            to="/admin"
            title="Admin"
          >
            Admin
          </Link>
          <UserMenu />
        </div>
      </header>

      
      <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">Analytics</h1>
          
          {dataStreamInfos.length > 0 && (
            <span className="inline-flex items-center gap-2 text-sm text-slate-600">
              <span className="font-medium">{dataStreamInfos.length} data stream{dataStreamInfos.length > 1 ? 's' : ''}</span>
              {urlStart && (
                <span className="text-slate-400">
                  • {new Date(urlStart).toLocaleDateString()} – {urlEnd ? new Date(urlEnd).toLocaleDateString() : 'now'}
                </span>
              )}
            </span>
          )}
        </div>

        
        <div className="flex flex-wrap items-center gap-4 bg-white border border-slate-200 rounded-lg shadow-sm px-4 py-3">
          <label className="flex items-center gap-2 text-sm font-medium">
            Start:
            <input
              type="datetime-local"
              className="transition-all duration-200 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
              value={start}
              onChange={(e) => setStartParam(e.target.value)}
              placeholder="All time"
              aria-label="Start date/time"
            />
          </label>
          <label className="flex items-center gap-2 text-sm font-medium">
            End:
            <input
              type="datetime-local"
              className="transition-all duration-200 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
              value={end}
              onChange={(e) => setEndParam(e.target.value)}
              placeholder="Now"
              aria-label="End date/time"
            />
          </label>
          <div className="relative">
            <button
              type="button"
              className="rounded-md p-1.5 bg-white border border-slate-300 text-slate-600 transition hover:shadow-sm hover:text-slate-800"
              onClick={() => setShowRangePicker((v) => !v)}
              aria-label="Open date range picker"
              title="Pick start/end date and time"
            >
              
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5" />
              </svg>
            </button>
            <DateTimeRangePicker
              open={showRangePicker}
              startIso={urlStart}
              endIso={urlEnd}
              onClose={() => setShowRangePicker(false)}
              onClear={() => {
                clearRange();
                setShowRangePicker(false);
              }}
              onApply={(s, e) => {
                if (!s) {
                  clearRange();
                  setShowRangePicker(false);
                  return;
                }
                const np = new URLSearchParams(searchParams.toString());
                np.set('start', s);
                if (e) np.set('end', e);
                else np.delete('end');
                setSearchParams(np);
                setShowRangePicker(false);
              }}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="accent-blue-600 h-4 w-4 transition-all duration-200"
              checked={includeInvalid}
              onChange={(event) => setIncludeInvalid(event.target.checked)}
            />
            <span className="font-medium">Include invalid measurements</span>
          </label>
          
          <div className="flex items-center gap-2">
            <label htmlFor="timezone-select-global" className="text-sm text-slate-600">Timezone:</label>
            <select
              id="timezone-select-global"
              className="rounded border border-slate-300 px-2 py-1 text-sm bg-white"
              value={timezoneMode}
              onChange={(e) => setTimezoneMode(e.target.value as TimezoneMode)}
              aria-label="Select timezone display mode"
            >
              {TIMEZONE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.value === 'stream' && streamTimezone 
                    ? getTimezoneLabel('stream', streamTimezone)
                    : opt.label}
                </option>
              ))}
            </select>
          </div>
          <div className="ml-auto">
            <button
              type="button"
              className="btn"
              onClick={() => setDataStreamModalOpen(true)}
              title="Select Data Stream"
              aria-label="Select Data Stream"
            >
              Select Data Stream
            </button>
          </div>
        </div>

        <DataStreamSelectionModal
          open={dataStreamModalOpen}
          onClose={() => setDataStreamModalOpen(false)}
          initialParameter={parameter}
          initialAggregate={aggregate}
          initialStartIso={urlStart}
          initialEndIso={urlEnd}
          initialHours={hours}
          existingSelections={existingDataStreamSelections}
          onSelectPrimary={(selectedSensorId, selectedParameter, selectionOptions) => {
            const newSearchParams = new URLSearchParams(searchParams.toString());
            newSearchParams.set('sensor_id', String(selectedSensorId));
            newSearchParams.set('parameter', String((selectedParameter || '').toLowerCase()));
            if (selectionOptions?.aggregate) newSearchParams.set('aggregate', selectionOptions.aggregate);
            else newSearchParams.delete('aggregate');
            if (selectionOptions?.start) newSearchParams.set('start', selectionOptions.start);
            else newSearchParams.delete('start');
            if (selectionOptions?.end) newSearchParams.set('end', selectionOptions.end);
            else newSearchParams.delete('end');
            setSearchParams(newSearchParams);
          }}
          onSelectOverlay={(selectedSensorId, selectedParameter, selectionOptions) => {
            const newSearchParams = new URLSearchParams(searchParams.toString());
            
            const overlayAggregate = selectionOptions?.aggregate || aggregate || 'hour';
            newSearchParams.append('overlay', `${selectedSensorId}:${(selectedParameter || '').toLowerCase()}:${overlayAggregate}`);
            
            if (selectionOptions?.start) newSearchParams.set('start', selectionOptions.start);
            else newSearchParams.delete('start');
            if (selectionOptions?.end) newSearchParams.set('end', selectionOptions.end);
            else newSearchParams.delete('end');
            setSearchParams(newSearchParams);
          }}
        />

        
        {!loading && !error && hasValidDataStreamSelection && dataStreamInfos.length > 0 && (
          <DataStreamSummaryPanel
            dataStreams={dataStreamInfos}
            onRemoveOverlay={handleRemoveOverlay}
          />
        )}

        
        {!loading && !error && hasValidDataStreamSelection && (
          <div className="panel-body">
            <div className="flex flex-col sm:flex-row gap-4 items-stretch">
              <div className="flex-1">
                <div className="flex flex-col sm:flex-row gap-4">
                  <MetricCard title="Latest">
                    {summary?.latest ? (
                      <div className="flex items-baseline gap-2">
                        <span>{formatValueForDisplay(parameter, summary.latest.value, aggregate)}</span>
                        <span className="text-sm text-slate-500">{unit}</span>
                      </div>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </MetricCard>
                  <MetricCard title="Average">
                    {summary?.avg != null ? formatValueForDisplay(parameter, summary.avg, aggregate) : <span className="text-slate-400">—</span>}
                  </MetricCard>
                  <MetricCard title="Min / Max">
                    {summary?.min != null ? (
                      <div className="text-sm text-slate-700">{formatValueForDisplay(parameter, summary.min, aggregate)} / {formatValueForDisplay(parameter, summary.max, aggregate)}</div>
                    ) : <span className="text-slate-400">—</span>}
                  </MetricCard>
                  <MetricCard title="Completeness">
                    {summary ? (
                      <div className="text-sm text-slate-700">{summary.completeness}% valid</div>
                    ) : <span className="text-slate-400">—</span>}
                  </MetricCard>
                </div>
              </div>
            </div>
          </div>
        )}

        
        {error && hasValidDataStreamSelection && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-md px-4 py-3 shadow-sm">{error}</div>
        )}
        {loading && hasValidDataStreamSelection && (
          <div className="bg-white border border-slate-200 rounded-md px-4 py-6 shadow-sm text-center text-blue-700">Loading…</div>
        )}

        {!hasValidDataStreamSelection && !dataStreamModalOpen && (
          <div className="bg-white border border-slate-200 rounded-lg shadow-sm p-8 text-center">
            <div className="text-slate-500 mb-4">
              <svg className="w-16 h-16 mx-auto mb-4 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              <h3 className="text-lg font-medium text-slate-700 mb-2">No Data Stream Selected</h3>
              <p className="text-slate-500 mb-4">Select a data stream to view analytics, charts, and measurement data.</p>
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => setDataStreamModalOpen(true)}
            >
              Select Data Stream
            </button>
          </div>
        )}

        
        {!loading && !error && hasValidDataStreamSelection && (
          <>
            
            <section className="bg-white border border-slate-200 rounded-lg shadow-sm p-4">
              <SensorChart sensorId={sensorId} parameter={parameter} unit={unit} hours={hours} data={history} overlays={overlayHistories} aggregationRules={aggregationRules} timeResolution={aggregate} timezoneMode={timezoneMode} streamTimezone={streamTimezone} />
            </section>

            
            <section className="bg-white border border-slate-200 rounded-lg shadow-sm p-0">
              <div className="border-b border-slate-100 px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-semibold tracking-tight">Measurements</h2>
                <div className="flex flex-wrap items-center gap-3">
                  
                  
                  {dataStreamInfos.length > 1 && (
                    <div className="flex items-center gap-2">
                      <label className="text-sm text-slate-600">Filter:</label>
                      <div className="relative">
                        <button
                          type="button"
                          className="rounded border border-slate-300 px-2 py-1 text-sm bg-white min-w-[180px] text-left flex items-center justify-between gap-2"
                          onClick={() => setShowSensorFilterDropdown(v => !v)}
                          aria-haspopup="listbox"
                          aria-expanded={showSensorFilterDropdown}
                          aria-label="Filter measurements by data stream"
                        >
                          <span className="truncate">
                            {tableFilteredSensorIds === null 
                              ? `All Sensors (${dataStreamInfos.length})`
                              : tableFilteredSensorIds.length === 1
                                ? dataStreamInfos.find(s => s.sensorId === tableFilteredSensorIds[0])?.sensorName || '1 selected'
                                : `${tableFilteredSensorIds.length} selected`
                            }
                          </span>
                          <svg className="w-4 h-4 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                          </svg>
                        </button>
                        {showSensorFilterDropdown && (
                          <div 
                            className="absolute top-full left-0 mt-1 bg-white border border-slate-200 rounded shadow-lg z-50 min-w-[220px] max-h-[300px] overflow-y-auto"
                            role="listbox"
                            aria-multiselectable="true"
                          >
                            
                            <label className="flex items-center gap-2 px-3 py-2 hover:bg-slate-50 cursor-pointer border-b border-slate-100">
                              <input
                                type="checkbox"
                                className="accent-blue-600 h-4 w-4"
                                checked={tableFilteredSensorIds === null}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setTableFilteredSensorIds(null);
                                  }
                                }}
                              />
                              <span className="text-sm font-medium">All Sensors ({dataStreamInfos.length})</span>
                            </label>
                            
                            {dataStreamInfos.map((stream) => {
                              const isChecked = tableFilteredSensorIds === null || tableFilteredSensorIds.includes(stream.sensorId);
                              return (
                                <label 
                                  key={stream.sensorId} 
                                  className="flex items-center gap-2 px-3 py-2 hover:bg-slate-50 cursor-pointer"
                                >
                                  <input
                                    type="checkbox"
                                    className="accent-blue-600 h-4 w-4"
                                    checked={isChecked}
                                    onChange={(e) => {
                                      if (e.target.checked) {
                                        
                                        if (tableFilteredSensorIds === null) {
                                          // Already showing all - nothing to do
                                        } else {
                                          const newIds = [...tableFilteredSensorIds, stream.sensorId];
                                          
                                          if (newIds.length >= dataStreamInfos.length) {
                                            setTableFilteredSensorIds(null);
                                          } else {
                                            setTableFilteredSensorIds(newIds);
                                          }
                                        }
                                      } else {
                                        
                                        const currentIds = tableFilteredSensorIds === null 
                                          ? dataStreamInfos.map(s => s.sensorId) 
                                          : tableFilteredSensorIds;
                                        const newIds = currentIds.filter(id => id !== stream.sensorId);
                                        setTableFilteredSensorIds(newIds.length > 0 ? newIds : null);
                                      }
                                    }}
                                  />
                                  <span 
                                    className="w-3 h-3 rounded-full flex-shrink-0"
                                    style={{ backgroundColor: stream.chartColor }}
                                    title={`Color: ${stream.chartColor}`}
                                  />
                                  <span className="text-sm truncate">
                                    {stream.isPrimary ? '★ ' : ''}{stream.sensorName} 
                                    <span className="text-slate-400 ml-1">({stream.source || 'Unknown'})</span>
                                  </span>
                                </label>
                              );
                            })}
                            
                            <div className="border-t border-slate-100 px-3 py-2">
                              <button
                                type="button"
                                className="w-full text-sm text-blue-600 hover:text-blue-800"
                                onClick={() => setShowSensorFilterDropdown(false)}
                              >
                                Done
                              </button>
                            </div>
                          </div>
                        )}
                        
                        {showSensorFilterDropdown && (
                          <div 
                            className="fixed inset-0 z-40" 
                            onClick={() => setShowSensorFilterDropdown(false)}
                            aria-hidden="true"
                          />
                        )}
                      </div>
                    </div>
                  )}
                  
                  
                  {sortedTableData.length > 0 && (
                    <>
                      <span className="text-sm text-slate-600">
                        Showing {displayRange.start}–{displayRange.end} of {displayRange.total}
                      </span>
                      <select
                        className="rounded border border-slate-300 px-2 py-1 text-sm bg-white"
                        value={pageSize}
                        onChange={(e) => handlePageSizeChange(Number(e.target.value))}
                        aria-label="Rows per page"
                      >
                        {PAGE_SIZE_OPTIONS.map((size) => (
                          <option key={size} value={size}>{size} / page</option>
                        ))}
                      </select>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          className="px-2 py-1 rounded border border-slate-300 text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-100 transition"
                          onClick={handlePreviousPage}
                          disabled={currentPage === 1}
                          aria-label="Previous page"
                        >
                          ←
                        </button>
                        <span className="px-2 text-sm text-slate-600">
                          Page {currentPage} of {totalPages}
                        </span>
                        <button
                          type="button"
                          className="px-2 py-1 rounded border border-slate-300 text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-100 transition"
                          onClick={handleNextPage}
                          disabled={currentPage === totalPages}
                          aria-label="Next page"
                        >
                          →
                        </button>
                      </div>
                    </>
                  )}
                  {sortedTableData.length > 0 && (
                    <button
                      type="button"
                      onClick={handleDownloadCSV}
                      className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 transition"
                      title="Download all visible measurements as CSV"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                      Download CSV
                    </button>
                  )}
                </div>
              </div>
              
              
              <div className="overflow-x-auto">
                
                {allMeasurementRows.length === 0 && (
                  <div className="text-slate-500 text-center py-8">No measurements in this window.</div>
                )}
                
                
                {allMeasurementRows.length > 0 && sortedTableData.length === 0 && (
                  <div className="text-slate-500 text-center py-8">
                    No measurements match the current filter.
                    <button
                      type="button"
                      className="ml-2 text-blue-600 hover:text-blue-800 underline"
                      onClick={() => setTableFilteredSensorIds(null)}
                    >
                      Show all
                    </button>
                  </div>
                )}
                
                
                {sortedTableData.length > 0 && (
                  <table className="min-w-full text-sm border-separate border-spacing-0">
                    <thead>
                      <tr>
                        
                        {dataStreamInfos.length > 1 && (
                          <>
                            <th
                              className="text-left font-semibold px-3 py-2 bg-slate-50 border-b border-slate-200 cursor-pointer hover:bg-slate-100 select-none whitespace-nowrap"
                              onClick={() => toggleSort('sensorName')}
                              title="Sort by Sensor Name"
                            >
                              Sensor <SortIndicator column="sensorName" />
                            </th>
                            <th
                              className="text-left font-semibold px-3 py-2 bg-slate-50 border-b border-slate-200 cursor-pointer hover:bg-slate-100 select-none whitespace-nowrap"
                              onClick={() => toggleSort('source')}
                              title="Sort by Source"
                            >
                              Source <SortIndicator column="source" />
                            </th>
                            <th
                              className="text-left font-semibold px-3 py-2 bg-slate-50 border-b border-slate-200 cursor-pointer hover:bg-slate-100 select-none whitespace-nowrap"
                              onClick={() => toggleSort('parameter')}
                              title="Sort by Parameter"
                            >
                              Parameter <SortIndicator column="parameter" />
                            </th>
                          </>
                        )}
                        
                        
                        <th
                          className="text-left font-semibold px-3 py-2 bg-slate-50 border-b border-slate-200 cursor-pointer hover:bg-slate-100 select-none whitespace-nowrap"
                          onClick={() => toggleSort('timestamp')}
                          title="Sort by Time"
                        >
                          Time ({getTimezoneLabel(timezoneMode, streamTimezone)}) <SortIndicator column="timestamp" />
                        </th>
                        <th
                          className="text-left font-semibold px-3 py-2 bg-slate-50 border-b border-slate-200 cursor-pointer hover:bg-slate-100 select-none whitespace-nowrap"
                          onClick={() => toggleSort('value')}
                          title="Sort by Value"
                        >
                          Value <SortIndicator column="value" />
                        </th>
                        <th className="text-left font-semibold px-3 py-2 bg-slate-50 border-b border-slate-200 whitespace-nowrap">
                          Unit
                        </th>
                        <th
                          className="text-left font-semibold px-3 py-2 bg-slate-50 border-b border-slate-200 cursor-pointer hover:bg-slate-100 select-none whitespace-nowrap"
                          onClick={() => toggleSort('status')}
                          title="Sort by Status"
                        >
                          Status <SortIndicator column="status" />
                        </th>
                        <th className="text-left font-semibold px-3 py-2 bg-slate-50 border-b border-slate-200 whitespace-nowrap">
                          Failed Checks
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedTableData.map((row, idx) => (
                        <tr
                          key={row.rowKey}
                          className={`
                            transition-all duration-150
                            ${!row.isValid
                              ? 'bg-red-50 hover:bg-red-100'
                              : idx % 2 === 0
                                ? 'bg-white hover:bg-blue-50'
                                : 'bg-slate-50 hover:bg-blue-50'
                            }
                          `}
                        >
                          
                          {dataStreamInfos.length > 1 && (
                            <>
                              <td className="px-3 py-2 align-middle">
                                <div className="flex items-center gap-2">
                                  
                                  <span
                                    className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
                                    style={{ backgroundColor: row.chartColor }}
                                    title={`Chart color for ${row.sensorName}`}
                                  />
                                  <div className="min-w-0">
                                    <div className="font-medium text-slate-800 truncate" title={row.sensorName}>
                                      {row.isPrimary && <span className="text-blue-600 mr-1">★</span>}
                                      {row.sensorName}
                                    </div>
                                    <div className="text-xs text-slate-500 truncate" title={`ID: ${row.externalSensorId ?? 'N/A'}`}>
                                      ID: {row.externalSensorId ?? 'N/A'}
                                    </div>
                                  </div>
                                </div>
                              </td>
                              <td className="px-3 py-2 align-middle whitespace-nowrap">
                                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-slate-200 text-slate-600">
                                  {row.source || 'Unknown'}
                                </span>
                              </td>
                              <td className="px-3 py-2 align-middle whitespace-nowrap">
                                <span className="font-medium">{row.parameterDisplayName}</span>
                              </td>
                            </>
                          )}
                          
                          
                          <td className="px-3 py-2 whitespace-nowrap align-middle">
                            {formatTimestamp(row.timestamp, timezoneMode, streamTimezone)}
                          </td>
                          <td className="px-3 py-2 align-middle font-mono">
                            {formatValueForDisplay(row.parameterCode, row.value, aggregate)}
                          </td>
                          <td className="px-3 py-2 align-middle whitespace-nowrap text-slate-600">
                            {row.unit}
                          </td>
                          <td className="px-3 py-2 align-middle">
                            {!row.isValid ? (
                              <span className="text-red-700 font-semibold">Invalid</span>
                            ) : (
                              <span className="text-green-700">Valid</span>
                            )}
                          </td>
                          <td className="px-3 py-2 align-middle">
                            {row.failedChecks && row.failedChecks.length > 0
                              ? row.failedChecks.map((check, checkIndex) => (
                                  <span
                                    key={`${check.check_code}-${checkIndex}`}
                                    className="inline-block bg-red-100 text-red-700 rounded-full px-2 py-0.5 text-xs font-medium mr-1"
                                    title={check.message || ''}
                                  >
                                    {check.check_code}
                                  </span>
                                ))
                              : <span className="text-slate-400">—</span>
                            }
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
