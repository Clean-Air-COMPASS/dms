

import { API_BASE } from '../apiBase';
import type { RefreshResponse, AuthUser, LoginResponse, LoginCredentials } from './types';


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


export type LoginResult =
  | { success: true; token: string }
  | { success: false; error: string; statusCode?: number };


export async function login(credentials: LoginCredentials): Promise<LoginResult> {
  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      credentials: 'include', // To receive the refresh cookie
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email: credentials.email, password: credentials.password }),
    });

    if (!response.ok) {
      let errorMessage = 'Login failed';
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
    const errorMessage = err instanceof Error ? err.message : 'Network error';
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
  
  if (!response.ok) {
    let errorMessage = `Request failed: ${response.status} ${response.statusText}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage = errorData.detail;
      }
    } catch {
      // Use default error message
    }
    throw new Error(errorMessage);
  }

  return response.json();
}
