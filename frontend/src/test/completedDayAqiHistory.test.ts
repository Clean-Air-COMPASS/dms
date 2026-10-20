import { describe, expect, it } from 'vitest';
import type { UsEpaCompletedDayHistoryResult } from '../airQualityIndex';
import {
  addRepresentedLocalDateDays,
  buildCompletedDayAqiChartModel,
  buildCompletedDayTooltipLines,
  createCompletedDayPresetRange,
  formatCompletedDayHourCounts,
  formatRepresentedLocalDate,
  parseRepresentedLocalDate,
  validateCompletedDayHistoryRange,
} from '../completedDayAqiHistory';


function historyResult(
  representedLocalDate: string,
  overrides: Partial<UsEpaCompletedDayHistoryResult> = {},
): UsEpaCompletedDayHistoryResult {
  return {
    represented_local_date: representedLocalDate,
    local_day_started_at: null,
    local_day_ended_at: null,
    utc_window_started_at: null,
    utc_window_ended_at: null,
    expected_hour_count: 24,
    valid_hour_count: 24,
    required_valid_hour_count: 18,
    required_completeness_fraction: 0.75,
    achieved_completeness_fraction: 1,
    daily_concentration: 26.3,
    preprocessed_concentration: 26.3,
    normalized_unit: 'µg/m³',
    calculation_status: 'calculated',
    coverage_status: 'complete',
    numeric_value: 84,
    category_code: 'moderate',
    category_label: 'Moderate',
    aqi_scale_status: 'within_0_to_500',
    selected_sensor_id: 12,
    blocking_reasons: [],
    audit_flags: [],
    ...overrides,
  };
}

describe('completed-day represented local date helpers', () => {
  it('validates real date-only values and formats without a browser timezone shift', () => {
    expect(parseRepresentedLocalDate('2026-07-10')).not.toBeNull();
    expect(parseRepresentedLocalDate('2026-02-30')).toBeNull();
    expect(parseRepresentedLocalDate('2026-7-10')).toBeNull();
    expect(formatRepresentedLocalDate('2026-07-10', 'en-US')).toBe('July 10, 2026');
  });

  it('performs inclusive preset arithmetic across leap days and DST calendar dates', () => {
    expect(addRepresentedLocalDateDays('2024-03-01', -1)).toBe('2024-02-29');
    expect(createCompletedDayPresetRange('2026-07-30', 7)).toEqual({
      startLocalDate: '2026-07-24',
      endLocalDate: '2026-07-30',
    });
    expect(createCompletedDayPresetRange('2025-03-10', 7)?.startLocalDate).toBe('2025-03-04');
    expect(createCompletedDayPresetRange('2025-11-03', 7)?.startLocalDate).toBe('2025-10-28');
  });

  it('accepts 366 days and explicitly rejects missing, reversed, and 367-day ranges', () => {
    expect(validateCompletedDayHistoryRange('2024-01-01', '2024-12-31')).toEqual({
      error: null,
      inclusiveDayCount: 366,
    });
    expect(validateCompletedDayHistoryRange('2024-01-01', '2025-01-01').error)
      .toContain('cannot exceed 366');
    expect(validateCompletedDayHistoryRange('2025-01-02', '2025-01-01').error)
      .toBe('Start date must be on or before end date.');
    expect(validateCompletedDayHistoryRange('', '2025-01-01').error)
      .toBe('Choose a valid start and end represented local date.');
  });
});

describe('completed-day chart and display model', () => {
  it('preserves backend dates, creates null gaps, and uses backend category colors', () => {
    const results = [
      historyResult('2026-07-10'),
      historyResult('2026-07-12', {
        calculation_status: 'unavailable',
        numeric_value: null,
        category_code: null,
        category_label: null,
        coverage_status: 'partial',
        valid_hour_count: 17,
        blocking_reasons: ['daily_completeness_not_met'],
      }),
      historyResult('2026-07-13', {
        numeric_value: 649,
        category_code: 'hazardous',
        category_label: 'Hazardous',
        aqi_scale_status: 'above_500',
      }),
    ];
    const model = buildCompletedDayAqiChartModel(results, [
      { code: 'moderate', label: 'Moderate', internal_severity_rank: 2, color: '#FFFF00' },
      { code: 'hazardous', label: 'Hazardous', internal_severity_rank: 6, color: '#7E0023' },
    ], '2026-07-12');

    expect(model.labels).toEqual(['2026-07-10', '2026-07-12', '2026-07-13']);
    expect(model.calculatedValues).toEqual([84, null, 649]);
    expect(model.unavailableValues).toEqual([null, 0, null]);
    expect(model.calculatedPointColors).toEqual(['#FFFF00', '#9CA3AF', '#7E0023']);
    expect(model.unavailablePointRadii[1]).toBe(7);
  });

  it('builds plain-language calculated and unavailable tooltip content', () => {
    expect(buildCompletedDayTooltipLines(historyResult('2026-07-10'))).toEqual([
      'AQI 84 — Moderate',
      'Daily concentration: 26.3 µg/m³',
      'Hourly concentrations: 24 of 24 available; 18 required',
      'Coverage: Complete',
    ]);
    const unavailable = historyResult('2026-07-11', {
      calculation_status: 'unavailable',
      numeric_value: null,
      category_code: null,
      category_label: null,
      valid_hour_count: 17,
      coverage_status: 'partial',
      blocking_reasons: ['daily_completeness_not_met'],
    });
    expect(buildCompletedDayTooltipLines(unavailable)).toContain(
      'Not enough eligible hourly concentrations for the completed day',
    );
    expect(formatCompletedDayHourCounts({
      ...unavailable,
      expected_hour_count: null,
      required_valid_hour_count: null,
    })).toBe('17 available; expected count not available');
  });
});
