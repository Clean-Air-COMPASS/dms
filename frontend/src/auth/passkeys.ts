import {
  browserSupportsWebAuthnAutofill, startAuthentication, startRegistration,
} from '@simplewebauthn/browser';
import { apiErrorFromResponse } from '../apiError';
import { API_BASE } from '../apiBase';
import { acceptPasskeySession } from './authClient';

async function passkeyRequest(path: string, body: object, token?: string, signal?: AbortSignal) {
  const response = await fetch(`${API_BASE}/auth/passkeys/${path}`, {
    method: 'POST', credentials: 'include', signal,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.json();
}

export async function registerPasskey(token: string, signal: AbortSignal, enrollment?: { reauthentication_token: string; name?: string }): Promise<void> {
  const optionsJSON = await passkeyRequest('register/options', enrollment ? { reauthentication_token: enrollment.reauthentication_token } : {}, token, signal);
  if (signal.aborted) return;
  const credential = await startRegistration({ optionsJSON });
  if (signal.aborted) return;
  await passkeyRequest('register/verify', { credential, ...(enrollment ? { name: enrollment.name } : {}) }, token, signal);
}

export async function signInWithPasskeyAutofill(signal: AbortSignal): Promise<void> {
  if (!await browserSupportsWebAuthnAutofill() || signal.aborted) return;
  const optionsJSON = await passkeyRequest('login/options', {}, undefined, signal);
  if (signal.aborted) return;
  const credential = await startAuthentication({ optionsJSON, useBrowserAutofill: true });
  if (signal.aborted) return;
  const result = await passkeyRequest('login/verify', { credential }, undefined, signal);
  if (!signal.aborted) await acceptPasskeySession(result.access_token);
}
