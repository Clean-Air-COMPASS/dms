

import { API_BASE } from '../apiBase';
import type { RefreshResponse, AuthUser, LoginResponse, LoginCredentials } from './types';
import { ApiError, apiErrorFromResponse } from '../apiError';


let currentAccessToken: string | null = null;


let onAuthStateChange: ((token: string | null, user: AuthUser | null) => void) | null = null;


let isRefreshing = false;


let refreshSubscribers: Array<(token: string | null) => void> = [];


export function setAccessToken(token: string | null): void {
  currentAccessToken = token;
}


export function getAccessToken(): string | null {
  return currentAccessToken;
}


export function setAuthStateChangeCallback(
  callback: ((token: string | null, user: AuthUser | null) => void) | null
): void {
  onAuthStateChange = callback;
}


function subscribeToRefresh(callback: (token: string | null) => void): void {
  refreshSubscribers.push(callback);
}


function onRefreshComplete(token: string | null): void {
  refreshSubscribers.forEach((callback) => callback(token));
  refreshSubscribers = [];
}


export async function refreshAccessToken(): Promise<string | null> {
  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      credentials: 'include', // Include HttpOnly cookie
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      return null;
    }

    const data: RefreshResponse = await response.json();
    return data.access_token;
  } catch {
    return null;
  }
}


export async function fetchCurrentUser(accessToken: string): Promise<AuthUser | null> {
  try {
    const response = await fetch(`${API_BASE}/auth/me`, {
      method: 'GET',
      credentials: 'include',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      return null;
    }

    return await response.json();
  } catch {
    return null;
  }
}

export async function acceptPasskeySession(token: string): Promise<void> {
  const user = await fetchCurrentUser(token);
  if (!user) throw new Error('current_user_unavailable');
  setAccessToken(token);
  onAuthStateChange?.(token, user);
}

/** Publish backend identity without duplicating its display-name rules. */
export async function refreshCurrentUser(): Promise<void> {
  const token = getAccessToken();
  if (!token) throw new Error('current_user_unavailable');
  const user = await fetchCurrentUser(token);
  if (!user) throw new ApiError({ status: 503, errorCode: 'account_refresh_failed' });
  onAuthStateChange?.(token, user);
}

export async function updateCurrentUserProfile(first_name: string, last_name: string): Promise<void> {
  const user = await authFetchJson<AuthUser>('/auth/me', {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ first_name, last_name }),
  });
  onAuthStateChange?.(getAccessToken(), user);
}

/** Store the replacement immediately: the previous refresh session is revoked. */
export async function acceptAccountSession(token: string): Promise<void> {
  setAccessToken(token);
  await refreshCurrentUser();
}

export async function updateCurrentUserPreferences(
  preferredLanguageCode: 'en' | 'es' | null,
): Promise<AuthUser> {
  return authFetchJson<AuthUser>('/auth/me/preferences', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preferred_language_code: preferredLanguageCode }),
  });
}


export type LoginResult =
  | { success: true; token: string }
  | { success: false; error: string; statusCode?: number };


export async function login(credentials: LoginCredentials, receiveRefreshCookie = true): Promise<LoginResult> {
  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      credentials: receiveRefreshCookie ? 'include' : 'omit',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email: credentials.email, password: credentials.password }),
    });

    if (!response.ok) {
      let errorMessage = 'login_failed';
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch {
        // Use default error message
      }
      
      return { success: false, error: errorMessage, statusCode: response.status };
    }

    const data: LoginResponse = await response.json();
    return { success: true, token: data.access_token };
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : 'network_error';
    return { success: false, error: errorMessage };
  }
}


export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Authorization': currentAccessToken ? `Bearer ${currentAccessToken}` : '',
        'Content-Type': 'application/json',
      },
    });
  } catch {
    // Logout endpoint failure shouldn't block local cleanup
  }
  
  
  currentAccessToken = null;
  if (onAuthStateChange) {
    onAuthStateChange(null, null);
  }
}


export async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;
  
  
  const makeRequest = (token: string | null): Promise<Response> => {
    const headers = new Headers(init?.headers);
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    
    return fetch(url, {
      ...init,
      credentials: 'include',
      headers,
    });
  };

  
  let response = await makeRequest(currentAccessToken);

  
  if (response.status === 401 && !path.includes('/auth/')) {
    
    if (isRefreshing) {
      return new Promise((resolve) => {
        subscribeToRefresh(async (newToken) => {
          if (newToken) {
            resolve(await makeRequest(newToken));
          } else {
            resolve(response); 
          }
        });
      });
    }

    
    isRefreshing = true;
    const newToken = await refreshAccessToken();
    isRefreshing = false;

    if (newToken) {
      
      currentAccessToken = newToken;
      
      
      const user = await fetchCurrentUser(newToken);
      if (onAuthStateChange) {
        onAuthStateChange(newToken, user);
      }
      
      
      onRefreshComplete(newToken);
      response = await makeRequest(newToken);
    } else {
      
      onRefreshComplete(null);
      currentAccessToken = null;
      if (onAuthStateChange) {
        onAuthStateChange(null, null);
      }
    }
  }

  return response;
}


export async function authFetchJson<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const response = await authFetch(path, init);
  
  if (!response.ok) throw await apiErrorFromResponse(response);

  return response.json();
}
