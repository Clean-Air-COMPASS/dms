import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import i18n from '../i18n';
import LoginPage from '../LoginPage';
import OpenAQFields from '../OpenAQFields';
import DateTimeRangePicker from '../components/DateTimeRangePicker';
import AdminQcParameterDetail from '../qc/AdminQcParameterDetail';
import { roleLabel, roleDescription } from '../rolePresentation';

const mocks = vi.hoisted(() => ({ login: vi.fn(), policy: vi.fn() }));
vi.mock('../auth', () => ({ useAuth: () => ({ login: mocks.login, isAuthenticated: false, isLoading: false }), authFetchJson: vi.fn() }));
vi.mock('../auth/passkeys', () => ({ signInWithPasskeyAutofill: vi.fn().mockResolvedValue(undefined) }));
vi.mock('../qc/api', async () => ({ ...await vi.importActual('../qc/api'), getParameterPolicy: mocks.policy, listQcChecks: vi.fn().mockResolvedValue([]), listQcParameters: vi.fn().mockResolvedValue({ items: [] }) }));

beforeEach(async () => { vi.clearAllMocks(); await i18n.changeLanguage('en'); });

it.each([401, 429, 503, undefined])('classifies login status %s without raw diagnostics', async statusCode => {
  mocks.login.mockResolvedValue({ success: false, statusCode, error: 'Private infrastructure diagnostic' });
  const user = userEvent.setup();
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  await user.type(screen.getByLabelText('Email'), 'fixture@example.org');
  await user.type(screen.getByLabelText('Password'), 'fixture-password');
  await user.click(screen.getByRole('button', { name: 'Sign In' }));
  const key = statusCode === 401 ? 'invalidCredentials' : statusCode === 429 ? 'tooManyAttempts' : 'serviceUnavailable';
  expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t(`auth:loginPage.messages.${key}`));
  expect(screen.getByRole('alert')).not.toHaveTextContent('Private infrastructure diagnostic');
});

it('associates OpenAQ visible labels with editable number inputs', () => {
  render(<OpenAQFields apiEditing={{}} setApiEditing={vi.fn()} selectedExternalAPI={null} apiParamsText="{}" setApiParamsText={vi.fn()} />);
  expect(screen.getByRole('spinbutton', { name: i18n.t('dataSources:openAQFields.text.rateLimitPerMinute') })).toBe(screen.getByLabelText(i18n.t('dataSources:openAQFields.text.rateLimitPerMinute')));
  expect(screen.getByRole('spinbutton', { name: i18n.t('dataSources:openAQFields.text.rateLimitPerHour') })).toBeInTheDocument();
});

it('keeps the known QC parameter, breadcrumbs and retry on failure', async () => {
  mocks.policy.mockRejectedValue(new Error('Fixture outage'));
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={[{ pathname: '/admin/qc/parameters/1', state: { parameterName: 'PM2.5' } }]}><Routes><Route path="/admin/qc/parameters/:parameterId" element={<AdminQcParameterDetail />} /></Routes></MemoryRouter>);
  const alert = await screen.findByRole('alert');
  expect(screen.getByRole('heading', { name: 'PM2.5' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Quality control' })).toHaveAttribute('href', '/admin/qc');
  await user.click(within(alert).getByRole('button', { name: 'Try again' }));
  expect(mocks.policy).toHaveBeenCalledTimes(2);
});

it('localizes known role names and descriptions while preserving unknown roles', async () => {
  await i18n.changeLanguage('es');
  expect(roleLabel('admin')).toBe('Administrador');
  expect(roleLabel('analyst')).toBe('Analista');
  expect(roleDescription('viewer', 'Read-only access')).toBe('Acceso de solo lectura');
  expect(roleLabel('custom-role')).toBe('custom-role');
});

it('uses Spanish calendar chrome and preserves selected dates', async () => {
  await i18n.changeLanguage('es');
  const apply = vi.fn();
  render(<DateTimeRangePicker open startIso="2026-01-15T12:00:00Z" endIso="2026-01-16T12:00:00Z" onApply={apply} onClose={vi.fn()} onClear={vi.fn()} />);
  expect(screen.getByText('enero 2026')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Mes siguiente' })).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: i18n.t('analytics:dateTimeRangePicker.accessibility.applyRange') }));
  expect(apply).toHaveBeenCalledWith('2026-01-15T12:00:00.000Z', '2026-01-16T12:00:00.000Z');
});
