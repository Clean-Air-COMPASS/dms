import { Trans, useTranslation } from 'react-i18next';


import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { browserSupportsWebAuthnAutofill, WebAuthnAbortService } from '@simplewebauthn/browser';
import { registerPasskey } from './auth/passkeys';
import { login as authenticateForPasskey } from './auth/authClient';
import PasswordInput from './components/PasswordInput';
import PasswordStrengthIndicator from './components/PasswordStrengthIndicator';
import { validatePasswordStrength } from './utils/passwordStrength';
import { API_BASE } from './apiBase';
import i18n, {
  writeAnonymousLanguagePreference,
  type SupportedLanguageCode,
} from './i18n';
import LanguageSelector from './components/LanguageSelector';
import { getLocalTimezone } from './utils/timezone';


interface DataSource {
  external_api_id: number;
  provider_code: string | null;
  name: string;
  description: string | null;
  has_api_key: boolean;
  requires_credential: boolean;
  enabled: boolean;
  is_configured?: boolean;
  import_authenticated_locations?: boolean;
  runnable_reason: 'disabled' | 'configuration_required' | 'paid_provider_requests_disabled' | 'ready' | 'unsupported_provider';
}

interface SetupResponse {
  success: boolean;
  is_configured?: boolean;
  message: string;
  message_code?: string;
  message_context?: Record<string, string | number>;
  detail?: unknown;
}

const SETUP_ERROR_KEYS = {
  setup_already_completed: 'setup:serverErrors.alreadyCompleted',
  password_confirmation_mismatch: 'setup:serverErrors.passwordConfirmationMismatch',
  password_policy_not_met: 'setup:serverErrors.passwordPolicyNotMet',
  setup_admin_email_exists: 'setup:serverErrors.adminEmailExists',
  api_key_confirmation_mismatch: 'setup:serverErrors.apiKeyConfirmationMismatch',
  data_source_not_found: 'setup:serverErrors.dataSourceNotFound',
  api_key_required: 'setup:serverErrors.apiKeyRequired',
  setup_admin_required: 'setup:serverErrors.adminRequired',
} as const;

function translateSetupError(
  detail: unknown,
  fallbackKey: 'setup:serverErrors.adminCreationFailed' | 'setup:serverErrors.apiKeySaveFailed' | 'setup:serverErrors.completionFailed',
): string {
  if (detail && typeof detail === 'object' && 'error_code' in detail) {
    const errorCode = String(detail.error_code);
    const key = SETUP_ERROR_KEYS[errorCode as keyof typeof SETUP_ERROR_KEYS];
    if (key) {
      const context = 'error_context' in detail && detail.error_context && typeof detail.error_context === 'object'
        ? detail.error_context as Record<string, string | number>
        : {};
      return i18n.t(key, context);
    }
  }
  return i18n.t(fallbackKey);
}

function isSetupEmailValidationError(status: number, detail: unknown): boolean {
  // FastAPI/Pydantic identifies the rejected body field. Never infer it from
  // HTTP 422 alone or display the validator's diagnostic message.
  return status === 422 && Array.isArray(detail) && detail.some(error => (
    error !== null && typeof error === 'object'
    && error.type === 'value_error'
    && Array.isArray(error.loc) && error.loc.length === 2
    && error.loc[0] === 'body' && error.loc[1] === 'email'
  ));
}


type WizardStep = 'welcome' | 'admin' | 'secure' | 'datasource' | 'geoapify' | 'complete';

interface SetupWizardProps {
  onSetupComplete: () => void;
  initialAdminCreated?: boolean;
}

export default function SetupWizard({
  onSetupComplete,
  initialAdminCreated = false,
}: SetupWizardProps) {
  useTranslation();
  const [defaultLanguageCode, setDefaultLanguageCode] = useState<SupportedLanguageCode>(
    i18n.resolvedLanguage === 'es' ? 'es' : 'en',
  );
  
  const [currentStep, setCurrentStep] = useState<WizardStep>(
    initialAdminCreated ? 'datasource' : 'welcome',
  );
  
  
  const [adminEmail, setAdminEmail] = useState('');
  const [adminEmailError, setAdminEmailError] = useState<string | null>(null);
  const adminEmailInput = useRef<HTMLInputElement>(null);
  const [adminPassword, setAdminPassword] = useState('');
  const [adminConfirmPassword, setAdminConfirmPassword] = useState('');
  const [adminError, setAdminError] = useState<string | null>(null);
  const [adminSubmitting, setAdminSubmitting] = useState(false);
  useEffect(() => {
    if (adminEmailError && !adminSubmitting) adminEmailInput.current?.focus();
  }, [adminEmailError, adminSubmitting]);
  const [passkeyBusy, setPasskeyBusy] = useState(false);
  const [passkeyCreated, setPasskeyCreated] = useState(false);
  const [passkeyMessage, setPasskeyMessage] = useState<'unsupported' | 'cancelled' | 'failed' | null>(null);
  const passkeyToken = useRef<string | null>(null);
  const passkeyController = useRef<AbortController | null>(null);

  useEffect(() => () => {
    passkeyController.current?.abort();
    WebAuthnAbortService.cancelCeremony();
  }, []);

  function continueAfterPasskey() {
    passkeyController.current?.abort();
    WebAuthnAbortService.cancelCeremony();
    passkeyToken.current = null;
    setAdminPassword('');
    setAdminConfirmPassword('');
    setCurrentStep('datasource');
  }

  async function handleCreatePasskey() {
    const controller = new AbortController();
    passkeyController.current = controller;
    setPasskeyMessage(null);
    setPasskeyBusy(true);
    try {
      if (!await browserSupportsWebAuthnAutofill()) {
        setPasskeyMessage('unsupported');
        return;
      }
      if (controller.signal.aborted) return;
      if (!passkeyToken.current) {
        // Authorize enrollment without changing the post-setup sign-in flow.
        const result = await authenticateForPasskey({ email: adminEmail.trim(), password: adminPassword }, false);
        if (controller.signal.aborted) return;
        if (!result.success) throw new Error('passkey_failed');
        passkeyToken.current = result.token;
        setAdminPassword('');
        setAdminConfirmPassword('');
      }
      await registerPasskey(passkeyToken.current, controller.signal);
      if (!controller.signal.aborted) {
        setPasskeyCreated(true);
        continueAfterPasskey();
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setPasskeyMessage(error instanceof Error && error.name === 'NotAllowedError' ? 'cancelled' : 'failed');
      }
    } finally {
      if (!controller.signal.aborted) setPasskeyBusy(false);
    }
  }
  
  
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [importAuthenticatedLocations, setImportAuthenticatedLocations] = useState(false);
  const [sourceDrafts, setSourceDrafts] = useState<Record<number, { apiKey: string }>>({});
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [sourceLoading, setSourceLoading] = useState(true);
  const [sourceSaving, setSourceSaving] = useState(false);
  const [sourcesSaved, setSourcesSaved] = useState(false);
  const [sourceCredentialSupplied, setSourceCredentialSupplied] = useState(false);
  
  
  const [geoapifyKey, setGeoapifyKey] = useState('');
  const [geoapifyError, setGeoapifyError] = useState<string | null>(null);
  const [geoapifyConfigured, setGeoapifyConfigured] = useState(false);
  const [geoapifySaving, setGeoapifySaving] = useState(false);
  
  
  const [completing, setCompleting] = useState(false);
  const [completionError, setCompletionError] = useState<string | null>(null);

  
  useEffect(() => {
    async function loadDataSources() {
      try {
        const resp = await fetch(`${API_BASE}/setup/data-sources`);
        if (!resp.ok) throw new Error('source_load_failed');
        const data = await resp.json();
        const loadedSources: DataSource[] = data.data_sources || [];
        const sourceOrder: Record<string, number> = { demo: 0, purpleair: 1, openaq: 2, airgradient: 3 };
        // Stable sort preserves the API's existing order for custom sources.
        loadedSources.sort((a, b) => (sourceOrder[a.provider_code ?? ''] ?? 4) - (sourceOrder[b.provider_code ?? ''] ?? 4));
        setDataSources(loadedSources);
        setImportAuthenticatedLocations(loadedSources.find(source => source.provider_code === 'airgradient')?.import_authenticated_locations ?? false);
        setSourceDrafts(Object.fromEntries(loadedSources.map((source) => [
          source.external_api_id,
          { apiKey: '' },
        ])));
      } catch {
        setSourceError(i18n.t('common:errors.loadDataSources'));
      } finally {
        setSourceLoading(false);
      }
    }
    loadDataSources();
  }, []);

  
  const passwordStrength = useMemo(
    () => validatePasswordStrength(adminPassword, adminEmail),
    [adminPassword, adminEmail]
  );

  const handleAdminEmailInvalid = useCallback((event: React.InvalidEvent<HTMLInputElement>) => {
    if (!event.currentTarget.validity.typeMismatch) return;

    event.preventDefault();
    setAdminError(null);
    setAdminEmailError(i18n.t('setup:setupWizard.messages.emailAddressInvalid'));
  }, []);

  
  const handleCreateAdmin = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setAdminError(null);
    setAdminEmailError(null);

    
    if (!adminEmail.trim()) {
      setAdminError(i18n.t('setup:setupWizard.messages.emailAddressRequired'));
      return;
    }

    
    if (!adminPassword) {
      setAdminError(i18n.t('setup:setupWizard.messages.passwordRequired'));
      return;
    }

    
    if (!passwordStrength.isValid) {
      setAdminError(i18n.t('setup:setupWizard.messages.pleaseChooseStrongerPasswordThatMeets'));
      return;
    }

    
    if (adminPassword !== adminConfirmPassword) {
      setAdminError(i18n.t('setup:setupWizard.messages.passwordsDoNotMatch'));
      return;
    }

    setAdminSubmitting(true);
    try {
      const resp = await fetch(`${API_BASE}/setup/admin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: adminEmail.trim(),
          password: adminPassword,
          confirm_password: adminConfirmPassword,
        }),
      });

      const data: SetupResponse = await resp.json();
      
      if (resp.ok && data.success) {
        setCurrentStep('secure');
      } else if (isSetupEmailValidationError(resp.status, data.detail)) {
        setAdminEmailError(i18n.t('setup:setupWizard.messages.emailAddressInvalid'));
      } else {
        
        setAdminError(translateSetupError(data.detail, 'setup:serverErrors.adminCreationFailed'));
      }
    } catch {
      setAdminError(i18n.t('setup:setupWizard.messages.networkErrorPleaseTryAgain'));
    } finally {
      setAdminSubmitting(false);
    }
  }, [adminEmail, adminPassword, adminConfirmPassword, passwordStrength.isValid]);

  
  const handleSourceEnabled = async (source: DataSource, enabled: boolean) => {
    setSourceSaving(true);
    setSourceError(null);
    try {
      const response = await fetch(`${API_BASE}/setup/data-source`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          external_api_id: source.external_api_id,
          enabled,
          ...(source.provider_code === 'airgradient'
            ? { import_authenticated_locations: importAuthenticatedLocations } : {}),
        }),
      });
      const result: SetupResponse = await response.json();
      if (!response.ok || !result.success) throw new Error('source_save_failed');
      setDataSources(current => current.map(item => item.external_api_id === source.external_api_id
        ? { ...item, enabled, is_configured: result.is_configured ?? item.is_configured } : item));
    } catch {
      setSourceError(i18n.t('dataSources:demo.saveFailed'));
    } finally {
      setSourceSaving(false);
    }
  };

  const handleSaveDataSources = useCallback(async () => {
    setSourceError(null);
    setSourceSaving(true);

    try {
      let credentialSupplied = false;
      for (const source of dataSources) {
        // Credential-free choices are persisted immediately by their control.
        if (source.requires_credential === false && source.provider_code !== 'airgradient') continue;
        const draft = sourceDrafts[source.external_api_id] ?? { apiKey: '' };
        const apiKey = draft.apiKey.trim();
        // Setup derives the initial enablement intent from the supplied credential.
        const requestBody: {
          external_api_id: number;
          enabled: boolean;
          api_key?: string | null;
          import_authenticated_locations?: boolean;
        } = {
          external_api_id: source.external_api_id,
          enabled: source.provider_code === 'airgradient' ? source.enabled || Boolean(apiKey) : Boolean(apiKey),
        };
        if (apiKey) {
          credentialSupplied = true;
          requestBody.api_key = apiKey;
        } else if (!source.has_api_key) {
          requestBody.api_key = null;
        }
        if (source.provider_code === 'airgradient') {
          requestBody.import_authenticated_locations = importAuthenticatedLocations;
        }
        const resp = await fetch(`${API_BASE}/setup/data-source`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody),
        });
        const data: SetupResponse = await resp.json();
        if (!resp.ok || !data.success) {
          setSourceError(translateSetupError(data.detail, 'setup:serverErrors.apiKeySaveFailed'));
          return;
        }
        if (source.provider_code === 'airgradient') {
          setDataSources(current => current.map(item => item.external_api_id === source.external_api_id
            ? { ...item, enabled: requestBody.enabled, is_configured: data.is_configured ?? item.is_configured } : item));
        }
      }
      setSourceCredentialSupplied(credentialSupplied);
      setSourcesSaved(true);
      setCurrentStep('geoapify');
    } catch {
      setSourceError(i18n.t('setup:setupWizard.messages.networkErrorPleaseTryAgain2'));
    } finally {
      setSourceSaving(false);
    }
  }, [dataSources, sourceDrafts, importAuthenticatedLocations]);

  
  const handleSaveGeoapify = useCallback(async () => {
    if (!geoapifyKey.trim()) return;

    setGeoapifyError(null);
    setGeoapifySaving(true);

    try {
      const resp = await fetch(`${API_BASE}/setup/geoapify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: geoapifyKey.trim() }),
      });

      const data: SetupResponse = await resp.json();
      
      if (resp.ok && data.success) {
        setGeoapifyConfigured(true);
        setCurrentStep('complete');
      } else {
        setGeoapifyError(translateSetupError(data.detail, 'setup:serverErrors.apiKeySaveFailed'));
      }
    } catch {
      setGeoapifyError(i18n.t('setup:setupWizard.messages.networkErrorPleaseTryAgain3'));
    } finally {
      setGeoapifySaving(false);
    }
  }, [geoapifyKey]);

  
  const handleCompleteSetup = useCallback(async () => {
    setCompletionError(null);
    setCompleting(true);

    try {
      const resp = await fetch(`${API_BASE}/setup/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          default_language_code: defaultLanguageCode,
          system_timezone: getLocalTimezone(),
        }),
      });

      const data: SetupResponse = await resp.json();
      
      if (resp.ok && data.success) {
        onSetupComplete();
      } else {
        setCompletionError(translateSetupError(data.detail, 'setup:serverErrors.completionFailed'));
      }
    } catch {
      setCompletionError(i18n.t('setup:setupWizard.messages.networkErrorPleaseTryAgain4'));
    } finally {
      setCompleting(false);
    }
  }, [defaultLanguageCode, onSetupComplete]);

  
  const handleSkipDataSource = () => {
    setCurrentStep('geoapify');
  };

  
  const handleSkipGeoapify = () => {
    setCurrentStep('complete');
  };

  
  const getStepNumber = (step: WizardStep): number => {
    switch (step) {
      // Securing the account is part of the existing account progress stage.
      case 'admin':
      case 'secure': return 1;
      case 'datasource': return 2;
      case 'geoapify': return 3;
      case 'complete': return 4;
      case 'welcome': return 0;
    }
  };

  const currentStepNumber = getStepNumber(currentStep);
  const sourceConfiguredAndEnabled = (sourcesSaved && sourceCredentialSupplied)
    || dataSources.some(source => source.provider_code === 'airgradient' && source.enabled && source.is_configured === true);
  return (
    <div className={`setup-wizard-overlay${currentStep === 'datasource' ? ' setup-wizard-overlay--sources' : ''}`}>
      <div className="setup-wizard-container">
        
        <div className="setup-wizard-header">
          <h1 className="setup-wizard-title"><Trans ns="setup" i18nKey="setupWizard.headings.productName" /></h1>
          <p className="setup-wizard-subtitle"><Trans ns="setup" i18nKey="setupWizard.text.airQualityDataPlatform" /></p>
          <LanguageSelector
            id="setup-default-language"
            value={defaultLanguageCode}
            onChange={(languageCode) => {
              setDefaultLanguageCode(languageCode);
              writeAnonymousLanguagePreference(window.localStorage, languageCode);
              void i18n.changeLanguage(languageCode);
            }}
          />
        </div>

        
        {currentStep !== 'welcome' && <div className="setup-wizard-progress">
          <div className={`setup-progress-step ${currentStepNumber >= 1 ? 'active' : ''} ${currentStepNumber > 1 ? 'completed' : ''}`}>
            <div className="setup-progress-number">{currentStepNumber > 1 ? '✓' : '1'}</div>
            <div className="setup-progress-label"><Trans ns="setup" i18nKey="setupWizard.text.adminAccount" /></div>
          </div>
          <div className="setup-progress-line"></div>
          <div className={`setup-progress-step ${currentStepNumber >= 2 ? 'active' : ''} ${currentStepNumber > 2 ? 'completed' : ''}`}>
            <div className="setup-progress-number">{currentStepNumber > 2 ? '✓' : '2'}</div>
            <div className="setup-progress-label"><Trans ns="setup" i18nKey="setupWizard.text.dataSource" /></div>
          </div>
          <div className="setup-progress-line"></div>
          <div className={`setup-progress-step ${currentStepNumber >= 3 ? 'active' : ''} ${currentStepNumber > 3 ? 'completed' : ''}`}>
            <div className="setup-progress-number">{currentStepNumber > 3 ? '✓' : '3'}</div>
            <div className="setup-progress-label"><Trans ns="setup" i18nKey="setupWizard.text.locationSearch" /></div>
          </div>
          <div className="setup-progress-line"></div>
          <div className={`setup-progress-step ${currentStepNumber >= 4 ? 'active' : ''}`}>
            <div className="setup-progress-number">4</div>
            <div className="setup-progress-label"><Trans ns="setup" i18nKey="setupWizard.text.complete" /></div>
          </div>
        </div>}

        
        <div className="setup-wizard-content">
          <span role="status" className="sr-only">{passkeyCreated ? i18n.t('setup:passkey.success') : ''}</span>
          {currentStep === 'welcome' && (
            <div className="setup-step setup-welcome-step">
              <h2 className="setup-step-title"><Trans ns="setup" i18nKey="setupWizard.headings.welcomeCompassAQ" /></h2>
              <p className="setup-step-description">
                <Trans ns="setup" i18nKey="setupWizard.text.welcomePreparation" />
              </p>

              <h3 className="setup-prerequisite-heading">
                <Trans ns="setup" i18nKey="setupWizard.headings.optionalItems" />
              </h3>
              <ul className="setup-prerequisite-list">
                <li>
                  <span className="setup-prerequisite-dot" aria-hidden="true" />
                  <span><strong><Trans ns="setup" i18nKey="setupWizard.text.airGradientApiToken" /></strong> — <Trans ns="setup" i18nKey="setupWizard.text.airGradientPurpose" /></span>
                </li>
                <li>
                  <span className="setup-prerequisite-dot" aria-hidden="true" />
                  <span><strong><Trans ns="setup" i18nKey="setupWizard.text.openAQApiKey" /></strong> — <Trans ns="setup" i18nKey="setupWizard.text.openAQPurpose" /></span>
                </li>
                <li>
                  <span className="setup-prerequisite-dot" aria-hidden="true" />
                  <span><strong><Trans ns="setup" i18nKey="setupWizard.text.purpleAirApiKey" /></strong> — <Trans ns="setup" i18nKey="setupWizard.text.purpleAirPurpose" /></span>
                </li>
                <li>
                  <span className="setup-prerequisite-dot" aria-hidden="true" />
                  <span><strong><Trans ns="setup" i18nKey="setupWizard.text.geoapifyApiKey" /></strong> — <Trans ns="setup" i18nKey="setupWizard.text.geoapifyPurpose" /></span>
                </li>
                <li>
                  <span className="setup-prerequisite-dot" aria-hidden="true" />
                  <span><strong><Trans ns="setup" i18nKey="setupWizard.text.smtpSettings" /></strong> — <Trans ns="setup" i18nKey="setupWizard.text.smtpPurpose" /></span>
                </li>
              </ul>

              <p className="setup-welcome-optionality">
                <Trans ns="setup" i18nKey="setupWizard.text.noneRequired" />
              </p>
              <div className="setup-form-actions-row setup-welcome-actions">
                <button
                  type="button"
                  className="setup-btn setup-btn-primary"
                  onClick={() => setCurrentStep('admin')}
                >
                  <Trans ns="setup" i18nKey="setupWizard.actions.continue" />
                </button>
              </div>
            </div>
          )}

          
          {currentStep === 'admin' && (
            <div className="setup-step">
              <h2 className="setup-step-title"><Trans ns="setup" i18nKey="setupWizard.headings.createAdminAccount" /></h2>
              <p className="setup-step-description">
                <Trans ns="setup" i18nKey="setupWizard.text.createAdministratorAccountManagePlatformAccount" /></p>

              {adminError && (
                <div className="setup-alert setup-alert-error" role="alert">
                  {adminError}
                </div>
              )}

              <form onSubmit={handleCreateAdmin} className="setup-form">
                <div className="setup-form-field">
                  <label htmlFor="admin-email" className="setup-form-label"><Trans ns="setup" i18nKey="setupWizard.fields.emailAddress" /></label>
                  <input
                    id="admin-email"
                    ref={adminEmailInput}
                    type="email"
                    value={adminEmail}
                    onChange={(e) => {
                      setAdminEmail(e.target.value);
                      if (e.currentTarget.validity.valid) setAdminEmailError(null);
                    }}
                    onInvalid={handleAdminEmailInvalid}
                    disabled={adminSubmitting}
                    className="setup-form-input"
                    placeholder={i18n.t('setup:setupWizard.placeholders.adminExampleCom')}
                    autoFocus
                    autoComplete="email"
                    aria-invalid={adminEmailError ? true : undefined}
                    aria-describedby={adminEmailError ? 'admin-email-error' : undefined}
                  />
                  {adminEmailError && (
                    <p id="admin-email-error" className="setup-form-error" role="alert">
                      {adminEmailError}
                    </p>
                  )}
                </div>

                <div className="setup-form-field">
                  <label htmlFor="admin-password" className="setup-form-label"><Trans ns="common" i18nKey="fields.password" /></label>
                  <PasswordInput
                    id="admin-password"
                    value={adminPassword}
                    onChange={(e) => setAdminPassword(e.target.value)}
                    disabled={adminSubmitting}
                    placeholder={i18n.t('setup:setupWizard.placeholders.createStrongPassword')}
                    autoComplete="new-password"
                  />
                  
                  <PasswordStrengthIndicator
                    password={adminPassword}
                    email={adminEmail}
                    showMeter={true}
                    showChecklist={true}
                  />
                </div>

                <div className="setup-form-field">
                  <label htmlFor="admin-confirm-password" className="setup-form-label"><Trans ns="setup" i18nKey="setupWizard.fields.confirmPassword" /></label>
                  <PasswordInput
                    id="admin-confirm-password"
                    value={adminConfirmPassword}
                    onChange={(e) => setAdminConfirmPassword(e.target.value)}
                    disabled={adminSubmitting}
                    placeholder={i18n.t('setup:setupWizard.placeholders.reEnterPassword')}
                    autoComplete="new-password"
                  />
                </div>

                <div className="setup-form-actions">
                  <button
                    type="submit"
                    disabled={adminSubmitting}
                    className="setup-btn setup-btn-primary"
                  >
                    {adminSubmitting ? i18n.t('setup:setupWizard.actions.creatingAccount') : i18n.t('setup:setupWizard.actions.createAdminAccount')}
                  </button>
                </div>
              </form>
            </div>
          )}

          
          {currentStep === 'secure' && (
            <div className="setup-step">
              <h2 className="setup-step-title">{i18n.t('setup:passkey.title')}</h2>
              <p className="setup-step-description">{i18n.t('setup:passkey.description')}</p>
              <div className="setup-info-banner">{i18n.t('setup:passkey.supporting')}</div>
              {passkeyMessage && (
                <div className="setup-alert setup-alert-error" role="alert">
                  {i18n.t(`setup:passkey.${passkeyMessage}`)}
                </div>
              )}
              <div className="setup-form">
                <p className="setup-form-hint">{i18n.t('setup:passkey.note')}</p>
                <div className="setup-form-actions-row">
                  <button type="button" className="setup-btn setup-btn-primary"
                    disabled={passkeyBusy} onClick={() => void handleCreatePasskey()}>
                    {i18n.t(passkeyBusy ? 'setup:passkey.creating' : 'setup:passkey.create')}
                  </button>
                </div>
                <div className="setup-form-actions setup-form-actions-row">
                  <button type="button" className="setup-btn setup-btn-secondary" onClick={continueAfterPasskey}>
                    {i18n.t('setup:passkey.skip')}
                  </button>
                </div>
              </div>
            </div>
          )}

          {currentStep === 'datasource' && (
            <div className="setup-step">
              <h2 className="setup-step-title"><Trans ns="setup" i18nKey="setupWizard.headings.configureDataSource" /></h2>
              <p className="setup-step-description">
                <Trans ns="setup" i18nKey="setupWizard.text.optionallyConfigureExternalDataSourceStart" /></p>

              <div className="setup-info-banner">
                <strong><Trans ns="setup" i18nKey="setupWizard.text.note" /></strong> <Trans ns="setup" i18nKey="setupWizard.text.noMeasurementDataWillAvailableUntil" /></div>

              {sourceLoading && <div className="setup-info-banner" role="status"><Trans ns="common" i18nKey="states.loading" /></div>}
              {sourceError && (
                <div className="setup-alert setup-alert-error" role="alert">
                  {sourceError}
                </div>
              )}

              <div className="setup-form">
                <div className="setup-source-options">
                  {dataSources.map((source) => {
                    const draft = sourceDrafts[source.external_api_id] ?? { apiKey: '' };
                    return (
                      <section key={source.external_api_id} className="setup-source-card selected">
                        <div className="setup-source-info">
                          <strong>{source.name}</strong>
                          {source.description && !source.provider_code && (
                            <span className="setup-source-desc">
                              {source.description}
                            </span>
                          )}
                        </div>
                        {source.requires_credential === false && source.provider_code !== 'airgradient' ? (
                          <div className="setup-form-field">
                            {source.provider_code === 'demo' && <>
                              <p className="setup-form-hint"><Trans ns="dataSources" i18nKey="demo.description" /></p>
                              <p className="setup-form-hint"><Trans ns="dataSources" i18nKey="demo.setupHelp" /></p>
                            </>}
                            <p className="setup-form-hint"><Trans ns="dataSources" i18nKey="credentialFree" /></p>
                            <label className="setup-source-toggle">
                              <input type="checkbox" checked={source.enabled} disabled={sourceSaving}
                                onChange={event => void handleSourceEnabled(source, event.target.checked)} />
                              {i18n.t('dataSources:enableSource', { name: source.name })}
                            </label>
                            <span role="status">{i18n.t(source.enabled ? 'admin:workspace.enabled' : 'admin:workspace.disabled')}</span>
                            {source.provider_code === 'demo' && <p className="setup-form-hint"><Trans ns="dataSources" i18nKey="demo.disableHelp" /></p>}
                          </div>
                        ) : <div className="setup-form-field">
                          {source.provider_code === 'airgradient' && <>
                            <p className="setup-form-hint">{i18n.t('dataSources:airgradientPublicHelp')}</p>
                            <label className="setup-source-toggle">
                              <input type="checkbox" checked={source.enabled} disabled={sourceSaving}
                                onChange={event => void handleSourceEnabled(source, event.target.checked)} />
                              {i18n.t('dataSources:enableSource', { name: source.name })}
                            </label>
                          </>}
                          <label htmlFor={`source-api-key-${source.external_api_id}`} className="setup-form-label">
                            <Trans ns="setup" i18nKey="setupWizard.fields.apiKey" />
                          </label>
                          <input
                            id={`source-api-key-${source.external_api_id}`}
                            type="text"
                            value={draft.apiKey}
                            onChange={(event) => setSourceDrafts((current) => ({
                              ...current,
                              [source.external_api_id]: { ...draft, apiKey: event.target.value },
                            }))}
                            disabled={sourceSaving}
                            className="setup-form-input setup-source-api-key-input"
                            placeholder={i18n.t(source.provider_code === 'airgradient'
                              ? 'dataSources:adminSourceForm.placeholders.airGradientApiKey'
                              : 'setup:setupWizard.placeholders.optionalApiKey')}
                          />
                          {source.provider_code === 'airgradient' && <>
                            <label className="setup-source-toggle">
                              <input type="checkbox" checked={importAuthenticatedLocations} disabled={sourceSaving}
                                aria-describedby="setup-airgradient-owned-locations-help"
                                onChange={event => setImportAuthenticatedLocations(event.target.checked)} />
                              {i18n.t('dataSources:adminSourceForm.text.importAuthenticatedLocations')}
                            </label>
                            <p id="setup-airgradient-owned-locations-help" className="setup-form-hint">
                              {i18n.t('dataSources:adminSourceForm.text.authenticatedLocationsHelp')}
                            </p>
                          </>}
                        </div>}
                      </section>
                    );
                  })}
                </div>

                <div className="setup-form-actions-row">
                  <button
                    type="button"
                    onClick={handleSaveDataSources}
                    disabled={sourceSaving || sourceLoading}
                    className="setup-btn setup-btn-primary"
                  >
                    {sourceSaving ? i18n.t('setup:setupWizard.actions.saving') : i18n.t('setup:setupWizard.actions.saveSourcesContinue')}
                  </button>
                </div>

                <div className="setup-form-actions">
                  {!initialAdminCreated && (
                    <button
                      type="button"
                      onClick={() => setCurrentStep('admin')}
                      disabled={sourceSaving}
                      className="setup-btn setup-btn-text"
                    >
                      <Trans ns="setup" i18nKey="setupWizard.actions.back" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={handleSkipDataSource}
                    disabled={sourceSaving || sourceLoading}
                    className="setup-btn setup-btn-secondary"
                  >
                    <Trans ns="setup" i18nKey="setupWizard.actions.skipNow" /></button>
                </div>
              </div>
            </div>
          )}

          
          {currentStep === 'geoapify' && (
            <div className="setup-step">
              <h2 className="setup-step-title"><Trans ns="setup" i18nKey="setupWizard.headings.configureLocationSearch" /></h2>
              <p className="setup-step-description">
                <Trans ns="setup" i18nKey="setupWizard.text.optionallyConfigureGeoapifyApiKeyEnable" /></p>

              <div className="setup-info-banner">
                <strong><Trans ns="setup" i18nKey="setupWizard.text.note2" /></strong> <Trans ns="setup" i18nKey="setupWizard.text.withoutGeoapifyApiKeyMapLocation" /></div>

              {geoapifyError && (
                <div className="setup-alert setup-alert-error">
                  {geoapifyError}
                </div>
              )}

              <div className="setup-form">
                <div className="setup-form-field">
                  <label htmlFor="geoapify-key" className="setup-form-label"><Trans ns="setup" i18nKey="setupWizard.fields.geoapifyApiKey" /></label>
                  <PasswordInput
                    id="geoapify-key"
                    value={geoapifyKey}
                    onChange={(e) => {
                      setGeoapifyKey(e.target.value);
                    }}
                    disabled={geoapifySaving}
                    placeholder={i18n.t('setup:setupWizard.placeholders.enterGeoapifyApiKey')}
                    autoComplete="off"
                  />
                  <p className="setup-form-hint">
                    <Trans ns="setup" i18nKey="setupWizard.text.getFreeApiKey" /> <a href="https://www.geoapify.com/" target="_blank" rel="noopener noreferrer">geoapify.com</a>
                  </p>
                </div>

                <div className="setup-form-actions-row">
                  <button
                    type="button"
                    onClick={handleSaveGeoapify}
                    disabled={!geoapifyKey.trim() || geoapifySaving}
                    className="setup-btn setup-btn-primary"
                  >
                    {geoapifySaving ? i18n.t('setup:setupWizard.actions.saving2') : i18n.t('setup:setupWizard.actions.saveContinue2')}
                  </button>
                </div>

                <div className="setup-form-actions">
                  <button
                    type="button"
                    onClick={() => setCurrentStep('datasource')}
                    className="setup-btn setup-btn-text"
                  >
                    <Trans ns="setup" i18nKey="setupWizard.actions.back2" /></button>
                  <button
                    type="button"
                    onClick={handleSkipGeoapify}
                    className="setup-btn setup-btn-secondary"
                  >
                    <Trans ns="setup" i18nKey="setupWizard.actions.skipNow2" /></button>
                </div>
              </div>
            </div>
          )}

          
          {currentStep === 'complete' && (
            <div className="setup-step">
              <h2 className="setup-step-title"><Trans ns="setup" i18nKey="setupWizard.headings.setupComplete" /></h2>
              <p className="setup-step-description">
                <Trans ns="setup" i18nKey="setupWizard.text.youReAllSetClickButton" /></p>

              <div className="setup-summary">
                <div className="setup-summary-item">
                  <span className="setup-summary-icon">✓</span>
                  <span><Trans ns="setup" i18nKey="setupWizard.text.adminAccountCreated" /></span>
                </div>
                <div className="setup-summary-item">
                  <span className="setup-summary-icon">{sourceConfiguredAndEnabled ? '✓' : '○'}</span>
                  <span>
                    {sourceConfiguredAndEnabled
                      ? i18n.t('setup:setupWizard.text.dataSourceConfiguredAndEnabled')
                      : i18n.t('setup:setupWizard.text.dataSourceNotConfiguredCanDone')
                    }
                  </span>
                </div>
                {dataSources.filter(source => source.provider_code === 'demo').map(source => (
                  <div className="setup-summary-item" key={source.external_api_id}>
                    <span className="setup-summary-icon">{source.enabled ? '✓' : '○'}</span>
                    <span>{source.name}: {i18n.t(source.enabled ? 'admin:workspace.enabled' : 'admin:workspace.disabled')}</span>
                  </div>
                ))}
                <div className="setup-summary-item">
                  <span className="setup-summary-icon">{geoapifyConfigured ? '✓' : '○'}</span>
                  <span>
                    {geoapifyConfigured
                      ? i18n.t('setup:setupWizard.text.locationSearchConfigured')
                      : i18n.t('setup:setupWizard.text.locationSearchNotConfiguredCanDone')
                    }
                  </span>
                </div>
              </div>

              {completionError && (
                <div className="setup-alert setup-alert-error">
                  {completionError}
                </div>
              )}

              <div className="setup-form-actions">
                <button
                  type="button"
                  onClick={() => setCurrentStep('geoapify')}
                  className="setup-btn setup-btn-text"
                >
                  <Trans ns="setup" i18nKey="setupWizard.actions.back3" /></button>
                <button
                  type="button"
                  onClick={handleCompleteSetup}
                  disabled={completing}
                  className="setup-btn setup-btn-primary setup-btn-large"
                >
                  {completing ? i18n.t('setup:setupWizard.actions.completingSetup') : i18n.t('setup:setupWizard.actions.completeSetupStartUsingPlatform')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
