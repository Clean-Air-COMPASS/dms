import { useTranslation } from 'react-i18next';
import { formatQcNumber } from './presentation';
import type { QcPreviewResponse } from './types';

export default function QcPreviewPanel({ preview }: { preview: QcPreviewResponse }) {
  const { t } = useTranslation('qualityControl');
  const check = preview.checks[0];
  if (!check || preview.samples_available === 0) {
    return (
      <section className="qc-preview-panel qc-preview-empty" aria-live="polite">
        <h3>{t('preview.title')}</h3>
        <p>{t('preview.noMeasurements')}</p>
        <p className="qc-preview-history-note">{t('preview.historyNote')}</p>
      </section>
    );
  }

  return (
    <section className="qc-preview-panel" aria-live="polite">
      <div className="qc-preview-heading">
        <div>
          <span className="qc-eyebrow">{t('preview.eyebrow')}</span>
          <h3>{t('preview.basedOn', {
            count: preview.samples_evaluated,
            formattedCount: formatQcNumber(preview.samples_evaluated),
            hours: formatQcNumber(preview.hours),
          })}</h3>
        </div>
        {preview.truncated && (
          <span className="qc-preview-limit">
            {t('preview.truncated', { limit: formatQcNumber(preview.sample_limit) })}
          </span>
        )}
      </div>
      <div className="qc-preview-metrics">
        <div><span>{t('preview.pass')}</span><strong>{formatQcNumber(check.passed)}</strong></div>
        <div><span>{t('preview.warnings')}</span><strong>{formatQcNumber(check.would_flag)}</strong></div>
        <div><span>{t('preview.invalid')}</span><strong>{formatQcNumber(check.would_invalidate)}</strong></div>
        <div><span>{t('preview.indeterminate')}</span><strong>{formatQcNumber(check.indeterminate)}</strong></div>
      </div>
      {check.disabled_or_not_applicable > 0 && (
        <p className="qc-preview-note">
          {t('preview.notApplicable', { count: check.disabled_or_not_applicable })}
        </p>
      )}
      {check.indeterminate > 0 && <p className="warning-banner">{t('preview.indeterminateHelp')}</p>}
      <p className="qc-preview-history-note">{t('preview.historyNote')}</p>
    </section>
  );
}
