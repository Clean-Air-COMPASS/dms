import React, { useState, useCallback } from 'react';
import { API_BASE } from '../api';



export interface QuickDownloadProps {
  
  parameter?: string | null;
  
  aggregation?: string | null;
  
  startIso?: string | null;
  
  endIso?: string | null;
  
  loading?: boolean;
  
  className?: string;
  
  showIcon?: boolean;
}

const QuickDownload: React.FC<QuickDownloadProps> = ({
  parameter,
  aggregation,
  startIso,
  endIso,
  loading = false,
  className = '',
  showIcon = true,
}) => {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDownload = useCallback(async () => {
    if (downloading || loading) return;
    
    setDownloading(true);
    setError(null);
    
    try {
      
      const params = new URLSearchParams();
      if (aggregation) params.set('aggregation', aggregation);
      if (startIso) params.set('since', startIso);
      if (endIso) params.set('until', endIso);
      
      const endpoint = parameter
        ? `/measurements/${encodeURIComponent(parameter)}/latest`
        : '/measurements/latest';
      
      const url = `${API_BASE}${endpoint}?${params.toString()}`;
      
      
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Download failed: ${response.statusText}`);
      }
      
      const jsonData = await response.json();
      
      
      if (!Array.isArray(jsonData) || jsonData.length === 0) {
        throw new Error('No data available for download');
      }
      
      
      const escapeCSV = (val: unknown): string => {
        if (val == null) return '';
        const str = String(val);
        
        if (str.includes(',') || str.includes('"') || str.includes('\n')) {
          return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
      };
      
      
      const columns = [
        { header: 'Measurement ID', key: 'measurement_id' },
        { header: 'Sensor ID', key: 'sensor_id' },
        { header: 'External Sensor ID', key: 'external_sensor_id' },
        { header: 'Parameter', key: 'parameter' },
        { header: 'Value', key: 'value' },
        { header: 'Unit', key: 'unit' },
        { header: 'Observed At (UTC)', key: 'observed_at' },
        { header: 'Device ID', key: (row: Record<string, unknown>) => (row.device as Record<string, unknown>)?.device_id },
        { header: 'Device Name', key: (row: Record<string, unknown>) => (row.device as Record<string, unknown>)?.name },
        { header: 'Latitude', key: (row: Record<string, unknown>) => (row.device as Record<string, unknown>)?.latitude },
        { header: 'Longitude', key: (row: Record<string, unknown>) => (row.device as Record<string, unknown>)?.longitude },
        { header: 'Network/Source', key: (row: Record<string, unknown>) => (row.device as Record<string, unknown>)?.network },
      ];
      
      const headerRow = columns.map(c => escapeCSV(c.header)).join(',');
      const dataRows = jsonData.map((row: Record<string, unknown>) => {
        return columns.map(col => {
          const val = typeof col.key === 'function' ? col.key(row) : row[col.key];
          return escapeCSV(val);
        }).join(',');
      });
      
      const csvText = [headerRow, ...dataRows].join('\n');
      
      
      const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' });
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      
      
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const paramPart = parameter ? `_${parameter}` : '';
      const aggPart = aggregation ? `_${aggregation}` : '';
      link.download = `aq_data${paramPart}${aggPart}_${timestamp}.csv`;
      
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Download failed';
      setError(message);
      console.error('Download error:', err);
    } finally {
      setDownloading(false);
    }
  }, [parameter, aggregation, startIso, endIso, downloading, loading]);

  return (
    <div className={`quick-download ${className}`}>
      <button
        type="button"
        className="quick-download-btn"
        onClick={handleDownload}
        disabled={downloading || loading}
        title={downloading ? 'Downloading...' : 'Download current data as CSV'}
        aria-label="Download data"
      >
        {showIcon && (
          <span className="quick-download-btn__icon" aria-hidden="true">
            {downloading ? '⏳' : '⬇️'}
          </span>
        )}
        <span className="quick-download-btn__text">
          {downloading ? 'Downloading...' : 'Download CSV'}
        </span>
      </button>
      {error && (
        <span className="quick-download-error" title={error}>
          ⚠️
        </span>
      )}
    </div>
  );
};

export default QuickDownload;
