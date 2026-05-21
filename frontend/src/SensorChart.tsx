import * as React from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  TimeScale,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import 'chartjs-adapter-date-fns';
import zoomPlugin from 'chartjs-plugin-zoom';
import { fetchJson } from './api';
import { isAqiResolution, describeAqiResolution, getAggregationDisplayLabel } from './aqi';

import { type TimezoneMode, getTimezoneLabel } from './utils/timezone';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  TimeScale,
  zoomPlugin
);

interface HistoryDataPoint {
  timestamp: string;
  value: number;
  is_valid?: boolean;
  qc_flags?: Record<string, any> | null;
  failed_checks?: { check_code: string; severity?: string; message?: string | null }[];
}


interface HistoryResponse {
  sensor_id: number;
  parameter: string;
  parameter_name: string;
  unit: string;
  hours?: number;
  data: HistoryDataPoint[];
  
  device_name?: string;
  
  external_sensor_id?: string | number;
  
  external_api?: { name: string | null } | null;
}

type ParamRule = {
  parameter_code: string;
  aggregation_code: string;
  rounding_method?: string | null;
  rounding_precision?: number | null;
  truncation_method?: string | null;
  truncation_precision?: number | null;
};

interface SensorChartProps {
  sensorId?: number | null;
  parameter?: string | null;
  unit?: string | null;
  hours?: number;
  data?: HistoryResponse | null;
  overlays?: HistoryResponse[];
  aggregationRules?: ParamRule[] | null;
  timeResolution?: string | null;
  timezoneMode?: TimezoneMode;
  streamTimezone?: string | null;
}

const SensorChart: React.FC<SensorChartProps> = ({ sensorId, parameter, unit, hours = 24, data, overlays, aggregationRules, timeResolution, timezoneMode = 'local', streamTimezone }) => {
  const [showInvalid, setShowInvalid] = React.useState(false);
  const [fetched, setFetched] = React.useState<HistoryResponse | null>(null);
  const [loading, setLoading] = React.useState(false);
  const chartRef = React.useRef<any>(null);
  
  
  const timezoneLabel = React.useMemo(() => {
    return getTimezoneLabel(timezoneMode, streamTimezone);
  }, [timezoneMode, streamTimezone]);
  
  
  const isAqiMode = isAqiResolution(timeResolution);
  const aqiLabel = isAqiMode ? describeAqiResolution(timeResolution) : '';

  React.useEffect(() => {
    if (data || !sensorId) return;
    let cancelled = false;
    setLoading(true);
    const params = new URLSearchParams();
    params.set('hours', String(hours ?? 24));
    params.set('include_qc', 'true');
    const agg = (() => {
      const code = (timeResolution || '').toLowerCase();
      if (code === 'raw' || code === 'latest' || code === '1m' || code === 'minute') return 'raw';
      if (code === '24h' || code === 'day') return 'day';
      if (code === '1h' || isAqiResolution(timeResolution)) return 'hour';
      return 'hour';
    })();
    params.set('aggregate', agg);
    (async () => {
      try {
        const d = await fetchJson<HistoryResponse>(`/sensors/${sensorId}/history?${params.toString()}`);
        if (!cancelled) {
          setFetched(d);
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [sensorId, hours, data, timeResolution]);

  
  const handleResetZoom = React.useCallback(() => {
    if (chartRef.current) {
      chartRef.current.resetZoom();
    }
  }, []);

  
  if (loading && !data) {
    return <div className="chart-loading">Loading chart data...</div>;
  }

  const primary: HistoryResponse | null = data ?? fetched ?? null;
  if (!primary && (!overlays || overlays.length === 0)) {
    return <div className="chart-empty">No data available for the selected window</div>;
  }

  const toChartPoints = (d?: HistoryResponse | null) => {
    if (!d?.data) return [];
    const points = d.data
      .filter((p) => {
        if (!p?.timestamp) return false;
        if (p.value == null || Number.isNaN(p.value)) return false;
        return showInvalid ? true : p.is_valid !== false;
      })
      .map((p) => ({ x: new Date(p.timestamp), y: p.value }))
      .sort((a, b) => a.x.getTime() - b.x.getTime());
    return points;
  };

  const primaryPoints = toChartPoints(primary);
  const overlayPointSets = (overlays || []).map((o) => toChartPoints(o));
  
  
  const palette = [
    '#0074D9', '#FF4136', '#2ECC40', '#FF851B', '#7FDBFF',
    '#B10DC9', '#85144b', '#3D9970', '#39CCCC', '#F012BE'
  ];

  
  const buildChartLabel = (historyData: HistoryResponse | null | undefined, isPrimary: boolean): string => {
    if (!historyData) return 'Unknown';
    
    const sensorName = historyData.device_name || `Sensor ${historyData.sensor_id}`;
    const parameterLabel = historyData.parameter_name || historyData.parameter?.toUpperCase() || '';
    const source = historyData.external_api?.name;
    
    const aggCode = (historyData as any)._displayAggregate || timeResolution || '1h';
    const aggLabel = getAggregationDisplayLabel(aggCode);
    
    
    const parts: string[] = [];
    
    
    const truncatedName = sensorName.length > 20 ? sensorName.slice(0, 18) + '…' : sensorName;
    parts.push(truncatedName);
    
    
    if (source) {
      parts[parts.length - 1] += ` (${source})`;
    }
    
    
    parts.push(`${parameterLabel} [${aggLabel}]`);
    
    
    const label = parts.join(' – ');
    return isPrimary ? `${label} ★` : label;
  };

  const datasets: any[] = [];
  if (primary) {
    datasets.push({
      label: buildChartLabel(primary, true),
      data: primaryPoints,
      borderColor: palette[0],
      backgroundColor: 'rgba(0, 116, 217, 0.08)',
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      fill: true,
      tension: 0.4,
      parsing: { xAxisKey: 'x', yAxisKey: 'y' },
      spanGaps: true,
      aqMeta: {
        sensorId: primary.sensor_id,
        sensorName: primary.device_name || `Sensor ${primary.sensor_id}`,
        parameter: primary.parameter,
        parameterName: primary.parameter_name || primary.parameter?.toUpperCase(),
        unit: primary.unit,
        aggregation: (primary as any)._displayAggregate || timeResolution || '1h',
      },
    });
  }
  overlayPointSets.forEach((points: Array<{ x: Date; y: number }>, idx: number) => {
    const overlay = overlays ? overlays[idx] : undefined;
    datasets.push({
      label: buildChartLabel(overlay, false),
      data: points,
      borderColor: palette[(idx + 1) % palette.length],
      backgroundColor: 'transparent',
      borderWidth: 1.5,
      pointRadius: points.length <= 2 ? 2 : 0,
      pointHoverRadius: 4,
      fill: false,
      tension: 0.2,
      parsing: { xAxisKey: 'x', yAxisKey: 'y' },
      spanGaps: true,
      aqMeta: {
        sensorId: overlay?.sensor_id,
        sensorName: overlay?.device_name || (overlay ? `Sensor ${overlay.sensor_id}` : 'Unknown'),
        parameter: overlay?.parameter,
        parameterName: overlay?.parameter_name || overlay?.parameter?.toUpperCase(),
        unit: overlay?.unit,
        aggregation: (overlay as any)?._displayAggregate || timeResolution || '1h',
      },
    });
  });

  const allLabels = (() => {
    const ts = new Set<number>();
    primaryPoints.forEach((p) => ts.add(p.x.getTime()));
    overlayPointSets.forEach((set) => set.forEach((p) => ts.add(p.x.getTime())));
    return Array.from(ts).sort().map((ms) => new Date(ms));
  })();

  const chartData = { labels: allLabels, datasets };
  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: true as const,
        position: 'top' as const,
        labels: {
          
          usePointStyle: true,
          pointStyle: 'circle',
          padding: 16,
          font: { size: 11 },
          
          generateLabels: (chart: any) => {
            const defaultLabels = ChartJS.defaults.plugins.legend.labels.generateLabels(chart);
            return defaultLabels.map((label: any) => ({
              ...label,
              
              text: label.text && label.text.length > 40 
                ? label.text.slice(0, 38) + '…' 
                : label.text,
            }));
          },
        },
      },
      tooltip: {
        mode: 'index' as const,
        intersect: false,
        backgroundColor: 'rgba(0,0,0,0.85)',
        padding: 14,
        titleFont: { size: 12, weight: 'bold' as const },
        bodyFont: { size: 12 },
        bodySpacing: 6,
        boxPadding: 4,
        callbacks: {
          title: (items: any[]) => {
            if (!items || items.length === 0) return '';
            return new Date(items[0].parsed.x).toLocaleString();
          },
          
          label: (context: any) => {
            const y = context.parsed.y;
            if (y == null || Number.isNaN(y)) return ''; 

            const meta = context?.dataset?.aqMeta || {};
            const sensorName = meta.sensorName || 'Unknown';
            const effectiveParameter = (meta.parameter ?? parameter) || '';
            const parameterName = meta.parameterName || effectiveParameter.toUpperCase();
            const effectiveUnit = (meta.unit ?? unit) || '';
            const effectiveAgg = (meta.aggregation ?? timeResolution) || '1h';
            const aggLabel = getAggregationDisplayLabel(effectiveAgg);

            
            let formattedValue = y.toFixed(2);
            if (aggregationRules && effectiveParameter) {
              try {
                const paramCode = (effectiveParameter || '').toLowerCase();
                const aggCode = effectiveAgg && String(effectiveAgg).trim() ? String(effectiveAgg).toLowerCase() : '1h';
                const map = new Map<string, ParamRule>();
                (aggregationRules as ParamRule[]).forEach((r) => {
                  if (!r || !r.parameter_code || !r.aggregation_code) return;
                  map.set(`${r.parameter_code.toLowerCase()}__${r.aggregation_code.toLowerCase()}`, r);
                });
                let rule = map.get(`${paramCode}__${aggCode}`) || (aggCode === '1h' ? undefined : map.get(`${paramCode}__1h`));
                if (!rule) {
                  if (paramCode === 'pm25' && aggCode === '1h') {
                    rule = { parameter_code: 'pm25', aggregation_code: '1h', rounding_method: 'round', rounding_precision: 1, truncation_method: 'none', truncation_precision: null } as ParamRule;
                  }
                }
                if (rule) {
                  let processed = y as number;
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
                    const str = (processed as number).toFixed(displayPrecision);
                    formattedValue = str === '-0' ? '0' : str;
                  }
                }
              } catch {
                // Fall back to default formatting on error
              }
            }

            
            const truncatedSensorName = sensorName.length > 25 ? sensorName.slice(0, 23) + '…' : sensorName;
            
            return `${truncatedSensorName} • ${parameterName} [${aggLabel}]: ${formattedValue} ${effectiveUnit}`;
          },
          
          filter: (item: any) => item.formattedValue !== '' && item.formattedValue != null,
        },
      },
      zoom: {
        pan: {
          enabled: true,
          mode: 'x' as const,
          modifierKey: 'shift' as const,
        },
        zoom: {
          wheel: {
            enabled: true,
            modifierKey: 'ctrl' as const,
          },
          pinch: {
            enabled: true,
          },
          drag: {
            enabled: true,
            backgroundColor: 'rgba(6, 71, 137, 0.1)',
            borderColor: 'rgba(6, 71, 137, 0.5)',
            borderWidth: 1,
          },
          mode: 'x' as const,
        },
        limits: {
          x: { min: 'original' as const, max: 'original' as const },
        },
      },
    },
    scales: {
      x: {
        type: 'time' as const,
        time: { unit: 'hour' as const, displayFormats: { hour: 'HH:mm' } },
        grid: { display: false },
        ticks: { font: { size: 11 }, color: '#666' },
        title: {
          display: true,
          text: `Time (${timezoneLabel})`,
          font: { size: 12, weight: 500 },
          color: '#374151',
        },
      },
      y: {
        type: 'linear' as const,
        beginAtZero: false,
        grid: { color: 'rgba(0,0,0,0.05)' },
        ticks: {
          font: { size: 11 },
          color: '#666',
          // Let Chart.js auto-generate unique, evenly spaced numeric ticks
        },
        title: {
          display: true,
          text: (() => {
            
            const allUnits = new Set<string>();
            const allParameters = new Set<string>();
            
            
            if (primary?.unit) allUnits.add(primary.unit);
            if (primary?.parameter) allParameters.add(primary.parameter.toUpperCase());
            
            
            if (overlays && overlays.length > 0) {
              overlays.forEach((overlay) => {
                if (overlay?.unit) allUnits.add(overlay.unit);
                if (overlay?.parameter) allParameters.add(overlay.parameter.toUpperCase());
              });
            }
            
            
            if (allUnits.size === 0 && unit) allUnits.add(unit);
            if (allParameters.size === 0 && parameter) allParameters.add(parameter.toUpperCase());
            
            
            const hasMultipleUnits = allUnits.size > 1;
            const hasMultipleParameters = allParameters.size > 1;
            
            let yAxisLabel = '';
            
            if (hasMultipleParameters) {
              
              yAxisLabel = 'Multiple Parameters';
            } else if (allParameters.size === 1) {
              
              yAxisLabel = Array.from(allParameters)[0];
            } else {
              yAxisLabel = 'Value';
            }
            
            
            if (hasMultipleUnits) {
              
              yAxisLabel += ' (Mixed Units)';
            } else if (allUnits.size === 1) {
              
              yAxisLabel += ` (${Array.from(allUnits)[0]})`;
            }
            
            
            const aggLabel = isAqiMode ? aqiLabel : getAggregationDisplayLabel(timeResolution);
            if (aggLabel && !hasMultipleParameters) {
              yAxisLabel += ` – ${aggLabel}`;
            }
            
            return yAxisLabel;
          })(),
          font: { size: 12, weight: 500 },
          color: '#374151',
        },
      },
    },
    interaction: { mode: 'nearest' as const, axis: 'x' as const, intersect: false },
  };

  return (
    <div className="sensor-chart">
      <div className="chart-header">
        <div className="chart-title">
          {isAqiMode ? (
            <>
              {aqiLabel} – Concentration History
              <span className="chart-subtitle" style={{ display: 'block', fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
                Chart shows raw concentration values used in AQI calculation
              </span>
            </>
          ) : (
            `Last ${hours} Hours`
          )}
        </div>
        <div className="chart-actions">
          <button
            type="button"
            className="chart-action-btn"
            onClick={handleResetZoom}
            title="Reset zoom (double-click chart)"
          >
            Reset Zoom
          </button>
        </div>
      </div>
      <div className="chart-controls mb-8">
        <label className="inline-flex align-center gap-6">
          <input type="checkbox" checked={showInvalid} onChange={(e)=>setShowInvalid(e.target.checked)} />
          Show invalid points
        </label>
      </div>
      <div className="chart-wrapper">
        <Line ref={chartRef} key={`sensor-${sensorId || 'multi'}-h${hours}-d${datasets.length}`} data={chartData} options={options} redraw />
      </div>
    </div>
  );
};

export default SensorChart;
