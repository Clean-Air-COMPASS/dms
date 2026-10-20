import type { SupportedLanguageCode } from './languagePreferences';

export type DateTimeValue = Date | number | string;

function toDate(value: DateTimeValue): Date {
  return value instanceof Date ? value : new Date(value);
}

export function formatDisplayDate(
  value: DateTimeValue,
  languageCode: SupportedLanguageCode,
  options?: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat(languageCode, options).format(toDate(value));
}

export function formatDisplayTime(
  value: DateTimeValue,
  languageCode: SupportedLanguageCode,
  options?: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat(
    languageCode,
    options ?? { hour: 'numeric', minute: '2-digit' },
  ).format(toDate(value));
}

export function formatDisplayDateTime(
  value: DateTimeValue,
  languageCode: SupportedLanguageCode,
  options?: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat(
    languageCode,
    options ?? { dateStyle: 'medium', timeStyle: 'short' },
  ).format(toDate(value));
}

export function formatDisplayNumber(
  value: number,
  languageCode: SupportedLanguageCode,
  options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(languageCode, options).format(value);
}

export function formatDisplayList(
  values: readonly string[],
  languageCode: SupportedLanguageCode,
  options?: Intl.ListFormatOptions,
): string {
  return new Intl.ListFormat(languageCode, options).format(values);
}

export function formatRelativeTime(
  value: number,
  unit: Intl.RelativeTimeFormatUnit,
  languageCode: SupportedLanguageCode,
  options?: Intl.RelativeTimeFormatOptions,
): string {
  return new Intl.RelativeTimeFormat(languageCode, { numeric: 'auto', ...options }).format(value, unit);
}

export function formatDisplayRelativeTimeFromNow(
  value: DateTimeValue,
  now: DateTimeValue,
  languageCode: SupportedLanguageCode,
): string {
  const differenceInSeconds = (toDate(value).getTime() - toDate(now).getTime()) / 1000;
  const absoluteSeconds = Math.abs(differenceInSeconds);
  if (absoluteSeconds < 30) return formatRelativeTime(0, 'second', languageCode);
  if (absoluteSeconds < 90) {
    return formatRelativeTime(Math.sign(differenceInSeconds), 'minute', languageCode);
  }
  const differenceInMinutes = Math.round(differenceInSeconds / 60);
  if (Math.abs(differenceInMinutes) < 60) {
    return formatRelativeTime(differenceInMinutes, 'minute', languageCode);
  }
  const differenceInHours = Math.round(differenceInMinutes / 60);
  if (Math.abs(differenceInHours) < 24) {
    return formatRelativeTime(differenceInHours, 'hour', languageCode);
  }
  return formatRelativeTime(Math.round(differenceInHours / 24), 'day', languageCode);
}
