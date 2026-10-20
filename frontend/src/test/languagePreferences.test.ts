import { describe, expect, it, vi } from 'vitest';

import {
  LANGUAGE_STORAGE_KEY,
  normalizeBrowserLanguage,
  readAnonymousLanguagePreference,
  resolveAnonymousLanguage,
  resolveAuthenticatedLanguage,
  resolveSetupLanguage,
  writeAnonymousLanguagePreference,
} from '../i18n';

const bothLanguages = ['en', 'es'] as const;

describe('language preference precedence', () => {
  it('uses an authenticated user override before the system default', () => {
    expect(resolveAuthenticatedLanguage('es', 'en', bothLanguages)).toBe('es');
    expect(resolveAuthenticatedLanguage(null, 'es', bothLanguages)).toBe('es');
  });

  it('activates a previously persisted Spanish preference now that Spanish is enabled', () => {
    expect(resolveAuthenticatedLanguage('es', 'en')).toBe('es');
    expect(resolveSetupLanguage('es', 'en')).toBe('es');
  });

  it('uses local, system, then browser preferences for anonymous pages', () => {
    expect(resolveAnonymousLanguage('es', 'en', 'en', bothLanguages)).toBe('es');
    expect(resolveAnonymousLanguage(null, 'es', 'en', bothLanguages)).toBe('es');
    expect(resolveAnonymousLanguage(null, null, 'es', bothLanguages)).toBe('es');
  });

  it('uses local then browser preferences during setup without persisting detection', () => {
    expect(resolveSetupLanguage(null, 'es', bothLanguages)).toBe('es');
    expect(resolveSetupLanguage('en', 'es', bothLanguages)).toBe('en');
  });

  it('normalizes supported browser locale tags', () => {
    expect(normalizeBrowserLanguage('es-MX')).toBe('es');
    expect(normalizeBrowserLanguage('en-US')).toBe('en');
    expect(normalizeBrowserLanguage('fr-FR')).toBeNull();
  });

  it('falls back to English when no enabled preference is available', () => {
    expect(resolveAuthenticatedLanguage(null, null)).toBe('en');
    expect(resolveAnonymousLanguage(null, null, null)).toBe('en');
  });
});

describe('anonymous language persistence', () => {
  it('reads and writes only explicit supported codes', () => {
    const storage = {
      getItem: vi.fn().mockReturnValue('es'),
      setItem: vi.fn(),
    };
    expect(readAnonymousLanguagePreference(storage)).toBe('es');
    writeAnonymousLanguagePreference(storage, 'en');
    expect(storage.setItem).toHaveBeenCalledWith(LANGUAGE_STORAGE_KEY, 'en');
  });

  it('ignores invalid and inaccessible storage', () => {
    expect(readAnonymousLanguagePreference({ getItem: () => 'fr' })).toBeNull();
    expect(readAnonymousLanguagePreference({ getItem: () => { throw new Error('blocked'); } })).toBeNull();
    expect(() => writeAnonymousLanguagePreference({ setItem: () => { throw new Error('blocked'); } }, 'en')).not.toThrow();
  });
});
