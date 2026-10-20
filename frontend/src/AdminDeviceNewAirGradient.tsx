import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { addAirGradientLocation, listAirGradientLocations, type AirGradientLocation } from './api';
import { ApiError } from './apiError';
import AdminPageLayout from './components/AdminPageLayout';
import './AdminDeviceNewAirGradient.css';

export default function AdminDeviceNewAirGradient() {
  const { t } = useTranslation('devices');
  const navigate = useNavigate();
  const [locations, setLocations] = useState<AirGradientLocation[]>([]);
  const [automaticImports, setAutomaticImports] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<AirGradientLocation | null>(null);
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<Awaited<ReturnType<typeof addAirGradientLocation>> | null>(null);

  const errorCode = (caught: unknown) => caught instanceof ApiError && caught.errorCode
    ? caught.errorCode : 'operation_failed';

  useEffect(() => {
    let cancelled = false;
    listAirGradientLocations().then(response => {
      if (cancelled) return;
      setLocations(response.locations);
      setAutomaticImports(response.automatic_imports_enabled);
    }).catch(caught => {
      if (!cancelled) setError(errorCode(caught));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [attempt]);

  const retry = () => {
    setError(null);
    setSelected(null);
    setLocations([]);
    setLoading(true);
    setAttempt(value => value + 1);
  };

  const add = async () => {
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      const response = await addAirGradientLocation(selected.location_id);
      if (response.already_exists) {
        setResult(response);
      } else {
        navigate(`/admin/devices/${response.device_id}/edit`, {
          state: { airgradientNoReadings: response.measurements_imported === 0 },
        });
      }
    } catch (caught) {
      setError(errorCode(caught));
    } finally { setSaving(false); }
  };

  const context = (location: AirGradientLocation) => (
    <>
      <span>{t('airgradient.locationId', { id: location.location_id })}</span>
      {location.latitude !== null && location.longitude !== null &&
        <span>{t('airgradient.coordinates', { latitude: location.latitude, longitude: location.longitude })}</span>}
      {location.timezone && <span>{location.timezone}</span>}
    </>
  );

  return <AdminPageLayout title={t('airgradient.title')}
    breadcrumbs={[
      { label: t('adminDeviceNew.content.admin'), to: '/admin' },
      { label: t('adminDeviceNew.content.devices'), to: '/admin/devices' },
      { label: t('adminDeviceNew.headings.selectDataSource'), to: '/admin/devices/new' },
      { label: 'AirGradient' },
    ]}
    actions={<Link className="btn btn-secondary" to="/admin/devices/new">{t('airgradient.back')}</Link>}
    contentClassName="admin-workspace device-editor-page">
    <div className="device-new-flow airgradient-add">
      <section className="card" aria-busy={loading || saving}>
        <h2>{t('airgradient.select')}</h2>
        <p className="muted">{t('airgradient.description')}</p>
        {loading && <p role="status" className="info-banner">{t('airgradient.loading')}</p>}
        {error && <div role="alert" className="error-banner">
          <p>{t(`airgradient.errors.${error}`, { defaultValue: t('airgradient.errors.operation_failed') })}</p>
          <div className="actions">
            <button className="btn btn-secondary" onClick={retry} disabled={saving}>{t('airgradient.retry')}</button>
            <Link to="/admin/sources">{t('airgradient.configure')}</Link>
          </div>
        </div>}
        {!loading && !error && locations.length === 0 && <div className="info-banner" role="status">
          <p>{t('airgradient.empty')}</p>
          <button className="btn btn-secondary" onClick={retry}>{t('airgradient.retry')}</button>
        </div>}
        {!loading && locations.length > 0 && <fieldset className="airgradient-locations" disabled={saving || result !== null}>
          <legend className="sr-only">{t('airgradient.select')}</legend>
          {locations.map(location => <label className={`airgradient-location ${selected?.location_id === location.location_id ? 'selected' : ''}`} key={location.location_id}>
            <input type="radio" name="airgradient-location" value={location.location_id}
              checked={selected?.location_id === location.location_id}
              onChange={() => { setSelected(location); setError(null); }} />
            <span className="airgradient-location-text">
              <strong>{location.name}</strong>
              {context(location)}
              {location.existing_device_id !== null && <span>{t('airgradient.alreadyAdded')}</span>}
            </span>
          </label>)}
        </fieldset>}
      </section>
      {selected && <section className="card" aria-labelledby="airgradient-preview">
        <h2 id="airgradient-preview">{t('airgradient.preview')}</h2>
        <div className="airgradient-location-text airgradient-preview-summary"><strong>{selected.name}</strong>{context(selected)}</div>
        {selected.existing_device_id !== null || result?.already_exists ? <div className="info-banner" role="status">
          <p>{t('airgradient.duplicate')}</p>
          <Link className="btn btn-primary" to={`/admin/devices/${result?.device_id ?? selected.existing_device_id}/edit`}>{t('airgradient.viewDevice')}</Link>
        </div> : <>
          <p>{t('airgradient.importNow')}</p>
          {!automaticImports && <p className="info-banner">{t('airgradient.automaticOff')}</p>}
          <div className="form-actions"><button type="button" className="btn btn-primary" disabled={saving} onClick={add}>
            {t(saving ? 'airgradient.adding' : 'airgradient.add')}
          </button></div>
        </>}
      </section>}
    </div>
  </AdminPageLayout>;
}
