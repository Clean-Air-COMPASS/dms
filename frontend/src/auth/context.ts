

import { createContext } from 'react';
import type { AuthState, LoginCredentials } from './types';


export interface LoginResult {
  success: boolean;
  error?: string;
  
  statusCode?: number;
}


export interface AuthContextValue extends AuthState {
  
  login: (credentials: LoginCredentials) => Promise<LoginResult>;
  
  logout: () => Promise<void>;
  
  hasScope: (scope: string) => boolean;
  
  hasAnyScope: (scopes: string[]) => boolean;
  
  hasAllScopes: (scopes: string[]) => boolean;
}


const defaultContextValue: AuthContextValue = {
  isAuthenticated: false,
  user: null,
  accessToken: null,
  isLoading: true,
  login: async () => ({ success: false, error: 'AuthProvider not mounted' }),
  logout: async () => {},
  hasScope: () => false,
  hasAnyScope: () => false,
  hasAllScopes: () => false,
};


export const AuthContext = createContext<AuthContextValue>(defaultContextValue);
