import { roleLabel, roleDescription } from './rolePresentation';
import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useState, useCallback, type FormEvent } from 'react';
import { accountErrorKey, type AccountErrorCode } from './account/accountApi';
import { Link, useNavigate, useParams } from 'react-router-dom';
import AdminPageLayout from './components/AdminPageLayout';
import PasswordRecovery from './users/PasswordRecovery';
import UsersDialog from './users/UsersDialog';
import './users/users.css';
import {
  getUser,
  updateUser,
  deleteUser,
  unlockUser,
  listRoles,
  type UserRecord,
  type RoleRecord,
} from './api';


function formatDate(val?: string | null): string {
  if (!val) return '—';
  try {
    return new Date(val).toLocaleString(i18n.language, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return val;
  }
}


export default function AdminUserDetail() {
  const { userId } = useParams<{ userId: string }>();
  const navigate = useNavigate();

  const [user, setUser] = useState<UserRecord | null>(null);
  const [availableRoles, setAvailableRoles] = useState<RoleRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<boolean>(false);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [profileState, setProfileState] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [profileError, setProfileError] = useState<AccountErrorCode | ''>('');
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  
  const [selectedRoles, setSelectedRoles] = useState<Set<string>>(new Set());
  const [isActive, setIsActive] = useState<boolean>(true);

  
  const [showStatusConfirm, setShowStatusConfirm] = useState<boolean>(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<boolean>(false);
  const [showUnlockConfirm, setShowUnlockConfirm] = useState<boolean>(false);

  
  const loadData = useCallback(async () => {
    if (!userId) return;
    
    setLoading(true);
    setError(null);

    try {
      const [userData, rolesData] = await Promise.all([
        getUser(userId),
        listRoles(),
      ]);
      setUser(userData);
      setFirstName(userData.first_name ?? '');
      setLastName(userData.last_name ?? '');
      setProfileState('idle');
      setProfileError('');
      setAvailableRoles(rolesData);
      setSelectedRoles(new Set(userData.roles));
      setIsActive(userData.is_active);
    } catch {
      const message = i18n.t('common:errors.loadUser');
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  
  useEffect(() => {
    if (saveMessage) {
      const timer = setTimeout(() => setSaveMessage(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [saveMessage]);

  
  const handleSaveProfile = async (event: FormEvent) => {
    event.preventDefault();
    if (!userId || saving) return;
    setSaving(true);
    setProfileState('saving');
    setProfileError('');
    try {
      const updatedUser = await updateUser(userId, { first_name: firstName, last_name: lastName });
      setUser(updatedUser);
      setFirstName(updatedUser.first_name ?? '');
      setLastName(updatedUser.last_name ?? '');
      setProfileState('saved');
    } catch (error) {
      setProfileError(accountErrorKey(error));
      setProfileState('idle');
    } finally {
      setSaving(false);
    }
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

  
  const handleSaveRoles = async () => {
    if (!userId) return;
    
    setSaving(true);
    setSaveMessage(null);

    try {
      const updatedUser = await updateUser(userId, {
        roles: Array.from(selectedRoles),
      });
      setUser(updatedUser);
      setSelectedRoles(new Set(updatedUser.roles));
      setSaveMessage({ type: 'success', text: i18n.t('users:adminUserDetail.text.rolesUpdated') });
    } catch {
      const message = i18n.t('common:errors.updateRoles');
      setSaveMessage({ type: 'error', text: message });
    } finally {
      setSaving(false);
    }
  };

  
  const handleToggleStatus = () => {
    setShowStatusConfirm(true);
  };

  const confirmToggleStatus = async () => {
    if (!userId) return;
    
    setShowStatusConfirm(false);
    setSaving(true);
    setSaveMessage(null);

    try {
      const newStatus = !isActive;
      const updatedUser = await updateUser(userId, { is_active: newStatus });
      setUser(updatedUser);
      setIsActive(updatedUser.is_active);
      setSaveMessage({
        type: 'success',
        text: newStatus
          ? i18n.t('users:adminUserDetail.text.userEnabled')
          : i18n.t('users:adminUserDetail.text.userDisabled'),
      });
    } catch {
      const message = i18n.t('common:errors.updateStatus');
      setSaveMessage({ type: 'error', text: message });
    } finally {
      setSaving(false);
    }
  };

  
  const handleDelete = () => {
    setShowDeleteConfirm(true);
  };

  const confirmDelete = async () => {
    if (!userId) return;
    
    setShowDeleteConfirm(false);
    setSaving(true);

    try {
      await deleteUser(userId);
      navigate('/admin/users', { replace: true });
    } catch {
      const message = i18n.t('common:errors.deleteUser');
      setSaveMessage({ type: 'error', text: message });
      setSaving(false);
    }
  };

  
  const handleUnlock = () => {
    setShowUnlockConfirm(true);
  };

  const confirmUnlock = async () => {
    if (!userId) return;
    
    setShowUnlockConfirm(false);
    setSaving(true);
    setSaveMessage(null);

    try {
      const updatedUser = await unlockUser(userId);
      setUser(updatedUser);
      setSaveMessage({
        type: 'success',
        text: i18n.t('users:adminUserDetail.text.accountUnlocked'),
      });
    } catch {
      
      const message = i18n.t('common:errors.unlockAccount');
      setSaveMessage({ type: 'error', text: message });
    } finally {
      setSaving(false);
    }
  };

  
  const isAccountLocked = user?.locked_until
    ? new Date(user.locked_until) > new Date()
    : false;

  
  const hasSecurityInfo =
    (user?.failed_login_count != null && user.failed_login_count > 0) ||
    user?.last_failed_login_at != null ||
    user?.locked_until != null;

  
  const rolesChanged = user && (
    selectedRoles.size !== user.roles.length ||
    !user.roles.every((role) => selectedRoles.has(role))
  );

  if (loading) {
    return (
      <div className="admin-page-content user-detail-page">
        <div className="admin-page-header">
          <div>
            <div className="breadcrumbs">
              <Link to="/admin"><Trans ns="users" i18nKey="adminUserDetail.actions.admin" /></Link>
              <span aria-hidden="true">/</span>
              <Link to="/admin/users"><Trans ns="users" i18nKey="adminUserDetail.actions.users" /></Link>
              <span aria-hidden="true">/</span>
              <span><Trans ns="common" i18nKey="states.loading" /></span>
            </div>
            <h1><Trans ns="users" i18nKey="adminUserDetail.headings.loadingUser" /></h1>
          </div>
        </div>
        <div className="info-banner"><Trans ns="users" i18nKey="adminUserDetail.text.loadingUserDetails" /></div>
      </div>
    );
  }

  if (error || !user) {
    return (
      <div className="admin-page-content user-detail-page">
        <div className="admin-page-header">
          <div>
            <div className="breadcrumbs">
              <Link to="/admin"><Trans ns="users" i18nKey="adminUserDetail.actions.admin2" /></Link>
              <span aria-hidden="true">/</span>
              <Link to="/admin/users"><Trans ns="users" i18nKey="adminUserDetail.actions.users2" /></Link>
              <span aria-hidden="true">/</span>
              <span><Trans ns="users" i18nKey="adminUserDetail.text.error" /></span>
            </div>
            <h1><Trans ns="users" i18nKey="adminUserDetail.headings.userNotFound" /></h1>
          </div>
        </div>
        <div className="error-banner">{error || i18n.t('users:adminUserDetail.text.userNotFound')}</div>
        <div style={{ marginTop: '16px' }}>
          <Link to="/admin/users" className="btn">
            <Trans ns="users" i18nKey="adminUserDetail.actions.backUsers" /></Link>
        </div>
      </div>
    );
  }

  return (
    <AdminPageLayout
      title={user.display_name || user.email}
      description={i18n.t('users:recovery.detailDescription')}
      breadcrumbs={[
        { label: i18n.t('users:adminUserDetail.content.admin'), to: '/admin' },
        { label: i18n.t('users:adminUserDetail.content.users'), to: '/admin/users' },
        { label: i18n.t('users:workspace.account') },
      ]}
      contentClassName="user-detail-page"
    >
      {saveMessage && (
        <div role={saveMessage.type === 'success' ? 'status' : 'alert'} className={saveMessage.type === 'success' ? 'success-banner' : 'error-banner'}>
          {saveMessage.text}
        </div>
      )}

      
      <div className="users-workspace">
        <div className="users-account-column">
          <section className="card users-profile" aria-labelledby="user-profile-heading">
            <h2 id="user-profile-heading">{i18n.t('auth:account.profile')}</h2>
            <form onSubmit={handleSaveProfile}>
              <div className="users-name-fields">
                <label className="field">
                  <span>{i18n.t('auth:account.firstName')}</span>
                  <input autoComplete="off" maxLength={100} value={firstName} disabled={saving} aria-describedby="user-name-help"
                    onChange={(event) => { setFirstName(event.target.value); setProfileState('idle'); }} />
                </label>
                <label className="field">
                  <span>{i18n.t('auth:account.lastName')}</span>
                  <input autoComplete="off" maxLength={100} value={lastName} disabled={saving} aria-describedby="user-name-help"
                    onChange={(event) => { setLastName(event.target.value); setProfileState('idle'); }} />
                </label>
              </div>
              <p className="muted" id="user-name-help">{i18n.t('auth:account.nameHelp')}</p>
              <label className="field">
                <span>{i18n.t('auth:account.email')}</span>
                <input type="email" value={user.email} readOnly />
              </label>
              {profileError && <p role="alert" className="error-banner">{i18n.t(`auth:account.errors.${profileError}`)}</p>}
              <div className="card-actions">
                <button className="btn btn-primary" disabled={saving || (firstName === (user.first_name ?? '') && lastName === (user.last_name ?? ''))}>
                  {i18n.t(profileState === 'saving' ? 'auth:account.saving' : 'auth:account.saveProfile')}
                </button>
                {profileState === 'saved' && <span role="status">{i18n.t('auth:account.saved')}</span>}
              </div>
            </form>
          </section>
          <div className="card users-access" id="account-access">
            <h2><Trans ns="users" i18nKey="workspace.access" /></h2>
            <div className="status-section">
              <div className="status-row">
                <div>
                  <span className={`status-badge ${isActive ? 'active' : 'disabled'}`}>
                    {isActive ? i18n.t('users:adminUserDetail.text.active') : i18n.t('users:adminUserDetail.text.disabled')}
                  </span>
                  <p className="muted" style={{ marginTop: '8px' }}>
                    {isActive
                      ? i18n.t('users:adminUserDetail.text.userCanLogAccessSystem')
                      : i18n.t('users:adminUserDetail.text.userCannotLogAccessSystem')}
                  </p>
                </div>
                <button
                  className="btn"
                  onClick={handleToggleStatus}
                  disabled={saving}
                >
                  {isActive ? i18n.t('users:adminUserDetail.actions.disableUser') : i18n.t('users:adminUserDetail.actions.enableUser')}
                </button>
              </div>
            </div>

            {hasSecurityInfo && (
              <div className="users-security">
                <h3><Trans ns="users" i18nKey="adminUserDetail.headings.securityInformation" /></h3>
                <div className="info-grid">
                  <div className="info-row">
                    <span className="info-label"><Trans ns="users" i18nKey="adminUserDetail.text.failedLoginAttempts" /></span>
                    <span className="info-value">
                      {user.failed_login_count != null ? user.failed_login_count : '—'}
                    </span>
                  </div>
                  <div className="info-row">
                    <span className="info-label"><Trans ns="users" i18nKey="adminUserDetail.text.lastFailedLogin" /></span>
                    <span className="info-value">
                      {formatDate(user.last_failed_login_at)}
                    </span>
                  </div>
                  <div className="info-row">
                    <span className="info-label"><Trans ns="users" i18nKey="adminUserDetail.text.accountLockStatus" /></span>
                    <span className="info-value">
                      {isAccountLocked ? (
                        <span className="status-badge disabled">
                          {i18n.t('users:adminUserDetail.text.lockedUntilValue', {
                            date: formatDate(user.locked_until),
                          })}
                        </span>
                      ) : user.locked_until ? (
                        <span className="status-badge active">
                          {i18n.t('users:adminUserDetail.text.lockExpiredValue', {
                            date: formatDate(user.locked_until),
                          })}
                        </span>
                      ) : (
                        i18n.t('users:adminUserDetail.text.notLocked')
                      )}
                    </span>
                  </div>
                </div>

                {(isAccountLocked || (user.failed_login_count != null && user.failed_login_count > 0)) && (
                  <div className="card-actions">
                    <button
                      className="btn"
                      onClick={handleUnlock}
                      disabled={saving}
                    >
                      <Trans ns="users" i18nKey="adminUserDetail.actions.unlockAccount" /></button>
                    <span className="muted">
                      <Trans ns="users" i18nKey="adminUserDetail.text.resetsFailedLoginCountClearsAny" /></span>
                  </div>
                )}
              </div>
            )}

          </div>
        </div>
        <div className="users-role-column">
          <div className="card users-roles" id="account-roles">
            <h2><Trans ns="users" i18nKey="adminUserDetail.headings.roles" /></h2>
            <p className="muted" style={{ marginBottom: '16px' }}>
              <Trans ns="users" i18nKey="adminUserDetail.text.selectRolesAssignUserChangesSaved" /></p>
            <div className="roles-grid">
              {availableRoles.map((role) => (
                <label key={role.role_id} className="role-checkbox">
                  <input
                    type="checkbox"
                    checked={selectedRoles.has(role.name)}
                    onChange={() => handleRoleToggle(role.name)}
                    disabled={saving}
                  />
                  <div className="role-info">
                    <strong>{roleLabel(role.name)}</strong>
                    <span className="muted">{roleDescription(role.name, role.description)}</span>
                  </div>
                </label>
              ))}
            </div>
            <div className="card-actions">
              <button
                className="btn btn-primary"
                onClick={handleSaveRoles}
                disabled={saving || !rolesChanged}
              >
                {saving && profileState !== 'saving' ? i18n.t('users:adminUserDetail.actions.saving') : i18n.t('users:adminUserDetail.actions.saveRoles')}
              </button>
              {rolesChanged && (
                <span className="muted">
                  <Trans ns="users" i18nKey="adminUserDetail.text.unsavedChanges" /></span>
              )}
            </div>
          </div>


          <details className="card users-metadata">
            <summary>{i18n.t('users:adminUserDetail.headings.userInformation')}</summary>
            <dl>
              <div><dt>{i18n.t('users:adminUserDetail.text.created')}</dt><dd>{formatDate(user.created_at)}</dd></div>
              <div><dt>{i18n.t('users:adminUserDetail.text.lastUpdated')}</dt><dd>{formatDate(user.updated_at)}</dd></div>
              <div><dt>{i18n.t('users:adminUserDetail.text.organizationId')}</dt><dd>{user.org_id}</dd></div>
            </dl>
          </details>
        </div>
      </div>

      <PasswordRecovery key={user.user_id} userId={user.user_id} />

      <section className="users-destructive" id="account-delete">
        <h2>{i18n.t('users:recovery.deleteTitle')}</h2>
        <p className="muted">{i18n.t('users:recovery.deleteDescription')}</p>
        <button className="btn btn-danger" onClick={handleDelete} disabled={saving}>{i18n.t('users:adminUserDetail.actions.deleteUser')}</button>
      </section>

      {showStatusConfirm && (
        <UsersDialog title={isActive ? i18n.t('users:adminUserDetail.headings.disableUser') : i18n.t('users:adminUserDetail.headings.enableUser')} onClose={() => setShowStatusConfirm(false)}>
            <p>
              {i18n.t(isActive ? 'users:recovery.confirmDisable' : 'users:recovery.confirmEnable', { email: user.email })}
            </p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowStatusConfirm(false)}>
                <Trans ns="common" i18nKey="actions.cancel" /></button>
              <button
                className="btn btn-primary"
                onClick={confirmToggleStatus}
              >
                {isActive ? i18n.t('users:adminUserDetail.actions.disable') : i18n.t('users:adminUserDetail.actions.enable')}
              </button>
            </div>
        </UsersDialog>
      )}

      
      {showDeleteConfirm && (
        <UsersDialog title={i18n.t('users:adminUserDetail.headings.deleteUser')} onClose={() => setShowDeleteConfirm(false)}>
            <p>
              {i18n.t('users:recovery.confirmDelete', { email: user.email })}</p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowDeleteConfirm(false)}>
                <Trans ns="common" i18nKey="actions.cancel" /></button>
              <button className="btn btn-danger" onClick={confirmDelete}>
                <Trans ns="users" i18nKey="adminUserDetail.actions.deleteUser2" /></button>
            </div>
        </UsersDialog>
      )}

      
      {showUnlockConfirm && (
        <UsersDialog title={i18n.t('users:adminUserDetail.headings.unlockAccount')} onClose={() => setShowUnlockConfirm(false)}>
            <p>
              <Trans ns="users" i18nKey="adminUserDetail.text.youSureYouWantUnlockAccount" /></p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowUnlockConfirm(false)}>
                <Trans ns="common" i18nKey="actions.cancel" /></button>
              <button className="btn btn-primary" onClick={confirmUnlock}>
                <Trans ns="users" i18nKey="adminUserDetail.actions.unlockAccount2" /></button>
            </div>
        </UsersDialog>
      )}
    </AdminPageLayout>
  );
}
