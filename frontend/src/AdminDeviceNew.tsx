import { formatMeasurementValue } from './measurementFormatting';
import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  listExternalAPIs,
  lookupPurpleAirSensor,
  createPurpleAirDevice,
  type ExternalAPI,
  type PurpleAirLookupDevice,
  type PurpleAirLookupSensor,
} from './api';
import AdminPageLayout from './components/AdminPageLayout';
import AdminDialog from './admin/AdminDialog';

type DataSource = 'none' | 'purpleair' | 'openaq' | 'manual';

export default function AdminDeviceNew() {
  const navigate = useNavigate();

  
  const [dataSource, setDataSource] = useState<DataSource>('none');

  
  const [sources, setSources] = useState<ExternalAPI[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState(false);

  
  const [sensorIndex, setSensorIndex] = useState('');
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookupData, setLookupData] = useState<{
    device: PurpleAirLookupDevice;
    sensors: PurpleAirLookupSensor[];
  } | null>(null);

  
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  
  const [showConfirm, setShowConfirm] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await listExternalAPIs({ skipCache: true });
        if (!cancelled) setSources(list || []);
      } catch {
        if (!cancelled) setSourcesError(true);
      } finally {
        if (!cancelled) setSourcesLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const activeSources = sources.filter((s) => s.enabled);

  const hasPurpleAir = sources.some(
    (s) => s.enabled && s.provider_code === 'purpleair'
  );

  const hasOpenAQ = sources.some(
    (s) => s.enabled && s.provider_code === 'openaq'
  );
  const hasAirGradient = sources.some(
    (s) => s.provider_code === 'airgradient' && s.has_api_key
  );

  const handleSourceSelect = (source: DataSource) => {
    if (source === 'openaq') {
      navigate('/admin/devices/new/openaq');
      return;
    }
    setDataSource(source);
    setLookupData(null);
    setLookupError(null);
    setSensorIndex('');
  };

  const handleLookupClick = () => {
    if (!sensorIndex.trim()) {
      setLookupError(i18n.t('devices:adminDeviceNew.messages.pleaseEnterSensorIndex'));
      return;
    }
    
    setShowConfirm(true);
  };

  const handleConfirmLookup = async () => {
    setShowConfirm(false);
    setLookupLoading(true);
    setLookupError(null);
    setLookupData(null);

    try {
      const result = await lookupPurpleAirSensor(sensorIndex.trim(), true);
      setLookupData(result);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setLookupError(message);
    } finally {
      setLookupLoading(false);
    }
  };

  const handleSave = async () => {
    if (!lookupData) return;

    setSaving(true);
    setSaveError(null);

    try {
      const result = await createPurpleAirDevice(
        lookupData.device,
        lookupData.sensors
      );
      
      navigate(`/admin/devices/${result.device.device_id}/edit`);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setSaveError(message);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    navigate('/admin/devices');
  };

  
  const renderSourceSelection = () => (
    <div className="card">
      <h2><Trans ns="devices" i18nKey="adminDeviceNew.headings.selectDataSource" /></h2>
      <p className="muted" style={{ marginBottom: 16 }}>
        <Trans ns="devices" i18nKey="adminDeviceNew.text.chooseHowYouWantAddNew" /></p>
      <div className="source-options">
        {hasAirGradient && (
          <button type="button" className="source-option-card"
            onClick={() => navigate('/admin/devices/new/airgradient')}>
            <div className="source-option-content">
              <strong>AirGradient</strong>
              <span className="muted"><Trans ns="devices" i18nKey="airgradient.choose" /></span>
            </div>
          </button>
        )}
        {hasPurpleAir && (
          <button
            type="button"
            className={`source-option-card ${dataSource === 'purpleair' ? 'selected' : ''}`}
            onClick={() => handleSourceSelect('purpleair')}
          >
            <div className="source-option-content">
              <strong>PurpleAir</strong>
              <span className="muted"><Trans ns="devices" i18nKey="adminDeviceNew.text.importPurpleAirSensorIndex" /></span>
            </div>
          </button>
        )}
        {hasOpenAQ && (
          <button
            type="button"
            className={`source-option-card ${dataSource === 'openaq' ? 'selected' : ''}`}
            onClick={() => handleSourceSelect('openaq')}
          >
            <div className="source-option-content">
              <strong>OpenAQ</strong>
              <span className="muted"><Trans ns="devices" i18nKey="adminDeviceNew.text.importOpenAqLocations" /></span>
            </div>
          </button>
        )}
        <button
          type="button"
          className={`source-option-card ${dataSource === 'manual' ? 'selected' : ''}`}
          onClick={() => handleSourceSelect('manual')}
        >
          <div className="source-option-content">
            <strong><Trans ns="devices" i18nKey="adminDeviceNew.text.manualEntry" /></strong>
            <span className="muted"><Trans ns="devices" i18nKey="adminDeviceNew.text.enterDeviceDetailsManually" /></span>
          </div>
        </button>
      </div>
      {sourcesError && <p className="error-banner" role="alert" style={{ marginTop: 12 }}>
        <Trans ns="common" i18nKey="errors.requestFailed" />
      </p>}
      {!sourcesLoading && !sourcesError && !hasAirGradient && (
        <p className="info-banner" style={{ marginTop: 12 }}>
          <Trans ns="devices" i18nKey="airgradient.errors.configuration_required" />{' '}
          <Link to="/admin/sources"><Trans ns="devices" i18nKey="airgradient.configure" /></Link>
        </p>
      )}
      {sourcesLoading && (
        <div className="info-banner" style={{ marginTop: 12 }}>
          <Trans ns="devices" i18nKey="adminDeviceNew.text.loadingDataSources" /></div>
      )}
      {!sourcesLoading && !sourcesError && !activeSources.length && (
        <div className="warning-banner" style={{ marginTop: 12 }}>
          <Trans ns="devices" i18nKey="adminDeviceNew.text.noActiveDataSourcesCurrentlyAvailable" /></div>
      )}
    </div>
  );

  
  const renderPurpleAirForm = () => (
    <div className="card">
      <h2><Trans ns="devices" i18nKey="adminDeviceNew.headings.purpleAirSensorLookup" /></h2>
      <div className="purpleair-instructions">
        <p>
          <Trans ns="devices" i18nKey="adminDeviceNew.text.enter" /><strong><Trans ns="devices" i18nKey="adminDeviceNew.text.sensorIndex" /></strong> <Trans ns="devices" i18nKey="adminDeviceNew.text.purpleAirMapLookUpDevice" /></p>
        <details>
          <summary><Trans ns="devices" i18nKey="adminDeviceNew.text.howFindSensorIndex" /></summary>
          <ol>
            <li>
              <Trans ns="devices" i18nKey="adminDeviceNew.text.go" />{' '}
              <a
                href="https://map.purpleair.com/"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Trans ns="devices" i18nKey="adminDeviceNew.actions.purpleAirMap" /></a>
            </li>
            <li><Trans ns="devices" i18nKey="adminDeviceNew.text.clickSensorYouWantAdd" /></li>
            <li>
              <Trans ns="devices" i18nKey="adminDeviceNew.text.lookUrlNumberAfter" /><code>/sensor/</code> <Trans ns="devices" i18nKey="adminDeviceNew.text.sensorIndex2" /></li>
            <li>
              <Trans ns="devices" i18nKey="adminDeviceNew.text.example" /><code>map.purpleair.com/sensor/12345</code><Trans ns="devices" i18nKey="adminDeviceNew.text.sensorIndex3" /><strong>12345</strong>
            </li>
          </ol>
        </details>
      </div>

      <div className="form-row" style={{ marginTop: 16 }}>
        <label className="field" style={{ flex: 1, maxWidth: 300 }}>
          <span><Trans ns="devices" i18nKey="adminDeviceNew.text.sensorIndex4" /></span>
          <input
            type="text"
            className="text-input"
            value={sensorIndex}
            onChange={(e) => setSensorIndex(e.target.value)}
            placeholder="e.g., 12345"
            disabled={lookupLoading}
          />
        </label>
        <div className="field" style={{ alignSelf: 'flex-end' }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleLookupClick}
            disabled={lookupLoading || !sensorIndex.trim()}
          >
            {lookupLoading ? i18n.t('devices:adminDeviceNew.actions.lookingUp') : i18n.t('devices:adminDeviceNew.actions.lookup')}
          </button>
        </div>
      </div>

      {lookupError && (
        <div className="error-banner" style={{ marginTop: 12 }}>
          {lookupError}
        </div>
      )}
    </div>
  );

  
  const renderLookupResults = () => {
    if (!lookupData) return null;

    const { device, sensors } = lookupData;

    return (
      <div className="card">
        <h2><Trans ns="devices" i18nKey="adminDeviceNew.headings.devicePreview" /></h2>
        <p className="muted" style={{ marginBottom: 16 }}>
          <Trans ns="devices" i18nKey="adminDeviceNew.text.reviewInformationBelowClickSaveCreate" /></p>

        <div className="preview-section">
          <h4><Trans ns="devices" i18nKey="adminDeviceNew.headings.deviceInformation" /></h4>
          <div className="preview-grid">
            <div className="preview-field">
              <span className="label"><Trans ns="common" i18nKey="fields.name" /></span>
              <span className="value">{device.name}</span>
            </div>
            <div className="preview-field">
              <span className="label"><Trans ns="devices" i18nKey="adminDeviceNew.text.externalId" /></span>
              <span className="value mono">{device.external_id}</span>
            </div>
            <div className="preview-field">
              <span className="label"><Trans ns="devices" i18nKey="adminDeviceNew.text.latitude" /></span>
              <span className="value">
                {device.latitude?.toFixed(6) ?? '—'}
              </span>
            </div>
            <div className="preview-field">
              <span className="label"><Trans ns="devices" i18nKey="adminDeviceNew.text.longitude" /></span>
              <span className="value">
                {device.longitude?.toFixed(6) ?? '—'}
              </span>
            </div>
            <div className="preview-field">
              <span className="label"><Trans ns="devices" i18nKey="adminDeviceNew.text.timezone" /></span>
              <span className="value">{device.timezone ?? '—'}</span>
            </div>
          </div>
        </div>

        <div className="preview-section" style={{ marginTop: 20 }}>
          <h4><Trans ns="devices" i18nKey="adminDeviceNew.headings.sensors" /></h4>
          <table className="admin-table">
            <thead>
              <tr>
                <th><Trans ns="devices" i18nKey="adminDeviceNew.columns.parameter" /></th>
                <th><Trans ns="devices" i18nKey="adminDeviceNew.columns.externalSensorId" /></th>
                <th><Trans ns="devices" i18nKey="adminDeviceNew.columns.latestValue" /></th>
                <th><Trans ns="devices" i18nKey="adminDeviceNew.columns.unit" /></th>
              </tr>
            </thead>
            <tbody>
              {sensors.map((s) => (
                <tr key={s.external_sensor_id}>
                  <td data-label={i18n.t('devices:adminDeviceNew.columns.parameter')}>
                    <strong>{s.parameter_code.toUpperCase()}</strong>
                  </td>
                  <td data-label={i18n.t('devices:adminDeviceNew.columns.externalSensorId')} className="mono">{s.external_sensor_id}</td>
                  <td data-label={i18n.t('devices:adminDeviceNew.columns.latestValue')}>{formatMeasurementValue(s.latest_value)}</td>
                  <td data-label={i18n.t('devices:adminDeviceNew.columns.unit')}>{s.unit_code === 'ug_m3' ? 'µg/m³' : s.unit_code}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {saveError && (
          <div className="error-banner" style={{ marginTop: 12 }}>
            {saveError}
          </div>
        )}

        <div className="form-actions" style={{ marginTop: 20 }}>
          <div className="actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleCancel}
              disabled={saving}
            >
              <Trans ns="common" i18nKey="actions.cancel" /></button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? i18n.t('devices:adminDeviceNew.actions.saving') : i18n.t('common:actions.save')}
            </button>
          </div>
        </div>
      </div>
    );
  };

  
  const renderConfirmDialog = () => {
    if (!showConfirm) return null;

    return (
      <AdminDialog title={i18n.t('devices:adminDeviceNew.headings.confirmApiRequest')} onClose={() => setShowConfirm(false)}>
          <p>
            <Trans ns="devices" i18nKey="adminDeviceNew.text.willMakeRequestPurpleAirApi" />{' '}
            <strong><Trans ns="devices" i18nKey="adminDeviceNew.text.consumesApiPoints" /></strong>.
          </p>
          <p className="muted" style={{ marginTop: 8 }}>
            <Trans ns="devices" i18nKey="adminDeviceNew.text.purpleAirApiUsageLimitedOnly" /></p>
          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setShowConfirm(false)}
            >
              <Trans ns="common" i18nKey="actions.cancel" /></button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleConfirmLookup}
            >
              <Trans ns="devices" i18nKey="adminDeviceNew.actions.proceedLookup" /></button>
          </div>
      </AdminDialog>
    );
  };

  
  if (dataSource === 'manual') {
    
    navigate('/admin/devices/manual');
    return null;
  }

  return (
    <AdminPageLayout
      title={i18n.t('devices:adminDeviceNew.tooltips.addNewDevice')}
      breadcrumbs={[
        { label: i18n.t('devices:adminDeviceNew.content.admin'), to: '/admin' },
        { label: i18n.t('devices:adminDeviceNew.content.devices'), to: '/admin/devices' },
        { label: i18n.t('devices:adminDeviceNew.content.newDevice') },
      ]}
      actions={
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleCancel}
        >
          <Trans ns="common" i18nKey="actions.cancel" /></button>
      }
      contentClassName="admin-workspace device-editor-page"
    >
      <div className="device-new-flow">
        {renderSourceSelection()}

        {dataSource === 'purpleair' && !lookupData && renderPurpleAirForm()}

        {lookupData && renderLookupResults()}
      </div>

      {renderConfirmDialog()}
    </AdminPageLayout>
  );
}
