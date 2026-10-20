import { formatMeasurementValue } from './measurementFormatting';
import { formatOperationalTimestamp, getSelectableIanaTimezones } from './utils/timezone';
import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import AdminPageLayout from './components/AdminPageLayout';
import { ApiError } from './apiError';
import { validateDeviceCoordinates } from './deviceCoordinateValidation';
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
import {
  formatLatestReading,
  formatMeasurementSummary,
} from './sensorMetadataFormatting';

const OTHER_DATA_SOURCE_VALUE = '__other__';
type FieldErrors = Partial<Record<'name' | 'custom_external_api_name' | 'latitude' | 'longitude', string>>;

type FormState = Omit<DevicePayload, 'latitude' | 'longitude' | 'external_api_id'> & {
  latitude?: string | number | null;
  longitude?: string | number | null;
  external_api_id?: string | number | null;
  created_at?: string | null;
  status?: DeviceRecord['status'];
  last_seen_at?: string | null;
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
    status: record.status,
    last_seen_at: record.last_seen_at,
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

function toNumberOrUndefined(val: string | number | undefined | null): number | undefined {
  if (val === undefined || val === null || String(val).trim() === '') return undefined;
  const num = Number(val);
  return Number.isFinite(num) ? num : undefined;
}

function buildDevicePayload(form: FormState, isExternal: boolean, isCreate: boolean): DevicePayload {
  const payload: DevicePayload = {
    friendly_name: form.friendly_name,
    allow_updates: form.allow_updates,
  };

  if (!isExternal || isCreate) {
    payload.name = form.name;
    payload.external_id = form.external_id;
    payload.latitude = toNumberOrUndefined(form.latitude) ?? null;
    payload.longitude = toNumberOrUndefined(form.longitude) ?? null;
    payload.timezone = form.timezone;
    if (form.data_source_mode === 'other') {
      payload.network = (form.custom_external_api_name || '').trim();
    } else {
      payload.external_api_id = toNumberOrUndefined(form.external_api_id);
    }
  }

  return payload;
}

type CoordinateMessages = {
  latitudeRange: string;
  longitudeRange: string;
  coordinatePair: string;
  coordinateNumber: string;
};

function mapRejectedCoordinateFields(errorCode: string | null, messages: CoordinateMessages): FieldErrors {
  const locationErrors: FieldErrors = {};
  if (errorCode === 'latitude_out_of_range') locationErrors.latitude = messages.latitudeRange;
  if (errorCode === 'longitude_out_of_range') locationErrors.longitude = messages.longitudeRange;
  if (errorCode === 'incomplete_coordinate_pair') {
    locationErrors.latitude = locationErrors.longitude = messages.coordinatePair;
  }
  if (errorCode === 'non_numeric_coordinate' || errorCode === 'non_finite_coordinate') {
    locationErrors.latitude = locationErrors.longitude = messages.coordinateNumber;
  }
  return locationErrors;
}

export default function AdminDeviceEditor() {
  const params = useParams();
  const navigate = useNavigate();
  const deviceId = params.deviceId ? Number(params.deviceId) : null;
  const isCreate = !deviceId;
  const location = useLocation();

  const [form, setForm] = useState<FormState>(toFormState());
  const [initial, setInitial] = useState<FormState>(toFormState());
  const [loading, setLoading] = useState<boolean>(!isCreate);
  const [loadFailed, setLoadFailed] = useState(false);
  const savingRef = useRef(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [validationFocus, setValidationFocus] = useState<keyof FieldErrors | null>(null);
  const [feedbackScope, setFeedbackScope] = useState<'device' | 'sensor'>('device');
  const saveFeedbackRef = useRef<HTMLDivElement>(null);
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
    setLoadFailed(false);
    setError(null);
    (async () => {
      try {
        const rec = await getDeviceAdmin(deviceId);
        if (cancelled) return;
        const fs = toFormState(rec);
        setForm(fs);
        setInitial(fs);
      } catch {
        const message = i18n.t('common:errors.loadDevice');
        if (!cancelled) {
          setError(message);
          setLoadFailed(true);
        }
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
      } catch {
        const message = i18n.t('common:errors.loadParameters');
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
      } catch {
        const message = i18n.t('common:errors.loadTimeResolutions');
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
      } catch {
        const message = i18n.t('common:errors.loadDataSources');
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
      if (source.enabled) return true;
      return !isCreate && Number(form.external_api_id) === source.external_api_id;
    });
  }, [sortedDataSources, isCreate, form.external_api_id]);

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
    } catch {
      const message = i18n.t('common:errors.loadSensors');
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
    setFeedbackScope('sensor');
    if (!deviceId) return;
    const parameterCode = (newSensorParameterCode || '').trim().toLowerCase();
    const aggregationCode = (newSensorAggregationCode || '').trim().toLowerCase();
    if (!parameterCode) {
      setError(i18n.t('devices:adminDeviceEditor.messages.parameterRequiredAddSensor'));
      return;
    }
    if (!aggregationCode) {
      setError(i18n.t('devices:adminDeviceEditor.messages.timeResolutionRequiredAddSensor'));
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
      setSuccess(i18n.t('devices:adminDeviceEditor.messages.sensorAdded', { id: created.sensor_id }));
      setNewSensorAggregationCode('');
      setNewSensorExternalId('');
      await loadSensors(deviceId);
    } catch {
      const message = i18n.t('common:errors.addSensor');
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
    setFeedbackScope('sensor');
    if (!deviceId) return;
    const parameterCode = editingSensorParameterCode.trim().toLowerCase();
    const aggregationCode = editingSensorAggregationCode.trim().toLowerCase();
    if (!parameterCode) {
      setError(i18n.t('devices:adminDeviceEditor.messages.parameterRequiredUpdateSensor'));
      return;
    }
    if (!aggregationCode) {
      setError(i18n.t('devices:adminDeviceEditor.messages.timeResolutionRequiredUpdateSensor'));
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
      setSuccess(i18n.t('devices:adminDeviceEditor.messages.sensorUpdated', { id: sensorId }));
      cancelEditingSensor();
    } catch {
      const message = i18n.t('common:errors.updateSensor');
      setError(message);
    } finally {
      setSavingSensor(false);
    }
  };

  const handleDeleteSensor = async (sensorId: number) => {
    setFeedbackScope('sensor');
    if (!deviceId) return;
    if (!window.confirm(i18n.t('devices:adminDeviceEditor.dialogs.deleteSensorWillAlsoDeleteIts'))) return;
    setDeletingSensorId(sensorId);
    setError(null);
    setSuccess(null);
    try {
      await deleteDeviceSensorAdmin(deviceId, sensorId);
      await loadSensors(deviceId);
      setSuccess(i18n.t('devices:adminDeviceEditor.messages.sensorDeleted', { id: sensorId }));
      if (editingSensorId === sensorId) {
        cancelEditingSensor();
      }
    } catch {
      const message = i18n.t('common:errors.deleteSensor');
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
    setSuccess(null);
    setForm((prev) => ({ ...prev, [key]: value }));
    setFieldErrors((prev) => ({ ...prev, [key]: undefined }));
  };

  const coordinateErrors = (): FieldErrors => {
    const errors = validateDeviceCoordinates(form.latitude, form.longitude);
    return Object.fromEntries(Object.entries(errors).map(([field, message]) =>
      [field, i18n.t(`devices:adminDeviceEditor.validation.${message}`)]));
  };

  const validateCoordinatesOnBlur = (event: React.FocusEvent<HTMLInputElement>) => {
    // Inserting an error can move the action row before a pointer click finishes.
    // Save validates on submit; keep Save/Cancel/Delete in place during their click.
    if (event.relatedTarget instanceof Element && event.relatedTarget.closest('.admin-form-save-actions')) return;
    setFieldErrors(prev => ({ ...prev, latitude: undefined, longitude: undefined, ...coordinateErrors() }));
  };

  useEffect(() => {
    // Wait until failed-save controls are enabled and their error descriptions are rendered.
    if (saving || !validationFocus) return;
    document.getElementById(validationFocus)?.focus();
    setValidationFocus(null);
  }, [validationFocus, saving]);

  const selectedDataSourceValue = useMemo(() => {
    if (form.data_source_mode === 'other') return OTHER_DATA_SOURCE_VALUE;
    const selectedId = toNumberOrUndefined(form.external_api_id);
    return selectedId === undefined ? '' : String(selectedId);
  }, [form.data_source_mode, form.external_api_id]);

  const handleDataSourceSelection = (value: string) => {
    setFieldErrors(prev => ({ ...prev, custom_external_api_name: undefined }));
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
    if (isDirty && !window.confirm(i18n.t('devices:adminDeviceEditor.dialogs.youHaveUnsavedChangesLeaveWithout'))) {
      e.preventDefault();
    }
  };

  const handleCancel = () => {
    if (savingRef.current) return;
    if (isDirty && !window.confirm(i18n.t('devices:adminDeviceEditor.dialogs.discardChanges'))) return;
    navigate('/admin/devices');
  };

  const handleSave = async () => {
    if (savingRef.current || loading || loadFailed) return;
    setFeedbackScope('device');
    setError(null);
    setSuccess(null);

    const validationErrors: FieldErrors = {};
    if (!isExternal || isCreate) {
      if (!form.name?.trim()) validationErrors.name = i18n.t('devices:adminDeviceEditor.validation.nameRequired');
      if (form.data_source_mode === 'other' && !form.custom_external_api_name?.trim()) {
        validationErrors.custom_external_api_name = i18n.t('devices:adminDeviceEditor.validation.otherSourceRequired');
      }
      Object.assign(validationErrors, coordinateErrors());
    }
    setFieldErrors(validationErrors);
    if (Object.keys(validationErrors).length) {
      setValidationFocus(Object.keys(validationErrors)[0] as keyof FieldErrors);
      return;
    }


    const payload = buildDevicePayload(form, isExternal, isCreate);

    savingRef.current = true;
    setSaving(true);
    let rejectedFields: FieldErrors | null = null;
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
      setSuccess(i18n.t('devices:adminDeviceEditor.messages.deviceSavedSuccessfully'));
    } catch (cause) {
      // Preserve the backend's authority if it rejects a location after client validation.
      const locationErrors = mapRejectedCoordinateFields(
        cause instanceof ApiError ? cause.errorCode : null,
        {
          latitudeRange: i18n.t('devices:adminDeviceEditor.validation.latitudeRange'),
          longitudeRange: i18n.t('devices:adminDeviceEditor.validation.longitudeRange'),
          coordinatePair: i18n.t('devices:adminDeviceEditor.validation.coordinatePair'),
          coordinateNumber: i18n.t('devices:adminDeviceEditor.validation.coordinateNumber'),
        },
      );
      if (Object.keys(locationErrors).length) {
        setFieldErrors(locationErrors);
        rejectedFields = locationErrors;
        setValidationFocus(Object.keys(locationErrors)[0] as keyof FieldErrors);
        return;
      }
      const message = i18n.t('common:errors.saveDevice');
      setError(message);
    } finally {
      savingRef.current = false;
      setSaving(false);
      if (!rejectedFields) requestAnimationFrame(() => saveFeedbackRef.current?.focus({ preventScroll: true }));
    }
  };

  const handleDelete = async () => {
    setFeedbackScope('device');
    if (!deviceId) return;
    if (!window.confirm(i18n.t('devices:adminDeviceEditor.dialogs.deleteDeviceCannotUndone'))) return;
    try {
      await deleteDeviceAdmin(deviceId);
      navigate('/admin/devices');
    } catch {
      const message = i18n.t('common:errors.deleteDevice');
      setError(message);
    }
  };


  const displayName = initial.friendly_name?.trim() || initial.name || i18n.t('devices:adminDeviceEditor.dynamic.device', { id: deviceId });

  return (
    <AdminPageLayout
      title={isCreate ? i18n.t('devices:adminDeviceEditor.text.newDevice') : i18n.t('devices:adminDeviceEditor.text.deviceDetails')}
      hidePageHeader
      contentClassName="admin-workspace device-editor-page"
    >
      <div>

        <div className="admin-page-header sticky">
          <div>
            <div className="breadcrumbs">
              <Link to="/admin" onClick={guardNav}><Trans ns="devices" i18nKey="adminDeviceEditor.actions.admin" /></Link>
              <span aria-hidden="true">/</span>
              <Link to="/admin/devices" onClick={guardNav}><Trans ns="devices" i18nKey="adminDeviceEditor.actions.devices" /></Link>
              <span aria-hidden="true">/</span>
              <span>{isCreate ? i18n.t('devices:adminDeviceEditor.text.newDevice2') : displayName}</span>
            </div>
            <h1>{isCreate ? i18n.t('devices:adminDeviceEditor.headings.newDevice') : displayName}</h1>

          </div>
        </div>


        {error && loadFailed && <div className="error-banner" role="alert">{error}</div>}
        {location.state?.airgradientNoReadings === true && <div className="info-banner" role="status">
          <Trans ns="devices" i18nKey="airgradient.noReadings" />
        </div>}
        {loading && <div className="info-banner"><Trans ns="devices" i18nKey="adminDeviceEditor.text.loadingDevice" /></div>}


        {!isCreate && !loading && !loadFailed && (
          <div className="device-overview">
            <span className="status-badge">{i18n.t(isExternal ? 'devices:adminDeviceEditor.workflow.providerDevice' : 'devices:adminDeviceEditor.workflow.manualDevice')}</span>
            <span>{initial.custom_external_api_name || initial.external_api_name}</span>
            <span className={`status-badge ${initial.status === 'active' ? 'active' : 'disabled'}`}>
              {i18n.t(`devices:adminDevicesList.options.${initial.status ?? 'unknown'}`)}
            </span>
            <span>{i18n.t('devices:adminDevicesList.actions.lastSeen')}: {initial.last_seen_at ? formatOperationalTimestamp(initial.last_seen_at) : '—'}</span>
            <a href="#device-sensors">{i18n.t('devices:adminDeviceEditor.headings.sensors')}</a>
          </div>
        )}
        {!loading && !loadFailed && <div className="device-editor-layout">

          <form id="device-settings" noValidate aria-label={i18n.t("devices:adminDeviceEditor.headings.localSettings")} className="device-form" aria-busy={saving} onSubmit={(e) => { e.preventDefault(); void handleSave(); }}>

            <fieldset className="device-edit-fields" disabled={saving}>
            <legend className="sr-only">{i18n.t("devices:adminDeviceEditor.headings.localSettings")}</legend>
            {!isExternal && <>
              <p>{isCreate && <strong>{i18n.t('devices:adminDeviceEditor.workflow.manualDevice')}. </strong>}{i18n.t("devices:adminDeviceEditor.workflow.manualHelp")}</p>
              <p>{i18n.t("devices:adminDeviceEditor.clarity.requiredHelp")}</p>
              <div className="card form-section">
                <h2><Trans ns="devices" i18nKey="adminDeviceEditor.headings.sourceIdentity" /></h2>
                <div className="form-grid">
                  <div className="field">
                    <label htmlFor="name"><Trans ns="common" i18nKey="fields.name" />{' '}<span className="required-star">*</span></label>
                    <input
                      id="name"
                      className="text-input"
                      value={form.name || ''}
                      onChange={(e) => handleChange('name', e.target.value)}
                      required
                      aria-invalid={!!fieldErrors.name}
                      aria-describedby={fieldErrors.name ? 'name-error' : undefined}
                    />
                    {fieldErrors.name && <small id="name-error" className="field-error" role="alert">{fieldErrors.name}</small>}
                  </div>
                  <div className="field">
                    <label htmlFor="friendly_name"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.friendlyName" /></label>
                    <input
                      id="friendly_name"
                      className="text-input"
                      value={form.friendly_name || ''}
                      onChange={(e) => handleChange('friendly_name', e.target.value)}
                      placeholder={i18n.t('devices:adminDeviceEditor.placeholders.enterCustomDisplayName')}
                    />
                    <small className="muted"><Trans ns="devices" i18nKey="adminDeviceEditor.text.preferredNameDeviceShownListsCharts" /></small>
                  </div>
                  <div className="field">
                    <label htmlFor="external_id"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.externalId" /></label>
                    <input
                      id="external_id"
                      className="text-input"
                      value={form.external_id || ''}
                      onChange={(e) => handleChange('external_id', e.target.value)}
                      placeholder="e.g., 12345"
                      readOnly={!isCreate}
                      aria-describedby={isCreate ? 'device-external-id-help' : undefined}
                    />
                    {isCreate && <small id="device-external-id-help" className="muted">{i18n.t('devices:adminDeviceEditor.workflow.externalIdHelp')}</small>}
                  </div>
                  <div className="field">
                    <label htmlFor="external_api_id"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.dataSource" /></label>
                    <select
                      id="external_api_id"
                      className="select-input"
                      value={selectedDataSourceValue}
                      onChange={(e) => handleDataSourceSelection(e.target.value)}
                      disabled={dataSourcesLoading}
                      aria-describedby="device-source-help"
                    >
                      <option value="">{dataSourcesLoading ? i18n.t('devices:adminDeviceEditor.options.loadingDataSources') : i18n.t(isCreate ? 'devices:adminDeviceEditor.clarity.automaticSource' : 'devices:adminDeviceEditor.clarity.keepSource')}</option>
                      {availableDataSources.map((source) => (
                        <option key={source.external_api_id} value={source.external_api_id}>
                          {source.name}
                        </option>
                      ))}
                      <option value={OTHER_DATA_SOURCE_VALUE}><Trans ns="devices" i18nKey="adminDeviceEditor.options.other" /></option>
                    </select>
                    {form.data_source_mode === 'other' && (
                      <div style={{ marginTop: '0.75rem' }}>
                        <label htmlFor="custom_external_api_name"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.otherDataSourceName" />{' '}<span className="required-star">*</span></label>
                        <input
                          id="custom_external_api_name"
                          required
                          className="text-input"
                          value={form.custom_external_api_name || ''}
                          onChange={(e) => handleChange('custom_external_api_name', e.target.value)}
                          placeholder={i18n.t('devices:adminDeviceEditor.placeholders.enterDataSourceName')}
                          aria-invalid={!!fieldErrors.custom_external_api_name}
                          aria-describedby={`device-source-help${fieldErrors.custom_external_api_name ? ' custom-source-error' : ''}`}
                        />
                        {fieldErrors.custom_external_api_name && <small id="custom-source-error" className="field-error" role="alert">{fieldErrors.custom_external_api_name}</small>}
                      </div>
                    )}
                    <small className="muted" id="device-source-help">{i18n.t(form.data_source_mode === 'other' ? 'devices:adminDeviceEditor.clarity.otherSourceHelp' : isCreate ? 'devices:adminDeviceEditor.clarity.sourceHelp' : 'devices:adminDeviceEditor.clarity.keepSourceHelp')}</small>
                    {dataSourcesError && <small className="muted" style={{ color: 'var(--danger-700, #b42318)' }}>{dataSourcesError}</small>}
                  </div>
                </div>
              </div>


              <div className="card form-section">
                <h2><Trans ns="devices" i18nKey="adminDeviceEditor.headings.location" /></h2>
                <p id="device-location-help" className="section-hint">{i18n.t('devices:adminDeviceEditor.validation.locationHelp')}</p>
                <div className="form-grid form-grid-3col">
                  <div className="field">
                    <label htmlFor="latitude"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.latitude" /></label>
                    <input
                      id="latitude"
                      className="text-input"
                      value={form.latitude ?? ''}
                      onChange={(e) => handleChange('latitude', e.target.value)}
                      placeholder="e.g., 35.1234"
                      inputMode="decimal"
                      onBlur={validateCoordinatesOnBlur}
                      aria-invalid={!!fieldErrors.latitude}
                      aria-describedby={`device-location-help${fieldErrors.latitude ? ' latitude-error' : ''}`}
                    />
                    {fieldErrors.latitude && <small id="latitude-error" className="field-error" role="alert">{fieldErrors.latitude}</small>}
                  </div>
                  <div className="field">
                    <label htmlFor="longitude"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.longitude" /></label>
                    <input
                      id="longitude"
                      className="text-input"
                      value={form.longitude ?? ''}
                      onChange={(e) => handleChange('longitude', e.target.value)}
                      placeholder="e.g., -120.1234"
                      inputMode="decimal"
                      onBlur={validateCoordinatesOnBlur}
                      aria-invalid={!!fieldErrors.longitude}
                      aria-describedby={`device-location-help${fieldErrors.longitude ? ' longitude-error' : ''}`}
                    />
                    {fieldErrors.longitude && <small id="longitude-error" className="field-error" role="alert">{fieldErrors.longitude}</small>}
                  </div>
                  <div className="field">
                    <label htmlFor="timezone"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.timezone" /></label>
                    <select id="timezone" className="select-input" value={form.timezone || ''} onChange={(e) => handleChange('timezone', e.target.value)}>
                      <option value="">{i18n.t('devices:adminDeviceEditor.clarity.timezoneUnset')}</option>
                      {getSelectableIanaTimezones(initial.timezone || '').map(timezone => <option key={timezone}>{timezone}</option>)}
                    </select>
                  </div>
                </div>
              </div>


            </>}
            <div className="card form-section">
              <h2><Trans ns="devices" i18nKey="adminDeviceEditor.headings.localSettings" /></h2>
              {isExternal && <p className="muted">{i18n.t("devices:adminDeviceEditor.workflow.localHelp")}</p>}
              <div className="form-grid">
                {isExternal && (
                  <div className="field">
                    <label htmlFor="friendly_name"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.friendlyName" /></label>
                    <input
                      id="friendly_name"
                      className="text-input"
                      value={form.friendly_name || ''}
                      onChange={(e) => handleChange('friendly_name', e.target.value)}
                      placeholder={i18n.t('devices:adminDeviceEditor.placeholders.enterCustomDisplayName')}
                    />
                    <small className="muted"><Trans ns="devices" i18nKey="adminDeviceEditor.text.preferredNameDeviceShownListsCharts" /></small>
                  </div>
                )}
                <div className="field">
                  <label htmlFor="allow_updates"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.measurementUpdatesPolicy" /></label>
                  <select
                    id="allow_updates"
                    aria-describedby="device-policy-help device-inherit-help"
                    className="select-input"
                    value={form.allow_updates || 'inherit'}
                    onChange={(e) => handleChange('allow_updates', e.target.value)}
                  >
                    <option value="inherit"><Trans ns="devices" i18nKey="adminDeviceEditor.clarity.inherit" /></option>
                    <option value="allow"><Trans ns="devices" i18nKey="adminDeviceEditor.clarity.replace" /></option>
                    <option value="deny"><Trans ns="devices" i18nKey="adminDeviceEditor.clarity.keep" /></option>
                  </select>
                  <small className="muted" id="device-policy-help"><Trans ns="devices" i18nKey="adminDeviceEditor.text.controlsWhetherIncomingMeasurementsCanUpdate" /></small>
                  <p id="device-inherit-help">{form.allow_updates === "inherit" && i18n.t("devices:adminDeviceEditor.clarity.inheritUnavailable")}</p>
                </div>
              </div>
            </div>


            </fieldset>
            <div ref={saveFeedbackRef} tabIndex={-1} className="device-save-feedback">
              {isDirty && <p role="status">{i18n.t('devices:adminDeviceEditor.text.unsavedChanges')}</p>}
              {feedbackScope === 'device' && error && <div className="error-banner" role="alert">{error}</div>}
              {feedbackScope === 'device' && success && <div className="success-banner" role="status">{success}</div>}
            </div>
            <div className="form-actions admin-form-save-actions">
              {!isCreate && <button type="button" className="btn btn-danger admin-form-destructive" disabled={saving} onClick={handleDelete}><Trans ns="common" i18nKey="actions.delete" /></button>}
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={handleCancel}><Trans ns="common" i18nKey="actions.cancel" /></button>
              <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? i18n.t('common:actions.savingChanges') : isCreate ? i18n.t('devices:adminDeviceEditor.clarity.addDevice') : i18n.t('common:actions.saveChanges')}</button>
            </div>
          </form>


          <div className="device-sidebar" id="device-sensors">
            <div className="card">
              <h2><Trans ns="devices" i18nKey="adminDeviceEditor.headings.sensors" /></h2>
              <p className="section-hint">{i18n.t('devices:adminDeviceEditor.workflow.sensorHelp')}</p>
              {feedbackScope === 'sensor' && error && <div className="error-banner" role="alert">{error}</div>}
              {feedbackScope === 'sensor' && success && <div className="success-banner" role="status">{success}</div>}
              {!isCreate && isExternal && <p className="muted">{i18n.t('devices:adminDeviceEditor.workflow.providerSensors', { provider: initial.external_api_name || i18n.t('devices:adminDeviceEditor.fields.dataSource') })}</p>}
              {isCreate ? (
                <p className="muted"><Trans ns="devices" i18nKey="adminDeviceEditor.text.saveDeviceFirstViewItsSensors" /></p>
              ) : sensorsLoading ? (
                <div className="loading-indicator"><Trans ns="devices" i18nKey="adminDeviceEditor.text.loadingSensors" /></div>
              ) : sensorsError ? (
                <div className="error-banner" role="alert">{sensorsError}</div>
              ) : !sensors.length ? (
                <p className="muted"><Trans ns="devices" i18nKey="adminDeviceEditor.text.noSensorsFoundDevice" /></p>
              ) : (
                <div className="sensor-list-compact">
                  {sensors.map((s) => {
                    const measurementSummary = formatMeasurementSummary(
                      s.expected_frequency_seconds,
                      s.measurement_duration_seconds,
                    );
                    const latestReading = formatLatestReading(s.observed_at);

                    return (
                      <div key={s.sensor_id} className="sensor-item">
                      <div className="sensor-item-header">
                        <span className="sensor-param">{s.parameter_name || s.parameter_code || 'Unknown'}</span>
                        {s.is_valid === false && <span className="qc-badge qc-invalid"><Trans ns="devices" i18nKey="adminDeviceEditor.text.invalid" /></span>}
                        {s.is_valid === true && <span className="qc-badge qc-valid"><Trans ns="devices" i18nKey="adminDeviceEditor.text.valid" /></span>}
                        {s.is_valid == null && <span className="qc-badge qc-unknown"><Trans ns="devices" i18nKey="adminDeviceEditor.text.validityUnknown" /></span>}
                      </div>
                      {editingSensorId === s.sensor_id ? (
                        <div>
                          <div className="field" style={{ marginBottom: 8 }}>
                            <label htmlFor={`sensor-parameter-${s.sensor_id}`}><Trans ns="devices" i18nKey="adminDeviceEditor.fields.parameter2" />{' '}<span className="required-star">*</span></label>
                            <select
                              id={`sensor-parameter-${s.sensor_id}`}
                              className="select-input"
                              value={editingSensorParameterCode}
                              onChange={(e) => setEditingSensorParameterCode(e.target.value)}
                              disabled={savingSensor}
                            >
                              <option value=""><Trans ns="devices" i18nKey="adminDeviceEditor.options.selectParameter2" /></option>
                              {sortedParameters.map((parameter) => (
                                <option key={parameter.code} value={parameter.code}>
                                  {parameter.display_name}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="field" style={{ marginBottom: 8 }}>
                            <label htmlFor={`sensor-aggregation-${s.sensor_id}`}><Trans ns="devices" i18nKey="adminDeviceEditor.fields.timeResolution2" />{' '}<span className="required-star">*</span></label>
                            <select
                              id={`sensor-aggregation-${s.sensor_id}`}
                              className="select-input"
                              value={editingSensorAggregationCode}
                              onChange={(e) => setEditingSensorAggregationCode(e.target.value)}
                              disabled={savingSensor || aggregationPeriodsLoading}
                            >
                              <option value=""><Trans ns="devices" i18nKey="adminDeviceEditor.options.selectTimeResolution2" /></option>
                              {sortedAggregationPeriods.map((aggregationPeriod) => (
                                <option key={aggregationPeriod.code} value={aggregationPeriod.code}>
                                  {aggregationPeriod.display_name}
                                </option>
                              ))}
                            </select>
                            {aggregationPeriodsError && <small className="muted" style={{ color: 'var(--danger-700, #b42318)' }}>{aggregationPeriodsError}</small>}
                          </div>
                          <div className="field" style={{ marginBottom: 8 }}>
                            <label htmlFor={`sensor-external-id-${s.sensor_id}`}><Trans ns="devices" i18nKey="adminDeviceEditor.fields.externalSensorId2" /></label>
                            <input
                              id={`sensor-external-id-${s.sensor_id}`}
                              className="text-input"
                              value={editingSensorExternalId}
                              onChange={(e) => setEditingSensorExternalId(e.target.value)}
                              placeholder={i18n.t('devices:adminDeviceEditor.placeholders.eGProviderSensor1232')}
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
                              <Trans ns="common" i18nKey="actions.cancel" /></button>
                            <button
                              type="button"
                              className="btn btn-primary"
                              onClick={() => void handleSaveSensor(s.sensor_id)}
                              disabled={savingSensor}
                            >
                              {savingSensor ? i18n.t('devices:adminDeviceEditor.actions.saving2') : i18n.t('common:actions.save')}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="sensor-item-details">
                          <div className="sensor-value">
                            {s.value !== undefined && s.value !== null ? (
                              <><strong>{formatMeasurementValue(s.value, s.display_precision)}</strong> {s.unit_symbol || ''}</>
                            ) : '—'}
                          </div>
                          {measurementSummary && (
                            <p className="sensor-measurement-summary">
                              {measurementSummary}
                            </p>
                          )}
                          <div className="sensor-latest-reading">
                            <span className="sensor-detail-label"><Trans ns="devices" i18nKey="adminDeviceEditor.text.latestReading" /></span>
                            {latestReading && s.observed_at ? (
                              <time dateTime={s.observed_at}>{latestReading}</time>
                            ) : (
                              <span><Trans ns="devices" i18nKey="adminDeviceEditor.text.noData" /></span>
                            )}
                          </div>
                        </div>
                      )}
                      <div className="sensor-identifiers">
                        {s.acquisition_metadata?.acquisition_method === 'map_processed_history' && (
                          <p className="muted">{i18n.t('dataSources:airgradientHistoryStream')}</p>
                        )}
                        <div><Trans ns="devices" i18nKey="adminDeviceEditor.text.internalSensorId" />{' '}{s.sensor_id}</div>
                        <div><Trans ns="devices" i18nKey="adminDeviceEditor.text.externalSensorId" />{' '}{s.external_sensor_id || '—'}</div>
                      </div>
                      {editingSensorId !== s.sensor_id && (
                        <div className="actions sensor-item-actions" style={{ marginTop: 8 }}>
                          <Link
                            className="btn btn-secondary sensor-item-qc-link"
                            to={`/admin/qc/sensors/${s.sensor_id}`}
                            onClick={guardNav}
                          >
                            <Trans ns="devices" i18nKey="adminDeviceEditor.actions.manageQc" />
                          </Link>
                          {!isExternal && (
                            <>
                              <button
                                type="button"
                                className="btn btn-secondary sensor-item-action-btn"
                                onClick={() => startEditingSensor(s)}
                                disabled={deletingSensorId === s.sensor_id}
                              >
                                <Trans ns="common" i18nKey="actions.edit" />
                              </button>
                              <button
                                type="button"
                                className="btn btn-danger sensor-item-action-btn"
                                onClick={() => void handleDeleteSensor(s.sensor_id)}
                                disabled={deletingSensorId === s.sensor_id || savingSensor}
                              >
                                {deletingSensorId === s.sensor_id ? i18n.t('devices:adminDeviceEditor.actions.deleting') : i18n.t('common:actions.delete')}
                              </button>
                            </>
                          )}
                        </div>
                      )}
                      </div>
                    );
                  })}
                </div>
              )}
              {!isCreate && !isExternal && (
                <div className="device-add-sensor">
                  <h3><Trans ns="devices" i18nKey="adminDeviceEditor.actions.addSensor" /></h3>
                  <p className="muted"><Trans ns="devices" i18nKey="adminDeviceEditor.workflow.sensorQcInheritance" /></p>
                  <div className="field" style={{ marginBottom: 8 }}>
                    <label htmlFor="new_sensor_parameter_code"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.parameter" />{' '}<span className="required-star">*</span></label>
                    <select
                      id="new_sensor_parameter_code"
                      className="select-input"
                      value={newSensorParameterCode}
                      onChange={(e) => setNewSensorParameterCode(e.target.value)}
                      disabled={addingSensor || parametersLoading || sortedParameters.length === 0}
                    >
                      <option value="">
                        {parametersLoading ? i18n.t('devices:adminDeviceEditor.options.loadingParameters') : i18n.t('devices:adminDeviceEditor.options.selectParameter')}
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
                    <label htmlFor="new_sensor_aggregation_code"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.timeResolution" />{' '}<span className="required-star">*</span></label>
                    <select
                      id="new_sensor_aggregation_code"
                      className="select-input"
                      value={newSensorAggregationCode}
                      onChange={(e) => setNewSensorAggregationCode(e.target.value)}
                      disabled={addingSensor || aggregationPeriodsLoading || sortedAggregationPeriods.length === 0}
                    >
                      <option value="">
                        {aggregationPeriodsLoading ? i18n.t('devices:adminDeviceEditor.options.loadingTimeResolutions') : i18n.t('devices:adminDeviceEditor.options.selectTimeResolution')}
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
                    <label htmlFor="new_sensor_external_id"><Trans ns="devices" i18nKey="adminDeviceEditor.fields.externalSensorId" /></label>
                    <input
                      id="new_sensor_external_id"
                      className="text-input"
                      value={newSensorExternalId}
                      onChange={(e) => setNewSensorExternalId(e.target.value)}
                      placeholder={i18n.t('devices:adminDeviceEditor.placeholders.eGProviderSensor123')}
                      disabled={addingSensor}
                    />
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={handleAddSensor}
                    disabled={addingSensor}
                  >
                    {addingSensor ? i18n.t('devices:adminDeviceEditor.actions.adding') : i18n.t('devices:adminDeviceEditor.actions.addSensor')}
                  </button>
                </div>
              )}
            </div>
          </div>
          {!isCreate && isExternal && (
            <section className="card device-provider-details" aria-labelledby="provider-details-heading">
              <h2 id="provider-details-heading">{i18n.t('devices:adminDeviceEditor.workflow.providerDetails')}</h2>
              <p className="muted">{i18n.t('devices:adminDeviceEditor.workflow.managedBy', { provider: initial.external_api_name || i18n.t('devices:adminDeviceEditor.fields.dataSource') })}</p>
              <h3>{i18n.t('devices:adminDeviceEditor.workflow.providerIdentity')}</h3>
              <dl className="device-reference-grid">
                <div><dt>{i18n.t('common:fields.name')}</dt><dd>{initial.name || '—'}</dd></div>
                <div><dt>{i18n.t('devices:adminDeviceEditor.fields.externalId')}</dt><dd>{initial.external_id || '—'}</dd></div>
              </dl>
              <h3>{i18n.t('devices:adminDeviceEditor.workflow.providerLocation')}</h3>
              <dl className="device-reference-grid">
                <div><dt>{i18n.t('devices:adminDeviceEditor.fields.latitude')}</dt><dd>{initial.latitude ?? '—'}</dd></div>
                <div><dt>{i18n.t('devices:adminDeviceEditor.fields.longitude')}</dt><dd>{initial.longitude ?? '—'}</dd></div>
                <div><dt>{i18n.t('devices:adminDeviceEditor.fields.timezone')}</dt><dd>{initial.timezone || '—'}</dd></div>
              </dl>
            </section>
          )}
          {!isCreate && (
              <details className="card meta-card">
                <summary><Trans ns="devices" i18nKey="adminDeviceEditor.headings.systemMetadata" /></summary>
                <div className="meta-grid">
                  <div className="meta-item">
                    <div className="meta-label"><Trans ns="devices" i18nKey="adminDeviceEditor.text.deviceId" /></div>
                    <div className="meta-value mono">{deviceId}</div>
                  </div>
                  <div className="meta-item">
                    <div className="meta-label"><Trans ns="devices" i18nKey="adminDeviceEditor.text.externalApiId" /></div>
                    <div className="meta-value mono">{initial.external_api_id ?? '—'}</div>
                  </div>
                  {initial.created_at && (
                    <div className="meta-item">
                      <div className="meta-label"><Trans ns="devices" i18nKey="adminDeviceEditor.text.created" /></div>
                      <div className="meta-value">{formatOperationalTimestamp(initial.created_at)}</div>
                    </div>
                  )}
                </div>
              </details>
            )}
        </div>}
      </div>
    </AdminPageLayout>
  );
}
