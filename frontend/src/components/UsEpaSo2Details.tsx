import { Trans } from 'react-i18next';
import i18n from '../i18n';
import type {
  DeviceAirQualityIndexResult,
  UsEpaSo2Candidate,
} from '../airQualityIndex';
import {
  getAirQualityIndexCoverageStatusLabel,
  getExclusionReasonLabel,
  formatUtcInterval,
} from '../airQualityIndexPresentation';


interface UsEpaSo2DetailsProps {
  result: DeviceAirQualityIndexResult;
}

const candidateLabel = (candidate: UsEpaSo2Candidate): string => (
  candidate.aggregation_period === '1h'
    ? i18n.t('aq:aggregation.oneHourMaximum')
    : i18n.t('aq:aggregation.twentyFourHourAverage')
);

const candidateResult = (candidate: UsEpaSo2Candidate): string => {
  if (candidate.candidate_status === 'calculated') {
    return `AQI ${candidate.numeric_value} · ${candidate.preprocessed_concentration} ${candidate.normalized_unit}`;
  }
  return getExclusionReasonLabel(candidate.exclusion_reason);
};

export default function UsEpaSo2Details({ result }: UsEpaSo2DetailsProps) {
  const oneHourCandidate = result.so2_1_hour_candidate;
  const twentyFourHourCandidate = result.so2_24_hour_candidate;
  if (!oneHourCandidate || !twentyFourHourCandidate) return null;

  const selectedCandidate = result.selected_aggregation_period === '24h'
    ? twentyFourHourCandidate
    : result.selected_aggregation_period === '1h'
      ? oneHourCandidate
      : null;
  const selectedBasis = result.selected_calculation_code === 'so2_1_hour_capped_at_200'
    ? i18n.t('aq:aggregation.oneHourMaximumCappedAtAqi200')
    : result.selected_aggregation_period === '24h'
      ? i18n.t('aq:aggregation.twentyFourHourAverage')
      : result.selected_aggregation_period === '1h'
        ? i18n.t('aq:aggregation.oneHourMaximum')
        : i18n.t('aq:usEpaSo2Details.text.noCandidateSelected');
  const selectedEvaluation = result.so2_candidate_sensor_evaluations?.find(
    (evaluation) => evaluation.sensor_id === result.sensor_id,
  );
  const representativeEvaluation = selectedEvaluation
    ?? result.so2_candidate_sensor_evaluations?.[0];

  return (
    <section className="so2-aqi-details" aria-label={i18n.t('aq:usEpaSo2Details.accessibility.sulfurDioxideAqiCalculationDetails')}>
      <dl className="so2-aqi-details__summary">
        <div><dt><Trans ns="aq" i18nKey="usEpaSo2Details.text.selectedBasis" /></dt><dd>{selectedBasis}</dd></div>
        <div>
          <dt><Trans ns="aq" i18nKey="usEpaSo2Details.text.selectedConcentration" /></dt>
          <dd>
            {selectedCandidate?.preprocessed_concentration != null
              ? `${selectedCandidate.preprocessed_concentration} ${selectedCandidate.normalized_unit}`
              : i18n.t('aq:usEpaSo2Details.text.unavailable')}
          </dd>
        </div>
        {selectedCandidate && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaSo2Details.text.selectedInterval" /></dt>
            <dd data-testid="so2-selected-interval">
              {formatUtcInterval(selectedCandidate.interval_started_at, selectedCandidate.interval_ended_at)}
            </dd>
          </div>
        )}
        <div>
          <dt><Trans ns="aq" i18nKey="usEpaSo2Details.text.evaluationCoverage" /></dt>
          <dd>
            {oneHourCandidate.valid_hour_count} {' '}<Trans ns="aq" i18nKey="usEpaSo2Details.text.of" />{' '}{oneHourCandidate.expected_hour_count}
            {' · '}{getAirQualityIndexCoverageStatusLabel(oneHourCandidate.coverage_status)}
          </dd>
        </div>
        <div><dt><Trans ns="aq" i18nKey="usEpaSo2Details.text.selectedSensor" /></dt><dd>{result.sensor_id ?? 'None'}</dd></div>
        {representativeEvaluation && (
          <div>
            <dt><Trans ns="aq" i18nKey="usEpaSo2Details.text.inputUnit" /></dt>
            <dd>
              {selectedEvaluation
                ? `${representativeEvaluation.input_unit_symbol || representativeEvaluation.input_unit_code || i18n.t('aq:common.unavailable')} → ppb`
                : representativeEvaluation.input_unit_symbol || representativeEvaluation.input_unit_code || i18n.t('aq:common.unavailable')}
            </dd>
          </div>
        )}
      </dl>

      <div className="so2-aqi-details__candidates">
        {[oneHourCandidate, twentyFourHourCandidate].map((candidate) => (
          <article
            className={`so2-aqi-candidate ${candidate === selectedCandidate ? 'so2-aqi-candidate--selected' : ''}`}
            key={candidate.aggregation_period}
          >
            <div className="so2-aqi-candidate__heading">
              <strong>{candidateLabel(candidate)}</strong>
              <span>
                {candidate.candidate_status === 'not_applicable'
                  ? i18n.t('aq:usEpaSo2Details.text.notApplicable')
                  : candidate.candidate_status}
              </span>
            </div>
            <p>{candidateResult(candidate)}</p>
            <small>
              <Trans ns="aq" i18nKey="usEpaSo2Details.text.evaluation" />{formatUtcInterval(
                candidate.evaluation_interval_started_at,
                candidate.evaluation_interval_ended_at,
              )}
            </small>
          </article>
        ))}
      </div>

      {result.selected_calculation_code === 'so2_1_hour_capped_at_200' && (
        <p className="so2-aqi-details__policy" role="note">
          <Trans ns="aq" i18nKey="usEpaSo2Details.text.epaGuidanceAssignsAqi200When" /></p>
      )}

      {!selectedEvaluation && result.exclusion_reason && (
        <p className="so2-aqi-details__availability" role="status">
          {getExclusionReasonLabel(result.exclusion_reason)}
        </p>
      )}

      <p className="so2-aqi-details__limitation">
        <Trans ns="aq" i18nKey="usEpaSo2Details.text.siteLevelInformationalResultTrailing24" /></p>
    </section>
  );
}
