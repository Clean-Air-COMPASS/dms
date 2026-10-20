import { useTranslation } from 'react-i18next';
import {
  enabledLanguageCodes,
  type SupportedLanguageCode,
} from '../i18n/languagePreferences';

type LanguageSelectorProps = {
  value: SupportedLanguageCode;
  onChange: (languageCode: SupportedLanguageCode) => void;
  includeSystemDefault?: boolean;
  systemDefaultSelected?: boolean;
  onSelectSystemDefault?: () => void;
  hideWhenSingleLanguage?: boolean;
  disabled?: boolean;
  id?: string;
};

export default function LanguageSelector({
  value,
  onChange,
  includeSystemDefault = false,
  systemDefaultSelected = false,
  onSelectSystemDefault,
  hideWhenSingleLanguage = false,
  disabled = false,
  id = 'language-selector',
}: LanguageSelectorProps) {
  const { t } = useTranslation('common');

  if (hideWhenSingleLanguage
      && (enabledLanguageCodes as readonly SupportedLanguageCode[]).length === 1) return null;

  return (
    <label className="language-selector" htmlFor={id}>
      <span>{t('language.label')}</span>
      <select
        id={id}
        value={systemDefaultSelected ? 'system' : value}
        disabled={disabled}
        onChange={(event) => {
          if (event.target.value === 'system') {
            onSelectSystemDefault?.();
            return;
          }
          onChange(event.target.value as SupportedLanguageCode);
        }}
      >
        {includeSystemDefault && <option value="system">{t('language.systemDefault')}</option>}
        {enabledLanguageCodes.map((languageCode) => (
          <option key={languageCode} value={languageCode}>
            {t(`language.names.${languageCode}`)}
          </option>
        ))}
      </select>
    </label>
  );
}
