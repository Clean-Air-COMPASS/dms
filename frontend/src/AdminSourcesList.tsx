import { formatOperationalTimestamp } from './utils/timezone';
import { Trans } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { deleteExternalAPI, listExternalAPIs } from './api';
import type { ExternalAPI } from './api';
import AdminPageLayout from './components/AdminPageLayout';
import { formatJobRunStatus } from './jobRunPresentation';

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
      } catch {
        setErr(i18n.t('common:errors.loadDataSources'));
      } finally {
        setLoading(false);
      }
    })();
  }, [location.search]);

  const handleDelete = async (api: ExternalAPI) => {
    if (!api.external_api_id || !api.can_delete) return;
    if (!confirm(i18n.t('dataSources:adminSourcesList.dialogs.deleteDataSource', { name: api.name }))) return;
    setDeletingId(api.external_api_id);
    setErr(null);
    try {
      await deleteExternalAPI(api.external_api_id);
      setApis((prev) => prev.filter((item) => item.external_api_id !== api.external_api_id));
    } catch {
      setErr(i18n.t('common:errors.deleteDataSource'));
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <AdminPageLayout
      title={i18n.t('dataSources:adminSourcesList.tooltips.dataSources')}
      description={i18n.t('dataSources:adminSourcesList.accessibility.configureExternalDataSources')}
      breadcrumbs={[
        { label: i18n.t('dataSources:adminSourcesList.content.admin'), to: '/admin' },
        { label: i18n.t('dataSources:adminSourcesList.content.dataSources') },
      ]}
      contentClassName="admin-workspace sources-admin-page"
    >
      {loading && <div className="info-banner" role="status"><Trans ns="common" i18nKey="states.loading" /></div>}
      {err && <div className="error-banner" role="alert">{err}</div>}
      {!loading && !err && (
        <div className="card table-card">
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th><Trans ns="dataSources" i18nKey="adminSourcesList.columns.dataSource" /></th>
                  <th><Trans ns="dataSources" i18nKey="adminSourcesList.columns.enabled" /></th>
                  <th><Trans ns="dataSources" i18nKey="adminSourcesList.columns.devices" /></th>
                  <th><Trans ns="dataSources" i18nKey="adminSourcesList.columns.lastImport" /></th>
                  <th><Trans ns="common" i18nKey="fields.status" /></th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {apis.map(a => (
                  <tr key={a.external_api_id}>
                    <td data-label={i18n.t('dataSources:adminSourcesList.columns.dataSource')}>
                      <Link to={`/admin/sources/${a.external_api_id}`} className="device-link" aria-label={i18n.t('dataSources:adminSourcesList.accessibility.openDataSource', { name: a.name })}>
                        {a.name}
                      </Link>
                      {a.provider_code === 'demo' && <p className="source-demo-help">{i18n.t('dataSources:demo.listDescription')}</p>}
                      {a.provider_code === 'demo' && <p className="source-demo-help">{i18n.t('dataSources:demo.disableHelp')}</p>}
                    </td>
                    <td data-label={i18n.t('dataSources:adminSourcesList.columns.enabled')}>
                      <div className="source-state-stack">
                        <span className={`status-badge ${a.enabled ? 'active' : 'disabled'}`}>{i18n.t(a.enabled ? 'admin:workspace.enabled' : 'admin:workspace.disabled')}</span>
                        <span>{i18n.t(`admin:workspace.sourceState.${a.runnable_reason ?? 'unknown'}`)}</span>
                        <span>{i18n.t(a.requires_credential === false ? 'dataSources:credentialFree' : a.has_api_key === undefined ? 'admin:workspace.credentialUnknown' : a.has_api_key ? 'admin:workspace.credentialStored' : 'admin:workspace.credentialMissing')}</span>
                      </div>
                    </td>
                    <td data-label={i18n.t('dataSources:adminSourcesList.columns.devices')}>{a.device_count ?? 0}</td>
                    <td data-label={i18n.t('dataSources:adminSourcesList.columns.lastImport')} className="source-last-import">
                      {a.latest_import?.started_at
                        ? formatOperationalTimestamp(a.latest_import.started_at)
                        : '—'}
                    </td>
                    <td data-label={i18n.t('common:fields.status')} className={`source-run-status source-run-status-${a.latest_import?.status ?? 'never'}`}>
                      {formatJobRunStatus(a.latest_import?.status)}
                    </td>
                    <td style={{whiteSpace:'nowrap'}}>
                      {a.can_delete && (
                        <button
                          type="button"
                          className="btn btn-danger small"
                          onClick={() => void handleDelete(a)}
                          disabled={deletingId === a.external_api_id}
                        >
                          {deletingId === a.external_api_id ? i18n.t('dataSources:adminSourcesList.actions.deleting') : i18n.t('common:actions.delete')}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {apis.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted"><Trans ns="dataSources" i18nKey="adminSourcesList.text.noDataSourcesConfigured" /></td>
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
