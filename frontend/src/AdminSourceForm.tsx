import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useRef, useState } from 'react';
import type { ExternalAPI } from './api';
import { updateExternalAPI, createExternalAPI, deleteExternalAPI } from './api';
import OpenAQFields from './OpenAQFields';
import PurpleAirFields from './PurpleAirFields';
import { sourceReadinessKey } from './sourceReadinessPresentation';

export default function AdminSourceForm(props: { selectedExternalAPI: ExternalAPI | null; externalAPIs?: ExternalAPI[]; onSaved?: (api: ExternalAPI)=>void; onCreated?: (api: ExternalAPI)=>void; onDeleted?: ()=>void }) {
  const { selectedExternalAPI, onSaved, onCreated, onDeleted } = props;

  const [apiEditing, setApiEditing] = useState<{ base_url?: string; description?: string; api_key?: string }>({});
  const savingRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const saveButtonRef = useRef<HTMLButtonElement>(null);
  const restoreSaveFocus = useRef(false);
  useEffect(() => {
    if (!saving && restoreSaveFocus.current) {
      if (document.activeElement === document.body) saveButtonRef.current?.focus();
      restoreSaveFocus.current = false;
    }
  }, [saving]);
  const [apiKeyMode, setApiKeyMode] = useState<'unchanged' | 'replace' | 'clear'>('unchanged');
  const [apiKeyError, setApiKeyError] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState<{ message: string; error: boolean } | null>(null);
  const [enabledIntent, setEnabledIntent] = useState(false);
  const [importAuthenticatedLocations, setImportAuthenticatedLocations] = useState(true);
  const [apiParamsText, setApiParamsText] = useState<string>('');
  const [purpleairLookback, setPurpleairLookback] = useState<number | undefined>(undefined);
  const [skipParamsSync, setSkipParamsSync] = useState(false);
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (syncTimerRef.current) {
      clearTimeout(syncTimerRef.current);
    }
  }, []);


  useEffect(() => {
    if (!selectedExternalAPI) {
      setApiEditing({});
      setApiKeyMode('unchanged');
      setApiKeyError(null);
      setEnabledIntent(false);
      setPurpleairLookback(undefined);
      return;
    }
    setApiEditing({
      base_url: selectedExternalAPI.base_url || '',
      description: selectedExternalAPI.description || '',
      api_key: '',
    });
    setEnabledIntent(selectedExternalAPI.enabled);
    setImportAuthenticatedLocations(selectedExternalAPI.params?.import_authenticated_locations
      ?? Boolean(selectedExternalAPI.credential_configured ?? selectedExternalAPI.has_api_key));

    if (!skipParamsSync && selectedExternalAPI.name !== 'PurpleAir') {
      try {
        setApiParamsText(selectedExternalAPI.params ? JSON.stringify(selectedExternalAPI.params, null, 2) : '{}');
      } catch {
        setApiParamsText('{}');
      }
    }

    if (selectedExternalAPI.name === 'PurpleAir') {
      try {
        const p = selectedExternalAPI.params || {};
        const v = p?.max_lookback_hours;
        setPurpleairLookback(v != null ? Number(v) : 24);
      } catch {
        setPurpleairLookback(24);
      }
    }
    setApiKeyMode('unchanged');
    setApiKeyError(null);
  // `skipParamsSync` intentionally excluded so recently-saved values are not overwritten
  // when the flag toggles; the early-return logic above handles that case.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedExternalAPI]);

  if (!selectedExternalAPI) return null;
  const isDemoSource = selectedExternalAPI.provider_code === 'demo';
  const showsCredential = !isDemoSource && (selectedExternalAPI.requires_credential !== false || selectedExternalAPI.provider_code === 'airgradient');
  const isPurpleAirSource = selectedExternalAPI.name === 'PurpleAir';
  const isAirGradientSource = selectedExternalAPI.provider_code === 'airgradient'
    || selectedExternalAPI.name === 'AirGradient';

  return (
    <div className={`admin-sources-form${isPurpleAirSource ? ' purpleair-source-form-layout' : ''}`}>
      {isDemoSource && <div className="card">
        <p>{i18n.t('dataSources:demo.description')}</p>
        <p>{i18n.t('dataSources:credentialFree')}</p>
      </div>}
      <div
        className={isPurpleAirSource ? 'card admin-source-configuration-card' : 'admin-source-configuration'}
        role={isPurpleAirSource ? 'region' : undefined}
        aria-label={isPurpleAirSource ? i18n.t('dataSources:adminSourceForm.text.dataSourceConfiguration') : undefined}
      >
        <fieldset className="admin-source-configuration-fields source-edit-fields" disabled={saving} onChange={() => setSaveNotice(null)}>
          <legend className="sr-only">{i18n.t("dataSources:adminSourceForm.text.dataSourceConfiguration")}</legend>
          {showsCredential && <div className="form-field">
            {isAirGradientSource && <p>{i18n.t('dataSources:airgradientPublicHelp')}</p>}
            <div>
              <Trans ns="dataSources" i18nKey="adminSourceForm.text.apiKey" />
            </div>
            {selectedExternalAPI.has_api_key && apiKeyMode === 'unchanged' ? (
              <>
                <input
                  className="text-input api-key-input"
                  type="password"
                  value="••••••••••••••••"
                  readOnly
                  aria-label={i18n.t('dataSources:adminSourceForm.accessibility.storedCredential')}
                />
                <div className="credential-state"><Trans ns="dataSources" i18nKey="adminSourceForm.text.credentialStored" /></div>
                <div className="credential-actions">
                  <button type="button" className="btn btn-secondary small" onClick={() => { setApiKeyMode('replace'); setApiEditing({ ...apiEditing, api_key: '' }); }}>
                    <Trans ns="dataSources" i18nKey="adminSourceForm.actions.replaceCredential" />
                  </button>
                  <button type="button" className="btn ghost small" onClick={() => { setApiKeyMode('clear'); setApiEditing({ ...apiEditing, api_key: '' }); }}>
                    <Trans ns="dataSources" i18nKey="adminSourceForm.actions.removeCredential" />
                  </button>
                </div>
              </>
            ) : (
              <>
                {apiKeyMode !== 'clear' && (
                  <input
                    aria-label={i18n.t('dataSources:adminSourceForm.text.apiKey')} className={`text-input api-key-input ${apiKeyError ? 'input-invalid' : ''}`}
                    type="password"
                    value={apiEditing.api_key || ''}
                    onChange={e=>{ setApiEditing({...apiEditing, api_key: e.target.value}); setApiKeyMode('replace'); setApiKeyError(null); }}
                    placeholder={i18n.t(selectedExternalAPI.has_api_key
                      ? 'dataSources:adminSourceForm.placeholders.replacementApiKey'
                      : isAirGradientSource
                        ? 'dataSources:adminSourceForm.placeholders.airGradientApiKey'
                        : 'dataSources:adminSourceForm.placeholders.apiKey')}
                    aria-invalid={apiKeyError ? true : undefined}
                  />
                )}
                <div className={apiKeyMode === 'clear' ? 'credential-state credential-remove-state' : 'muted'}>
                  {apiKeyMode === 'clear'
                    ? i18n.t('dataSources:adminSourceForm.text.credentialWillBeRemoved')
                    : selectedExternalAPI.has_api_key
                      ? i18n.t('dataSources:adminSourceForm.text.enterReplacementCredential')
                      : i18n.t(isAirGradientSource && selectedExternalAPI.requires_credential === false && selectedExternalAPI.credential_configured !== true
                        ? 'dataSources:airgradientOptionalCredential'
                        : selectedExternalAPI.is_configured === true
                          ? 'dataSources:workflow.deploymentCredential'
                          : 'dataSources:adminSourceForm.text.credentialRequiredWhenEnabled')}
                </div>
                {selectedExternalAPI.has_api_key && (
                  <button type="button" className="btn ghost small credential-keep-button" onClick={() => { setApiKeyMode('unchanged'); setApiEditing({ ...apiEditing, api_key: '' }); setApiKeyError(null); }}>
                    <Trans ns="dataSources" i18nKey="adminSourceForm.actions.keepCredential" />
                  </button>
                )}
              </>
            )}
            {apiKeyError && apiKeyMode === 'replace' && (
              <div className="field-error" role="alert" style={{color:'#b00020', marginTop:6}}>{apiKeyError}</div>
            )}
          </div>}

          <div className="form-field">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <input
                type="checkbox"
                checked={enabledIntent}
                disabled={saving}
                aria-describedby={isDemoSource ? "demo-disable-help" : undefined}
                onChange={(e) => setEnabledIntent(e.target.checked)}
              />
              <span>{isDemoSource ? i18n.t('dataSources:enableSource', { name: selectedExternalAPI.name }) : i18n.t('dataSources:adminSourceForm.text.enabled')}</span>
            </label>
            {isDemoSource && <p id="demo-disable-help">{i18n.t('dataSources:demo.disableHelp')}</p>}
            {enabledIntent && !['ready', 'disabled'].includes(sourceReadinessKey(selectedExternalAPI)) && (
              <div className="warning-banner source-configuration-warning" role="status">
                {i18n.t(`dataSources:workflow.${sourceReadinessKey(selectedExternalAPI)}`)}
              </div>
            )}
          </div>
          {isAirGradientSource && <div className="form-field">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" checked={importAuthenticatedLocations} disabled={saving}
                aria-describedby="airgradient-owned-locations-help"
                onChange={event => setImportAuthenticatedLocations(event.target.checked)} />
              <span>{i18n.t('dataSources:adminSourceForm.text.importAuthenticatedLocations')}</span>
            </label>
            <p id="airgradient-owned-locations-help">
              {i18n.t('dataSources:adminSourceForm.text.authenticatedLocationsHelp')}
            </p>
          </div>}
          {!isDemoSource && <><div className="form-field">
            <div><Trans ns="dataSources" i18nKey="adminSourceForm.text.baseUrl" /></div>
            <input aria-label={i18n.t('dataSources:adminSourceForm.text.baseUrl')} className="text-input" value={apiEditing.base_url || ''} onChange={e=>setApiEditing({...apiEditing, base_url: e.target.value})} placeholder="https://api.example.com" />
          </div>



          <div className="form-field admin-extapi-desc">
            <div><Trans ns="dataSources" i18nKey="adminSourceForm.text.description" /></div>
            <input aria-label={i18n.t('dataSources:adminSourceForm.text.description')} className="text-input" value={apiEditing.description || ''} onChange={e=>setApiEditing({...apiEditing, description: e.target.value})} placeholder={i18n.t('dataSources:adminSourceForm.placeholders.apiDescription')} />
          </div>


          </>}
          {selectedExternalAPI?.name === 'OpenAQ' && (
            <OpenAQFields
              apiEditing={apiEditing}
              setApiEditing={setApiEditing}
              selectedExternalAPI={selectedExternalAPI}
              apiParamsText={apiParamsText}
              setApiParamsText={setApiParamsText}
            />
          )}
          {selectedExternalAPI?.name === 'PurpleAir' && (
            <>
              <PurpleAirFields />
              <div className="form-field">
                <div>
                  <Trans ns="dataSources" i18nKey="adminSourceForm.text.maxLookbackHours" /><span className="hint" style={{ marginLeft: 8, fontSize: '0.85em', color: '#666' }}><Trans ns="dataSources" i18nKey="adminSourceForm.text.limitsImporterHistoryFetchWindow" /></span>
                </div>
                <input
                  type="number"
                  className="text-input"
                  aria-label={i18n.t('dataSources:adminSourceForm.text.maxLookbackHours')}
                  value={purpleairLookback ?? ''}
                  onChange={e => setPurpleairLookback(e.target.value ? Number(e.target.value) : undefined)}
                  min={1}
                  max={168}
                  step={1}
                />
              </div>
            </>
          )}

        </fieldset>

        {saveNotice && <div className={saveNotice.error ? 'error-banner' : 'success-banner'} role={saveNotice.error ? 'alert' : 'status'}>{saveNotice.message}</div>}
        <div className="save-actions admin-form-save-actions">
        <button ref={saveButtonRef} className="btn btn-primary" disabled={saving || !(selectedExternalAPI && selectedExternalAPI.external_api_id > 0)} onClick={async ()=>{
          if (savingRef.current || !selectedExternalAPI || selectedExternalAPI.external_api_id <= 0) return;

          if (apiKeyMode === 'replace' && !(apiEditing.api_key || '').trim()) {
            setApiKeyError(i18n.t('dataSources:adminSourceForm.validation.replacementApiKeyRequired'));
            return;
          }

          restoreSaveFocus.current = document.activeElement === saveButtonRef.current;
          savingRef.current = true;
          setSaving(true);
          setSaveNotice(null);
          try {
            let paramsPayload: any = {};
            if (selectedExternalAPI.name === 'PurpleAir') {
              const existing = selectedExternalAPI.params || {};
              paramsPayload = { ...existing };
              if (purpleairLookback != null) paramsPayload.max_lookback_hours = Number(purpleairLookback);
            } else {
              paramsPayload = JSON.parse(apiParamsText || '{}');
            }
            if (isAirGradientSource) paramsPayload.import_authenticated_locations = importAuthenticatedLocations;

            const payload: Parameters<typeof updateExternalAPI>[1] = {
              base_url: apiEditing.base_url || undefined,
              description: apiEditing.description || undefined,
              params: paramsPayload,
              enabled: enabledIntent,
            };
            if (apiKeyMode === 'replace') payload.api_key = apiEditing.api_key?.trim() || null;
            if (apiKeyMode === 'clear') payload.api_key = null;
            const updated = await updateExternalAPI(selectedExternalAPI.external_api_id, isDemoSource ? { enabled: enabledIntent } : payload);

            try {
              const p = updated.params;
              if (selectedExternalAPI.name !== 'PurpleAir') {
                try { setApiParamsText(p ? JSON.stringify(p, null, 2) : '{}'); } catch { setApiParamsText('{}'); }
              }
            } catch {
              // ignore UI sync errors
            }
            onSaved?.(updated);
            setSaveNotice({ message: i18n.t('dataSources:adminSourceForm.notifications.dataSourceUpdated'), error: false });
          } catch { setSaveNotice({ message: i18n.t('common:errors.update'), error: true }); }
          finally {
            savingRef.current = false;
            setSaving(false);


            if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
            setSkipParamsSync(true);
            syncTimerRef.current = setTimeout(() => setSkipParamsSync(false), 1500);
          }
        }}>{saving ? i18n.t('common:actions.savingChanges') : i18n.t('common:actions.saveChanges')}</button>

        {selectedExternalAPI && selectedExternalAPI.external_api_id <= 0 && (
          <div className="create-button-wrap">
            <button className="btn" onClick={async ()=>{
              if (!selectedExternalAPI) return;
              try {
                let paramsPayload: any = {};
                if (selectedExternalAPI.name === 'PurpleAir') {
                  paramsPayload = {};
                  if (purpleairLookback != null) paramsPayload.max_lookback_hours = Number(purpleairLookback);
                } else {
                  paramsPayload = JSON.parse(apiParamsText || '{}');
                }
                if (isAirGradientSource) paramsPayload.import_authenticated_locations = importAuthenticatedLocations;

                const created = await createExternalAPI({
                  name: selectedExternalAPI.name,
                  base_url: apiEditing.base_url || undefined,

                  description: apiEditing.description || undefined,
                  api_key: apiEditing.api_key || null,
                  params: paramsPayload,
                  enabled: enabledIntent,
                });

                try {
                  const p = created.params;
                  if (selectedExternalAPI.name !== 'PurpleAir') {
                    try { setApiParamsText(p ? JSON.stringify(p, null, 2) : '{}'); } catch { setApiParamsText('{}'); }
                  }
                } catch { /* ignore UI sync errors */ }
                onCreated?.(created);
                alert(i18n.t('dataSources:adminSourceForm.notifications.createdExternalApi'));
              } catch { alert(i18n.t('common:errors.create')); }
                finally {
                  if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
                  setSkipParamsSync(true);
                  syncTimerRef.current = setTimeout(() => setSkipParamsSync(false), 1500);
                }
            }}><Trans ns="dataSources" i18nKey="adminSourceForm.actions.createSource" /></button>
          </div>
        )}

        {selectedExternalAPI?.can_delete && selectedExternalAPI.external_api_id > 0 && (
          <button
            className="btn btn-danger admin-form-destructive"
            disabled={saving}
            type="button"
            onClick={async () => {
              if (!selectedExternalAPI) return;
              if (!confirm(i18n.t('dataSources:adminSourceForm.dialogs.deleteDataSource', { name: selectedExternalAPI.name }))) return;
              try {
                await deleteExternalAPI(selectedExternalAPI.external_api_id);
                onDeleted?.();
              } catch {
                alert(i18n.t('common:errors.deleteDataSource'));
              }
            }}
          >
            <Trans ns="common" i18nKey="actions.delete" /></button>
        )}
        </div>
      </div>

    </div>
  );
}
