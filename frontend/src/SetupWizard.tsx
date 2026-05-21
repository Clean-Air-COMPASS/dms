

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import PasswordInput from './components/PasswordInput';
import PasswordStrengthIndicator from './components/PasswordStrengthIndicator';
import { validatePasswordStrength } from './utils/passwordStrength';
import { API_BASE } from './apiBase';


interface DataSource {
  external_api_id: number;
  name: string;
  description: string | null;
  has_api_key: boolean;
}

interface VerifyResponse {
  success: boolean;
  message: string;
  provider_name?: string;
}


type WizardStep = 'admin' | 'datasource' | 'geoapify' | 'complete';

interface SetupWizardProps {
  onSetupComplete: () => void;
}

export default function SetupWizard({ onSetupComplete }: SetupWizardProps) {
  
  const [currentStep, setCurrentStep] = useState<WizardStep>('admin');
  
  
  const [adminEmail, setAdminEmail] = useState('');
  const [adminPassword, setAdminPassword] = useState('');
  const [adminConfirmPassword, setAdminConfirmPassword] = useState('');
  const [adminError, setAdminError] = useState<string | null>(null);
  const [adminSuccess, setAdminSuccess] = useState(false);
  const [adminSubmitting, setAdminSubmitting] = useState(false);
  
  
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(null);
  const [sourceApiKey, setSourceApiKey] = useState('');
  const [sourceConfirmApiKey, setSourceConfirmApiKey] = useState('');
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [sourceSuccess, setSourceSuccess] = useState<string | null>(null);
  const [sourceVerifying, setSourceVerifying] = useState(false);
  const [sourceVerified, setSourceVerified] = useState(false);
  const [sourceSaving, setSourceSaving] = useState(false);
  
  
  const [geoapifyKey, setGeoapifyKey] = useState('');
  const [geoapifyError, setGeoapifyError] = useState<string | null>(null);
  const [geoapifySuccess, setGeoapifySuccess] = useState<string | null>(null);
  const [geoapifyVerifying, setGeoapifyVerifying] = useState(false);
  const [geoapifyVerified, setGeoapifyVerified] = useState(false);
  const [geoapifySaving, setGeoapifySaving] = useState(false);
  
  
  const [completing, setCompleting] = useState(false);
  const [completionError, setCompletionError] = useState<string | null>(null);

  
  useEffect(() => {
    async function loadDataSources() {
      try {
        const resp = await fetch(`${API_BASE}/setup/data-sources`);
        if (resp.ok) {
          const data = await resp.json();
          setDataSources(data.data_sources || []);
        }
      } catch {
        // Ignore errors - data sources are optional
      }
    }
    loadDataSources();
  }, []);

  
  const passwordStrength = useMemo(
    () => validatePasswordStrength(adminPassword, adminEmail),
    [adminPassword, adminEmail]
  );

  
  const handleCreateAdmin = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setAdminError(null);
    setAdminSuccess(false);

    
    if (!adminEmail.trim()) {
      setAdminError('Email address is required');
      return;
    }

    
    if (!adminPassword) {
      setAdminError('Password is required');
      return;
    }

    
    if (!passwordStrength.isValid) {
      setAdminError('Please choose a stronger password that meets all requirements.');
      return;
    }

    
    if (adminPassword !== adminConfirmPassword) {
      setAdminError('Passwords do not match');
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

      const data = await resp.json();
      
      if (resp.ok && data.success) {
        setAdminSuccess(true);
        
        setTimeout(() => setCurrentStep('datasource'), 1500);
      } else {
        
        setAdminError(data.detail || 'Failed to create admin account');
      }
    } catch {
      setAdminError('Network error. Please try again.');
    } finally {
      setAdminSubmitting(false);
    }
  }, [adminEmail, adminPassword, adminConfirmPassword, passwordStrength.isValid]);

  
  const handleVerifyDataSource = useCallback(async () => {
    if (!selectedSourceId || !sourceApiKey.trim()) return;
    
    setSourceError(null);
    setSourceSuccess(null);
    setSourceVerifying(true);
    setSourceVerified(false);

    try {
      const resp = await fetch(`${API_BASE}/setup/verify-data-source`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          external_api_id: selectedSourceId,
          api_key: sourceApiKey.trim(),
        }),
      });

      const data: VerifyResponse = await resp.json();
      
      if (data.success) {
        setSourceSuccess(data.message);
        setSourceVerified(true);
      } else {
        setSourceError(data.message);
      }
    } catch {
      setSourceError('Network error during verification. Please try again.');
    } finally {
      setSourceVerifying(false);
    }
  }, [selectedSourceId, sourceApiKey]);

  
  const handleSaveDataSource = useCallback(async () => {
    if (!selectedSourceId || !sourceApiKey.trim()) return;
    
    
    if (sourceApiKey !== sourceConfirmApiKey) {
      setSourceError('API keys do not match');
      return;
    }

    setSourceError(null);
    setSourceSaving(true);

    try {
      const resp = await fetch(`${API_BASE}/setup/data-source`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          external_api_id: selectedSourceId,
          api_key: sourceApiKey.trim(),
          confirm_api_key: sourceConfirmApiKey.trim(),
        }),
      });

      const data = await resp.json();
      
      if (resp.ok && data.success) {
        setSourceSuccess(data.message + ' Moving to next step...');
        setTimeout(() => setCurrentStep('geoapify'), 1500);
      } else {
        setSourceError(data.detail || 'Failed to save API key');
      }
    } catch {
      setSourceError('Network error. Please try again.');
    } finally {
      setSourceSaving(false);
    }
  }, [selectedSourceId, sourceApiKey, sourceConfirmApiKey]);

  
  const handleVerifyGeoapify = useCallback(async () => {
    if (!geoapifyKey.trim()) return;
    
    setGeoapifyError(null);
    setGeoapifySuccess(null);
    setGeoapifyVerifying(true);
    setGeoapifyVerified(false);

    try {
      const resp = await fetch(`${API_BASE}/setup/verify-geoapify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: geoapifyKey.trim() }),
      });

      const data: VerifyResponse = await resp.json();
      
      if (data.success) {
        setGeoapifySuccess(data.message);
        setGeoapifyVerified(true);
      } else {
        setGeoapifyError(data.message);
      }
    } catch {
      setGeoapifyError('Network error during verification. Please try again.');
    } finally {
      setGeoapifyVerifying(false);
    }
  }, [geoapifyKey]);

  
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

      const data = await resp.json();
      
      if (resp.ok && data.success) {
        setGeoapifySuccess(data.message + ' Moving to final step...');
        setTimeout(() => setCurrentStep('complete'), 1500);
      } else {
        setGeoapifyError(data.detail || 'Failed to save API key');
      }
    } catch {
      setGeoapifyError('Network error. Please try again.');
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
      });

      const data = await resp.json();
      
      if (resp.ok && data.success) {
        onSetupComplete();
      } else {
        setCompletionError(data.detail || 'Failed to complete setup');
      }
    } catch {
      setCompletionError('Network error. Please try again.');
    } finally {
      setCompleting(false);
    }
  }, [onSetupComplete]);

  
  const handleSkipDataSource = () => {
    setCurrentStep('geoapify');
  };

  
  const handleSkipGeoapify = () => {
    setCurrentStep('complete');
  };

  
  const getStepNumber = (step: WizardStep): number => {
    switch (step) {
      case 'admin': return 1;
      case 'datasource': return 2;
      case 'geoapify': return 3;
      case 'complete': return 4;
      default: return 1;
    }
  };

  const currentStepNumber = getStepNumber(currentStep);
  const selectedSource = dataSources.find(s => s.external_api_id === selectedSourceId);

  return (
    <div className="setup-wizard-overlay">
      <div className="setup-wizard-container">
        
        <div className="setup-wizard-header">
          <h1 className="setup-wizard-title">Welcome to COMPASS</h1>
          <p className="setup-wizard-subtitle">Air Quality Data Platform</p>
        </div>

        
        <div className="setup-wizard-progress">
          <div className={`setup-progress-step ${currentStepNumber >= 1 ? 'active' : ''} ${currentStepNumber > 1 ? 'completed' : ''}`}>
            <div className="setup-progress-number">{currentStepNumber > 1 ? '✓' : '1'}</div>
            <div className="setup-progress-label">Admin Account</div>
          </div>
          <div className="setup-progress-line"></div>
          <div className={`setup-progress-step ${currentStepNumber >= 2 ? 'active' : ''} ${currentStepNumber > 2 ? 'completed' : ''}`}>
            <div className="setup-progress-number">{currentStepNumber > 2 ? '✓' : '2'}</div>
            <div className="setup-progress-label">Data Source</div>
          </div>
          <div className="setup-progress-line"></div>
          <div className={`setup-progress-step ${currentStepNumber >= 3 ? 'active' : ''} ${currentStepNumber > 3 ? 'completed' : ''}`}>
            <div className="setup-progress-number">{currentStepNumber > 3 ? '✓' : '3'}</div>
            <div className="setup-progress-label">Location Search</div>
          </div>
          <div className="setup-progress-line"></div>
          <div className={`setup-progress-step ${currentStepNumber >= 4 ? 'active' : ''}`}>
            <div className="setup-progress-number">4</div>
            <div className="setup-progress-label">Complete</div>
          </div>
        </div>

        
        <div className="setup-wizard-content">
          
          {currentStep === 'admin' && (
            <div className="setup-step">
              <h2 className="setup-step-title">Create Admin Account</h2>
              <p className="setup-step-description">
                Create your administrator account to manage the platform. This account will have full access to all features.
              </p>

              {adminError && (
                <div className="setup-alert setup-alert-error">
                  {adminError}
                </div>
              )}

              {adminSuccess && (
                <div className="setup-alert setup-alert-success">
                  Admin account created successfully! Moving to next step...
                </div>
              )}

              <form onSubmit={handleCreateAdmin} className="setup-form">
                <div className="setup-form-field">
                  <label htmlFor="admin-email" className="setup-form-label">Email Address</label>
                  <input
                    id="admin-email"
                    type="email"
                    value={adminEmail}
                    onChange={(e) => setAdminEmail(e.target.value)}
                    disabled={adminSubmitting || adminSuccess}
                    className="setup-form-input"
                    placeholder="admin@example.com"
                    autoFocus
                    autoComplete="email"
                  />
                </div>

                <div className="setup-form-field">
                  <label htmlFor="admin-password" className="setup-form-label">Password</label>
                  <PasswordInput
                    id="admin-password"
                    value={adminPassword}
                    onChange={(e) => setAdminPassword(e.target.value)}
                    disabled={adminSubmitting || adminSuccess}
                    placeholder="Create a strong password"
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
                  <label htmlFor="admin-confirm-password" className="setup-form-label">Confirm Password</label>
                  <PasswordInput
                    id="admin-confirm-password"
                    value={adminConfirmPassword}
                    onChange={(e) => setAdminConfirmPassword(e.target.value)}
                    disabled={adminSubmitting || adminSuccess}
                    placeholder="Re-enter password"
                    autoComplete="new-password"
                  />
                </div>

                <div className="setup-form-actions">
                  <button
                    type="submit"
                    disabled={adminSubmitting || adminSuccess}
                    className="setup-btn setup-btn-primary"
                  >
                    {adminSubmitting ? 'Creating Account...' : 'Create Admin Account'}
                  </button>
                </div>
              </form>
            </div>
          )}

          
          {currentStep === 'datasource' && (
            <div className="setup-step">
              <h2 className="setup-step-title">Configure Data Source</h2>
              <p className="setup-step-description">
                Optionally configure an external data source to start importing air quality measurements.
              </p>

              <div className="setup-info-banner">
                <strong>Note:</strong> No measurement data will be available until at least one data source is configured.
                You can also configure data sources later from the Admin section.
              </div>

              {sourceError && (
                <div className="setup-alert setup-alert-error">
                  {sourceError}
                </div>
              )}

              {sourceSuccess && (
                <div className="setup-alert setup-alert-success">
                  {sourceSuccess}
                </div>
              )}

              <div className="setup-form">
                
                <div className="setup-form-field">
                  <label className="setup-form-label">Select Data Source</label>
                  <div className="setup-source-options">
                    {dataSources.map((source) => (
                      <button
                        key={source.external_api_id}
                        type="button"
                        className={`setup-source-card ${selectedSourceId === source.external_api_id ? 'selected' : ''}`}
                        onClick={() => {
                          setSelectedSourceId(source.external_api_id);
                          setSourceApiKey('');
                          setSourceConfirmApiKey('');
                          setSourceError(null);
                          setSourceSuccess(null);
                          setSourceVerified(false);
                        }}
                      >
                        <div className="setup-source-icon">
                          {source.name === 'OpenAQ' && '🌍'}
                          {source.name === 'PurpleAir' && '🟣'}
                          {source.name === 'AirGradient' && '🌿'}
                          {!['OpenAQ', 'PurpleAir', 'AirGradient'].includes(source.name) && '📡'}
                        </div>
                        <div className="setup-source-info">
                          <strong>{source.name}</strong>
                          {source.description && <span className="setup-source-desc">{source.description}</span>}
                        </div>
                        {source.has_api_key && <span className="setup-source-badge">Configured</span>}
                      </button>
                    ))}
                  </div>
                </div>

                
                {selectedSourceId && (
                  <>
                    <div className="setup-form-field">
                      <label htmlFor="source-api-key" className="setup-form-label">
                        {selectedSource?.name} API Key
                      </label>
                      <PasswordInput
                        id="source-api-key"
                        value={sourceApiKey}
                        onChange={(e) => {
                          setSourceApiKey(e.target.value);
                          setSourceVerified(false);
                          setSourceSuccess(null);
                        }}
                        disabled={sourceSaving}
                        placeholder="Enter your API key"
                      />
                    </div>

                    <div className="setup-form-field">
                      <label htmlFor="source-confirm-api-key" className="setup-form-label">
                        Confirm API Key
                      </label>
                      <PasswordInput
                        id="source-confirm-api-key"
                        value={sourceConfirmApiKey}
                        onChange={(e) => setSourceConfirmApiKey(e.target.value)}
                        disabled={sourceSaving}
                        placeholder="Re-enter API key"
                      />
                    </div>

                    <div className="setup-form-actions-row">
                      <button
                        type="button"
                        onClick={handleVerifyDataSource}
                        disabled={!sourceApiKey.trim() || sourceVerifying || sourceSaving}
                        className="setup-btn setup-btn-secondary"
                      >
                        {sourceVerifying ? 'Verifying...' : sourceVerified ? '✓ Verified' : 'Verify Key'}
                      </button>
                      <button
                        type="button"
                        onClick={handleSaveDataSource}
                        disabled={!sourceApiKey.trim() || !sourceConfirmApiKey.trim() || sourceSaving}
                        className="setup-btn setup-btn-primary"
                      >
                        {sourceSaving ? 'Saving...' : 'Save & Continue'}
                      </button>
                    </div>
                  </>
                )}

                <div className="setup-form-actions">
                  <button
                    type="button"
                    onClick={() => setCurrentStep('admin')}
                    className="setup-btn setup-btn-text"
                  >
                    ← Back
                  </button>
                  <button
                    type="button"
                    onClick={handleSkipDataSource}
                    className="setup-btn setup-btn-secondary"
                  >
                    Skip for Now →
                  </button>
                </div>
              </div>
            </div>
          )}

          
          {currentStep === 'geoapify' && (
            <div className="setup-step">
              <h2 className="setup-step-title">Configure Location Search</h2>
              <p className="setup-step-description">
                Optionally configure a Geoapify API key to enable location search on the map.
              </p>

              <div className="setup-info-banner">
                <strong>Note:</strong> Without a Geoapify API key, the map location search feature will not work.
                You can configure this later from the Admin section.
              </div>

              {geoapifyError && (
                <div className="setup-alert setup-alert-error">
                  {geoapifyError}
                </div>
              )}

              {geoapifySuccess && (
                <div className="setup-alert setup-alert-success">
                  {geoapifySuccess}
                </div>
              )}

              <div className="setup-form">
                <div className="setup-form-field">
                  <label htmlFor="geoapify-key" className="setup-form-label">Geoapify API Key</label>
                  <PasswordInput
                    id="geoapify-key"
                    value={geoapifyKey}
                    onChange={(e) => {
                      setGeoapifyKey(e.target.value);
                      setGeoapifyVerified(false);
                      setGeoapifySuccess(null);
                    }}
                    disabled={geoapifySaving}
                    placeholder="Enter your Geoapify API key"
                    autoComplete="off"
                  />
                  <p className="setup-form-hint">
                    Get a free API key at <a href="https://www.geoapify.com/" target="_blank" rel="noopener noreferrer">geoapify.com</a>
                  </p>
                </div>

                <div className="setup-form-actions-row">
                  <button
                    type="button"
                    onClick={handleVerifyGeoapify}
                    disabled={!geoapifyKey.trim() || geoapifyVerifying || geoapifySaving}
                    className="setup-btn setup-btn-secondary"
                  >
                    {geoapifyVerifying ? 'Verifying...' : geoapifyVerified ? '✓ Verified' : 'Verify Key'}
                  </button>
                  <button
                    type="button"
                    onClick={handleSaveGeoapify}
                    disabled={!geoapifyKey.trim() || geoapifySaving}
                    className="setup-btn setup-btn-primary"
                  >
                    {geoapifySaving ? 'Saving...' : 'Save & Continue'}
                  </button>
                </div>

                <div className="setup-form-actions">
                  <button
                    type="button"
                    onClick={() => setCurrentStep('datasource')}
                    className="setup-btn setup-btn-text"
                  >
                    ← Back
                  </button>
                  <button
                    type="button"
                    onClick={handleSkipGeoapify}
                    className="setup-btn setup-btn-secondary"
                  >
                    Skip for Now →
                  </button>
                </div>
              </div>
            </div>
          )}

          
          {currentStep === 'complete' && (
            <div className="setup-step">
              <h2 className="setup-step-title">Setup Complete!</h2>
              <p className="setup-step-description">
                You're all set! Click the button below to finish setup and start using the platform.
              </p>

              <div className="setup-summary">
                <div className="setup-summary-item">
                  <span className="setup-summary-icon">✓</span>
                  <span>Admin account created</span>
                </div>
                <div className="setup-summary-item">
                  <span className="setup-summary-icon">{selectedSourceId ? '✓' : '○'}</span>
                  <span>
                    {selectedSourceId 
                      ? `${selectedSource?.name} configured` 
                      : 'Data source not configured (can be done in Admin)'
                    }
                  </span>
                </div>
                <div className="setup-summary-item">
                  <span className="setup-summary-icon">{geoapifyVerified ? '✓' : '○'}</span>
                  <span>
                    {geoapifyVerified 
                      ? 'Location search configured' 
                      : 'Location search not configured (can be done in Admin)'
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
                  ← Back
                </button>
                <button
                  type="button"
                  onClick={handleCompleteSetup}
                  disabled={completing}
                  className="setup-btn setup-btn-primary setup-btn-large"
                >
                  {completing ? 'Completing Setup...' : 'Complete Setup & Start Using Platform'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
