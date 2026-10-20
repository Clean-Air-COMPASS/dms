import { formatOperationalTimestamp } from './utils/timezone';
import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { listDevicesAdmin, listExternalAPIs, type DeviceOperationalStatus, type DeviceRecord, type ExternalAPI } from './api';
import AdminPageLayout from './components/AdminPageLayout';

type Filters = {
  name: string;
  status: DeviceOperationalStatus | '';
  network: string;
  sensor_id: string;
  external_device_id: string;
  external_sensor_id: string;
};

type SortKey = 'name' | 'source_name' | 'network' | 'status' | 'last_seen_at' | 'created_at';
type SortDir = 'asc' | 'desc';
const OTHER_DATA_SOURCE_VALUE = '__other__';

function operationalStatusFilter(value: string | null): DeviceOperationalStatus | '' {
  if (value === 'active' || value === 'inactive' || value === 'unknown') return value;
  return '';
}

function statusLabel(status: DeviceOperationalStatus): string {
  return i18n.t(`devices:adminDevicesList.options.${status}`);
}

function statusBadgeClass(status: DeviceOperationalStatus): string {
  if (status === 'active') return 'status-badge active';
  if (status === 'inactive') return 'status-badge disabled';
  return 'status-badge status-unknown';
}

function formatDate(val?: string | null): string {
  if (!val) return '—';
  try {
    return formatOperationalTimestamp(val);
  } catch {
    return val;
  }
}

export default function AdminDevicesList() {
  const navigate = useNavigate();
  const location = useLocation();
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [sources, setSources] = useState<ExternalAPI[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>({ name: '', status: '', network: '', sensor_id: '', external_device_id: '', external_sensor_id: '' });
  const [page, setPage] = useState<number>(0);
  const [pageSize, setPageSize] = useState<number>(20);
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    setFilters({
      name: params.get('name') || '',
      status: operationalStatusFilter(params.get('status')),
      network: params.get('network') || '',
      sensor_id: params.get('sensor_id') || '',
      external_device_id: params.get('external_device_id') || '',
      external_sensor_id: params.get('external_sensor_id') || '',
    });
    setPage(0);
  }, [location.search]);

  useEffect(() => {
    const savedScroll = sessionStorage.getItem('admin-devices-scroll');
    if (savedScroll) {
      requestAnimationFrame(() => {
        window.scrollTo(0, Number(savedScroll));
      });
    }
    return () => {
      sessionStorage.setItem('admin-devices-scroll', String(window.scrollY));
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await listExternalAPIs({ skipCache: false });
        if (!cancelled) setSources(list || []);
      } catch {
        // ignore listing errors; dropdown will just show "All"
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const list = await listDevicesAdmin({
          name: filters.name || undefined,
          status: filters.status || undefined,
          network: filters.network || undefined,
          sensor_id: filters.sensor_id.trim() ? Number(filters.sensor_id) : undefined,
          external_device_id: filters.external_device_id || undefined,
          external_sensor_id: filters.external_sensor_id || undefined,
        });
        if (!cancelled) setDevices(list || []);
      } catch {
        if (!cancelled) setError(i18n.t('common:errors.loadDevices'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filters.name, filters.status, filters.network, filters.sensor_id, filters.external_device_id, filters.external_sensor_id]);

  const filtered = useMemo(() => {
    const rows = [...devices];
    const dir = sortDir === 'asc' ? 1 : -1;
    const text = (v?: string | null) => (v || '').toString().toLowerCase();
    const ts = (v?: string | null) => {
      if (!v) return -Infinity;
      const n = Date.parse(v);
      return Number.isFinite(n) ? n : -Infinity;
    };

    rows.sort((a, b) => {
      let comparison: number;
      switch (sortKey) {
        case 'name':
          comparison = text(a.friendly_name?.trim() || a.name).localeCompare(text(b.friendly_name?.trim() || b.name)) * dir;
          break;
        case 'source_name':
          comparison = text(a.name).localeCompare(text(b.name)) * dir;
          break;
        case 'network':
          comparison = text(a.network || a.external_api_name).localeCompare(text(b.network || b.external_api_name)) * dir;
          break;
        case 'status':
          comparison = text(a.status).localeCompare(text(b.status)) * dir;
          break;
        case 'last_seen_at':
          comparison = (ts(a.last_seen_at) - ts(b.last_seen_at)) * dir;
          break;
        case 'created_at':
        default:
          comparison = (ts(a.created_at) - ts(b.created_at)) * dir;
          break;
      }
      return comparison || a.device_id - b.device_id;
    });
    return rows;
  }, [devices, sortDir, sortKey]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageSafe = Math.min(page, pageCount - 1);
  const slice = filtered.slice(pageSafe * pageSize, pageSafe * pageSize + pageSize);

  const onChangeFilter = (key: keyof Filters, value: string) => {
    setPage(0);
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const onSort = (key: SortKey) => {
    setPage(0);
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortKey(key);
    setSortDir('asc');
  };

  const sortMark = (key: SortKey) => (sortKey !== key ? '' : sortDir === 'asc' ? ' ▲' : ' ▼');

  return (
    <AdminPageLayout
      title={i18n.t('devices:adminDevicesList.tooltips.devices')}
      description={i18n.t('devices:adminDevicesList.accessibility.manageDevicesThatProvideMeasurements')}
      breadcrumbs={[
        { label: i18n.t('devices:adminDevicesList.content.admin'), to: '/admin' },
        { label: i18n.t('devices:adminDevicesList.content.devices') },
      ]}
      actions={
        <button className="btn btn-primary" onClick={() => navigate('/admin/devices/new')}><Trans ns="devices" i18nKey="adminDevicesList.actions.newDevice" /></button>
      }
      contentClassName="admin-workspace devices-admin-page"
    >

      <div className="card filters-card">
        <div className="filters-grid">
          <label className="field">
            <span><Trans ns="common" i18nKey="fields.name" /></span>
            <input value={filters.name} onChange={(e) => onChangeFilter('name', e.target.value)} placeholder={i18n.t('devices:adminDevicesList.placeholders.searchName')} />
          </label>
          <label className="field">
            <span><Trans ns="common" i18nKey="fields.status" /></span>
            <select value={filters.status} onChange={(e) => onChangeFilter('status', e.target.value)}>
              <option value=""><Trans ns="devices" i18nKey="adminDevicesList.options.any" /></option>
              <option value="active"><Trans ns="devices" i18nKey="adminDevicesList.options.active" /></option>
              <option value="inactive"><Trans ns="devices" i18nKey="adminDevicesList.options.inactive" /></option>
              <option value="unknown"><Trans ns="devices" i18nKey="adminDevicesList.options.unknown" /></option>
            </select>
          </label>
          <label className="field">
            <span><Trans ns="devices" i18nKey="adminDevicesList.text.dataSource" /></span>
            <select
              value={filters.network}
              onChange={(e) => onChangeFilter('network', e.target.value)}
              className="select-input"
            >
              <option value=""><Trans ns="devices" i18nKey="adminDevicesList.options.all" /></option>
              {sources.map((s) => (
                <option key={s.external_api_id} value={s.name}>{s.name}</option>
              ))}
              <option value={OTHER_DATA_SOURCE_VALUE}><Trans ns="devices" i18nKey="adminDevicesList.options.other" /></option>
            </select>
          </label>
          <div className="field actions">
            <button className="btn ghost" onClick={() => { setFilters({ name: '', status: '', network: '', sensor_id: '', external_device_id: '', external_sensor_id: '' }); setPage(0); }}><Trans ns="common" i18nKey="actions.reset" /></button>
          </div>
        </div>
        <details className="device-identifier-filters" open={Boolean(filters.sensor_id || filters.external_device_id || filters.external_sensor_id) || undefined}>
          <summary>{i18n.t('admin:workspace.identifierFilters')}</summary>
          <div className="filters-grid">
          <label className="field">
            <span><Trans ns="devices" i18nKey="adminDevicesList.text.externalDeviceId" /></span>
            <input value={filters.external_device_id} onChange={(e) => onChangeFilter('external_device_id', e.target.value)} placeholder="12345" />
          </label>
          <label className="field">
            <span><Trans ns="devices" i18nKey="adminDevicesList.text.sensorId" /></span>
            <input value={filters.sensor_id} onChange={(e) => onChangeFilter('sensor_id', e.target.value)} placeholder="5678" />
          </label>
          <label className="field">
            <span><Trans ns="devices" i18nKey="adminDevicesList.text.externalSensorId" /></span>
            <input value={filters.external_sensor_id} onChange={(e) => onChangeFilter('external_sensor_id', e.target.value)} placeholder={i18n.t('devices:adminDevicesList.placeholders.eGSensor5678')} />
          </label>
          </div>
        </details>

      </div>

      {loading && <div className="info-banner" role="status"><Trans ns="devices" i18nKey="adminDevicesList.text.loadingDevices" /></div>}
      {error && <div className="error-banner" role="alert">{error}</div>}

      <div className="card table-card">
        <div className="table-responsive">
          <table className="admin-table">
            <thead>
              <tr>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('name')}><Trans ns="common" i18nKey="fields.name" />{sortMark('name')}</button></th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('source_name')}><Trans ns="devices" i18nKey="adminDevicesList.actions.sourceName" />{sortMark('source_name')}</button></th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('network')}><Trans ns="devices" i18nKey="adminDevicesList.actions.dataSource" />{sortMark('network')}</button></th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('status')}><Trans ns="common" i18nKey="fields.status" />{sortMark('status')}</button></th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('last_seen_at')}><Trans ns="devices" i18nKey="adminDevicesList.actions.lastSeen" />{sortMark('last_seen_at')}</button></th>
                <th><Trans ns="devices" i18nKey="adminDevicesList.columns.location" /></th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('created_at')}><Trans ns="devices" i18nKey="adminDevicesList.actions.created" />{sortMark('created_at')}</button></th>
              </tr>
            </thead>
            <tbody>
              {slice.map((d) => {
                
                const displayName = d.friendly_name?.trim() || d.name || '—';
                const isExternal = d.is_external ?? !!d.external_id;
                return (
                <tr key={d.device_id}>
                  <td data-label={i18n.t('common:fields.name')}>
                    <div className="stacked">
                      <Link to={`/admin/devices/${d.device_id}/edit`} className="device-link" aria-label={i18n.t('devices:adminDevicesList.accessibility.openDevice', { name: displayName })}>
                        <strong>{displayName}</strong>
                      </Link>
                      {d.external_id ? <span className="muted small"><Trans ns="devices" i18nKey="adminDevicesList.text.id" />{' '}{d.external_id}</span> : null}
                    </div>
                  </td>
                  <td data-label={i18n.t('devices:adminDevicesList.actions.sourceName')}>
                    <div className="stacked">
                      <span>{d.name || '—'}</span>
                      <span className="badge-external-small">{i18n.t(isExternal ? 'devices:adminDeviceEditor.workflow.providerDevice' : 'devices:adminDeviceEditor.workflow.manualDevice')}</span>
                    </div>
                  </td>
                  <td data-label={i18n.t('devices:adminDevicesList.actions.dataSource')}>{d.network || d.external_api_name || '—'}</td>
                  <td data-label={i18n.t('common:fields.status')}><span className={statusBadgeClass(d.status)}>{statusLabel(d.status)}</span></td>
                  <td data-label={i18n.t('devices:adminDevicesList.actions.lastSeen')}>{formatDate(d.last_seen_at)}</td>
                  <td data-label={i18n.t('devices:adminDevicesList.columns.location')}>{(d.latitude !== null && d.latitude !== undefined) && (d.longitude !== null && d.longitude !== undefined) ? `${d.latitude.toFixed(4)}, ${d.longitude.toFixed(4)}` : '—'}</td>
                  <td data-label={i18n.t('devices:adminDevicesList.actions.created')}>{formatDate(d.created_at)}</td>
                </tr>
                );
              })}
              {!slice.length && !loading && (
                <tr>
                  <td colSpan={7} className="muted"><Trans ns="devices" i18nKey="adminDevicesList.text.noDevicesFound" /></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="table-footer">
          <div className="pagination">
            <button className="btn small" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={pageSafe <= 0}><Trans ns="devices" i18nKey="adminDevicesList.actions.prev" /></button>
            <span className="muted"><Trans ns="devices" i18nKey="adminDevicesList.text.page" />{' '}{pageSafe + 1} {' '}<Trans ns="devices" i18nKey="adminDevicesList.text.of" />{' '}{pageCount}</span>
            <button className="btn small" onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))} disabled={pageSafe >= pageCount - 1}><Trans ns="common" i18nKey="actions.next" /></button>
          </div>
          <label className="field inline">
            <span><Trans ns="devices" i18nKey="adminDevicesList.text.rows" /></span>
            <select value={pageSize} onChange={(e) => { setPage(0); setPageSize(Number(e.target.value)); }}>
              {[10, 20, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
      </div>
    </AdminPageLayout>
  );
}
