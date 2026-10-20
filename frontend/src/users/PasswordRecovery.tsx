import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { createResetLink, getRecoveryReadiness, sendResetEmail, type ResetLink } from './passwordResetApi';
import UsersDialog from './UsersDialog';

export default function PasswordRecovery({ userId }: { userId: string }) {
  const { t } = useTranslation('users');
  const [ready, setReady] = useState<boolean | null>(null);
  const [readinessFailed, setReadinessFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState<ResetLink | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [copyStatus, setCopyStatus] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const createButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    let active = true;
    getRecoveryReadiness().then((result) => { if (active) setReady(result.email_delivery_ready); })
      .catch(() => { if (active) { setReady(false); setReadinessFailed(true); } });
    return () => { active = false; };
  }, [userId]);
  async function generate(email: boolean) {
    setBusy(true); setError(''); setMessage(''); setCopyStatus('');
    try {
      if (email) { await sendResetEmail(userId); setMessage(t('recovery.sent')); }
      else setLink(await createResetLink(userId));
    } catch { setError(t(email ? 'recovery.sendFailed' : 'recovery.createFailed')); }
    finally { setBusy(false); }
  }
  async function copy() {
    if (!link) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('unavailable');
      await navigator.clipboard.writeText(link.reset_url);
      setCopyStatus(t('recovery.copied'));
    } catch {
      input.current?.focus(); input.current?.select(); setCopyStatus(t('recovery.copyFallback'));
    }
  }
  return <section className="card users-recovery" id="account-recovery" aria-labelledby="recovery-title">
    <h2 id="recovery-title">{t('recovery.title')}</h2>
    <p className="muted">{t('recovery.description')}</p>
    <div className="users-actions">
      <button ref={createButton} className="btn" disabled={busy} onClick={() => void generate(false)}>{t('recovery.create')}</button>
      <button className="btn" disabled={busy || ready !== true} aria-describedby={ready !== true ? 'email-unavailable' : undefined} onClick={() => void generate(true)}>{t('recovery.send')}</button>
    </div>
    {ready !== true && <div className="users-email-notice" id="email-unavailable" role="status">
      <span>{t(ready === null ? 'recovery.checking' : 'recovery.unavailable')}</span>
      <p>{t(readinessFailed ? 'recovery.readinessFailed' : 'recovery.unavailableReason')}</p>
      <Link to="/admin/email">{t('recovery.configure')}</Link>
    </div>}
    {message && <p className="success-banner" role="status">{message}</p>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {link && <UsersDialog title={t('recovery.created')} returnFocusRef={createButton} onClose={() => { setLink(null); setCopyStatus(''); }}>
      <p>{t('recovery.expiry', { count: link.expires_in_minutes })}</p>
      <label className="field"><span>{t('recovery.link')}</span><input ref={input} readOnly value={link.reset_url} onFocus={(event) => event.target.select()} /></label>
      <p className="muted">{t('recovery.bearerAdvice')}</p>
      <p role="status" aria-live="polite">{copyStatus}</p>
      <div className="users-actions">
        <button className="btn btn-primary" onClick={() => void copy()}>{t('recovery.copy')}</button>
        <button className="btn" onClick={() => { setLink(null); setCopyStatus(''); }}>{t('recovery.done')}</button>
      </div>
    </UsersDialog>}
  </section>;
}
