

import React, { useEffect, useState, useCallback, useMemo } from 'react';
import type { AuthState, AuthUser, LoginCredentials } from './types';
import { AuthContext, type AuthContextValue } from './context';
import {
  setAccessToken,
  setAuthStateChangeCallback,
  refreshAccessToken,
  fetchCurrentUser,
  login as authClientLogin,
  logout as authClientLogout,
} from './authClient';


export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authState, setAuthState] = useState<AuthState>({
    isAuthenticated: false,
    user: null,
    accessToken: null,
    isLoading: true, // Start as loading until initial check completes
  });

  
  const handleAuthStateChange = useCallback((token: string | null, user: AuthUser | null) => {
    if (token && user) {
      setAuthState({
        isAuthenticated: true,
        user,
        accessToken: token,
        isLoading: false,
      });
    } else {
      setAuthState({
        isAuthenticated: false,
        user: null,
        accessToken: null,
        isLoading: false,
      });
    }
  }, []);

  
  useEffect(() => {
    let cancelled = false;

    async function initializeAuth() {
      try {
        
        const newToken = await refreshAccessToken();
        
        if (cancelled) return;

        if (newToken) {
          
          setAccessToken(newToken);
          const user = await fetchCurrentUser(newToken);
          
          if (cancelled) return;

          if (user) {
            setAuthState({
              isAuthenticated: true,
              user,
              accessToken: newToken,
              isLoading: false,
            });
          } else {
            
            setAccessToken(null);
            setAuthState({
              isAuthenticated: false,
              user: null,
              accessToken: null,
              isLoading: false,
            });
          }
        } else {
          
          setAuthState({
            isAuthenticated: false,
            user: null,
            accessToken: null,
            isLoading: false,
          });
        }
      } catch {
        
        if (!cancelled) {
          setAuthState({
            isAuthenticated: false,
            user: null,
            accessToken: null,
            isLoading: false,
          });
        }
      }
    }

    
    setAuthStateChangeCallback(handleAuthStateChange);
    
    
    initializeAuth();

    return () => {
      cancelled = true;
      setAuthStateChangeCallback(null);
    };
  }, [handleAuthStateChange]);

  
  const login = useCallback(async (credentials: LoginCredentials): Promise<{ success: boolean; error?: string; statusCode?: number }> => {
    setAuthState((prev) => ({ ...prev, isLoading: true }));

    const result = await authClientLogin(credentials);

    if (result.success) {
      
      const token = result.token;
      setAccessToken(token);
      
      const user = await fetchCurrentUser(token);
      
      if (user) {
        setAuthState({
          isAuthenticated: true,
          user,
          accessToken: token,
          isLoading: false,
        });
        return { success: true };
      } else {
        
        setAccessToken(null);
        setAuthState({
          isAuthenticated: false,
          user: null,
          accessToken: null,
          isLoading: false,
        });
        return { success: false, error: 'Failed to fetch user information' };
      }
    } else {
      setAuthState((prev) => ({ ...prev, isLoading: false }));
      
      return { success: false, error: result.error, statusCode: result.statusCode };
    }
  }, []);

  
  const logout = useCallback(async (): Promise<void> => {
    setAuthState((prev) => ({ ...prev, isLoading: true }));
    await authClientLogout();
    setAuthState({
      isAuthenticated: false,
      user: null,
      accessToken: null,
      isLoading: false,
    });
  }, []);

  
  const hasScope = useCallback((scope: string): boolean => {
    if (!authState.user) return false;
    return authState.user.scopes.includes(scope);
  }, [authState.user]);

  
  const hasAnyScope = useCallback((scopes: string[]): boolean => {
    if (!authState.user) return false;
    return scopes.some((scope) => authState.user!.scopes.includes(scope));
  }, [authState.user]);

  
  const hasAllScopes = useCallback((scopes: string[]): boolean => {
    if (!authState.user) return false;
    return scopes.every((scope) => authState.user!.scopes.includes(scope));
  }, [authState.user]);

  
  const contextValue = useMemo<AuthContextValue>(() => ({
    ...authState,
    login,
    logout,
    hasScope,
    hasAnyScope,
    hasAllScopes,
  }), [authState, login, logout, hasScope, hasAnyScope, hasAllScopes]);

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}
