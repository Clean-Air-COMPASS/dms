import i18n from './i18n';
import type { MeasurementHistoryDataPoint } from './measurementHistory';

export type MeasurementQcFilter = 'all' | 'flagged' | 'invalid' | 'indeterminate';

export function isFlagged(point: MeasurementHistoryDataPoint): boolean {
  return (point.qc_results || []).some(result => result.evaluation_status === 'failed'
    && result.failure_action === 'flag_for_review');
}

export function isIndeterminate(point: MeasurementHistoryDataPoint): boolean {
  return (point.qc_results || []).some(result => result.evaluation_status === 'indeterminate');
}

export function matchesQcFilter(point: MeasurementHistoryDataPoint, filter: MeasurementQcFilter): boolean {
  return filter === 'all' || (filter === 'invalid' ? point.is_valid === false
    : filter === 'flagged' ? isFlagged(point) : isIndeterminate(point));
}

export function measurementQcStatus(point: MeasurementHistoryDataPoint): string {
  const validity = point.is_valid === false ? i18n.t('common:states.invalid')
    : isFlagged(point) ? i18n.t('analytics:qc.flaggedValid') : i18n.t('common:states.valid');
  return isIndeterminate(point) ? `${validity} · ${i18n.t('analytics:qc.indeterminate')}` : validity;
}
