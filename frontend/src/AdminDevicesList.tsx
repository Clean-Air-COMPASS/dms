import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { listDevicesAdmin, listExternalAPIs, type DeviceRecord, type ExternalAPI } from './api';
import AdminPageLayout from './components/AdminPageLayout';

type Filters = {
  name: string;
  type: string;
  status: string;
  network: string;
  sensor_id: string;
  external_device_id: string;
  external_sensor_id: string;
};

type SortKey = 'name' | 'source_name' | 'network' | 'status' | 'last_seen_at' | 'created_at';
type SortDir = 'asc' | 'desc';
const OTHER_DATA_SOURCE_VALUE = '__other__';

function formatDate(val?: string | null): string {
  if (!val) return '—';
  try {
    return new Date(val).toLocaleString();
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
  const [filters, setFilters] = useState<Filters>({ name: '', type: '', status: '', network: '', sensor_id: '', external_device_id: '', external_sensor_id: '' });
  const [page, setPage] = useState<number>(0);
  const [pageSize, setPageSize] = useState<number>(20);
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    setFilters({
      name: params.get('name') || '',
      type: params.get('type') || '',
      status: params.get('status') || '',
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
          type: filters.type || undefined,
          status: filters.status || undefined,
          network: filters.network || undefined,
          sensor_id: filters.sensor_id.trim() ? Number(filters.sensor_id) : undefined,
          external_device_id: filters.external_device_id || undefined,
          external_sensor_id: filters.external_sensor_id || undefined,
        });
        if (!cancelled) setDevices(list || []);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Failed to load devices');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filters.name, filters.type, filters.status, filters.network, filters.sensor_id, filters.external_device_id, filters.external_sensor_id]);

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
      switch (sortKey) {
        case 'name':
          return text(a.friendly_name?.trim() || a.name).localeCompare(text(b.friendly_name?.trim() || b.name)) * dir;
        case 'source_name':
          return text(a.name).localeCompare(text(b.name)) * dir;
        case 'network':
          return text(a.network || a.external_api_name).localeCompare(text(b.network || b.external_api_name)) * dir;
        case 'status':
          return text(a.status).localeCompare(text(b.status)) * dir;
        case 'last_seen_at':
          return (ts(a.last_seen_at) - ts(b.last_seen_at)) * dir;
        case 'created_at':
        default:
          return (ts(a.created_at) - ts(b.created_at)) * dir;
      }
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
      title="Devices"
      description="Manage devices that provide measurements."
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'Devices' },
      ]}
      actions={
        <button className="btn btn-primary" onClick={() => navigate('/admin/devices/new')}>New Device</button>
      }
      contentClassName="devices-admin-page"
    >

      <div className="card filters-card">
        <div className="filters-grid">
          <label className="field">
            <span>Name</span>
            <input value={filters.name} onChange={(e) => onChangeFilter('name', e.target.value)} placeholder="Search name…" />
          </label>
          <label className="field">
            <span>Type</span>
            <input value={filters.type} onChange={(e) => onChangeFilter('type', e.target.value)} placeholder="e.g. PurpleAir" />
          </label>
          <label className="field">
            <span>Status</span>
            <select value={filters.status} onChange={(e) => onChangeFilter('status', e.target.value)}>
              <option value="">Any</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="error">Error</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
          <label className="field">
            <span>Data Source</span>
            <select
              value={filters.network}
              onChange={(e) => onChangeFilter('network', e.target.value)}
              className="select-input"
            >
              <option value="">All</option>
              {sources.map((s) => (
                <option key={s.external_api_id} value={s.name}>{s.name}</option>
              ))}
              <option value={OTHER_DATA_SOURCE_VALUE}>Other</option>
            </select>
          </label>
          <label className="field">
            <span>External Device ID</span>
            <input value={filters.external_device_id} onChange={(e) => onChangeFilter('external_device_id', e.target.value)} placeholder="e.g., 12345" />
          </label>
          <label className="field">
            <span>Sensor ID</span>
            <input value={filters.sensor_id} onChange={(e) => onChangeFilter('sensor_id', e.target.value)} placeholder="e.g., 5678" />
          </label>
          <label className="field">
            <span>External Sensor ID</span>
            <input value={filters.external_sensor_id} onChange={(e) => onChangeFilter('external_sensor_id', e.target.value)} placeholder="e.g., sensor-5678" />
          </label>
          <div className="field actions">
            <button className="btn ghost" onClick={() => { setFilters({ name: '', type: '', status: '', network: '', sensor_id: '', external_device_id: '', external_sensor_id: '' }); setPage(0); }}>Reset</button>
          </div>
        </div>
      </div>

      {loading && <div className="info-banner">Loading devices…</div>}
      {error && <div className="error-banner">{error}</div>}

      <div className="card table-card">
        <div className="table-responsive">
          <table className="admin-table">
            <thead>
              <tr>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('name')}>Name{sortMark('name')}</button></th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('source_name')}>Source Name{sortMark('source_name')}</button></th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('network')}>Data Source{sortMark('network')}</button></th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('status')}>Status{sortMark('status')}</button></th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('last_seen_at')}>Last seen{sortMark('last_seen_at')}</button></th>
                <th>Location</th>
                <th><button className="btn ghost small" type="button" onClick={() => onSort('created_at')}>Created{sortMark('created_at')}</button></th>
                <th />
              </tr>
            </thead>
            <tbody>
              {slice.map((d) => {
                
                const displayName = d.friendly_name?.trim() || d.name || '—';
                const isExternal = d.is_external ?? !!d.external_id;
                return (
                <tr key={d.device_id}>
                  <td>
                    <div className="stacked">
                      <Link to={`/admin/devices/${d.device_id}/edit`} className="device-link" aria-label={`Open ${displayName} view`}>
                        <strong>{displayName}</strong>
                      </Link>
                      {d.external_id ? <span className="muted small">ID: {d.external_id}</span> : null}
                    </div>
                  </td>
                  <td>
                    <div className="stacked">
                      <span>{d.name || '—'}</span>
                      {isExternal && <span className="badge-external-small">External</span>}
                    </div>
                  </td>
                  <td>{d.network || d.external_api_name || '—'}</td>
                  <td>{d.status || '—'}</td>
                  <td>{formatDate(d.last_seen_at)}</td>
                  <td>{(d.latitude !== null && d.latitude !== undefined) && (d.longitude !== null && d.longitude !== undefined) ? `${d.latitude.toFixed(4)}, ${d.longitude.toFixed(4)}` : '—'}</td>
                  <td>{formatDate(d.created_at)}</td>
                </tr>
                );
              })}
              {!slice.length && !loading && (
                <tr>
                  <td colSpan={8} className="muted">No devices found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="table-footer">
          <div className="pagination">
            <button className="btn small" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={pageSafe <= 0}>Prev</button>
            <span className="muted">Page {pageSafe + 1} of {pageCount}</span>
            <button className="btn small" onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))} disabled={pageSafe >= pageCount - 1}>Next</button>
          </div>
          <label className="field inline">
            <span>Rows</span>
            <select value={pageSize} onChange={(e) => { setPage(0); setPageSize(Number(e.target.value)); }}>
              {[10, 20, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
      </div>
    </AdminPageLayout>
  );
}
