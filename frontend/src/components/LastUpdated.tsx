import React, { useState, useEffect, useCallback } from 'react';



export interface LastUpdatedProps {
  
  timestamp?: string | null;
  
  autoRefresh?: boolean;
  
  refreshInterval?: number;
  
  onRefresh?: () => void;
  
  className?: string;
  
  showEmptyText?: boolean;
}


function formatElapsed(diffMs: number): string {
  if (diffMs < 0) return 'in the future';
  const sec = Math.floor(diffMs / 1000);
  if (sec < 30) return 'just now';
  if (sec < 90) return '1 min ago';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} hr${hr === 1 ? '' : 's'} ago`;
  const day = Math.floor(hr / 24);
  return `${day} day${day === 1 ? '' : 's'} ago`;
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
        <span className="last-updated__text">No data loaded</span>
        {onRefresh && (
          <button
            className="last-updated__refresh-btn"
            onClick={handleManualRefresh}
            title="Refresh data"
            aria-label="Refresh data"
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
  const elapsed = formatElapsed(diffMs);

  return (
    <div className={`last-updated last-updated--${status} ${className}`}>
      <span className="last-updated__dot" aria-hidden="true" />
      <span className="last-updated__text">
        Updated {elapsed}
      </span>
      {autoRefresh && (
        <span className="last-updated__countdown" title={`Auto-refresh in ${countdown}s`}>
          ({countdown}s)
        </span>
      )}
      {onRefresh && (
        <button
          className="last-updated__refresh-btn"
          onClick={handleManualRefresh}
          title="Refresh now"
          aria-label="Refresh now"
        >
          ↻
        </button>
      )}
    </div>
  );
};

export default LastUpdated;
