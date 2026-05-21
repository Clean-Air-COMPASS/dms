import { useEffect, useState, useCallback } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import AdminPageLayout from './components/AdminPageLayout';
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
    return new Date(val).toLocaleString();
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
      setAvailableRoles(rolesData);
      setSelectedRoles(new Set(userData.roles));
      setIsActive(userData.is_active);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load user';
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
      setSaveMessage({ type: 'success', text: 'Roles updated successfully.' });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to update roles';
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
        text: `User ${newStatus ? 'enabled' : 'disabled'} successfully.`,
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to update status';
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
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to delete user';
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
        text: 'Account unlocked successfully. Failed login count has been reset.',
      });
    } catch (err: unknown) {
      
      const message = err instanceof Error ? err.message : 'Failed to unlock account';
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
              <Link to="/admin">Admin</Link>
              <span aria-hidden="true">/</span>
              <Link to="/admin/users">Users</Link>
              <span aria-hidden="true">/</span>
              <span>Loading…</span>
            </div>
            <h1>Loading User…</h1>
          </div>
        </div>
        <div className="info-banner">Loading user details…</div>
      </div>
    );
  }

  if (error || !user) {
    return (
      <div className="admin-page-content user-detail-page">
        <div className="admin-page-header">
          <div>
            <div className="breadcrumbs">
              <Link to="/admin">Admin</Link>
              <span aria-hidden="true">/</span>
              <Link to="/admin/users">Users</Link>
              <span aria-hidden="true">/</span>
              <span>Error</span>
            </div>
            <h1>User Not Found</h1>
          </div>
        </div>
        <div className="error-banner">{error || 'User not found'}</div>
        <div style={{ marginTop: '16px' }}>
          <Link to="/admin/users" className="btn">
            ← Back to Users
          </Link>
        </div>
      </div>
    );
  }

  return (
    <AdminPageLayout
      title={user.email}
      description={`User ID: ${user.user_id}`}
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'Users', to: '/admin/users' },
        { label: user.email },
      ]}
      actions={
        <button
          className="btn btn-danger"
          onClick={handleDelete}
          disabled={saving}
        >
          Delete User
        </button>
      }
      contentClassName="user-detail-page"
    >
      {saveMessage && (
        <div className={saveMessage.type === 'success' ? 'success-banner' : 'error-banner'}>
          {saveMessage.text}
        </div>
      )}

      
      <div className="card">
        <h2>User Information</h2>
        <div className="info-grid">
          <div className="info-row">
            <span className="info-label">Email</span>
            <span className="info-value">{user.email}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Organization ID</span>
            <span className="info-value">{user.org_id}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Created</span>
            <span className="info-value">{formatDate(user.created_at)}</span>
          </div>
          <div className="info-row">
            <span className="info-label">Last Updated</span>
            <span className="info-value">{formatDate(user.updated_at)}</span>
          </div>
        </div>
      </div>

      
      <div className="card">
        <h2>Account Status</h2>
        <div className="status-section">
          <div className="status-row">
            <div>
              <span className={`status-badge large ${isActive ? 'active' : 'disabled'}`}>
                {isActive ? 'Active' : 'Disabled'}
              </span>
              <p className="muted" style={{ marginTop: '8px' }}>
                {isActive
                  ? 'This user can log in and access the system.'
                  : 'This user cannot log in or access the system.'}
              </p>
            </div>
            <button
              className={`btn ${isActive ? 'btn-warning' : 'btn-primary'}`}
              onClick={handleToggleStatus}
              disabled={saving}
            >
              {isActive ? 'Disable User' : 'Enable User'}
            </button>
          </div>
        </div>
      </div>

      
      {hasSecurityInfo && (
        <div className="card">
          <h2>Security Information</h2>
          <p className="muted" style={{ marginBottom: '16px' }}>
            Login security status for this account. This information is only visible to administrators.
          </p>
          <div className="info-grid">
            <div className="info-row">
              <span className="info-label">Failed Login Attempts</span>
              <span className="info-value">
                {user.failed_login_count != null ? user.failed_login_count : '—'}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Last Failed Login</span>
              <span className="info-value">
                {formatDate(user.last_failed_login_at)}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Account Lock Status</span>
              <span className="info-value">
                {isAccountLocked ? (
                  <span className="status-badge disabled">
                    Locked until {formatDate(user.locked_until)}
                  </span>
                ) : user.locked_until ? (
                  <span className="status-badge active">
                    Lock expired ({formatDate(user.locked_until)})
                  </span>
                ) : (
                  'Not locked'
                )}
              </span>
            </div>
          </div>
          
          {(isAccountLocked || (user.failed_login_count != null && user.failed_login_count > 0)) && (
            <div className="card-actions" style={{ marginTop: '16px' }}>
              <button
                className="btn btn-primary"
                onClick={handleUnlock}
                disabled={saving}
              >
                Unlock Account
              </button>
              <span className="muted" style={{ marginLeft: '12px' }}>
                Resets failed login count and clears any active lock.
              </span>
            </div>
          )}
        </div>
      )}

      
      <div className="card">
        <h2>Roles</h2>
        <p className="muted" style={{ marginBottom: '16px' }}>
          Select the roles to assign to this user. Changes are saved when you click "Save Roles".
        </p>
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
                <strong>{role.name}</strong>
                {role.description && <span className="muted">{role.description}</span>}
              </div>
            </label>
          ))}
        </div>
        <div className="card-actions" style={{ marginTop: '16px' }}>
          <button
            className="btn btn-primary"
            onClick={handleSaveRoles}
            disabled={saving || !rolesChanged}
          >
            {saving ? 'Saving…' : 'Save Roles'}
          </button>
          {rolesChanged && (
            <span className="muted" style={{ marginLeft: '12px' }}>
              Unsaved changes
            </span>
          )}
        </div>
      </div>

      
      {showStatusConfirm && (
        <div className="modal-overlay" onClick={() => setShowStatusConfirm(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{isActive ? 'Disable User' : 'Enable User'}</h3>
            <p>
              Are you sure you want to {isActive ? 'disable' : 'enable'} this user?
              {isActive && ' They will not be able to log in until re-enabled.'}
            </p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowStatusConfirm(false)}>
                Cancel
              </button>
              <button
                className={`btn ${isActive ? 'btn-warning' : 'btn-primary'}`}
                onClick={confirmToggleStatus}
              >
                {isActive ? 'Disable' : 'Enable'}
              </button>
            </div>
          </div>
        </div>
      )}

      
      {showDeleteConfirm && (
        <div className="modal-overlay" onClick={() => setShowDeleteConfirm(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <h3>Delete User</h3>
            <p>
              Are you sure you want to permanently delete <strong>{user.email}</strong>?
              This action cannot be undone.
            </p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowDeleteConfirm(false)}>
                Cancel
              </button>
              <button className="btn btn-danger" onClick={confirmDelete}>
                Delete User
              </button>
            </div>
          </div>
        </div>
      )}

      
      {showUnlockConfirm && (
        <div className="modal-overlay">
          <div className="modal">
            <h3>Unlock Account</h3>
            <p>
              Are you sure you want to unlock this account? This will reset the failed login
              counter to zero and remove any active time-based lock.
            </p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowUnlockConfirm(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={confirmUnlock}>
                Unlock Account
              </button>
            </div>
          </div>
        </div>
      )}
    </AdminPageLayout>
  );
}
