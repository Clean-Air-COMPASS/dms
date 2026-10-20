
import i18n, { formatDisplayDateTime, type SupportedLanguageCode } from '../i18n';


export type TimezoneMode = 'local' | 'utc' | 'stream';

type TimezoneOptionLabelKey =
  | 'analytics:timezones.userLocal'
  | 'analytics:timezones.utc'
  | 'analytics:timezones.device';

export const TIMEZONE_OPTIONS: { value: TimezoneMode; labelKey: TimezoneOptionLabelKey }[] = [
  { value: 'local', labelKey: 'analytics:timezones.userLocal' },
  { value: 'utc', labelKey: 'analytics:timezones.utc' },
  { value: 'stream', labelKey: 'analytics:timezones.device' },
];

export const PRIORITY_IANA_TIMEZONES = [
  'UTC',
  'America/Los_Angeles',
  'Asia/Manila',
  'America/Sao_Paulo',
] as const;

// This is only a compatibility fallback for runtimes without
// Intl.supportedValuesOf. It is intentionally a broad reference set, not
// the authoritative timezone list.
const FALLBACK_IANA_TIMEZONES = [
  ...PRIORITY_IANA_TIMEZONES,
  'America/Adak',
  'America/Anchorage',
  'America/Argentina/Buenos_Aires',
  'America/Bogota',
  'America/Chicago',
  'America/Denver',
  'America/Guatemala',
  'America/Halifax',
  'America/Lima',
  'America/Mexico_City',
  'America/Montevideo',
  'America/New_York',
  'America/Phoenix',
  'America/Santiago',
  'America/Toronto',
  'America/Vancouver',
  'Africa/Cairo',
  'Africa/Johannesburg',
  'Africa/Lagos',
  'Africa/Nairobi',
  'Asia/Bangkok',
  'Asia/Dubai',
  'Asia/Hong_Kong',
  'Asia/Jakarta',
  'Asia/Jerusalem',
  'Asia/Kolkata',
  'Asia/Riyadh',
  'Asia/Seoul',
  'Asia/Shanghai',
  'Asia/Singapore',
  'Asia/Taipei',
  'Asia/Tokyo',
  'Australia/Brisbane',
  'Australia/Melbourne',
  'Australia/Perth',
  'Australia/Sydney',
  'Europe/Amsterdam',
  'Europe/Berlin',
  'Europe/Dublin',
  'Europe/Istanbul',
  'Europe/Lisbon',
  'Europe/London',
  'Europe/Madrid',
  'Europe/Moscow',
  'Europe/Paris',
  'Europe/Rome',
  'Europe/Zurich',
  'Pacific/Auckland',
  'Pacific/Honolulu',
] as const;

const PRIORITY_IANA_TIMEZONE_SET = new Set<string>(PRIORITY_IANA_TIMEZONES);

export function runtimeSupportedIanaTimezones(): readonly string[] {
  const intlWithSupportedValuesOf = Intl as typeof Intl & {
    supportedValuesOf?: (key: 'timeZone') => readonly string[];
  };
  const supportedValuesOf = intlWithSupportedValuesOf.supportedValuesOf;

  if (typeof supportedValuesOf === 'function') {
    try {
      return supportedValuesOf('timeZone');
    } catch {
      // A partially implemented Intl API should use the same fallback as an older runtime.
    }
  }

  return FALLBACK_IANA_TIMEZONES;
}

export function getSelectableIanaTimezones(
  savedTimezone: string,
  availableTimezones: readonly string[] = runtimeSupportedIanaTimezones(),
): string[] {
  const timezones = new Set<string>([
    ...PRIORITY_IANA_TIMEZONES,
    ...availableTimezones,
  ]);

  // Backend validation owns the saved value. Keep it visible even when a
  // compatibility fallback list does not contain that valid IANA timezone.
  if (savedTimezone) timezones.add(savedTimezone);

  return [
    ...PRIORITY_IANA_TIMEZONES,
    ...Array.from(timezones)
      .filter((timezone) => !PRIORITY_IANA_TIMEZONE_SET.has(timezone))
      .sort((left, right) => left.localeCompare(right)),
  ];
}

export function getTimezoneOptionLabel(option: (typeof TIMEZONE_OPTIONS)[number]): string {
  return i18n.t(option.labelKey);
}

function displayLanguage(): SupportedLanguageCode {
  return i18n.resolvedLanguage === 'es' ? 'es' : 'en';
}


export function formatTimestamp(
  isoTimestamp: string | null | undefined,
  mode: TimezoneMode,
  streamTimezone?: string | null
): string {
  if (!isoTimestamp) return '—';

  const date = new Date(isoTimestamp);
  if (isNaN(date.getTime())) return '—';

  // An offset is required for instants; do not guess the meaning of naive API values.
  if (!hasTimestampOffset(isoTimestamp)) return isoTimestamp;
  const timezone = resolveDisplayTimezone(mode, streamTimezone);
  return timezone ? formatInTimezone(date, timezone) : isoTimestamp;
}


export function formatInTimezone(date: Date, timezone: string): string {
  try {
    const options: Intl.DateTimeFormatOptions = {
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZone: timezone,
      timeZoneName: 'short',
    };
    return formatDisplayDateTime(date, displayLanguage(), options);
  } catch {
    
    return date.toISOString();
  }
}


export function getTimezoneLabel(
  mode: TimezoneMode,
  streamTimezone?: string | null
): string {
  const timezone = resolveDisplayTimezone(mode, streamTimezone);
  if (!timezone) return i18n.t('analytics:timezones.originalTimestamps');
  return mode === 'local' ? i18n.t('analytics:timezones.browser', { timezone }) : timezone;
}

export function hasTimestampOffset(value: string): boolean {
  return /T.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
}

export function resolveDisplayTimezone(mode: TimezoneMode, streamTimezone?: string | null): string | null {
  const timezone = mode === 'utc' ? 'UTC' : mode === 'stream' ? streamTimezone : Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!timezone) return null;
  try {
    new Intl.DateTimeFormat('en', { timeZone: timezone });
    return timezone;
  } catch {
    return null;
  }
}

// Operational timestamps use UTC. System timezone is a scheduling/reporting setting.
export function formatOperationalTimestamp(value: string | Date | null | undefined): string {
  if (!value) return '—';
  const raw = value instanceof Date ? value.toISOString() : value;
  if (!hasTimestampOffset(raw)) return `${raw} (${i18n.t('analytics:timezones.offsetMissing')})`;
  return formatTimestamp(raw, 'utc');
}

export function formatChartTick(value: number, mode: TimezoneMode, streamTimezone?: string | null): string | string[] {
  const timezone = resolveDisplayTimezone(mode, streamTimezone);
  if (!timezone) return new Date(value).toISOString();
  // Two short lines remain readable when adjacent ticks are close on mobile.
  return [
    new Intl.DateTimeFormat(displayLanguage(), { timeZone: timezone, month: 'short', day: 'numeric' }).format(value),
    new Intl.DateTimeFormat(displayLanguage(), { timeZone: timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(value),
  ];
}

/** Wall-clock fields for a native datetime-local input, never a shifted Date instant. */
export function timestampToInput(iso: string, timezone: string): string {
  if (!iso || !hasTimestampOffset(iso) || !Number.isFinite(Date.parse(iso))) return '';
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(iso));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(item => item.type === type)!.value;
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}:${part('second')}`;
}

/** Reject DST gaps/overlaps instead of silently choosing a different instant. */
export function inputToTimestamp(value: string, timezone: string, previousIso = ''): string {
  if (!value) return '';
  const normalized = value.length === 16 ? `${value}:00` : value;
  if (previousIso && timestampToInput(previousIso, timezone) === normalized) return previousIso;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(normalized)) throw new Error('invalid');
  const wallTime = Date.parse(`${normalized}Z`);
  if (!Number.isFinite(wallTime)) throw new Error('invalid');
  // Sample both sides of a transition to discover candidate UTC offsets.
  const offsets = new Set<number>();
  for (const hours of [-36, 0, 36]) {
    const instant = wallTime + hours * 3_600_000;
    offsets.add(Date.parse(`${timestampToInput(new Date(instant).toISOString(), timezone)}Z`) - instant);
  }
  const candidates = [...offsets].map(offset => new Date(wallTime - offset).toISOString())
    .filter(iso => timestampToInput(iso, timezone) === normalized);
  if (candidates.length !== 1) throw new Error(candidates.length ? 'ambiguous' : 'invalid');
  return candidates[0];
}


export function formatTimezoneShort(timezone: string): string {
  if (!timezone) return '';
  
  const parts = timezone.split('/');
  const location = parts[parts.length - 1].replace(/_/g, ' ');
  return location;
}


export function formatTimezoneWithOffset(timezone: string): string {
  if (!timezone) return '';
  
  try {
    
    const now = new Date();
    const formatter = new Intl.DateTimeFormat(displayLanguage(), {
      timeZone: timezone,
      timeZoneName: 'shortOffset',
    });
    
    
    const parts = formatter.formatToParts(now);
    const offsetPart = parts.find(p => p.type === 'timeZoneName');
    
    if (offsetPart) {
      
      let offset = offsetPart.value;
      
      offset = offset.replace(/^GMT/, 'UTC');
      
      const match = offset.match(/UTC([+-]?)(\d+)?(?::(\d+))?$/);
      if (match) {
        const sign = match[1] || '+';
        const hours = match[2] ? match[2].padStart(2, '0') : '00';
        const minutes = match[3] ? match[3].padStart(2, '0') : '00';
        
        const displaySign = sign === '-' ? '−' : '+';
        offset = `UTC${displaySign}${hours}:${minutes}`;
      } else if (offset === 'UTC') {
        offset = 'UTC+00:00';
      }
      return `${timezone} (${offset})`;
    }
    
    
    return timezone;
  } catch {
    return timezone;
  }
}


export function getLocalTimezone(): string {
  try {
    const detectedTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!detectedTimezone) return 'UTC';

    // resolvedOptions() is the browser's suggestion, so validate it with the
    // same runtime before sending it to setup. Fixed offsets and unknown names
    // are intentionally rejected rather than persisted.
    new Intl.DateTimeFormat('en-US', { timeZone: detectedTimezone }).format();
    return detectedTimezone;
  } catch {
    return 'UTC';
  }
}
