import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import UsersDialog from '../users/UsersDialog';
import PasswordStrengthIndicator from '../components/PasswordStrengthIndicator';
import { accountErrorKey, verifyIdentity, type IdentityProof, type Passkey, type AccountErrorCode } from './accountApi';

export type SensitiveAction = { kind: 'email' | 'password' | 'add' } | { kind: 'remove'; passkey: Passkey };

export default function SensitiveActionDialog({ action, email, hasPasskeys, onClose, onSave }: {
  action: SensitiveAction; email: string; hasPasskeys: boolean; onClose: () => void;
  onSave: (proof: IdentityProof, values: { email: string; password: string; confirm: string; name: string }) => Promise<void>;
}) {
  const { t } = useTranslation(['auth', 'common', 'users']);
  const [values, setValues] = useState({ email: '', password: '', confirm: '', name: '' });
  const [method, setMethod] = useState<'password' | 'passkey'>('password');
  const [currentPassword, setCurrentPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<AccountErrorCode | ''>('');
  const needsReload = error === 'account_refresh_failed';
  const title = action.kind === 'remove' ? t('account.removeTitle', { name: action.passkey.name || t('account.unnamed') }) : t(`account.${action.kind}Title`);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || needsReload) return;
    setError('');
    if (action.kind === 'password' && values.password !== values.confirm) {
      setError('password_confirmation_mismatch'); return;
    }
    setBusy(true);
    try {
      const proof = await verifyIdentity(method, currentPassword);
      setCurrentPassword('');
      await onSave(proof, values);
      onClose();
    } catch (err) { setError(accountErrorKey(err)); }
    finally { setBusy(false); }
  }
  return <UsersDialog title={title} onClose={() => { if (!busy) onClose(); }}>
    <form onSubmit={(event) => void submit(event)} className="account-sensitive-form" aria-busy={busy} aria-describedby={error ? 'account-action-error' : undefined}>
      <fieldset disabled={busy || needsReload}>
        {action.kind === 'email' && <>
          <p className="muted">{t('account.emailHelp')}</p>
          <label className="field"><span>{t('account.newEmail')}</span><input type="email" autoComplete="email" required value={values.email} onChange={(event) => setValues({ ...values, email: event.target.value })} /></label>
        </>}
        {action.kind === 'password' && <>
          <p className="muted">{t('users:recovery.policy', { count: 12 })}</p>
          <label className="field"><span>{t('users:recovery.newPassword')}</span><input type="password" autoComplete="new-password" required value={values.password} onChange={(event) => setValues({ ...values, password: event.target.value })} /></label>
          <PasswordStrengthIndicator password={values.password} email={email} showChecklist={false} />
          <label className="field"><span>{t('users:recovery.confirmPassword')}</span><input type="password" autoComplete="new-password" required value={values.confirm} onChange={(event) => setValues({ ...values, confirm: event.target.value })} /></label>
        </>}
        {action.kind === 'add' && <>
          <p className="muted">{t('account.passkeyHelp')}</p>
          <label className="field"><span>{t('account.passkeyName')}</span><input maxLength={100} value={values.name} onChange={(event) => setValues({ ...values, name: event.target.value })} /></label>
        </>}
        {action.kind === 'remove' && <p>{t('account.removeHelp')}</p>}
        <div className="account-verification">
          <h3>{t('account.verifyTitle')}</h3>
          <p className="muted">{t('account.verifyHelp')}</p>
          {hasPasskeys && <div className="account-methods">
            <label><input type="radio" name="verification" checked={method === 'password'} onChange={() => setMethod('password')} />{t('account.verifyPassword')}</label>
            <label><input type="radio" name="verification" checked={method === 'passkey'} onChange={() => { setMethod('passkey'); setCurrentPassword(''); }} />{t('account.verifyPasskey')}</label>
          </div>}
          {method === 'password' && <label className="field"><span>{t('account.currentPassword')}</span><input type="password" autoComplete="current-password" required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} aria-describedby={error === 'incorrect_current_password' ? 'account-action-error' : undefined} /></label>}
        </div>
      </fieldset>
      {error && <p id="account-action-error" role="alert" className="error-banner">{t(`account.errors.${error}`)}</p>}
      {busy && <p role="status" className="sr-only">{t('account.saving')}</p>}
      <div className="modal-actions">
        <button type="button" className="btn" disabled={busy} onClick={onClose}>{t('common:actions.cancel')}</button>
        {needsReload
          ? <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>{t('account.reload')}</button>
          : <button className={`btn ${action.kind === 'remove' ? 'btn-danger' : 'btn-primary'}`} disabled={busy}>{t(busy ? 'account.saving' : `account.${action.kind}Submit`)}</button>}
      </div>
    </form>
  </UsersDialog>;
}
