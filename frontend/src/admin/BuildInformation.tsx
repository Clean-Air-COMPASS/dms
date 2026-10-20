import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { compareBuilds, frontendVersion, getBackendVersion, type BackendVersion } from '../buildIdentity';
import './BuildInformation.css';

export default function BuildInformation() {
  const { t } = useTranslation('admin');
  const [backend, setBackend] = useState<BackendVersion | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const load = useCallback(async () => {
    setBackend(null);
    setState('loading');
    try {
      setBackend(await getBackendVersion());
      setState('ready');
    } catch {
      setState('unavailable');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const unknown = t('buildInformation.unknown');
  const backendMissing = state === 'loading' ? t('buildInformation.loading') : t('buildInformation.unavailable');
  const timestamp = (value: string | null | undefined) => value ? `${value.replace('T', ' ').replace(/Z$/, '')} UTC` : unknown;
  const comparison = compareBuilds(frontendVersion.frontend, backend?.backend);
  const rows = [
    ['applicationVersion', t('buildInformation.applicationVersionValue', { version: frontendVersion.application_version })],
    ['frontendCommit', frontendVersion.frontend.commit_sha ?? unknown],
    ['backendCommit', backend ? backend.backend.commit_sha ?? unknown : backendMissing],
    ['frontendBuilt', timestamp(frontendVersion.frontend.build_time_utc)],
    ['backendBuilt', backend ? timestamp(backend.backend.build_time_utc) : backendMissing],
    ['environment', backend ? backend.environment ? t(`buildInformation.environments.${backend.environment}`) : unknown : backendMissing],
  ] as const;

  return (
    <section className="card admin-section build-information" aria-labelledby="build-information-heading">
      <h2 id="build-information-heading">{t('buildInformation.title')}</h2>
      <p className={comparison === 'different' ? 'error-message' : 'muted'} role="status">
        {t(`buildInformation.comparison.${comparison}`)}
      </p>
      <dl className="build-information-fields">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{t(`buildInformation.${label}`)}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {backend && backend.application_version !== frontendVersion.application_version && (
        <p className="muted">{t('buildInformation.backendVersion', { version: backend.application_version })}</p>
      )}
      {state === 'unavailable' && (
        <div className="error-message" role="alert">
          <p>{t('buildInformation.loadError')}</p>
          <button type="button" className="btn" onClick={() => void load()}>{t('buildInformation.retry')}</button>
        </div>
      )}
    </section>
  );
}
