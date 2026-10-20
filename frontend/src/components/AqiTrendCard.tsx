import { Trans } from 'react-i18next';
import i18n from '../i18n';
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
  type ChartOptions,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import 'chartjs-adapter-date-fns';
import zoomPlugin from 'chartjs-plugin-zoom';
import {
  getAirQualityIndexHistory,
  getUsEpaCompletedDayHistory,
  type AirQualityIndexProductMetadata,
  type AirQualityIndexStandardMetadata,
  type DeviceAirQualityIndexResult,
  type UsEpaCompletedDayHistoryResult,
} from '../airQualityIndex';
import { createCompletedDayPresetRange } from '../completedDayAqiHistory';
import {
  getEuropeanAqiDisplayedResult,
  getAirQualityIndexCategoryLabel,
  getAirQualityIndexProductLabel,
  getExclusionReasonLabel,
} from '../airQualityIndexPresentation';
import {
  AQI_COMPLETED_DAY_HISTORY_DAYS,
  AQI_CURRENT_CONDITION_HISTORY_HOURS,
  createCurrentConditionHistoryRange,
} from '../aqiTrend';


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


interface AqiTrendCardProps {
  standardMetadata: AirQualityIndexStandardMetadata;
  product: AirQualityIndexProductMetadata;
  deviceId: number | null;
  deviceName: string;
  sourceName: string | null;
  latestObservedAt: string | null;
  latestRepresentedLocalDate?: string | null;
}

interface TrendPoint {
  timestamp: string;
  numericValue: number | null;
  categoryCode: string | null;
  categoryLabel: string | null;
  exclusionReason: string | null;
}

interface TrendState {
  loading: boolean;
  error: boolean;
  points: TrendPoint[];
}

function completedDayPoint(result: UsEpaCompletedDayHistoryResult): TrendPoint {
  return {
    timestamp: result.represented_local_date,
    numericValue: result.calculation_status === 'calculated' ? result.numeric_value : null,
    categoryCode: result.category_code,
    categoryLabel: result.category_label,
    exclusionReason: result.blocking_reasons[0] ?? null,
  };
}


function hourlyPoint(
  result: DeviceAirQualityIndexResult,
  standardMetadata: AirQualityIndexStandardMetadata,
  product: AirQualityIndexProductMetadata,
): TrendPoint {
  if (standardMetadata.standard_code === 'eea_european') {
    const displayedResult = getEuropeanAqiDisplayedResult(result, product);
    const category = standardMetadata.categories.find(
      (candidate) => candidate.code === displayedResult.categoryCode,
    );
    return {
      timestamp: result.observed_at,
      // European AQI is categorical. The metadata rank positions categories
      // on the chart without inventing a numeric European AQI value.
      numericValue: category?.internal_severity_rank ?? null,
      categoryCode: displayedResult.categoryCode,
      categoryLabel: displayedResult.categoryLabel,
      exclusionReason: displayedResult.exclusionReason,
    };
  }
  return {
    // History endpoints use observed_at for the evaluation boundary. A
    // selected ozone or SO2 candidate interval may end earlier in that window.
    timestamp: result.observed_at,
    numericValue: result.numeric_value,
    categoryCode: result.category_code,
    categoryLabel: result.category_label,
    exclusionReason: result.exclusion_reason ?? null,
  };
}


export default function AqiTrendCard({
  standardMetadata,
  product,
  deviceId,
  deviceName,
  sourceName,
  latestObservedAt,
  latestRepresentedLocalDate = null,
}: AqiTrendCardProps) {
  const chartRef = React.useRef<any>(null);
  const [retryToken, setRetryToken] = React.useState(0);
  const [state, setState] = React.useState<TrendState>({
    loading: false,
    error: false,
    points: [],
  });
  const isCompletedDay = product.product_kind === 'completed_day';

  React.useEffect(() => {
    if (deviceId == null || !latestObservedAt) {
      setState({ loading: false, error: false, points: [] });
      return;
    }
    const controller = new AbortController();
    setState({ loading: true, error: false, points: [] });

    const request = async (): Promise<TrendPoint[]> => {
      if (isCompletedDay) {
        if (!latestRepresentedLocalDate) return [];
        const range = createCompletedDayPresetRange(
          latestRepresentedLocalDate,
          AQI_COMPLETED_DAY_HISTORY_DAYS,
        );
        if (!range) return [];
        if (standardMetadata.standard_code !== 'us_epa') {
          const rangeStart = new Date(`${range.startLocalDate}T00:00:00+08:00`);
          const rangeEnd = new Date(`${range.endLocalDate}T00:00:00+08:00`);
          rangeEnd.setUTCDate(rangeEnd.getUTCDate() + 2);
          const response = await getAirQualityIndexHistory({
            standard_code: standardMetadata.standard_code,
            product_code: product.product_code,
            start: rangeStart.toISOString(),
            end: rangeEnd.toISOString(),
            device_id: deviceId,
            external_api_name: sourceName,
          }, controller.signal);
          return response.results
            .filter((result) => result.device_id === deviceId)
            .map((result) => ({
              ...hourlyPoint(result, standardMetadata, product),
              timestamp: result.represented_local_date ?? result.observed_at.slice(0, 10),
            }));
        }
        const response = await getUsEpaCompletedDayHistory({
          product_code: product.product_code,
          start_local_date: range.startLocalDate,
          end_local_date: range.endLocalDate,
          device_id: deviceId,
          external_api_name: sourceName,
        }, controller.signal);
        const deviceSeries = response.device_series.find(
          (series) => series.device_id === deviceId,
        );
        return deviceSeries?.results.map(completedDayPoint) ?? [];
      }

      const range = createCurrentConditionHistoryRange(latestObservedAt);
      if (!range) return [];
      const response = await getAirQualityIndexHistory({
        standard_code: standardMetadata.standard_code,
        product_code: product.product_code,
        start: range.start,
        end: range.end,
        device_id: deviceId,
        external_api_name: sourceName,
      }, controller.signal);
      const returnedPoints = response.results
        .filter((result) => result.device_id === deviceId)
        .map((result) => hourlyPoint(result, standardMetadata, product));
      const returnedPointByTimestamp = new Map(returnedPoints.map((point) => [
        new Date(point.timestamp).getTime(),
        point,
      ]));
      const rangeStart = new Date(range.start).getTime();
      return Array.from({ length: AQI_CURRENT_CONDITION_HISTORY_HOURS }, (_value, index) => {
        const timestamp = rangeStart + index * 60 * 60 * 1000;
        return returnedPointByTimestamp.get(timestamp) ?? {
          timestamp: new Date(timestamp).toISOString(),
          numericValue: null,
          categoryCode: null,
          categoryLabel: null,
          exclusionReason: 'missing_measurements',
        };
      });
    };

    request().then((points) => {
      if (!controller.signal.aborted) {
        setState({ loading: false, error: false, points });
      }
    }).catch((error: unknown) => {
      if (
        !controller.signal.aborted
        && !(error instanceof Error && error.name === 'AbortError')
      ) {
        setState({ loading: false, error: true, points: [] });
      }
    });
    return () => controller.abort();
  }, [
    deviceId,
    isCompletedDay,
    latestObservedAt,
    latestRepresentedLocalDate,
    product,
    retryToken,
    sourceName,
    standardMetadata,
  ]);

  const categoryByCode = React.useMemo(() => new Map(
    standardMetadata.categories.map((category) => [category.code, category]),
  ), [standardMetadata.categories]);
  const availablePointCount = state.points.filter(
    (point) => point.numericValue != null,
  ).length;
  const unavailablePointCount = state.points.length - availablePointCount;
  const chartPoints = state.points.map((point) => ({
    x: isCompletedDay
      ? new Date(`${point.timestamp}T00:00:00Z`).getTime()
      : new Date(point.timestamp).getTime(),
    y: point.numericValue,
    categoryLabel: point.categoryLabel,
    exclusionReason: point.exclusionReason,
  }));
  const pointColors = state.points.map((point) => (
    point.categoryCode ? categoryByCode.get(point.categoryCode)?.color ?? '#64748B' : '#64748B'
  ));

  const chartData = {
    datasets: [{
      label: `${deviceName} – ${getAirQualityIndexProductLabel(product.product_code)}`,
      data: chartPoints,
      borderColor: '#0074D9',
      backgroundColor: 'rgba(0, 116, 217, 0.08)',
      pointBackgroundColor: pointColors,
      pointBorderColor: '#FFFFFF',
      pointBorderWidth: 1,
      borderWidth: 2,
      pointRadius: chartPoints.length <= 7 ? 3 : 1.5,
      pointHoverRadius: 5,
      fill: true,
      tension: isCompletedDay ? 0 : 0.25,
      spanGaps: false,
      parsing: false as const,
    }],
  };

  const sortedEuropeanCategories = [...standardMetadata.categories].sort(
    (first, second) => first.internal_severity_rank - second.internal_severity_rank,
  );
  const categoryLabelByRank = new Map(
    sortedEuropeanCategories.map((category) => [
      category.internal_severity_rank,
      getAirQualityIndexCategoryLabel(category.code),
    ]),
  );
  const isEuropean = standardMetadata.standard_code === 'eea_european';
  const options: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    plugins: {
      legend: {
        display: true,
        position: 'top',
        labels: {
          usePointStyle: true,
          pointStyle: 'circle',
          padding: 16,
          font: { size: 11 },
          generateLabels: (chart) => (
            ChartJS.defaults.plugins.legend.labels.generateLabels(chart).map((label) => ({
              ...label,
              text: label.text.length > 40 ? `${label.text.slice(0, 38)}…` : label.text,
            }))
          ),
        },
      },
      tooltip: {
        mode: 'nearest',
        intersect: false,
        backgroundColor: 'rgba(0,0,0,0.85)',
        padding: 14,
        displayColors: false,
        callbacks: {
          title: (items) => {
            const point = state.points[items[0]?.dataIndex ?? -1];
            if (!point) return '';
            if (isCompletedDay) {
              return new Date(`${point.timestamp}T00:00:00Z`).toLocaleDateString(
                undefined,
                { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' },
              );
            }
            return new Date(point.timestamp).toLocaleString();
          },
          label: (context) => {
            const point = state.points[context.dataIndex];
            if (!point || point.numericValue == null) {
              return point?.exclusionReason
                ? i18n.t('aq:aqiTrendCard.dynamic.unavailableReason', {
                    reason: getExclusionReasonLabel(point.exclusionReason),
                  })
                : i18n.t('aq:completedDayPresentation.status.unavailable');
            }
            return isEuropean
              ? point.categoryCode
                ? getAirQualityIndexCategoryLabel(point.categoryCode)
                : i18n.t('aq:aqiTrendCard.text.europeanCategoryUnavailable')
              : point.categoryCode
                ? i18n.t('aq:completedDayPresentation.tooltip.aqiWithCategory', {
                    value: point.numericValue,
                    category: getAirQualityIndexCategoryLabel(point.categoryCode),
                  })
                : i18n.t('aq:completedDayPresentation.tooltip.aqi', { value: point.numericValue });
          },
        },
      },
      zoom: {
        pan: { enabled: true, mode: 'x', modifierKey: 'shift' },
        zoom: {
          wheel: { enabled: true, modifierKey: 'ctrl' },
          pinch: { enabled: true },
          drag: {
            enabled: true,
            backgroundColor: 'rgba(6, 71, 137, 0.1)',
            borderColor: 'rgba(6, 71, 137, 0.5)',
            borderWidth: 1,
          },
          mode: 'x',
        },
        limits: { x: { min: 'original', max: 'original' } },
      },
    },
    scales: {
      x: isCompletedDay ? {
        type: 'time',
        time: { unit: 'day', displayFormats: { day: 'MMM d' } },
        grid: { display: false },
        ticks: { color: '#666', font: { size: 11 }, maxRotation: 0 },
        title: { display: true, text: i18n.t('aq:aqiTrendCard.axes.localDate'), color: '#374151', font: { size: 12, weight: 500 } },
      } : {
        type: 'time',
        time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
        grid: { display: false },
        ticks: { color: '#666', font: { size: 11 }, maxRotation: 50 },
        title: { display: true, text: i18n.t('aq:aqiTrendCard.axes.localTime'), color: '#374151', font: { size: 12, weight: 500 } },
      },
      y: {
        type: 'linear',
        beginAtZero: !isEuropean,
        suggestedMax: isEuropean
          ? sortedEuropeanCategories.at(-1)?.internal_severity_rank
          : 100,
        grid: { color: 'rgba(0,0,0,0.05)' },
        ticks: {
          color: '#666',
          font: { size: 11 },
          stepSize: isEuropean ? 1 : undefined,
          callback: isEuropean
            ? (value) => categoryLabelByRank.get(Number(value)) ?? ''
            : undefined,
        },
        title: {
          display: true,
          text: isEuropean
            ? i18n.t('aq:aqiTrendCard.axes.europeanCategory')
            : i18n.t('aq:aqiTrendCard.axes.aqi'),
          color: '#374151',
          font: { size: 12, weight: 500 },
        },
      },
    },
  };

  const title = isCompletedDay
    ? i18n.t('aq:aqiTrendCard.headings.lastSevenDays')
    : i18n.t('aq:aqiTrendCard.headings.lastTwentyFourHours');
  return (
    <div className="sensor-chart aqi-trend-card" data-testid="aqi-trend-card">
      <div className="chart-header">
        <div className="chart-title">{title}</div>
        <div className="chart-actions">
          <button
            type="button"
            className="chart-action-btn"
            onClick={() => chartRef.current?.resetZoom()}
            title={i18n.t('aq:aqiTrendCard.tooltips.resetZoom')}
          >
            <Trans ns="aq" i18nKey="aqiTrendCard.actions.resetZoom" /></button>
        </div>
      </div>

      {state.loading && (
        <div className="chart-loading aqi-trend-card__state" role="status">
          <span className="aqi-trend-card__loading-bar" />
          <span><Trans ns="aq" i18nKey="aqiTrendCard.text.loadingAqiHistory" /></span>
        </div>
      )}
      {state.error && !state.loading && (
        <div className="chart-error aqi-trend-card__state" role="alert">
          <span><Trans ns="aq" i18nKey="aqiTrendCard.text.historicalAqiCouldNotLoaded" /></span>
          <button type="button" className="chart-action-btn" onClick={() => setRetryToken((token) => token + 1)}>
            <Trans ns="common" i18nKey="actions.retry" /></button>
        </div>
      )}
      {!state.loading && !state.error && availablePointCount === 0 && (
        <div className="chart-empty aqi-trend-card__state" role="status">
          <Trans ns="aq" i18nKey="aqiTrendCard.text.noHistoricalAqiValuesAvailablePeriod" /></div>
      )}
      {!state.loading && !state.error && availablePointCount > 0 && (
        <>
          <div className="chart-wrapper">
            <Line ref={chartRef} data={chartData} options={options} />
          </div>
          <p className="aqi-trend-card__coverage" role="status">
            {i18n.t('aq:aqiTrendCard.counts.availableResults', { count: availablePointCount })}{unavailablePointCount > 0
              ? i18n.t('aq:aqiTrendCard.counts.unavailableIntervals', { count: unavailablePointCount })
              : ''}
          </p>
        </>
      )}
    </div>
  );
}
