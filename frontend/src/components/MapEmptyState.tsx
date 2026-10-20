import { useTranslation } from 'react-i18next';
import type { MapLayer } from '../mapLayerSelection';

export default function MapEmptyState({ layer }: { layer: MapLayer }) {
  const { t } = useTranslation('map');
  return (
    <div className="map-empty-state" role="status" aria-live="polite" data-testid="map-empty-state">
      <div className="map-empty-state__icon" aria-hidden="true">📍</div>
      <h3 className="map-empty-state__title">{t(`mapEmptyState.headings.${layer}`)}</h3>
      <p className="map-empty-state__message">{t(`mapEmptyState.messages.${layer}`)}</p>
      <p className="map-empty-state__message">{t('mapEmptyState.suggestion')}</p>
    </div>
  );
}
