import { beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';
import AdminUsersList from '../AdminUsersList';
import AdminUserNew from '../AdminUserNew';
import AdminUserDetail from '../AdminUserDetail';
import * as api from '../api';
import i18n from '../i18n';
import { ApiError } from '../apiError';

vi.mock('../api');
vi.mock('../users/PasswordRecovery', () => ({ default: () => <h2>Password recovery</h2> }));
vi.mock('../components/AdminPageLayout', () => ({ default: ({ title, children, actions }: { title: string; children: ReactNode; actions: ReactNode }) => <main><h1>{title}</h1>{actions}{children}</main> }));
const user = { user_id: 'staff', org_id: 'org', email: 'staff@example.org', roles: ['analyst'], is_active: true, failed_login_count: 3 };

beforeEach(async () => {
  cleanup(); vi.resetAllMocks(); await i18n.changeLanguage('en');
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  vi.mocked(api.listUsers).mockResolvedValue([user]);
  vi.mocked(api.getUser).mockResolvedValue(user);
  vi.mocked(api.listRoles).mockResolvedValue([{ role_id: '1', name: 'analyst' }, { role_id: '2', name: 'viewer' }]);
  vi.mocked(api.updateUser).mockImplementation(async (_, payload) => ({ ...user, ...payload }));
  vi.mocked(api.unlockUser).mockResolvedValue({ ...user, failed_login_count: 0 });
  vi.mocked(api.deleteUser).mockResolvedValue(undefined);
});

function usersPage(path: string) {
  render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/admin/users" element={<AdminUsersList />} />
    <Route path="/admin/users/new" element={<AdminUserNew />} />
    <Route path="/admin/users/:userId" element={<AdminUserDetail />} />
  </Routes></MemoryRouter>);
}

it.each(['en', 'es'])('keeps routine editing before recovery and deletion in %s document order', async (language) => {
  await i18n.changeLanguage(language);
  usersPage('/admin/users/staff');
  await screen.findByRole('heading', { name: 'staff@example.org' });
  expect(screen.getAllByRole('heading', { level: 2 }).map(heading => heading.textContent)).toEqual([
    i18n.t('auth:account.profile'),
    i18n.t('users:workspace.access'),
    i18n.t('users:adminUserDetail.headings.roles'),
    'Password recovery',
    i18n.t('users:recovery.deleteTitle'),
  ]);
});

it('filters Users and opens the selected account with recovery', async () => {
  usersPage('/admin/users');
  await screen.findByRole('link', { name: 'View staff@example.org' });
  fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), { target: { value: 'missing' } });
  expect(screen.getByText('No users found.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
  fireEvent.click(screen.getByRole('link', { name: 'View staff@example.org' }));
  expect(await screen.findByRole('heading', { name: 'Password recovery' })).toBeVisible();
});

it('shows the current display name alongside email in the Users list', async () => {
  vi.mocked(api.listUsers).mockResolvedValue([{ ...user, display_name: 'María García' }]);
  usersPage('/admin/users');
  expect(await screen.findByText('María García')).toBeVisible();
  expect(screen.getByRole('link', { name: 'View staff@example.org' })).toHaveTextContent('staff@example.orgMaría García');
});

it('creates a user with chosen roles and status after password confirmation', async () => {
  vi.mocked(api.createUser).mockResolvedValue(user);
  usersPage('/admin/users/new');
  await screen.findByRole('checkbox', { name: /^Analyst/ });
  fireEvent.change(screen.getByLabelText(/Email/), { target: { value: 'new@example.org' } });
  fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: 'CredentialCreation123!' } });
  fireEvent.change(screen.getByLabelText(/Confirm Password/), { target: { value: 'CredentialCreation123!' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /^Analyst/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Create User' }));
  await waitFor(() => expect(api.createUser).toHaveBeenCalledWith({ email: 'new@example.org', password: 'CredentialCreation123!', roles: ['analyst'], is_active: true }));
  expect(await screen.findByRole('heading', { name: 'staff@example.org' })).toBeVisible();
});

it('keeps creation validation in the form and Cancel returns to Users', async () => {
  usersPage('/admin/users/new');
  await screen.findByRole('checkbox', { name: /^Analyst/ });
  fireEvent.change(screen.getByLabelText(/Email/), { target: { value: 'new@example.org' } });
  fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: 'eight123' } });
  fireEvent.change(screen.getByLabelText(/Confirm Password/), { target: { value: 'eight123' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create User' }));
  expect(api.createUser).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(await screen.findByRole('heading', { name: 'Users' })).toBeVisible();
});

it('saves roles, changes account status with confirmation, and unlocks', async () => {
  usersPage('/admin/users/staff');
  await screen.findByRole('heading', { name: 'staff@example.org' });
  fireEvent.click(screen.getByRole('checkbox', { name: /^Viewer/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith('staff', { roles: ['analyst', 'viewer'] }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Disable User' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Disable User' }));
  fireEvent.click(screen.getByRole('button', { name: /^Disable$/ }));
  await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith('staff', { is_active: false }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Unlock Account' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Unlock Account' }));
  fireEvent.click(screen.getByRole('dialog').querySelector('.btn-primary')!);
  await waitFor(() => expect(api.unlockUser).toHaveBeenCalledWith('staff'));
});

it('deletes only after confirmation and returns to Users', async () => {
  usersPage('/admin/users/staff');
  fireEvent.click(await screen.findByRole('button', { name: 'Delete User' }));
  expect(api.deleteUser).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('dialog').querySelector('.btn-danger')!);
  expect(await screen.findByRole('heading', { name: 'Users' })).toBeVisible();
  expect(api.deleteUser).toHaveBeenCalledWith('staff');
});

it('keeps the account and role edits visible when the server rejects a protected role change', async () => {
  vi.mocked(api.getUser).mockResolvedValue({ ...user, roles: ['admin'] });
  vi.mocked(api.listRoles).mockResolvedValue([{ role_id: 'admin', name: 'admin' }]);
  vi.mocked(api.updateUser).mockRejectedValue(new ApiError({ status: 403 }));
  usersPage('/admin/users/staff');
  fireEvent.click(await screen.findByRole('checkbox', { name: /^Administrator/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t('common:errors.updateRoles'));
  expect(screen.getByText('Unsaved changes')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
  expect(screen.getByRole('heading', { name: 'staff@example.org' })).toBeVisible();
});

it.each([[null, null], ['', ''], ['María', 'García']])('populates optional profile names (%s, %s)', async (first, last) => {
  vi.mocked(api.getUser).mockResolvedValue({ ...user, first_name: first, last_name: last });
  usersPage('/admin/users/staff');
  expect(await screen.findByLabelText('First name')).toHaveValue(first ?? '');
  expect(screen.getByLabelText('Last name')).toHaveValue(last ?? '');
  expect(screen.getByLabelText('Email address')).toHaveAttribute('readonly');
  expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled();
  expect(screen.queryByRole('navigation', { name: 'Account management' })).not.toBeInTheDocument();
});

it('saves names independently and immediately displays the normalized server identity', async () => {
  let resolve!: (value: api.UserRecord) => void;
  vi.mocked(api.updateUser).mockReturnValue(new Promise(value => { resolve = value; }));
  usersPage('/admin/users/staff');
  fireEvent.change(await screen.findByLabelText('First name'), { target: { value: '  María  ' } });
  fireEvent.change(screen.getByLabelText('Last name'), { target: { value: 'García' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /^Viewer/ }));
  expect(api.updateUser).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
  expect(api.updateUser).toHaveBeenCalledWith('staff', { first_name: '  María  ', last_name: 'García' });
  expect(screen.getByLabelText('First name')).toBeDisabled();
  expect(screen.getByRole('checkbox', { name: /^Viewer/ })).toBeDisabled();
  resolve({ ...user, first_name: 'María', last_name: 'García', display_name: 'María García' });
  expect(await screen.findByRole('heading', { name: 'María García' })).toBeVisible();
  expect(screen.getByLabelText('First name')).toHaveValue('María');
  expect(screen.getByRole('status')).toHaveTextContent('Saved');
  // Saving identity must not discard unsaved role selections.
  expect(screen.getByRole('checkbox', { name: /^Viewer/ })).toBeChecked();
});

it.each([
  [new Error('offline'), 'The change could not be completed. Check your connection and try again.'],
  [new ApiError({ status: 422, errorCode: 'invalid_name_length' }), 'Use no more than 100 characters for each name.'],
])('preserves entered names when saving fails', async (error, message) => {
  vi.mocked(api.updateUser).mockRejectedValue(error);
  usersPage('/admin/users/staff');
  const first = await screen.findByLabelText('First name');
  expect(first).toHaveAttribute('maxlength', '100');
  expect(screen.getByLabelText('Last name')).toHaveAttribute('maxlength', '100');
  fireEvent.change(first, { target: { value: 'María' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(message);
  expect(first).toHaveValue('María');
  expect(screen.getByRole('button', { name: 'Save profile' })).toBeEnabled();
});
