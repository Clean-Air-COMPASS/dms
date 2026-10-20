import i18n from './i18n';

const canonicalParameterTranslationKeys = {
  pm1: 'common:parameters.pm1',
  pm25: 'common:parameters.pm25',
  pm10: 'common:parameters.pm10',
  co2: 'common:parameters.co2',
  temperature: 'common:parameters.temperature',
  relative_humidity: 'common:parameters.relative_humidity',
  pressure: 'common:parameters.pressure',
  tvoc: 'common:parameters.tvoc',
  tvoc_index: 'common:parameters.tvoc_index',
  nox_index: 'common:parameters.nox_index',
} as const;

/** Localize a canonical parameter code while preserving unknown API labels. */
export function getParameterDisplayName(
  parameterCode: string | null | undefined,
  fallbackDisplayName?: string | null,
): string {
  const normalizedCode = (parameterCode || '').trim().toLowerCase();
  if (normalizedCode in canonicalParameterTranslationKeys) {
    const canonicalCode = normalizedCode as keyof typeof canonicalParameterTranslationKeys;
    return i18n.t(canonicalParameterTranslationKeys[canonicalCode]);
  }
  const fallback = (fallbackDisplayName || '').trim();
  return fallback || normalizedCode.toUpperCase() || i18n.t('common:states.unknown');
}
