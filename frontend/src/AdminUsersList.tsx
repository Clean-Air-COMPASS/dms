import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { listUsers, type UserRecord } from './api';
import AdminPageLayout from './components/AdminPageLayout';


function formatDate(val?: string | null): string {
  if (!val) return '—';
  try {
    return new Date(val).toLocaleString();
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
      } catch (err: unknown) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'Failed to load users';
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
      title="Users"
      description="Manage user accounts and role assignments."
      breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'Users' }]}
      actions={
        <button className="btn btn-primary" onClick={() => navigate('/admin/users/new')}>
          New User
        </button>
      }
      contentClassName="users-admin-page"
    >
      <div className="card filters-card">
        <div className="filters-grid">
          <label className="field">
            <span>Email</span>
            <input
              value={filterEmail}
              onChange={(e) => setFilterEmail(e.target.value)}
              placeholder="Search email…"
            />
          </label>
          <label className="field">
            <span>Status</span>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="">Any</option>
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
            </select>
          </label>
          <label className="field">
            <span>Role</span>
            <select value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
              <option value="">Any</option>
              {allRoles.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>
          <div className="field actions">
            <button className="btn ghost" onClick={resetFilters}>
              Reset
            </button>
          </div>
        </div>
      </div>

      {loading && <div className="info-banner">Loading users…</div>}
      {error && <div className="error-banner">{error}</div>}

      <div className="card table-card">
        <div className="table-responsive">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Roles</th>
                <th>Status</th>
                <th>Created</th>
                <th>Last Updated</th>
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
                      aria-label={`View ${user.email}`}
                    >
                      <strong>{user.email}</strong>
                    </Link>
                  </td>
                  <td>
                    <div className="role-badges">
                      {user.roles.length > 0 ? (
                        user.roles.map((role) => (
                          <span key={role} className="badge badge-role">
                            {role}
                          </span>
                        ))
                      ) : (
                        <span className="muted">No roles</span>
                      )}
                    </div>
                  </td>
                  <td>
                    <span className={`status-badge ${user.is_active ? 'active' : 'disabled'}`}>
                      {user.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td>{formatDate(user.created_at)}</td>
                  <td>{formatDate(user.updated_at)}</td>
                  <td>
                    <button
                      className="btn small"
                      onClick={() => navigate(`/admin/users/${user.user_id}`)}
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
              {!filtered.length && !loading && (
                <tr>
                  <td colSpan={6} className="muted">
                    No users found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="table-footer">
          <span className="muted">
            Showing {filtered.length} of {users.length} users
          </span>
        </div>
      </div>
    </AdminPageLayout>
  );
}
