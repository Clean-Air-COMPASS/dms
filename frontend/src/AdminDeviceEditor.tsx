import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import AdminPageLayout from './components/AdminPageLayout';
import {
  createDeviceSensorAdmin,
  createDeviceAdmin,
  deleteDeviceSensorAdmin,
  deleteDeviceAdmin,
  fetchJson,
  getDeviceAdmin,
  listExternalAPIs,
  listDeviceSensors,
  updateDeviceSensorAdmin,
  updateDeviceAdmin,
  type DevicePayload,
  type DeviceRecord,
  type DeviceSensorSummary,
  type ExternalAPI,
} from './api';

const OTHER_DATA_SOURCE_VALUE = '__other__';

type FormState = Omit<DevicePayload, 'latitude' | 'longitude' | 'external_api_id'> & {
  latitude?: string | number | null;
  longitude?: string | number | null;
  external_api_id?: string | number | null;
  created_at?: string | null;
  is_external?: boolean;
  data_source_mode?: 'existing' | 'other';
  custom_external_api_name?: string;
};

function toFormState(record?: DeviceRecord): FormState {
  if (!record) {
    return {
      name: '',
      friendly_name: '',
      allow_updates: 'inherit',
      is_external: false,
      data_source_mode: 'existing',
      custom_external_api_name: '',
    };
  }
  return {
    name: record.name || '',
    friendly_name: record.friendly_name || '',
    external_id: record.external_id || '',
    external_api_id: record.external_api_id,
    external_api_name: record.external_api_name || record.network || '',
    latitude: record.latitude ?? undefined,
    longitude: record.longitude ?? undefined,
    timezone: record.timezone || '',
    allow_updates: record.allow_updates || 'inherit',
    created_at: record.created_at || null,
    is_external: record.is_external ?? !!record.external_id,
    data_source_mode: record.manual_data_source_name ? 'other' : 'existing',
    custom_external_api_name: record.manual_data_source_name || '',
  };
}

function normalizeForDirtyCheck(f: FormState): Record<string, unknown> {
  const normalized: Record<string, unknown> = { ...f };
  ['latitude', 'longitude', 'external_api_id'].forEach((k) => {
    const v = normalized[k];
    if (v === '' || v === null) normalized[k] = undefined;
  });
  return normalized;
}

export default function AdminDeviceEditor() {
  const params = useParams();
  const navigate = useNavigate();
  const deviceId = params.deviceId ? Number(params.deviceId) : null;
  const isCreate = !deviceId;

  const [form, setForm] = useState<FormState>(toFormState());
  const [initial, setInitial] = useState<FormState>(toFormState());
  const [loading, setLoading] = useState<boolean>(!isCreate);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [sensors, setSensors] = useState<DeviceSensorSummary[]>([]);
  const [sensorsLoading, setSensorsLoading] = useState<boolean>(false);
  const [sensorsError, setSensorsError] = useState<string | null>(null);
  const [newSensorParameterCode, setNewSensorParameterCode] = useState<string>('');
  const [newSensorAggregationCode, setNewSensorAggregationCode] = useState<string>('');
  const [newSensorExternalId, setNewSensorExternalId] = useState<string>('');
  const [addingSensor, setAddingSensor] = useState<boolean>(false);
  const [editingSensorId, setEditingSensorId] = useState<number | null>(null);
  const [editingSensorParameterCode, setEditingSensorParameterCode] = useState<string>('');
  const [editingSensorAggregationCode, setEditingSensorAggregationCode] = useState<string>('');
  const [editingSensorExternalId, setEditingSensorExternalId] = useState<string>('');
  const [savingSensor, setSavingSensor] = useState<boolean>(false);
  const [deletingSensorId, setDeletingSensorId] = useState<number | null>(null);
  const [parameters, setParameters] = useState<Array<{ code: string; display_name: string }>>([]);
  const [parametersLoading, setParametersLoading] = useState<boolean>(false);
  const [parametersError, setParametersError] = useState<string | null>(null);
  const [aggregationPeriods, setAggregationPeriods] = useState<Array<{ code: string; display_name: string }>>([]);
  const [aggregationPeriodsLoading, setAggregationPeriodsLoading] = useState<boolean>(false);
  const [aggregationPeriodsError, setAggregationPeriodsError] = useState<string | null>(null);
  const [dataSources, setDataSources] = useState<ExternalAPI[]>([]);
  const [dataSourcesLoading, setDataSourcesLoading] = useState<boolean>(false);
  const [dataSourcesError, setDataSourcesError] = useState<string | null>(null);

  
  const isExternal = form.is_external ?? !!form.external_id;

  useEffect(() => {
    let cancelled = false;
    if (!deviceId) return;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const rec = await getDeviceAdmin(deviceId);
        if (cancelled) return;
        const fs = toFormState(rec);
        setForm(fs);
        setInitial(fs);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : 'Failed to load device';
        if (!cancelled) setError(message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [deviceId]);

  useEffect(() => {
    let cancelled = false;
    setParametersLoading(true);
    setParametersError(null);
    (async () => {
      try {
        const list = await fetchJson<Array<{ code: string; display_name: string }>>('/parameters', { skipCache: true });
        if (cancelled) return;
        setParameters(list || []);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : 'Failed to load parameters';
        if (!cancelled) setParametersError(message);
      } finally {
        if (!cancelled) setParametersLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const sortedParameters = useMemo(() => {
    return [...parameters].sort((a, b) =>
      a.display_name.localeCompare(b.display_name, undefined, { sensitivity: 'base' }) ||
      a.code.localeCompare(b.code, undefined, { sensitivity: 'base' })
    );
  }, [parameters]);

  useEffect(() => {
    let cancelled = false;
    setAggregationPeriodsLoading(true);
    setAggregationPeriodsError(null);
    (async () => {
      try {
        const list = await fetchJson<Array<{ code: string; display_name: string }>>('/aggregation_periods', { skipCache: true });
        if (cancelled) return;
        setAggregationPeriods(list || []);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : 'Failed to load time resolutions';
        if (!cancelled) setAggregationPeriodsError(message);
      } finally {
        if (!cancelled) setAggregationPeriodsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const sortedAggregationPeriods = useMemo(() => {
    return [...aggregationPeriods].sort((a, b) =>
      a.display_name.localeCompare(b.display_name, undefined, { sensitivity: 'base' }) ||
      a.code.localeCompare(b.code, undefined, { sensitivity: 'base' })
    );
  }, [aggregationPeriods]);

  useEffect(() => {
    let cancelled = false;
    setDataSourcesLoading(true);
    setDataSourcesError(null);
    (async () => {
      try {
        const list = await listExternalAPIs({ skipCache: true });
        if (cancelled) return;
        setDataSources(list || []);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : 'Failed to load data sources';
        if (!cancelled) setDataSourcesError(message);
      } finally {
        if (!cancelled) setDataSourcesLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const sortedDataSources = useMemo(() => {
    return [...dataSources].sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) ||
      a.external_api_id - b.external_api_id
    );
  }, [dataSources]);

  const availableDataSources = useMemo(() => {
    return sortedDataSources.filter((source) => {
      if (source.is_active !== false) return true;
      return !isCreate && Number(form.external_api_id) === source.external_api_id;
    });
  }, [sortedDataSources, isCreate, form.external_api_id]);

  const aggregationPeriodDisplayByCode = useMemo(() => {
    const byCode = new Map<string, string>();
    sortedAggregationPeriods.forEach((aggregationPeriod) => {
      byCode.set(aggregationPeriod.code.toLowerCase(), aggregationPeriod.display_name);
    });
    return byCode;
  }, [sortedAggregationPeriods]);

  const loadSensors = async (targetDeviceId: number, cancelledRef?: { cancelled: boolean }) => {
    setSensorsLoading(true);
    setSensorsError(null);
    try {
      const list = await listDeviceSensors(targetDeviceId);
      const normalized = (list || []).map((s) => ({
        ...s,
        aggregation_code: s.aggregation_code ?? (s as Record<string, unknown>).aggregation_code as string ?? null,
        parameter_code: s.parameter_code ?? (s as Record<string, unknown>).parameter as string ?? null,
        parameter_name: s.parameter_name ?? (s as Record<string, unknown>).parameter_name as string ?? (s as Record<string, unknown>).parameter as string ?? null,
        unit_symbol: s.unit_symbol ?? (s as Record<string, unknown>).unit as string ?? null,
        value: s.value ?? (s as Record<string, unknown>).latest_value as number ?? null,
        observed_at: s.observed_at ?? (s as Record<string, unknown>).latest_observed_at as string ?? null,
        is_valid: s.is_valid ?? (s as Record<string, unknown>).latest_is_valid as boolean ?? null,
      }));
      if (!cancelledRef?.cancelled) setSensors(normalized);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to load sensors';
      if (!cancelledRef?.cancelled) setSensorsError(message);
    } finally {
      if (!cancelledRef?.cancelled) setSensorsLoading(false);
    }
  };

  useEffect(() => {
    if (!deviceId) return;
    const state = { cancelled: false };
    void loadSensors(deviceId, state);
    return () => { state.cancelled = true; };
  }, [deviceId]);

  const handleAddSensor = async () => {
    if (!deviceId) return;
    const parameterCode = (newSensorParameterCode || '').trim().toLowerCase();
    const aggregationCode = (newSensorAggregationCode || '').trim().toLowerCase();
    if (!parameterCode) {
      setError('Parameter is required to add a sensor.');
      return;
    }
    if (!aggregationCode) {
      setError('Time Resolution is required to add a sensor.');
      return;
    }
    setAddingSensor(true);
    setError(null);
    setSuccess(null);
    try {
      const created = await createDeviceSensorAdmin(deviceId, {
        parameter_code: parameterCode,
        aggregation_code: aggregationCode,
        external_sensor_id: newSensorExternalId.trim() || undefined,
      });
      setSuccess(`Sensor added successfully (Sensor ID ${created.sensor_id}).`);
      setNewSensorAggregationCode('');
      setNewSensorExternalId('');
      await loadSensors(deviceId);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to add sensor';
      setError(message);
    } finally {
      setAddingSensor(false);
    }
  };

  const startEditingSensor = (sensor: DeviceSensorSummary) => {
    setEditingSensorId(sensor.sensor_id);
    setEditingSensorParameterCode(sensor.parameter_code || '');
    setEditingSensorAggregationCode(sensor.aggregation_code || '');
    setEditingSensorExternalId(sensor.external_sensor_id || '');
    setError(null);
    setSuccess(null);
  };

  const cancelEditingSensor = () => {
    setEditingSensorId(null);
    setEditingSensorParameterCode('');
    setEditingSensorAggregationCode('');
    setEditingSensorExternalId('');
  };

  const handleSaveSensor = async (sensorId: number) => {
    if (!deviceId) return;
    const parameterCode = editingSensorParameterCode.trim().toLowerCase();
    const aggregationCode = editingSensorAggregationCode.trim().toLowerCase();
    if (!parameterCode) {
      setError('Parameter is required to update a sensor.');
      return;
    }
    if (!aggregationCode) {
      setError('Time Resolution is required to update a sensor.');
      return;
    }
    setSavingSensor(true);
    setError(null);
    setSuccess(null);
    try {
      await updateDeviceSensorAdmin(deviceId, sensorId, {
        parameter_code: parameterCode,
        aggregation_code: aggregationCode,
        external_sensor_id: editingSensorExternalId.trim() || '',
      });
      await loadSensors(deviceId);
      setSuccess(`Sensor ${sensorId} updated successfully.`);
      cancelEditingSensor();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to update sensor';
      setError(message);
    } finally {
      setSavingSensor(false);
    }
  };

  const handleDeleteSensor = async (sensorId: number) => {
    if (!deviceId) return;
    if (!window.confirm('Delete this sensor? This will also delete its measurements.')) return;
    setDeletingSensorId(sensorId);
    setError(null);
    setSuccess(null);
    try {
      await deleteDeviceSensorAdmin(deviceId, sensorId);
      await loadSensors(deviceId);
      setSuccess(`Sensor ${sensorId} deleted successfully.`);
      if (editingSensorId === sensorId) {
        cancelEditingSensor();
      }
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to delete sensor';
      setError(message);
    } finally {
      setDeletingSensorId(null);
    }
  };

  const isDirty = useMemo(() => {
    return JSON.stringify(normalizeForDirtyCheck(form)) !== JSON.stringify(normalizeForDirtyCheck(initial));
  }, [form, initial]);

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isMetaSave = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's';
      if (isMetaSave) {
        e.preventDefault();
        void handleSave();
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        handleCancel();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const handleChange = (key: keyof FormState, value: unknown) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const toNumberOrUndefined = (val: string | number | undefined | null) => {
    if (val === undefined || val === null || val === '') return undefined;
    const num = Number(val);
    return Number.isFinite(num) ? num : undefined;
  };

  const selectedDataSourceValue = useMemo(() => {
    if (form.data_source_mode === 'other') return OTHER_DATA_SOURCE_VALUE;
    const selectedId = toNumberOrUndefined(form.external_api_id);
    return selectedId === undefined ? '' : String(selectedId);
  }, [form.data_source_mode, form.external_api_id]);

  const handleDataSourceSelection = (value: string) => {
    if (value === OTHER_DATA_SOURCE_VALUE) {
      setForm((prev) => ({
        ...prev,
        data_source_mode: 'other',
      }));
      return;
    }
    setForm((prev) => ({
      ...prev,
      external_api_id: value,
      data_source_mode: 'existing',
      custom_external_api_name: '',
    }));
  };

  const guardNav = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (isDirty && !window.confirm('You have unsaved changes. Leave without saving?')) {
      e.preventDefault();
    }
  };

  const handleCancel = () => {
    if (isDirty && !window.confirm('Discard changes?')) return;
    navigate('/admin/devices');
  };

  const handleSave = async () => {
    setError(null);
    setSuccess(null);

    
    if (isCreate && (!form.name || !form.name.trim())) {
      setError('Name is required for new devices.');
      return;
    }
    if (!isExternal || isCreate) {
      if (form.data_source_mode === 'other') {
        if (!(form.custom_external_api_name || '').trim()) {
          setError('Data Source is required for manual devices.');
          return;
        }
      } else if (toNumberOrUndefined(form.external_api_id) === undefined) {
        setError('Data Source is required for manual devices.');
        return;
      }
    }

    
    const { created_at: _createdAt, is_external: _isExt, external_api_name: _apiName, ...rest } = form;

    
    const payload: DevicePayload = {
      friendly_name: form.friendly_name,
      allow_updates: form.allow_updates,
    };

    
    if (!isExternal || isCreate) {
      payload.name = rest.name;
      payload.external_id = rest.external_id;
      payload.latitude = toNumberOrUndefined(form.latitude);
      payload.longitude = toNumberOrUndefined(form.longitude);
      payload.timezone = form.timezone;
      if (form.data_source_mode === 'other') {
        payload.network = (form.custom_external_api_name || '').trim();
      } else {
        payload.external_api_id = toNumberOrUndefined(form.external_api_id);
      }
    }

    setSaving(true);
    try {
      let saved: DeviceRecord;
      if (isCreate) {
        saved = await createDeviceAdmin(payload);
        navigate(`/admin/devices/${saved.device_id}/edit`, { replace: true });
      } else {
        saved = await updateDeviceAdmin(deviceId!, payload);
      }
      const fs = toFormState(saved);
      setInitial(fs);
      setForm(fs);
      setSuccess('Device saved successfully.');
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to save device';
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deviceId) return;
    if (!window.confirm('Delete this device? This cannot be undone.')) return;
    try {
      await deleteDeviceAdmin(deviceId);
      navigate('/admin/devices');
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to delete device';
      setError(message);
    }
  };

  
  const displayName = form.friendly_name?.trim() || form.name || `Device ${deviceId}`;

  return (
    <AdminPageLayout
      title={isCreate ? 'New Device' : 'Device Details'}
      hidePageHeader
      contentClassName="device-editor-page"
    >
      <div>
        
        <div className="admin-page-header sticky">
          <div>
            <div className="breadcrumbs">
              <Link to="/admin" onClick={guardNav}>Admin</Link>
              <span aria-hidden="true">/</span>
              <Link to="/admin/devices" onClick={guardNav}>Devices</Link>
              <span aria-hidden="true">/</span>
              <span>{isCreate ? 'New Device' : displayName}</span>
            </div>
            <h1>{isCreate ? 'New Device' : 'Device Details'}</h1>
            {isDirty && <div className="warning-banner">Unsaved changes</div>}
          </div>
        </div>

        
        {error && <div className="error-banner">{error}</div>}
        {success && <div className="success-banner">{success}</div>}
        {loading && <div className="info-banner">Loading device…</div>}

        
        {!isCreate && isExternal && (
          <div className="info-banner">
            <strong>External Device</strong> — This device is synced from {form.external_api_name || 'an external API'}.
            Most fields are read-only. You can edit the Friendly Name and local settings.
          </div>
        )}

        <div className="device-editor-layout">
          
          <form className="device-form" onSubmit={(e) => { e.preventDefault(); void handleSave(); }}>
            
            <div className="card form-section">
              <h3>Source Identity</h3>
              {isExternal && (
                <div className="section-hint">
                  <span className="hint-icon">🔒</span>
                  These fields are managed by the external data source and cannot be edited.
                </div>
              )}
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="name">Name {!isExternal && !isCreate && <span className="required-star">*</span>}</label>
                  {isExternal ? (
                    <div className="readonly-value">{form.name || '—'}</div>
                  ) : (
                    <input
                      id="name"
                      className="text-input"
                      value={form.name || ''}
                      onChange={(e) => handleChange('name', e.target.value)}
                      required={!isExternal}
                    />
                  )}
                </div>
                  <div className="field">
                    <label htmlFor="friendly_name">Friendly Name</label>
                    <input
                      id="friendly_name"
                      className="text-input"
                      value={form.friendly_name || ''}
                      onChange={(e) => handleChange('friendly_name', e.target.value)}
                      placeholder="Enter a custom display name"
                    />
                    <small className="muted">Your preferred name for this device. Shown in lists and charts.</small>
                  </div>
                <div className="field">
                  <label htmlFor="external_id">External ID</label>
                  {isExternal ? (
                    <div className="readonly-value mono">{form.external_id || '—'}</div>
                  ) : (
                    <input
                      id="external_id"
                      className="text-input"
                      value={form.external_id || ''}
                      onChange={(e) => handleChange('external_id', e.target.value)}
                      placeholder="e.g., 12345"
                    />
                  )}
                </div>
                <div className="field">
                  <label htmlFor="external_api_id">Data Source <span className="required-star">*</span></label>
                  {isExternal ? (
                    <div className="readonly-value">
                      {form.external_api_name || 'Unknown'}
                      {isExternal && <span className="badge badge-external">External</span>}
                    </div>
                  ) : (
                    <>
                      <select
                        id="external_api_id"
                        className="select-input"
                        value={selectedDataSourceValue}
                        onChange={(e) => handleDataSourceSelection(e.target.value)}
                        disabled={dataSourcesLoading}
                      >
                        <option value="">{dataSourcesLoading ? 'Loading data sources…' : 'Select data source'}</option>
                        {availableDataSources.map((source) => (
                          <option key={source.external_api_id} value={source.external_api_id}>
                            {source.name}
                          </option>
                        ))}
                        <option value={OTHER_DATA_SOURCE_VALUE}>Other</option>
                      </select>
                      {form.data_source_mode === 'other' && (
                        <div style={{ marginTop: '0.75rem' }}>
                          <label htmlFor="custom_external_api_name">Other Data Source Name <span className="required-star">*</span></label>
                          <input
                            id="custom_external_api_name"
                            className="text-input"
                            value={form.custom_external_api_name || ''}
                            onChange={(e) => handleChange('custom_external_api_name', e.target.value)}
                            placeholder="Enter data source name"
                          />
                        </div>
                      )}
                      <small className="muted">Choose which data source this device's data comes from.</small>
                      {dataSourcesError && <small className="muted" style={{ color: 'var(--danger-700, #b42318)' }}>{dataSourcesError}</small>}
                    </>
                  )}
                </div>
              </div>
            </div>

            
            <div className="card form-section">
              <h3>Location</h3>
              {isExternal && (
                <div className="section-hint">
                  <span className="hint-icon">🔒</span>
                  Location data is synced from the external source.
                </div>
              )}
              <div className="form-grid form-grid-3col">
                <div className="field">
                  <label htmlFor="latitude">Latitude</label>
                  {isExternal ? (
                    <div className="readonly-value">{form.latitude ?? '—'}</div>
                  ) : (
                    <input
                      id="latitude"
                      className="text-input"
                      value={form.latitude ?? ''}
                      onChange={(e) => handleChange('latitude', e.target.value)}
                      placeholder="e.g., 35.1234"
                    />
                  )}
                </div>
                <div className="field">
                  <label htmlFor="longitude">Longitude</label>
                  {isExternal ? (
                    <div className="readonly-value">{form.longitude ?? '—'}</div>
                  ) : (
                    <input
                      id="longitude"
                      className="text-input"
                      value={form.longitude ?? ''}
                      onChange={(e) => handleChange('longitude', e.target.value)}
                      placeholder="e.g., -120.1234"
                    />
                  )}
                </div>
                <div className="field">
                  <label htmlFor="timezone">Timezone</label>
                  {isExternal ? (
                    <div className="readonly-value">{form.timezone || '—'}</div>
                  ) : (
                    <input
                      id="timezone"
                      className="text-input"
                      value={form.timezone || ''}
                      onChange={(e) => handleChange('timezone', e.target.value)}
                      placeholder="America/Los_Angeles"
                    />
                  )}
                </div>
              </div>
            </div>

            
            <div className="card form-section">
              <h3>Local Settings</h3>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="allow_updates">Measurement Updates Policy</label>
                  <select
                    id="allow_updates"
                    className="select-input"
                    value={form.allow_updates || 'inherit'}
                    onChange={(e) => handleChange('allow_updates', e.target.value)}
                  >
                    <option value="inherit">Inherit (from system default)</option>
                    <option value="allow">Allow updates to existing measurements</option>
                    <option value="deny">Deny updates (keep first value)</option>
                  </select>
                  <small className="muted">Controls whether incoming measurements can update existing records.</small>
                </div>
              </div>
            </div>

            
            {!isCreate && (
              <div className="card meta-card">
                <h3>System Metadata</h3>
                <div className="meta-grid">
                  <div className="meta-item">
                    <div className="meta-label">Device ID</div>
                    <div className="meta-value mono">{deviceId}</div>
                  </div>
                  <div className="meta-item">
                    <div className="meta-label">External API ID</div>
                    <div className="meta-value mono">{form.external_api_id ?? '—'}</div>
                  </div>
                  {initial.created_at && (
                    <div className="meta-item">
                      <div className="meta-label">Created</div>
                      <div className="meta-value">{new Date(initial.created_at).toLocaleString()}</div>
                    </div>
                  )}
                </div>
              </div>
            )}

            
            <div className="form-actions sticky">
              <div className="actions">
                {!isCreate && <button type="button" className="btn btn-danger" onClick={handleDelete}>Delete</button>}
                <button type="button" className="btn btn-secondary" onClick={handleCancel}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
              </div>
            </div>
          </form>

          
          <div className="device-sidebar">
            <div className="card">
              <h3>Sensors</h3>
              {!isCreate && (
                <div style={{ marginBottom: 12 }}>
                  <div className="field" style={{ marginBottom: 8 }}>
                    <label htmlFor="new_sensor_parameter_code">Parameter <span className="required-star">*</span></label>
                    <select
                      id="new_sensor_parameter_code"
                      className="select-input"
                      value={newSensorParameterCode}
                      onChange={(e) => setNewSensorParameterCode(e.target.value)}
                      disabled={addingSensor || parametersLoading || sortedParameters.length === 0}
                    >
                      <option value="">
                        {parametersLoading ? 'Loading parameters…' : 'Select parameter'}
                      </option>
                      {sortedParameters.map((parameter) => (
                        <option key={parameter.code} value={parameter.code}>
                          {parameter.display_name}
                        </option>
                      ))}
                    </select>
                    {parametersError && <small className="muted" style={{ color: 'var(--danger-700, #b42318)' }}>{parametersError}</small>}
                  </div>
                  <div className="field" style={{ marginBottom: 8 }}>
                    <label htmlFor="new_sensor_aggregation_code">Time Resolution <span className="required-star">*</span></label>
                    <select
                      id="new_sensor_aggregation_code"
                      className="select-input"
                      value={newSensorAggregationCode}
                      onChange={(e) => setNewSensorAggregationCode(e.target.value)}
                      disabled={addingSensor || aggregationPeriodsLoading || sortedAggregationPeriods.length === 0}
                    >
                      <option value="">
                        {aggregationPeriodsLoading ? 'Loading time resolutions…' : 'Select time resolution'}
                      </option>
                      {sortedAggregationPeriods.map((aggregationPeriod) => (
                        <option key={aggregationPeriod.code} value={aggregationPeriod.code}>
                          {aggregationPeriod.display_name}
                        </option>
                      ))}
                    </select>
                    {aggregationPeriodsError && <small className="muted" style={{ color: 'var(--danger-700, #b42318)' }}>{aggregationPeriodsError}</small>}
                  </div>
                  <div className="field" style={{ marginBottom: 8 }}>
                    <label htmlFor="new_sensor_external_id">External Sensor ID</label>
                    <input
                      id="new_sensor_external_id"
                      className="text-input"
                      value={newSensorExternalId}
                      onChange={(e) => setNewSensorExternalId(e.target.value)}
                      placeholder="e.g., provider-sensor-123"
                      disabled={addingSensor}
                    />
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleAddSensor}
                    disabled={addingSensor}
                  >
                    {addingSensor ? 'Adding…' : 'Add Sensor'}
                  </button>
                </div>
              )}
              {isCreate ? (
                <p className="muted">Save the device first to view its sensors.</p>
              ) : sensorsLoading ? (
                <div className="loading-indicator">Loading sensors…</div>
              ) : sensorsError ? (
                <div className="error-banner">{sensorsError}</div>
              ) : !sensors.length ? (
                <p className="muted">No sensors found for this device.</p>
              ) : (
                <div className="sensor-list-compact">
                  {sensors.map((s) => (
                    <div key={s.sensor_id} className="sensor-item">
                      <div className="sensor-item-header">
                        <span className="sensor-param">{s.parameter_name || s.parameter_code || 'Unknown'}</span>
                        {s.is_valid === false && <span className="qc-badge qc-invalid">Invalid</span>}
                        {s.is_valid === true && <span className="qc-badge qc-valid">Valid</span>}
                      </div>
                      {editingSensorId === s.sensor_id ? (
                        <div>
                          <div className="field" style={{ marginBottom: 8 }}>
                            <label htmlFor={`sensor-parameter-${s.sensor_id}`}>Parameter <span className="required-star">*</span></label>
                            <select
                              id={`sensor-parameter-${s.sensor_id}`}
                              className="select-input"
                              value={editingSensorParameterCode}
                              onChange={(e) => setEditingSensorParameterCode(e.target.value)}
                              disabled={savingSensor}
                            >
                              <option value="">Select parameter</option>
                              {sortedParameters.map((parameter) => (
                                <option key={parameter.code} value={parameter.code}>
                                  {parameter.display_name}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="field" style={{ marginBottom: 8 }}>
                            <label htmlFor={`sensor-aggregation-${s.sensor_id}`}>Time Resolution <span className="required-star">*</span></label>
                            <select
                              id={`sensor-aggregation-${s.sensor_id}`}
                              className="select-input"
                              value={editingSensorAggregationCode}
                              onChange={(e) => setEditingSensorAggregationCode(e.target.value)}
                              disabled={savingSensor || aggregationPeriodsLoading}
                            >
                              <option value="">Select time resolution</option>
                              {sortedAggregationPeriods.map((aggregationPeriod) => (
                                <option key={aggregationPeriod.code} value={aggregationPeriod.code}>
                                  {aggregationPeriod.display_name}
                                </option>
                              ))}
                            </select>
                            {aggregationPeriodsError && <small className="muted" style={{ color: 'var(--danger-700, #b42318)' }}>{aggregationPeriodsError}</small>}
                          </div>
                          <div className="field" style={{ marginBottom: 8 }}>
                            <label htmlFor={`sensor-external-id-${s.sensor_id}`}>External Sensor ID</label>
                            <input
                              id={`sensor-external-id-${s.sensor_id}`}
                              className="text-input"
                              value={editingSensorExternalId}
                              onChange={(e) => setEditingSensorExternalId(e.target.value)}
                              placeholder="e.g., provider-sensor-123"
                              disabled={savingSensor}
                            />
                          </div>
                          <div className="actions" style={{ marginTop: 8 }}>
                            <button
                              type="button"
                              className="btn btn-secondary"
                              onClick={cancelEditingSensor}
                              disabled={savingSensor}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="btn btn-primary"
                              onClick={() => void handleSaveSensor(s.sensor_id)}
                              disabled={savingSensor}
                            >
                              {savingSensor ? 'Saving…' : 'Save'}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="sensor-item-details">
                          <div className="sensor-value">
                            {s.value !== undefined && s.value !== null ? (
                              <><strong>{s.value}</strong> {s.unit_symbol || ''}</>
                            ) : '—'}
                          </div>
                          <div className="sensor-time-resolution muted small">
                            Time Resolution: {
                              s.aggregation_code
                                ? (aggregationPeriodDisplayByCode.get(s.aggregation_code.toLowerCase()) || s.aggregation_code)
                                : '—'
                            }
                          </div>
                          <div className="sensor-time muted small">
                            {s.observed_at ? new Date(s.observed_at).toLocaleString() : 'No data'}
                          </div>
                        </div>
                      )}
                      <div className="sensor-ext-id muted small">Internal Sensor ID: {s.sensor_id}</div>
                      <div className="sensor-ext-id muted small">External Sensor ID: {s.external_sensor_id || '—'}</div>
                      {!isExternal && (
                        <div className="actions sensor-item-actions" style={{ marginTop: 8 }}>
                          {editingSensorId !== s.sensor_id && (
                            <button
                              type="button"
                              className="btn btn-secondary sensor-item-action-btn"
                              onClick={() => startEditingSensor(s)}
                              disabled={deletingSensorId === s.sensor_id}
                            >
                              Edit
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn btn-danger sensor-item-action-btn"
                            onClick={() => void handleDeleteSensor(s.sensor_id)}
                            disabled={deletingSensorId === s.sensor_id || savingSensor}
                          >
                            {deletingSensorId === s.sensor_id ? 'Deleting…' : 'Delete'}
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </AdminPageLayout>
  );
}
