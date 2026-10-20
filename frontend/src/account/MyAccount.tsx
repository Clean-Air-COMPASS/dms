import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth';
import AdminPageLayout from '../components/AdminPageLayout';
import { refreshCurrentUser, updateCurrentUserProfile } from '../auth/authClient';
import { registerPasskey } from '../auth/passkeys';
import { accountErrorKey, changeEmail, changePassword, listPasskeys, removePasskey, type Passkey, type AccountErrorCode } from './accountApi';
import AccountLanguage from './AccountLanguage';
import SensitiveActionDialog, { type SensitiveAction } from './SensitiveActionDialog';
import '../users/users.css';
import './account.css';

export default function MyAccount() {
  const { user } = useAuth();
  const { t, i18n } = useTranslation(['auth', 'common', 'users']);
  useEffect(() => { document.title = t('account.title'); }, [t]);
  const [firstName, setFirstName] = useState(user?.first_name ?? '');
  const [lastName, setLastName] = useState(user?.last_name ?? '');
  const [profileState, setProfileState] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [profileError, setProfileError] = useState<AccountErrorCode | ''>('');
  const [passkeys, setPasskeys] = useState<Passkey[]>([]);
  const [passkeyState, setPasskeyState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [action, setAction] = useState<SensitiveAction | null>(null);
  const [success, setSuccess] = useState<SensitiveAction['kind'] | ''>('');
  useEffect(() => { setFirstName(user?.first_name ?? ''); setLastName(user?.last_name ?? ''); }, [user?.first_name, user?.last_name]);
  const loadPasskeys = useCallback(async () => {
    setPasskeyState('loading');
    try { setPasskeys((await listPasskeys()).passkeys); setPasskeyState('ready'); }
    catch { setPasskeyState('error'); }
  }, []);
  useEffect(() => { void loadPasskeys(); }, [loadPasskeys]);
  async function saveProfile(event: FormEvent) {
    event.preventDefault(); setProfileState('saving'); setProfileError('');
    try { await updateCurrentUserProfile(firstName, lastName); setProfileState('saved'); }
    catch (error) { setProfileError(accountErrorKey(error)); setProfileState('idle'); }
  }
  const open = (next: SensitiveAction) => { setSuccess(''); setAction(next); };
  const date = (value: string) => new Intl.DateTimeFormat(i18n.resolvedLanguage, { dateStyle: 'medium' }).format(new Date(value));
  if (!user) return null;
  return <AdminPageLayout title={t('account.title')} description={t('account.description')} contentClassName="account-page">
    <main className="account-workspace">
      <div className="account-column">
        <section className="card" aria-labelledby="account-profile">
          <h2 id="account-profile">{t('account.profile')}</h2>
          <p className="account-display-name">{user.display_name}</p>
          <form onSubmit={(event) => void saveProfile(event)}>
            <div className="account-name-fields">
              <label className="field"><span>{t('account.firstName')}</span><input autoComplete="given-name" maxLength={100} value={firstName} disabled={profileState === 'saving'} onChange={(event) => { setFirstName(event.target.value); setProfileState('idle'); }} /></label>
              <label className="field"><span>{t('account.lastName')}</span><input autoComplete="family-name" maxLength={100} value={lastName} disabled={profileState === 'saving'} onChange={(event) => { setLastName(event.target.value); setProfileState('idle'); }} /></label>
            </div>
            <p className="muted">{t('account.nameHelp')}</p>
            {profileError && <p role="alert" className="error-banner">{t(`account.errors.${profileError}`)}</p>}
            <div className="account-actions"><button className="btn btn-primary" disabled={profileState === 'saving'}>{t(profileState === 'saving' ? 'account.saving' : 'account.saveProfile')}</button>
              {profileState === 'saved' && <span role="status">{t('account.saved')}</span>}
            </div>
          </form>
          <div className="account-email"><div><h3>{t('account.email')}</h3><p>{user.email}</p></div><button className="btn" onClick={() => open({ kind: 'email' })}>{t('account.emailTitle')}</button></div>
        </section>
        <section className="card" aria-labelledby="account-preferences"><h2 id="account-preferences">{t('account.preferences')}</h2><AccountLanguage id="page-account-language" /></section>
      </div>
      <section className="card account-security" aria-labelledby="account-security">
        <h2 id="account-security">{t('account.security')}</h2>
        {success && <p role="status" className="account-success">{t(`account.${success}Success`)}</p>}
        <div className="account-password"><div><h3>{t('account.password')}</h3><p className="muted">{t('account.passwordHelp')}</p></div><button className="btn" onClick={() => open({ kind: 'password' })}>{t('account.passwordTitle')}</button></div>
        <div className="account-passkeys"><h3>{t('account.passkeys')}</h3><p className="muted">{t('account.passkeyHelp')}</p>
          {passkeyState === 'loading' && <p role="status">{t('account.loadingPasskeys')}</p>}
          {passkeyState === 'error' && <div role="alert"><p>{t('account.passkeyLoadError')}</p><button className="btn" onClick={() => void loadPasskeys()}>{t('common:actions.retry')}</button></div>}
          {passkeyState === 'ready' && (passkeys.length === 0 ? <p>{t('account.noPasskeys')}</p> : <ul className="account-passkey-list">{passkeys.map((key) => <li key={key.id}>
            <div><strong>{key.name || t('account.unnamed')}</strong><p className="muted">{key.created_at ? t('account.added', { date: date(key.created_at) }) : t('account.addedUnknown')}</p><p className="muted">{key.last_used_at ? t('account.lastUsed', { date: date(key.last_used_at) }) : t('account.lastUsedUnknown')}</p></div>
            <button className="btn account-remove" onClick={() => open({ kind: 'remove', passkey: key })} aria-label={t('account.removeTitle', { name: key.name || t('account.unnamed') })}>{t('account.remove')}</button>
          </li>)}</ul>)}
          <button className="btn" onClick={() => open({ kind: 'add' })}>{t('account.addTitle')}</button>
        </div>
      </section>
    </main>
    {action && <SensitiveActionDialog action={action} email={user.email} hasPasskeys={passkeys.length > 0 || user.passkey_count > 0} onClose={() => setAction(null)} onSave={async (proof, values) => {
      if (action.kind === 'email') await changeEmail(values.email, proof);
      if (action.kind === 'password') await changePassword(values.password, values.confirm, proof);
      if (action.kind === 'add') await registerPasskey(proof.accessToken, new AbortController().signal, { reauthentication_token: proof.reauthentication_token, name: values.name });
      if (action.kind === 'remove') await removePasskey(action.passkey.id, proof);
      setSuccess(action.kind);
      // List errors remain local and retryable after a successful mutation.
      await loadPasskeys();
      if (action.kind === 'add' || action.kind === 'remove') await refreshCurrentUser();
    }} />}
  </AdminPageLayout>;
}
