import type {
  AirQualityIndexCategoryMetadata,
  UsEpaCompletedDayHistoryResult,
} from './airQualityIndex';
import {
  getAirQualityIndexCategoryLabel,
  getAirQualityIndexCoverageStatusLabel,
  getExclusionReasonLabel,
} from './airQualityIndexPresentation';
import i18n from './i18n';


export const COMPLETED_DAY_HISTORY_MAXIMUM_DAY_COUNT = 366;
export type CompletedDayHistoryPreset = 7 | 30 | 90;

export interface CompletedDayHistoryDateRange {
  startLocalDate: string;
  endLocalDate: string;
}

export interface CompletedDayHistoryRangeValidation {
  error: string | null;
  inclusiveDayCount: number | null;
}

export interface CompletedDayAqiChartModel {
  labels: string[];
  calculatedValues: Array<number | null>;
  calculatedPointColors: string[];
  calculatedPointRadii: number[];
  calculatedPointHoverRadii: number[];
  unavailableValues: Array<number | null>;
  unavailablePointRadii: number[];
}

const DATE_ONLY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000;
const NEUTRAL_POINT_COLOR = '#9CA3AF';

function createUtcCalendarDate(year: number, month: number, day: number): Date {
  const date = new Date(0);
  date.setUTCHours(0, 0, 0, 0);
  date.setUTCFullYear(year, month - 1, day);
  return date;
}

function formatDateParts(year: number, month: number, day: number): string {
  return `${year.toString().padStart(4, '0')}-${month.toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}`;
}

export function parseRepresentedLocalDate(representedLocalDate: string): Date | null {
  const match = DATE_ONLY_PATTERN.exec(representedLocalDate);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = createUtcCalendarDate(year, month, day);
  if (
    date.getUTCFullYear() !== year
    || date.getUTCMonth() !== month - 1
    || date.getUTCDate() !== day
  ) {
    return null;
  }
  return date;
}

export function formatRepresentedLocalDate(
  representedLocalDate: string,
  locale?: string,
): string {
  const date = parseRepresentedLocalDate(representedLocalDate);
  if (!date) return representedLocalDate;
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}

export function addRepresentedLocalDateDays(
  representedLocalDate: string,
  dayOffset: number,
): string | null {
  const date = parseRepresentedLocalDate(representedLocalDate);
  if (!date || !Number.isInteger(dayOffset)) return null;
  date.setUTCDate(date.getUTCDate() + dayOffset);
  return formatDateParts(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
}

export function createCompletedDayPresetRange(
  endLocalDate: string,
  preset: CompletedDayHistoryPreset,
): CompletedDayHistoryDateRange | null {
  const startLocalDate = addRepresentedLocalDateDays(endLocalDate, -(preset - 1));
  if (!startLocalDate) return null;
  return { startLocalDate, endLocalDate };
}

export function validateCompletedDayHistoryRange(
  startLocalDate: string,
  endLocalDate: string,
  maximumDayCount: number = COMPLETED_DAY_HISTORY_MAXIMUM_DAY_COUNT,
): CompletedDayHistoryRangeValidation {
  const startDate = parseRepresentedLocalDate(startLocalDate);
  const endDate = parseRepresentedLocalDate(endLocalDate);
  if (!startDate || !endDate) {
    return {
      error: i18n.t('aq:completedDayPresentation.errors.invalidRange'),
      inclusiveDayCount: null,
    };
  }
  if (startDate.getTime() > endDate.getTime()) {
    return {
      error: i18n.t('aq:completedDayPresentation.errors.startAfterEnd'),
      inclusiveDayCount: null,
    };
  }
  const inclusiveDayCount = Math.round(
    (endDate.getTime() - startDate.getTime()) / MILLISECONDS_PER_DAY,
  ) + 1;
  if (inclusiveDayCount > maximumDayCount) {
    return {
      error: i18n.t('aq:completedDayPresentation.errors.rangeTooLong', { count: maximumDayCount }),
      inclusiveDayCount,
    };
  }
  return { error: null, inclusiveDayCount };
}

export function formatCompletedDayConcentration(
  result: UsEpaCompletedDayHistoryResult,
): string {
  if (result.daily_concentration == null) return i18n.t('common:states.notAvailable');
  return `${String(result.daily_concentration)}${result.normalized_unit ? ` ${result.normalized_unit}` : ''}`;
}

export function formatCompletedDayHourCounts(
  result: UsEpaCompletedDayHistoryResult,
): string {
  if (result.expected_hour_count == null) {
    return result.valid_hour_count > 0
      ? i18n.t('aq:completedDayPresentation.hourCounts.expectedUnavailable', {
          valid: result.valid_hour_count,
        })
      : i18n.t('common:states.notAvailable');
  }
  const requiredText = result.required_valid_hour_count == null
    ? i18n.t('aq:completedDayPresentation.hourCounts.requiredUnavailable')
    : i18n.t('aq:completedDayPresentation.hourCounts.required', {
        required: result.required_valid_hour_count,
      });
  return i18n.t('aq:completedDayPresentation.hourCounts.summary', {
    valid: result.valid_hour_count,
    expected: result.expected_hour_count,
    requiredText,
  });
}

export function getCompletedDayBlockingReasonLabels(
  result: UsEpaCompletedDayHistoryResult,
): string[] {
  return Array.from(new Set(result.blocking_reasons.map(getExclusionReasonLabel)));
}

export function getCompletedDayStatusLabel(result: UsEpaCompletedDayHistoryResult): string {
  if (result.calculation_status === 'calculated') {
    return result.aqi_scale_status === 'above_500'
      ? i18n.t('aq:completedDayPresentation.status.calculatedAbove500')
      : i18n.t('aq:completedDayPresentation.status.calculated');
  }
  return getCompletedDayBlockingReasonLabels(result)[0]
    ?? i18n.t('aq:completedDayPresentation.status.unavailable');
}

export function buildCompletedDayAqiChartModel(
  results: UsEpaCompletedDayHistoryResult[],
  categories: AirQualityIndexCategoryMetadata[],
  selectedRepresentedLocalDate: string | null,
): CompletedDayAqiChartModel {
  const categoryColors = new Map(categories.map((category) => [category.code, category.color]));
  return {
    labels: results.map((result) => result.represented_local_date),
    calculatedValues: results.map((result) => (
      result.calculation_status === 'calculated' ? result.numeric_value : null
    )),
    calculatedPointColors: results.map((result) => (
      result.category_code ? categoryColors.get(result.category_code) ?? NEUTRAL_POINT_COLOR : NEUTRAL_POINT_COLOR
    )),
    calculatedPointRadii: results.map((result) => (
      result.represented_local_date === selectedRepresentedLocalDate ? 6 : 4
    )),
    calculatedPointHoverRadii: results.map((result) => (
      result.represented_local_date === selectedRepresentedLocalDate ? 7 : 6
    )),
    unavailableValues: results.map((result) => (
      result.calculation_status === 'unavailable' ? 0 : null
    )),
    unavailablePointRadii: results.map((result) => (
      result.represented_local_date === selectedRepresentedLocalDate ? 7 : 5
    )),
  };
}

export function buildCompletedDayTooltipLines(
  result: UsEpaCompletedDayHistoryResult,
): string[] {
  if (result.calculation_status === 'unavailable') {
    return [
      i18n.t('aq:completedDayPresentation.status.unavailable'),
      ...getCompletedDayBlockingReasonLabels(result),
      i18n.t('aq:completedDayPresentation.tooltip.hourlyConcentrations', {
        counts: formatCompletedDayHourCounts(result),
      }),
      i18n.t('aq:completedDayPresentation.tooltip.coverage', {
        status: getAirQualityIndexCoverageStatusLabel(result.coverage_status),
      }),
    ];
  }
  const aqiText = result.numeric_value == null
    ? i18n.t('aq:completedDayPresentation.status.valueUnavailable')
    : result.category_code
      ? i18n.t('aq:completedDayPresentation.tooltip.aqiWithCategory', {
          value: result.numeric_value,
          category: getAirQualityIndexCategoryLabel(result.category_code),
        })
      : i18n.t('aq:completedDayPresentation.tooltip.aqi', { value: result.numeric_value });
  return [
    aqiText,
    i18n.t('aq:completedDayPresentation.tooltip.dailyConcentration', {
      concentration: formatCompletedDayConcentration(result),
    }),
    i18n.t('aq:completedDayPresentation.tooltip.hourlyConcentrations', {
      counts: formatCompletedDayHourCounts(result),
    }),
    i18n.t('aq:completedDayPresentation.tooltip.coverage', {
      status: getAirQualityIndexCoverageStatusLabel(result.coverage_status),
    }),
  ];
}
