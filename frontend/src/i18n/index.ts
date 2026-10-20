import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import {
  FALLBACK_LANGUAGE_CODE,
  normalizeBrowserLanguage,
  readAnonymousLanguagePreference,
  resolveSetupLanguage,
} from './languagePreferences';
import { namespaces, resources } from './resources';

const initialLanguage = typeof window === 'undefined'
  ? FALLBACK_LANGUAGE_CODE
  : resolveSetupLanguage(
      readAnonymousLanguagePreference(window.localStorage),
      normalizeBrowserLanguage(window.navigator.language),
    );

void i18n.use(initReactI18next).init({
  resources,
  lng: initialLanguage,
  fallbackLng: FALLBACK_LANGUAGE_CODE,
  defaultNS: 'common',
  ns: namespaces,
  initAsync: false,
  interpolation: { escapeValue: false },
  returnNull: false,
});

function updateDocumentLanguage(): void {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = i18n.resolvedLanguage ?? FALLBACK_LANGUAGE_CODE;
  }
}

updateDocumentLanguage();
i18n.on('languageChanged', updateDocumentLanguage);

export default i18n;
export * from './formatters';
export * from './languagePreferences';
export { namespaces, resources } from './resources';
