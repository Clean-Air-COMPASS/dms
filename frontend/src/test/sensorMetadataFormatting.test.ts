import { describe, expect, it } from 'vitest';
import {
  formatAverageDuration,
  formatCadence,
  formatDuration,
  formatMeasurementSummary,
} from '../sensorMetadataFormatting';

describe('sensor metadata duration formatting', () => {
  it.each([
    [60, '1 minute'],
    [120, '2 minutes'],
    [300, '5 minutes'],
    [3_600, '1 hour'],
    [7_200, '2 hours'],
    [86_400, '1 day'],
  ])('formats %i seconds as %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });

  it('uses raw seconds only for durations under one minute', () => {
    expect(formatDuration(30)).toBe('30 seconds');
    expect(formatDuration(90)).toBe('1.5 minutes');
  });

  it.each([
    [120, 'Every 2 minutes'],
    [3_600, 'Every hour'],
    [7_200, 'Every 2 hours'],
  ])('formats cadence for %i seconds as %s', (seconds, expected) => {
    expect(formatCadence(seconds)).toBe(expected);
  });

  it.each([
    [120, '2-minute average'],
    [3_600, '1-hour average'],
  ])('formats represented duration for %i seconds as %s', (seconds, expected) => {
    expect(formatAverageDuration(seconds)).toBe(expected);
  });

  it('combines cadence and represented duration into one concise summary', () => {
    expect(formatMeasurementSummary(60, 300)).toBe(
      'Updates every minute · Each value is a 5-minute average',
    );
  });

  it('omits invalid or missing durations', () => {
    expect(formatDuration(null)).toBeNull();
    expect(formatCadence(0)).toBeNull();
    expect(formatAverageDuration(Number.NaN)).toBeNull();
    expect(formatMeasurementSummary(null, undefined)).toBeNull();
  });
});
