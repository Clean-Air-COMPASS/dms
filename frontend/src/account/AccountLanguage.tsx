import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth';
import LanguageSelector from '../components/LanguageSelector';
import type { SupportedLanguageCode } from '../i18n';

export default function AccountLanguage({ id }: { id: string }) {
  const { user, setPreferredLanguageCode } = useAuth();
  const { t } = useTranslation('auth');
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  async function save(language: SupportedLanguageCode | null) {
    setState('saving');
    try { await setPreferredLanguageCode(language); setState('saved'); }
    catch { setState('error'); }
  }
  if (!user) return null;
  return <div>
    <LanguageSelector id={id} value={user.preferred_language_code ?? user.system_default_language_code}
      includeSystemDefault systemDefaultSelected={user.preferred_language_code === null}
      disabled={state === 'saving'} onChange={(language) => void save(language)}
      onSelectSystemDefault={() => void save(null)} />
    {state !== 'idle' && <p role={state === 'error' ? 'alert' : 'status'} className={state === 'error' ? 'error-banner' : 'muted'}>
      {t(state === 'error' ? 'account.errors.save_failed' : `account.${state}`)}
    </p>}
  </div>;
}
