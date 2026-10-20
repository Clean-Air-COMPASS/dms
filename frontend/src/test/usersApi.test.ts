import { expect, it, vi } from 'vitest';
import { deleteUser, updateUser } from '../api';
import { authFetch, authFetchJson } from '../auth';
vi.mock('../auth', () => ({ authFetch: vi.fn(), authFetchJson: vi.fn() }));

it('accepts the empty 204 response from user deletion', async () => {
  vi.mocked(authFetch).mockResolvedValue(new Response(null, { status: 204 }));
  await expect(deleteUser('staff')).resolves.toBeUndefined();
  expect(authFetch).toHaveBeenCalledWith('/admin/users/staff', { method: 'DELETE' });
});

it('sends optional names through the authorized Admin update endpoint', async () => {
  const payload = { first_name: '  María  ', last_name: null };
  const response = { display_name: 'María' };
  vi.mocked(authFetchJson).mockResolvedValue(response);
  await expect(updateUser('staff', payload)).resolves.toEqual(response);
  expect(authFetchJson).toHaveBeenCalledWith('/admin/users/staff', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
});
