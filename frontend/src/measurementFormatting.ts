import i18n from './i18n';

const formatters = new Map<string, Intl.NumberFormat>();

/**
 * Human-readable measurement only; never use for calculations, sorting or exports.
 * Backend precision is decimal places. Without it, use the existing QC convention
 * of up to 12 significant digits, retaining small values and trimming float tails.
 * Units and scientific/product rules remain owned by the caller/backend.
 */
export function formatMeasurementValue(
  value: unknown,
  displayPrecision?: number | null,
  locale = i18n.resolvedLanguage || 'en',
): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  let precision = typeof displayPrecision === 'number'
    && Number.isInteger(displayPrecision) && displayPrecision >= 0 && displayPrecision <= 100
    ? displayPrecision : null;
  // Never present a nonzero observation as zero merely because its metadata is
  // coarser than the supplied value (e.g. native 0.0049 with two decimal places).
  if (precision !== null && value !== 0 && Math.abs(value) < 0.5 * 10 ** -precision) {
    precision = null;
  }
  const key = `${locale}:${precision ?? 'significant'}`;
  let formatter = formatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, {
      useGrouping: false,
      ...(precision === null
        ? { maximumSignificantDigits: 12 }
        : { minimumFractionDigits: precision, maximumFractionDigits: precision }),
    });
    // Bound the cache even if future callers supply arbitrary locale strings.
    if (formatters.size >= 64) formatters.clear();
    formatters.set(key, formatter);
  }
  return formatter.format(Object.is(value, -0) ? 0 : value);
}
