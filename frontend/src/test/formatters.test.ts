import { describe, expect, it } from 'vitest';

import {
  formatDisplayDateTime,
  formatDisplayList,
  formatDisplayNumber,
  formatRelativeTime,
} from '../i18n';

describe('locale-aware display formatters', () => {
  it('formats numbers with locale-specific separators without changing values', () => {
    expect(formatDisplayNumber(1234.5, 'en', { minimumFractionDigits: 1 })).toBe('1,234.5');
    expect(formatDisplayNumber(1234.5, 'es', { minimumFractionDigits: 1 })).toBe('1234,5');
  });

  it('preserves an explicitly requested timezone', () => {
    const formatted = formatDisplayDateTime('2026-08-12T12:00:00Z', 'en', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
      timeZone: 'UTC',
    });
    expect(formatted).toContain('08/12/2026');
    expect(formatted).toContain('12:00');
  });

  it('formats lists and relative times by locale', () => {
    expect(formatDisplayList(['PM2.5', 'O₃'], 'en')).toBe('PM2.5 and O₃');
    expect(formatRelativeTime(-1, 'day', 'en')).toBe('yesterday');
    expect(formatDisplayList(['PM2.5', 'O₃'], 'es')).toBe('PM2.5 y O₃');
    expect(formatRelativeTime(-1, 'day', 'es')).toBe('ayer');
  });

  it('formats Spanish display dates and times without changing the requested timezone', () => {
    const formatted = formatDisplayDateTime('2026-08-12T12:00:00Z', 'es', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
      timeZone: 'UTC',
    });
    expect(formatted).toContain('12 de agosto de 2026');
    expect(formatted).toContain('12:00');
  });
});
