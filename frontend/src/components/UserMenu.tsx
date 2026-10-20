

import { useState, useRef, useEffect } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../auth';
import { useTranslation } from 'react-i18next';
import AccountLanguage from '../account/AccountLanguage';

function getDisplayInitial(displayName: string): string {
  return displayName?.charAt(0).toUpperCase() ?? '';
}

export default function UserMenu() {
  const { isAuthenticated, user, logout, isLoading } = useAuth();
  const { t } = useTranslation(['common', 'auth']);
  const navigate = useNavigate();
  const location = useLocation();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (!isOpen) return undefined;

    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    }

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen]);

  async function handleLogout() {
    setIsOpen(false);
    await logout();
    navigate('/login', { replace: true });
  }

  if (isLoading) {
    return <div className="user-menu__loading" aria-hidden="true" />;
  }

  if (!isAuthenticated || !user) {
    return (
      <Link
        to="/login"
        state={{ from: { pathname: location.pathname } }}
        className="btn"
      >
        {t('common:actions.signIn')}
      </Link>
    );
  }

  return (
    <div className="user-menu" ref={menuRef}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="user-menu__trigger"
        aria-label={t('auth:accountMenu.forUser', { email: user.display_name })}
        title={t('auth:accountMenu.label')}
        aria-expanded={isOpen}
        aria-controls="user-menu-dropdown"
      >
        <span className="user-menu__avatar" aria-hidden="true">
          {getDisplayInitial(user.display_name)}
        </span>
      </button>

      {isOpen && (
        <div
          id="user-menu-dropdown"
          className="user-menu__dropdown"
          role="region"
          aria-label={t('auth:accountMenu.label')}
        >
          <div className="user-menu__identity">
            <p className="user-menu__email">{user.display_name}</p>
            {user.display_name !== user.email && <p className="user-menu__email user-menu__secondary-email">{user.email}</p>}
          </div>

          <div className="user-menu__items">
            <Link
              to="/account"
              className="user-menu__item"
              onClick={() => setIsOpen(false)}
            >
              {t('auth:account.title')}
            </Link>
            {user.scopes.includes('users:write') && <Link
              to="/admin" className="user-menu__item" onClick={() => setIsOpen(false)}>
              {t('auth:accountMenu.admin')}
            </Link>}
            <AccountLanguage id="account-language-selector" />
            <button
              type="button"
              onClick={handleLogout}
              className="user-menu__item user-menu__item--sign-out"
            >
              {t('common:actions.signOut')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
