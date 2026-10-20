import { formatOperationalTimestamp } from './utils/timezone';
import i18n, { formatDisplayNumber } from './i18n';

type DurationUnit = {
  seconds: number;
  code: 'day' | 'hour' | 'minute' | 'second';
};

const DURATION_UNITS: DurationUnit[] = [
  { seconds: 86_400, code: 'day' },
  { seconds: 3_600, code: 'hour' },
  { seconds: 60, code: 'minute' },
  { seconds: 1, code: 'second' },
];

function normalizeDurationSeconds(
  seconds: number | null | undefined,
): number | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) {
    return null;
  }
  return seconds;
}

function formatDurationNumber(value: number): string {
  return formatDisplayNumber(value, i18n.resolvedLanguage === 'es' ? 'es' : 'en', {
    maximumFractionDigits: 2,
  });
}

function durationParts(
  seconds: number | null | undefined,
): { value: number; valueLabel: string; unit: DurationUnit } | null {
  const normalizedSeconds = normalizeDurationSeconds(seconds);
  if (normalizedSeconds == null) {
    return null;
  }

  const unit = DURATION_UNITS.find(
    (candidate) => normalizedSeconds >= candidate.seconds,
  ) ?? DURATION_UNITS[DURATION_UNITS.length - 1];
  const value = normalizedSeconds / unit.seconds;

  return {
    value,
    valueLabel: formatDurationNumber(value),
    unit,
  };
}

export function formatDuration(
  seconds: number | null | undefined,
): string | null {
  const parts = durationParts(seconds);
  if (!parts) {
    return null;
  }

  return i18n.t(`devices:sensorMetadataFormatting.duration.${parts.unit.code}`, {
    count: parts.value,
    value: parts.valueLabel,
  });
}

export function formatCadence(
  seconds: number | null | undefined,
): string | null {
  const parts = durationParts(seconds);
  if (!parts) {
    return null;
  }

  return i18n.t(`devices:sensorMetadataFormatting.cadence.${parts.unit.code}`, {
    count: parts.value,
    value: parts.valueLabel,
  });
}

export function formatAverageDuration(
  seconds: number | null | undefined,
): string | null {
  const parts = durationParts(seconds);
  if (!parts) {
    return null;
  }

  return i18n.t(`devices:sensorMetadataFormatting.average.${parts.unit.code}`, {
    value: parts.valueLabel,
  });
}

export function formatMeasurementSummary(
  expectedFrequencySeconds: number | null | undefined,
  measurementDurationSeconds: number | null | undefined,
): string | null {
  const cadence = formatCadence(expectedFrequencySeconds);
  const averageDuration = formatAverageDuration(measurementDurationSeconds);
  const summaryParts: string[] = [];

  if (cadence) {
    const cadenceParts = durationParts(expectedFrequencySeconds)!;
    summaryParts.push(i18n.t(`devices:sensorMetadataFormatting.updates.${cadenceParts.unit.code}`, {
      count: cadenceParts.value,
      value: cadenceParts.valueLabel,
    }));
  }
  if (averageDuration) {
    summaryParts.push(i18n.t('devices:sensorMetadataFormatting.eachValue', {
      duration: averageDuration,
    }));
  }

  return summaryParts.length > 0 ? summaryParts.join(' · ') : null;
}

export function formatLatestReading(
  observedAt: string | null | undefined,
): string | null {
  if (!observedAt) {
    return null;
  }

  const observedDate = new Date(observedAt);
  if (Number.isNaN(observedDate.getTime())) {
    return null;
  }

  return formatOperationalTimestamp(observedAt);
}
