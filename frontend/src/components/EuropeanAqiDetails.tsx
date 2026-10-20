import { Trans } from 'react-i18next';
import i18n, { formatDisplayRelativeTimeFromNow } from '../i18n';
import { Link } from 'react-router-dom';
import type {
  AirQualityIndexProductMetadata,
  AirQualityIndexPollutantResult,
  AirQualityIndexStandardMetadata,
  DeviceAirQualityIndexResult,
} from '../airQualityIndex';
import { buildAirQualityIndexAnalyticsPath } from '../airQualityIndex';
import {
  getEeaEuropeanStandardLabel,
  formatCompletedEuropeanAqiHour,
  formatEuropeanAqiConcentration,
  formatPollutantList,
  getAirQualityIndexCoverageStatusLabel,
  getAirQualityIndexCategoryLabel,
  getAirQualityIndexProductLabel,
  getAirQualityIndexTimeResolutionLabel,
  getEuropeanAqiDisplayedResult,
  getEuropeanAqiMarkerPresentation,
  getExclusionReasonLabel,
  getPollutantDisplayLabel,
} from '../airQualityIndexPresentation';
import { formatTimezoneWithOffset } from '../utils/timezone';
import AqiTrendCard from './AqiTrendCard';
import CopyableCoordinates from './CopyableCoordinates';
import DataSourceBadge from './DataSourceBadge';


interface EuropeanAqiDetailsProps {
  result: DeviceAirQualityIndexResult;
  standardMetadata: AirQualityIndexStandardMetadata;
  product: AirQualityIndexProductMetadata;
  onClose: () => void;
}


function formatRecency(observedAt: string): string {
  return formatDisplayRelativeTimeFromNow(
    observedAt,
    Date.now(),
    i18n.resolvedLanguage === 'es' ? 'es' : 'en',
  );
}


function formatEligiblePollutantResult(
  pollutantResult: AirQualityIndexPollutantResult,
): string {
  const displayedConcentration = pollutantResult.preprocessed_concentration
    ?? pollutantResult.normalized_concentration;
  const concentrationText = displayedConcentration == null
    ? ''
    : ` · ${formatEuropeanAqiConcentration(displayedConcentration)} ${pollutantResult.normalized_unit || ''}`;
  return `${pollutantResult.category_code
    ? getAirQualityIndexCategoryLabel(pollutantResult.category_code)
    : i18n.t('common:states.notAvailable')}${concentrationText}`;
}


export default function EuropeanAqiDetails({
  result,
  standardMetadata,
  product,
  onClose,
}: EuropeanAqiDetailsProps) {
  const presentation = getEuropeanAqiMarkerPresentation(result, standardMetadata, product);
  const displayedResult = getEuropeanAqiDisplayedResult(result, product);
  const deviceName = result.device_friendly_name
    || result.device_name
    || i18n.t('aq:europeanAqiDetails.dynamic.device', { id: result.device_id });
  const selectedParameterCode = product.parameter_code ?? result.dominant_pollutants[0] ?? null;
  const selectedProvenance = selectedParameterCode
    ? result.sensor_provenance.find(
        (provenance) => provenance.parameter_code === selectedParameterCode,
      )
    : null;
  const analyticsPath = buildAirQualityIndexAnalyticsPath({
    standard_code: standardMetadata.standard_code,
    product_code: product.product_code,
    device_id: result.device_id,
    parameter_code: selectedParameterCode,
    sensor_id: selectedProvenance?.selected_sensor_id,
    external_api_name: result.source_name,
    completed_day: false,
  });
  const unavailableReasonLabel = getExclusionReasonLabel(displayedResult.exclusionReason);

  return (
    <>
      <div className="panel-header-compact">
        <div className="panel-title-section">
          <h3 className="panel-title">{deviceName}</h3>
          <span className="panel-subtitle">{getAirQualityIndexProductLabel(product.product_code)}</span>
          {result.source_name && (
            <div className="panel-source-badge">
              <DataSourceBadge source={result.source_name} size="sm" />
            </div>
          )}
        </div>
        <button className="close-button" onClick={onClose} aria-label={i18n.t('aq:europeanAqiDetails.accessibility.closePanel')}>×</button>
      </div>
      <div className="panel-content-compact european-aqi-details">
        <div className="measurement-hero aqi-hero">
          <span className="hero-value">{presentation.categoryLabel}</span>
          <span className="hero-unit"><Trans ns="aq" i18nKey="europeanAqiDetails.text.europeanAqi" /></span>
          {presentation.isPartial && <span className="coverage-badge"><Trans ns="aq" i18nKey="europeanAqiDetails.text.partialCoverage" /></span>}
          <span className="hero-time">{formatRecency(result.observed_at)}</span>
        </div>
        {!presentation.isAvailable && (
          <p className="aqi-unavailable-message" role="status">
            {unavailableReasonLabel === i18n.t('aq:common.unavailable')
              ? i18n.t('aq:europeanAqiDetails.text.europeanAqiUnavailableInterval')
              : i18n.t('aq:europeanAqiDetails.dynamic.unavailableReason', { reason: unavailableReasonLabel })}
          </p>
        )}

        <div className="panel-chart-container">
          <AqiTrendCard
            standardMetadata={standardMetadata}
            product={product}
            deviceId={result.device_id}
            deviceName={deviceName}
            sourceName={result.source_name}
            latestObservedAt={result.observed_at}
          />
        </div>

        <details className="aqi-secondary-details">
          <summary><Trans ns="aq" i18nKey="europeanAqiDetails.text.aqiDetails" /></summary>
          <div className="aqi-secondary-details__content">
            <dl className="european-aqi-details__summary">
              <div><dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.standard" /></dt><dd>{getEeaEuropeanStandardLabel()}</dd></div>
              <div><dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.calculation" /></dt><dd>{getAirQualityIndexProductLabel(product.product_code)}</dd></div>
              {product.parameter_code && (
                <div><dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.pollutant" /></dt><dd>{getPollutantDisplayLabel(product.parameter_code)}</dd></div>
              )}
              <div><dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.averagingPeriod" /></dt><dd>{getAirQualityIndexTimeResolutionLabel(product)}</dd></div>
              <div><dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.completedHourUtc" /></dt><dd>{formatCompletedEuropeanAqiHour(result.observed_at)}</dd></div>
              {product.result_scope === 'overall' && (
                <div><dt>{i18n.t('aq:europeanAqiDetails.text.dominantPollutant', { count: result.dominant_pollutants.length })}</dt><dd>{formatPollutantList(result.dominant_pollutants)}</dd></div>
              )}
              <div>
                <dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.coverage" /></dt>
                <dd>{getAirQualityIndexCoverageStatusLabel(result.coverage.coverage_status)}</dd>
              </div>
              <div><dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.available" /></dt><dd>{formatPollutantList(result.coverage.available_pollutants)}</dd></div>
              <div><dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.missing" /></dt><dd>{formatPollutantList(result.coverage.missing_pollutants)}</dd></div>
              <div><dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.ineligible" /></dt><dd>{formatPollutantList(result.coverage.ineligible_pollutants)}</dd></div>
              <div><dt><Trans ns="aq" i18nKey="europeanAqiDetails.text.displayQualification" /></dt><dd>{result.coverage.display_qualification === 'not_evaluated' ? i18n.t('aq:europeanAqiDetails.text.notEvaluated') : result.coverage.display_qualification}</dd></div>
            </dl>
            <p className="european-aqi-details__qualification">
              <Trans ns="aq" i18nKey="europeanAqiDetails.text.compassAqHasNotEvaluatedEea" /></p>
            <details className="european-aqi-details__pollutants">
              <summary><Trans ns="aq" i18nKey="europeanAqiDetails.text.pollutantResults" />{result.pollutant_results.length})</summary>
              <ul>
                {result.pollutant_results.map((pollutantResult) => (
                  <li key={pollutantResult.parameter_code}>
                    <strong>{getPollutantDisplayLabel(pollutantResult.parameter_code)}</strong>{' '}
                    {pollutantResult.eligibility_status === 'eligible' && pollutantResult.category_label
                      ? formatEligiblePollutantResult(pollutantResult)
                      : getExclusionReasonLabel(pollutantResult.exclusion_reason)}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        </details>

        <div className="meta-row">
          <CopyableCoordinates latitude={result.latitude} longitude={result.longitude} />
          {result.device_timezone && (
            <span className="meta-timezone" title={i18n.t('aq:europeanAqiDetails.tooltips.deviceTimezone')}>
              {formatTimezoneWithOffset(result.device_timezone)}
            </span>
          )}
        </div>
        <div className="panel-actions">
          <Link className="btn btn-primary" to={analyticsPath}><Trans ns="aq" i18nKey="europeanAqiDetails.actions.openFullAnalytics" /></Link>
        </div>
      </div>
    </>
  );
}
