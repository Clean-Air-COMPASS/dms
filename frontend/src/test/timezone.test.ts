import { describe, it, expect, vi } from 'vitest';
import {
  timestampToInput, inputToTimestamp, formatOperationalTimestamp, resolveDisplayTimezone,
  TIMEZONE_OPTIONS,
  formatTimestamp,
  formatInTimezone,
  getTimezoneLabel,
  formatTimezoneShort,
  formatTimezoneWithOffset,
  getLocalTimezone,
} from '../utils/timezone';

describe('timezone utilities', () => {
  describe('TIMEZONE_OPTIONS', () => {
    it('should have three timezone options', () => {
      expect(TIMEZONE_OPTIONS).toHaveLength(3);
    });

    it('should have local, utc, and stream options', () => {
      const values = TIMEZONE_OPTIONS.map((opt) => opt.value);
      expect(values).toContain('local');
      expect(values).toContain('utc');
      expect(values).toContain('stream');
    });

    it('should have user-friendly labels', () => {
      const localOpt = TIMEZONE_OPTIONS.find((opt) => opt.value === 'local');
      const utcOpt = TIMEZONE_OPTIONS.find((opt) => opt.value === 'utc');
      const streamOpt = TIMEZONE_OPTIONS.find((opt) => opt.value === 'stream');

      expect(localOpt?.labelKey).toBe('analytics:timezones.userLocal');
      expect(utcOpt?.labelKey).toBe('analytics:timezones.utc');
      expect(streamOpt?.labelKey).toBe('analytics:timezones.device');
    });
  });

  describe('formatTimestamp', () => {
    const testIso = '2024-06-15T14:30:00Z';

    it('should return em dash for null timestamp', () => {
      expect(formatTimestamp(null, 'local')).toBe('—');
      expect(formatTimestamp(undefined, 'utc')).toBe('—');
      expect(formatTimestamp('', 'stream')).toBe('—');
    });

    it('should return em dash for invalid timestamp', () => {
      expect(formatTimestamp('not-a-date', 'local')).toBe('—');
    });

    it('should format in UTC mode', () => {
      const result = formatTimestamp(testIso, 'utc');
      
      expect(result).toMatch(/UTC|Coordinated Universal Time/i);
    });

    it('should format in local mode', () => {
      const result = formatTimestamp(testIso, 'local');
      
      expect(result).not.toBe('—');
      expect(result.length).toBeGreaterThan(5);
    });

    it('should format in stream mode with timezone', () => {
      const result = formatTimestamp(testIso, 'stream', 'America/New_York');
      
      expect(result).not.toBe('—');
      expect(result.length).toBeGreaterThan(5);
    });

    it('preserves the original instant when device timezone is unavailable', () => {
      const result = formatTimestamp(testIso, 'stream', null);
      
      expect(result).not.toBe('—');
      expect(result).toBe(testIso);
    });
  });

  describe('formatInTimezone', () => {
    const testDate = new Date('2024-06-15T14:30:00Z');

    it('should format date in UTC', () => {
      const result = formatInTimezone(testDate, 'UTC');
      expect(result).toMatch(/UTC/);
    });

    it('should format date in named timezone', () => {
      const result = formatInTimezone(testDate, 'America/Los_Angeles');
      
      expect(result.length).toBeGreaterThan(5);
    });

    it('should fall back gracefully for invalid timezone', () => {
      const result = formatInTimezone(testDate, 'Invalid/Timezone');
      
      expect(result).not.toBe('—');
    });
  });

  describe('getTimezoneLabel', () => {
    it('should return "UTC" for utc mode', () => {
      expect(getTimezoneLabel('utc')).toBe('UTC');
    });

    it('identifies the browser timezone', () => {
      expect(getTimezoneLabel('local')).toBe(`Browser time (${Intl.DateTimeFormat().resolvedOptions().timeZone})`);
    });

    it('should return formatted timezone for stream mode with timezone', () => {
      const result = getTimezoneLabel('stream', 'America/Los_Angeles');
      
      expect(result).toBe('America/Los_Angeles');
    });

    it('identifies original timestamps when device timezone is missing', () => {
      expect(getTimezoneLabel('stream', null)).toBe('Original timestamps');
      expect(getTimezoneLabel('stream', undefined)).toBe('Original timestamps');
    });
  });

  describe('formatTimezoneShort', () => {
    it('should extract city name from IANA timezone', () => {
      expect(formatTimezoneShort('America/Los_Angeles')).toBe('Los Angeles');
      expect(formatTimezoneShort('Europe/Paris')).toBe('Paris');
      expect(formatTimezoneShort('Asia/Tokyo')).toBe('Tokyo');
    });

    it('should handle nested timezones', () => {
      expect(formatTimezoneShort('America/Indiana/Indianapolis')).toBe('Indianapolis');
    });

    it('should replace underscores with spaces', () => {
      expect(formatTimezoneShort('America/New_York')).toBe('New York');
    });

    it('should return empty string for empty input', () => {
      expect(formatTimezoneShort('')).toBe('');
    });
  });

  describe('getLocalTimezone', () => {
    it('should return a non-empty string', () => {
      const result = getLocalTimezone();
      expect(typeof result).toBe('string');
      expect(result.length).toBeGreaterThan(0);
    });

    it('should return a valid IANA timezone format', () => {
      const result = getLocalTimezone();
      
      expect(result === 'UTC' || result.includes('/')).toBe(true);
    });

    it('uses the browser-detected America/Los_Angeles timezone when available', () => {
      const resolvedOptions = vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions')
        .mockReturnValue({ timeZone: 'America/Los_Angeles' } as Intl.ResolvedDateTimeFormatOptions);

      expect(getLocalTimezone()).toBe('America/Los_Angeles');
      resolvedOptions.mockRestore();
    });

    it('falls back to UTC when browser timezone detection fails', () => {
      const resolvedOptions = vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions')
        .mockImplementation(() => {
          throw new Error('timezone detection unavailable');
        });

      expect(getLocalTimezone()).toBe('UTC');
      resolvedOptions.mockRestore();
    });
  });

  describe('formatTimezoneWithOffset', () => {
    it('should format timezone with UTC offset', () => {
      const result = formatTimezoneWithOffset('America/Los_Angeles');
      
      expect(result).toMatch(/America\/Los_Angeles \(UTC[−+-]\d{2}:\d{2}\)/);
    });

    it('should handle UTC timezone', () => {
      const result = formatTimezoneWithOffset('UTC');
      
      expect(result).toMatch(/UTC.*\+00:00/);
    });

    it('should handle various timezone formats', () => {
      const nyResult = formatTimezoneWithOffset('America/New_York');
      expect(nyResult).toMatch(/America\/New_York \(UTC[−+-]\d{2}:\d{2}\)/);
      
      const parisResult = formatTimezoneWithOffset('Europe/Paris');
      expect(parisResult).toMatch(/Europe\/Paris \(UTC[−+-]\d{2}:\d{2}\)/);
    });

    it('should return empty string for empty input', () => {
      expect(formatTimezoneWithOffset('')).toBe('');
    });

    it('should handle invalid timezone gracefully', () => {
      const result = formatTimezoneWithOffset('Invalid/Timezone');
      
      expect(result).toBe('Invalid/Timezone');
    });
  });
});


describe('explicit instant and wall-clock conversion', () => {
  it('formats UTC without depending on the browser timezone', () => {
    expect(timestampToInput('2026-03-08T07:30:00Z', 'UTC')).toBe('2026-03-08T07:30:00');
    expect(inputToTimestamp('2026-03-08T07:30', 'UTC')).toBe('2026-03-08T07:30:00.000Z');
    expect(formatOperationalTimestamp('2026-03-08T07:30:00Z')).toContain('07:30:00 AM UTC');
  });
  it('tracks the New York spring transition and rejects nonexistent times', () => {
    expect(timestampToInput('2026-03-08T06:30:00Z', 'America/New_York')).toBe('2026-03-08T01:30:00');
    expect(timestampToInput('2026-03-08T07:30:00Z', 'America/New_York')).toBe('2026-03-08T03:30:00');
    expect(inputToTimestamp('2026-03-08T03:30', 'America/New_York')).toBe('2026-03-08T07:30:00.000Z');
    expect(() => inputToTimestamp('2026-03-08T02:30', 'America/New_York')).toThrow('invalid');
  });
  it('rejects a repeated New York clock time, but preserves an existing exact instant', () => {
    expect(() => inputToTimestamp('2026-11-01T01:30', 'America/New_York')).toThrow('ambiguous');
    for (const iso of ['2026-11-01T05:30:00.123Z', '2026-11-01T06:30:00Z']) {
      expect(inputToTimestamp('2026-11-01T01:30', 'America/New_York', iso)).toBe(iso);
    }
  });
  it('does not guess missing timezone metadata or convert date-only values', () => {
    expect(resolveDisplayTimezone('stream', 'Invalid/Zone')).toBeNull();
    expect(formatTimestamp('2026-08-01', 'utc')).toBe('2026-08-01');
    expect(formatTimestamp('2026-08-01T01:00:00', 'utc')).toBe('2026-08-01T01:00:00');
    expect(formatOperationalTimestamp('2026-08-01T01:00:00')).toContain('timezone offset missing');
    expect(formatTimestamp('2026-08-01T01:00:00Z', 'stream', 'Invalid/Zone')).toBe('2026-08-01T01:00:00Z');
  });
});
