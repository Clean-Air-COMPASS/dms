

import { useState, useRef, useEffect } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../auth';

export default function UserMenu() {
  const { isAuthenticated, user, logout, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  
  async function handleLogout() {
    setIsOpen(false);
    await logout();
    navigate('/login', { replace: true });
  }

  
  if (isLoading) {
    return (
      <div className="h-8 w-20 bg-slate-200 animate-pulse rounded"></div>
    );
  }

  
  if (!isAuthenticated || !user) {
    return (
      <Link
        to="/login"
        state={{ from: { pathname: location.pathname } }}
        className="btn"
      >
        Sign In
      </Link>
    );
  }

  
  return (
    <div className="relative" ref={menuRef}>
      
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-1.5 rounded hover:bg-slate-100 transition-colors"
        aria-haspopup="true"
        aria-expanded={isOpen}
      >
        
        <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-sm font-medium">
          {user.email.charAt(0).toUpperCase()}
        </div>
        
        <span className="hidden sm:inline text-sm text-slate-700 max-w-[150px] truncate">
          {user.email}
        </span>
        
        <svg
          className={`w-4 h-4 text-slate-500 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      
      {isOpen && (
        <div className="absolute right-0 mt-2 w-56 bg-white border border-slate-200 rounded-lg shadow-lg z-50">
          
          <div className="px-4 py-3 border-b border-slate-100">
            <p className="text-sm font-medium text-slate-800 truncate">{user.email}</p>
            {user.roles.length > 0 && (
              <p className="text-xs text-slate-500 mt-0.5">
                {user.roles.join(', ')}
              </p>
            )}
          </div>

          
          <div className="py-1">
            
            <button
              onClick={handleLogout}
              className="w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
            >
              Sign Out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
