import i18n from '../i18n';
import React, { useState, useCallback, useId, useRef } from 'react';
import { API_BASE } from '../api';
import { buildDeviceCsv, buildMeasurementCsv } from '../quickDownloadCsv';
import { createUtf8CsvBlob } from '../measurementCsv';
import { fetchLatestAqiCsv } from '../aqiCsv';



export interface QuickDownloadProps {
  mode?: 'devices' | 'measurements' | 'aqi';
  standardCode?: string;
  productCode?: string;
  aqiParameterCode?: string | null;
  source?: string;
  
  parameter?: string | null;
  
  aggregation?: string | null;
  
  startIso?: string | null;
  
  endIso?: string | null;
  
  loading?: boolean;
  
  className?: string;
  
  showIcon?: boolean;

  iconOnly?: boolean;

  explanation?: string;
}

const QuickDownload: React.FC<QuickDownloadProps> = ({
  mode = 'measurements',
  standardCode,
  productCode,
  aqiParameterCode,
  source,
  parameter,
  aggregation,
  startIso,
  endIso,
  loading = false,
  className = '',
  showIcon = true,
  iconOnly = false,
  explanation,
}) => {
  const descriptionId = useId();
  const downloadInProgress = useRef(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDownload = useCallback(async () => {
    if (downloadInProgress.current || loading) return;
    downloadInProgress.current = true;
    
    setDownloading(true);
    setError(null);
    
    try {
      let csvText: string;
      if (mode === 'aqi') {
        csvText = await fetchLatestAqiCsv(standardCode || '', productCode || '', source, aqiParameterCode);
      } else {
        const params = new URLSearchParams();
        if (source) params.set('external_api_name', source);
        if (mode === 'devices') {
          if (parameter) params.set('parameter', parameter);
        } else {
          if (aggregation) params.set('aggregation', aggregation);
          if (startIso) params.set('since', startIso);
          if (endIso) params.set('until', endIso);
        }
      
        const endpoint = mode === 'devices' ? '/devices' : parameter
          ? `/measurements/${encodeURIComponent(parameter)}/latest`
          : '/measurements/latest';
      
        const rows: Record<string, unknown>[] = [];
        const sensorIds = new Set<unknown>();
        const pageSize = 100;
        let offset = 0;
        while (true) {
          if (mode === 'measurements') {
            params.set('limit', String(pageSize));
            params.set('offset', String(offset));
          }
          const response = await fetch(`${API_BASE}${endpoint}?${params.toString()}`);
          if (!response.ok) throw new Error(`download_failed:${response.status}`);
          const page: unknown = await response.json();
          if (!Array.isArray(page) || page.some(row => !row || typeof row !== 'object' || Array.isArray(row))) {
            throw new Error('download_invalid_response');
          }
          if (mode === 'measurements') {
            // A repeated sensor means pagination is inconsistent. Fail explicitly
            // instead of saving a duplicated or silently incomplete result set.
            for (const row of page) {
              if (typeof row.sensor_id !== 'number' || sensorIds.has(row.sensor_id)) {
                throw new Error('download_inconsistent_page');
              }
              sensorIds.add(row.sensor_id);
            }
          }
          rows.push(...page);
          if (mode === 'devices' || page.length < pageSize) break;
          offset += pageSize;
        }
        if (rows.length === 0) {
          throw new Error('download_empty');
        }
      
        csvText = mode === 'devices' ? buildDeviceCsv(rows) : buildMeasurementCsv(rows);
      }
      
      
      const blob = createUtf8CsvBlob(csvText);
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      
      
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const paramPart = parameter ? `_${parameter}` : '';
      const aggPart = aggregation ? `_${aggregation}` : '';
      link.download = mode === 'devices'
        ? `compassaq-devices-${new Date().toISOString().slice(0, 10)}.csv`
        : mode === 'aqi' ? `compassaq-aqi-${productCode}-${timestamp}.csv`
        : `aq_data${paramPart}${aggPart}_${timestamp}.csv`;
      
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err: unknown) {
      const message = i18n.t(err instanceof Error && err.message === 'download_empty'
        ? 'map:app.text.downloadEmpty' : 'map:app.text.downloadFailed');
      setError(message);
      console.error('Download error:', err);
    } finally {
      downloadInProgress.current = false;
      setDownloading(false);
    }
  }, [mode, standardCode, productCode, aqiParameterCode, source, parameter, aggregation, startIso, endIso, loading]);

  const buttonLabel = downloading
    ? i18n.t('analytics:quickDownload.text.downloadingCsv')
    : i18n.t('analytics:quickDownload.text.downloadCsv');

  const downloadControl = (
    <>
      <button
        type="button"
        className={`quick-download-btn${iconOnly ? ' quick-download-btn--icon-only' : ''}`}
        onClick={handleDownload}
        disabled={downloading || loading}
        title={buttonLabel}
        aria-label={buttonLabel}
        aria-busy={downloading}
        aria-describedby={explanation ? descriptionId : undefined}
      >
        {(showIcon || iconOnly) && (
          <span className="quick-download-btn__icon" aria-hidden="true">
            {downloading ? (
              <svg className="quick-download-btn__spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="9" strokeOpacity="0.25" strokeWidth="2" />
                <path d="M12 3a9 9 0 0 1 9 9" strokeLinecap="round" strokeWidth="2" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 4v11" strokeWidth="2" />
                <path d="m7 11 5 5 5-5" strokeWidth="2" />
                <path d="M5 20h14" strokeWidth="2" />
              </svg>
            )}
          </span>
        )}
        {!iconOnly && (
          <span className="quick-download-btn__text">
            {downloading ? i18n.t('analytics:quickDownload.text.downloading') : i18n.t('analytics:quickDownload.text.downloadCsv')}
          </span>
        )}
      </button>
      <span className="sr-only" role="status">{downloading ? buttonLabel : ''}</span>
      {error && <span className="quick-download-error" role="alert">{error}</span>}
    </>
  );
  return explanation ? (
    <details className="quick-download map-download">
      <summary className="btn">{i18n.t('map:app.actions.csvExport')}</summary>
      <div className="map-download-panel">
        <p id={descriptionId}>{explanation}</p>
        {downloadControl}
      </div>
    </details>
  ) : <div className={`quick-download${className ? ` ${className}` : ''}`}>{downloadControl}</div>;
};

export default QuickDownload;
