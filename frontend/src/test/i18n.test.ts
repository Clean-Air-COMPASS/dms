import { afterEach, describe, expect, it } from 'vitest';

import i18n, { namespaces } from '../i18n';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('bundled i18n resources', () => {
  it('initializes i18next with every English and Spanish namespace', () => {
    expect(i18n.isInitialized).toBe(true);
    for (const namespace of namespaces) {
      expect(i18n.hasResourceBundle('en', namespace)).toBe(true);
      expect(i18n.hasResourceBundle('es', namespace)).toBe(true);
    }
  });

  it('resolves static keys and plurals in both languages', async () => {
    expect(i18n.t('common:actions.save')).toBe('Save');
    expect(i18n.t('common:counts.item', { count: 1 })).toBe('1 item');
    expect(i18n.t('common:counts.item', { count: 2 })).toBe('2 items');
    expect(i18n.t('analytics:analytics.text.dataStream', { count: 2 })).toBe('data streams');

    await i18n.changeLanguage('es');
    expect(i18n.t('common:actions.save')).toBe('Guardar');
    expect(i18n.t('common:counts.item', { count: 1 })).toBe('1 elemento');
    expect(i18n.t('common:counts.item', { count: 2 })).toBe('2 elementos');
    expect(i18n.t('analytics:analytics.text.dataStream', { count: 2 })).toBe('flujos de datos');
    expect(i18n.t('aq:europeanAqiDetails.text.dominantPollutant', { count: 2 }))
      .toBe('Contaminantes dominantes');
    expect(i18n.t('aq:aggregation.oneHourMaximum')).toBe('Máximo de 1 hora');
    expect(i18n.t('aq:aggregation.oneHourMaximumCappedAtAqi200'))
      .toBe('Máximo de 1 hora limitado a un AQI de 200');
  });

  it('falls back to English when a Spanish key is missing at runtime', async () => {
    const spanishCommon = i18n.getResourceBundle('es', 'common');
    i18n.removeResourceBundle('es', 'common');
    await i18n.changeLanguage('es');
    expect(i18n.t('common:actions.save')).toBe('Save');
    i18n.addResourceBundle('es', 'common', spanishCommon, true, true);
  });

  it('updates the document language when switching languages', async () => {
    await i18n.changeLanguage('es');
    expect(document.documentElement.lang).toBe('es');
    await i18n.changeLanguage('en');
    expect(document.documentElement.lang).toBe('en');
  });

  it('resolves an unsupported locale and document language to English', async () => {
    await i18n.changeLanguage('fr');
    expect(i18n.resolvedLanguage).toBe('en');
    expect(i18n.t('common:actions.save')).toBe('Save');
    expect(document.documentElement.lang).toBe('en');
  });
});
