import { afterEach, expect, it, vi } from 'vitest';
import { getBackendVersion } from '../buildIdentity';

afterEach(() => vi.restoreAllMocks());

it('fetches public build metadata without using the application GET cache', async () => {
  const payload = { application_version: '0.1.0', backend: { commit_sha: 'a'.repeat(40), build_time_utc: '2026-10-18T20:00:00Z' }, environment: 'test' };
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(payload)));
  expect(await getBackendVersion()).toEqual(payload);
  expect(fetch).toHaveBeenCalledWith('/api/version', { cache: 'no-store', signal: expect.any(AbortSignal) });
});

it.each([
  { postgres_version: 'old backend' },
  { application_version: '0.1.0', backend: { commit_sha: 'short', build_time_utc: null }, environment: 'test' },
  { application_version: '0.1.0', backend: { commit_sha: null, build_time_utc: 'invalid' }, environment: 'test' },
  null,
])('rejects older or invalid contracts as unavailable: %j', async (payload) => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(payload)));
  await expect(getBackendVersion()).rejects.toThrow('Build metadata contract unavailable');
});

it('rejects an unavailable backend instead of returning cached metadata', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 502 }));
  await expect(getBackendVersion()).rejects.toThrow('Build metadata unavailable');
});
