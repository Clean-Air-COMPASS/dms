import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createUser, listRoles, type RoleRecord } from './api';
import AdminPageLayout from './components/AdminPageLayout';


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
        // Roles fetch failed, but we can still create users without roles
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
      setEmailError('Email is required');
      return false;
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(value)) {
      setEmailError('Invalid email format');
      return false;
    }
    setEmailError(null);
    return true;
  };

  
  const validatePassword = (): boolean => {
    if (!password) {
      setPasswordError('Password is required');
      return false;
    }
    if (password.length < 8) {
      setPasswordError('Password must be at least 8 characters');
      return false;
    }
    if (password !== confirmPassword) {
      setPasswordError('Passwords do not match');
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
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to create user';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AdminPageLayout
      title="Create New User"
      description="Add a new user account to the system."
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'Users', to: '/admin/users' },
        { label: 'New User' },
      ]}
      contentClassName="user-new-page"
    >
      {error && <div className="error-banner">{error}</div>}

      <form onSubmit={handleSubmit}>
        
        <div className="card">
          <h2>Account Details</h2>

          <div className="form-group">
            <label className="field">
              <span>
                Email <span className="required">*</span>
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (emailError) validateEmail(e.target.value);
                }}
                onBlur={() => validateEmail(email)}
                placeholder="user@example.com"
                disabled={submitting}
                autoComplete="off"
              />
              {emailError && <span className="field-error">{emailError}</span>}
            </label>
          </div>

          <div className="form-group">
            <label className="field">
              <span>
                Password <span className="required">*</span>
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (passwordError) setPasswordError(null);
                }}
                placeholder="Minimum 8 characters"
                disabled={submitting}
                autoComplete="new-password"
              />
            </label>
          </div>

          <div className="form-group">
            <label className="field">
              <span>
                Confirm Password <span className="required">*</span>
              </span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => {
                  setConfirmPassword(e.target.value);
                  if (passwordError) setPasswordError(null);
                }}
                onBlur={validatePassword}
                placeholder="Re-enter password"
                disabled={submitting}
                autoComplete="new-password"
              />
              {passwordError && <span className="field-error">{passwordError}</span>}
            </label>
          </div>
        </div>

        
        <div className="card">
          <h2>Initial Status</h2>
          <label className="status-toggle">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              disabled={submitting}
            />
            <div>
              <strong>Active</strong>
              <span className="muted">
                {isActive
                  ? 'User will be able to log in immediately after creation.'
                  : 'User will be created but cannot log in until enabled.'}
              </span>
            </div>
          </label>
        </div>

        
        <div className="card">
          <h2>Initial Roles</h2>
          <p className="muted" style={{ marginBottom: '16px' }}>
            Select roles to assign to this user. Roles can be modified later.
          </p>
          {loadingRoles ? (
            <div className="info-banner">Loading roles…</div>
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
                    <strong>{role.name}</strong>
                    {role.description && <span className="muted">{role.description}</span>}
                  </div>
                </label>
              ))}
              {availableRoles.length === 0 && (
                <p className="muted">No roles available.</p>
              )}
            </div>
          )}
        </div>

        
        <div className="form-actions">
          <button
            type="button"
            className="btn"
            onClick={() => navigate('/admin/users')}
            disabled={submitting}
          >
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create User'}
          </button>
        </div>
      </form>
    </AdminPageLayout>
  );
}
