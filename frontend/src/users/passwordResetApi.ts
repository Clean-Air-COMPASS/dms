import { authFetchJson } from '../auth';
import { API_BASE } from '../apiBase';

export interface ResetLink { reset_url: string; expires_at: string; expires_in_minutes: number }
export const getRecoveryReadiness = () => authFetchJson<{ email_delivery_ready: boolean }>('/admin/users/password-reset/readiness');
export const createResetLink = (id: string) => authFetchJson<ResetLink>(`/admin/users/${encodeURIComponent(id)}/password-reset-link`, { method: 'POST' });
export const sendResetEmail = (id: string) => authFetchJson(`/admin/users/${encodeURIComponent(id)}/password-reset-email`, { method: 'POST' });

export async function submitReset(action: 'verify' | 'complete', token: string, password?: string): Promise<{ password_min_length?: number }> {
  const response = await fetch(`${API_BASE}/auth/password-reset/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    credentials: 'omit', cache: 'no-store', body: JSON.stringify({ token, password }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'reset_invalid');
  return data;
}
