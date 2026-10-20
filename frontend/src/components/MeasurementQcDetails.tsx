import { formatMeasurementValue } from '../measurementFormatting';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchJson } from '../api';
import type { MeasurementHistoryDataPoint, MeasurementQcResponse } from '../measurementHistory';
import { checkName, failureActionLabel, settingLabel } from '../qc/presentation';

export default function MeasurementQcDetails({ sensorId, point, label, unit, context, displayPrecision }: {
  sensorId: number;
  point: MeasurementHistoryDataPoint;
  label: string;
  unit: string;
  context: string;
  displayPrecision?: number | null;
}) {
  const { t } = useTranslation('analytics');
  const [response, setResponse] = useState<MeasurementQcResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const aggregate = point.qc_provenance_status === 'source_details_unavailable';
  const load = async () => {
    if (!point.measurement_id || aggregate || loading || response) return;
    setLoading(true); setError(false);
    try {
      setResponse(await fetchJson<MeasurementQcResponse>(`/sensors/${sensorId}/measurements/${point.measurement_id}/qc`, { skipCache: true }));
    } catch { setError(true); }
    finally { setLoading(false); }
  };
  return <details onToggle={event => { if (event.currentTarget.open) void load(); }} className="max-w-xl">
    <summary className="cursor-pointer text-blue-700 rounded focus-visible:outline-2 focus-visible:outline-blue-600" aria-label={t('qc.inspectLabel', { timestamp: label })}>{t('qc.inspect')}</summary>
    <div className="space-y-2 py-2 whitespace-normal break-words">
      <p className="font-medium">{label} · {formatMeasurementValue(point.value, displayPrecision)} {unit}</p>
      {context && <p>{context}</p>}
      {!aggregate && <p>{t(point.is_valid === false ? 'qc.ineligible' : 'qc.eligible')}</p>}
      {aggregate ? <>
        <p>{t(point.invalid_sample_count ? 'qc.aggregateInvalid' : 'qc.aggregateValid')}</p>
        <p>{t('qc.sourceCounts', { valid: point.valid_sample_count ?? '—', invalid: point.invalid_sample_count ?? '—' })}</p>
        <p>{t('qc.aggregateUnavailable')}</p>
      </> : <>
        {loading && <p role="status">{t('qc.loading')}</p>}
        {error && <p role="alert">{t('qc.error')} <button type="button" className="text-blue-700 underline" onClick={() => void load()}>{t('qc.retry')}</button></p>}
        {(!point.measurement_id || response?.qc_provenance_status === 'not_recorded') && <p>{t('qc.notRecorded')}</p>}
        {response?.qc_results.map(result => <div key={result.check_code} className="border-t border-slate-200 pt-2 space-y-1">
          <p className="font-medium">{checkName(result.check_code)} · {t(result.evaluation_status === 'failed' ? 'qc.failed' : 'qc.indeterminate')}</p>
          <p>{result.message || t('qc.reasonUnavailable')}</p>
          <p>{t(result.evaluation_status === 'failed' ? 'qc.action' : 'qc.configuredAction')}: {result.failure_action ? failureActionLabel(result.failure_action) : t('qc.unavailable')}</p>
          {result.evaluation_status === 'indeterminate' && <p>{t('qc.indeterminateHelp')}</p>}
          <p>{t('qc.source')}: {t(`qc.sources.${result.rule_source || 'unavailable'}`, { defaultValue: t('qc.unavailable') })}</p>
          <details>
            <summary className="cursor-pointer text-blue-700 rounded focus-visible:outline-2 focus-visible:outline-blue-600">{t('qc.provenance')}</summary>
            <div className="space-y-1 py-2">
              <p>{t('qc.historicalOnly')}</p>
              <p>{t('qc.policyVersion')}: {result.qc_version || t('qc.unavailable')}</p>
              <p>{t('qc.pluginVersion')}: {result.plugin_version || t('qc.unavailable')}</p>
              {!result.policy_snapshot && <p>{t('qc.provenanceUnavailable')}</p>}
              {result.settings_disclosure === 'unavailable' && <p>{t('qc.settingsUnavailable')}</p>}
              {Object.entries(result.params_snapshot || {}).map(([key, value]) => <p key={key}>
                {settingLabel(result.check_code, key, key)}: {String(value)}
                {result.policy_provenance?.[`settings.${key}`]?.layer != null && <> · {t(`qc.sources.${String(result.policy_provenance[`settings.${key}`].layer)}`, { defaultValue: t('qc.unavailable') })}</>}
              </p>)}
              <p>{t('qc.technicalCodes')}: {result.check_code} · {result.reason_code || t('qc.unavailable')}</p>
              <pre className="text-xs whitespace-pre-wrap break-all">{JSON.stringify({ policy_snapshot: result.policy_snapshot, policy_provenance: result.policy_provenance, stage: result.stage, recorded_at: result.recorded_at }, null, 2)}</pre>
            </div>
          </details>
        </div>)}
      </>}
    </div>
  </details>;
}
