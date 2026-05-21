

export type TimezoneMode = 'local' | 'utc' | 'stream';

export const TIMEZONE_OPTIONS: { value: TimezoneMode; label: string }[] = [
  { value: 'local', label: 'User Local Time' },
  { value: 'utc', label: 'UTC' },
  { value: 'stream', label: 'Device Timezone' },
];


export function formatTimestamp(
  isoTimestamp: string | null | undefined,
  mode: TimezoneMode,
  streamTimezone?: string | null
): string {
  if (!isoTimestamp) return '—';

  const date = new Date(isoTimestamp);
  if (isNaN(date.getTime())) return '—';

  switch (mode) {
    case 'utc':
      return formatInTimezone(date, 'UTC');
    case 'stream':
      if (streamTimezone) {
        return formatInTimezone(date, streamTimezone);
      }
      
      return date.toLocaleString();
    case 'local':
    default:
      return date.toLocaleString();
  }
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
    return date.toLocaleString(undefined, options);
  } catch {
    
    return date.toLocaleString();
  }
}


export function getTimezoneLabel(
  mode: TimezoneMode,
  streamTimezone?: string | null
): string {
  switch (mode) {
    case 'utc':
      return 'UTC';
    case 'stream':
      return streamTimezone ? formatTimezoneWithOffset(streamTimezone) : 'Device TZ';
    case 'local':
    default:
      return 'Local';
  }
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
    const formatter = new Intl.DateTimeFormat('en-US', {
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
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
}
