import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import PasswordRecovery from '../users/PasswordRecovery';
import ResetPasswordPage from '../ResetPasswordPage';
import i18n from '../i18n';
import * as recovery from '../users/passwordResetApi';

vi.mock('../users/passwordResetApi');

beforeEach(async () => {
  cleanup(); vi.resetAllMocks(); await i18n.changeLanguage('en');
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  vi.mocked(recovery.getRecoveryReadiness).mockResolvedValue({ email_delivery_ready: false });
  vi.mocked(recovery.createResetLink).mockResolvedValue({ reset_url: 'https://compass.example/reset-password#token=test-secret', expires_at: '2026-09-05T13:00:00Z', expires_in_minutes: 60 });
  vi.mocked(recovery.submitReset).mockResolvedValue({ password_min_length: 12 });
});

function renderRecovery() {
  return render(<MemoryRouter><Routes><Route path="/" element={<PasswordRecovery userId="staff" />} /><Route path="/admin/email" element={<h1>Email settings</h1>} /></Routes></MemoryRouter>);
}

describe('administrator password recovery', () => {
  it('keeps create available, explains unavailable email, and links to configuration', async () => {
    renderRecovery();
    expect(screen.getByRole('button', { name: 'Create password reset link' })).toBeEnabled();
    await screen.findByText('Email delivery unavailable');
    expect(screen.getByRole('button', { name: 'Send password reset email' })).toBeDisabled();
    expect(screen.getByText(/You can still create and copy/)).toBeVisible();
    fireEvent.click(screen.getByRole('link', { name: 'Configure email' }));
    expect(screen.getByRole('heading', { name: 'Email settings' })).toBeVisible();
  });
  it('copies with an announced confirmation and removes the raw link on close', async () => {
    const copy = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } });
    renderRecovery();
    fireEvent.click(screen.getByRole('button', { name: 'Create password reset link' }));
    const field = await screen.findByRole('textbox', { name: 'Password reset URL' });
    fireEvent.click(screen.getByRole('button', { name: 'Copy link' }));
    await screen.findByText('Link copied.');
    expect(copy).toHaveBeenCalledWith((field as HTMLInputElement).value);
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain('test-secret');
    fireEvent.click(screen.getByRole('button', { name: 'Create password reset link' }));
    await screen.findByRole('dialog');
    expect(recovery.createResetLink).toHaveBeenCalledTimes(2);
    expect(screen.queryByText('Link copied.')).not.toBeInTheDocument();
  });
  it('selects the URL for manual copying when clipboard access is unavailable', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    renderRecovery();
    fireEvent.click(screen.getByRole('button', { name: 'Create password reset link' }));
    const field = await screen.findByRole('textbox', { name: 'Password reset URL' });
    fireEvent.click(screen.getByRole('button', { name: 'Copy link' }));
    expect(await screen.findByText(/Use your device’s Copy command/)).toBeVisible();
    expect(field).toHaveFocus();
  });
  it('sends only when ready and contains delivery failures', async () => {
    vi.mocked(recovery.getRecoveryReadiness).mockResolvedValue({ email_delivery_ready: true });
    vi.mocked(recovery.sendResetEmail).mockResolvedValue({ success: true });
    renderRecovery();
    const send = screen.getByRole('button', { name: 'Send password reset email' });
    await waitFor(() => expect(send).toBeEnabled());
    fireEvent.click(send);
    await screen.findByText(/Password reset email sent/);
    vi.mocked(recovery.sendResetEmail).mockRejectedValue(new Error('SECRET provider response'));
    fireEvent.click(send);
    await screen.findByRole('alert');
    expect(document.body.textContent).not.toContain('SECRET');
    expect(screen.queryByText(/Password reset email sent/)).not.toBeInTheDocument();
  });
  it('renders Spanish recovery copy', async () => {
    await i18n.changeLanguage('es'); renderRecovery();
    expect(screen.getByRole('heading', { name: 'Recuperación de contraseña' })).toBeVisible();
    expect(await screen.findByText('Envío de correo no disponible')).toBeVisible();
  });
});

describe('public password reset', () => {
  it.each(['reset_invalid', 'reset_expired', 'reset_used'])('explains %s without exposing account metadata', async (code) => {
    vi.mocked(recovery.submitReset).mockRejectedValue(new Error(code));
    render(<MemoryRouter><ResetPasswordPage /></MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Ask your administrator');
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument();
  });
  it('removes the fragment, validates confirmation, and directs successful resets to sign in', async () => {
    window.history.replaceState(null, '', '/reset-password#token=private-token');
    render(<MemoryRouter><ResetPasswordPage /></MemoryRouter>);
    const password = await screen.findByLabelText('New password');
    expect(window.location.hash).toBe('');
    fireEvent.change(password, { target: { value: 'ReplacementCredential123!' } });
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'mismatch' } });
    fireEvent.click(screen.getByRole('button', { name: 'Set new password' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Passwords do not match');
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'ReplacementCredential123!' } });
    fireEvent.click(screen.getByRole('button', { name: 'Set new password' }));
    expect(await screen.findByRole('heading', { name: 'Password changed' })).toBeVisible();
    expect(recovery.submitReset).toHaveBeenCalledWith('complete', 'private-token', 'ReplacementCredential123!');
    expect(screen.getByRole('link', { name: 'Go to sign in' })).toHaveAttribute('href', '/login');
  });
});
