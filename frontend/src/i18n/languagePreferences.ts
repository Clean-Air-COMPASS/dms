export const supportedLanguageCodes = ['en', 'es'] as const;

export type SupportedLanguageCode = (typeof supportedLanguageCodes)[number];

export const enabledLanguageCodes = ['en', 'es'] as const satisfies readonly SupportedLanguageCode[];

export const LANGUAGE_STORAGE_KEY = 'compassaq.language';
export const FALLBACK_LANGUAGE_CODE: SupportedLanguageCode = 'en';

export function isSupportedLanguageCode(value: unknown): value is SupportedLanguageCode {
  return typeof value === 'string' && supportedLanguageCodes.includes(value as SupportedLanguageCode);
}

export function isEnabledLanguageCode(value: unknown): value is SupportedLanguageCode {
  return isSupportedLanguageCode(value) && enabledLanguageCodes.some((code) => code === value);
}

export function normalizeBrowserLanguage(language: string | null | undefined): SupportedLanguageCode | null {
  if (!language) return null;
  const primaryLanguage = language.trim().toLowerCase().split('-')[0];
  return isSupportedLanguageCode(primaryLanguage) ? primaryLanguage : null;
}

export function readAnonymousLanguagePreference(storage: Pick<Storage, 'getItem'> | null): SupportedLanguageCode | null {
  if (!storage) return null;
  try {
    const storedLanguage = storage.getItem(LANGUAGE_STORAGE_KEY);
    return isSupportedLanguageCode(storedLanguage) ? storedLanguage : null;
  } catch {
    return null;
  }
}

export function writeAnonymousLanguagePreference(
  storage: Pick<Storage, 'setItem'> | null,
  languageCode: SupportedLanguageCode,
): void {
  if (!storage) return;
  try {
    storage.setItem(LANGUAGE_STORAGE_KEY, languageCode);
  } catch {
    // A blocked or full localStorage must not prevent login or setup.
  }
}

function firstEnabledLanguage(
  candidates: ReadonlyArray<SupportedLanguageCode | null | undefined>,
  enabledLanguages: readonly SupportedLanguageCode[],
): SupportedLanguageCode {
  for (const candidate of candidates) {
    if (candidate && enabledLanguages.includes(candidate)) return candidate;
  }
  return FALLBACK_LANGUAGE_CODE;
}

export function resolveAuthenticatedLanguage(
  preferredLanguageCode: SupportedLanguageCode | null | undefined,
  systemDefaultLanguageCode: SupportedLanguageCode | null | undefined,
  enabledLanguages: readonly SupportedLanguageCode[] = enabledLanguageCodes,
): SupportedLanguageCode {
  return firstEnabledLanguage([preferredLanguageCode, systemDefaultLanguageCode], enabledLanguages);
}

export function resolveSetupLanguage(
  anonymousLanguageCode: SupportedLanguageCode | null | undefined,
  browserLanguageCode: SupportedLanguageCode | null | undefined,
  enabledLanguages: readonly SupportedLanguageCode[] = enabledLanguageCodes,
): SupportedLanguageCode {
  return firstEnabledLanguage([anonymousLanguageCode, browserLanguageCode], enabledLanguages);
}

export function resolveAnonymousLanguage(
  anonymousLanguageCode: SupportedLanguageCode | null | undefined,
  systemDefaultLanguageCode: SupportedLanguageCode | null | undefined,
  browserLanguageCode: SupportedLanguageCode | null | undefined,
  enabledLanguages: readonly SupportedLanguageCode[] = enabledLanguageCodes,
): SupportedLanguageCode {
  return firstEnabledLanguage(
    [anonymousLanguageCode, systemDefaultLanguageCode, browserLanguageCode],
    enabledLanguages,
  );
}
