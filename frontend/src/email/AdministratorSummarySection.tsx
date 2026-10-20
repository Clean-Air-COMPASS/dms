import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ApiError } from '../apiError';
import { formatDisplayDateTime } from '../i18n/formatters';
import type { SupportedLanguageCode } from '../i18n/languagePreferences';
import { getSelectableIanaTimezones } from '../utils/timezone';
import {
  getAdministratorSummaryConfiguration,
  previewAdministratorSummary,
  sendAdministratorSummaryTest,
  updateAdministratorSummaryConfiguration,
} from './api';
import { reasonMessage, testErrorMessage } from './presentation';
import type {
  AdministratorSummaryCadence,
  AdministratorSummaryConfiguration,
  AdministratorSummaryPreview,
  EmailConfiguration,
} from './types';

const SYSTEM_TIMEZONE_OPTION = '__system_timezone__';

interface ScheduleForm {
  enabled: boolean;
  cadence: AdministratorSummaryCadence;
  dailySendTime: string;
  reportingTimezone: string;
  reportingTimezoneMode: 'system' | 'override';
  reportingTimezoneOverride: string | null;
  systemTimezone: string;
}

function formFromConfiguration(
  configuration: AdministratorSummaryConfiguration,
): ScheduleForm {
  return {
    enabled: configuration.enabled,
    cadence: configuration.cadence,
    dailySendTime: configuration.daily_send_time.slice(0, 5),
    reportingTimezone: configuration.reporting_timezone,
    reportingTimezoneMode: configuration.reporting_timezone_source === 'system_preferences'
      ? 'system'
      : 'override',
    reportingTimezoneOverride: configuration.reporting_timezone_override,
    systemTimezone: configuration.system_timezone,
  };
}

function dateTimeInTimezone(
  value: string,
  languageCode: SupportedLanguageCode,
  reportingTimezone: string,
): string {
  return new Intl.DateTimeFormat(languageCode, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: reportingTimezone,
  }).format(new Date(value));
}

function reportingPeriod(
  periodStart: string,
  periodEnd: string,
  languageCode: SupportedLanguageCode,
  reportingTimezone: string,
): string {
  const formatter = new Intl.DateTimeFormat(languageCode, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: reportingTimezone,
  });
  return `${formatter.format(new Date(periodStart))} – ${formatter.format(new Date(periodEnd))}`;
}

function wallClockTime(value: string, languageCode: SupportedLanguageCode): string {
  const [hour, minute] = value.split(':').map(Number);
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return value || '—';
  return new Intl.DateTimeFormat(languageCode, {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(2020, 0, 1, hour, minute)));
}

interface AdministratorSummarySectionProps {
  defaultRecipient: string;
  deliveryConfiguration?: EmailConfiguration;
  onConfigurationChange?: (configuration: AdministratorSummaryConfiguration) => void;
}

export default function AdministratorSummarySection({
  defaultRecipient,
  deliveryConfiguration,
  onConfigurationChange,
}: AdministratorSummarySectionProps) {
  const { t, i18n } = useTranslation('emailNotifications');
  const [configuration, setConfiguration] = useState<AdministratorSummaryConfiguration | null>(null);
  const [form, setForm] = useState<ScheduleForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [saved, setSaved] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [preview, setPreview] = useState<AdministratorSummaryPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState(false);
  const [previewMode, setPreviewMode] = useState<'html' | 'text'>('html');
  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [testRecipient, setTestRecipient] = useState('');
  const [testRecipientInvalid, setTestRecipientInvalid] = useState(false);
  const [sendingTest, setSendingTest] = useState(false);
  const [testSuccessRecipient, setTestSuccessRecipient] = useState<string | null>(null);
  const [testFailureCode, setTestFailureCode] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLElement>(null);

  const languageCode: SupportedLanguageCode = i18n.resolvedLanguage === 'es' ? 'es' : 'en';

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const loaded = await getAdministratorSummaryConfiguration();
      setConfiguration(loaded);
      setForm(formFromConfiguration(loaded));
      setAdvancedOpen(loaded.cadence !== 'daily');
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (configuration) onConfigurationChange?.(configuration);
  }, [configuration, onConfigurationChange]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (saved || saveError || previewError || testSuccessRecipient || testFailureCode) {
      resultRef.current?.focus();
    }
  }, [previewError, saveError, saved, testFailureCode, testSuccessRecipient]);

  useEffect(() => {
    if (preview) previewRef.current?.focus();
  }, [preview]);

  const timezoneOptions = useMemo(
    () => getSelectableIanaTimezones(form?.reportingTimezone ?? ''),
    [form?.reportingTimezone],
  );

  const focusResult = () => {
    window.requestAnimationFrame(() => resultRef.current?.focus());
  };

  if (loading) {
    return (
      <section className="card administrator-summary-section" aria-labelledby="administrator-summary-title">
        <h2 id="administrator-summary-title">{t('administratorSummary.title')}</h2>
        <div className="info-banner" role="status">{t('administratorSummary.states.loading')}</div>
      </section>
    );
  }

  if (loadError || !configuration || !form) {
    return (
      <section className="card administrator-summary-section" aria-labelledby="administrator-summary-title">
        <h2 id="administrator-summary-title">{t('administratorSummary.title')}</h2>
        <div className="error-banner email-state-banner" role="alert">
          <span>{t('administratorSummary.errors.loadFailed')}</span>
          <button className="btn" type="button" onClick={() => void load()}>{t('actions.retry')}</button>
        </div>
      </section>
    );
  }

  const dirty = (
    form.enabled !== configuration.enabled
    || form.cadence !== configuration.cadence
    || form.dailySendTime !== configuration.daily_send_time.slice(0, 5)
    || form.reportingTimezoneMode !== (
      configuration.reporting_timezone_source === 'system_preferences' ? 'system' : 'override'
    )
    || form.reportingTimezoneOverride !== configuration.reporting_timezone_override
  );
  const scheduleLabel = configuration.cadence === 'daily'
    ? t('administratorSummary.schedule.dailyAt', {
      time: wallClockTime(configuration.daily_send_time, languageCode),
    })
    : configuration.cadence === 'hourly'
      ? t('administratorSummary.schedule.hourly')
      : t('administratorSummary.schedule.testing');

  const saveSchedule = async () => {
    setSaving(true);
    setSaveError(false);
    setSaved(false);
    setPreviewError(false);
    setTestSuccessRecipient(null);
    setTestFailureCode(null);
    try {
      const updated = await updateAdministratorSummaryConfiguration({
        enabled: form.enabled,
        cadence: form.cadence,
        daily_send_time: `${form.dailySendTime}:00`,
        reporting_timezone_mode: form.reportingTimezoneMode,
        reporting_timezone_override: form.reportingTimezoneOverride,
      });
      setConfiguration(updated);
      setForm(formFromConfiguration(updated));
      setAdvancedOpen(updated.cadence !== 'daily');
      setSaved(true);
      focusResult();
    } catch {
      setSaveError(true);
      focusResult();
    } finally {
      setSaving(false);
    }
  };

  const buildPreview = async () => {
    setPreviewing(true);
    setSaved(false);
    setSaveError(false);
    setPreviewError(false);
    setTestSuccessRecipient(null);
    setTestFailureCode(null);
    setPreview(null);
    try {
      const builtPreview = await previewAdministratorSummary({
        cadence: form.cadence,
        daily_send_time: `${form.dailySendTime}:00`,
        reporting_timezone_mode: form.reportingTimezoneMode,
        reporting_timezone_override: form.reportingTimezoneOverride,
      });
      setPreview(builtPreview);
      setPreviewMode('html');
      focusResult();
    } catch {
      setPreviewError(true);
      focusResult();
    } finally {
      setPreviewing(false);
    }
  };

  const sendTest = async () => {
    const normalizedRecipient = testRecipient.trim();
    if (normalizedRecipient && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedRecipient)) {
      setTestRecipientInvalid(true);
      window.requestAnimationFrame(() => document.getElementById('summary-test-recipient')?.focus());
      return;
    }
    setSendingTest(true);
    setSaved(false);
    setSaveError(false);
    setPreviewError(false);
    setTestRecipientInvalid(false);
    setTestSuccessRecipient(null);
    setTestFailureCode(null);
    try {
      const result = await sendAdministratorSummaryTest({
        cadence: form.cadence,
        daily_send_time: `${form.dailySendTime}:00`,
        reporting_timezone_mode: form.reportingTimezoneMode,
        reporting_timezone_override: form.reportingTimezoneOverride,
        recipient: normalizedRecipient || undefined,
      });
      setTestDialogOpen(false);
      setTestSuccessRecipient(result.recipient);
      focusResult();
    } catch (error) {
      setTestDialogOpen(false);
      setTestFailureCode(error instanceof ApiError ? error.errorCode : 'request_failed');
      focusResult();
    } finally {
      setSendingTest(false);
    }
  };

  const statusTone = configuration.schedule_status === 'last_summary_sent'
    ? 'ready'
    : configuration.schedule_status === 'summary_off'
      ? 'disabled'
      : configuration.schedule_status === 'waiting_for_first_scheduled_period'
        || configuration.schedule_status === 'delivery_in_progress'
        ? 'neutral'
        : 'attention';

  return (
    <section className="administrator-summary-section" aria-labelledby="administrator-summary-title">
      <div className="email-feature-divider">
        <span>{t('administratorSummary.eyebrow')}</span>
        <div>
          <h2 id="administrator-summary-title">{t('administratorSummary.title')}</h2>
          <p>{t('workflow.summaryDescription')}</p>
        </div>
      </div>

      <form className="card administrator-summary-form" aria-labelledby="administrator-summary-title" onSubmit={(event) => {
        event.preventDefault();
        void saveSchedule();
      }}>
        <div className="email-section-heading">
          <div>
            <h3>{t('administratorSummary.form.title')}</h3>
            <p>{t('administratorSummary.form.description')}</p>
          </div>
          <label className="email-switch-row">
            <input
              type="checkbox"
              aria-label={t('administratorSummary.form.enabledLabel')}
              checked={form.enabled}
              onChange={(event) => {
                setForm({ ...form, enabled: event.target.checked });
                setSaved(false);
              }}
            />
            <span>
              <strong>{t('administratorSummary.form.enabledLabel')}</strong>
              <small>{t('administratorSummary.form.enabledHelp')}</small>
            </span>
          </label>
        </div>

        <fieldset className="administrator-summary-cadence">
          <legend>{t('administratorSummary.form.cadenceLegend')}</legend>
          <label className={form.cadence === 'daily' ? 'selected' : ''}>
            <input
              type="radio"
              aria-label={t('administratorSummary.cadence.daily.label')}
              name="summary-cadence"
              value="daily"
              checked={form.cadence === 'daily'}
              onChange={() => setForm({ ...form, cadence: 'daily' })}
            />
            <span><strong>{t('administratorSummary.cadence.daily.label')}</strong><small>{t('administratorSummary.cadence.daily.help')}</small></span>
          </label>
          <details
            className="administrator-summary-advanced"
            open={advancedOpen}
            onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
          >
            <summary>{t('administratorSummary.advanced.title')}</summary>
            <p>{t('administratorSummary.advanced.help')}</p>
            <label className={form.cadence === 'hourly' ? 'selected' : ''}>
              <input
                type="radio"
                aria-label={t('administratorSummary.cadence.hourly.label')}
                name="summary-cadence"
                value="hourly"
                checked={form.cadence === 'hourly'}
                onChange={() => setForm({ ...form, cadence: 'hourly' })}
              />
              <span><strong>{t('administratorSummary.cadence.hourly.label')}</strong><small>{t('administratorSummary.cadence.hourly.help')}</small></span>
            </label>
            <label className={form.cadence === 'every_15_minutes' ? 'selected' : ''}>
              <input
                type="radio"
                aria-label={t('administratorSummary.cadence.every15.label')}
                name="summary-cadence"
                value="every_15_minutes"
                checked={form.cadence === 'every_15_minutes'}
                onChange={() => setForm({ ...form, cadence: 'every_15_minutes' })}
              />
              <span><strong>{t('administratorSummary.cadence.every15.label')}</strong><small>{t('administratorSummary.cadence.every15.help')}</small></span>
            </label>
            {form.cadence === 'every_15_minutes' && (
              <div className="warning-banner" role="note">{t('administratorSummary.cadence.every15.warning')}</div>
            )}
          </details>
        </fieldset>

        <div className="administrator-summary-schedule-fields">
          {form.cadence === 'daily' && (
            <label className="email-field">
              <span>{t('administratorSummary.form.sendTimeLabel')}</span>
              <input
                type="time"
                aria-label={t('administratorSummary.form.sendTimeLabel')}
                value={form.dailySendTime}
                onChange={(event) => setForm({ ...form, dailySendTime: event.target.value })}
                required
              />
              <small>{t('administratorSummary.form.sendTimeHelp', {
                time: wallClockTime(form.dailySendTime, languageCode),
              })}</small>
            </label>
          )}
          <label className="email-field">
            <span>{t('administratorSummary.form.timezoneLabel')}</span>
            <select
              aria-label={t('administratorSummary.form.timezoneLabel')}
              value={form.reportingTimezoneMode === 'system'
                ? SYSTEM_TIMEZONE_OPTION
                : form.reportingTimezoneOverride ?? form.reportingTimezone}
              onChange={(event) => {
                const selectedTimezone = event.target.value;
                if (selectedTimezone === SYSTEM_TIMEZONE_OPTION) {
                  setForm({
                    ...form,
                    reportingTimezone: form.systemTimezone,
                    reportingTimezoneMode: 'system',
                    reportingTimezoneOverride: null,
                  });
                } else {
                  setForm({
                    ...form,
                    reportingTimezone: selectedTimezone,
                    reportingTimezoneMode: 'override',
                    reportingTimezoneOverride: selectedTimezone,
                  });
                }
              }}
            >
              <option value={SYSTEM_TIMEZONE_OPTION}>
                {t('administratorSummary.form.useSystemTimezone', {
                  timezone: form.systemTimezone,
                })}
              </option>
              {timezoneOptions.map((timezone) => {
                const translatedLabel = t(
                  `administratorSummary.timezones.${timezone.replaceAll('/', '_')}`,
                  { defaultValue: timezone },
                );
                return (
                  <option key={timezone} value={timezone}>
                    {translatedLabel === timezone ? timezone : `${translatedLabel} — ${timezone}`}
                  </option>
                );
              })}
            </select>
            <small>
              {form.reportingTimezoneMode === 'system'
                ? t('administratorSummary.form.systemTimezoneHelp')
                : t('administratorSummary.form.timezoneHelp')}
            </small>
          </label>
        </div>

        <p className="administrator-summary-period-help">
          {t(`administratorSummary.cadence.${form.cadence === 'every_15_minutes' ? 'every15' : form.cadence}.periodHelp`)}
        </p>

        <div className="email-form-actions administrator-summary-actions">
          <button className="btn" type="button" disabled={previewing} onClick={() => void buildPreview()}>
            {previewing ? t('administratorSummary.preview.loading') : t('administratorSummary.preview.action')}
          </button>
          <button
            className="btn"
            type="button"
            disabled={!configuration.email_delivery_ready || dirty}
            onClick={() => {
              setTestRecipient(defaultRecipient);
              setTestRecipientInvalid(false);
              setTestDialogOpen(true);
            }}
          >
            {t('administratorSummary.test.action')}
          </button>
          <button className="btn btn-primary" type="submit" disabled={!dirty || saving}>
            {saving ? t('administratorSummary.form.saving') : t('administratorSummary.form.save')}
          </button>
        </div>

        {!configuration.email_delivery_ready && (
          <small className="administrator-summary-test-help">{t('administratorSummary.test.blocked')}</small>
        )}
        {dirty && (
          <small className="administrator-summary-test-help">{t('administratorSummary.test.unsaved')}</small>
        )}
      </form>

      <div className="card administrator-summary-facts" aria-label={t('administratorSummary.facts.label')}>
        <div>
          <span>{t('administratorSummary.facts.nextSummary')}</span>
          <strong>{configuration.next_due_at
            ? dateTimeInTimezone(configuration.next_due_at, languageCode, configuration.reporting_timezone)
            : t('administratorSummary.common.notScheduled')}</strong>
        </div>
        <div>
          <span>{t('administratorSummary.facts.nextPeriod')}</span>
          <strong>{configuration.next_reporting_window
            ? reportingPeriod(
              configuration.next_reporting_window.period_start,
              configuration.next_reporting_window.period_end,
              languageCode,
              configuration.reporting_timezone,
            )
            : t('administratorSummary.common.notAvailable')}</strong>
        </div>
      </div>

      {(saved || saveError || previewError || testSuccessRecipient || testFailureCode) && (
        <div
          ref={resultRef}
          className={(saveError || previewError || testFailureCode) ? 'error-banner' : 'success-banner'}
          role={(saveError || previewError || testFailureCode) ? 'alert' : 'status'}
          tabIndex={-1}
        >
          {saved && t('administratorSummary.messages.saved')}
          {saveError && t('administratorSummary.errors.saveFailed')}
          {previewError && t('administratorSummary.errors.previewFailed')}
          {testSuccessRecipient && t('administratorSummary.test.success', { recipient: testSuccessRecipient })}
          {testFailureCode && (testFailureCode === 'request_failed'
            ? t('administratorSummary.errors.testFailed')
            : testErrorMessage(testFailureCode))}
        </div>
      )}

      {preview && (
        <section
          ref={previewRef}
          className="card administrator-summary-preview"
          aria-labelledby="administrator-summary-preview-title"
          tabIndex={-1}
        >
          <div className="email-section-heading">
            <div>
              <h3 id="administrator-summary-preview-title">{t('administratorSummary.preview.title')}</h3>
              <p>{t('administratorSummary.preview.notSent')}</p>
            </div>
            <span className={`email-status-badge email-status-badge-${preview.overall_status === 'needs_attention' ? 'attention' : 'ready'}`}>
              {preview.overall_status === 'needs_attention'
                ? t('administratorSummary.preview.needsAttention', { count: preview.attention_count })
                : t('administratorSummary.preview.allNormal')}
            </span>
          </div>
          <dl className="administrator-summary-preview-meta">
            <div><dt>{t('administratorSummary.preview.period')}</dt><dd>{reportingPeriod(
              preview.reporting_window.period_start,
              preview.reporting_window.period_end,
              languageCode,
              form.reportingTimezone,
            )}</dd></div>
            <div><dt>{t('administratorSummary.preview.subject')}</dt><dd>{preview.subject}</dd></div>
          </dl>
          <div className="administrator-summary-preview-tabs" role="tablist" aria-label={t('administratorSummary.preview.formatLabel')}>
            <button id="summary-preview-html-tab" className="btn" type="button" role="tab" aria-controls="summary-preview-html-panel" aria-selected={previewMode === 'html'} onClick={() => setPreviewMode('html')}>{t('administratorSummary.preview.html')}</button>
            <button id="summary-preview-text-tab" className="btn" type="button" role="tab" aria-controls="summary-preview-text-panel" aria-selected={previewMode === 'text'} onClick={() => setPreviewMode('text')}>{t('administratorSummary.preview.text')}</button>
          </div>
          {previewMode === 'html' ? (
            <iframe
              id="summary-preview-html-panel"
              className="administrator-summary-preview-frame"
              title={t('administratorSummary.preview.frameTitle')}
              role="tabpanel"
              aria-labelledby="summary-preview-html-tab"
              sandbox=""
              srcDoc={preview.html_body}
            />
          ) : (
            <pre id="summary-preview-text-panel" className="administrator-summary-preview-text" role="tabpanel" aria-labelledby="summary-preview-text-tab">{preview.text_body}</pre>
          )}
        </section>
      )}

      <section className="email-activity" aria-labelledby="email-activity-title">
        <h2 id="email-activity-title">{t('workflow.activityTitle')}</h2>
        {deliveryConfiguration && (
          <div className="card email-summary-card">
            <h3>{t('overview.lastTest')}</h3>
            <p>{t(deliveryConfiguration.last_test_status === 'success' ? 'test.lastSuccess'
              : deliveryConfiguration.last_test_status === 'failed' ? 'test.lastFailure' : 'test.neverTested')}</p>
            {deliveryConfiguration.last_tested_at && <p>{formatDisplayDateTime(
              deliveryConfiguration.last_tested_at, languageCode,
            )}</p>}
            {deliveryConfiguration.last_test_error_code && <p>{testErrorMessage(deliveryConfiguration.last_test_error_code)}</p>}
          </div>
        )}
        <div className={`card administrator-summary-status email-status-${statusTone}`}>
          <div>
            <span className={`email-status-badge email-status-badge-${statusTone}`}>
              {t(`administratorSummary.status.${configuration.schedule_status}.label`)}
            </span>
            <h3>{configuration.enabled ? scheduleLabel : t('administratorSummary.schedule.whenEnabled', { cadence: scheduleLabel })}</h3>
            <p>{t(`administratorSummary.status.${configuration.schedule_status}.explanation`)}</p>
          </div>
          {configuration.blocker_codes.length > 0 && (
            <div className="warning-banner administrator-summary-blockers" role="note">
              <strong>{t('administratorSummary.status.blockedTitle')}</strong>
              <ul>
                {configuration.blocker_codes.map((code) => <li key={code}>{reasonMessage(code)}</li>)}
              </ul>
              <a href="#email-overall-status">{t('administratorSummary.status.reviewEmailDelivery')}</a>
            </div>
          )}
        </div>

        <div className="card administrator-summary-facts" aria-label={t('administratorSummary.facts.label')}>
          <div>
            <span>{t('administratorSummary.facts.lastSummary')}</span>
            <strong>{configuration.last_scheduled_delivery
              ? reportingPeriod(
                configuration.last_scheduled_delivery.period_start,
                configuration.last_scheduled_delivery.period_end,
                languageCode,
                configuration.reporting_timezone,
              )
              : t('administratorSummary.common.noneYet')}</strong>
          </div>
          <div>
            <span>{t('administratorSummary.facts.lastDelivery')}</span>
            <strong>{configuration.last_scheduled_delivery
              ? t(`administratorSummary.delivery.${configuration.last_scheduled_delivery.status}`)
              : t('administratorSummary.common.noneYet')}</strong>
            {configuration.last_scheduled_delivery?.last_attempted_at && (
              <small>{dateTimeInTimezone(
                configuration.last_scheduled_delivery.last_attempted_at,
                languageCode,
                configuration.reporting_timezone,
              )}</small>
            )}
          </div>
        </div>

        {configuration.last_scheduled_delivery?.error_code && (
          <div className="warning-banner">{testErrorMessage(configuration.last_scheduled_delivery.error_code)}</div>
        )}
      </section>

      {testDialogOpen && (
        <div className="email-dialog-backdrop">
          <div
            className="email-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="summary-test-dialog-title"
            onKeyDown={(event) => {
              if (event.key === 'Escape' && !sendingTest) setTestDialogOpen(false);
            }}
          >
            <h2 id="summary-test-dialog-title">{t('administratorSummary.test.dialogTitle')}</h2>
            <p>{t('administratorSummary.test.dialogDescription')}</p>
            <label className="email-field">
              <span>{t('administratorSummary.test.recipientLabel')}</span>
              <input
                id="summary-test-recipient"
                type="email"
                aria-label={t('administratorSummary.test.recipientLabel')}
                value={testRecipient}
                placeholder={t('administratorSummary.test.recipientPlaceholder')}
                aria-invalid={testRecipientInvalid}
                aria-describedby="summary-test-recipient-help"
                autoFocus
                onChange={(event) => {
                  setTestRecipient(event.target.value);
                  setTestRecipientInvalid(false);
                }}
                disabled={sendingTest}
              />
              <small id="summary-test-recipient-help">{testRecipientInvalid
                ? t('validation.invalidEmailAddress')
                : t('administratorSummary.test.recipientHelp')}</small>
            </label>
            <div className="email-dialog-actions">
              <button className="btn" type="button" disabled={sendingTest} onClick={() => setTestDialogOpen(false)}>{t('actions.cancel')}</button>
              <button className="btn btn-primary" type="button" disabled={sendingTest} onClick={() => void sendTest()}>
                {sendingTest ? t('administratorSummary.test.sending') : t('administratorSummary.test.confirm')}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
