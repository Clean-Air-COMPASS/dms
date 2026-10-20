import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { listDevicesAdmin, listDeviceSensors, type DeviceRecord, type DeviceSensorSummary } from '../api';

const DEVICE_REFERENCE_PAGE_SIZE = 20;
const FIRST_DEVICE_REFERENCE_PAGE = 0;

export default function CsvSensorReference() {
  const { t } = useTranslation(['admin', 'common']);
  const [query, setQuery] = useState('');
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [device, setDevice] = useState<DeviceRecord | null>(null);
  const [sensors, setSensors] = useState<DeviceSensorSummary[]>([]);
  const [page, setPage] = useState(FIRST_DEVICE_REFERENCE_PAGE);
  const [hasNextPage, setHasNextPage] = useState(false);
  const [reachedEndOfResults, setReachedEndOfResults] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    const timer = window.setTimeout(() => {
      const request = device
        ? listDeviceSensors(device.device_id).then(rows => { if (!cancelled) setSensors(rows); })
        : listDevicesAdmin({ search: query.trim(), page, page_size: DEVICE_REFERENCE_PAGE_SIZE }).then(rows => {
          if (cancelled) return;

          // The endpoint does not return a total. If an exact multiple of the
          // page size is followed by an empty page, stay on the last page
          // instead of presenting that boundary as a genuine empty search.
          if (page > FIRST_DEVICE_REFERENCE_PAGE && rows.length === 0) {
            setReachedEndOfResults(true);
            setHasNextPage(false);
            setPage(currentPage => Math.max(FIRST_DEVICE_REFERENCE_PAGE, currentPage - 1));
            return;
          }

          setDevices(rows);
          setHasNextPage(!reachedEndOfResults && rows.length === DEVICE_REFERENCE_PAGE_SIZE);
        });
      void request.catch(() => { if (!cancelled) setError(true); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [query, device, page, reachedEndOfResults, retry]);

  return <section className="card">
    <h2>{t('adminCsvUpload.reference.title')}</h2>
    <p>{t('adminCsvUpload.reference.help')}</p>
    <label className="form-field">
      <span>{t('adminCsvUpload.reference.search')}</span>
      <input className="text-input" type="search" value={query} onChange={event => {
        setQuery(event.target.value);
        setPage(FIRST_DEVICE_REFERENCE_PAGE);
        setHasNextPage(false);
        setReachedEndOfResults(false);
        setDevice(null);
        setSensors([]);
      }} />
    </label>
    {loading ? <p role="status">{t('common:states.loading')}</p> : error ? <div role="alert" className="error-banner">
      <p>{t('adminCsvUpload.reference.error')}</p>
      <button type="button" className="btn" onClick={() => setRetry(value => value + 1)}>{t('common:actions.retry')}</button>
    </div> : device ? <>
      <h3>{device.friendly_name || device.name}</h3>
      <p>{t('adminCsvUpload.reference.deviceId', { id: device.device_id })}</p>
      <p>{t('adminCsvUpload.reference.externalDeviceId', { id: device.external_id || t('common:states.unavailable') })}</p>
      <p>{t('adminCsvUpload.reference.dataSource', { source: device.network || device.external_api_name || t('common:states.unavailable') })}</p>
      <p>{t('adminCsvUpload.reference.timezone', { timezone: device.timezone || t('common:states.unavailable') })}</p>
      {sensors.length ? <ul className="space-y-3 my-3">{sensors.map(sensor => <li key={sensor.sensor_id}>
        <strong>{t('adminCsvUpload.reference.parameter', { parameter: sensor.parameter_name || sensor.parameter_code || sensor.parameter || t('common:states.unavailable') })}</strong>
        <div>{t('adminCsvUpload.reference.sensor', { id: sensor.sensor_id, unit: sensor.unit || sensor.unit_symbol || t('common:states.unavailable') })}</div>
        <div>{t('adminCsvUpload.reference.externalSensor', { id: sensor.external_sensor_id || t('common:states.unavailable') })}</div>
        <div>{t('adminCsvUpload.reference.aggregation', { aggregation: sensor.aggregation_code || t('common:states.unavailable') })}</div>
        <div>{t('adminCsvUpload.reference.timestamp', { semantics: t(`adminCsvUpload.reference.semantics.${sensor.measurement_timestamp_semantics || 'unknown'}`, { defaultValue: t('adminCsvUpload.reference.semantics.unknown') }) })}</div>
        <div>{t('adminCsvUpload.reference.duration', { seconds: sensor.measurement_duration_seconds ?? t('common:states.unavailable') })}</div>
        <div>{t('adminCsvUpload.reference.frequency', { seconds: sensor.expected_frequency_seconds ?? t('common:states.unavailable') })}</div>
      </li>)}</ul> : <p>{t('adminCsvUpload.reference.noSensors')}</p>}
      <div className="form-actions">
        <button type="button" className="btn" onClick={() => setDevice(null)}>{t('adminCsvUpload.reference.changeDevice')}</button>
        <Link className="btn" to={`/admin/devices/${device.device_id}/edit`}>{t('adminCsvUpload.reference.viewDevice')}</Link>
      </div>
    </> : <>
      {devices.length ? <ul className="space-y-2 my-3">{devices.map(item => <li key={item.device_id}>
        <button type="button" className="btn" onClick={() => { setLoading(true); setSensors([]); setDevice(item); }}>{item.friendly_name || item.name}</button>
      </li>)}</ul> : <p>{t('adminCsvUpload.reference.noDevices')}</p>}
      <p className="muted">{t('adminCsvUpload.reference.limit')}</p>
      <div className="pagination" aria-label={t('adminCsvUpload.reference.paginationLabel')}>
        <button
          type="button"
          className="btn small"
          onClick={() => setPage(currentPage => Math.max(FIRST_DEVICE_REFERENCE_PAGE, currentPage - 1))}
          disabled={loading || page <= FIRST_DEVICE_REFERENCE_PAGE}
        >
          {t('common:actions.previous')}
        </button>
        <span className="muted">{t('adminCsvUpload.reference.page', { page: page + 1 })}</span>
        <button
          type="button"
          className="btn small"
          onClick={() => setPage(currentPage => currentPage + 1)}
          disabled={loading || !hasNextPage}
        >
          {t('common:actions.next')}
        </button>
      </div>
    </>}
  </section>;
}
