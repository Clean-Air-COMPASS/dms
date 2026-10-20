import { Trans } from 'react-i18next';
import type {
  AirQualityIndexProductMetadata,
  AirQualityIndexStandardMetadata,
} from '../airQualityIndex';
import {
  categoriesWithEuropeanColors,
  EUROPEAN_AQI_UNAVAILABLE_COLOR,
  getAirQualityIndexCategoryLabel,
  getAirQualityIndexProductLabel,
  getAirQualityIndexStandardLabel,
} from '../airQualityIndexPresentation';
import i18n from '../i18n';

interface EuropeanAqiLegendProps {
  standardMetadata: AirQualityIndexStandardMetadata;
  product: AirQualityIndexProductMetadata;
}

export default function EuropeanAqiLegend({ standardMetadata, product }: EuropeanAqiLegendProps) {
  const categories = categoriesWithEuropeanColors(standardMetadata.categories);
  const standardLabel = getAirQualityIndexStandardLabel(standardMetadata.standard_code);
  const productLabel = getAirQualityIndexProductLabel(product.product_code);

  return (
    <div
      className="european-aqi-legend"
      aria-label={i18n.t('aq:europeanAqiLegend.accessibility.legend', { standard: standardLabel })}
    >
      <div className="european-aqi-legend__title">
        {i18n.t('aq:europeanAqiLegend.text.title', {
          standard: standardLabel,
          product: productLabel,
        })}
      </div>
      <div className="european-aqi-legend__items">
        {categories.map((category) => (
          <span className="european-aqi-legend__item" key={category.code}>
            <span
              className="european-aqi-legend__swatch"
              style={{ backgroundColor: category.color }}
              aria-hidden="true"
            />
            {getAirQualityIndexCategoryLabel(category.code)}
          </span>
        ))}
        <span className="european-aqi-legend__item">
          <span
            className="european-aqi-legend__swatch"
            style={{ backgroundColor: EUROPEAN_AQI_UNAVAILABLE_COLOR }}
            aria-hidden="true"
          />
          <Trans ns="aq" i18nKey="europeanAqiLegend.text.unavailable" /></span>
      </div>
    </div>
  );
}
