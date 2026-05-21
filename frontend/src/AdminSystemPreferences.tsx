import { useCallback, useEffect, useMemo, useState } from 'react';
import AdminPageLayout from './components/AdminPageLayout';
import { getSystemPreferences, updateSystemPreferences, type SystemPreferencesRecord } from './api';

type FormState = {
  geoapify_api_key: string;
};

function buildFormState(preferences: SystemPreferencesRecord): FormState {
  return {
    geoapify_api_key: preferences.geoapify_api_key ?? '',
  };
}

export default function AdminSystemPreferences() {
  const [preferences, setPreferences] = useState<SystemPreferencesRecord | null>(null);
  const [formState, setFormState] = useState<FormState>({ geoapify_api_key: '' });
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
    return buildFormState(preferences).geoapify_api_key !== formState.geoapify_api_key;
  }, [preferences, formState]);

  const handleSave = useCallback(async () => {
    if (!preferences) return;
    if (!hasChanges) {
      setSuccessMessage('No changes to save.');
      setErrorMessage(null);
      return;
    }

    setIsSaving(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const updatedPreferences = await updateSystemPreferences({
        geoapify_api_key: formState.geoapify_api_key,
      });
      setPreferences(updatedPreferences);
      setFormState(buildFormState(updatedPreferences));
      setSuccessMessage('System preferences updated.');
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      setErrorMessage(message);
    } finally {
      setIsSaving(false);
    }
  }, [preferences, hasChanges, formState]);

  return (
    <AdminPageLayout
      title="System Preferences"
      description="Manage platform-wide settings used by administrative features and shared services."
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'System Preferences' },
      ]}
      actions={
        <button className="btn btn-primary" onClick={handleSave} disabled={isLoading || isSaving}>
          {isSaving ? 'Saving...' : 'Save Changes'}
        </button>
      }
    >
      <div className="card form-section">
        {isLoading && <div className="loading-indicator">Loading system preferences…</div>}
        {!isLoading && errorMessage && <div className="error-message">{errorMessage}</div>}
        {!isLoading && !errorMessage && (
          <div className="admin-sources-form">
            {successMessage && <div className="success-message">{successMessage}</div>}

            <section className="admin-section">
              <h3 style={{ marginTop: 0 }}>Geocoding</h3>
              <p className="muted">
                Geoapify powers the location search proxy. Leave the field blank and save to clear the key.
              </p>

              <div className="form-grid">
                <div className="field">
                  <label htmlFor="geoapify-api-key">Geoapify API Key</label>
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
                    placeholder="Enter Geoapify API key"
                    autoComplete="off"
                  />
                  <small className="muted">
                    Server-side API key used by the geocoding proxy. Leave this blank and save to clear it.
                  </small>
                </div>
              </div>

              <div className="muted" style={{ marginTop: 12 }}>
                Last updated:{' '}
                {preferences?.updated_at ? new Date(preferences.updated_at).toLocaleString() : 'Never'}
              </div>
            </section>
          </div>
        )}
      </div>
    </AdminPageLayout>
  );
}
