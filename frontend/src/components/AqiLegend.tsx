import { Trans } from 'react-i18next';
import React from 'react';
import { AQI_BUCKETS, AQI_NO_DATA_COLOR } from '../aqi';
import type { AirQualityIndexStandardMetadata } from '../airQualityIndex';
import { getAirQualityIndexCategoryLabel } from '../airQualityIndexPresentation';



export interface AqiLegendProps {
  
  compact?: boolean;
  
  showNoData?: boolean;
  
  className?: string;
  standardMetadata?: AirQualityIndexStandardMetadata | null;
}


const US_EPA_CATEGORY_CODES = [
  'good',
  'moderate',
  'unhealthy_for_sensitive_groups',
  'unhealthy',
  'very_unhealthy',
  'hazardous',
] as const;

const AqiLegend: React.FC<AqiLegendProps> = ({
  compact = false,
  showNoData = true,
  className = '',
  standardMetadata = null,
}) => {
  const categories = standardMetadata?.categories?.length
    ? [...standardMetadata.categories].sort(
        (first, second) => first.internal_severity_rank - second.internal_severity_rank,
      )
    : AQI_BUCKETS.map((bucket, index) => ({
        code: US_EPA_CATEGORY_CODES[index],
        label: getAirQualityIndexCategoryLabel(US_EPA_CATEGORY_CODES[index]),
        color: bucket.color,
        internal_severity_rank: index + 1,
        index_min: index === 0 ? 0 : AQI_BUCKETS[index - 1].max + 1,
        index_max: bucket.max,
      }));
  if (compact) {
    return (
      <div className={`aqi-legend aqi-legend--compact ${className}`}>
        <div className="aqi-legend__title"><Trans ns="aq" i18nKey="aqiLegend.text.aqi" /></div>
        <div className="aqi-legend__bar">
          {categories.map((category) => {
            const range = category.index_min != null && category.index_max != null
              ? `${category.index_min}-${category.index_max}`
              : getAirQualityIndexCategoryLabel(category.code);
            return (
              <div
                key={category.code}
                className="aqi-legend__segment"
                style={{ backgroundColor: category.color }}
                title={`${range}: ${getAirQualityIndexCategoryLabel(category.code)}`}
              >
                <span className="aqi-legend__range">{category.index_max ?? ''}</span>
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
        <span className="aqi-legend__title"><Trans ns="aq" i18nKey="aqiLegend.text.airQualityIndexAqi" /></span>
      </div>
      <div className="aqi-legend__items">
        {categories.map((category) => {
          const range = category.index_min != null && category.index_max != null
            ? `${category.index_min}-${category.index_max}`
            : '';
          return (
            <div key={category.code} className="aqi-legend__item">
              <div
                className="aqi-legend__color"
                style={{ backgroundColor: category.color }}
              />
              <div className="aqi-legend__text">
                <span className="aqi-legend__range">{range}</span>
                <span className="aqi-legend__label">{getAirQualityIndexCategoryLabel(category.code)}</span>
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
              <span className="aqi-legend__label"><Trans ns="aq" i18nKey="aqiLegend.text.noData" /></span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default AqiLegend;
