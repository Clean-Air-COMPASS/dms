import { startAuthentication } from '@simplewebauthn/browser';
import { API_BASE } from '../apiBase';
import { ApiError, apiErrorFromResponse } from '../apiError';
import { acceptAccountSession, authFetchJson, getAccessToken } from '../auth/authClient';

export type Passkey = { id: string; name: string | null; created_at: string | null; last_used_at: string | null };
export type IdentityProof = { accessToken: string; reauthentication_token: string };

export const listPasskeys = () => authFetchJson<{ passkeys: Passkey[] }>('/auth/passkeys');

// Keep proof and its exact access session together, even if another request refreshes auth.
async function accountRequest<T>(path: string, accessToken: string, body?: object, method = 'POST', proof?: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method, credentials: 'include',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}`,
      ...(proof ? { 'X-Reauthentication-Token': proof } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.json();
}

export async function verifyIdentity(method: 'password' | 'passkey', current_password: string): Promise<IdentityProof> {
  const accessToken = getAccessToken();
  if (!accessToken) throw new ApiError({ status: 401 });
  let result: { reauthentication_token: string };
  if (method === 'password') {
    result = await accountRequest('/auth/reauthenticate', accessToken, { current_password });
  } else {
    const optionsJSON = await accountRequest<Parameters<typeof startAuthentication>[0]['optionsJSON']>(
      '/auth/passkeys/reauthenticate/options', accessToken, {});
    const credential = await startAuthentication({ optionsJSON });
    result = await accountRequest('/auth/passkeys/reauthenticate/verify', accessToken, { credential });
  }
  return { accessToken, reauthentication_token: result.reauthentication_token };
}

export async function changeEmail(email: string, proof: IdentityProof): Promise<void> {
  const result = await accountRequest<{ access_token: string }>('/auth/me/email', proof.accessToken,
    { email, reauthentication_token: proof.reauthentication_token });
  await acceptAccountSession(result.access_token);
}

export async function changePassword(password: string, confirm_password: string, proof: IdentityProof): Promise<void> {
  const result = await accountRequest<{ access_token: string }>('/auth/me/password', proof.accessToken,
    { password, confirm_password, reauthentication_token: proof.reauthentication_token });
  await acceptAccountSession(result.access_token);
}

export async function removePasskey(id: string, proof: IdentityProof): Promise<void> {
  await accountRequest(`/auth/passkeys/${encodeURIComponent(id)}`, proof.accessToken, undefined,
    'DELETE', proof.reauthentication_token);
}

const knownErrors = ['invalid_email', 'email_already_in_use', 'incorrect_current_password',
  'password_policy', 'password_confirmation_mismatch', 'reauthentication_required', 'account_locked',
  'invalid_name_length', 'passkey_not_found', 'passkey_not_owned', 'last_authentication_method', 'passkey_failed', 'account_refresh_failed'] as const;
export type AccountErrorCode = typeof knownErrors[number] | 'session_expired' | 'rate_limited' | 'save_failed';

export function accountErrorKey(error: unknown): AccountErrorCode {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'session_expired';
    if (error.status === 429) return 'rate_limited';
    const known = knownErrors.find((code) => code === error.errorCode);
    if (known) return known;
  }
  if (error instanceof Error && ['NotAllowedError', 'InvalidStateError', 'NotSupportedError', 'SecurityError', 'WebAuthnError'].includes(error.name)) return 'passkey_failed';
  return 'save_failed';
}
