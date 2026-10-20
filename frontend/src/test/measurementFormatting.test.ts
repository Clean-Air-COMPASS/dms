import { describe, expect, it } from 'vitest';
import { formatMeasurementValue } from '../measurementFormatting';

describe('measurement display strings, never scientific transformations', () => {
  it.each([
    ['native PM2.5 µg/m³', 17.1, 1, '17.1'],
    ['hourly PM2.5 µg/m³', 17.1, 1, '17.1'],
    ['daily PM2.5 µg/m³', 17, 1, '17.0'],
    ['rolling PM2.5 µg/m³', 17.141666666666666, null, '17.1416666667'],
    ['PM10 µg/m³', 17, 0, '17'],
    ['ozone ppm', 0.005, 3, '0.005'],
    ['NO₂ ppm', 1, 1, '1.0'],
    ['SO₂ ppm', 2, 1, '2.0'],
    ['CO ppm', 3, 1, '3.0'],
    ['NO ppb', 4, 1, '4.0'],
    ['NOx ppm', 0.0049, null, '0.0049'],
    ['provider PM1 µg/m³', 12.3456, null, '12.3456'],
    ['provider CO₂ ppm', 401.234, null, '401.234'],
    ['temperature °C', -0.0049, null, '-0.0049'],
    ['TVOC ppb', 0.0049, null, '0.0049'],
    ['TVOC index (not AQI)', 12.3456, null, '12.3456'],
    ['NOx index (not AQI)', 99.995, null, '99.995'],
    ['pressure hPa', 1013.251, null, '1013.251'],
    ['relative humidity %', 45.1234, null, '45.1234'],
    ['genuine zero', 0, null, '0'],
    ['negative zero', -0, null, '0'],
    ['explicit negative zero', -0, 2, '0.00'],
    ['small positive with coarse metadata', 0.0049, 2, '0.0049'],
    ['small negative with coarse metadata', -0.0049, 2, '-0.0049'],
    ['near threshold', 9.099999999, null, '9.099999999'],
    ['large, unconfigured', 999.995, null, '999.995'],
    ['large, explicit rounding', 999.995, 2, '1000.00'],
    ['tiny positive', 1e-20, null, '0.00000000000000000001'],
    ['tiny negative', -1e-20, null, '-0.00000000000000000001'],
    ['large magnitude', 1e21, null, '1000000000000000000000'],
    ['unknown precision', 12.3456, undefined, '12.3456'],
    ['invalid negative precision', 12.3456, -1, '12.3456'],
    ['invalid fractional precision', 12.3456, 1.5, '12.3456'],
    ['out of range precision', 12.3456, 101, '12.3456'],
    ['nonfinite precision', 12.3456, Infinity, '12.3456'],
  ])('%s', (_context, value, precision, expected) => {
    expect(formatMeasurementValue(value, precision, 'en')).toBe(expected);
  });
  it.each([null, undefined, NaN, Infinity, -Infinity, '17', {}])('marks unavailable input %s', value => {
    expect(formatMeasurementValue(value, 1, 'en')).toBe('—');
  });
  it('uses the requested locale without changing the input or units', () => {
    const sample = Object.freeze({ value: 17.141666666666666, unit: 'µg/m³' });
    expect(formatMeasurementValue(sample.value, null, 'es')).toBe('17,1416666667');
    expect(formatMeasurementValue(0.005, 3, 'es')).toBe('0,005');
    expect(formatMeasurementValue(-0, 1, 'es')).toBe('0,0');
    expect(formatMeasurementValue(sample.value, null, 'en')).toBe('17.1416666667');
    expect(sample).toEqual({ value: 17.141666666666666, unit: 'µg/m³' });
  });
});
