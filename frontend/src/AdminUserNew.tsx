import { roleLabel, roleDescription } from './rolePresentation';
import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createUser, listRoles, type RoleRecord } from './api';
import AdminPageLayout from './components/AdminPageLayout';
import PasswordStrengthIndicator from './components/PasswordStrengthIndicator';
import './users/users.css';


export default function AdminUserNew() {
  const navigate = useNavigate();

  const [availableRoles, setAvailableRoles] = useState<RoleRecord[]>([]);
  const [loadingRoles, setLoadingRoles] = useState<boolean>(true);

  
  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');
  const [selectedRoles, setSelectedRoles] = useState<Set<string>>(new Set());
  const [isActive, setIsActive] = useState<boolean>(true);

  
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const roles = await listRoles();
        if (!cancelled) {
          setAvailableRoles(roles);
        }
      } catch {
        if (!cancelled) setError(i18n.t('users:recovery.rolesLoadFailed'));
      } finally {
        if (!cancelled) {
          setLoadingRoles(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  
  const validateEmail = (value: string): boolean => {
    if (!value.trim()) {
      setEmailError(i18n.t('users:adminUserNew.messages.emailRequired'));
      return false;
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(value)) {
      setEmailError(i18n.t('users:adminUserNew.messages.invalidEmailFormat'));
      return false;
    }
    setEmailError(null);
    return true;
  };

  
  const validatePassword = (): boolean => {
    if (!password) {
      setPasswordError(i18n.t('users:adminUserNew.messages.passwordRequired'));
      return false;
    }
    if (password.length < 12) {
      setPasswordError(i18n.t('users:recovery.policy', { count: 12 }));
      return false;
    }
    if (password !== confirmPassword) {
      setPasswordError(i18n.t('users:adminUserNew.messages.passwordsDoNotMatch'));
      return false;
    }
    setPasswordError(null);
    return true;
  };

  
  const handleRoleToggle = (roleName: string) => {
    setSelectedRoles((prev) => {
      const next = new Set(prev);
      if (next.has(roleName)) {
        next.delete(roleName);
      } else {
        next.add(roleName);
      }
      return next;
    });
  };

  
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    
    const emailValid = validateEmail(email);
    const passwordValid = validatePassword();

    if (!emailValid || !passwordValid) {
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const newUser = await createUser({
        email: email.trim().toLowerCase(),
        password,
        roles: Array.from(selectedRoles),
        is_active: isActive,
      });
      
      navigate(`/admin/users/${newUser.user_id}`, { replace: true });
    } catch {
      const message = i18n.t('common:errors.createUser');
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AdminPageLayout
      title={i18n.t('users:adminUserNew.tooltips.createNewUser')}
      description={i18n.t('users:adminUserNew.accessibility.addNewUserAccountSystem')}
      breadcrumbs={[
        { label: i18n.t('users:adminUserNew.content.admin'), to: '/admin' },
        { label: i18n.t('users:adminUserNew.content.users'), to: '/admin/users' },
        { label: i18n.t('users:adminUserNew.content.newUser') },
      ]}
      contentClassName="user-new-page"
    >
      {error && <div className="error-banner" role="alert">{error}</div>}

      <form onSubmit={handleSubmit} className="users-create-form">
        <div className="users-create-grid">
        
          <div className="card users-create-identity">
            <h2><Trans ns="users" i18nKey="adminUserNew.headings.accountDetails" /></h2>

            <div className="form-group">
              <label className="field">
                <span>
                  <Trans ns="common" i18nKey="fields.email" /><span className="required">*</span>
                </span>
                <input
                  type="email"
                  required
                  aria-invalid={!!emailError}
                  aria-describedby={emailError ? 'new-user-email-error' : undefined}
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    if (emailError) validateEmail(e.target.value);
                  }}
                  onBlur={() => validateEmail(email)}
                  placeholder={i18n.t('users:adminUserNew.placeholders.userExampleCom')}
                  disabled={submitting}
                  autoComplete="off"
                />
                {emailError && <span className="field-error" id="new-user-email-error" role="alert">{emailError}</span>}
              </label>
            </div>

            <div className="form-group">
              <label className="field">
                <span>
                  <Trans ns="common" i18nKey="fields.password" /><span className="required">*</span>
                </span>
                <input
                  type="password"
                  required
                  aria-invalid={!!passwordError}
                  aria-describedby="new-user-password-policy"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (passwordError) setPasswordError(null);
                  }}
                  placeholder={i18n.t('users:recovery.newPassword')}
                  disabled={submitting}
                  autoComplete="new-password"
                />
              </label>
            </div>

            <p className="muted users-password-guidance" id="new-user-password-policy">{i18n.t('users:recovery.policy', { count: 12 })}</p>
            <PasswordStrengthIndicator password={password} email={email} showChecklist={false} />
            <div className="form-group">
              <label className="field">
                <span>
                  <Trans ns="users" i18nKey="adminUserNew.text.confirmPassword" /><span className="required">*</span>
                </span>
                <input
                  type="password"
                  required
                  value={confirmPassword}
                  onChange={(e) => {
                    setConfirmPassword(e.target.value);
                    if (passwordError) setPasswordError(null);
                  }}
                  onBlur={validatePassword}
                  placeholder={i18n.t('users:adminUserNew.placeholders.reEnterPassword')}
                  disabled={submitting}
                  autoComplete="new-password"
                />
                {passwordError && <span className="field-error" role="alert">{passwordError}</span>}
              </label>
            </div>
          </div>


          <div className="users-create-access">
            <div className="card">
              <h2><Trans ns="users" i18nKey="adminUserNew.headings.initialStatus" /></h2>
              <label className="status-toggle">
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                  disabled={submitting}
                />
                <div>
                  <strong><Trans ns="users" i18nKey="adminUserNew.text.active" /></strong>
                  <span className="muted">
                    {isActive
                      ? i18n.t('users:adminUserNew.text.userWillAbleLogImmediatelyAfter')
                      : i18n.t('users:adminUserNew.text.userWillCreatedButCannotLog')}
                  </span>
                </div>
              </label>
            </div>


            <div className="card">
              <h2><Trans ns="users" i18nKey="adminUserNew.headings.initialRoles" /></h2>
              <p className="muted" style={{ marginBottom: '16px' }}>
                <Trans ns="users" i18nKey="adminUserNew.text.selectRolesAssignUserRolesCan" /></p>
              {loadingRoles ? (
                <div className="info-banner"><Trans ns="users" i18nKey="adminUserNew.text.loadingRoles" /></div>
              ) : (
                <div className="roles-grid">
                  {availableRoles.map((role) => (
                    <label key={role.role_id} className="role-checkbox">
                      <input
                        type="checkbox"
                        checked={selectedRoles.has(role.name)}
                        onChange={() => handleRoleToggle(role.name)}
                        disabled={submitting}
                      />
                      <div className="role-info">
                        <strong>{roleLabel(role.name)}</strong>
                        <span className="muted">{roleDescription(role.name, role.description)}</span>
                      </div>
                    </label>
                  ))}
                  {availableRoles.length === 0 && (
                    <p className="muted"><Trans ns="users" i18nKey="adminUserNew.text.noRolesAvailable" /></p>
                  )}
                </div>
              )}
            </div>


          </div>
        </div>
        <div className="form-actions">
          <button
            type="button"
            className="btn"
            onClick={() => navigate('/admin/users')}
            disabled={submitting}
          >
            <Trans ns="common" i18nKey="actions.cancel" /></button>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? i18n.t('users:adminUserNew.actions.creating') : i18n.t('users:adminUserNew.actions.createUser')}
          </button>
        </div>
      </form>
    </AdminPageLayout>
  );
}
