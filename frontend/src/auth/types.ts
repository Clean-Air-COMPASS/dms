


export interface AuthUser {
  
  user_id: string;
  
  email: string;
  first_name: string | null;
  last_name: string | null;
  display_name: string;
  passkey_count: number;
  
  org_id: string;
  
  roles: string[];
  
  scopes: string[];
  preferred_language_code: 'en' | 'es' | null;
  system_default_language_code: 'en' | 'es';
}


export interface AuthState {
  
  isAuthenticated: boolean;
  
  user: AuthUser | null;
  
  accessToken: string | null;
  
  isLoading: boolean;
}


export interface LoginResponse {
  access_token: string;
  token_type: string;
}


export interface RefreshResponse {
  access_token: string;
  token_type: string;
}


export interface LoginCredentials {
  email: string;
  password: string;
}


export interface AuthApiError {
  detail: string;
}
