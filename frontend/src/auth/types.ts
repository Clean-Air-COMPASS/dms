


export interface AuthUser {
  
  user_id: string;
  
  email: string;
  
  org_id: string;
  
  roles: string[];
  
  scopes: string[];
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
