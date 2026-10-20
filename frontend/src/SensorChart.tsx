import { formatMeasurementValue } from './measurementFormatting';
import { checkName } from './qc/presentation';
import { isolatedMeasurementMarkerIndices } from './isolatedMeasurementMarkers';
import { isFlagged, isIndeterminate, measurementQcStatus } from './measurementQc';
import { Trans } from 'react-i18next';
import i18n from './i18n';
import * as React from 'react';
import {
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  TimeScale,
  Tooltip,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import 'chartjs-adapter-date-fns';
import zoomPlugin from 'chartjs-plugin-zoom';
import {
  MAX_ANALYTICS_SCALE_GROUPS,
  analyticsScaleGroupKey,
  normalizeDisplayUnit,
} from './analyticsSeries';
import type {
  AirQualityIndexAnalyticsPoint,
  AirQualityIndexAnalyticsSeries,
  AirQualityIndexStandardMetadata,
} from './airQualityIndex';
import {
  EEA_EUROPEAN_STANDARD_CODE,
  formatEuropeanAqiConcentration,
  formatPollutantList,
  getAirQualityIndexCategoryLabel,
  getAirQualityIndexCoverageStatusLabel,
  getAirQualityIndexProductLabel,
  getAirQualityIndexStandardLabel,
  getExclusionReasonLabel,
} from './airQualityIndexPresentation';
import { getAggregationDisplayLabel } from './aqi';
import { type TimezoneMode, formatChartTick, formatTimestamp, getTimezoneLabel } from './utils/timezone';
import type { MeasurementHistoryDataPoint, MeasurementHistoryResponse } from './measurementHistory';
import { getParameterDisplayName } from './parameterPresentation';

export type { MeasurementHistoryDataPoint, MeasurementHistoryResponse } from './measurementHistory';


ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler,
  TimeScale,
  zoomPlugin,
);


interface SensorChartProps {
  invalidMeasurementsIncluded?: boolean;
  sensorId?: number | null;
  parameter?: string | null;
  unit?: string | null;
  hours?: number;
  rangeStartedAt?: string | null;
  rangeEndedAt?: string | null;
  data?: MeasurementHistoryResponse | null;
  overlays?: MeasurementHistoryResponse[];
  aqiSeries?: AirQualityIndexAnalyticsSeries[];
  aqiStandards?: AirQualityIndexStandardMetadata[];
  orderedSeriesKeys?: string[];
  timeResolution?: string | null;
  timezoneMode?: TimezoneMode;
  streamTimezone?: string | null;
}


type MeasurementChartPoint = {
  x: number;
  y: number | null;
  measurementPoint: MeasurementHistoryDataPoint;
};


type AirQualityIndexChartPoint = {
  x: number;
  y: number | null;
  aqiPoint: AirQualityIndexAnalyticsPoint;
};


const SERIES_COLORS = ['#0074D9', '#DC2626', '#059669', '#D97706', '#7C3AED', '#0891B2'];


function compactSiteName(siteName: string): string {
  return siteName.length > 24 ? `${siteName.slice(0, 22)}…` : siteName;
}


function wrapChartLabel(text: string): string[] {
  // Bound long translated labels to the narrowest chart without shrinking text.
  return text.match(/.{1,34}(?:\s|$)|\S{1,34}/g)?.map(line => line.trim()) || [text];
}


const AGGREGATION_DURATION_MILLISECONDS: Record<string, number> = {
  '1m': 60_000,
  '2m': 2 * 60_000,
  '5m': 5 * 60_000,
  '1h': 60 * 60_000,
  '8h': 8 * 60 * 60_000,
  '24h': 24 * 60 * 60_000,
};


function measurementGapThresholdMilliseconds(
  history: MeasurementHistoryResponse,
  points: MeasurementChartPoint[],
  aggregationCode: string,
): number | false {
  const configuredDuration = AGGREGATION_DURATION_MILLISECONDS[
    history.result_aggregation_code || aggregationCode
  ] || AGGREGATION_DURATION_MILLISECONDS[history.native_aggregation_code || ''];
  if (configuredDuration) return configuredDuration * 1.5;

  const positiveGaps = points.slice(1).flatMap((point, index) => {
    const gap = point.x - points[index].x;
    return gap > 0 ? [gap] : [];
  }).sort((left, right) => left - right);
  if (!positiveGaps.length) return false;
  const medianGap = positiveGaps[Math.floor(positiveGaps.length / 2)];
  return medianGap * 1.5;
}


function measurementIdentityKey(
  history: MeasurementHistoryResponse,
  aggregationCode: string,
): string {
  return [history.device_name || '', history.parameter, aggregationCode].join('|');
}


function categoryRank(
  point: AirQualityIndexAnalyticsPoint,
  standard: AirQualityIndexStandardMetadata | undefined,
): number | null {
  if (!point.category_code) return null;
  return standard?.categories.find(
    (category) => category.code === point.category_code,
  )?.internal_severity_rank ?? null;
}


const SensorChart: React.FC<SensorChartProps> = ({
  sensorId,
  invalidMeasurementsIncluded,
  unit,
  hours = 24,
  rangeStartedAt,
  rangeEndedAt,
  data,
  overlays = [],
  aqiSeries = [],
  aqiStandards = [],
  orderedSeriesKeys = [],
  timeResolution,
  timezoneMode = 'local',
  streamTimezone,
}) => {
  const [showInvalid, setShowInvalid] = React.useState(true);
  const chartRef = React.useRef<any>(null);
  const measurementHistories = React.useMemo(
    () => [data, ...overlays].filter((history): history is MeasurementHistoryResponse => history != null),
    [data, overlays],
  );
  const seriesOrder = React.useMemo(
    () => new Map(orderedSeriesKeys.map((seriesKey, index) => [seriesKey, index])),
    [orderedSeriesKeys],
  );
  const primarySeriesKey = orderedSeriesKeys[0] || measurementHistories[0]?._seriesKey || '';
  const requestedRangeHours = rangeStartedAt && rangeEndedAt
    ? (Date.parse(rangeEndedAt) - Date.parse(rangeStartedAt)) / 3_600_000
    : hours;
  const displayedRangeHours = Number.isFinite(requestedRangeHours) && requestedRangeHours > 0
    ? requestedRangeHours
    : hours;

  if (measurementHistories.length === 0 && aqiSeries.length === 0) {
    return <div className="chart-empty"><Trans ns="analytics" i18nKey="sensorChart.text.noDataAvailableSelectedWindow" /></div>;
  }

  const measurementScaleGroups = new Map<string, {
    axisId: string;
    unit: string;
    parameterLabels: Set<string>;
  }>();
  measurementHistories.forEach((history) => {
    const scaleKey = analyticsScaleGroupKey({ kind: 'measurement', normalized_unit: history.unit });
    const existing = measurementScaleGroups.get(scaleKey);
    if (existing) {
      existing.parameterLabels.add(getParameterDisplayName(history.parameter, history.parameter_name));
      return;
    }
    measurementScaleGroups.set(scaleKey, {
      axisId: `measurementScale${measurementScaleGroups.size + 1}`,
      unit: history.unit || unit || i18n.t('analytics:sensorChart.states.unitUnavailable'),
      parameterLabels: new Set([getParameterDisplayName(history.parameter, history.parameter_name)]),
    });
  });
  const measurementIdentityCounts = new Map<string, number>();
  measurementHistories.forEach((history) => {
    const aggregationCode = history._displayAggregate || timeResolution || 'hour';
    const identityKey = measurementIdentityKey(history, aggregationCode);
    measurementIdentityCounts.set(identityKey, (measurementIdentityCounts.get(identityKey) || 0) + 1);
  });
  const numericAqiPresent = aqiSeries.some((series) => series.result_kind === 'numeric');
  const numericStandardCodes = [...new Set(
    aqiSeries
      .filter((series) => series.result_kind === 'numeric')
      .map((series) => series.standard_code),
  )];
  const numericAqiAxisTitle = numericStandardCodes.length === 1
    ? getAirQualityIndexStandardLabel(numericStandardCodes[0])
    : i18n.t('analytics:sensorChart.axes.aqi');
  const categoricalStandardCodes = [...new Set(
    aqiSeries.filter((series) => series.result_kind === 'categorical').map((series) => series.standard_code),
  )];
  const scaleGroupCount = measurementScaleGroups.size + (numericAqiPresent ? 1 : 0) + categoricalStandardCodes.length;
  if (scaleGroupCount > MAX_ANALYTICS_SCALE_GROUPS) {
    return (
      <div className="chart-error">
        <Trans ns="analytics" i18nKey="sensorChart.text.selectionRequires" />{scaleGroupCount} {' '}<Trans ns="analytics" i18nKey="sensorChart.text.incompatibleYAxisGroupsRemoveSeries" />{' '}{MAX_ANALYTICS_SCALE_GROUPS}<Trans ns="analytics" i18nKey="sensorChart.text.axisReadabilityLimit" /></div>
    );
  }

  const invalidAvailable = measurementHistories.length > 0 && (invalidMeasurementsIncluded
    ?? measurementHistories.some(history => history.data.some(point => point.is_valid === false)));
  const displayInvalid = invalidAvailable && showInvalid;
  let hasQcMarkers = false;
  let markersReduced = false;
  const datasets: any[] = [];
  measurementHistories.forEach((history, measurementIndex) => {
    const seriesKey = history._seriesKey || `measurement|${history.sensor_id}|${history.parameter}|${history._displayAggregate || timeResolution || 'hour'}`;
    const orderIndex = seriesOrder.get(seriesKey) ?? measurementIndex;
    const aggregationCode = history._displayAggregate || timeResolution || 'hour';
    const scaleKey = analyticsScaleGroupKey({ kind: 'measurement', normalized_unit: history.unit });
    const scale = measurementScaleGroups.get(scaleKey)!;
    const points: MeasurementChartPoint[] = history.data
      .filter((point) => point.timestamp && Number.isFinite(point.value))
      // With parsing disabled, Chart.js requires epoch milliseconds; Date
      // objects are ignored by automatic bounds and hide historical points.
      .map((point) => ({ x: Date.parse(point.timestamp), y: point.is_valid === false && !displayInvalid ? null : point.value, measurementPoint: point }))
      .sort((first, second) => first.x - second.x);
    // Bound marker density by horizontal time bins and status, preserving every
    // observation for tooltips/table inspection. At most 300 markers per status.
    const markerIndices = new Set<number>();
    const markerBins = new Set<string>();
    const invalidPrefix = [0];
    const gapThreshold = measurementGapThresholdMilliseconds(history, points, aggregationCode);
    const gapPrefix: number[] = [];
    const extent = Math.max(1, (points.at(-1)?.x || 0) - (points[0]?.x || 0));
    points.forEach((point, index) => {
      invalidPrefix.push(invalidPrefix[index] + (point.measurementPoint.is_valid === false ? 1 : 0));
      gapPrefix.push((gapPrefix[index - 1] || 0) + (index > 0 && gapThreshold !== false
        && point.x - points[index - 1].x > gapThreshold ? 1 : 0));
      const kind = point.measurementPoint.is_valid === false ? 'invalid' : isFlagged(point.measurementPoint) ? 'flagged' : null;
      if (!kind || point.y == null) return;
      hasQcMarkers = true;
      const bin = kind + Math.min(299, Math.floor((point.x - points[0].x) / extent * 300));
      if (!markerBins.has(bin)) { markerBins.add(bin); markerIndices.add(index); }
      else markersReduced = true;
    });
    const excludedSegment = (context: { p0DataIndex: number; p1DataIndex: number }) =>
      invalidPrefix[context.p1DataIndex + 1] > invalidPrefix[context.p0DataIndex]
      || gapPrefix[context.p1DataIndex] > gapPrefix[context.p0DataIndex];
    const isolatedMarkerIndices = isolatedMeasurementMarkerIndices(points, excludedSegment);
    const streamIdentifier = history.external_sensor_id ?? history.sensor_id;
    const streamSuffix = (measurementIdentityCounts.get(measurementIdentityKey(history, aggregationCode)) || 0) > 1
      ? i18n.t('analytics:sensorChart.dynamic.streamIdentifierSuffix', { id: streamIdentifier })
      : '';
    const isPrimary = seriesKey === primarySeriesKey;
    datasets.push({
      label: i18n.t('analytics:sensorChart.dynamic.seriesLabel', {
        site: compactSiteName(history.device_name || i18n.t('analytics:analytics.dynamic.sensor', { id: history.sensor_id })),
        descriptor: getParameterDisplayName(history.parameter, history.parameter_name),
        product: getAggregationDisplayLabel(aggregationCode),
        stream: streamSuffix,
        daily: '',
        primary: isPrimary ? ' ★' : '',
      }),
      data: points,
      yAxisID: scale.axisId,
      borderColor: SERIES_COLORS[orderIndex % SERIES_COLORS.length],
      backgroundColor: isPrimary ? `${SERIES_COLORS[orderIndex % SERIES_COLORS.length]}14` : 'transparent',
      borderWidth: isPrimary ? 2.25 : 1.6,
      borderDash: [],
      pointStyle: points.map(point => point.measurementPoint.is_valid === false ? 'crossRot' : isFlagged(point.measurementPoint) ? 'triangle' : 'circle'),
      pointRadius: points.map((point, index) => point.y == null ? 0 : markerIndices.has(index) ? 4 : points.length <= 2 || isolatedMarkerIndices.has(index) ? 2.5 : 0),
      pointBorderWidth: 1.8,
      pointBorderColor: points.map(point => point.measurementPoint.is_valid === false ? '#B91C1C' : isFlagged(point.measurementPoint) ? '#92400E' : SERIES_COLORS[orderIndex % SERIES_COLORS.length]),
      pointBackgroundColor: '#FFFFFF',
      segment: {
        // Do not draw a valid trend through an excluded or invalid observation,
        // even if Chart.js spans a null within the ordinary temporal gap limit.
        borderColor: (context: { p0DataIndex: number; p1DataIndex: number }) =>
          excludedSegment(context) ? 'transparent' : undefined,
        backgroundColor: (context: { p0DataIndex: number; p1DataIndex: number }) =>
          excludedSegment(context) ? 'transparent' : undefined,
      },
      pointHoverRadius: 5,
      fill: isPrimary,
      tension: 0.2,
      spanGaps: gapThreshold,
      parsing: false,
      analyticsMeta: {
        kind: 'measurement',
        seriesKey,
        siteName: history.device_name || i18n.t('analytics:analytics.dynamic.sensor', { id: history.sensor_id }),
        source: history.external_api?.name,
        parameterCode: history.parameter,
        parameterLabel: getParameterDisplayName(history.parameter, history.parameter_name),
        aggregationCode,
        displayPrecision: history.display_precision,
        unit: history.unit,
        streamSuffix,
        timestampSemantics: history.measurement_timestamp_semantics,
      },
    });
  });

  aqiSeries.forEach((series, aqiIndex) => {
    const standard = aqiStandards.find((candidate) => candidate.standard_code === series.standard_code);
    const seriesKey = `aqi|${series.standard_code}|${series.product_code}|${series.device_id}`;
    const orderIndex = seriesOrder.get(seriesKey) ?? measurementHistories.length + aqiIndex;
    const isCategorical = series.result_kind === 'categorical';
    const points: AirQualityIndexChartPoint[] = series.points.map((point) => ({
      x: Date.parse(point.observed_at),
      y: point.calculation_status === 'calculated'
        ? (isCategorical ? categoryRank(point, standard) : point.numeric_value)
        : null,
      aqiPoint: point,
    }));
    const categoryColors = points.map((point) => standard?.categories.find(
      (category) => category.code === point.aqiPoint.category_code,
    )?.color || SERIES_COLORS[orderIndex % SERIES_COLORS.length]);
    const isPrimary = seriesKey === primarySeriesKey;
    datasets.push({
      label: i18n.t('analytics:sensorChart.dynamic.seriesLabel', {
        site: compactSiteName(series.device_friendly_name || series.device_name),
        descriptor: getAirQualityIndexStandardLabel(series.standard_code),
        stream: '',
        product: getAirQualityIndexProductLabel(series.product_code),
        daily: series.history_interval === 'represented_device_local_date'
          ? i18n.t('analytics:sensorChart.dynamic.dailySuffix')
          : '',
        primary: isPrimary ? ' ★' : '',
      }),
      data: points,
      yAxisID: isCategorical ? `categorical_${series.standard_code}` : 'numericAqi',
      borderColor: SERIES_COLORS[orderIndex % SERIES_COLORS.length],
      backgroundColor: 'transparent',
      borderWidth: isPrimary ? 2.25 : 1.8,
      borderDash: isCategorical ? [3, 3] : [7, 3],
      pointStyle: isCategorical ? 'rectRot' : 'triangle',
      pointBackgroundColor: isCategorical ? categoryColors : SERIES_COLORS[orderIndex % SERIES_COLORS.length],
      pointBorderColor: points.map((point, pointIndex) => (
        point.aqiPoint.coverage_status === 'partial' ? '#111827' : (isCategorical ? categoryColors[pointIndex] : SERIES_COLORS[orderIndex % SERIES_COLORS.length])
      )),
      pointBorderWidth: points.map((point) => point.aqiPoint.coverage_status === 'partial' ? 2 : 1),
      pointRadius: points.length > 180 ? 0 : 2.5,
      pointHoverRadius: 5,
      stepped: isCategorical,
      tension: 0,
      spanGaps: false,
      parsing: false,
      analyticsMeta: {
        kind: 'aqi',
        seriesKey,
        series,
      },
    });
  });
  datasets.sort((first, second) => (
    (seriesOrder.get(first.analyticsMeta.seriesKey) ?? Number.MAX_SAFE_INTEGER)
    - (seriesOrder.get(second.analyticsMeta.seriesKey) ?? Number.MAX_SAFE_INTEGER)
  ));

  const scales: Record<string, any> = {
    x: {
      type: 'time',
      min: rangeStartedAt ? Date.parse(rangeStartedAt) : undefined,
      max: rangeEndedAt ? Date.parse(rangeEndedAt) : undefined,
      time: { unit: displayedRangeHours > 48 ? 'day' : 'hour', displayFormats: { hour: 'HH:mm', day: 'MMM d' } },
      grid: { display: false },
      ticks: { callback: (value: number) => formatChartTick(value, timezoneMode, streamTimezone), font: { size: 11 }, color: '#666', maxRotation: 0, autoSkip: true },
      title: {
        display: true,
        text: wrapChartLabel(i18n.t('analytics:sensorChart.dynamic.timeAxis', {
          timezone: getTimezoneLabel(timezoneMode, streamTimezone),
        })),
        font: { size: 12, weight: 500 },
        color: '#374151',
      },
    },
  };
  let axisIndex = 0;
  measurementScaleGroups.forEach((scale) => {
    const parameterLabels = [...scale.parameterLabels];
    scales[scale.axisId] = {
      type: 'linear',
      position: axisIndex % 2 === 0 ? 'left' : 'right',
      offset: axisIndex >= 2,
      grid: { color: 'rgba(0,0,0,0.05)', drawOnChartArea: axisIndex === 0 },
      ticks: { font: { size: 11 }, color: '#475569' },
      title: {
        display: true,
        text: i18n.t('analytics:sensorChart.dynamic.measurementAxis', {
          parameter: parameterLabels.length === 1
            ? parameterLabels[0]
            : i18n.t('analytics:sensorChart.axes.concentration'),
          unit: scale.unit,
        }),
        color: '#374151',
        font: { size: 12, weight: 500 },
      },
    };
    axisIndex += 1;
  });
  if (numericAqiPresent) {
    scales.numericAqi = {
      type: 'linear',
      position: axisIndex % 2 === 0 ? 'left' : 'right',
      offset: axisIndex >= 2,
      beginAtZero: true,
      suggestedMax: 500,
      grid: { drawOnChartArea: axisIndex === 0 },
      ticks: { stepSize: 50, color: '#475569', font: { size: 11 } },
      title: {
        display: true,
        text: numericAqiAxisTitle,
        color: '#374151',
        font: { size: 12, weight: 500 },
      },
    };
    axisIndex += 1;
  }
  categoricalStandardCodes.forEach((standardCode) => {
    const standard = aqiStandards.find((candidate) => candidate.standard_code === standardCode);
    const categories = [...(standard?.categories || [])].sort(
      (first, second) => first.internal_severity_rank - second.internal_severity_rank,
    );
    scales[`categorical_${standardCode}`] = {
      type: 'linear',
      position: axisIndex % 2 === 0 ? 'left' : 'right',
      offset: axisIndex >= 2,
      min: categories[0]?.internal_severity_rank ?? 1,
      max: categories.at(-1)?.internal_severity_rank ?? 6,
      grid: { drawOnChartArea: axisIndex === 0 },
      ticks: {
        stepSize: 1,
        color: '#475569',
        font: { size: 11 },
        callback: (value: number | string) => categories.find(
          (category) => category.internal_severity_rank === Number(value),
        )?.code
          ? getAirQualityIndexCategoryLabel(categories.find(
              (category) => category.internal_severity_rank === Number(value),
            )!.code)
          : '',
      },
      title: { display: true, text: i18n.t('analytics:sensorChart.dynamic.standardCategory', {
        standard: getAirQualityIndexStandardLabel(standardCode),
      }), color: '#374151', font: { size: 12, weight: 500 } },
    };
    axisIndex += 1;
  });

  const pointCount = datasets.reduce((count, dataset) => count + dataset.data.length, 0);
  const options: any = {
    responsive: true,
    maintainAspectRatio: false,
    animation: pointCount > 500 ? false : undefined,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    plugins: {
      legend: {
        display: true,
        position: 'top',
        labels: {
          usePointStyle: true,
          padding: 16,
          font: { size: 11 },
          generateLabels: (chart: any) => ChartJS.defaults.plugins.legend.labels.generateLabels(chart).map((label: any) => ({
            ...label,
            text: label.text?.length > 52 ? `${label.text.slice(0, 50)}…` : label.text,
          })),
        },
      },
      tooltip: {
        mode: 'nearest',
        axis: 'xy',
        intersect: false,
        // Inspect one nearest point even when multiple streams share a timestamp.
        // Chart.js chooses alignment and flips at canvas edges.
        filter: (_item: unknown, index: number) => index === 0,
        backgroundColor: 'rgba(15,23,42,0.94)',
        padding: 8,
        bodySpacing: 3,
        callbacks: {
          title: (items: any[]) => {
            if (!items?.length) return '';
            const raw = items[0].raw as MeasurementChartPoint | AirQualityIndexChartPoint;
            if ('aqiPoint' in raw && raw.aqiPoint.represented_local_date) {
              return i18n.t('analytics:sensorChart.dynamic.representedLocalDate', {
                date: raw.aqiPoint.represented_local_date,
              });
            }
            return formatTimestamp(new Date(items[0].parsed.x).toISOString(), timezoneMode, streamTimezone);
          },
          label: (context: any) => {
            const meta = context.dataset.analyticsMeta;
            if (meta.kind === 'measurement') {
              const raw = context.raw as MeasurementChartPoint;
              const status = raw.measurementPoint.is_valid === false
                ? i18n.t('analytics:sensorChart.states.invalidSuffix')
                : '';
              return [
                ...(measurementHistories.length + aqiSeries.length > 1
                  ? [`${compactSiteName(meta.siteName)}${meta.streamSuffix}`] : []),
                `${meta.parameterLabel} · ${getAggregationDisplayLabel(meta.aggregationCode)}: ${formatMeasurementValue(raw.measurementPoint.value, meta.displayPrecision)} ${meta.unit}${status}`,
              ].flatMap(wrapChartLabel);
            }
            const raw = context.raw as AirQualityIndexChartPoint;
            const point = raw.aqiPoint;
            if (point.calculation_status !== 'calculated') {
              return [
                compactSiteName(meta.series.device_friendly_name || meta.series.device_name),
                i18n.t('analytics:sensorChart.dynamic.unavailableReason', {
                  reason: getExclusionReasonLabel(point.exclusion_reason),
                }),
              ];
            }
            return [
              compactSiteName(meta.series.device_friendly_name || meta.series.device_name),
              point.numeric_value != null
                ? point.category_code
                  ? i18n.t('analytics:sensorChart.dynamic.aqiCategory', {
                      value: point.numeric_value,
                      category: getAirQualityIndexCategoryLabel(point.category_code),
                    })
                  : i18n.t('analytics:sensorChart.dynamic.aqi', { value: point.numeric_value })
                : point.category_code
                  ? getAirQualityIndexCategoryLabel(point.category_code)
                  : i18n.t('analytics:sensorChart.states.categoryUnavailable'),
            ];
          },
          afterLabel: (context: any) => {
            const meta = context.dataset.analyticsMeta;
            if (meta.kind === 'measurement') {
              const point = (context.raw as MeasurementChartPoint).measurementPoint;
              if (point.is_valid !== false && !isFlagged(point) && !isIndeterminate(point)) return [];
              const names = [...new Set((point.qc_results || []).map(result => checkName(result.check_code)))];
              return [measurementQcStatus(point), ...names.slice(0, 2)].flatMap(wrapChartLabel);
            }
            const point = (context.raw as AirQualityIndexChartPoint).aqiPoint;
            const details = [
              i18n.t('analytics:sensorChart.dynamic.coverage', {
                status: getAirQualityIndexCoverageStatusLabel(point.coverage_status),
              }),
            ];
            if (point.dominant_pollutants.length) details.push(i18n.t('analytics:sensorChart.dynamic.dominant', { pollutants: formatPollutantList(point.dominant_pollutants) }));
            if (point.preprocessed_concentration != null && point.normalized_unit) {
              const concentration = meta.series.standard_code === EEA_EUROPEAN_STANDARD_CODE
                ? formatEuropeanAqiConcentration(point.preprocessed_concentration)
                : point.preprocessed_concentration;
              details.push(i18n.t('analytics:sensorChart.dynamic.processedConcentration', {
                concentration,
                unit: point.normalized_unit,
              }));
            }
            return details;
          },
        },
      },
      zoom: {
        pan: { enabled: true, mode: 'x', modifierKey: 'shift' },
        zoom: {
          wheel: { enabled: true, modifierKey: 'ctrl' },
          pinch: { enabled: true },
          drag: { enabled: true, backgroundColor: 'rgba(6,71,137,0.1)', borderColor: 'rgba(6,71,137,0.5)', borderWidth: 1 },
          mode: 'x',
        },
        limits: { x: { min: 'original', max: 'original' } },
      },
    },
    scales,
  };

  return (
    <div className="sensor-chart">
      <div className="chart-header">
        <div className="chart-title">{displayedRangeHours <= 24
          ? i18n.t('analytics:sensorChart.counts.lastHours', { count: Math.round(displayedRangeHours) })
          : i18n.t('analytics:sensorChart.counts.lastDays', { count: Math.round(displayedRangeHours / 24) })}</div>
        <div className="chart-actions">
          <button type="button" className="chart-action-btn" onClick={() => chartRef.current?.resetZoom()} title={i18n.t('analytics:sensorChart.tooltips.resetZoom')}><Trans ns="analytics" i18nKey="sensorChart.actions.resetZoom" /></button>
        </div>
      </div>
      {invalidAvailable && (
        <div className="chart-controls mb-8">
          <label className="inline-flex align-center gap-6">
            <input type="checkbox" checked={showInvalid} onChange={(event) => setShowInvalid(event.target.checked)} />
            <Trans ns="analytics" i18nKey="sensorChart.fields.showInvalidPoints" /></label>
          <p className="text-sm text-slate-500 mt-1"><Trans ns="analytics" i18nKey="qc.chartHelp" /></p>
        </div>
      )}
      {hasQcMarkers && <p className="text-sm text-slate-600 mb-2"><Trans ns="analytics" i18nKey="qc.markerLegend" /></p>}
      {markersReduced && <p className="text-sm text-slate-500 mb-2"><Trans ns="analytics" i18nKey="qc.denseMarkers" /></p>}
      <div className={`chart-wrapper${aqiSeries.length > 0 ? ' chart-wrapper--aqi' : ''}${scaleGroupCount >= 3 ? ' chart-wrapper--multi-axis' : ''}`}>
        <div className="chart-canvas-container">
          <Line ref={chartRef} key={`analytics-${sensorId || 'mixed'}-${datasets.length}-${scaleGroupCount}-${normalizeDisplayUnit(unit)}`} data={{ datasets }} options={options} redraw />
        </div>
      </div>
    </div>
  );
};


export default SensorChart;
