import { useTranslation } from 'react-i18next';
import type { ExternalAPI } from './api';
import { sourceReadinessKey } from './sourceReadinessPresentation';

export type ScheduleState = 'loading' | 'unavailable' | 'none' | 'on' | 'off';

export default function SourceReadiness({ source, scheduleState }: { source: ExternalAPI; scheduleState: ScheduleState }) {
  const { t } = useTranslation('dataSources');
  const readiness = sourceReadinessKey(source);
  const deploymentCredential = source.requires_credential !== false && source.provider_code !== 'demo' && source.has_api_key === false && source.is_configured === true;
  const needsSetup = ['missingCredential', 'needsConfiguration', 'disabled'].includes(readiness);
  const automate = readiness === 'ready' && (source.provider_code === 'demo' || (source.latest_import?.status === 'success' && scheduleState !== 'on'));
  const target = needsSetup ? 'source-configuration' : automate ? 'source-schedule' : 'source-run-now';
  const action = needsSetup ? 'finishConfiguration' : automate ? 'configureSchedule' : 'runNow';
  return <section className="source-readiness card" aria-labelledby="source-readiness-heading">
    <div className="source-heading">
      <h2 id="source-readiness-heading">{t(`workflow.${readiness === 'missingCredential' ? 'needsConfiguration' : readiness}`)}</h2>
      <span className={`status-badge ${source.enabled ? 'active' : 'disabled'}`}>{t(source.enabled ? 'workflow.enabled' : 'workflow.disabled')}</span>
    </div>
    <div className="source-readiness-facts" role="status">
      {readiness === 'missingCredential' && <span>{t('workflow.missingCredential')}</span>}
      {source.requires_credential !== false && source.provider_code !== 'demo' && source.has_api_key === true && <span>{t('adminSourceForm.text.credentialStored')}</span>}
      {deploymentCredential && <span>{t('workflow.deploymentCredential')}</span>}
      {source.provider_code === 'demo' && <span>{t('workflow.demoAutomatic')}</span>}
      <span>{t(`workflow.schedule.${scheduleState}`)}</span>
    </div>
    {(needsSetup || readiness === 'ready') && <a className="btn btn-primary" href={`#${target}`} onClick={() => document.getElementById(target)?.focus()}>{t(`workflow.${action}`)}</a>}
  </section>;
}
