import { formatOperationalTimestamp } from './utils/timezone';
import { useCallback, useEffect, useMemo, useState } from 'react';
import AdminPageLayout from './components/AdminPageLayout';
import { getSystemPreferences, updateSystemPreferences, type SystemPreferencesRecord } from './api';
import { useTranslation } from 'react-i18next';
import LanguageSelector from './components/LanguageSelector';
import BuildInformation from './admin/BuildInformation';
import { useAuth } from './auth';
import i18n, { type SupportedLanguageCode } from './i18n';
import { getSelectableIanaTimezones } from './utils/timezone';

type FormState = {
  geoapify_api_key: string;
  default_language_code: SupportedLanguageCode;
  system_timezone: string;
};

function formatBytes(value: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let amount = value;
  let unitIndex = 0;
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024;
    unitIndex += 1;
  }
  const digits = amount < 100 ? 1 : 0;
  return `${amount.toFixed(digits)} ${units[unitIndex]}`;
}

function buildFormState(preferences: SystemPreferencesRecord): FormState {
  return {
    geoapify_api_key: preferences.geoapify_api_key ?? '',
    default_language_code: preferences.default_language_code ?? 'en',
    system_timezone: preferences.system_timezone ?? 'UTC',
  };
}

export default function AdminSystemPreferences() {
  const { t } = useTranslation(['admin', 'common', 'emailNotifications']);
  const { user } = useAuth();
  const [preferences, setPreferences] = useState<SystemPreferencesRecord | null>(null);
  const [formState, setFormState] = useState<FormState>({
    geoapify_api_key: '',
    default_language_code: 'en',
    system_timezone: 'UTC',
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const loadPreferences = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const data = await getSystemPreferences();
      setPreferences(data);
      setFormState(buildFormState(data));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      setErrorMessage(message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPreferences();
  }, [loadPreferences]);

  const hasChanges = useMemo(() => {
    if (!preferences) return false;
    const savedState = buildFormState(preferences);
    return savedState.geoapify_api_key !== formState.geoapify_api_key
      || savedState.default_language_code !== formState.default_language_code
      || savedState.system_timezone !== formState.system_timezone;
  }, [preferences, formState]);

  const timezoneOptions = useMemo(
    () => getSelectableIanaTimezones(formState.system_timezone),
    [formState.system_timezone],
  );

  const handleSave = useCallback(async () => {
    if (!preferences) return;
    if (!hasChanges) {
      setSuccessMessage(t('admin:systemPreferences.messages.noChanges'));
      setErrorMessage(null);
      return;
    }

    setIsSaving(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const updatedPreferences = await updateSystemPreferences({
        geoapify_api_key: formState.geoapify_api_key,
        default_language_code: formState.default_language_code,
        system_timezone: formState.system_timezone,
      });
      setPreferences(updatedPreferences);
      setFormState(buildFormState(updatedPreferences));
      if (user?.preferred_language_code === null) {
        await i18n.changeLanguage(updatedPreferences.default_language_code ?? 'en');
      }
      setSuccessMessage(t('admin:systemPreferences.messages.saved'));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      setErrorMessage(message);
    } finally {
      setIsSaving(false);
    }
  }, [preferences, hasChanges, formState, t, user?.preferred_language_code]);

  const renderSaveButton = () => (
    <button type="button" className="btn btn-primary" onClick={handleSave} disabled={isLoading || isSaving}>
      {isSaving ? t('admin:systemPreferences.states.saving') : t('common:actions.saveChanges')}
    </button>
  );

  return (
    <AdminPageLayout
      title={t('admin:systemPreferences.title')}
      description={t('admin:systemPreferences.description')}
      breadcrumbs={[
        { label: t('admin:navigation.admin'), to: '/admin' },
        { label: t('admin:systemPreferences.title') },
      ]}
      contentClassName="admin-workspace system-preferences-page"
      actions={renderSaveButton()}
    >
      <div>
        {isLoading && <div className="loading-indicator" role="status">{t('admin:systemPreferences.states.loading')}</div>}
        {!isLoading && errorMessage && <div className="error-message" role="alert">{errorMessage}</div>}
        {!isLoading && preferences && (
          <div className="preferences-workspace">
            {successMessage && <div className="success-message" role="status">{successMessage}</div>}

            <section className="card admin-section">
              <h2>{t('admin:systemPreferences.geocoding.title')}</h2>
              <p className="muted system-preferences-section-description">
                <a
                  href="https://www.geoapify.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Geoapify
                </a>{' '}
                {t('admin:systemPreferences.geocoding.description')}
              </p>

              <div className="form-grid">
                <div className="field">
                  <label htmlFor="geoapify-api-key">{t('admin:systemPreferences.geocoding.apiKeyLabel')}</label>
                  <input
                    id="geoapify-api-key"
                    type="text"
                    className="text-input"
                    value={formState.geoapify_api_key}
                    onChange={(event) => {
                      setFormState((currentState) => ({
                        ...currentState,
                        geoapify_api_key: event.target.value,
                      }));
                    }}
                    placeholder={t('admin:systemPreferences.geocoding.apiKeyPlaceholder')}
                    autoComplete="off"
                  />
                  <small className="muted system-preferences-helper-text">
                    {t('admin:systemPreferences.geocoding.apiKeyHelp')}
                  </small>
                </div>
              </div>

            </section>
            <section className="card admin-section">
              <h2>{t('admin:workspace.regional')}</h2>
              <div className="form-grid">
                <LanguageSelector
                  id="system-default-language"
                  value={formState.default_language_code}
                  onChange={(defaultLanguageCode) => setFormState((currentState) => ({
                    ...currentState,
                    default_language_code: defaultLanguageCode,
                  }))}
                />
                <small className="muted system-preferences-helper-text">
                  {t('admin:systemPreferences.language.help')}
                </small>
              </div>

              <div className="form-grid">
                <div className="field">
                  <label htmlFor="system-timezone">{t('admin:systemPreferences.systemTimezone.label')}</label>
                  <select
                    id="system-timezone"
                    className="text-input"
                    value={formState.system_timezone}
                    onChange={(event) => setFormState((currentState) => ({
                      ...currentState,
                      system_timezone: event.target.value,
                    }))}
                    aria-describedby="system-timezone-help"
                  >
                    {timezoneOptions.map((timezone) => {
                      const translatedLabel = t(
                        `emailNotifications:administratorSummary.timezones.${timezone.replaceAll('/', '_')}`,
                        { defaultValue: timezone },
                      );
                      return (
                        <option key={timezone} value={timezone}>
                          {translatedLabel === timezone ? timezone : `${translatedLabel} — ${timezone}`}
                        </option>
                      );
                    })}
                  </select>
                  <small id="system-timezone-help" className="muted system-preferences-helper-text">
                    {t('admin:systemPreferences.systemTimezone.help')}
                  </small>
                </div>
              </div>

            </section>
              {preferences?.storage && (
                <section className="card admin-section preferences-storage" aria-labelledby="system-storage-heading">
                  <h2 id="system-storage-heading">{t('admin:systemPreferences.storage.title')}</h2>
                  <p className="muted system-preferences-section-description">
                    {t('admin:systemPreferences.storage.description')}
                  </p>
                  <div className="form-grid">
                    <div className="field">
                      <strong>{t('admin:systemPreferences.storage.free')}</strong>{' '}
                      {formatBytes(preferences.storage.free_bytes)} ({preferences.storage.percent_free.toFixed(1)}%)
                    </div>
                    <div className="field">
                      <strong>{t('admin:systemPreferences.storage.used')}</strong>{' '}
                      {formatBytes(preferences.storage.used_bytes)}
                    </div>
                    <div className="field">
                      <strong>{t('admin:systemPreferences.storage.total')}</strong>{' '}
                      {formatBytes(preferences.storage.total_bytes)}
                    </div>
                    <div className="field">
                      <strong>{t('admin:systemPreferences.storage.statusLabel')}</strong>{' '}
                      {t(`admin:systemPreferences.storage.status.${preferences.storage.status}`)}
                    </div>
                  </div>
                </section>
              )}

            <div className="preferences-save-state">
              <span role="status">{t(hasChanges ? 'admin:workspace.unsaved' : 'admin:workspace.saved')}</span>
              <div className="muted system-preferences-last-updated">
                {t('admin:systemPreferences.lastUpdated.label')}{' '}
                {preferences?.updated_at
                  ? formatOperationalTimestamp(preferences.updated_at)
                  : t('common:states.never')}
                {' '}{(preferences?.last_updated_by_display_name || preferences?.last_updated_by_email)
                  && t('admin:systemPreferences.lastUpdated.byUser', { email: preferences.last_updated_by_display_name || preferences.last_updated_by_email })}
              </div>
            </div>

            <div className="preferences-save-actions admin-form-save-actions">
              {renderSaveButton()}
            </div>
          </div>
        )}
        <BuildInformation />
      </div>
    </AdminPageLayout>
  );
}
