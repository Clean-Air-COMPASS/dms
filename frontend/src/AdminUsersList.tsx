import { roleLabel } from './rolePresentation';
import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { listUsers, type UserRecord } from './api';
import AdminPageLayout from './components/AdminPageLayout';
import './users/users.css';


function formatDate(val?: string | null): string {
  if (!val) return '—';
  try {
    return new Date(val).toLocaleDateString(i18n.language, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return val;
  }
}


export default function AdminUsersList() {
  const navigate = useNavigate();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [filterEmail, setFilterEmail] = useState<string>('');
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [filterRole, setFilterRole] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const list = await listUsers();
        if (!cancelled) {
          setUsers(list || []);
        }
      } catch {
        if (!cancelled) {
          const message = i18n.t('common:errors.loadUsers');
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  
  const filtered = users.filter((user) => {
    
    if (filterEmail && !user.email.toLowerCase().includes(filterEmail.toLowerCase())) {
      return false;
    }
    
    if (filterStatus === 'active' && !user.is_active) {
      return false;
    }
    if (filterStatus === 'disabled' && user.is_active) {
      return false;
    }
    
    if (filterRole && !user.roles.includes(filterRole)) {
      return false;
    }
    return true;
  });

  
  const allRoles = Array.from(new Set(users.flatMap((u) => u.roles))).sort();

  const resetFilters = () => {
    setFilterEmail('');
    setFilterStatus('');
    setFilterRole('');
  };

  return (
    <AdminPageLayout
      title={i18n.t('users:adminUsersList.tooltips.users')}
      description={i18n.t('users:adminUsersList.accessibility.manageUserAccountsRoleAssignments')}
      breadcrumbs={[{ label: i18n.t('users:adminUsersList.content.admin'), to: '/admin' }, { label: i18n.t('users:adminUsersList.content.users') }]}
      actions={
        <button className="btn btn-primary" onClick={() => navigate('/admin/users/new')}>
          <Trans ns="users" i18nKey="adminUsersList.actions.newUser" /></button>
      }
      contentClassName="users-admin-page"
    >
      <div className="card filters-card">
        <div className="filters-grid">
          <label className="field">
            <span><Trans ns="common" i18nKey="fields.email" /></span>
            <input
              value={filterEmail}
              onChange={(e) => setFilterEmail(e.target.value)}
              placeholder={i18n.t('users:adminUsersList.placeholders.searchEmail')}
            />
          </label>
          <label className="field">
            <span><Trans ns="common" i18nKey="fields.status" /></span>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value=""><Trans ns="users" i18nKey="adminUsersList.options.any" /></option>
              <option value="active"><Trans ns="users" i18nKey="adminUsersList.options.active" /></option>
              <option value="disabled"><Trans ns="users" i18nKey="adminUsersList.options.disabled" /></option>
            </select>
          </label>
          <label className="field">
            <span><Trans ns="users" i18nKey="adminUsersList.text.role" /></span>
            <select value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
              <option value=""><Trans ns="users" i18nKey="adminUsersList.options.any2" /></option>
              {allRoles.map((role) => (
                <option key={role} value={role}>
                  {roleLabel(role)}
                </option>
              ))}
            </select>
          </label>
          <div className="field actions">
            <button className="btn ghost" onClick={resetFilters}>
              <Trans ns="common" i18nKey="actions.reset" /></button>
          </div>
        </div>
      </div>

      {loading && <div className="info-banner" role="status"><Trans ns="users" i18nKey="adminUsersList.text.loadingUsers" /></div>}
      {error && <div className="error-banner" role="alert">{error}</div>}

      {!loading && !error && <div className="card table-card">
        <p className="muted users-table-hint">{i18n.t('users:recovery.scrollTable')}</p>
        <div className="table-responsive" tabIndex={0} role="region" aria-label={i18n.t('users:adminUsersList.tooltips.users')}>
          <table className="admin-table">
            <thead>
              <tr>
                <th><Trans ns="common" i18nKey="fields.email" /></th>
                <th><Trans ns="users" i18nKey="adminUsersList.columns.roles" /></th>
                <th><Trans ns="common" i18nKey="fields.status" /></th>
                <th><Trans ns="users" i18nKey="adminUsersList.columns.created" /></th>
                <th><Trans ns="users" i18nKey="adminUsersList.columns.lastUpdated" /></th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((user) => (
                <tr key={user.user_id}>
                  <td>
                    <Link
                      to={`/admin/users/${user.user_id}`}
                      className="user-link"
                      aria-label={i18n.t('users:adminUsersList.accessibility.viewUser', { email: user.email })}
                    >
                      <strong>{user.email}</strong>
                      {user.display_name && user.display_name !== user.email && (
                        <span className="users-display-name muted">{user.display_name}</span>
                      )}
                    </Link>
                  </td>
                  <td data-label={i18n.t('users:adminUsersList.columns.roles')}>
                    <div className="role-badges">
                      {user.roles.length > 0 ? (
                        user.roles.map((role) => (
                          <span key={role} className="badge badge-role">
                            {roleLabel(role)}
                          </span>
                        ))
                      ) : (
                        <span className="muted"><Trans ns="users" i18nKey="adminUsersList.text.noRoles" /></span>
                      )}
                    </div>
                  </td>
                  <td data-label={i18n.t('common:fields.status')}>
                    <span className={`status-badge ${user.is_active ? 'active' : 'disabled'}`}>
                      {user.is_active ? i18n.t('users:adminUsersList.text.active') : i18n.t('users:adminUsersList.text.disabled')}
                    </span>
                  </td>
                  <td data-label={i18n.t('users:adminUsersList.columns.created')}>{formatDate(user.created_at)}</td>
                  <td data-label={i18n.t('users:adminUsersList.columns.lastUpdated')}>{formatDate(user.updated_at)}</td>
                  <td>
                    <button
                      className="btn small"
                      onClick={() => navigate(`/admin/users/${user.user_id}`)}
                    >
                      <Trans ns="users" i18nKey="adminUsersList.actions.view" /></button>
                  </td>
                </tr>
              ))}
              {!filtered.length && !loading && !error && (
                <tr>
                  <td colSpan={6} className="muted">
                    <Trans ns="users" i18nKey="adminUsersList.text.noUsersFound" /></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="table-footer">
          <span className="muted">
            {i18n.t('users:recovery.userCount', { shown: filtered.length, total: users.length })}</span>
        </div>
      </div>}
    </AdminPageLayout>
  );
}
