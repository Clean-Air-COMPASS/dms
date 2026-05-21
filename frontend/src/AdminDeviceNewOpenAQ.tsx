import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  lookupOpenAQLocations,
  lookupOpenAQSensor,
  createOpenAQDevices,
  type OpenAQLocation,
  type OpenAQSensor,
} from './api';
import AdminPageLayout from './components/AdminPageLayout';

type LookupMode = 'bbox' | 'sensor_id';


type SelectionState = Record<string, Set<number>>;

export default function AdminDeviceNewOpenAQ() {
  const navigate = useNavigate();

  
  const [mode, setMode] = useState<LookupMode>('bbox');

  
  const [minLon, setMinLon] = useState('');
  const [minLat, setMinLat] = useState('');
  const [maxLon, setMaxLon] = useState('');
  const [maxLat, setMaxLat] = useState('');
  const [sensorIdInput, setSensorIdInput] = useState('');

  
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [locations, setLocations] = useState<OpenAQLocation[] | null>(null);

  
  const [selection, setSelection] = useState<SelectionState>({});

  
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  
  const [showConfirm, setShowConfirm] = useState(false);

  const handleModeChange = (newMode: LookupMode) => {
    setMode(newMode);
    setLocations(null);
    setLookupError(null);
    setSelection({});
    
    if (newMode === 'bbox') {
      setSensorIdInput('');
    } else {
      setMinLon('');
      setMinLat('');
      setMaxLon('');
      setMaxLat('');
    }
  };

  const handleLookupClick = () => {
    if (mode === 'bbox') {
      const minLonTrimmed = minLon.trim();
      const minLatTrimmed = minLat.trim();
      const maxLonTrimmed = maxLon.trim();
      const maxLatTrimmed = maxLat.trim();

      
      if (!minLonTrimmed || !minLatTrimmed || !maxLonTrimmed || !maxLatTrimmed) {
        setLookupError('Please fill in all four coordinate fields');
        return;
      }

      
      const minLonNum = parseFloat(minLonTrimmed);
      const minLatNum = parseFloat(minLatTrimmed);
      const maxLonNum = parseFloat(maxLonTrimmed);
      const maxLatNum = parseFloat(maxLatTrimmed);

      if (isNaN(minLonNum) || isNaN(minLatNum) || isNaN(maxLonNum) || isNaN(maxLatNum)) {
        setLookupError('All coordinate values must be valid numbers');
        return;
      }

      
      if (minLonNum >= maxLonNum) {
        setLookupError('Minimum Longitude (West) must be less than Maximum Longitude (East)');
        return;
      }
      if (minLatNum >= maxLatNum) {
        setLookupError('Minimum Latitude (South) must be less than Maximum Latitude (North)');
        return;
      }
    }
    if (mode === 'sensor_id') {
      const trimmed = sensorIdInput.trim();
      if (!trimmed) {
        setLookupError('Please enter an OpenAQ Sensor ID');
        return;
      }
      if (!/^\d+$/.test(trimmed)) {
        setLookupError('Sensor ID must be numeric');
        return;
      }
    }
    
    setShowConfirm(true);
  };

  const handleConfirmLookup = async () => {
    setShowConfirm(false);
    setLookupLoading(true);
    setLookupError(null);
    setLocations(null);
    setSelection({});

    try {
      let result;
      
      if (mode === 'bbox') {
        
        const bbox = `${minLon.trim()},${minLat.trim()},${maxLon.trim()},${maxLat.trim()}`;
        result = await lookupOpenAQLocations({ bbox });
      } else {
        
        result = await lookupOpenAQSensor(sensorIdInput.trim());
      }
      
      if (!result.locations || result.locations.length === 0) {
        setLookupError(mode === 'sensor_id' ? 'Sensor not found.' : 'No locations found for the given criteria.');
        return;
      }

      setLocations(result.locations);
      
      
      const initialSelection: SelectionState = {};
      for (const loc of result.locations) {
        const selectableSensors = loc.sensors.filter((s) => !s.exists);
        if (!loc.already_exists && selectableSensors.length > 0) {
          initialSelection[loc.device.external_id] = new Set(
            selectableSensors.map((s) => s.sensor_id)
          );
        }
      }
      setSelection(initialSelection);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setLookupError(message);
    } finally {
      setLookupLoading(false);
    }
  };

  const toggleDeviceSelection = (extId: string, sensors: OpenAQSensor[], disableAll?: boolean) => {
    if (disableAll) return;
    const selectableSensors = sensors.filter((s) => !s.exists);
    if (!selectableSensors.length) return;
    setSelection((prev) => {
      const newSelection = { ...prev };
      if (newSelection[extId] && newSelection[extId].size > 0) {
        
        delete newSelection[extId];
      } else {
        
        newSelection[extId] = new Set(selectableSensors.map((s) => s.sensor_id));
      }
      return newSelection;
    });
  };

  const toggleSensorSelection = (extId: string, sensorId: number, disable?: boolean) => {
    if (disable) return;
    setSelection((prev) => {
      const newSelection = { ...prev };
      const current = newSelection[extId] || new Set();
      const updated = new Set(current);
      if (updated.has(sensorId)) {
        updated.delete(sensorId);
      } else {
        updated.add(sensorId);
      }
      if (updated.size === 0) {
        delete newSelection[extId];
      } else {
        newSelection[extId] = updated;
      }
      return newSelection;
    });
  };

  const getSelectedCount = () => {
    let devices = 0;
    let sensors = 0;
    for (const extId of Object.keys(selection)) {
      if (selection[extId].size > 0) {
        devices++;
        sensors += selection[extId].size;
      }
    }
    return { devices, sensors };
  };

  const handleSave = async () => {
    if (!locations) return;

    const selectedExtIds = Object.keys(selection).filter(
      (extId) => selection[extId] && selection[extId].size > 0
    );
    if (selectedExtIds.length === 0) {
      setSaveError('Please select at least one device/sensor to save.');
      return;
    }

    setSaving(true);
    setSaveError(null);

    try {
      
      const locsToCreate = locations.filter(
        (loc) => selectedExtIds.includes(loc.device.external_id) && !loc.already_exists
      );

      
      const selectedSensors: Record<string, number[]> = {};
      for (const extId of selectedExtIds) {
        const loc = locations.find((l) => l.device.external_id === extId);
        const allowed = loc?.sensors.filter((s) => !s.exists).map((s) => s.sensor_id) || [];
        const allowedSet = new Set(allowed);
        const picked = Array.from(selection[extId] || []).filter((sid) => allowedSet.has(sid));
        if (picked.length > 0) {
          selectedSensors[extId] = picked;
        }
      }

      const result = await createOpenAQDevices(locsToCreate, selectedSensors);

      if (result.count === 1 && result.created.length === 1) {
        
        navigate(`/admin/devices/${result.created[0].device.device_id}/edit`);
      } else {
        
        navigate('/admin/devices');
      }
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

  const formatDate = (isoStr: string | null | undefined) => {
    if (!isoStr) return '—';
    try {
      return new Date(isoStr).toLocaleDateString();
    } catch {
      return isoStr;
    }
  };

  const formatDateTime = (isoStr: string | null | undefined) => {
    if (!isoStr) return '—';
    try {
      return new Date(isoStr).toLocaleString();
    } catch {
      return isoStr;
    }
  };

  const formatNumber = (val: number | null | undefined, decimals = 2) => {
    if (val === null || val === undefined) return '—';
    return val.toFixed(decimals);
  };

  
  const renderLookupForm = () => (
    <div className="card">
      <h3>OpenAQ Location Lookup</h3>
      <p className="muted" style={{ marginBottom: 16 }}>
        Search for air quality monitoring locations from the OpenAQ network.
      </p>

      
      <div className="tablist" style={{ marginBottom: 16 }}>
        <button
          type="button"
          className={`tab ${mode === 'bbox' ? 'active' : ''}`}
          onClick={() => handleModeChange('bbox')}
        >
          By Bounding Box
        </button>
        <button
          type="button"
          className={`tab ${mode === 'sensor_id' ? 'active' : ''}`}
          onClick={() => handleModeChange('sensor_id')}
        >
          By Sensor ID
        </button>
      </div>

      {mode === 'bbox' && (
        <div className="openaq-instructions">
          <p>
            Enter coordinates to define a <strong>bounding box</strong> for searching locations within a geographic area.
          </p>
          <details>
            <summary>How to find coordinates</summary>
            <div style={{ padding: '8px 0' }}>
              <p>You can use tools like <a href="https://boundingbox.klokantech.com/" target="_blank" rel="noopener noreferrer">bboxfinder</a> to draw a box and get coordinates.</p>
              <p style={{ marginTop: 8 }}>Example for San Luis Obispo area:</p>
              <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
                <li>West (Min Lon): <code>-121.0</code></li>
                <li>South (Min Lat): <code>34.8</code></li>
                <li>East (Max Lon): <code>-120.3</code></li>
                <li>North (Max Lat): <code>35.7</code></li>
              </ul>
            </div>
          </details>

          <div className="bbox-fields-grid" style={{ marginTop: 16 }}>
            <div className="bbox-row">
              <label className="field">
                <span>Minimum Longitude (West)</span>
                <input
                  type="text"
                  className="text-input"
                  value={minLon}
                  onChange={(e) => setMinLon(e.target.value)}
                  placeholder="e.g., -121.0"
                  disabled={lookupLoading}
                />
              </label>
              <label className="field">
                <span>Minimum Latitude (South)</span>
                <input
                  type="text"
                  className="text-input"
                  value={minLat}
                  onChange={(e) => setMinLat(e.target.value)}
                  placeholder="e.g., 34.8"
                  disabled={lookupLoading}
                />
              </label>
            </div>
            <div className="bbox-row">
              <label className="field">
                <span>Maximum Longitude (East)</span>
                <input
                  type="text"
                  className="text-input"
                  value={maxLon}
                  onChange={(e) => setMaxLon(e.target.value)}
                  placeholder="e.g., -120.3"
                  disabled={lookupLoading}
                />
              </label>
              <label className="field">
                <span>Maximum Latitude (North)</span>
                <input
                  type="text"
                  className="text-input"
                  value={maxLat}
                  onChange={(e) => setMaxLat(e.target.value)}
                  placeholder="e.g., 35.7"
                  disabled={lookupLoading}
                />
              </label>
            </div>
          </div>

          <div className="form-row" style={{ marginTop: 16 }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleLookupClick}
              disabled={lookupLoading || !minLon.trim() || !minLat.trim() || !maxLon.trim() || !maxLat.trim()}
            >
              {lookupLoading ? 'Searching…' : 'Search'}
            </button>
          </div>
        </div>
      )}

      {mode === 'sensor_id' && (
        <div className="openaq-instructions">
          <p>
            Enter an <strong>OpenAQ Sensor ID</strong> to look up a specific sensor.
          </p>
          <details>
            <summary>How to find the Sensor ID</summary>
            <div style={{ padding: '8px 0' }}>
              <ol>
                <li>
                  Go to the{' '}
                  <a
                    href="https://explore.openaq.org/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    OpenAQ Explorer
                  </a>
                </li>
                <li>Click on a monitoring station on the map</li>
                <li>Select a specific sensor/parameter from the station</li>
                <li>The Sensor ID is shown in the sensor details or URL</li>
              </ol>
              <p style={{ marginTop: 8, fontSize: '0.9em', color: '#666' }}>
                Note: Each sensor measures a single parameter (e.g., PM2.5, O3). A location may have multiple sensors.
              </p>
            </div>
          </details>

          <div className="form-row" style={{ marginTop: 16 }}>
            <label className="field" style={{ flex: 1, maxWidth: 300 }}>
              <span>OpenAQ Sensor ID</span>
              <input
                type="text"
                className="text-input"
                value={sensorIdInput}
                onChange={(e) => setSensorIdInput(e.target.value)}
                placeholder="e.g., 3917"
                disabled={lookupLoading}
              />
            </label>
            <div className="field" style={{ alignSelf: 'flex-end' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleLookupClick}
                disabled={lookupLoading || !sensorIdInput.trim()}
              >
                {lookupLoading ? 'Looking up…' : 'Lookup'}
              </button>
            </div>
          </div>
        </div>
      )}

      {lookupError && (
        <div className="error-banner" style={{ marginTop: 12 }}>
          {lookupError}
        </div>
      )}
    </div>
  );

  
  const renderResults = () => {
    if (!locations || locations.length === 0) return null;

    const { devices: selectedDevices, sensors: selectedSensors } = getSelectedCount();
    const existingLocations = locations.filter((loc) => loc.already_exists);
    const isSensorLookup = mode === 'sensor_id';

    return (
      <div className="card">
        <div className="card-header-row">
          <h3>Search Results</h3>
          <span className="muted">
            Found {locations.length} {isSensorLookup ? 'sensor' : 'location'}{locations.length !== 1 ? 's' : ''}
            {existingLocations.length > 0 && (
              <> ({existingLocations.length} already in database)</>
            )}
          </span>
        </div>

        {locations.length > 0 && (
          <div className="openaq-results-table-wrapper">
            <table className="admin-table openaq-results-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>
                    <span className="sr-only">Select</span>
                  </th>
                  <th>Name</th>
                  {isSensorLookup ? (
                    <>
                      <th>Parameter</th>
                      <th>Latest Value</th>
                      <th>Coordinates</th>
                      <th>Data Range</th>
                      <th>Coverage</th>
                    </>
                  ) : (
                    <>
                      <th>Location</th>
                      <th>Provider</th>
                      <th>Coordinates</th>
                      <th>Sensors</th>
                      <th>Data Range</th>
                      <th>Type</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {locations.map((loc) => {
                  const extId = loc.device.external_id;
                  const isSelected = selection[extId] && selection[extId].size > 0;
                  const isExisting = loc.already_exists;
                  const selectableSensors = loc.sensors.filter((s) => !s.exists);
                  const hasSelectableSensors = selectableSensors.length > 0;
                  const allSelectableSelected = selection[extId]?.size === selectableSensors.length;

                  if (isSensorLookup) {
                    
                    const sensor = loc.sensors[0];
                    const sensorExists = sensor?.exists;
                    const checkboxDisabled = isExisting || sensorExists;
                    return (
                      <tr
                        key={extId}
                        className={`${checkboxDisabled ? 'row-disabled' : ''} ${isSelected ? 'row-selected' : ''}`}
                      >
                        <td>
                          <input
                            type="checkbox"
                            checked={!checkboxDisabled && Boolean(isSelected)}
                            disabled={checkboxDisabled}
                            onChange={() => toggleDeviceSelection(extId, loc.sensors, checkboxDisabled)}
                            title={checkboxDisabled ? 'Already exists in database' : 'Select sensor'}
                          />
                        </td>
                        <td>
                          <div className="cell-primary">{loc.device.name}</div>
                          <div className="cell-secondary mono">Sensor ID: {extId}</div>
                          {(isExisting || sensorExists) && (
                            <span className="status-badge status-error badge-exists">Already exists</span>
                          )}
                        </td>
                        <td>
                          <div className="cell-primary">
                            {sensor?.parameter_display || sensor?.parameter_code?.toUpperCase() || sensor?.name || '—'}
                          </div>
                          <div className="cell-secondary">{sensor?.unit || '—'}</div>
                        </td>
                        <td>
                          {loc.metadata.latest_value !== null && loc.metadata.latest_value !== undefined ? (
                            <>
                              <div className="cell-primary">
                                {formatNumber(loc.metadata.latest_value)} {sensor?.unit || ''}
                              </div>
                              <div className="cell-secondary">
                                {formatDateTime(loc.metadata.latest_datetime_utc)}
                              </div>
                            </>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className="mono">
                          {loc.device.latitude?.toFixed(4) ?? '—'},<br />
                          {loc.device.longitude?.toFixed(4) ?? '—'}
                        </td>
                        <td>
                          <div className="cell-secondary">
                            {formatDate(loc.metadata.datetime_first_utc)}
                          </div>
                          <div className="cell-secondary">
                            to {formatDate(loc.metadata.datetime_last_utc)}
                          </div>
                        </td>
                        <td>
                          {loc.metadata.coverage_percent !== null && loc.metadata.coverage_percent !== undefined ? (
                            <>
                              <div className="cell-primary">
                                {formatNumber(loc.metadata.coverage_percent, 1)}%
                              </div>
                              <div className="cell-secondary">
                                {loc.metadata.observed_count ?? '—'} / {loc.metadata.expected_count ?? '—'}
                              </div>
                            </>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  }

                  
                  const rowDisabled = isExisting || !hasSelectableSensors;
                  return (
                    <tr
                      key={extId}
                      className={`${rowDisabled ? 'row-disabled' : ''} ${isSelected ? 'row-selected' : ''}`}
                    >
                      <td>
                        <input
                          type="checkbox"
                          checked={!rowDisabled && Boolean(selection[extId] && allSelectableSelected)}
                          disabled={rowDisabled}
                          onChange={() => toggleDeviceSelection(extId, loc.sensors, rowDisabled)}
                          title={rowDisabled ? 'Already exists in database or no selectable sensors' : 'Select/deselect all sensors'}
                        />
                      </td>
                      <td>
                        <div className="cell-primary">{loc.device.name}</div>
                        <div className="cell-secondary mono">ID: {extId}</div>
                        {isExisting && (
                          <span className="status-badge status-error badge-exists">Already exists</span>
                        )}
                      </td>
                      <td>
                        <div>{loc.metadata.locality || '—'}</div>
                        <div className="cell-secondary">
                          {loc.metadata.country_name || loc.metadata.country_code || '—'}
                        </div>
                      </td>
                      <td>
                        <div>{loc.metadata.provider_name || '—'}</div>
                        {loc.metadata.owner_name && (
                          <div className="cell-secondary">{loc.metadata.owner_name}</div>
                        )}
                      </td>
                      <td className="mono">
                        {loc.device.latitude?.toFixed(4) ?? '—'},<br />
                        {loc.device.longitude?.toFixed(4) ?? '—'}
                      </td>
                      <td>
                          <div className="sensor-checkboxes">
                            {loc.sensors.map((s) => {
                            const sensorSelected = selection[extId]?.has(s.sensor_id) ?? false;
                            const sensorExists = s.exists;
                            const checkboxDisabled = isExisting || sensorExists || !hasSelectableSensors;
                            return (
                              <label
                                key={s.sensor_id}
                                className={`sensor-checkbox ${checkboxDisabled ? 'disabled' : ''}`}
                                title={`${s.parameter_display || s.name} (${s.unit})`}
                              >
                                <input
                                  type="checkbox"
                                  checked={!checkboxDisabled && sensorSelected}
                                  disabled={checkboxDisabled}
                                  onChange={() => toggleSensorSelection(extId, s.sensor_id, checkboxDisabled)}
                                />
                                <span className="sensor-label">
                                  {s.parameter_code?.toUpperCase() || s.name}
                                </span>
                                <span className="sensor-unit">{s.unit}</span>
                                {sensorExists && (
                                  <span className="status-badge status-error badge-exists">Already Exists</span>
                                )}
                              </label>
                            );
                          })}
                        </div>
                      </td>
                      <td>
                        <div className="cell-secondary">
                          {formatDate(loc.metadata.datetime_first_utc)}
                        </div>
                        <div className="cell-secondary">
                          to {formatDate(loc.metadata.datetime_last_utc)}
                        </div>
                      </td>
                      <td>
                        <div className="type-badges">
                          {loc.metadata.is_monitor && (
                            <span className="badge badge-monitor">Monitor</span>
                          )}
                          {loc.metadata.is_mobile && (
                            <span className="badge badge-mobile">Mobile</span>
                          )}
                          {!loc.metadata.is_monitor && !loc.metadata.is_mobile && (
                            <span className="badge">Sensor</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {saveError && (
          <div className="error-banner" style={{ marginTop: 12 }}>
            {saveError}
          </div>
        )}

        <div className="form-actions" style={{ marginTop: 20 }}>
          <div className="selection-summary">
            {selectedDevices > 0 ? (
              <span>
                {selectedDevices} device{selectedDevices !== 1 ? 's' : ''},{' '}
                {selectedSensors} sensor{selectedSensors !== 1 ? 's' : ''} selected
              </span>
            ) : (
              <span className="muted">No devices selected</span>
            )}
          </div>
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
              disabled={saving || selectedDevices === 0}
            >
              {saving ? 'Saving…' : `Save Selected (${selectedDevices})`}
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
            This will make a request to the OpenAQ API.
          </p>
          <p className="muted" style={{ marginTop: 8 }}>
            OpenAQ has rate limits. If you encounter a rate limit error, please wait and try again later.
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
              Proceed
            </button>
          </div>
        </div>
      </div>
    );
  };

  return (
    <AdminPageLayout
      title="Add OpenAQ Sensor"
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'Devices', to: '/admin/devices' },
        { label: 'Add OpenAQ Sensor' },
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
        {renderLookupForm()}
        {renderResults()}
      </div>

      {renderConfirmDialog()}
    </AdminPageLayout>
  );
}
