import i18n from '../i18n';
import React, { useState } from 'react';

interface PasswordInputProps {
  id: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  disabled?: boolean;
  placeholder?: string;
  autoComplete?: string;
  className?: string;
  name?: string;
}

export default function PasswordInput({
  id,
  value,
  onChange,
  disabled = false,
  placeholder,
  autoComplete,
  className,
  name,
}: PasswordInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="password-input-wrapper">
      <input
        id={id}
        name={name}
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={onChange}
        disabled={disabled}
        className={className || 'setup-form-input'}
        placeholder={placeholder}
        autoComplete={autoComplete}
      />

      <button
        type="button"
        aria-label={visible ? i18n.t('auth:passwordInput.actions.hidePassword') : i18n.t('auth:passwordInput.actions.showPassword')}
        aria-pressed={visible}
        className="password-toggle-btn"
        onClick={() => setVisible(v => !v)}
      >
        {visible ? (
          
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-5 0-9.27-3-11-8 1.03-2.64 2.8-4.79 4.93-6.23" />
            <path d="M1 1l22 22" />
          </svg>
        ) : (
          
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  );
}
