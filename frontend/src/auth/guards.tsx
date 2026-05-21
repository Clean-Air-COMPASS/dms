

import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './useAuth';


interface RequireAuthProps {
  children: React.ReactNode;
  
  redirectTo?: string;
}


export function RequireAuth({ children, redirectTo = '/login' }: RequireAuthProps) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-slate-600">Checking authentication...</p>
        </div>
      </div>
    );
  }

  
  if (!isAuthenticated) {
    
    return <Navigate to={redirectTo} state={{ from: location }} replace />;
  }

  
  return <>{children}</>;
}


interface RequireScopeProps {
  children: React.ReactNode;
  
  scopes: string[];
  
  requireAll?: boolean;
  
  fallback?: React.ReactNode;
}


export function RequireScope({ children, scopes, requireAll = false, fallback }: RequireScopeProps) {
  const { isAuthenticated, isLoading, hasAnyScope, hasAllScopes, user } = useAuth();

  
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-slate-600">Checking permissions...</p>
        </div>
      </div>
    );
  }

  
  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md mx-auto p-6">
          <div className="text-red-500 text-5xl mb-4">🔒</div>
          <h1 className="text-xl font-semibold text-slate-800 mb-2">Authentication Required</h1>
          <p className="text-slate-600 mb-4">Please log in to access this page.</p>
          <a href="/login" className="btn bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">
            Go to Login
          </a>
        </div>
      </div>
    );
  }

  
  const hasRequiredScopes = requireAll ? hasAllScopes(scopes) : hasAnyScope(scopes);

  if (!hasRequiredScopes) {
    
    if (fallback) {
      return <>{fallback}</>;
    }

    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md mx-auto p-6">
          <div className="text-amber-500 text-5xl mb-4">⚠️</div>
          <h1 className="text-xl font-semibold text-slate-800 mb-2">Not Authorized</h1>
          <p className="text-slate-600 mb-4">
            You don't have permission to access this page.
          </p>
          <p className="text-sm text-slate-500 mb-4">
            Required permission{scopes.length > 1 ? 's' : ''}: {scopes.join(', ')}
          </p>
          {user && (
            <p className="text-xs text-slate-400">
              Your permissions: {user.scopes.length > 0 ? user.scopes.join(', ') : 'none'}
            </p>
          )}
        </div>
      </div>
    );
  }

  
  return <>{children}</>;
}


export function RequireAuthAndScope({ 
  children, 
  scopes, 
  requireAll = false,
  redirectTo = '/login',
  fallback 
}: RequireAuthProps & RequireScopeProps) {
  return (
    <RequireAuth redirectTo={redirectTo}>
      <RequireScope scopes={scopes} requireAll={requireAll} fallback={fallback}>
        {children}
      </RequireScope>
    </RequireAuth>
  );
}
