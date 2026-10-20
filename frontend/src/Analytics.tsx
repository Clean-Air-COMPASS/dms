import { formatMeasurementValue } from './measurementFormatting';
import { Trans, useTranslation } from 'react-i18next';
import i18n from './i18n';
import { checkName } from './qc/presentation';
import MeasurementQcDetails from './components/MeasurementQcDetails';
import { matchesQcFilter, measurementQcStatus, type MeasurementQcFilter } from './measurementQc';
import type { MeasurementHistoryDataPoint } from './measurementHistory';
import { ApiError } from './apiError';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import UserMenu from './components/UserMenu';
import SensorChart from './SensorChart';
import { fetchJson } from './api';
import { fetchMeasurementHistory, type MeasurementHistoryResponse } from './measurementHistory';
import DataStreamSelectionModal, { type AirQualityIndexDeviceOption } from './components/DataStreamSelectionModal';
import DataStreamSummaryPanel, { type DataStreamInfo } from './components/DataStreamSummaryPanel';
import { isValidAnalyticsDateRange } from './analyticsDateRange';
import ZonedDateTimeInput from './components/ZonedDateTimeInput';
import { getAggregationDisplayLabel } from './aqi';
import { calculateDisplayRange, calculateTotalPages, DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, slicePage } from './utils/pagination';
import { resolveDisplayTimezone, formatTimestamp, getTimezoneLabel, getTimezoneOptionLabel, TIMEZONE_OPTIONS, type TimezoneMode } from './utils/timezone';
import {
  MAX_ANALYTICS_SCALE_GROUPS,
  MAX_ANALYTICS_SERIES,
  analyticsScaleGroupKey,
  analyticsSeriesKey,
  readAnalyticsSeries,
  writeAnalyticsSeries,
  type AirQualityIndexSeriesSelection,
  type AnalyticsScaleDescriptor,
  type AnalyticsSeriesSelection,
  type MeasurementSeriesSelection,
} from './analyticsSeries';
import {
  getAirQualityIndexAnalyticsHistory,
  listAirQualityIndexStandards,
  type AirQualityIndexAnalyticsHistory,
  type AirQualityIndexAnalyticsPoint,
  type AirQualityIndexAnalyticsSeries,
  type AirQualityIndexStandardMetadata,
} from './airQualityIndex';
import {
  EEA_EUROPEAN_STANDARD_CODE,
  formatEuropeanAqiConcentration,
  formatPollutantList,
  getAirQualityIndexCategoryLabel,
  getAirQualityIndexCoverageStatusLabel,
  getAirQualityIndexProductLabel,
  getAirQualityIndexStandardLabel,
  getAirQualityIndexTimeResolutionLabel,
  getExclusionReasonLabel,
} from './airQualityIndexPresentation';
import { buildAnalyticsCsv } from './analyticsCsv';
import { createUtf8CsvBlob } from './measurementCsv';
import { getMeasurementTimestampRoleLabel } from './measurementTimestampPresentation';
import { getParameterDisplayName } from './parameterPresentation';
import DataAttribution from './components/DataAttribution';
import type { DataAttribution as DataAttributionValue } from './dataAttribution';

type AnalyticsTableRow = {
  rowKey: string;
  seriesKey: string;
  seriesType: 'measurement' | 'aqi';
  sensorName: string;
  externalSensorId: string | number | null;
  source: string | null;
  parameterCode: string;
  parameterDisplayName: string;
  parameterName: string | null;
  measurementId: number | null;
  sensorId: number | null;
  deviceId: number | null;
  deviceName: string | null;
  latitude: number | null;
  longitude: number | null;
  shownDuration: string;
  timestamp: string;
  intervalStartedAt: string | null;
  intervalEndedAt: string | null;
  measurementTimestampSemantics: string | null;
  representedLocalDate: string | null;
  value: number | null;
  unit: string;
  concentrationUnit: string | null;
  categoryLabel: string | null;
  normalizedConcentration: number | null;
  preprocessedConcentration: number | null;
  isValid: boolean | null;
  coverageStatus: string | null;
  eligibilityStatus: string | null;
  exclusionReason: string | null;
  dominantPollutants: string[];
  availablePollutants: string[];
  missingPollutants: string[];
  ineligiblePollutants: string[];
  standardDisplayName: string | null;
  standardCode: string | null;
  productDisplayName: string | null;
  failedChecks: { check_code: string; severity?: string; message?: string | null }[];
  dataAttribution: DataAttributionValue | null;
  measurementPoint?: MeasurementHistoryDataPoint;
  displayPrecision?: number | null;
};

type TableSortColumn = 'timestamp' | 'value' | 'status' | 'sensorName' | 'source' | 'parameter';

const CHART_COLORS = ['#0074D9', '#FF4136', '#2ECC40', '#FF851B', '#7FDBFF', '#B10DC9'];

function recencyToHours(recency: string): number {
  if (recency === 'all') return 168;
  const match = recency.match(/^(\d+)\s*([hd])$/);
  if (!match) return 24;
  const count = Number(match[1]);
  if (!Number.isFinite(count) || count <= 0) return 24;
  return match[2] === 'd' ? count * 24 : count;
}

function shownDuration(aggregationCode: string | null | undefined): string {
  const code = (aggregationCode || 'hour').toLowerCase();
  return getAggregationDisplayLabel(code);
}

function aqiSeriesKey(series: AirQualityIndexAnalyticsSeries): string {
  return analyticsSeriesKey({
    kind: 'aqi',
    standard_code: series.standard_code,
    product_code: series.product_code,
    device_id: series.device_id,
  });
}

function AnalyticsWorkspace() {
  const { i18n: activeI18n } = useTranslation();
  const activeLanguage = activeI18n.resolvedLanguage;
  const [searchParams, setSearchParams] = useSearchParams();
  const searchString = searchParams.toString();
  const selectedSeries = useMemo(() => readAnalyticsSeries(new URLSearchParams(searchString)), [searchString]);
  const measurementSelections = useMemo(
    () => selectedSeries.filter((series): series is MeasurementSeriesSelection => series.kind === 'measurement'),
    [selectedSeries],
  );
  const aqiSelections = useMemo(
    () => selectedSeries.filter((series): series is AirQualityIndexSeriesSelection => series.kind === 'aqi'),
    [selectedSeries],
  );
  const primarySeriesKey = selectedSeries[0] ? analyticsSeriesKey(selectedSeries[0]) : null;
  const urlStart = searchParams.get('start') || '';
  const urlEnd = searchParams.get('end') || '';
  const recencyRaw = (searchParams.get('recency') || '24h').toLowerCase();
  const hours = recencyToHours(recencyRaw);
  const [startValid, setStartValid] = useState(true);
  const [endValid, setEndValid] = useState(true);
  const rangeValid = startValid && endValid && isValidAnalyticsDateRange(urlStart, urlEnd);

  const [includeInvalid, setIncludeInvalid] = useState(false);
  const [qcFilter, setQcFilter] = useState<MeasurementQcFilter>('all');
  const [measurementHistories, setMeasurementHistories] = useState<MeasurementHistoryResponse[]>([]);
  const [measurementLoading, setMeasurementLoading] = useState(false);
  const [measurementError, setMeasurementError] = useState<string | null>(null);
  const [aqiStandards, setAqiStandards] = useState<AirQualityIndexStandardMetadata[]>([]);
  const [aqiDevices, setAqiDevices] = useState<AirQualityIndexDeviceOption[]>([]);
  const [aqiHistory, setAqiHistory] = useState<AirQualityIndexAnalyticsHistory | null>(null);
  const [aqiCatalogLoading, setAqiCatalogLoading] = useState(false);
  const [aqiCatalogError, setAqiCatalogError] = useState<string | null>(null);
  const [aqiLoading, setAqiLoading] = useState(false);
  const [aqiError, setAqiError] = useState<string | null>(null);
  const [normalizationNotice, setNormalizationNotice] = useState<string | null>(null);
  const [dataStreamModalOpen, setDataStreamModalOpen] = useState(false);
  const [showSeriesFilterDropdown, setShowSeriesFilterDropdown] = useState(false);
  const [tableFilteredSeriesKeys, setTableFilteredSeriesKeys] = useState<string[] | null>(null);
  const [sortColumn, setSortColumn] = useState<TableSortColumn>('timestamp');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [retryToken, setRetryToken] = useState(0);
  const autoRangeForRecencyRef = useRef<string | null>(null);
  const pendingRangeEditsRef = useRef<Partial<Record<'start' | 'end', string>>>({});
  useEffect(() => {
    pendingRangeEditsRef.current = {};
  }, [searchString]);
  // Readiness must commit with the catalog used to validate navigation targets.
  const [aqiCatalogLoaded, setAqiCatalogLoaded] = useState(false);

  const requestedTimezoneMode = (searchParams.get('timezone') || '').toLowerCase();
  const defaultTimezoneMode: TimezoneMode = selectedSeries[0]?.kind === 'aqi' ? 'utc' : 'stream';
  const timezoneMode: TimezoneMode = ['local', 'utc', 'stream'].includes(requestedTimezoneMode)
    ? requestedTimezoneMode as TimezoneMode
    : defaultTimezoneMode;

  useEffect(() => {
    const canonicalValues = searchParams.getAll('series');
    const expectedValues = selectedSeries.map(analyticsSeriesKey);
    const legacyKeys = ['sensor_id', 'overlay', 'standard_code', 'product_code', 'device_id', 'compare', 'layer'];
    const hasLegacyState = legacyKeys.some((key) => searchParams.has(key));
    if (!hasLegacyState && canonicalValues.join(',') === expectedValues.join(',')) return;
    const next = writeAnalyticsSeries(searchParams, selectedSeries);
    const legacyRange = searchParams.get('range');
    if (!next.has('recency') && legacyRange) next.set('recency', legacyRange);
    setSearchParams(next, { replace: true });
    setNormalizationNotice(i18n.t('analytics:analytics.messages.analyticsLinkWasNormalizedUnifiedSeries'));
  }, [searchParams, selectedSeries, setSearchParams]);

  useEffect(() => {
    if (!selectedSeries.length) setDataStreamModalOpen(true);
  }, [selectedSeries.length]);

  useEffect(() => {
    if (!recencyRaw || searchParams.has('start') || searchParams.has('end') || autoRangeForRecencyRef.current === recencyRaw) return;
    autoRangeForRecencyRef.current = recencyRaw;
    const now = new Date();
    const endedAt = new Date(now);
    if (endedAt.getMinutes() || endedAt.getSeconds() || endedAt.getMilliseconds()) endedAt.setHours(endedAt.getHours() + 1);
    endedAt.setMinutes(0, 0, 0);
    const startedAt = new Date(now.getTime() - hours * 3_600_000);
    startedAt.setMinutes(0, 0, 0);
    const next = new URLSearchParams(searchParams);
    next.set('start', startedAt.toISOString());
    next.set('end', endedAt.toISOString());
    setSearchParams(next, { replace: true });
  }, [hours, recencyRaw, searchParams, setSearchParams, urlEnd, urlStart]);

  useEffect(() => {
    if (!dataStreamModalOpen && !aqiSelections.length) return;
    if (aqiCatalogLoaded) return;
    const controller = new AbortController();
    setAqiCatalogLoading(true);
    setAqiCatalogError(null);
    Promise.all([
      listAirQualityIndexStandards(),
      fetchJson<AirQualityIndexDeviceOption[]>('/devices', { signal: controller.signal, skipCache: true }),
    ]).then(([standards, devices]) => {
      if (controller.signal.aborted) return;
      setAqiStandards(standards);
      setAqiDevices(devices.filter((device) => device.sensor_count > 0));
      setAqiCatalogLoaded(true);
    }).catch((catalogError: unknown) => {
      if (catalogError instanceof DOMException && catalogError.name === 'AbortError') return;
      setAqiCatalogError(i18n.t('analytics:analytics.messages.aqiStandardsDevicesCouldNotLoaded'));
    }).finally(() => {
      if (!controller.signal.aborted) setAqiCatalogLoading(false);
    });
    return () => controller.abort();
  }, [aqiSelections.length, dataStreamModalOpen, retryToken, aqiCatalogLoaded]);

  useEffect(() => {
    if (!measurementSelections.length) {
      setMeasurementHistories([]);
      setMeasurementError(null);
      setMeasurementLoading(false);
      return;
    }
    if (!rangeValid) {
      setMeasurementLoading(false);
      return;
    }
    const controller = new AbortController();
    setMeasurementLoading(true);
    setMeasurementError(null);
    Promise.allSettled(measurementSelections.map((selection) => fetchMeasurementHistory({
      sensorId: selection.sensor_id,
      parameterCode: selection.parameter_code,
      aggregation: selection.aggregation_code,
      start: urlStart,
      end: urlEnd,
      includeInvalid,
      signal: controller.signal,
    }))).then((results) => {
      if (controller.signal.aborted) return;
      const available = results.flatMap((result) => result.status === 'fulfilled' ? [result.value] : []);
      const failedCount = results.length - available.length;
      setMeasurementHistories(available);
      setMeasurementError(failedCount
        ? i18n.t('analytics:analytics.messages.measurementSeriesLoadFailed', { count: failedCount })
        : null);
    }).finally(() => {
      if (!controller.signal.aborted) setMeasurementLoading(false);
    });
    return () => controller.abort();
  }, [hours, includeInvalid, measurementSelections, rangeValid, retryToken, urlEnd, urlStart]);

  useEffect(() => {
    if (!aqiCatalogLoaded || !aqiSelections.length) return;
    const validAqiKeys = new Set<string>();
    aqiSelections.forEach((selection) => {
      const standard = aqiStandards.find((candidate) => candidate.standard_code === selection.standard_code);
      const product = standard?.products.find((candidate) => (
        candidate.product_code === selection.product_code
        && candidate.availability_status === 'available'
        && (!candidate.history_status || candidate.history_status === 'available')
      ));
      const deviceExists = aqiDevices.some((device) => device.device_id === selection.device_id);
      if (standard && product && deviceExists) validAqiKeys.add(analyticsSeriesKey(selection));
    });
    if (validAqiKeys.size === aqiSelections.length) return;
    const normalized = selectedSeries.filter((selection) => (
      selection.kind === 'measurement' || validAqiKeys.has(analyticsSeriesKey(selection))
    ));
    setNormalizationNotice(i18n.t('analytics:analytics.messages.unsupportedUnavailableAqiSeriesWereRemoved'));
    setSearchParams(writeAnalyticsSeries(searchParams, normalized), { replace: true });
  }, [aqiDevices, aqiSelections, aqiStandards, searchParams, selectedSeries, setSearchParams, aqiCatalogLoaded]);

  useEffect(() => {
    if (!aqiSelections.length) {
      setAqiHistory(null);
      setAqiError(null);
      setAqiLoading(false);
      return;
    }
    const selectionsAreCatalogValid = aqiStandards.length > 0 && aqiSelections.every((selection) => {
      const standard = aqiStandards.find((candidate) => candidate.standard_code === selection.standard_code);
      const productExists = standard?.products.some((candidate) => (
        candidate.product_code === selection.product_code
        && candidate.availability_status === 'available'
        && (!candidate.history_status || candidate.history_status === 'available')
      ));
      return productExists && aqiDevices.some((device) => device.device_id === selection.device_id);
    });
    if (!selectionsAreCatalogValid) return;
    if (!rangeValid) {
      setAqiLoading(false);
      return;
    }
    const controller = new AbortController();
    setAqiLoading(true);
    setAqiError(null);
    getAirQualityIndexAnalyticsHistory(
      urlStart,
      urlEnd,
      aqiSelections.map(({ standard_code, product_code, device_id }) => ({ standard_code, product_code, device_id })),
      controller.signal,
    ).then((response) => {
      if (!controller.signal.aborted) setAqiHistory(response);
    }).catch((historyError: unknown) => {
      if (historyError instanceof DOMException && historyError.name === 'AbortError') return;
      setAqiHistory(null);
      setAqiError(historyError instanceof ApiError && historyError.errorCode === 'aqi_history_range_exceeded'
        ? i18n.t('analytics:analytics.messages.aqiHistoryRangeExceeded', { count: historyError.errorContext.maximum_days })
        : i18n.t('analytics:analytics.messages.aqiHistoryLoadFailed'));
    }).finally(() => {
      if (!controller.signal.aborted) setAqiLoading(false);
    });
    return () => controller.abort();
  }, [aqiDevices, aqiSelections, aqiStandards, rangeValid, retryToken, urlEnd, urlStart]);

  const measurementByKey = useMemo(
    () => new Map(measurementHistories.map((item) => [item._seriesKey, item])),
    [measurementHistories],
  );
  const aqiByKey = useMemo(
    () => new Map((aqiHistory?.series || []).map((item) => [aqiSeriesKey(item), item])),
    [aqiHistory],
  );

  const resolvedScaleDescriptors = useMemo(() => selectedSeries.flatMap((selection): AnalyticsScaleDescriptor[] => {
    const key = analyticsSeriesKey(selection);
    if (selection.kind === 'measurement') {
      const response = measurementByKey.get(key);
      return response ? [{ kind: 'measurement', normalized_unit: response.unit || i18n.t('analytics:analytics.states.unknownUnit') }] : [];
    }
    const response = aqiByKey.get(key);
    return response ? [{ kind: 'aqi', result_kind: response.result_kind, standard_code: response.standard_code }] : [];
  }), [aqiByKey, measurementByKey, selectedSeries]);
  const scaleGroupKeys = useMemo(
    () => [...new Set(resolvedScaleDescriptors.map(analyticsScaleGroupKey))],
    [resolvedScaleDescriptors],
  );

  const dataStreamInfos = useMemo(() => selectedSeries.flatMap((selection, index): DataStreamInfo[] => {
    void activeLanguage;
    const key = analyticsSeriesKey(selection);
    const isPrimary = index === 0;
    const chartColor = CHART_COLORS[index % CHART_COLORS.length];
    if (selection.kind === 'measurement') {
      const response = measurementByKey.get(key);
      if (!response) return [];
      return [{
        kind: 'measurement', seriesKey: key, sensorId: response.sensor_id, deviceId: null,
        sensorName: response.device_friendly_name || response.device_name || i18n.t('analytics:analytics.dynamic.sensor', { id: response.sensor_id }),
        externalSensorId: response.external_sensor_id ?? null,
        parameterCode: response.parameter,
        parameterDisplayName: getParameterDisplayName(response.parameter, response.parameter_name),
        unit: response.unit, aggregateCode: selection.aggregation_code,
        shownDuration: shownDuration(selection.aggregation_code), source: response.external_api?.name ?? null,
        isPrimary, chartColor,
      }];
    }
    const response = aqiByKey.get(key);
    if (!response) return [];
    return [{
      kind: 'aqi', seriesKey: key, sensorId: null, deviceId: response.device_id,
      sensorName: response.device_friendly_name || response.device_name || i18n.t('analytics:analytics.dynamic.device', { id: response.device_id }),
      externalSensorId: response.device_id, parameterCode: response.parameter_code || 'overall',
      parameterDisplayName: response.parameter_code?.toUpperCase() || i18n.t('analytics:analytics.states.overall'),
      unit: response.result_kind === 'numeric' ? 'AQI' : i18n.t('analytics:analytics.states.category'), aggregateCode: response.aggregation_period,
      shownDuration: getAirQualityIndexTimeResolutionLabel(response), source: response.source_name,
      isPrimary, chartColor, standardDisplayName: getAirQualityIndexStandardLabel(response.standard_code), standardCode: response.standard_code,
      productDisplayName: getAirQualityIndexProductLabel(response.product_code), resultKind: response.result_kind,
      historyInterval: response.history_interval,
    }];
  }), [activeLanguage, aqiByKey, measurementByKey, selectedSeries]);

  const ambiguousMeasurementSeriesKeys = useMemo(() => {
    const identityCounts = new Map<string, number>();
    dataStreamInfos.forEach((stream) => {
      if (stream.kind !== 'measurement') return;
      const identity = [stream.sensorName, stream.parameterCode, stream.aggregateCode].join('|');
      identityCounts.set(identity, (identityCounts.get(identity) || 0) + 1);
    });
    return new Set(dataStreamInfos.flatMap((stream) => {
      if (stream.kind !== 'measurement') return [];
      const identity = [stream.sensorName, stream.parameterCode, stream.aggregateCode].join('|');
      return (identityCounts.get(identity) || 0) > 1 ? [stream.seriesKey] : [];
    }));
  }, [dataStreamInfos]);

  const streamTimezone = useMemo(() => {
    if (!primarySeriesKey) return null;
    return measurementByKey.get(primarySeriesKey)?.device_timezone
      || aqiByKey.get(primarySeriesKey)?.device_timezone
      || null;
  }, [aqiByKey, measurementByKey, primarySeriesKey]);

  const displayTimezone = resolveDisplayTimezone(timezoneMode, streamTimezone);
  // A device timezone is unavailable before selection (or when metadata is missing).
  // Edit explicit UTC instants in that case; chart/table timestamp semantics stay unchanged.
  const rangeTimezone = displayTimezone || 'UTC';

  const primaryMeasurementHistory = primarySeriesKey ? measurementByKey.get(primarySeriesKey) || null : null;
  const primaryAqiHistory = primarySeriesKey ? aqiByKey.get(primarySeriesKey) || null : null;
  const measurementAttributions = useMemo(() => {
    const uniqueAttributions = new Map<string, DataAttributionValue>();
    measurementHistories.forEach((history) => {
      if (!history.data_attribution) return;
      uniqueAttributions.set(JSON.stringify(history.data_attribution), history.data_attribution);
    });
    return [...uniqueAttributions.values()];
  }, [measurementHistories]);

  const summary = useMemo(() => {
    void activeLanguage;
    if (primaryMeasurementHistory) {
      const points = primaryMeasurementHistory.data;
      const validCount = points.filter((point) => point.is_valid !== false).length;
      const considered = points.filter((point) => includeInvalid || point.is_valid !== false);
      const values = considered.map((point) => point.value).filter((value) => typeof value === 'number' && Number.isFinite(value));
      const latest = [...considered].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))[0];
      return {
        firstTitle: i18n.t('analytics:analytics.summary.latest'), firstValue: latest ? formatMeasurementValue(latest.value, primaryMeasurementHistory.display_precision) : '—', firstUnit: primaryMeasurementHistory.unit,
        secondUnit: primaryMeasurementHistory.unit,
        secondTitle: i18n.t('analytics:analytics.summary.average'), secondValue: values.length ? formatMeasurementValue(values.reduce((sum, value) => sum + value, 0) / values.length, primaryMeasurementHistory.display_precision) : '—',
        thirdUnit: primaryMeasurementHistory.unit,
        thirdTitle: i18n.t('analytics:analytics.summary.minimumMaximum'), thirdValue: values.length ? `${formatMeasurementValue(Math.min(...values), primaryMeasurementHistory.display_precision)} / ${formatMeasurementValue(Math.max(...values), primaryMeasurementHistory.display_precision)}` : '—',
        fourthTitle: i18n.t('analytics:analytics.summary.returnedReadings'), fourthValue: points.length
          ? i18n.t('analytics:analytics.summary.percentValid', { value: Math.round(validCount / points.length * 100) }) : '—',
      };
    }
    if (primaryAqiHistory) {
      const calculated = primaryAqiHistory.points.filter((point) => point.calculation_status === 'calculated');
      const latest = [...calculated].sort((a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at))[0];
      const numericValues = calculated.map((point) => point.numeric_value).filter((value): value is number => value != null);
      const worstCategory = primaryAqiHistory.result_kind === 'categorical'
        ? calculated.reduce<AirQualityIndexAnalyticsPoint | null>((worst, point) => {
            const categories = aqiStandards.find((standard) => standard.standard_code === primaryAqiHistory.standard_code)?.categories || [];
            const rank = categories.find((category) => category.code === point.category_code)?.internal_severity_rank ?? -1;
            const worstRank = categories.find((category) => category.code === worst?.category_code)?.internal_severity_rank ?? -1;
            return rank > worstRank ? point : worst;
          }, null)
        : null;
      return {
        firstTitle: i18n.t('analytics:analytics.summary.latest'), firstValue: latest?.numeric_value != null ? String(latest.numeric_value) : latest?.category_code ? getAirQualityIndexCategoryLabel(latest.category_code) : '—', firstUnit: latest?.numeric_value != null ? 'AQI' : '',
        secondTitle: primaryAqiHistory.result_kind === 'numeric' ? i18n.t('analytics:analytics.summary.average') : i18n.t('analytics:analytics.summary.coverage'),
        secondValue: numericValues.length ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(numericValues.reduce((sum, value) => sum + value, 0) / numericValues.length) : latest?.coverage_status ? getAirQualityIndexCoverageStatusLabel(latest.coverage_status) : '—',
        thirdTitle: primaryAqiHistory.result_kind === 'numeric' ? i18n.t('analytics:analytics.summary.minimumMaximum') : i18n.t('analytics:analytics.summary.worstCategory'),
        thirdValue: numericValues.length ? `${Math.min(...numericValues)} / ${Math.max(...numericValues)}` : worstCategory?.category_code ? getAirQualityIndexCategoryLabel(worstCategory.category_code) : '—',
        fourthTitle: i18n.t('analytics:analytics.summary.availability'), fourthValue: i18n.t('analytics:analytics.summary.percentCalculated', { value: primaryAqiHistory.points.length ? Math.round(calculated.length / primaryAqiHistory.points.length * 100) : 0 }),
      };
    }
    return null;
  }, [activeLanguage, aqiStandards, includeInvalid, primaryAqiHistory, primaryMeasurementHistory]);

  const allRows = useMemo(() => {
    void activeLanguage;
    const rows: AnalyticsTableRow[] = [];
    selectedSeries.forEach((selection) => {
      const key = analyticsSeriesKey(selection);
      if (selection.kind === 'measurement') {
        const response = measurementByKey.get(key);
        if (!response) return;
        response.data.forEach((point, index) => rows.push({
          rowKey: `${key}-${index}-${point.timestamp}`, seriesKey: key, seriesType: 'measurement',
          sensorName: response.device_friendly_name || response.device_name || i18n.t('analytics:analytics.dynamic.sensor', { id: response.sensor_id }), externalSensorId: response.external_sensor_id ?? null,
          source: response.external_api?.name ?? null, parameterCode: response.parameter,
          parameterDisplayName: getParameterDisplayName(response.parameter, response.parameter_name),
          parameterName: response.parameter_name,
          measurementId: point.measurement_id ?? null,
          measurementPoint: point,
          displayPrecision: response.display_precision,
          sensorId: response.sensor_id,
          deviceId: response.device_id ?? null,
          deviceName: response.device_friendly_name || response.device_name || null,
          latitude: response.latitude ?? null,
          longitude: response.longitude ?? null,
          shownDuration: shownDuration(selection.aggregation_code), timestamp: point.timestamp,
          intervalStartedAt: point.interval_started_at || null, intervalEndedAt: point.interval_ended_at || null,
          measurementTimestampSemantics: response.measurement_timestamp_semantics || null, representedLocalDate: null,
          value: point.value, unit: response.unit, concentrationUnit: null,
          categoryLabel: null, normalizedConcentration: null, preprocessedConcentration: null,
          isValid: point.is_valid !== false, coverageStatus: null,
          eligibilityStatus: null, exclusionReason: null, dominantPollutants: [], availablePollutants: [], missingPollutants: [], ineligiblePollutants: [],
          standardDisplayName: null, standardCode: null, productDisplayName: null, failedChecks: point.failed_checks || [],
          dataAttribution: response.data_attribution || null,
        }));
        return;
      }
      const response = aqiByKey.get(key);
      if (!response) return;
      response.points.forEach((point, index) => rows.push({
        rowKey: `${key}-${index}-${point.observed_at}`, seriesKey: key, seriesType: 'aqi',
        sensorName: response.device_friendly_name || response.device_name || i18n.t('analytics:analytics.dynamic.device', { id: response.device_id }), externalSensorId: response.device_id,
        source: response.source_name, parameterCode: response.product_code,
        parameterDisplayName: getAirQualityIndexProductLabel(response.product_code), shownDuration: getAirQualityIndexTimeResolutionLabel(response),
        parameterName: null, measurementId: null, sensorId: null, deviceId: response.device_id,
        deviceName: response.device_friendly_name || response.device_name || null, latitude: null, longitude: null,
        timestamp: point.observed_at, intervalStartedAt: point.interval_started_at, intervalEndedAt: point.interval_ended_at,
        measurementTimestampSemantics: null, representedLocalDate: point.represented_local_date,
        value: point.numeric_value,
        unit: response.result_kind === 'numeric' ? 'AQI' : i18n.t('analytics:analytics.states.category'),
        concentrationUnit: point.normalized_unit,
        categoryLabel: point.category_code ? getAirQualityIndexCategoryLabel(point.category_code) : null,
        normalizedConcentration: point.normalized_concentration,
        preprocessedConcentration: point.preprocessed_concentration,
        isValid: null,
        coverageStatus: point.coverage_status, eligibilityStatus: point.eligibility_status, exclusionReason: point.exclusion_reason,
        dominantPollutants: point.dominant_pollutants, availablePollutants: point.available_pollutants,
        missingPollutants: point.missing_pollutants, ineligiblePollutants: point.ineligible_pollutants,
        standardDisplayName: getAirQualityIndexStandardLabel(response.standard_code), standardCode: response.standard_code, productDisplayName: getAirQualityIndexProductLabel(response.product_code), failedChecks: [],
        dataAttribution: null,
      }));
    });
    return rows;
  }, [activeLanguage, aqiByKey, measurementByKey, selectedSeries]);

  const filteredRows = useMemo(() => allRows.filter((row) => {
    if (tableFilteredSeriesKeys !== null && !tableFilteredSeriesKeys.includes(row.seriesKey)) return false;
    if (measurementSelections.length > 0 && qcFilter !== 'all' && (!row.measurementPoint || !matchesQcFilter(row.measurementPoint, qcFilter))) return false;
    return row.seriesType === 'aqi' || includeInvalid || row.isValid;
  }), [allRows, includeInvalid, tableFilteredSeriesKeys, qcFilter, measurementSelections.length]);

  const sortedRows = useMemo(() => [...filteredRows].sort((left, right) => {
    let comparison = 0;
    if (sortColumn === 'timestamp') comparison = Date.parse(left.timestamp) - Date.parse(right.timestamp);
    if (sortColumn === 'value') comparison = (left.value ?? Number.NEGATIVE_INFINITY) - (right.value ?? Number.NEGATIVE_INFINITY);
    if (sortColumn === 'status') comparison = `${left.coverageStatus || (left.isValid ? 'valid' : 'invalid')}`.localeCompare(`${right.coverageStatus || (right.isValid ? 'valid' : 'invalid')}`);
    if (sortColumn === 'sensorName') comparison = left.sensorName.localeCompare(right.sensorName);
    if (sortColumn === 'source') comparison = (left.source || '').localeCompare(right.source || '');
    if (sortColumn === 'parameter') comparison = left.parameterDisplayName.localeCompare(right.parameterDisplayName);
    return sortDirection === 'asc' ? comparison : -comparison;
  }), [filteredRows, sortColumn, sortDirection]);

  useEffect(() => setCurrentPage(1), [pageSize, sortedRows]);
  const totalPages = calculateTotalPages(sortedRows.length, pageSize);
  const displayRange = calculateDisplayRange(currentPage, pageSize, sortedRows.length);
  const paginatedRows = slicePage(sortedRows, currentPage, pageSize);
  const hasAqi = aqiSelections.length > 0;
  const loading = measurementLoading || aqiLoading;
  const hasAvailableSeries = dataStreamInfos.length > 0;

  const updateSeries = useCallback((nextSeries: AnalyticsSeriesSelection[]) => {
    const next = writeAnalyticsSeries(searchParams, nextSeries);
    setSearchParams(next);
  }, [searchParams, setSearchParams]);

  const addSeries = useCallback((selection: AnalyticsSeriesSelection, role: 'primary' | 'overlay') => {
    const key = analyticsSeriesKey(selection);
    const withoutDuplicate = selectedSeries.filter((item) => analyticsSeriesKey(item) !== key);
    const next = role === 'primary' ? [selection, ...withoutDuplicate] : [...withoutDuplicate, selection];
    if (next.length > MAX_ANALYTICS_SERIES) return;
    updateSeries(next);
  }, [selectedSeries, updateSeries]);

  const removeSeries = useCallback((seriesKey: string) => {
    updateSeries(selectedSeries.filter((selection) => analyticsSeriesKey(selection) !== seriesKey));
    setTableFilteredSeriesKeys(null);
  }, [selectedSeries, updateSeries]);

  const setRangeBoundary = (boundary: 'start' | 'end', value: string) => {
    // The router clones the last rendered parameters for each update. Keep
    // both edits together until navigation commits so a rapid second edit
    // cannot restore the first boundary's previous value.
    const edits = pendingRangeEditsRef.current;
    edits[boundary] = value;
    const next = new URLSearchParams(searchParams);
    if (edits.start !== undefined) next.set('start', edits.start);
    if (edits.end !== undefined) next.set('end', edits.end);
    setSearchParams(next);
  };

  const closeDataStreamModal = () => {
    // Invalid clock text is an uncommitted input draft. Closing the modal
    // discards that draft; valid edits already belong to the page's URL range.
    setStartValid(true);
    setEndValid(true);
    setDataStreamModalOpen(false);
  };

  const setTimezoneMode = (mode: TimezoneMode) => {
    const next = new URLSearchParams(searchParams);
    next.set('timezone', mode);
    setSearchParams(next);
  };

  const downloadCsv = () => {
    if (!sortedRows.length) return;
    const csv = buildAnalyticsCsv(sortedRows, hasAqi);
    const url = URL.createObjectURL(createUtf8CsvBlob(csv));
    const link = document.createElement('a');
    link.href = url;
    link.download = hasAqi
      ? `analytics_${new Date().toISOString().slice(0, 10)}_${selectedSeries.length}_series.csv`
      : `measurements_${new Date().toISOString().slice(0, 10)}_${selectedSeries.length}_streams.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const primaryMapPath = useMemo(() => {
    const primary = selectedSeries[0];
    if (!primary || primary.kind === 'measurement') return '/map';
    const product = aqiByKey.get(analyticsSeriesKey(primary));
    const query = new URLSearchParams({
      mode: 'pollutants',
      display_mode: primary.standard_code === 'eea_european'
        ? 'eea_european'
        : primary.standard_code === 'philippines_denr'
          ? 'philippines_denr'
          : 'us_epa',
      standard_code: primary.standard_code, product_code: primary.product_code, device_id: String(primary.device_id), recency: '24h',
    });
    if (product?.source_name) query.set('source', product.source_name);
    if (urlEnd) query.set('until', urlEnd);
    return `/map?${query.toString()}`;
  }, [aqiByKey, selectedSeries, urlEnd]);

  const toggleSort = (column: TableSortColumn) => {
    if (sortColumn === column) setSortDirection((direction) => direction === 'asc' ? 'desc' : 'asc');
    else { setSortColumn(column); setSortDirection(column === 'timestamp' ? 'desc' : 'asc'); }
  };
  const SortIndicator = ({ column }: { column: TableSortColumn }) => sortColumn === column
    ? <span aria-hidden="true" className="text-blue-600 ml-1">{sortDirection === 'asc' ? '↑' : '↓'}</span>
    : <span aria-hidden="true" className="text-slate-300 ml-1">↕</span>;

  const renderSortHeader = (column: TableSortColumn, label: React.ReactNode) => (
    <th scope="col" className="text-left font-semibold px-3 py-2 bg-slate-50 border-b whitespace-nowrap"
      aria-sort={sortColumn === column ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="inline-flex items-center rounded px-1 py-1 focus-visible:outline-2 focus-visible:outline-blue-600"
        onClick={() => toggleSort(column)}>
        {label}<SortIndicator column={column} />
      </button>
    </th>
  );

  const MetricCard = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div className="flex-1 min-w-0 w-full sm:w-auto p-3 rounded-lg shadow-sm bg-white border border-slate-100 hover:shadow-md">
      <div className="text-xs text-slate-400">{title}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight break-words">{children}</div>
    </div>
  );

  return (
    <div className="min-h-screen bg-[#f9fafb] font-sans text-slate-800">
      <header className="sticky top-0 z-10 bg-white/90 border-b border-slate-200 shadow-sm flex flex-wrap sm:flex-nowrap items-center justify-between gap-1 px-2 sm:px-6 py-3">
        <Link to="/map" className="text-lg font-semibold tracking-wide select-none" style={{ textDecoration: 'none', color: 'inherit' }}>COMPASS</Link>
        <div className="flex flex-wrap items-center justify-end gap-1 sm:gap-2 min-w-0 ml-auto">
          <Link className="btn" to={primaryMapPath} title={hasAqi ? i18n.t('analytics:analytics.actions.viewPrimarySeriesMapComparisonSeries') : i18n.t('analytics:analytics.actions.backMap')}>
            {hasAqi ? <><span className="hidden sm:inline"><Trans ns="analytics" i18nKey="analytics.text.viewPrimaryMap" /></span><span className="sm:hidden"><Trans ns="analytics" i18nKey="analytics.text.map" /></span></> : i18n.t('analytics:analytics.actions.map')}
          </Link>
          <Link className="btn" to="/admin"><Trans ns="analytics" i18nKey="analytics.actions.admin" /></Link><UserMenu />
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight"><Trans ns="analytics" i18nKey="analytics.headings.analytics" /></h1>
          {selectedSeries.length > 0 && <span className="text-sm text-slate-600 font-medium">{selectedSeries.length} {i18n.t('analytics:analytics.text.dataStream', { count: selectedSeries.length })}</span>}
        </div>

        <div className="flex flex-wrap items-center gap-4 min-w-0 bg-white border border-slate-200 rounded-lg shadow-sm px-4 py-3">
          <p className="w-full text-sm text-slate-600">{displayTimezone ? i18n.t('analytics:timezones.displayedIn', { timezone: getTimezoneLabel(timezoneMode, streamTimezone) }) : i18n.t('analytics:timezones.rangeInUtc')}</p>
          {(['start', 'end'] as const).map(boundary => <ZonedDateTimeInput key={boundary}
            label={i18n.t(boundary === 'start' ? 'analytics:analytics.fields.start' : 'analytics:analytics.fields.end')}
            iso={boundary === 'start' ? urlStart : urlEnd} timezone={rangeTimezone}
            onValidityChange={boundary === 'start' ? setStartValid : setEndValid}
            onChange={value => setRangeBoundary(boundary, value)} />)}
          <label className="flex items-center gap-2 text-sm"><input aria-describedby="invalid-inclusion-help" type="checkbox" checked={includeInvalid} onChange={(event) => setIncludeInvalid(event.target.checked)} /><span className="font-medium"><Trans ns="analytics" i18nKey="analytics.text.includeInvalidMeasurements" /></span></label>
          <label className="flex w-full sm:w-auto min-w-0 items-center gap-2 text-sm text-slate-600"><Trans ns="analytics" i18nKey="analytics.fields.timezone" /><select className="min-w-0 flex-1 sm:flex-none rounded border border-slate-300 px-2 py-1 text-sm bg-white" value={timezoneMode} onChange={(event) => setTimezoneMode(event.target.value as TimezoneMode)}>
              {TIMEZONE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.value === 'stream' && streamTimezone ? getTimezoneLabel('stream', streamTimezone) : getTimezoneOptionLabel(option)}</option>)}
            </select>
          </label>
          <div className="w-full sm:w-auto sm:ml-auto"><button type="button" className="btn w-full sm:w-auto" disabled={!startValid || !endValid} onClick={() => setDataStreamModalOpen(true)}><Trans ns="analytics" i18nKey="analytics.actions.selectDataStream" /></button></div>
          <p id="invalid-inclusion-help" className="text-sm text-slate-500 mt-2">{i18n.t('analytics:qc.inclusionHelp')}</p>
        </div>

        {!isValidAnalyticsDateRange(urlStart, urlEnd) && <p role="alert" className="text-sm text-red-700">{i18n.t('analytics:analytics.messages.invalidDateRange')}</p>}

        <DataStreamSelectionModal
          displayTimezone={rangeTimezone}
          open={dataStreamModalOpen} onClose={closeDataStreamModal}
          initialParameter={measurementSelections[0]?.parameter_code || ''} initialAggregate={measurementSelections[0]?.aggregation_code || 'hour'}
          startIso={urlStart} endIso={urlEnd} rangeValid={rangeValid}
          onStartChange={value => setRangeBoundary('start', value)} onEndChange={value => setRangeBoundary('end', value)}
          onStartValidityChange={setStartValid} onEndValidityChange={setEndValid}
          existingSelections={measurementSelections.map((selection) => ({ sensor_id: selection.sensor_id, parameter: selection.parameter_code, aggregate: selection.aggregation_code }))}
          existingAqiSelections={aqiSelections} aqiStandards={aqiStandards} aqiDevices={aqiDevices}
          aqiCatalogLoading={aqiCatalogLoading} aqiCatalogError={aqiCatalogError}
          onRetryAqiCatalog={() => setRetryToken((token) => token + 1)}
          currentSeriesCount={selectedSeries.length} existingScaleGroupKeys={scaleGroupKeys}
          onSelectPrimary={(sensorId, parameter, options) => addSeries({ kind: 'measurement', sensor_id: sensorId, parameter_code: parameter.toLowerCase(), aggregation_code: options.aggregate }, 'primary')}
          onSelectOverlay={(sensorId, parameter, options) => addSeries({ kind: 'measurement', sensor_id: sensorId, parameter_code: parameter.toLowerCase(), aggregation_code: options.aggregate }, 'overlay')}
          onSelectAqi={(series, options) => addSeries(series, options.role)}
        />

        {normalizationNotice && <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800" role="status">{normalizationNotice}</div>}
        {scaleGroupKeys.length > MAX_ANALYTICS_SCALE_GROUPS && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><Trans ns="analytics" i18nKey="analytics.text.selectionRequiresMoreThan" />{' '}{MAX_ANALYTICS_SCALE_GROUPS} {' '}<Trans ns="analytics" i18nKey="analytics.text.incompatibleChartScalesRemoveSeriesContinue" /></div>}
        {(measurementError || aqiError) && <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 flex flex-wrap items-center justify-between gap-3" role="alert"><span>{[measurementError, aqiError].filter(Boolean).join(' ')}</span><button type="button" className="btn" onClick={() => setRetryToken((token) => token + 1)}><Trans ns="common" i18nKey="actions.retry" /></button></div>}

        {!loading && hasAvailableSeries && <DataStreamSummaryPanel dataStreams={dataStreamInfos} onRemoveSeries={removeSeries} />}

        {!loading && measurementAttributions.length > 0 && (
          <div className="space-y-2">
            {measurementAttributions.map((attribution) => (
              <DataAttribution key={JSON.stringify(attribution)} value={attribution} />
            ))}
          </div>
        )}

        {!loading && rangeValid && summary && <div className="panel-body"><div className="flex flex-col sm:flex-row gap-4 items-stretch"><div className="flex-1"><div className="flex flex-col sm:flex-row gap-4">
          <MetricCard title={summary.firstTitle}><span>{summary.firstValue}</span>{summary.firstUnit && <span className="ml-2 text-sm text-slate-500">{summary.firstUnit}</span>}</MetricCard>
          <MetricCard title={summary.secondTitle}><span className="text-sm text-slate-700">{summary.secondValue}</span>{summary.secondUnit && <span className="ml-2 text-sm text-slate-500">{summary.secondUnit}</span>}</MetricCard>
          <MetricCard title={summary.thirdTitle}><span className="text-sm text-slate-700">{summary.thirdValue}</span>{summary.thirdUnit && <span className="ml-2 text-sm text-slate-500">{summary.thirdUnit}</span>}</MetricCard>
          <MetricCard title={summary.fourthTitle}><span className="text-sm text-slate-700">{summary.fourthValue}</span></MetricCard>
        </div></div></div></div>}

        {loading && selectedSeries.length > 0 && <div className="bg-white border border-slate-200 rounded-md px-4 py-6 shadow-sm text-center text-blue-700"><Trans ns="analytics" i18nKey="analytics.text.loadingSelectedSeries" /></div>}
        {!selectedSeries.length && !dataStreamModalOpen && <div className="bg-white border border-slate-200 rounded-lg shadow-sm p-8 text-center"><h3 className="text-lg font-medium text-slate-700 mb-2"><Trans ns="analytics" i18nKey="analytics.headings.noDataStreamSelected" /></h3><p className="text-slate-500 mb-4"><Trans ns="analytics" i18nKey="analytics.text.selectMeasurementAqiDataViewAnalytics" /></p><button type="button" className="btn" onClick={() => setDataStreamModalOpen(true)}><Trans ns="analytics" i18nKey="analytics.actions.selectDataStream2" /></button></div>}
        {!loading && rangeValid && selectedSeries.length > 0 && !hasAvailableSeries && <div className="bg-white border border-slate-200 rounded-lg shadow-sm p-8 text-center text-slate-600"><Trans ns="analytics" i18nKey="analytics.text.noSelectedSeriesCouldLoadedWindow" /></div>}

        {!loading && rangeValid && hasAvailableSeries && <>
          <section className="bg-white border border-slate-200 rounded-lg shadow-sm p-4">
            {measurementHistories.filter(history => history.history_status === 'no_eligible_observations').map(history => <p key={history._seriesKey} role="status" className="mb-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <strong>{history.device_friendly_name || history.device_name} · {getParameterDisplayName(history.parameter, history.parameter_name)}</strong>{' '}
              {i18n.t('analytics:qc.noEligible')}
            </p>)}
            {(aqiHistory?.series || []).filter(series => !series.points.some(point => point.calculation_status === 'calculated')).map(series => <div key={analyticsSeriesKey({ kind: 'aqi', ...series })} role="status" className="mb-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <strong>{series.device_friendly_name || series.device_name} · {getAirQualityIndexProductLabel(series.product_code)}</strong>
              <p>{i18n.t('analytics:analytics.text.chartUnavailable')}</p>
              {[...new Set(series.points.map(point => point.exclusion_reason).filter((reason): reason is string => Boolean(reason)))].map(reason => <p key={reason}>{getExclusionReasonLabel(reason)}</p>)}
            </div>)}
            <SensorChart sensorId={primaryMeasurementHistory?.sensor_id || 0} parameter={primaryMeasurementHistory?.parameter || ''} unit={primaryMeasurementHistory?.unit || ''} hours={hours}
              invalidMeasurementsIncluded={includeInvalid}
              rangeStartedAt={urlStart} rangeEndedAt={urlEnd}
              data={primaryMeasurementHistory} overlays={measurementHistories.filter((item) => item._seriesKey !== primarySeriesKey)}
              aqiSeries={aqiHistory?.series || []} aqiStandards={aqiStandards} orderedSeriesKeys={selectedSeries.map(analyticsSeriesKey)}
              timeResolution={primaryMeasurementHistory?._displayAggregate || 'hour'} timezoneMode={timezoneMode} streamTimezone={streamTimezone} />
          </section>

          <section className="bg-white border border-slate-200 rounded-lg shadow-sm p-0">
            <div className="border-b border-slate-100 px-4 py-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold tracking-tight">{hasAqi ? i18n.t('analytics:analytics.headings.analysisResults') : i18n.t('analytics:analytics.headings.measurements')}</h2>
              <div className="flex flex-wrap items-center gap-3">
                {measurementSelections.length > 0 && <label className="flex flex-wrap items-center gap-2 text-sm">{i18n.t('analytics:qc.filterLabel')}
                  <select className="rounded border border-slate-300 px-2 py-1 text-sm bg-white" value={qcFilter} onChange={event => setQcFilter(event.target.value as MeasurementQcFilter)}>
                    {(['all', 'flagged', 'invalid', 'indeterminate'] as const).map(filter => <option key={filter} value={filter}>{i18n.t(`analytics:qc.filters.${filter}`)}</option>)}
                  </select>
                </label>}
                {dataStreamInfos.length > 1 && <div className="relative"><button type="button" className="rounded border border-slate-300 px-2 py-1 text-sm bg-white min-w-[180px] text-left" onClick={() => setShowSeriesFilterDropdown((open) => !open)}>{tableFilteredSeriesKeys === null
                  ? i18n.t('analytics:analytics.dynamic.allSeries', { count: dataStreamInfos.length })
                  : i18n.t('analytics:analytics.dynamic.selectedSeries', { count: tableFilteredSeriesKeys.length })}</button>
                  {showSeriesFilterDropdown && <div className="absolute top-full left-0 mt-1 bg-white border border-slate-200 rounded shadow-lg z-50 min-w-[260px] max-h-[300px] overflow-y-auto">
                    <label className="flex items-center gap-2 px-3 py-2 border-b border-slate-100"><input type="checkbox" checked={tableFilteredSeriesKeys === null} onChange={() => setTableFilteredSeriesKeys(null)} /><span className="text-sm font-medium"><Trans ns="analytics" i18nKey="analytics.text.allSeries" /></span></label>
                    {dataStreamInfos.map((stream) => <label key={stream.seriesKey} className="flex items-center gap-2 px-3 py-2 hover:bg-slate-50"><input type="checkbox" checked={tableFilteredSeriesKeys === null || tableFilteredSeriesKeys.includes(stream.seriesKey)} onChange={(event) => {
                      const current = tableFilteredSeriesKeys === null ? dataStreamInfos.map((item) => item.seriesKey) : tableFilteredSeriesKeys;
                      const next = event.target.checked ? [...new Set([...current, stream.seriesKey])] : current.filter((key) => key !== stream.seriesKey);
                      setTableFilteredSeriesKeys(next.length === dataStreamInfos.length ? null : next);
                    }} /><span className="w-3 h-3 rounded-full" style={{ backgroundColor: stream.chartColor }} /><span className="text-sm truncate">{stream.sensorName} · {stream.productDisplayName || stream.parameterDisplayName}{ambiguousMeasurementSeriesKeys.has(stream.seriesKey) ? i18n.t('analytics:analytics.dynamic.streamId', { id: stream.externalSensorId ?? stream.sensorId }) : ''}</span></label>)}
                    <div className="border-t border-slate-100 px-3 py-2"><button type="button" className="w-full text-sm text-blue-600" onClick={() => setShowSeriesFilterDropdown(false)}><Trans ns="analytics" i18nKey="analytics.actions.done" /></button></div>
                  </div>}
                </div>}
                {sortedRows.length > 0 && <><span className="text-sm text-slate-600"><Trans ns="analytics" i18nKey="analytics.text.showing" />{' '}{displayRange.start}–{displayRange.end} {' '}<Trans ns="analytics" i18nKey="analytics.text.of" />{' '}{displayRange.total}</span><select className="rounded border border-slate-300 px-2 py-1 text-sm bg-white" value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>{PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{i18n.t('analytics:analytics.dynamic.rowsPerPage', { count: size })}</option>)}</select>
                  <div className="flex items-center gap-1"><button type="button" className="px-2 py-1 rounded border border-slate-300 text-sm disabled:opacity-50" onClick={() => setCurrentPage((page) => Math.max(1, page - 1))} disabled={currentPage === 1}>←</button><span className="px-2 text-sm text-slate-600"><Trans ns="analytics" i18nKey="analytics.text.page" />{' '}{currentPage} {' '}<Trans ns="analytics" i18nKey="analytics.text.of2" />{' '}{totalPages}</span><button type="button" className="px-2 py-1 rounded border border-slate-300 text-sm disabled:opacity-50" onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))} disabled={currentPage === totalPages}>→</button></div>
                  <button type="button" onClick={downloadCsv} className="text-sm text-blue-600 hover:text-blue-800"><Trans ns="analytics" i18nKey="analytics.actions.downloadCsv" /></button></>}
              </div>
            </div>
            <div className="overflow-x-auto">
              {!allRows.length && <div className="text-slate-500 text-center py-8"><Trans ns="analytics" i18nKey="analytics.text.noResultsWindow" /></div>}
              {!!allRows.length && !sortedRows.length && <div className="text-slate-500 text-center py-8"><Trans ns="analytics" i18nKey="analytics.text.noResultsMatchCurrentFilter" />{' '}<button type="button" className="text-blue-600 underline" onClick={() => { setTableFilteredSeriesKeys(null); setQcFilter('all'); }}><Trans ns="analytics" i18nKey="analytics.actions.showAll" /></button></div>}
              {!!sortedRows.length && <table className="min-w-full text-sm border-separate border-spacing-0"><thead><tr>
                {dataStreamInfos.length > 1 && <>{renderSortHeader('sensorName', <><Trans ns="analytics" i18nKey="analytics.columns.site" />{' '}</>)}{renderSortHeader('source', <><Trans ns="analytics" i18nKey="analytics.columns.source" />{' '}</>)}{renderSortHeader('parameter', <><Trans ns="analytics" i18nKey="analytics.columns.parameterProduct" />{' '}</>)}</>}
                {ambiguousMeasurementSeriesKeys.size > 0 && <th className="text-left font-semibold px-3 py-2 bg-slate-50 border-b whitespace-nowrap"><Trans ns="analytics" i18nKey="analytics.columns.stream" /></th>}
                {renderSortHeader('timestamp', <><Trans ns="analytics" i18nKey="analytics.columns.time" />{getTimezoneLabel(timezoneMode, streamTimezone)}) </>)}
                {renderSortHeader('value', <><Trans ns="analytics" i18nKey="analytics.columns.value" />{' '}</>)}<th className="text-left font-semibold px-3 py-2 bg-slate-50 border-b whitespace-nowrap"><Trans ns="analytics" i18nKey="analytics.columns.unit" /></th>{renderSortHeader('status', <><Trans ns="common" i18nKey="fields.status" />{' '}</>)}<th className="text-left font-semibold px-3 py-2 bg-slate-50 border-b whitespace-nowrap"><Trans ns="analytics" i18nKey="analytics.columns.details" /></th>
              </tr></thead><tbody>{paginatedRows.map((row) => {
                const displayedConcentration = row.preprocessedConcentration;
                const formattedConcentration = displayedConcentration == null ? null : row.standardCode === EEA_EUROPEAN_STANDARD_CODE
                  ? formatEuropeanAqiConcentration(displayedConcentration)
                  : displayedConcentration;
                const hasAqiResult = row.value != null || row.categoryLabel != null || displayedConcentration != null;
                const status = row.seriesType === 'measurement'
                  ? measurementQcStatus(row.measurementPoint!)
                  : !hasAqiResult || row.coverageStatus === 'none'
                    ? i18n.t('common:states.unavailable')
                    : row.coverageStatus
                      ? getAirQualityIndexCoverageStatusLabel(row.coverageStatus)
                      : row.eligibilityStatus || i18n.t('common:states.available');
                const measurementTimestampRoleLabel = getMeasurementTimestampRoleLabel(
                  row.measurementTimestampSemantics,
                );
                const details = row.seriesType === 'measurement'
                  ? [
                      (row.measurementPoint?.qc_results || row.failedChecks).map((check) => checkName(check.check_code, { display_name: check.check_code, description: '' })).join(', '),
                      row.intervalStartedAt && row.intervalEndedAt
                        ? i18n.t('analytics:sensorChart.dynamic.interval', {
                            start: formatTimestamp(row.intervalStartedAt, timezoneMode, streamTimezone),
                            end: formatTimestamp(row.intervalEndedAt, timezoneMode, streamTimezone),
                          })
                        : '',
                      measurementTimestampRoleLabel
                        ? i18n.t('analytics:sensorChart.dynamic.timestampRole', {
                            role: measurementTimestampRoleLabel,
                          })
                        : '',
                    ].filter(Boolean).join(' · ')
                  : [
                      row.categoryLabel,
                      row.preprocessedConcentration != null
                        ? i18n.t('analytics:sensorChart.dynamic.processedConcentration', { concentration: formattedConcentration, unit: row.concentrationUnit || '' })
                        : '',
                      row.dominantPollutants.length ? i18n.t('analytics:sensorChart.dynamic.dominant', { pollutants: formatPollutantList(row.dominantPollutants) }) : '',
                      row.availablePollutants.length ? i18n.t('analytics:sensorChart.dynamic.available', { pollutants: formatPollutantList(row.availablePollutants) }) : '',
                      row.missingPollutants.length ? i18n.t('analytics:sensorChart.dynamic.missing', { pollutants: formatPollutantList(row.missingPollutants) }) : '',
                      row.ineligiblePollutants.length ? i18n.t('analytics:sensorChart.dynamic.ineligible', { pollutants: formatPollutantList(row.ineligiblePollutants) }) : '',
                      row.intervalStartedAt && row.intervalEndedAt
                        ? i18n.t('analytics:sensorChart.dynamic.interval', {
                            start: formatTimestamp(row.intervalStartedAt, timezoneMode, streamTimezone),
                            end: formatTimestamp(row.intervalEndedAt, timezoneMode, streamTimezone),
                          }) : '',
                      row.exclusionReason ? getExclusionReasonLabel(row.exclusionReason) : '',
                      row.representedLocalDate ? i18n.t('analytics:analytics.dynamic.localDate', { date: row.representedLocalDate }) : '',
                    ].filter(Boolean).join(' · ');
                return <tr key={row.rowKey} className="odd:bg-white even:bg-slate-50/50 align-top">
                  {dataStreamInfos.length > 1 && <><td className="px-3 py-2 whitespace-nowrap">{row.sensorName}</td><td className="px-3 py-2 whitespace-nowrap">{row.source || '—'}</td><td className="px-3 py-2 min-w-[12rem]">{row.parameterDisplayName}</td></>}
                  {ambiguousMeasurementSeriesKeys.size > 0 && <td className="px-3 py-2 whitespace-nowrap">{ambiguousMeasurementSeriesKeys.has(row.seriesKey) ? row.externalSensorId ?? '—' : '—'}</td>}
                  <td className="px-3 py-2 whitespace-nowrap">{formatTimestamp(row.timestamp, timezoneMode, streamTimezone)}</td><td className="px-3 py-2 font-medium">{row.seriesType === 'measurement' ? formatMeasurementValue(row.value, row.displayPrecision) : row.value ?? row.categoryLabel ?? formattedConcentration ?? '—'}</td><td className="px-3 py-2 whitespace-nowrap">{row.value != null || row.categoryLabel != null ? row.unit : displayedConcentration != null ? row.concentrationUnit || '—' : '—'}</td><td className="px-3 py-2 min-w-[10rem]">{status}</td><td className="px-3 py-2 min-w-[14rem] text-slate-600">{row.measurementPoint && row.sensorId ? <MeasurementQcDetails sensorId={row.sensorId} point={row.measurementPoint} label={formatTimestamp(row.timestamp, timezoneMode, streamTimezone)} unit={row.unit} displayPrecision={row.displayPrecision} context={details} /> : details || '—'}</td>
                </tr>;
              })}</tbody></table>}
            </div>
          </section>
        </>}
      </main>
    </div>
  );
}

export default AnalyticsWorkspace;
