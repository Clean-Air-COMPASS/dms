import { formatMeasurementValue } from './measurementFormatting';
import { Trans } from 'react-i18next';
import i18n from './i18n';
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
import AdminDialog from './admin/AdminDialog';

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
        setLookupError(i18n.t('devices:adminDeviceNewOpenAQ.messages.pleaseFillAllFourCoordinateFields'));
        return;
      }

      
      const minLonNum = parseFloat(minLonTrimmed);
      const minLatNum = parseFloat(minLatTrimmed);
      const maxLonNum = parseFloat(maxLonTrimmed);
      const maxLatNum = parseFloat(maxLatTrimmed);

      if (isNaN(minLonNum) || isNaN(minLatNum) || isNaN(maxLonNum) || isNaN(maxLatNum)) {
        setLookupError(i18n.t('devices:adminDeviceNewOpenAQ.messages.allCoordinateValuesMustValidNumbers'));
        return;
      }

      
      if (minLonNum >= maxLonNum) {
        setLookupError(i18n.t('devices:adminDeviceNewOpenAQ.messages.minimumLongitudeWestMustLessThan'));
        return;
      }
      if (minLatNum >= maxLatNum) {
        setLookupError(i18n.t('devices:adminDeviceNewOpenAQ.messages.minimumLatitudeSouthMustLessThan'));
        return;
      }
    }
    if (mode === 'sensor_id') {
      const trimmed = sensorIdInput.trim();
      if (!trimmed) {
        setLookupError(i18n.t('devices:adminDeviceNewOpenAQ.messages.pleaseEnterOpenAqSensorId'));
        return;
      }
      if (!/^\d+$/.test(trimmed)) {
        setLookupError(i18n.t('devices:adminDeviceNewOpenAQ.messages.sensorIdMustNumeric'));
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
        setLookupError(mode === 'sensor_id'
          ? i18n.t('devices:adminDeviceNewOpenAQ.messages.sensorNotFound')
          : i18n.t('devices:adminDeviceNewOpenAQ.messages.noLocationsFound'));
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
      setSaveError(i18n.t('devices:adminDeviceNewOpenAQ.messages.pleaseSelectLeastOneDeviceSensor'));
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
      <h2><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.headings.openAqLocationLookup" /></h2>
      <p className="muted" style={{ marginBottom: 16 }}>
        <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.searchAirQualityMonitoringLocationsOpen" /></p>

      
      <div className="tablist" style={{ marginBottom: 16 }}>
        <button
          type="button"
          className={`tab ${mode === 'bbox' ? 'active' : ''}`}
          onClick={() => handleModeChange('bbox')}
        >
          <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.actions.boundingBox" /></button>
        <button
          type="button"
          className={`tab ${mode === 'sensor_id' ? 'active' : ''}`}
          onClick={() => handleModeChange('sensor_id')}
        >
          <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.actions.sensorId" /></button>
      </div>

      {mode === 'bbox' && (
        <div className="openaq-instructions">
          <p>
            <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.enterCoordinatesDefine" /><strong><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.boundingBox" /></strong> <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.searchingLocationsWithinGeographicArea" /></p>
          <details>
            <summary><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.howFindCoordinates" /></summary>
            <div style={{ padding: '8px 0' }}>
              <p><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.youCanUseToolsLike" />{' '}<a href="https://boundingbox.klokantech.com/" target="_blank" rel="noopener noreferrer"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.actions.bboxfinder" /></a> {' '}<Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.drawBoxGetCoordinates" /></p>
              <p style={{ marginTop: 8 }}><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.exampleSanLuisObispoArea" /></p>
              <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
                <li><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.westMinLon" />{' '}<code>-121.0</code></li>
                <li><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.southMinLat" />{' '}<code>34.8</code></li>
                <li><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.eastMaxLon" />{' '}<code>-120.3</code></li>
                <li><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.northMaxLat" />{' '}<code>35.7</code></li>
              </ul>
            </div>
          </details>

          <div className="bbox-fields-grid" style={{ marginTop: 16 }}>
            <div className="bbox-row">
              <label className="field">
                <span><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.minimumLongitudeWest" /></span>
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
                <span><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.minimumLatitudeSouth" /></span>
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
                <span><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.maximumLongitudeEast" /></span>
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
                <span><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.maximumLatitudeNorth" /></span>
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
              {lookupLoading ? i18n.t('devices:adminDeviceNewOpenAQ.actions.searching') : i18n.t('common:actions.search')}
            </button>
          </div>
        </div>
      )}

      {mode === 'sensor_id' && (
        <div className="openaq-instructions">
          <p>
            <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.enter" /><strong><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.openAqSensorId" /></strong> <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.lookUpSpecificSensor" /></p>
          <details>
            <summary><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.howFindSensorId" /></summary>
            <div style={{ padding: '8px 0' }}>
              <ol>
                <li>
                  <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.go" />{' '}
                  <a
                    href="https://explore.openaq.org/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.actions.openAqExplorer" /></a>
                </li>
                <li><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.clickMonitoringStationMap" /></li>
                <li><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.selectSpecificSensorParameterStation" /></li>
                <li><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.sensorIdShownSensorDetailsUrl" /></li>
              </ol>
              <p style={{ marginTop: 8, fontSize: '0.9em', color: '#666' }}>
                <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.noteEachSensorMeasuresSingleParameter" /></p>
            </div>
          </details>

          <div className="form-row" style={{ marginTop: 16 }}>
            <label className="field" style={{ flex: 1, maxWidth: 300 }}>
              <span><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.openAqSensorId2" /></span>
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
                {lookupLoading ? i18n.t('devices:adminDeviceNewOpenAQ.actions.lookingUp') : i18n.t('devices:adminDeviceNewOpenAQ.actions.lookup')}
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

    const columns = {
      select: { id: 'openaq-result-select', label: i18n.t('common:actions.select') },
      name: { id: 'openaq-result-name', label: i18n.t('common:fields.name') },
      parameter: { id: 'openaq-result-parameter', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.parameter') },
      latestValue: { id: 'openaq-result-latest-value', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.latestValue') },
      coordinates: { id: 'openaq-result-coordinates', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.coordinates') },
      coordinates2: { id: 'openaq-result-location-coordinates', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.coordinates2') },
      dataRange: { id: 'openaq-result-data-range', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.dataRange') },
      coverage: { id: 'openaq-result-coverage', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.coverage') },
      location: { id: 'openaq-result-location', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.location') },
      provider: { id: 'openaq-result-provider', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.provider') },
      sensors: { id: 'openaq-result-sensors', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.sensors') },
      dataRange2: { id: 'openaq-result-location-data-range', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.dataRange2') },
      type: { id: 'openaq-result-type', label: i18n.t('devices:adminDeviceNewOpenAQ.columns.type') },
    };
    const tableColumns = isSensorLookup
      ? [columns.select, columns.name, columns.parameter, columns.latestValue, columns.coordinates, columns.dataRange, columns.coverage]
      : [columns.select, columns.name, columns.location, columns.provider, columns.coordinates2, columns.sensors, columns.dataRange2, columns.type];

    return (
      <div className="card">
        <div className="card-header-row">
          <h2><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.headings.searchResults" /></h2>
          <span className="muted">
            <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.found" />{locations.length} {isSensorLookup ? i18n.t('devices:adminDeviceNewOpenAQ.text.sensor') : i18n.t('devices:adminDeviceNewOpenAQ.text.location')}{locations.length !== 1 ? 's' : ''}
            {existingLocations.length > 0 && (
              <> ({existingLocations.length} {' '}<Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.alreadyDatabase" /></>
            )}
          </span>
        </div>

        {locations.length > 0 && (
          <div className="openaq-results-table-wrapper">
            <table className="admin-table openaq-results-table">
              <thead>
                <tr>
                  {tableColumns.map((column) => (
                    <th
                      key={column.id}
                      id={column.id}
                      scope="col"
                      style={column === columns.select ? { width: 40 } : undefined}
                    >
                      {column === columns.select
                        ? <span className="sr-only">{column.label}</span>
                        : column.label}
                    </th>
                  ))}
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
                        <td headers={columns.select.id} data-label={columns.select.label}>
                          <input
                            type="checkbox"
                            checked={!checkboxDisabled && Boolean(isSelected)}
                            disabled={checkboxDisabled}
                            onChange={() => toggleDeviceSelection(extId, loc.sensors, checkboxDisabled)}
                            title={checkboxDisabled ? i18n.t('devices:adminDeviceNewOpenAQ.text.alreadyExistsDatabase') : i18n.t('devices:adminDeviceNewOpenAQ.text.selectSensor')}
                          />
                        </td>
                        <td headers={columns.name.id} data-label={columns.name.label}>
                          <div className="cell-primary">{loc.device.name}</div>
                          <div className="cell-secondary mono"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.sensorId" />{' '}{extId}</div>
                          {(isExisting || sensorExists) && (
                            <span className="status-badge status-error badge-exists"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.alreadyExists" /></span>
                          )}
                        </td>
                        <td headers={columns.parameter.id} data-label={columns.parameter.label}>
                          <div className="cell-primary">
                            {sensor?.parameter_display || sensor?.parameter_code?.toUpperCase() || sensor?.name || '—'}
                          </div>
                          <div className="cell-secondary">{sensor?.unit || '—'}</div>
                        </td>
                        <td headers={columns.latestValue.id} data-label={columns.latestValue.label}>
                          {loc.metadata.latest_value !== null && loc.metadata.latest_value !== undefined ? (
                            <>
                              <div className="cell-primary">
                                {formatMeasurementValue(loc.metadata.latest_value)} {sensor?.unit || ''}
                              </div>
                              <div className="cell-secondary">
                                {formatDateTime(loc.metadata.latest_datetime_utc)}
                              </div>
                            </>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td headers={columns.coordinates.id} data-label={columns.coordinates.label} className="mono">
                          {loc.device.latitude?.toFixed(4) ?? '—'},<br />
                          {loc.device.longitude?.toFixed(4) ?? '—'}
                        </td>
                        <td headers={columns.dataRange.id} data-label={columns.dataRange.label}>
                          <div className="cell-secondary">
                            {formatDate(loc.metadata.datetime_first_utc)}
                          </div>
                          <div className="cell-secondary">
                            <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.to" />{formatDate(loc.metadata.datetime_last_utc)}
                          </div>
                        </td>
                        <td headers={columns.coverage.id} data-label={columns.coverage.label}>
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
                      <td headers={columns.select.id} data-label={columns.select.label}>
                        <input
                          type="checkbox"
                          checked={!rowDisabled && Boolean(selection[extId] && allSelectableSelected)}
                          disabled={rowDisabled}
                          onChange={() => toggleDeviceSelection(extId, loc.sensors, rowDisabled)}
                          title={rowDisabled ? i18n.t('devices:adminDeviceNewOpenAQ.text.alreadyExistsDatabaseNoSelectableSensors') : i18n.t('devices:adminDeviceNewOpenAQ.text.selectDeselectAllSensors')}
                        />
                      </td>
                      <td headers={columns.name.id} data-label={columns.name.label}>
                        <div className="cell-primary">{loc.device.name}</div>
                        <div className="cell-secondary mono"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.id" />{' '}{extId}</div>
                        {isExisting && (
                          <span className="status-badge status-error badge-exists"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.alreadyExists2" /></span>
                        )}
                      </td>
                      <td headers={columns.location.id} data-label={columns.location.label}>
                        <div>{loc.metadata.locality || '—'}</div>
                        <div className="cell-secondary">
                          {loc.metadata.country_name || loc.metadata.country_code || '—'}
                        </div>
                      </td>
                      <td headers={columns.provider.id} data-label={columns.provider.label}>
                        <div>{loc.metadata.provider_name || '—'}</div>
                        {loc.metadata.owner_name && (
                          <div className="cell-secondary">{loc.metadata.owner_name}</div>
                        )}
                      </td>
                      <td headers={columns.coordinates2.id} data-label={columns.coordinates2.label} className="mono">
                        {loc.device.latitude?.toFixed(4) ?? '—'},<br />
                        {loc.device.longitude?.toFixed(4) ?? '—'}
                      </td>
                      <td headers={columns.sensors.id} data-label={columns.sensors.label}>
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
                                  <span className="status-badge status-error badge-exists"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.alreadyExists3" /></span>
                                )}
                              </label>
                            );
                          })}
                        </div>
                      </td>
                      <td headers={columns.dataRange2.id} data-label={columns.dataRange2.label}>
                        <div className="cell-secondary">
                          {formatDate(loc.metadata.datetime_first_utc)}
                        </div>
                        <div className="cell-secondary">
                          <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.to2" />{formatDate(loc.metadata.datetime_last_utc)}
                        </div>
                      </td>
                      <td headers={columns.type.id} data-label={columns.type.label}>
                        <div className="type-badges">
                          {loc.metadata.is_monitor && (
                            <span className="badge badge-monitor"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.monitor" /></span>
                          )}
                          {loc.metadata.is_mobile && (
                            <span className="badge badge-mobile"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.mobile" /></span>
                          )}
                          {!loc.metadata.is_monitor && !loc.metadata.is_mobile && (
                            <span className="badge"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.sensor2" /></span>
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
                {selectedDevices} {' '}<Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.device" />{selectedDevices !== 1 ? 's' : ''},{' '}
                {selectedSensors} {' '}<Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.sensor3" />{selectedSensors !== 1 ? 's' : ''} <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.selected" /></span>
            ) : (
              <span className="muted"><Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.noDevicesSelected" /></span>
            )}
          </div>
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
              disabled={saving || selectedDevices === 0}
            >
              {saving
                ? i18n.t('devices:adminDeviceNewOpenAQ.actions.saving')
                : i18n.t('devices:adminDeviceNewOpenAQ.actions.saveSelected', { count: selectedDevices })}
            </button>
          </div>
        </div>
      </div>
    );
  };

  
  const renderConfirmDialog = () => {
    if (!showConfirm) return null;

    return (
      <AdminDialog title={i18n.t('devices:adminDeviceNewOpenAQ.headings.confirmApiRequest')} onClose={() => setShowConfirm(false)}>
          <p>
            <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.willMakeRequestOpenAqApi" /></p>
          <p className="muted" style={{ marginTop: 8 }}>
            <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.text.openAqHasRateLimitsIf" /></p>
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
              <Trans ns="devices" i18nKey="adminDeviceNewOpenAQ.actions.proceed" /></button>
          </div>
      </AdminDialog>
    );
  };

  return (
    <AdminPageLayout
      title={i18n.t('devices:adminDeviceNewOpenAQ.tooltips.addOpenAqSensor')}
      breadcrumbs={[
        { label: i18n.t('devices:adminDeviceNewOpenAQ.content.admin'), to: '/admin' },
        { label: i18n.t('devices:adminDeviceNewOpenAQ.content.devices'), to: '/admin/devices' },
        { label: i18n.t('devices:adminDeviceNewOpenAQ.content.addOpenAqSensor') },
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
        {renderLookupForm()}
        {renderResults()}
      </div>

      {renderConfirmDialog()}
    </AdminPageLayout>
  );
}
