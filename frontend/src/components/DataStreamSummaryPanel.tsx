import { Trans } from 'react-i18next';
import i18n from '../i18n';

export interface DataStreamInfo {
  kind: 'measurement' | 'aqi';
  seriesKey: string;
  
  sensorId: number | null;
  deviceId: number | null;
  
  sensorName: string;
  
  externalSensorId: string | number | null;
  
  parameterCode: string;
  
  parameterDisplayName: string;
  
  unit: string;
  
  aggregateCode: string;
  
  shownDuration: string;
  
  source: string | null;
  
  isPrimary: boolean;
  
  chartColor: string;
  
  overlayKey?: string;
  standardDisplayName?: string | null;
  standardCode?: string | null;
  productDisplayName?: string | null;
  resultKind?: 'numeric' | 'categorical' | null;
  historyInterval?: string | null;
}

interface DataStreamSummaryPanelProps {
  
  dataStreams: DataStreamInfo[];
  
  onRemoveSeries?: (seriesKey: string) => void;
}


export function DataStreamSummaryPanel({
  dataStreams,
  onRemoveSeries,
}: DataStreamSummaryPanelProps) {
  if (!dataStreams || dataStreams.length === 0) {
    return null;
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-sm p-4 mb-4">
      <div className="flex flex-wrap items-center justify-between gap-1 mb-3">
        <h3 className="text-sm font-semibold text-slate-700">
          <Trans ns="analytics" i18nKey="dataStreamSummaryPanel.headings.activeDataStreams" />{dataStreams.length})
        </h3>
        {dataStreams.length > 1 && (
          <span className="text-xs text-slate-500">
            <Trans ns="analytics" i18nKey="dataStreamSummaryPanel.text.showing" />{dataStreams.filter(d => d.isPrimary).length} {' '}<Trans ns="analytics" i18nKey="dataStreamSummaryPanel.text.primary" />{' '}{dataStreams.filter(d => !d.isPrimary).length} <Trans ns="analytics" i18nKey="dataStreamSummaryPanel.text.overlay" /></span>
        )}
      </div>
      
      
      <div className={`
        grid grid-cols-1 gap-3 min-w-0
        ${dataStreams.length <= 4 ? 'sm:grid-cols-2' : 'sm:grid-cols-2 lg:grid-cols-3'}
      `}>
        {dataStreams.map((stream) => (
          <DataStreamItem
            key={stream.seriesKey}
            stream={stream}
            compact={dataStreams.length > 4}
            onRemove={
              !stream.isPrimary && onRemoveSeries
                ? () => onRemoveSeries(stream.seriesKey)
                : undefined
            }
          />
        ))}
      </div>
    </div>
  );
}

interface DataStreamItemProps {
  stream: DataStreamInfo;
  compact?: boolean;
  onRemove?: () => void;
}


function DataStreamItem({ stream, compact, onRemove }: DataStreamItemProps) {
  const {
    sensorName,
    externalSensorId,
    parameterCode,
    parameterDisplayName,
    unit,
    shownDuration,
    source,
    isPrimary,
    chartColor,
    kind,
    standardDisplayName,
    productDisplayName,
    resultKind,
    historyInterval,
  } = stream;

  
  const formattedExternalId = externalSensorId != null
    ? String(externalSensorId)
    : i18n.t('common:states.notAvailableShort');

  
  const formattedSource = source || i18n.t('analytics:analytics.states.unknownSource');

  return (
    <div
      className={`
        relative flex items-start gap-3 p-3 rounded-lg border min-w-0 max-w-full overflow-hidden
        ${isPrimary ? 'border-blue-300 bg-blue-50/50' : 'border-slate-200 bg-slate-50/50'}
        ${compact ? 'p-2' : 'p-3'}
      `}
    >
      
      <div
        className="flex-shrink-0 w-3 h-3 rounded-full mt-1 ring-2 ring-white shadow-sm"
        style={{ backgroundColor: chartColor }}
        title={i18n.t('analytics:analytics.dynamic.chartLineColorFor', { sensor: sensorName })}
        aria-label={i18n.t('analytics:analytics.dynamic.chartLineColor', { color: chartColor })}
      />
      
      <div className="flex-1 min-w-0">
        
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <span
            className={`font-medium text-slate-800 truncate min-w-0 max-w-full ${compact ? 'text-sm' : 'text-base'}`}
            title={sensorName}
          >
            {sensorName || i18n.t('analytics:analytics.states.unnamedSensor')}
          </span>
          {isPrimary && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-semibold bg-blue-600 text-white">
              <Trans ns="analytics" i18nKey="dataStreamSummaryPanel.text.primary2" /></span>
          )}
        </div>
        
        
        <div className={`flex items-center gap-2 flex-wrap mt-1 ${compact ? 'text-xs' : 'text-sm'} text-slate-600`}>
          <span className="font-medium text-slate-700">{kind === 'aqi' ? productDisplayName : (parameterDisplayName || parameterCode.toUpperCase())}</span>
          <span className="text-slate-400">•</span>
          <span>{kind === 'aqi' ? (resultKind === 'categorical' ? i18n.t('analytics:analytics.states.category') : 'AQI') : unit}</span>
          <span className="text-slate-400">•</span>
          <span className="text-slate-500">{kind === 'aqi' && historyInterval === 'represented_device_local_date' ? i18n.t('analytics:dataStreamSummaryPanel.text.completedLocalDay') : shownDuration}</span>
        </div>
        
        
        <div className={`flex items-center gap-2 flex-wrap mt-1 ${compact ? 'text-xs' : 'text-sm'} text-slate-500`}>
          <span
            className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-200 text-slate-600 text-xs max-w-full truncate"
            title={i18n.t('common:dynamic.dataSource', { source: formattedSource })}
          >
            {formattedSource}
          </span>
          {kind === 'aqi' ? (
            <span className="text-slate-400">{standardDisplayName}</span>
          ) : (
            <span className="text-slate-400"><Trans ns="analytics" i18nKey="dataStreamSummaryPanel.text.id" />{' '}{formattedExternalId}</span>
          )}
        </div>
      </div>
      
      
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="flex-shrink-0 p-1 rounded hover:bg-slate-200 text-slate-400 hover:text-slate-600 transition"
          title={i18n.t('analytics:dataStreamSummaryPanel.tooltips.removeDataStream')}
          aria-label={i18n.t('analytics:dataStreamSummaryPanel.accessibility.removeDataStream', { sensor: sensorName })}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      )}
    </div>
  );
}

export default DataStreamSummaryPanel;
