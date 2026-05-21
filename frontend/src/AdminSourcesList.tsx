import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { deleteExternalAPI, listExternalAPIs } from './api';
import type { ExternalAPI } from './api';
import AdminPageLayout from './components/AdminPageLayout';

export default function AdminSourcesList() {
  const [apis, setApis] = useState<ExternalAPI[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const location = useLocation();

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const shouldBypassCache = /(?:^|[?&])(fresh|refresh)=/i.test(location.search || '');
        const items = await listExternalAPIs(shouldBypassCache ? { skipCache: true } : undefined);
        setApis(items || []);
      } catch (e:any) {
        setErr(String(e?.message || e));
      } finally {
        setLoading(false);
      }
    })();
  // Re-run when the URL search changes so we can pick up a forced refresh
  }, [location.search]);

  const handleDelete = async (api: ExternalAPI) => {
    if (!api.external_api_id || (api.device_count ?? 0) > 0) return;
    if (!confirm(`Delete data source "${api.name}"?`)) return;
    setDeletingId(api.external_api_id);
    setErr(null);
    try {
      await deleteExternalAPI(api.external_api_id);
      setApis((prev) => prev.filter((item) => item.external_api_id !== api.external_api_id));
    } catch (e:any) {
      setErr(String(e?.message || e));
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <AdminPageLayout
      title="Data Sources"
      description="Configure external data sources."
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'Data Sources' },
      ]}
      contentClassName="sources-admin-page"
    >
      {loading && <div className="info-banner">Loading…</div>}
      {err && <div className="error-banner">{err}</div>}
      {!loading && !err && (
        <div className="card table-card">
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Devices</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {apis.map(a => (
                  <tr key={a.external_api_id}>
                    <td>
                      <Link to={`/admin/sources/${a.external_api_id}`} className="device-link" aria-label={`Open ${a.name} view`}>
                        {a.name}
                      </Link></td>
                    <td>{a.is_active === false ? 'Inactive' : 'Active'}</td>
                    <td>{a.device_count ?? 0}</td>
                    <td style={{whiteSpace:'nowrap'}}>
                      {(a.device_count ?? 0) === 0 && (
                        <button
                          type="button"
                          className="btn btn-danger small"
                          onClick={() => void handleDelete(a)}
                          disabled={deletingId === a.external_api_id}
                        >
                          {deletingId === a.external_api_id ? 'Deleting…' : 'Delete'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {apis.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted">No data sources configured.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </AdminPageLayout>
  );
}
