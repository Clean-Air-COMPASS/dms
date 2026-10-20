import { Trans } from 'react-i18next';
import i18n, { formatDisplayRelativeTimeFromNow } from '../i18n';
import React, { useState, useEffect, useCallback } from 'react';



export interface LastUpdatedProps {
  
  timestamp?: string | null;
  
  autoRefresh?: boolean;
  
  refreshInterval?: number;
  
  onRefresh?: () => void;
  
  className?: string;
  
  showEmptyText?: boolean;
}


function getFreshnessStatus(diffMs: number): 'fresh' | 'stale' | 'old' {
  const minutes = diffMs / (1000 * 60);
  if (minutes <= 15) return 'fresh';
  if (minutes <= 60) return 'stale';
  return 'old';
}

const LastUpdated: React.FC<LastUpdatedProps> = ({
  timestamp,
  autoRefresh = false,
  refreshInterval = 60,
  onRefresh,
  className = '',
  showEmptyText = true,
}) => {
  const [now, setNow] = useState(Date.now());
  const [countdown, setCountdown] = useState(refreshInterval);

  
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(interval);
  }, []);

  
  useEffect(() => {
    if (!autoRefresh || !onRefresh) return;
    
    setCountdown(refreshInterval);
    const interval = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          onRefresh();
          return refreshInterval;
        }
        return prev - 1;
      });
    }, 1000);
    
    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, onRefresh]);

  const handleManualRefresh = useCallback(() => {
    if (onRefresh) {
      onRefresh();
      setCountdown(refreshInterval);
    }
  }, [onRefresh, refreshInterval]);

  if (!timestamp) {
    if (!showEmptyText) return null;
    return (
      <div className={`last-updated last-updated--unknown ${className}`}>
        <span className="last-updated__text"><Trans ns="map" i18nKey="lastUpdated.text.noDataLoaded" /></span>
        {onRefresh && (
          <button
            className="last-updated__refresh-btn"
            onClick={handleManualRefresh}
            title={i18n.t('map:lastUpdated.tooltips.refreshData')}
            aria-label={i18n.t('map:lastUpdated.accessibility.refreshData')}
          >
            ↻
          </button>
        )}
      </div>
    );
  }

  const updatedAt = new Date(timestamp);
  const diffMs = now - updatedAt.getTime();
  const status = getFreshnessStatus(diffMs);
  const elapsed = formatDisplayRelativeTimeFromNow(
    updatedAt,
    now,
    i18n.resolvedLanguage === 'es' ? 'es' : 'en',
  );

  return (
    <div className={`last-updated last-updated--${status} ${className}`}>
      <span className="last-updated__dot" aria-hidden="true" />
      <span className="last-updated__text">
        {i18n.t('map:lastUpdated.text.updatedElapsed', { elapsed })}
      </span>
      {autoRefresh && (
        <span
          className="last-updated__countdown"
          title={i18n.t('map:lastUpdated.countdown.autoRefresh', { count: countdown })}
        >
          ({countdown}s)
        </span>
      )}
      {onRefresh && (
        <button
          className="last-updated__refresh-btn"
          onClick={handleManualRefresh}
          title={i18n.t('map:lastUpdated.tooltips.refreshNow')}
          aria-label={i18n.t('map:lastUpdated.accessibility.refreshNow')}
        >
          ↻
        </button>
      )}
    </div>
  );
};

export default LastUpdated;
