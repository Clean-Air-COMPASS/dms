import { Trans } from 'react-i18next';
import i18n from '../i18n';
import type {
  DeviceAirQualityIndexResult,
  UsEpaOzoneCandidate,
} from '../airQualityIndex';
import {
  getAirQualityIndexCoverageStatusLabel,
  getExclusionReasonLabel,
  formatUtcInterval,
} from '../airQualityIndexPresentation';


interface UsEpaOzoneDetailsProps {
  result: DeviceAirQualityIndexResult;
}

const candidateLabel = (candidate: UsEpaOzoneCandidate): string => (
  candidate.aggregation_period === '8h'
    ? i18n.t('aq:aggregation.eightHourAverage')
    : i18n.t('aq:aggregation.oneHourMaximum')
);

const formatCandidateResult = (candidate: UsEpaOzoneCandidate): string => {
  if (candidate.candidate_status === 'calculated') {
    return `AQI ${candidate.numeric_value} · ${candidate.preprocessed_concentration} ${candidate.normalized_unit ?? ''}`;
  }
  return getExclusionReasonLabel(candidate.exclusion_reason);
};

export default function UsEpaOzoneDetails({ result }: UsEpaOzoneDetailsProps) {
  const eightHourCandidate = result.ozone_8_hour_candidate;
  const oneHourCandidate = result.ozone_1_hour_candidate;
  if (!eightHourCandidate || !oneHourCandidate) return null;

  const selectedBasis = result.selected_aggregation_period === '1h'
    ? i18n.t('aq:aggregation.oneHourMaximum')
    : result.selected_aggregation_period === '8h'
      ? i18n.t('aq:aggregation.eightHourAverage')
      : i18n.t('aq:usEpaOzoneDetails.text.noCandidateSelected');
  const selectedCandidate = result.selected_aggregation_period === '1h'
    ? oneHourCandidate
    : result.selected_aggregation_period === '8h'
      ? eightHourCandidate
      : null;
  const selectedSensor = result.ozone_candidate_sensor_evaluations?.find(
    (evaluation) => evaluation.sensor_id === result.sensor_id,
  );
  const representativeSensor = selectedSensor
    ?? result.ozone_candidate_sensor_evaluations?.[0];
  const sensorBlockingReason = representativeSensor?.blocking_reasons?.[0] ?? null;

  return (
    <section className="ozone-aqi-details" aria-label={i18n.t('aq:usEpaOzoneDetails.accessibility.ozoneAqiCalculationDetails')}>
      <dl className="ozone-aqi-details__summary">
        <div><dt><Trans ns="aq" i18nKey="usEpaOzoneDetails.text.selectedBasis" /></dt><dd>{selectedBasis}</dd></div>
        {selectedCandidate && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaOzoneDetails.text.selectedConcentration" /></dt>
            <dd>{selectedCandidate.preprocessed_concentration} {selectedCandidate.normalized_unit}</dd>
          </div>
        )}
        {selectedCandidate && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaOzoneDetails.text.selectedInterval" /></dt>
            <dd data-testid="ozone-selected-interval">{formatUtcInterval(selectedCandidate.interval_started_at, selectedCandidate.interval_ended_at)}</dd>
          </div>
        )}
        {selectedCandidate && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaOzoneDetails.text.selectedCoverage" /></dt>
            <dd data-testid="ozone-selected-coverage">{getAirQualityIndexCoverageStatusLabel(selectedCandidate.coverage_status)}</dd>
          </div>
        )}
        {selectedCandidate && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaOzoneDetails.text.eligibleHours" /></dt>
            <dd>{selectedCandidate.valid_hour_count} {' '}<Trans ns="aq" i18nKey="usEpaOzoneDetails.text.of" />{' '}{selectedCandidate.expected_hour_count}</dd>
          </div>
        )}
        <div><dt><Trans ns="aq" i18nKey="usEpaOzoneDetails.text.selectedSensor" /></dt><dd>{result.sensor_id ?? 'None'}</dd></div>
        {representativeSensor && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaOzoneDetails.text.inputUnit" /></dt>
            <dd>
              {selectedSensor
                ? `${representativeSensor.input_unit_symbol || representativeSensor.input_unit_code || i18n.t('aq:common.unavailable')} → ppm`
                : representativeSensor.input_unit_symbol || representativeSensor.input_unit_code || i18n.t('aq:common.unavailable')}
            </dd>
          </div>
        )}
      </dl>

      {!selectedSensor && sensorBlockingReason && (
        <p className="ozone-aqi-details__availability">
          {getExclusionReasonLabel(sensorBlockingReason)}
        </p>
      )}

      <div className="ozone-aqi-details__candidates">
        {[eightHourCandidate, oneHourCandidate].map((candidate) => (
          <article
            className={`ozone-aqi-candidate ${candidate.aggregation_period === result.selected_aggregation_period ? 'ozone-aqi-candidate--selected' : ''}`}
            key={candidate.aggregation_period}
          >
            <div className="ozone-aqi-candidate__heading">
              <strong>{candidateLabel(candidate)}</strong>
              <span>{candidate.candidate_status === 'not_applicable' ? i18n.t('aq:usEpaOzoneDetails.text.notApplicable') : candidate.candidate_status}</span>
            </div>
            <p>{formatCandidateResult(candidate)}</p>
            <small>{formatUtcInterval(candidate.interval_started_at, candidate.interval_ended_at)}</small>
            <small>
              <Trans ns="aq" i18nKey="usEpaOzoneDetails.text.coverage" />{getAirQualityIndexCoverageStatusLabel(candidate.coverage_status)}
              {' · '}{candidate.valid_hour_count} {' '}<Trans ns="aq" i18nKey="usEpaOzoneDetails.text.of2" />{' '}{candidate.expected_hour_count} <Trans ns="aq" i18nKey="usEpaOzoneDetails.text.eligibleHours2" /></small>
            {candidate.zero_substitution_used && (
              <small><Trans ns="aq" i18nKey="usEpaOzoneDetails.text.appendixUZeroSubstitutionWasUsed" /></small>
            )}
          </article>
        ))}
      </div>

      <p className="ozone-aqi-details__policy">
        <Trans ns="aq" i18nKey="usEpaOzoneDetails.text.compassAqEvaluatesApplicable8Hour" /></p>

      <p className="ozone-aqi-details__limitation">
        <Trans ns="aq" i18nKey="usEpaOzoneDetails.text.siteLevelInformationalResultNotEpa" /></p>
    </section>
  );
}
