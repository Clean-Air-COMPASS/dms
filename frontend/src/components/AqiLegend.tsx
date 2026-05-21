import React from 'react';
import { AQI_BUCKETS, AQI_NO_DATA_COLOR } from '../aqi';



export interface AqiLegendProps {
  
  compact?: boolean;
  
  showNoData?: boolean;
  
  className?: string;
}


const AQI_CATEGORIES = [
  { max: 50, label: 'Good', description: 'Air quality is satisfactory' },
  { max: 100, label: 'Moderate', description: 'Acceptable; may affect sensitive individuals' },
  { max: 150, label: 'Unhealthy for Sensitive Groups', description: 'Sensitive groups may experience effects' },
  { max: 200, label: 'Unhealthy', description: 'Everyone may experience health effects' },
  { max: 300, label: 'Very Unhealthy', description: 'Health alert; serious effects possible' },
  { max: 500, label: 'Hazardous', description: 'Health emergency; entire population affected' },
];

const AqiLegend: React.FC<AqiLegendProps> = ({ compact = false, showNoData = true, className = '' }) => {
  if (compact) {
    return (
      <div className={`aqi-legend aqi-legend--compact ${className}`}>
        <div className="aqi-legend__title">AQI</div>
        <div className="aqi-legend__bar">
          {AQI_BUCKETS.map((bucket, idx) => {
            const prevMax = idx > 0 ? AQI_BUCKETS[idx - 1].max : 0;
            const range = `${prevMax + 1}-${bucket.max}`;
            return (
              <div
                key={bucket.max}
                className="aqi-legend__segment"
                style={{ backgroundColor: bucket.color }}
                title={`${range}: ${AQI_CATEGORIES[idx].label}`}
              >
                <span className="aqi-legend__range">{bucket.max}</span>
              </div>
            );
          })}
        </div>
        {showNoData && (
          <div className="aqi-legend__nodata" style={{ backgroundColor: AQI_NO_DATA_COLOR }}>
            <span>N/A</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`aqi-legend aqi-legend--full ${className}`}>
      <div className="aqi-legend__header">
        <span className="aqi-legend__title">Air Quality Index (AQI)</span>
      </div>
      <div className="aqi-legend__items">
        {AQI_BUCKETS.map((bucket, idx) => {
          const prevMax = idx > 0 ? AQI_BUCKETS[idx - 1].max : 0;
          const range = `${prevMax}-${bucket.max}`;
          const category = AQI_CATEGORIES[idx];
          return (
            <div key={bucket.max} className="aqi-legend__item">
              <div
                className="aqi-legend__color"
                style={{ backgroundColor: bucket.color }}
              />
              <div className="aqi-legend__text">
                <span className="aqi-legend__range">{range}</span>
                <span className="aqi-legend__label">{category.label}</span>
              </div>
            </div>
          );
        })}
        {showNoData && (
          <div className="aqi-legend__item aqi-legend__item--nodata">
            <div
              className="aqi-legend__color"
              style={{ backgroundColor: AQI_NO_DATA_COLOR }}
            />
            <div className="aqi-legend__text">
              <span className="aqi-legend__label">No Data</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default AqiLegend;
