import { Trans } from 'react-i18next';
import i18n from '../i18n';
import type { DeviceAirQualityIndexResult } from '../airQualityIndex';
import {
  getAirQualityIndexCoverageStatusLabel,
  getExclusionReasonLabel,
  formatUtcInterval,
  getAirQualityIndexProductLabel,
} from '../airQualityIndexPresentation';


interface UsEpaGasDetailsProps {
  result: DeviceAirQualityIndexResult;
}

export default function UsEpaGasDetails({ result }: UsEpaGasDetailsProps) {
  if (result.parameter_code !== 'co' && result.parameter_code !== 'no2') return null;

  const selectedEvaluation = result.gas_candidate_sensor_evaluations?.find(
    (evaluation) => evaluation.sensor_id === result.sensor_id,
  );
  const representativeEvaluation = selectedEvaluation
    ?? result.gas_candidate_sensor_evaluations?.[0];
  const isCarbonMonoxide = result.parameter_code === 'co';
  const selectedBasis = result.selected_aggregation_period === '8h'
    ? i18n.t('aq:aggregation.eightHourAverage')
    : result.selected_aggregation_period === '1h'
      ? i18n.t('aq:aggregation.oneHourAverage')
      : i18n.t('aq:usEpaGasDetails.text.noResultSelected');
  const productLabel = getAirQualityIndexProductLabel(result.product_code ?? 'unknown');

  return (
    <section className="gas-aqi-details" aria-label={i18n.t('aq:usEpaGasDetails.accessibility.calculationDetails', { product: productLabel })}>
      <dl className="gas-aqi-details__summary">
        <div><dt><Trans ns="aq" i18nKey="usEpaGasDetails.text.selectedBasis" /></dt><dd>{selectedBasis}</dd></div>
        <div>
          <dt><Trans ns="aq" i18nKey="usEpaGasDetails.text.selectedConcentration" /></dt>
          <dd>
            {result.preprocessed_concentration != null
              ? `${result.preprocessed_concentration} ${result.normalized_unit ?? ''}`
              : i18n.t('aq:usEpaGasDetails.text.unavailable')}
          </dd>
        </div>
        {result.window_started_at && result.window_ended_at && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaGasDetails.text.selectedInterval" /></dt>
            <dd data-testid="gas-selected-interval">
              {formatUtcInterval(result.window_started_at, result.window_ended_at)}
            </dd>
          </div>
        )}
        {result.expected_observation_count != null
          && result.valid_observation_count != null && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaGasDetails.text.eligibleHours" /></dt>
            <dd>{result.valid_observation_count} {' '}<Trans ns="aq" i18nKey="usEpaGasDetails.text.of" />{' '}{result.expected_observation_count}</dd>
          </div>
        )}
        {result.calculation_status === 'calculated' && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaGasDetails.text.coverage" /></dt>
            <dd>{getAirQualityIndexCoverageStatusLabel(result.coverage_status ?? 'none')}</dd>
          </div>
        )}
        <div><dt><Trans ns="aq" i18nKey="usEpaGasDetails.text.selectedSensor" /></dt><dd>{result.sensor_id ?? i18n.t('aq:common.none')}</dd></div>
        {representativeEvaluation && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaGasDetails.text.inputUnit" /></dt>
            <dd>
              {representativeEvaluation.input_unit_symbol
                || representativeEvaluation.input_unit_code
                || i18n.t('aq:common.unavailable')}
              {selectedEvaluation && ` → ${isCarbonMonoxide ? 'ppm' : 'ppb'}`}
            </dd>
          </div>
        )}
      </dl>

      {!selectedEvaluation && result.exclusion_reason && (
        <p className="gas-aqi-details__availability" role="status">
          {getExclusionReasonLabel(result.exclusion_reason)}
        </p>
      )}

      <p className="gas-aqi-details__limitation">
        <Trans ns="aq" i18nKey="usEpaGasDetails.text.siteLevelInformationalResultCompletedUtc" /></p>
    </section>
  );
}
