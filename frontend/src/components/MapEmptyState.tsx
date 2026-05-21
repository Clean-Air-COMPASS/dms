import React from 'react';

export interface MapEmptyStateProps {
  
  mode: 'pollutants' | 'devices';
  
  parameter?: string | null;
}


const MapEmptyState: React.FC<MapEmptyStateProps> = ({ mode, parameter }) => {
  const title = mode === 'pollutants' ? 'No Measurements Found' : 'No Devices Found';
  
  const message = mode === 'pollutants'
    ? `No ${parameter ? parameter.toUpperCase() + ' ' : ''}measurements match your current filters.`
    : 'No devices match your current filters.';

  return (
    <div className="map-empty-state" role="status" aria-live="polite" data-testid="map-empty-state">
      <div className="map-empty-state__icon" aria-hidden="true">📍</div>
      <h3 className="map-empty-state__title">{title}</h3>
      <p className="map-empty-state__message">{message}</p>
      <ul className="map-empty-state__suggestions">
        <li>Try selecting a different time range</li>
        {mode === 'pollutants' && <li>Choose a different parameter</li>}
        <li>Check if data sources are available</li>
      </ul>
    </div>
  );
};

export default MapEmptyState;
