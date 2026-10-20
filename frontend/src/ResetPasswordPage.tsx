import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import PasswordStrengthIndicator from './components/PasswordStrengthIndicator';
import LanguageSelector from './components/LanguageSelector';
import { submitReset } from './users/passwordResetApi';
import './users/users.css';

export default function ResetPasswordPage() {
  const { t, i18n } = useTranslation('users');
  const [token, setToken] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') || '');
  const [state, setState] = useState('checking');
  const [minimum, setMinimum] = useState(12);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    window.history.replaceState(null, '', window.location.pathname);
    let active = true;
    submitReset('verify', token).then((result) => {
      if (active) { setMinimum(result.password_min_length || 12); setState('valid'); }
    }).catch((err: Error) => { if (active) setState(['reset_expired', 'reset_used', 'reset_invalid'].includes(err.message) ? err.message : 'resetUnavailable'); });
    return () => { active = false; };
  }, [token]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('');
    if (password !== confirm) { setError(t('recovery.mismatch')); return; }
    setBusy(true);
    try { await submitReset('complete', token, password); setPassword(''); setConfirm(''); setState('success'); }
    catch (err) {
      const code = err instanceof Error ? err.message : '';
      if (['reset_expired', 'reset_used', 'reset_invalid'].includes(code)) setState(code);
      else setError(t(code === 'password_policy' ? 'recovery.policyError' : 'recovery.resetFailed', { count: minimum }));
    } finally { setBusy(false); }
  }
  // Keep the token only in this mounted page. It is never saved to storage.
  return <main className="users-reset-page"><div className="users-reset-card">
    {/* i18n-ignore: CompassAQ is the product name. */}
    <div className="users-reset-brand"><strong>CompassAQ</strong><LanguageSelector value={i18n.resolvedLanguage === 'es' ? 'es' : 'en'} onChange={(language) => { void i18n.changeLanguage(language); }} /></div>
    <h1>{t('recovery.resetTitle')}</h1>
    {state === 'checking' && <p role="status">{t('recovery.verifying')}</p>}
    {state === 'valid' && <form onSubmit={submit}>
      <p className="muted">{t('recovery.policy', { count: minimum })}</p>
      <label className="field"><span>{t('recovery.newPassword')}</span><input type="password" autoComplete="new-password" required minLength={minimum} value={password} disabled={busy} onChange={(event) => setPassword(event.target.value)} /></label>
      <PasswordStrengthIndicator password={password} showChecklist={false} />
      <label className="field"><span>{t('recovery.confirmPassword')}</span><input type="password" autoComplete="new-password" required value={confirm} disabled={busy} onChange={(event) => setConfirm(event.target.value)} /></label>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <button className="btn btn-primary" disabled={busy}>{t(busy ? 'recovery.saving' : 'recovery.resetAction')}</button>
    </form>}
    {state === 'success' && <div role="status"><h2>{t('recovery.successTitle')}</h2><p>{t('recovery.success')}</p></div>}
    {!['valid', 'checking', 'success'].includes(state) && <div role="alert"><h2>{t(state === 'reset_expired' ? 'recovery.reset_expired' : state === 'reset_used' ? 'recovery.reset_used' : state === 'reset_invalid' ? 'recovery.reset_invalid' : 'recovery.resetUnavailable')}</h2><p>{t('recovery.requestAnother')}</p></div>}
    <Link to="/login" onClick={() => setToken('')}>{t('recovery.signIn')}</Link>
  </div></main>;
}
