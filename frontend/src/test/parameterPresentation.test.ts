import { afterEach, describe, expect, it } from 'vitest';

import i18n from '../i18n';
import { getParameterDisplayName } from '../parameterPresentation';

const canonicalParameterCodes = [
  'pm1', 'pm25', 'pm10', 'co2', 'temperature', 'relative_humidity',
  'pressure', 'tvoc', 'tvoc_index', 'nox_index',
] as const;

describe('canonical parameter presentation', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('has analyst-friendly English names for every AirGradient parameter', async () => {
    await i18n.changeLanguage('en');
    expect(canonicalParameterCodes.map((code) => getParameterDisplayName(code))).toEqual([
      'PM1', 'PM2.5', 'PM10', 'CO₂', 'Temperature', 'Relative humidity',
      'Pressure', 'TVOC', 'VOC Index', 'NOx Index',
    ]);
  });

  it('has analyst-friendly Spanish names without translating machine codes', async () => {
    await i18n.changeLanguage('es');
    expect(canonicalParameterCodes.map((code) => getParameterDisplayName(code))).toEqual([
      'PM1', 'PM2.5', 'PM10', 'CO₂', 'Temperatura', 'Humedad relativa',
      'Presión', 'TVOC', 'Índice de VOC', 'Índice de NOx',
    ]);
    expect(getParameterDisplayName('provider_field', 'Provider field')).toBe('Provider field');
  });
});
