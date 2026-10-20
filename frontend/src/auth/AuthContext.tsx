

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
  updateCurrentUserPreferences,
} from './authClient';
import i18n, {
  resolveAuthenticatedLanguage,
  writeAnonymousLanguagePreference,
  type SupportedLanguageCode,
} from '../i18n';

async function applyAuthenticatedLanguage(user: AuthUser): Promise<void> {
  const languageCode = resolveAuthenticatedLanguage(
    user.preferred_language_code,
    user.system_default_language_code,
  );
  if (typeof window !== 'undefined') {
    writeAnonymousLanguagePreference(window.localStorage, languageCode);
  }
  await i18n.changeLanguage(languageCode);
}


export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authState, setAuthState] = useState<AuthState>({
    isAuthenticated: false,
    user: null,
    accessToken: null,
    isLoading: true, // Start as loading until initial check completes
  });

  
  const handleAuthStateChange = useCallback(async (token: string | null, user: AuthUser | null) => {
    if (token && user) {
      await applyAuthenticatedLanguage(user);
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
            await applyAuthenticatedLanguage(user);
            if (cancelled) return;
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
        await applyAuthenticatedLanguage(user);
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
        return { success: false, error: 'current_user_unavailable' };
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

  const setPreferredLanguageCode = useCallback(async (
    languageCode: SupportedLanguageCode | null,
  ): Promise<void> => {
    const updatedUser = await updateCurrentUserPreferences(languageCode);
    await applyAuthenticatedLanguage(updatedUser);
    setAuthState((currentState) => ({ ...currentState, user: updatedUser }));
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
    setPreferredLanguageCode,
    hasScope,
    hasAnyScope,
    hasAllScopes,
  }), [authState, login, logout, setPreferredLanguageCode, hasScope, hasAnyScope, hasAllScopes]);

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}
