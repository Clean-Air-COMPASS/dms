
export interface DataStreamInfo {
  
  sensorId: number;
  
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
}

interface DataStreamSummaryPanelProps {
  
  dataStreams: DataStreamInfo[];
  
  onRemoveOverlay?: (overlayKey: string) => void;
}


export function DataStreamSummaryPanel({
  dataStreams,
  onRemoveOverlay,
}: DataStreamSummaryPanelProps) {
  if (!dataStreams || dataStreams.length === 0) {
    return null;
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-sm p-4 mb-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-700">
          Active Data Streams ({dataStreams.length})
        </h3>
        {dataStreams.length > 1 && (
          <span className="text-xs text-slate-500">
            Showing {dataStreams.filter(d => d.isPrimary).length} primary + {dataStreams.filter(d => !d.isPrimary).length} overlay
          </span>
        )}
      </div>
      
      
      <div className={`
        grid gap-3
        ${dataStreams.length <= 4 ? 'sm:grid-cols-2' : 'sm:grid-cols-2 lg:grid-cols-3'}
      `}>
        {dataStreams.map((stream) => (
          <DataStreamItem
            key={`${stream.sensorId}-${stream.parameterCode}-${stream.aggregateCode}`}
            stream={stream}
            compact={dataStreams.length > 4}
            onRemove={
              !stream.isPrimary && onRemoveOverlay && stream.overlayKey
                ? () => onRemoveOverlay(stream.overlayKey!)
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
  } = stream;

  
  const formattedExternalId = externalSensorId != null
    ? String(externalSensorId)
    : 'N/A';

  
  const formattedSource = source || 'Unknown Source';

  return (
    <div
      className={`
        relative flex items-start gap-3 p-3 rounded-lg border
        ${isPrimary ? 'border-blue-300 bg-blue-50/50' : 'border-slate-200 bg-slate-50/50'}
        ${compact ? 'p-2' : 'p-3'}
      `}
    >
      
      <div
        className="flex-shrink-0 w-3 h-3 rounded-full mt-1 ring-2 ring-white shadow-sm"
        style={{ backgroundColor: chartColor }}
        title={`Chart line color for ${sensorName}`}
        aria-label={`Chart line color: ${chartColor}`}
      />
      
      <div className="flex-1 min-w-0">
        
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={`font-medium text-slate-800 truncate ${compact ? 'text-sm' : 'text-base'}`}
            title={sensorName}
          >
            {sensorName || 'Unnamed Sensor'}
          </span>
          {isPrimary && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-semibold bg-blue-600 text-white">
              Primary
            </span>
          )}
        </div>
        
        
        <div className={`flex items-center gap-2 flex-wrap mt-1 ${compact ? 'text-xs' : 'text-sm'} text-slate-600`}>
          <span className="font-medium text-slate-700">
            {parameterDisplayName || parameterCode.toUpperCase()}
          </span>
          <span className="text-slate-400">•</span>
          <span>{unit}</span>
          <span className="text-slate-400">•</span>
          <span className="text-slate-500">{shownDuration}</span>
        </div>
        
        
        <div className={`flex items-center gap-2 flex-wrap mt-1 ${compact ? 'text-xs' : 'text-sm'} text-slate-500`}>
          <span
            className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-200 text-slate-600 text-xs"
            title={`Data source: ${formattedSource}`}
          >
            {formattedSource}
          </span>
          <span className="text-slate-400">
            ID: {formattedExternalId}
          </span>
        </div>
      </div>
      
      
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="flex-shrink-0 p-1 rounded hover:bg-slate-200 text-slate-400 hover:text-slate-600 transition"
          title="Remove this overlay data stream"
          aria-label={`Remove ${sensorName} overlay`}
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
