import { useTranslation } from 'react-i18next';
import { getAggregationDisplayLabel } from '../aqi';
import { formatDisplayDateTime } from '../i18n';

interface Props {
  resultAggregation?: string | null;
  nativeAggregation?: string | null;
  observedAt?: string | null;
  isValid?: boolean | null;
  isRolling?: boolean;
  intervalStartedAt?: string | null;
  intervalEndedAt?: string | null;
  latestSourceObservedAt?: string | null;
}

/** Present backend metadata without inferring quality or averaging from map filters. */
export default function MapMeasurementContext({ resultAggregation, nativeAggregation, observedAt, isValid, isRolling = false, intervalStartedAt, intervalEndedAt, latestSourceObservedAt }: Props) {
  const { t, i18n } = useTranslation('map');
  const aggregation = resultAggregation?.trim() || nativeAggregation?.trim();
  const renderTime = (timestamp?: string | null) => {
    const date = timestamp ? new Date(timestamp) : null;
    return date && Number.isFinite(date.getTime())
      ? <time dateTime={date.toISOString()}>{formatDisplayDateTime(date, i18n.resolvedLanguage === 'es' ? 'es' : 'en', {
        year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
        timeZone: 'UTC', timeZoneName: 'short', hourCycle: 'h23',
      })}</time> : t('measurementContext.unavailable');
  };
  return (
    <dl className="map-measurement-context">
      <div>
        <dt>{t('measurementContext.averagingPeriod')}</dt>
        <dd>{aggregation ? getAggregationDisplayLabel(aggregation) : t('measurementContext.unavailable')}</dd>
      </div>
      <div>
        <dt>{t('measurementContext.qcStatus')}</dt>
        <dd>{isValid === true ? t('mapLibreMap.tooltips.validMeasurement')
          : isValid === false ? t('mapLibreMap.tooltips.invalidMeasurement')
          : t('measurementContext.unavailable')}</dd>
      </div>
      <div>
        <dt>{t(isRolling ? 'measurementContext.calculatedAtUtc' : 'measurementContext.observedAtUtc')}</dt>
        <dd>{renderTime(observedAt)}</dd>
      </div>
      {isRolling && <>
        <div>
          <dt>{t('measurementContext.rollingWindowUtc')}</dt>
          <dd>{renderTime(intervalStartedAt)} – {renderTime(intervalEndedAt)}</dd>
        </div>
        <div>
          <dt>{t('measurementContext.latestSourceObservationUtc')}</dt>
          <dd>{renderTime(latestSourceObservedAt)}</dd>
        </div>
      </>}
    </dl>
  );
}
