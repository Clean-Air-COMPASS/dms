import { Trans } from 'react-i18next';
import i18n from '../i18n';
import * as React from 'react';
import type {
  AirQualityIndexCategoryMetadata,
  UsEpaCompletedDayHistoryDeviceSeries,
  UsEpaCompletedDayHistorySummary,
} from '../airQualityIndex';
import { getUsEpaCompletedDayHistory } from '../airQualityIndex';
import {
  COMPLETED_DAY_HISTORY_MAXIMUM_DAY_COUNT,
  createCompletedDayPresetRange,
  formatCompletedDayConcentration,
  formatCompletedDayHourCounts,
  formatRepresentedLocalDate,
  getCompletedDayBlockingReasonLabels,
  getCompletedDayStatusLabel,
  validateCompletedDayHistoryRange,
  type CompletedDayHistoryDateRange,
  type CompletedDayHistoryPreset,
} from '../completedDayAqiHistory';
import {
  getAirQualityIndexAuditFlagLabel,
  getAirQualityIndexCategoryLabel,
  getAirQualityIndexCoverageStatusLabel,
} from '../airQualityIndexPresentation';
import CompletedDayAqiHistoryChart from './CompletedDayAqiHistoryChart';
import '../CompletedDayAqiHistory.css';


interface CompletedDayAqiHistoryProps {
  applicable: boolean;
  deviceId: number | null;
  productCode: string;
  productDisplayName: string;
  latestRepresentedLocalDate: string | null;
  externalApiName: string | null;
  categories: AirQualityIndexCategoryMetadata[];
}

type RangePreference = CompletedDayHistoryPreset | 'custom';

interface HistoryRequestState {
  identity: string | null;
  loading: boolean;
  response: UsEpaCompletedDayHistorySummary | null;
  error: boolean;
}

const PRESETS: CompletedDayHistoryPreset[] = [7, 30, 90];

function createRequestIdentity(
  deviceId: number,
  productCode: string,
  range: CompletedDayHistoryDateRange,
  externalApiName: string | null,
): string {
  return [
    deviceId,
    productCode,
    range.startLocalDate,
    range.endLocalDate,
    externalApiName ?? '',
  ].join('|');
}

export default function CompletedDayAqiHistory({
  applicable,
  deviceId,
  productCode,
  productDisplayName,
  latestRepresentedLocalDate,
  externalApiName,
  categories,
}: CompletedDayAqiHistoryProps) {
  const [rangePreference, setRangePreference] = React.useState<RangePreference>(30);
  const [customEditorOpen, setCustomEditorOpen] = React.useState(false);
  const [appliedCustomRange, setAppliedCustomRange] = React.useState<CompletedDayHistoryDateRange | null>(null);
  const [draftStartLocalDate, setDraftStartLocalDate] = React.useState('');
  const [draftEndLocalDate, setDraftEndLocalDate] = React.useState('');
  const [maximumDayCount, setMaximumDayCount] = React.useState(
    COMPLETED_DAY_HISTORY_MAXIMUM_DAY_COUNT,
  );
  const [retryToken, setRetryToken] = React.useState(0);
  const [selectedRepresentedLocalDate, setSelectedRepresentedLocalDate] = React.useState<string | null>(null);
  const [requestState, setRequestState] = React.useState<HistoryRequestState>({
    identity: null,
    loading: false,
    response: null,
    error: false,
  });
  const requestTokenRef = React.useRef(0);

  const appliedRange = React.useMemo<CompletedDayHistoryDateRange | null>(() => {
    if (!latestRepresentedLocalDate) return null;
    if (rangePreference === 'custom') return appliedCustomRange;
    return createCompletedDayPresetRange(latestRepresentedLocalDate, rangePreference);
  }, [appliedCustomRange, latestRepresentedLocalDate, rangePreference]);

  const requestIdentity = React.useMemo(() => {
    if (!applicable || deviceId == null || !appliedRange || !productCode) return null;
    return createRequestIdentity(deviceId, productCode, appliedRange, externalApiName);
  }, [applicable, appliedRange, deviceId, externalApiName, productCode]);

  React.useEffect(() => {
    if (!requestIdentity || deviceId == null || !appliedRange) {
      requestTokenRef.current += 1;
      setRequestState({ identity: null, loading: false, response: null, error: false });
      return;
    }

    const controller = new AbortController();
    const requestToken = requestTokenRef.current + 1;
    requestTokenRef.current = requestToken;
    setRequestState({ identity: requestIdentity, loading: true, response: null, error: false });

    getUsEpaCompletedDayHistory({
      product_code: productCode,
      start_local_date: appliedRange.startLocalDate,
      end_local_date: appliedRange.endLocalDate,
      device_id: deviceId,
      external_api_name: externalApiName,
    }, controller.signal).then((response) => {
      if (controller.signal.aborted || requestToken !== requestTokenRef.current) return;
      setMaximumDayCount(response.maximum_supported_day_count);
      setRequestState({
        identity: requestIdentity,
        loading: false,
        response,
        error: false,
      });
    }).catch((error: unknown) => {
      if (
        controller.signal.aborted
        || requestToken !== requestTokenRef.current
        || (error instanceof Error && error.name === 'AbortError')
      ) {
        return;
      }
      setRequestState({ identity: requestIdentity, loading: false, response: null, error: true });
    });

    return () => controller.abort();
  }, [appliedRange, deviceId, externalApiName, productCode, requestIdentity, retryToken]);

  const currentResponse = requestState.identity === requestIdentity ? requestState.response : null;
  const currentError = requestState.identity === requestIdentity && requestState.error;
  const currentLoading = requestIdentity != null && (
    requestState.identity !== requestIdentity || requestState.loading
  );

  const deviceSeries = React.useMemo<UsEpaCompletedDayHistoryDeviceSeries | null>(() => {
    if (!currentResponse || deviceId == null) return null;
    return currentResponse.device_series.find((series) => series.device_id === deviceId) ?? null;
  }, [currentResponse, deviceId]);

  React.useEffect(() => {
    if (!deviceSeries || deviceSeries.results.length === 0) {
      setSelectedRepresentedLocalDate(null);
      return;
    }
    setSelectedRepresentedLocalDate(
      deviceSeries.results[deviceSeries.results.length - 1].represented_local_date,
    );
  }, [deviceSeries]);

  const selectedResult = React.useMemo(() => (
    deviceSeries?.results.find(
      (result) => result.represented_local_date === selectedRepresentedLocalDate,
    ) ?? null
  ), [deviceSeries, selectedRepresentedLocalDate]);

  const draftValidation = React.useMemo(() => validateCompletedDayHistoryRange(
    draftStartLocalDate,
    draftEndLocalDate,
    maximumDayCount,
  ), [draftEndLocalDate, draftStartLocalDate, maximumDayCount]);

  const openCustomEditor = () => {
    setDraftStartLocalDate(appliedRange?.startLocalDate ?? '');
    setDraftEndLocalDate(appliedRange?.endLocalDate ?? latestRepresentedLocalDate ?? '');
    setCustomEditorOpen(true);
  };

  const applyPreset = (preset: CompletedDayHistoryPreset) => {
    setCustomEditorOpen(false);
    setRangePreference(preset);
  };

  const applyCustomRange = () => {
    if (draftValidation.error) return;
    setAppliedCustomRange({
      startLocalDate: draftStartLocalDate,
      endLocalDate: draftEndLocalDate,
    });
    setRangePreference('custom');
    setCustomEditorOpen(false);
  };

  if (!applicable) return null;

  const displayedPreference: RangePreference = customEditorOpen ? 'custom' : rangePreference;
  const allDatesUnavailable = Boolean(
    currentResponse
    && currentResponse.returned_result_count > 0
    && currentResponse.calculated_result_count === 0,
  );

  return (
    <section className="completed-day-history" aria-labelledby="completed-day-history-title">
      <div className="completed-day-history__heading">
        <div>
          <h4 id="completed-day-history-title"><Trans ns="aq" i18nKey="completedDayAqiHistory.headings.completedDayHistory" /></h4>
          <p>{productDisplayName} {' '}<Trans ns="aq" i18nKey="completedDayAqiHistory.text.representedDeviceLocalDate" /></p>
        </div>
        {appliedRange && (
          <span className="completed-day-history__range-summary">
            {appliedRange.startLocalDate}–{appliedRange.endLocalDate}
          </span>
        )}
      </div>

      <div className="completed-day-history__range-controls">
        <span className="completed-day-history__control-label"><Trans ns="aq" i18nKey="completedDayAqiHistory.text.historyRange" /></span>
        <div className="completed-day-history__presets" role="group" aria-label={i18n.t('aq:completedDayAqiHistory.accessibility.completedDayHistoryRange')}>
          {PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className="completed-day-history__preset"
              aria-pressed={displayedPreference === preset}
              disabled={!latestRepresentedLocalDate}
              onClick={() => applyPreset(preset)}
            >
              {preset} <Trans ns="aq" i18nKey="completedDayAqiHistory.actions.days" /></button>
          ))}
          <button
            type="button"
            className="completed-day-history__preset"
            aria-pressed={displayedPreference === 'custom'}
            disabled={!latestRepresentedLocalDate}
            onClick={openCustomEditor}
          >
            <Trans ns="aq" i18nKey="completedDayAqiHistory.actions.custom" /></button>
        </div>
      </div>

      {customEditorOpen && (
        <div className="completed-day-history__custom" aria-label={i18n.t('aq:completedDayAqiHistory.accessibility.customRepresentedLocalDateRange')}>
          <label>
            <span><Trans ns="aq" i18nKey="completedDayAqiHistory.text.startDate" /></span>
            <input
              type="date"
              value={draftStartLocalDate}
              aria-invalid={Boolean(draftValidation.error)}
              aria-describedby="completed-day-history-range-help completed-day-history-range-error"
              onChange={(event) => setDraftStartLocalDate(event.target.value)}
            />
          </label>
          <label>
            <span><Trans ns="aq" i18nKey="completedDayAqiHistory.text.endDate" /></span>
            <input
              type="date"
              value={draftEndLocalDate}
              aria-invalid={Boolean(draftValidation.error)}
              aria-describedby="completed-day-history-range-help completed-day-history-range-error"
              onChange={(event) => setDraftEndLocalDate(event.target.value)}
            />
          </label>
          <p id="completed-day-history-range-help" className="completed-day-history__help">
            <Trans ns="aq" i18nKey="completedDayAqiHistory.text.maximum" />{maximumDayCount} <Trans ns="aq" i18nKey="completedDayAqiHistory.text.representedLocalDaysDatesNotReordered" /></p>
          <div className="completed-day-history__custom-actions">
            <button type="button" className="btn" onClick={() => setCustomEditorOpen(false)}><Trans ns="common" i18nKey="actions.cancel" /></button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={Boolean(draftValidation.error)}
              onClick={applyCustomRange}
            >
              <Trans ns="aq" i18nKey="completedDayAqiHistory.actions.apply" /></button>
          </div>
          {draftValidation.error && (
            <p id="completed-day-history-range-error" className="completed-day-history__validation" role="alert">
              {draftValidation.error}
            </p>
          )}
        </div>
      )}

      {!latestRepresentedLocalDate && (
        <div className="completed-day-history__local-state" role="status" aria-live="polite">
          <Trans ns="aq" i18nKey="completedDayAqiHistory.text.waitingLatestRepresentedCompletedDateProduct" /></div>
      )}

      {currentLoading && (
        <div className="completed-day-history__local-state completed-day-history__loading" role="status" aria-live="polite">
          <span className="completed-day-history__loading-bar" />
          <span className="completed-day-history__loading-bar completed-day-history__loading-bar--short" />
          <span><Trans ns="aq" i18nKey="completedDayAqiHistory.text.loadingCompletedDayHistory" /></span>
        </div>
      )}

      {currentError && !currentLoading && (
        <div className="completed-day-history__local-state completed-day-history__error" role="alert">
          <strong><Trans ns="aq" i18nKey="completedDayAqiHistory.text.historicalAqiCouldNotLoaded" /></strong>
          <span><Trans ns="aq" i18nKey="completedDayAqiHistory.text.pleaseTryAgain" /></span>
          <button type="button" className="btn" onClick={() => setRetryToken((token) => token + 1)}>
            <Trans ns="common" i18nKey="actions.retry" /></button>
        </div>
      )}

      {currentResponse && !currentLoading && !currentError && !deviceSeries && (
        <div className="completed-day-history__local-state" role="status">
          <Trans ns="aq" i18nKey="completedDayAqiHistory.text.noCompletedDayHistoryWasReturned" /></div>
      )}

      {currentResponse && deviceSeries && deviceSeries.results.length === 0 && !currentLoading && (
        <div className="completed-day-history__local-state" role="status">
          <Trans ns="aq" i18nKey="completedDayAqiHistory.text.noCompletedDayHistoryWasReturned2" /></div>
      )}

      {currentResponse && deviceSeries && deviceSeries.results.length > 0 && !currentLoading && !currentError && (
        <>
          {allDatesUnavailable && (
            <div className="completed-day-history__unavailable-banner" role="status">
              <Trans ns="aq" i18nKey="completedDayAqiHistory.text.noCompletedDayAqiValuesAvailable" /></div>
          )}

          <CompletedDayAqiHistoryChart
            results={deviceSeries.results}
            categories={categories}
            selectedRepresentedLocalDate={selectedRepresentedLocalDate}
            calculatedResultCount={currentResponse.calculated_result_count}
            unavailableResultCount={currentResponse.unavailable_result_count}
            onSelectRepresentedLocalDate={setSelectedRepresentedLocalDate}
          />

          {selectedResult && (
            <article className="completed-day-history__selected" aria-labelledby="completed-day-history-selected-title">
              <div className="completed-day-history__selected-heading">
                <div>
                  <span><Trans ns="aq" i18nKey="completedDayAqiHistory.text.selectedRepresentedDate" /></span>
                  <h5 id="completed-day-history-selected-title">
                    {formatRepresentedLocalDate(selectedResult.represented_local_date)}
                  </h5>
                </div>
                <strong className={selectedResult.calculation_status === 'calculated' ? '' : 'unavailable'}>
                  {selectedResult.calculation_status === 'calculated' && selectedResult.numeric_value != null
                    ? i18n.t('aq:completedDayPresentation.tooltip.aqi', { value: selectedResult.numeric_value })
                    : i18n.t('aq:completedDayAqiHistory.text.aqiUnavailable')}
                </strong>
              </div>
              <dl className="completed-day-history__details">
                <div><dt><Trans ns="aq" i18nKey="completedDayAqiHistory.text.category" /></dt><dd>{selectedResult.category_code ? getAirQualityIndexCategoryLabel(selectedResult.category_code) : i18n.t('common:states.notAvailable')}</dd></div>
                <div><dt><Trans ns="aq" i18nKey="completedDayAqiHistory.text.dailyConcentration" /></dt><dd>{formatCompletedDayConcentration(selectedResult)}</dd></div>
                <div><dt><Trans ns="aq" i18nKey="completedDayAqiHistory.text.hourlyConcentrations" /></dt><dd>{formatCompletedDayHourCounts(selectedResult)}</dd></div>
                <div><dt><Trans ns="aq" i18nKey="completedDayAqiHistory.text.coverage" /></dt><dd>{getAirQualityIndexCoverageStatusLabel(selectedResult.coverage_status)}</dd></div>
                <div><dt><Trans ns="aq" i18nKey="completedDayAqiHistory.text.deviceTimezone" /></dt><dd>{deviceSeries.device_timezone ?? i18n.t('common:states.notAvailable')}</dd></div>
                <div><dt><Trans ns="common" i18nKey="fields.status" /></dt><dd>{getCompletedDayStatusLabel(selectedResult)}</dd></div>
              </dl>
              {selectedResult.blocking_reasons.length > 0 && (
                <div className="completed-day-history__notes">
                  <strong><Trans ns="aq" i18nKey="completedDayAqiHistory.text.whyAqiUnavailable" /></strong>
                  <ul>
                    {getCompletedDayBlockingReasonLabels(selectedResult).map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
              )}
              {selectedResult.audit_flags.length > 0 && (
                <div className="completed-day-history__notes completed-day-history__notes--audit">
                  <strong><Trans ns="aq" i18nKey="completedDayAqiHistory.text.dataQualityNotes" /></strong>
                  <ul>
                    {Array.from(new Set(selectedResult.audit_flags.map(getAirQualityIndexAuditFlagLabel))).map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </div>
              )}
            </article>
          )}

          <div className="completed-day-history__table-region" tabIndex={0} aria-label={i18n.t('aq:completedDayAqiHistory.accessibility.completedDayAqiHistoryTable')}>
            <table className="completed-day-history__table">
              <thead>
                <tr>
                  <th><Trans ns="aq" i18nKey="completedDayAqiHistory.columns.date" /></th>
                  <th><Trans ns="aq" i18nKey="completedDayAqiHistory.columns.aqi" /></th>
                  <th><Trans ns="aq" i18nKey="completedDayAqiHistory.columns.category" /></th>
                  <th><Trans ns="aq" i18nKey="completedDayAqiHistory.columns.dailyConcentration" /></th>
                  <th><Trans ns="aq" i18nKey="completedDayAqiHistory.columns.hourlyConcentrationsAvailable" /></th>
                  <th><Trans ns="common" i18nKey="fields.status" /></th>
                </tr>
              </thead>
              <tbody>
                {deviceSeries.results.map((result) => {
                  const isSelected = result.represented_local_date === selectedRepresentedLocalDate;
                  return (
                    <tr key={result.represented_local_date} className={isSelected ? 'selected' : ''}>
                      <td>
                        <button
                          type="button"
                          aria-pressed={isSelected}
                          aria-label={i18n.t('aq:completedDayAqiHistory.accessibility.selectDate', { date: formatRepresentedLocalDate(result.represented_local_date) })}
                          onClick={() => setSelectedRepresentedLocalDate(result.represented_local_date)}
                        >
                          <span>{formatRepresentedLocalDate(result.represented_local_date)}</span>
                          {isSelected && <small><Trans ns="aq" i18nKey="completedDayAqiHistory.text.selected2" /></small>}
                        </button>
                      </td>
                      <td>{result.numeric_value ?? i18n.t('common:states.unavailable')}</td>
                      <td>{result.category_code ? getAirQualityIndexCategoryLabel(result.category_code) : i18n.t('common:states.notAvailable')}</td>
                      <td>{formatCompletedDayConcentration(result)}</td>
                      <td>{formatCompletedDayHourCounts(result)}</td>
                      <td>{getCompletedDayStatusLabel(result)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
