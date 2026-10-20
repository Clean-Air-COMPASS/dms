import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ApiError } from '../apiError';
import { updateEmailConfiguration } from './api';
import EmailConfirmationDialog from './EmailConfirmationDialog';
import { saveErrorMessage } from './presentation';
import type {
  EmailConfiguration,
  EmailConfigurationUpdate,
  SmtpSecurityMode,
} from './types';

const MAX_ADMINISTRATOR_RECIPIENTS = 50;

type PasswordIntent = 'preserve' | 'replace' | 'clear';

interface FormValues {
  enabled: boolean;
  smtp_host: string;
  smtp_port: string;
  smtp_security_mode: SmtpSecurityMode | '';
  smtp_username: string;
  from_email: string;
  from_display_name: string;
  reply_to_email: string;
  administrator_recipients: string[];
}

interface ValidationErrors {
  [fieldName: string]: string | undefined;
}

interface EmailConfigurationFormProps {
  configuration: EmailConfiguration;
  onSaved: (configuration: EmailConfiguration) => void;
  onCancel: () => void;
  onDirtyChange: (dirty: boolean) => void;
}

function formValuesFromConfiguration(configuration: EmailConfiguration): FormValues {
  const isFresh = configuration.status === 'not_configured';
  return {
    enabled: isFresh ? true : configuration.enabled,
    smtp_host: configuration.smtp_host ?? '',
    smtp_port: configuration.smtp_port === null
      ? isFresh ? '587' : ''
      : String(configuration.smtp_port),
    smtp_security_mode: configuration.smtp_security_mode ?? (isFresh ? 'starttls' : ''),
    smtp_username: configuration.smtp_username ?? '',
    from_email: configuration.from_email ?? '',
    from_display_name: configuration.from_display_name ?? '',
    reply_to_email: configuration.reply_to_email ?? '',
    administrator_recipients: configuration.administrator_recipients.length > 0
      ? [...configuration.administrator_recipients]
      : [''],
  };
}

function normalizedValues(values: FormValues): FormValues {
  return {
    ...values,
    smtp_host: values.smtp_host.trim(),
    smtp_port: values.smtp_port.trim(),
    smtp_username: values.smtp_username.trim(),
    from_email: values.from_email.trim(),
    from_display_name: values.from_display_name.trim(),
    reply_to_email: values.reply_to_email.trim(),
    administrator_recipients: values.administrator_recipients.map((recipient) => recipient.trim()),
  };
}

function valuesAreEqual(left: FormValues, right: FormValues): boolean {
  return JSON.stringify(normalizedValues(left)) === JSON.stringify(normalizedValues(right));
}

function isValidEmailAddress(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function fieldErrorId(fieldName: string): string {
  return `email-${fieldName.replace(/[^a-zA-Z0-9_-]/g, '-')}-error`;
}

export default function EmailConfigurationForm({
  configuration,
  onSaved,
  onCancel,
  onDirtyChange,
}: EmailConfigurationFormProps) {
  const { t } = useTranslation('emailNotifications');
  const initialValues = useMemo(
    () => formValuesFromConfiguration(configuration),
    [configuration],
  );
  const [values, setValues] = useState<FormValues>(initialValues);
  const [passwordIntent, setPasswordIntent] = useState<PasswordIntent>('preserve');
  const [replacementPassword, setReplacementPassword] = useState('');
  const [validationErrors, setValidationErrors] = useState<ValidationErrors>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [unencryptedDialogOpen, setUnencryptedDialogOpen] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  const dirty = !valuesAreEqual(values, initialValues)
    || passwordIntent !== 'preserve'
    || replacementPassword !== '';

  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  const updateValue = <FieldName extends keyof FormValues>(
    fieldName: FieldName,
    value: FormValues[FieldName],
  ) => {
    setValues((current) => ({ ...current, [fieldName]: value }));
    setValidationErrors((current) => ({ ...current, [fieldName]: undefined }));
    setSaveError(null);
  };

  const updateRecipient = (index: number, recipient: string) => {
    setValues((current) => ({
      ...current,
      administrator_recipients: current.administrator_recipients.map(
        (currentRecipient, currentIndex) => currentIndex === index ? recipient : currentRecipient,
      ),
    }));
    setValidationErrors((current) => ({
      ...current,
      [`administrator_recipients[${index}]`]: undefined,
      administrator_recipients: undefined,
    }));
    setSaveError(null);
  };

  const removeRecipient = (index: number) => {
    setValues((current) => {
      const remainingRecipients = current.administrator_recipients.filter(
        (_, currentIndex) => currentIndex !== index,
      );
      return {
        ...current,
        administrator_recipients: remainingRecipients.length > 0 ? remainingRecipients : [''],
      };
    });
    setValidationErrors({});
    setSaveError(null);
  };

  const validate = (): ValidationErrors => {
    const errors: ValidationErrors = {};
    const normalized = normalizedValues(values);
    const recipients = normalized.administrator_recipients.filter(Boolean);
    const effectivePasswordConfigured = passwordIntent === 'clear'
      ? false
      : passwordIntent === 'replace'
        ? replacementPassword.length > 0
        : configuration.password_configured;

    if (normalized.smtp_host && /[\s/@\\]/.test(normalized.smtp_host)) {
      errors.smtp_host = t('validation.invalidSmtpHost');
    }
    if (normalized.smtp_port) {
      const port = Number(normalized.smtp_port);
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        errors.smtp_port = t('validation.invalidSmtpPort');
      }
    }
    if (normalized.from_email && !isValidEmailAddress(normalized.from_email)) {
      errors.from_email = t('validation.invalidEmailAddress');
    }
    if (normalized.reply_to_email && !isValidEmailAddress(normalized.reply_to_email)) {
      errors.reply_to_email = t('validation.invalidEmailAddress');
    }
    normalized.administrator_recipients.forEach((recipient, index) => {
      if (recipient && !isValidEmailAddress(recipient)) {
        errors[`administrator_recipients[${index}]`] = t('validation.invalidEmailAddress');
      }
    });
    if (recipients.length > MAX_ADMINISTRATOR_RECIPIENTS) {
      errors.administrator_recipients = t('validation.tooManyRecipients');
    }
    const recipientKeys = recipients.map((recipient) => recipient.toLocaleLowerCase());
    if (new Set(recipientKeys).size !== recipientKeys.length) {
      errors.administrator_recipients = t('validation.duplicateRecipients');
    }
    if (passwordIntent === 'replace' && replacementPassword.length === 0) {
      errors.smtp_password = t('validation.emptyPassword');
    }
    if (replacementPassword.length > 4096) {
      errors.smtp_password = t('validation.passwordTooLong');
    }
    if (normalized.smtp_security_mode === 'none'
        && (normalized.smtp_username || effectivePasswordConfigured)) {
      errors.smtp_security_mode = t('validation.unencryptedCredentials');
    }

    if (normalized.enabled) {
      if (!normalized.smtp_host) errors.smtp_host = t('validation.required');
      if (!normalized.smtp_port) errors.smtp_port = t('validation.required');
      if (!normalized.smtp_security_mode) errors.smtp_security_mode = t('validation.required');
      if (!normalized.from_email) errors.from_email = t('validation.required');
      if (recipients.length === 0) {
        errors.administrator_recipients = t('validation.recipientRequired');
      }
      if (Boolean(normalized.smtp_username) !== effectivePasswordConfigured) {
        errors.smtp_username = t('validation.credentialsTogether');
        errors.smtp_password = t('validation.credentialsTogether');
      }
    }
    return errors;
  };

  const focusFirstError = () => {
    window.requestAnimationFrame(() => {
      formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    });
  };

  const save = async () => {
    const errors = validate();
    if (Object.values(errors).some(Boolean)) {
      setValidationErrors(errors);
      focusFirstError();
      return;
    }

    const normalized = normalizedValues(values);
    const update: EmailConfigurationUpdate = {
      enabled: normalized.enabled,
      smtp_host: normalized.smtp_host || null,
      smtp_port: normalized.smtp_port ? Number(normalized.smtp_port) : null,
      smtp_security_mode: normalized.smtp_security_mode || null,
      smtp_username: normalized.smtp_username || null,
      from_email: normalized.from_email || null,
      from_display_name: normalized.from_display_name || null,
      reply_to_email: normalized.reply_to_email || null,
      administrator_recipients: normalized.administrator_recipients.filter(Boolean),
    };
    if (passwordIntent === 'replace') update.smtp_password = replacementPassword;
    if (passwordIntent === 'clear') update.smtp_password = null;

    setSaving(true);
    setSaveError(null);
    try {
      const savedConfiguration = await updateEmailConfiguration(update);
      setReplacementPassword('');
      setPasswordIntent('preserve');
      onSaved(savedConfiguration);
    } catch (error) {
      if (error instanceof ApiError) {
        setSaveError(saveErrorMessage(error.errorCode));
        const field = error.errorContext.field;
        if (typeof field === 'string') {
          setValidationErrors((current) => ({
            ...current,
            [field]: saveErrorMessage(error.errorCode),
          }));
          focusFirstError();
        }
      } else {
        setSaveError(t('errors.saveFailed'));
      }
    } finally {
      setSaving(false);
    }
  };

  const requestSave = () => {
    const errors = validate();
    if (Object.values(errors).some(Boolean)) {
      setValidationErrors(errors);
      focusFirstError();
      return;
    }
    if (values.smtp_security_mode === 'none') {
      setUnencryptedDialogOpen(true);
      return;
    }
    void save();
  };

  const fieldError = (fieldName: string) => validationErrors[fieldName];
  const describedBy = (fieldName: string, helpId?: string) => {
    const ids = [helpId, fieldError(fieldName) ? fieldErrorId(fieldName) : null].filter(Boolean);
    return ids.length > 0 ? ids.join(' ') : undefined;
  };

  return (
    <form
      ref={formRef}
      className="email-configuration-form"
      aria-label={t('form.delivery.title')}
      onSubmit={(event) => {
        event.preventDefault();
        requestSave();
      }}
      noValidate
    >
      <div className="card email-edit-intro">
        <label className="email-switch-row">
          <input
            type="checkbox"
            aria-label={t('form.delivery.enabledLabel')}
            checked={values.enabled}
            onChange={(event) => updateValue('enabled', event.target.checked)}
          />
          <span>
            <strong>{t('form.delivery.enabledLabel')}</strong>
            <small>{t('form.delivery.enabledHelp')}</small>
          </span>
        </label>
      </div>

      <section className="card email-form-section" aria-labelledby="email-smtp-title">
        <div className="email-section-heading">
          <div>
            <h3 id="email-smtp-title">{t('form.smtp.title')}</h3>
            <p>{t('form.smtp.description')}</p>
          </div>
        </div>
        <div className="email-form-grid email-form-grid-smtp">
          <label className="email-field">
            <span>{t('form.smtp.hostLabel')}</span>
            <input
              name="smtp_host"
              value={values.smtp_host}
              onChange={(event) => updateValue('smtp_host', event.target.value)}
              placeholder={t('form.smtp.hostPlaceholder')}
              aria-label={t('form.smtp.hostLabel')}
              autoComplete="off"
              aria-invalid={Boolean(fieldError('smtp_host'))}
              aria-describedby={describedBy('smtp_host', 'email-smtp-host-help')}
            />
            <small id="email-smtp-host-help">{t('form.smtp.hostHelp')}</small>
            {fieldError('smtp_host') && (
              <span className="email-field-error" id={fieldErrorId('smtp_host')}>{fieldError('smtp_host')}</span>
            )}
          </label>
          <label className="email-field email-port-field">
            <span>{t('form.smtp.portLabel')}</span>
            <input
              name="smtp_port"
              type="number"
              min="1"
              max="65535"
              inputMode="numeric"
              aria-label={t('form.smtp.portLabel')}
              value={values.smtp_port}
              onChange={(event) => updateValue('smtp_port', event.target.value)}
              aria-invalid={Boolean(fieldError('smtp_port'))}
              aria-describedby={describedBy('smtp_port', 'email-smtp-port-help')}
            />
            <small id="email-smtp-port-help">{t('form.smtp.portHelp')}</small>
            {fieldError('smtp_port') && (
              <span className="email-field-error" id={fieldErrorId('smtp_port')}>{fieldError('smtp_port')}</span>
            )}
          </label>
          <label className="email-field">
            <span>{t('form.smtp.securityLabel')}</span>
            <select
              name="smtp_security_mode"
              aria-label={t('form.smtp.securityLabel')}
              value={values.smtp_security_mode}
              onChange={(event) => updateValue(
                'smtp_security_mode',
                event.target.value as SmtpSecurityMode | '',
              )}
              aria-invalid={Boolean(fieldError('smtp_security_mode'))}
              aria-describedby={describedBy('smtp_security_mode', 'email-security-help')}
            >
              <option value="">{t('form.smtp.securityPlaceholder')}</option>
              <option value="starttls">{t('security.options.starttls')}</option>
              <option value="ssl_tls">{t('security.options.ssl_tls')}</option>
              <option value="none">{t('security.options.none')}</option>
            </select>
            <small id="email-security-help">{t('form.smtp.securityHelp')}</small>
            {fieldError('smtp_security_mode') && (
              <span className="email-field-error" id={fieldErrorId('smtp_security_mode')}>{fieldError('smtp_security_mode')}</span>
            )}
          </label>
          <label className="email-field">
            <span>{t('form.smtp.usernameLabel')}</span>
            <input
              name="smtp_username"
              aria-label={t('form.smtp.usernameLabel')}
              value={values.smtp_username}
              onChange={(event) => updateValue('smtp_username', event.target.value)}
              autoComplete="off"
              aria-invalid={Boolean(fieldError('smtp_username'))}
              aria-describedby={describedBy('smtp_username', 'email-username-help')}
            />
            <small id="email-username-help">{t('form.smtp.usernameHelp')}</small>
            {fieldError('smtp_username') && (
              <span className="email-field-error" id={fieldErrorId('smtp_username')}>{fieldError('smtp_username')}</span>
            )}
          </label>
        </div>

        {values.smtp_security_mode === 'none' && (
          <div className="warning-banner email-security-warning" role="note">
            <strong>{t('security.warningTitle')}</strong>
            <span>{t('security.warningDescription')}</span>
          </div>
        )}

        <div className="email-password-panel">
          <div>
            <span className="email-field-label">{t('form.smtp.passwordLabel')}</span>
            <strong>
              {passwordIntent === 'clear'
                ? t('password.willClear')
                : configuration.password_configured
                  ? t('password.configured')
                  : t('password.notConfigured')}
            </strong>
            <small>{t('password.writeOnlyHelp')}</small>
          </div>

          {passwordIntent === 'replace' || !configuration.password_configured ? (
            <label className="email-field email-password-field">
              <span>
                {configuration.password_configured
                  ? t('password.replacementLabel')
                  : t('password.newLabel')}
              </span>
              <input
                name="smtp_password"
                type="password"
                aria-label={configuration.password_configured
                  ? t('password.replacementLabel')
                  : t('password.newLabel')}
                value={replacementPassword}
                onChange={(event) => {
                  const password = event.target.value;
                  setReplacementPassword(password);
                  setPasswordIntent(
                    password.length > 0 || configuration.password_configured
                      ? 'replace'
                      : 'preserve',
                  );
                  setValidationErrors((current) => ({ ...current, smtp_password: undefined }));
                  setSaveError(null);
                }}
                autoComplete="new-password"
                aria-invalid={Boolean(fieldError('smtp_password'))}
                aria-describedby={describedBy('smtp_password', 'email-password-help')}
              />
              <small id="email-password-help">{t('password.inputHelp')}</small>
              {fieldError('smtp_password') && (
                <span className="email-field-error" id={fieldErrorId('smtp_password')}>{fieldError('smtp_password')}</span>
              )}
            </label>
          ) : null}

          <div className="email-password-actions">
            {configuration.password_configured && passwordIntent === 'preserve' && (
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setPasswordIntent('replace');
                  setReplacementPassword('');
                }}
              >
                {t('password.replaceAction')}
              </button>
            )}
            {configuration.password_configured && passwordIntent !== 'clear' && (
              <button className="btn btn-danger" type="button" onClick={() => setClearDialogOpen(true)}>
                {t('password.clearAction')}
              </button>
            )}
            {passwordIntent !== 'preserve' && configuration.password_configured && (
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setPasswordIntent('preserve');
                  setReplacementPassword('');
                  setValidationErrors((current) => ({ ...current, smtp_password: undefined }));
                }}
              >
                {t('password.keepAction')}
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="card email-form-section" aria-labelledby="email-sender-title">
        <div className="email-section-heading">
          <div>
            <h3 id="email-sender-title">{t('form.sender.title')}</h3>
            <p>{t('form.sender.description')}</p>
          </div>
        </div>
        <div className="email-form-grid">
          <label className="email-field">
            <span>{t('form.sender.fromEmailLabel')}</span>
            <input
              name="from_email"
              type="email"
              aria-label={t('form.sender.fromEmailLabel')}
              value={values.from_email}
              onChange={(event) => updateValue('from_email', event.target.value)}
              autoComplete="email"
              aria-invalid={Boolean(fieldError('from_email'))}
              aria-describedby={describedBy('from_email')}
            />
            {fieldError('from_email') && (
              <span className="email-field-error" id={fieldErrorId('from_email')}>{fieldError('from_email')}</span>
            )}
          </label>
          <label className="email-field">
            <span>{t('form.sender.displayNameLabel')}</span>
            <input
              name="from_display_name"
              aria-label={t('form.sender.displayNameLabel')}
              value={values.from_display_name}
              onChange={(event) => updateValue('from_display_name', event.target.value)}
              autoComplete="organization"
            />
          </label>
          <label className="email-field">
            <span>{t('form.sender.replyToLabel')}</span>
            <input
              name="reply_to_email"
              type="email"
              aria-label={t('form.sender.replyToLabel')}
              value={values.reply_to_email}
              onChange={(event) => updateValue('reply_to_email', event.target.value)}
              autoComplete="email"
              aria-invalid={Boolean(fieldError('reply_to_email'))}
              aria-describedby={describedBy('reply_to_email', 'email-reply-to-help')}
            />
            <small id="email-reply-to-help">{t('form.sender.replyToHelp')}</small>
            {fieldError('reply_to_email') && (
              <span className="email-field-error" id={fieldErrorId('reply_to_email')}>{fieldError('reply_to_email')}</span>
            )}
          </label>
        </div>
      </section>

      <section className="card email-form-section" aria-labelledby="email-recipients-title">
        <div className="email-section-heading email-recipient-heading">
          <div>
            <h3 id="email-recipients-title">{t('form.recipients.title')}</h3>
            <p>{t('form.recipients.description')}</p>
          </div>
          <span>{t('form.recipients.count', {
            count: values.administrator_recipients.filter((recipient) => recipient.trim()).length,
            maximum: MAX_ADMINISTRATOR_RECIPIENTS,
          })}</span>
        </div>
        <div className="email-recipient-list">
          {values.administrator_recipients.map((recipient, index) => {
            const fieldName = `administrator_recipients[${index}]`;
            return (
              <div className="email-recipient-row" key={index}>
                <label className="email-field">
                  <span>{t('form.recipients.addressLabel', { number: index + 1 })}</span>
                  <input
                    name={fieldName}
                    type="email"
                    aria-label={t('form.recipients.addressLabel', { number: index + 1 })}
                    value={recipient}
                    onChange={(event) => updateRecipient(index, event.target.value)}
                    autoComplete="email"
                    aria-invalid={Boolean(fieldError(fieldName))}
                    aria-describedby={describedBy(fieldName)}
                  />
                  {fieldError(fieldName) && (
                    <span className="email-field-error" id={fieldErrorId(fieldName)}>{fieldError(fieldName)}</span>
                  )}
                </label>
                <button
                  className="btn email-remove-recipient"
                  type="button"
                  onClick={() => removeRecipient(index)}
                  aria-label={t('form.recipients.removeLabel', { number: index + 1 })}
                >
                  {t('form.recipients.removeAction')}
                </button>
              </div>
            );
          })}
        </div>
        {fieldError('administrator_recipients') && (
          <span
            className="email-field-error"
            id={fieldErrorId('administrator_recipients')}
            role="alert"
          >
            {fieldError('administrator_recipients')}
          </span>
        )}
        <button
          className="btn email-add-recipient"
          type="button"
          disabled={values.administrator_recipients.length >= MAX_ADMINISTRATOR_RECIPIENTS}
          onClick={() => updateValue(
            'administrator_recipients',
            [...values.administrator_recipients, ''],
          )}
        >
          {t('form.recipients.addAction')}
        </button>
      </section>

      {saveError && <div className="error-banner" role="alert">{saveError}</div>}

      <div className="email-form-actions">
        <button className="btn" type="button" onClick={onCancel} disabled={saving}>
          {t('actions.cancel')}
        </button>
        <button className="btn btn-primary" type="submit" disabled={!dirty || saving}>
          {saving ? t('actions.saving') : t('actions.save')}
        </button>
      </div>

      <EmailConfirmationDialog
        open={clearDialogOpen}
        title={t('password.clearDialog.title')}
        description={t('password.clearDialog.description')}
        confirmLabel={t('password.clearDialog.confirm')}
        onCancel={() => setClearDialogOpen(false)}
        onConfirm={() => {
          setPasswordIntent('clear');
          setReplacementPassword('');
          setClearDialogOpen(false);
        }}
      />
      <EmailConfirmationDialog
        open={unencryptedDialogOpen}
        title={t('security.confirmDialog.title')}
        description={t('security.confirmDialog.description')}
        confirmLabel={t('security.confirmDialog.confirm')}
        tone="primary"
        busy={saving}
        onCancel={() => setUnencryptedDialogOpen(false)}
        onConfirm={() => {
          setUnencryptedDialogOpen(false);
          void save();
        }}
      />
    </form>
  );
}
