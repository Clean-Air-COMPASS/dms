import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listExternalAPIs,
  lookupPurpleAirSensor,
  createPurpleAirDevice,
  type ExternalAPI,
  type PurpleAirLookupDevice,
  type PurpleAirLookupSensor,
} from './api';
import AdminPageLayout from './components/AdminPageLayout';

type DataSource = 'none' | 'purpleair' | 'openaq' | 'manual';

export default function AdminDeviceNew() {
  const navigate = useNavigate();

  
  const [dataSource, setDataSource] = useState<DataSource>('none');

  
  const [sources, setSources] = useState<ExternalAPI[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);

  
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
        // Non-critical; show empty list
      } finally {
        if (!cancelled) setSourcesLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const activeSources = sources.filter((s) => s.is_active !== false);

  const hasPurpleAir = sources.some(
    (s) => s.is_active !== false && s.name.toLowerCase() === 'purpleair'
  );

  const hasOpenAQ = sources.some(
    (s) => s.is_active !== false && s.name.toLowerCase() === 'openaq'
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
      setLookupError('Please enter a Sensor Index');
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
      const result = await lookupPurpleAirSensor(sensorIndex.trim());
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
      <h3>Select Data Source</h3>
      <p className="muted" style={{ marginBottom: 16 }}>
        Choose how you want to add the new device.
      </p>
      <div className="source-options">
        {hasPurpleAir && (
          <button
            type="button"
            className={`source-option-card ${dataSource === 'purpleair' ? 'selected' : ''}`}
            onClick={() => handleSourceSelect('purpleair')}
          >
            <div className="source-option-icon">🟣</div>
            <div className="source-option-content">
              <strong>PurpleAir</strong>
              <span className="muted">Import from PurpleAir sensor index</span>
            </div>
          </button>
        )}
        {hasOpenAQ && (
          <button
            type="button"
            className={`source-option-card ${dataSource === 'openaq' ? 'selected' : ''}`}
            onClick={() => handleSourceSelect('openaq')}
          >
            <div className="source-option-icon">🌐</div>
            <div className="source-option-content">
              <strong>OpenAQ</strong>
              <span className="muted">Import from OpenAQ locations</span>
            </div>
          </button>
        )}
        <button
          type="button"
          className={`source-option-card ${dataSource === 'manual' ? 'selected' : ''}`}
          onClick={() => handleSourceSelect('manual')}
        >
          <div className="source-option-icon">✏️</div>
          <div className="source-option-content">
            <strong>Manual Entry</strong>
            <span className="muted">Enter device details manually</span>
          </div>
        </button>
      </div>
      {sourcesLoading && (
        <div className="info-banner" style={{ marginTop: 12 }}>
          Loading data sources…
        </div>
      )}
      {!sourcesLoading && !activeSources.length && (
        <div className="warning-banner" style={{ marginTop: 12 }}>
          No active data sources are currently available for new devices.
        </div>
      )}
    </div>
  );

  
  const renderPurpleAirForm = () => (
    <div className="card">
      <h3>PurpleAir Sensor Lookup</h3>
      <div className="purpleair-instructions">
        <p>
          Enter the <strong>Sensor Index</strong> from the PurpleAir Map to look
          up device metadata.
        </p>
        <details>
          <summary>How to find the Sensor Index</summary>
          <ol>
            <li>
              Go to the{' '}
              <a
                href="https://map.purpleair.com/"
                target="_blank"
                rel="noopener noreferrer"
              >
                PurpleAir Map
              </a>
            </li>
            <li>Click on the sensor you want to add</li>
            <li>
              Look at the URL — the number after <code>/sensor/</code> is the
              Sensor Index
            </li>
            <li>
              Example: In <code>map.purpleair.com/sensor/12345</code>, the
              Sensor Index is <strong>12345</strong>
            </li>
          </ol>
        </details>
      </div>

      <div className="form-row" style={{ marginTop: 16 }}>
        <label className="field" style={{ flex: 1, maxWidth: 300 }}>
          <span>Sensor Index</span>
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
            {lookupLoading ? 'Looking up…' : 'Lookup'}
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
        <h3>Device Preview</h3>
        <p className="muted" style={{ marginBottom: 16 }}>
          Review the information below. Click Save to create the device.
        </p>

        <div className="preview-section">
          <h4>Device Information</h4>
          <div className="preview-grid">
            <div className="preview-field">
              <span className="label">Name</span>
              <span className="value">{device.name}</span>
            </div>
            <div className="preview-field">
              <span className="label">External ID</span>
              <span className="value mono">{device.external_id}</span>
            </div>
            <div className="preview-field">
              <span className="label">Latitude</span>
              <span className="value">
                {device.latitude?.toFixed(6) ?? '—'}
              </span>
            </div>
            <div className="preview-field">
              <span className="label">Longitude</span>
              <span className="value">
                {device.longitude?.toFixed(6) ?? '—'}
              </span>
            </div>
            <div className="preview-field">
              <span className="label">Timezone</span>
              <span className="value">{device.timezone ?? '—'}</span>
            </div>
          </div>
        </div>

        <div className="preview-section" style={{ marginTop: 20 }}>
          <h4>Sensors</h4>
          <table className="admin-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>External Sensor ID</th>
                <th>Latest Value</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {sensors.map((s) => (
                <tr key={s.external_sensor_id}>
                  <td>
                    <strong>{s.parameter_code.toUpperCase()}</strong>
                  </td>
                  <td className="mono">{s.external_sensor_id}</td>
                  <td>{s.latest_value?.toFixed(2) ?? '—'}</td>
                  <td>{s.unit_code === 'ug_m3' ? 'µg/m³' : s.unit_code}</td>
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
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    );
  };

  
  const renderConfirmDialog = () => {
    if (!showConfirm) return null;

    return (
      <div className="modal-overlay" onClick={() => setShowConfirm(false)}>
        <div
          className="modal-dialog"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-title"
        >
          <h3 id="confirm-title">Confirm API Request</h3>
          <p>
            This will make a request to the PurpleAir API, which{' '}
            <strong>consumes API points</strong>.
          </p>
          <p className="muted" style={{ marginTop: 8 }}>
            PurpleAir API usage is limited. Only proceed if you intend to add
            this device.
          </p>
          <div className="modal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setShowConfirm(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleConfirmLookup}
            >
              Proceed with Lookup
            </button>
          </div>
        </div>
      </div>
    );
  };

  
  if (dataSource === 'manual') {
    
    navigate('/admin/devices/manual');
    return null;
  }

  return (
    <AdminPageLayout
      title="Add New Device"
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'Devices', to: '/admin/devices' },
        { label: 'New Device' },
      ]}
      actions={
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleCancel}
        >
          Cancel
        </button>
      }
      contentClassName="device-editor-page"
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
