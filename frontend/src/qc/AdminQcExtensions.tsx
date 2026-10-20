import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import AdminPageLayout from '../components/AdminPageLayout';
import { getQcPlugins } from './api';
import { checkDescription, checkName } from './presentation';
import type { QcPluginInfo, QcPluginsResponse } from './types';

export default function AdminQcExtensions() {
  const { t } = useTranslation('qualityControl');
  const [response, setResponse] = useState<QcPluginsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(false);
    try {
      setResponse(await getQcPlugins());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const issues = [...(response?.discovery.rejected ?? []), ...(response?.discovery.failed ?? [])];
  const unavailableChecks = response?.unavailable_checks ?? [];
  const originLabel = (plugin: QcPluginInfo) => {
    if (plugin.origin === 'entry_point') return t('extensions.origins.installedPackage');
    if (plugin.origin === 'runtime') return t('extensions.origins.runtime');
    return t('extensions.origins.builtIn');
  };
  const accessLabel = (plugin: QcPluginInfo) => {
    if (plugin.required_access === 'db-read') return t('extensions.accessLevels.databaseRead');
    if (plugin.required_access === 'db-write') return t('extensions.accessLevels.databaseWrite');
    return t('extensions.accessLevels.policyOnly');
  };
  return (
    <AdminPageLayout
      title={t('extensions.title')}
      description={t('extensions.description')}
      breadcrumbs={[
        { label: t('breadcrumbs.admin'), to: '/admin' },
        { label: t('breadcrumbs.qualityControl'), to: '/admin/qc' },
        { label: t('extensions.title') },
      ]}
      actions={<button className="btn" type="button" onClick={() => void load()}>{t('actions.refresh')}</button>}
      contentClassName="qc-admin-page qc-extensions-page"
    >
      <div className="info-banner">{t('extensions.deploymentOwned')}</div>
      {loading && <div className="info-banner">{t('extensions.loading')}</div>}
      {error && <div className="error-banner qc-state-banner"><span>{t('extensions.loadError')}</span><button className="btn" onClick={() => void load()}>{t('actions.retry')}</button></div>}
      {response && (
        <>
          <section className="card">
            <div className="qc-section-heading"><div><h2>{t('extensions.installedTitle')}</h2><p>{t('extensions.installedDescription')}</p></div></div>
            <div className="qc-extension-list">
              {response.plugins.map((plugin) => (
                <article className="qc-extension-card" key={plugin.name}>
                  <div>
                    <h3>{checkName(plugin.name, {
                      display_name: plugin.display_name || plugin.name,
                      description: plugin.description || plugin.long_description || '',
                    })}</h3>
                    <p>{checkDescription(plugin.name, {
                      display_name: plugin.display_name || plugin.name,
                      description: plugin.description || plugin.long_description || '',
                    })}</p>
                  </div>
                  <dl>
                    <div><dt>{t('extensions.origin')}</dt><dd>{originLabel(plugin)}</dd></div>
                    <div><dt>{t('extensions.access')}</dt><dd>{accessLabel(plugin)}</dd></div>
                    <div><dt>{t('extensions.version')}</dt><dd>{plugin.version || '—'}</dd></div>
                    <div><dt>{t('extensions.rules')}</dt><dd>{plugin.rules_count}</dd></div>
                  </dl>
                </article>
              ))}
            </div>
          </section>
          <section className="card">
            <div className="qc-section-heading"><div><h2>{t('extensions.diagnosticsTitle')}</h2><p>{t('extensions.diagnosticsDescription')}</p></div></div>
            {issues.length === 0 && unavailableChecks.length === 0 ? <div className="success-banner">{t('extensions.noIssues')}</div> : (
              <div className="qc-diagnostic-list">
                {unavailableChecks.map((check) => (
                  <article className="warning-banner" key={check.check_code}>
                    <strong>{t('extensions.unavailableCheckTitle', {
                      check: checkName(check.check_code, {
                        display_name: check.display_name,
                        description: '',
                      }),
                    })}</strong>
                    <span>{t('extensions.unavailableCheckDescription', {
                      count: check.configured_rule_count,
                    })}</span>
                    <code>{check.reason_code}</code>
                  </article>
                ))}
                {issues.map((issue, index) => (
                  <article className="warning-banner" key={`${issue.reason_code}-${index}`}>
                    <strong>{issue.reason_code}</strong>
                    <span>{issue.message}</span>
                    {issue.entrypoint && <code>{issue.entrypoint}</code>}
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </AdminPageLayout>
  );
}
