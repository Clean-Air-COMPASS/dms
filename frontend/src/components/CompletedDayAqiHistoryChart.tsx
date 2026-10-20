import i18n from '../i18n';
import * as React from 'react';
import {
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartOptions,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import type {
  AirQualityIndexCategoryMetadata,
  UsEpaCompletedDayHistoryResult,
} from '../airQualityIndex';
import {
  buildCompletedDayAqiChartModel,
  buildCompletedDayTooltipLines,
  formatRepresentedLocalDate,
} from '../completedDayAqiHistory';


ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

interface CompletedDayAqiHistoryChartProps {
  results: UsEpaCompletedDayHistoryResult[];
  categories: AirQualityIndexCategoryMetadata[];
  selectedRepresentedLocalDate: string | null;
  calculatedResultCount: number;
  unavailableResultCount: number;
  onSelectRepresentedLocalDate: (representedLocalDate: string) => void;
}

function maximumTickCount(containerWidth: number): number {
  if (containerWidth > 0 && containerWidth < 340) return 6;
  if (containerWidth > 0 && containerWidth < 560) return 10;
  return 14;
}

export default function CompletedDayAqiHistoryChart({
  results,
  categories,
  selectedRepresentedLocalDate,
  calculatedResultCount,
  unavailableResultCount,
  onSelectRepresentedLocalDate,
}: CompletedDayAqiHistoryChartProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = React.useState(0);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === 'undefined') return;
    setContainerWidth(container.getBoundingClientRect().width);
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (typeof width === 'number') setContainerWidth(width);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const chartModel = React.useMemo(() => buildCompletedDayAqiChartModel(
    results,
    categories,
    selectedRepresentedLocalDate,
  ), [results, categories, selectedRepresentedLocalDate]);

  const chartData = React.useMemo(() => ({
    labels: chartModel.labels,
    datasets: [
      {
        label: i18n.t('aq:completedDayAqiHistoryChart.content.calculatedAqi'),
        data: chartModel.calculatedValues,
        borderColor: '#64748B',
        backgroundColor: chartModel.calculatedPointColors,
        pointBackgroundColor: chartModel.calculatedPointColors,
        pointBorderColor: '#FFFFFF',
        pointBorderWidth: 2,
        pointRadius: chartModel.calculatedPointRadii,
        pointHoverRadius: chartModel.calculatedPointHoverRadii,
        borderWidth: 2,
        tension: 0,
        fill: false,
        spanGaps: false,
      },
      {
        label: i18n.t('aq:completedDayAqiHistoryChart.content.aqiUnavailable'),
        data: chartModel.unavailableValues,
        borderColor: 'transparent',
        backgroundColor: '#64748B',
        pointBackgroundColor: '#64748B',
        pointBorderColor: '#FFFFFF',
        pointBorderWidth: 1,
        pointRadius: chartModel.unavailablePointRadii,
        pointHoverRadius: 7,
        pointStyle: 'crossRot' as const,
        showLine: false,
        spanGaps: false,
      },
    ],
  }), [chartModel]);

  const options = React.useMemo<ChartOptions<'line'>>(() => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    onClick: (_event, activeElements) => {
      const resultIndex = activeElements[0]?.index;
      const result = typeof resultIndex === 'number' ? results[resultIndex] : null;
      if (result) onSelectRepresentedLocalDate(result.represented_local_date);
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        mode: 'nearest',
        intersect: false,
        backgroundColor: 'rgba(15, 23, 42, 0.94)',
        padding: 12,
        titleFont: { size: 12, weight: 'bold' },
        bodyFont: { size: 11 },
        bodySpacing: 5,
        displayColors: false,
        callbacks: {
          title: (items) => {
            const result = results[items[0]?.dataIndex ?? -1];
            return result ? formatRepresentedLocalDate(result.represented_local_date) : '';
          },
          label: (context) => {
            const result = results[context.dataIndex];
            return result ? buildCompletedDayTooltipLines(result) : [];
          },
        },
      },
    },
    scales: {
      x: {
        type: 'category',
        grid: { display: false },
        ticks: {
          autoSkip: true,
          maxTicksLimit: maximumTickCount(containerWidth),
          maxRotation: 0,
          color: '#64748B',
          font: { size: 10 },
          callback: (_value, index) => {
            const representedLocalDate = results[index]?.represented_local_date;
            return representedLocalDate ? representedLocalDate.slice(5).replace('-', '/') : '';
          },
        },
        title: {
          display: true,
          text: i18n.t('aq:completedDayAqiHistoryChart.axes.representedLocalDate'),
          color: '#475569',
          font: { size: 11, weight: 500 },
        },
      },
      y: {
        beginAtZero: true,
        suggestedMax: 100,
        grid: { color: 'rgba(15, 23, 42, 0.07)' },
        ticks: { color: '#64748B', font: { size: 10 } },
        title: {
          display: true,
          text: 'AQI',
          color: '#475569',
          font: { size: 11, weight: 500 },
        },
      },
    },
  }), [containerWidth, onSelectRepresentedLocalDate, results]);

  const chartSummary = i18n.t('aq:completedDayAqiHistoryChart.accessibility.summary', {
    count: results.length,
    calculated: calculatedResultCount,
    unavailable: unavailableResultCount,
  });

  return (
    <div
      ref={containerRef}
      className="completed-day-history__chart"
      role="img"
      aria-label={chartSummary}
    >
      <Line data={chartData} options={options} />
    </div>
  );
}
