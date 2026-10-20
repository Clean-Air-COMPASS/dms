import { Trans } from 'react-i18next';
import i18n from './i18n';
import { Link } from 'react-router-dom';
import type { ExternalAPI } from './api';
import { formatOperationalTimestamp } from './utils/timezone';
import { formatJobRunStatus, formatJobRunSummary } from './jobRunPresentation';

export default function SourceMonitoring({ selectedExternalAPI }: { selectedExternalAPI: ExternalAPI }) {
  const latestImport = selectedExternalAPI.latest_import;
  const isPurpleAirSource = selectedExternalAPI.name === 'PurpleAir';
  const isAirGradientSource = selectedExternalAPI.provider_code === 'airgradient' || selectedExternalAPI.name === 'AirGradient';
  return <section id="source-monitoring" className="source-monitoring" aria-labelledby="source-monitoring-heading">
    <h2 id="source-monitoring-heading">{i18n.t('dataSources:workflow.monitoring')}</h2>
      {selectedExternalAPI.external_api_id > 0 && (
        <div className="card source-devices-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <div>
              <div className="muted small" style={{ textTransform: 'uppercase', letterSpacing: '0.06em' }}><Trans ns="dataSources" i18nKey="adminSourceForm.text.associatedDevices" /></div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <strong className="source-device-count">{selectedExternalAPI.device_count ?? 0}</strong>
                <span className="muted">{(selectedExternalAPI.device_count ?? 0) === 1 ? i18n.t('dataSources:adminSourceForm.text.deviceLinkedSource') : i18n.t('dataSources:adminSourceForm.text.devicesLinkedSource')}</span>
              </div>
            </div>
            <Link
              to={`/admin/devices?network=${encodeURIComponent(selectedExternalAPI.name)}&fresh=${Date.now()}`}
              className="btn btn-secondary"
            >
              <Trans ns="dataSources" i18nKey="adminSourceForm.actions.viewDevices" /></Link>
          </div>
        </div>
      )}

      {selectedExternalAPI.external_api_id > 0 && (
        <section className="card source-operation-card" aria-labelledby="source-last-import-heading">
          <div>
            <h3 id="source-last-import-heading" className="source-operation-label">
              <Trans ns="dataSources" i18nKey="adminSourceForm.headings.lastImport" />
            </h3>
            {latestImport ? (
              <>
                <div className="source-operation-time">
                  {latestImport.started_at ? formatOperationalTimestamp(latestImport.started_at) : '—'}
                </div>
                <div className="source-operation-summary">
                  <strong>{formatJobRunStatus(latestImport.status)}</strong>
                  <span aria-hidden="true"> · </span>
                  <span>{formatJobRunSummary(latestImport.summary)}</span>
                </div>
                {latestImport.status === 'failed' && latestImport.error_message && (
                  <div className="source-operation-error" role="status">{latestImport.error_message}</div>
                )}
              </>
            ) : (
              <div className="source-operation-time"><Trans ns="dataSources" i18nKey="adminSourceForm.text.neverRun" /></div>
            )}
          </div>
          <Link to={`/admin/events?task=${encodeURIComponent(selectedExternalAPI.provider_code ? `${selectedExternalAPI.provider_code}_import` : '')}`} className="btn btn-secondary">
            <Trans ns="dataSources" i18nKey="adminSourceForm.actions.viewJobRuns" />
          </Link>
        </section>
      )}

      {isPurpleAirSource && (
        <section className="card purpleair-source-about" aria-labelledby="purpleair-source-about-heading">
          <h3 id="purpleair-source-about-heading"><Trans ns="dataSources" i18nKey="adminSourceForm.headings.aboutDataSource" /></h3>
          <dl className="purpleair-source-about-grid">
            <div>
              <dt><Trans ns="dataSources" i18nKey="adminSourceForm.text.reportingInterval" /></dt>
              <dd><Trans ns="dataSources" i18nKey="adminSourceForm.text.purpleAirProvidesNewMeasurementApproximately" /></dd>
            </div>
            <div>
              <dt><Trans ns="dataSources" i18nKey="adminSourceForm.text.measurementPeriod" /></dt>
              <dd><Trans ns="dataSources" i18nKey="adminSourceForm.text.eachImportedValueRepresents2Minute" /></dd>
            </div>
            <div>
              <dt><Trans ns="dataSources" i18nKey="adminSourceForm.text.measurementTime" /></dt>
              <dd><Trans ns="dataSources" i18nKey="adminSourceForm.text.compassAqRecordsTimePurpleAir" /></dd>
            </div>
            <div>
              <dt><Trans ns="dataSources" i18nKey="adminSourceForm.text.pmMeasurementSource" /></dt>
              <dd><Trans ns="dataSources" i18nKey="adminSourceForm.text.compassAqImportsPurpleAirApos" /></dd>
            </div>
            <div>
              <dt><Trans ns="dataSources" i18nKey="adminSourceForm.text.metadataManagement" /></dt>
              <dd><Trans ns="dataSources" i18nKey="adminSourceForm.text.managedAutomaticallyMeasurementTimingInformationSupplied" /></dd>
            </div>
            <div>
              <dt><Trans ns="dataSources" i18nKey="adminSourceForm.text.dataQualification" /></dt>
              <dd><Trans ns="dataSources" i18nKey="adminSourceForm.text.purpleAirDevicesAirSensorsThey" /></dd>
            </div>
          </dl>
        </section>
      )}
      {isAirGradientSource && (
        <section className="card" aria-labelledby="airgradient-source-about-heading">
          <h3 id="airgradient-source-about-heading"><Trans ns="dataSources" i18nKey="adminSourceForm.headings.airGradientDataPaths" /></h3>
          <div className="space-y-3 text-sm text-slate-700">
            <p><Trans ns="dataSources" i18nKey="adminSourceForm.text.airGradientCredentialWorkflow" /></p>
            <p><Trans ns="dataSources" i18nKey="adminSourceForm.text.airGradientReferenceWorkflow" /></p>
            <p><Trans ns="dataSources" i18nKey="adminSourceForm.text.airGradientAttributionWorkflow" /></p>
          </div>
        </section>
      )}
  </section>;
}
