import { describe, expect, it } from 'vitest';
import { matchesQcFilter, measurementQcStatus } from '../measurementQc';
import type { MeasurementHistoryDataPoint, MeasurementQcResult } from '../measurementHistory';
import { getAggregationDisplayLabel } from '../aqi';
import i18n from '../i18n';

const base: MeasurementHistoryDataPoint = { timestamp: '2026-10-01T00:00:00Z', value: 99999, is_valid: true };
const flagged: MeasurementQcResult = { check_code: 'max_value', evaluation_status: 'failed', passed: false, failure_action: 'flag_for_review', reason_code: null };
const uncertain: MeasurementQcResult = { ...flagged, check_code: 'baseline_drift', evaluation_status: 'indeterminate', passed: null };

describe('persisted measurement QC semantics', () => {
  it('does not infer passed checks or failures from a value or absent history', () => {
    expect(measurementQcStatus(base)).toBe('Valid');
    expect(matchesQcFilter(base, 'flagged')).toBe(false);
    expect(matchesQcFilter(base, 'indeterminate')).toBe(false);
  });
  it('keeps review failures valid and indeterminate outcomes separate', () => {
    expect(measurementQcStatus({ ...base, qc_results: [flagged] })).toBe('Flagged for review · Valid');
    expect(measurementQcStatus({ ...base, qc_results: [uncertain] })).toBe('Valid · Unable to evaluate');
    expect(matchesQcFilter({ ...base, qc_results: [uncertain] }, 'invalid')).toBe(false);
  });
  it('retains overlapping outcomes and uses stored invalidity without inventing reasons', () => {
    const mixed = { ...base, is_valid: false, qc_results: [flagged, uncertain] };
    for (const filter of ['all', 'flagged', 'invalid', 'indeterminate'] as const) expect(matchesQcFilter(mixed, filter)).toBe(true);
    expect(measurementQcStatus(mixed)).toBe('Invalid · Unable to evaluate');
    expect(measurementQcStatus({ ...base, is_valid: false })).toBe('Invalid');
  });
  it('shares canonical aggregation labels in English and Spanish', async () => {
    expect(getAggregationDisplayLabel('2m')).toBe('2-minute');
    await i18n.changeLanguage('es');
    try {
      expect(getAggregationDisplayLabel('2m')).toBe('2 minutos');
      expect(measurementQcStatus({ ...base, qc_results: [flagged] })).toBe('Marcada para revisión · Válida');
    } finally { await i18n.changeLanguage('en'); }
  });
});
