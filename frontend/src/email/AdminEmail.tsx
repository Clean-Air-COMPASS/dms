import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ApiError } from '../apiError';
import AdminPageLayout from '../components/AdminPageLayout';
import { formatDisplayDateTime } from '../i18n/formatters';
import type { SupportedLanguageCode } from '../i18n/languagePreferences';
import { getEmailConfiguration, sendEmailTest } from './api';
import AdministratorSummarySection from './AdministratorSummarySection';
import EmailConfigurationForm from './EmailConfigurationForm';
import {
  reasonMessage,
  securityModeLabel,
  statusExplanation,
  statusLabel,
  testErrorMessage,
} from './presentation';
import type { AdministratorSummaryConfiguration, EmailConfiguration, EmailReadinessStatus } from './types';

function statusTone(status: EmailReadinessStatus): string {
  if (status === 'ready') return 'ready';
  if (status === 'needs_attention') return 'attention';
  if (status === 'disabled') return 'disabled';
  return 'neutral';
}

function displayValue(value: string | number | null, fallback: string): string {
  if (value === null || value === '') return fallback;
  return String(value);
}

function senderSummary(configuration: EmailConfiguration, fallback: string): string {
  if (!configuration.from_email) return fallback;
  if (!configuration.from_display_name) return configuration.from_email;
  return `${configuration.from_display_name} <${configuration.from_email}>`;
}

export default function AdminEmail() {
  const { t, i18n } = useTranslation('emailNotifications');
  const [configuration, setConfiguration] = useState<EmailConfiguration | null>(null);
  const [summaryConfiguration, setSummaryConfiguration] = useState<AdministratorSummaryConfiguration | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [editing, setEditing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [savedNotice, setSavedNotice] = useState(false);
  const [testRecipient, setTestRecipient] = useState('');
  const [testRecipientInvalid, setTestRecipientInvalid] = useState(false);
  const [sendingTest, setSendingTest] = useState(false);
  const [testSuccessRecipient, setTestSuccessRecipient] = useState<string | null>(null);
  const [testFailureCode, setTestFailureCode] = useState<string | null>(null);
  const [smtpResponseCode, setSmtpResponseCode] = useState<number | null>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const testResultRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const loadedConfiguration = await getEmailConfiguration();
      setConfiguration(loadedConfiguration);
      setEditing(loadedConfiguration.status === 'not_configured');
      setTestRecipient((current) => (
        current || loadedConfiguration.administrator_recipients[0] || ''
      ));
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const focusNotice = (ref: React.RefObject<HTMLDivElement | null>) => {
    window.requestAnimationFrame(() => ref.current?.focus());
  };

  const languageCode: SupportedLanguageCode = i18n.resolvedLanguage === 'es' ? 'es' : 'en';
  const notConfiguredLabel = t('common.notConfigured');

  const setupBlocker = configuration?.status_reason_codes.find((code) => [
    'email_not_configured', 'smtp_host_missing', 'smtp_port_missing',
    'smtp_security_mode_missing', 'from_email_missing', 'administrator_recipients_missing',
    'smtp_credentials_incomplete', 'unencrypted_smtp_credentials_not_allowed',
    'smtp_secret_unavailable', 'email_configuration_incomplete',
  ].includes(code));
  const testBlocked = !configuration?.enabled || Boolean(setupBlocker);
  const nextAction = configuration?.status === 'ready'
    ? summaryConfiguration?.enabled
      ? t('workflow.monitor')
      : t('workflow.summary')
    : testBlocked
      ? t('workflow.configure')
      : configuration?.last_test_status === 'failed'
        ? t('workflow.retry')
        : t('workflow.test');

  const sendTest = async () => {
    if (!configuration) return;
    const normalizedRecipient = testRecipient.trim();
    if (normalizedRecipient && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedRecipient)) {
      setTestRecipientInvalid(true);
      window.requestAnimationFrame(() => {
        document.getElementById('email-test-recipient')?.focus();
      });
      return;
    }

    setSendingTest(true);
    setTestRecipientInvalid(false);
    setTestSuccessRecipient(null);
    setTestFailureCode(null);
    setSmtpResponseCode(null);
    try {
      const defaultRecipient = configuration.administrator_recipients[0] ?? '';
      const recipientOverride = normalizedRecipient && normalizedRecipient !== defaultRecipient
        ? normalizedRecipient
        : undefined;
      const result = await sendEmailTest(recipientOverride);
      setTestSuccessRecipient(result.recipient);
      const refreshedConfiguration = await getEmailConfiguration();
      setConfiguration(refreshedConfiguration);
      focusNotice(testResultRef);
    } catch (error) {
      if (error instanceof ApiError) {
        setTestFailureCode(error.errorCode);
        const responseCode = error.errorContext.smtp_code;
        setSmtpResponseCode(typeof responseCode === 'number' ? responseCode : null);
      } else {
        setTestFailureCode('request_failed');
      }
      try {
        const refreshedConfiguration = await getEmailConfiguration();
        setConfiguration(refreshedConfiguration);
      } catch {
        // The test result remains useful even if the follow-up status refresh fails.
      }
      focusNotice(testResultRef);
    } finally {
      setSendingTest(false);
    }
  };

  const testDelivery = configuration ? (
    <section className="card email-test-card" aria-labelledby="email-test-title">
      <div className="email-section-heading">
        <div>
          <h2 id="email-test-title">{t('test.title')}</h2>
          <p>{t('test.description')}</p>
        </div>
        <span className="email-last-tested">{t(configuration.last_test_status === 'success' ? 'test.lastSuccess' : configuration.last_test_status === 'failed' ? 'test.lastFailure' : 'test.neverTested')}</span>
        {configuration.last_tested_at && (
          <span className="email-last-tested">
            {t('test.lastTested', {
              date: formatDisplayDateTime(configuration.last_tested_at, languageCode),
            })}
          </span>
        )}
      </div>

      {dirty && (
        <div className="warning-banner email-test-unsaved" role="note">
          {t('test.unsavedChanges')}
        </div>
      )}
      {testBlocked && (
        <div className="info-banner email-test-unsaved" role="note">
          {setupBlocker ? reasonMessage(setupBlocker) : t('test.disabled')}
        </div>
      )}

      <div className="email-test-controls">
        <label className="email-field">
          <span>{t('test.recipientLabel')}</span>
          <input
            id="email-test-recipient"
            type="email"
            aria-label={t('test.recipientLabel')}
            value={testRecipient}
            onChange={(event) => {
              setTestRecipient(event.target.value);
              setTestRecipientInvalid(false);
              setTestSuccessRecipient(null);
              setTestFailureCode(null);
            }}
            placeholder={t('test.recipientPlaceholder')}
            disabled={sendingTest}
            aria-invalid={testRecipientInvalid}
            aria-describedby={`email-test-recipient-help${testRecipientInvalid ? ' email-test-recipient-error' : ''}`}
          />
          <small id="email-test-recipient-help">{t('test.recipientHelp')}</small>
          {testRecipientInvalid && (
            <span className="email-field-error" id="email-test-recipient-error">
              {t('validation.invalidEmailAddress')}
            </span>
          )}
        </label>
        <button
          className="btn btn-primary"
          type="button"
          disabled={sendingTest || dirty || testBlocked}
          onClick={() => void sendTest()}
        >
          {sendingTest
            ? t('test.sending')
            : testFailureCode
              ? t('actions.retryTest')
              : t('test.sendAction')}
        </button>
      </div>

      {(testSuccessRecipient || testFailureCode) && (
        <div
          ref={testResultRef}
          className={testSuccessRecipient ? 'success-banner email-test-result' : 'error-banner email-test-result'}
          role={testSuccessRecipient ? 'status' : 'alert'}
          tabIndex={-1}
        >
          <strong>
            {testSuccessRecipient
              ? t('test.success', { recipient: testSuccessRecipient })
              : testFailureCode === 'request_failed'
                ? t('errors.testFailed')
                : testErrorMessage(testFailureCode ?? 'unknown')}
          </strong>
          {smtpResponseCode !== null && (
            <details>
              <summary>{t('test.moreDetails')}</summary>
              <p>{t('test.smtpResponseCode', { code: smtpResponseCode })}</p>
            </details>
          )}
        </div>
      )}
    </section>
  ) : null;

  return (
    <AdminPageLayout
      title={t('page.title')}
      description={t('page.description')}
      breadcrumbs={[
        { label: t('breadcrumbs.admin'), to: '/admin' },
        { label: t('breadcrumbs.email') },
      ]}
      contentClassName="admin-workspace email-admin-page"
    >
      {loading && <div className="info-banner email-state-banner">{t('states.loading')}</div>}
      {!loading && loadError && (
        <div className="error-banner email-state-banner" role="alert">
          <span>{t('errors.loadFailed')}</span>
          <button className="btn" type="button" onClick={() => void load()}>{t('actions.retry')}</button>
        </div>
      )}

      {!loading && !loadError && configuration && (
        <>
          {savedNotice && (
            <div ref={noticeRef} className="success-banner" role="status" tabIndex={-1}>
              {t('messages.saved')}
            </div>
          )}

          <section className="email-delivery-column" aria-labelledby="email-delivery-title">
            <div className="email-section-heading">
              <div>
                <h2 id="email-delivery-title">{t('workflow.deliveryTitle')}</h2>
                <p>{t('workflow.deliveryDescription')}</p>
              </div>
              {!editing && (
                <button id="email-edit-action" className={testBlocked ? 'btn btn-primary' : 'btn'} type="button" onClick={() => {
                  setEditing(true);
                  setSavedNotice(false);
                  setTestSuccessRecipient(null);
                  setTestFailureCode(null);
                  setSmtpResponseCode(null);
                  window.requestAnimationFrame(() => {
                    document.querySelector<HTMLInputElement>('.email-configuration-form input')?.focus();
                  });
                }}>
                  {t('actions.edit')}
                </button>
              )}
            </div>
            <div className={`card email-status-card email-status-${statusTone(configuration.status)}`} aria-label={t('overview.title')}>
              <div className="email-status-main" id="email-overall-status">
                <span className={`email-status-badge email-status-badge-${statusTone(configuration.status)}`}>
                  {statusLabel(configuration.status)}
                </span>
                <div>
                  <p>{configuration.status === 'not_configured'
                    ? t('workflow.setupHelp')
                    : configuration.status_reason_codes[0]
                      ? reasonMessage(configuration.status_reason_codes[0])
                      : statusExplanation(configuration.status)}</p>
                  {configuration.status === 'ready' && (
                    <p><span>{senderSummary(configuration, notConfiguredLabel)}</span> · <span>{t('overview.recipientCount', {
                      count: configuration.administrator_recipients.length,
                    })}</span></p>
                  )}
                </div>
              </div>
              <div className="email-next-action">
                <span>{t('overview.nextActionLabel')}</span>
                <strong>{nextAction}</strong>
              </div>
            </div>

            {editing ? (
              <EmailConfigurationForm
                configuration={configuration}
                onDirtyChange={setDirty}
                onCancel={() => {
                  setEditing(false);
                  setDirty(false);
                  setSavedNotice(false);
                  window.requestAnimationFrame(() => document.getElementById('email-edit-action')?.focus());
                }}
                onSaved={(savedConfiguration) => {
                  setConfiguration(savedConfiguration);
                  setEditing(false);
                  setDirty(false);
                  setSavedNotice(true);
                  setTestSuccessRecipient(null);
                  setTestFailureCode(null);
                  setSmtpResponseCode(null);
                  setTestRecipient(savedConfiguration.administrator_recipients[0] || '');
                  focusNotice(noticeRef);
                }}
              />
            ) : (
              <div className="email-summary-grid">
                <section className="card email-summary-card" aria-labelledby="email-smtp-summary">
                  <div className="email-section-heading">
                    <div>
                      <h3 id="email-smtp-summary">{t('summary.smtp.title')}</h3>
                      <p>{t('summary.smtp.description')}</p>
                    </div>
                  </div>
                  <dl>
                    <div><dt>{t('form.smtp.hostLabel')}</dt><dd>{displayValue(configuration.smtp_host, notConfiguredLabel)}</dd></div>
                    <div><dt>{t('form.smtp.portLabel')}</dt><dd>{displayValue(configuration.smtp_port, notConfiguredLabel)}</dd></div>
                    <div><dt>{t('form.smtp.securityLabel')}</dt><dd>{securityModeLabel(configuration.smtp_security_mode)}</dd></div>
                    <div><dt>{t('form.smtp.usernameLabel')}</dt><dd>{displayValue(configuration.smtp_username, t('common.notUsed'))}</dd></div>
                    <div><dt>{t('form.smtp.passwordLabel')}</dt><dd>{configuration.password_configured ? t('password.configured') : t('password.notConfigured')}</dd></div>
                  </dl>
                </section>

                <section className="card email-summary-card" aria-labelledby="email-sender-summary">
                  <div className="email-section-heading">
                    <div>
                      <h3 id="email-sender-summary">{t('summary.sender.title')}</h3>
                      <p>{t('summary.sender.description')}</p>
                    </div>
                  </div>
                  <dl>
                    <div><dt>{t('form.sender.fromEmailLabel')}</dt><dd>{displayValue(configuration.from_email, notConfiguredLabel)}</dd></div>
                    <div><dt>{t('form.sender.displayNameLabel')}</dt><dd>{displayValue(configuration.from_display_name, t('common.notUsed'))}</dd></div>
                    <div><dt>{t('form.sender.replyToLabel')}</dt><dd>{displayValue(configuration.reply_to_email, t('common.notUsed'))}</dd></div>
                  </dl>
                </section>

                <section className="card email-summary-card email-recipient-summary" aria-labelledby="email-recipient-summary">
                  <div className="email-section-heading">
                    <div>
                      <h3 id="email-recipient-summary">{t('summary.recipients.title')}</h3>
                      <p>{t('summary.recipients.description')}</p>
                    </div>
                  </div>
                  {configuration.administrator_recipients.length > 0 ? (
                    <ul>
                      {configuration.administrator_recipients.map((recipient) => (
                        <li key={recipient}>{recipient}</li>
                      ))}
                    </ul>
                  ) : <p className="email-empty-value">{t('summary.recipients.empty')}</p>}
                </section>
              </div>
            )}
          </section>
          {testDelivery}
          <AdministratorSummarySection
            defaultRecipient={configuration.administrator_recipients[0] ?? ''}
            deliveryConfiguration={configuration}
            onConfigurationChange={setSummaryConfiguration}
          />
        </>
      )}
    </AdminPageLayout>
  );
}
