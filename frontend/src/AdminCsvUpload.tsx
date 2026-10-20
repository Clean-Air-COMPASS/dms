import { Trans, useTranslation } from 'react-i18next';
import i18n from './i18n';
import { useEffect, useRef, useState } from 'react';
import CsvSensorReference from './components/CsvSensorReference';
import AdminPageLayout from './components/AdminPageLayout';
import { uploadMeasurementsCsv, type CsvUploadResult } from './api';
import { ApiError } from './apiError';
import { Link } from 'react-router-dom';

const CSV_REQUIRED_HEADERS = ['internalsensorid', 'datetime', 'value'] as const;
const CSV_REQUIRED_HEADER = CSV_REQUIRED_HEADERS.join(',');
const MISSING_CSV_COLUMNS_PREFIX = 'missing required CSV columns: ';

type UploadError =
  | {
      kind: 'message';
      key: 'admin:adminCsvUpload.messages.pleaseChooseCsvFileFirst' | 'admin:adminCsvUpload.messages.fileTooLarge';
    }
  | { kind: 'header'; requiredHeaderNames: string[] }
  | { kind: 'unconfirmed' };

function getRequiredCsvHeaderNames(error: unknown): string[] | null {
  if (!(error instanceof ApiError) || error.status !== 400) return null;

  const diagnostic = error.diagnosticMessage;
  if (!diagnostic?.startsWith(MISSING_CSV_COLUMNS_PREFIX)) return null;

  const names = diagnostic
    .slice(MISSING_CSV_COLUMNS_PREFIX.length)
    .split(',')
    .map((name) => name.trim().toLowerCase());
  const requiredHeaders = new Set<string>(CSV_REQUIRED_HEADERS);
  if (names.length === 0 || names.some((name) => !requiredHeaders.has(name))) {
    return null;
  }

  const missing = new Set(names);
  return CSV_REQUIRED_HEADERS.filter((name) => missing.has(name));
}

export default function AdminCsvUpload() {
  const { t } = useTranslation('admin');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<CsvUploadResult | null>(null);
  const [error, setError] = useState<UploadError | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  useEffect(() => {
    if (!uploading) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsedSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [uploading]);

  const onUpload = async () => {
    if (!file) {
      setError({ kind: 'message', key: 'admin:adminCsvUpload.messages.pleaseChooseCsvFileFirst' });
      return;
    }
    setElapsedSeconds(0);
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const data = await uploadMeasurementsCsv(file);
      setResult(data);
    } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.status === 413) {
        setError({ kind: 'message', key: 'admin:adminCsvUpload.messages.fileTooLarge' });
      } else {
        const requiredHeaderNames = getRequiredCsvHeaderNames(caught);
        setError(requiredHeaderNames ? { kind: 'header', requiredHeaderNames } : { kind: 'unconfirmed' });
      }
    } finally {
      setUploading(false);
    }
  };

  return (
    <AdminPageLayout
      title={i18n.t('admin:adminCsvUpload.tooltips.csvUpload')}
      description={i18n.t('admin:adminCsvUpload.accessibility.uploadMeasurementsCsvFile')}
      breadcrumbs={[{ label: i18n.t('admin:adminCsvUpload.content.admin'), to: '/admin' }, { label: i18n.t('admin:adminCsvUpload.content.csvUpload') }]}
      contentClassName="admin-workspace csv-upload-page"
    >
      <div className="csv-workspace">
        {result && (
          <section className="card csv-result col-span-full" role={result.success ? 'status' : 'alert'}>
            <h2>{i18n.t('admin:workspace.result')}</h2>
            <div>{i18n.t(result.success ? 'admin:adminCsvUpload.summary.success' : result.inserted_records + (result.updated_records ?? 0) + (result.skipped_records ?? 0) > 0 ? 'admin:adminCsvUpload.summary.partial' : 'admin:adminCsvUpload.summary.failed')}</div>
            <div style={{ marginTop: 8 }}>
              <Trans ns="admin" i18nKey="adminCsvUpload.text.total" />{' '}{result.total_records} {' '}<Trans ns="admin" i18nKey="adminCsvUpload.text.inserted" />{' '}{result.inserted_records} {' '}{t('adminCsvUpload.text.updated')} {result.updated_records ?? 0} {' '}{t('adminCsvUpload.text.skipped')} {result.skipped_records ?? 0} {' '}<Trans ns="admin" i18nKey="adminCsvUpload.text.failed" />{' '}{result.failed_records}
            </div>
            <p>{t('adminCsvUpload.text.skippedExplanation')}</p>
            {result.qc && <p>{t('adminCsvUpload.summary.qc', result.qc)}</p>}
            <p>{t('adminCsvUpload.text.qcExplanation')}</p>
            <div className="form-actions">
              <Link className="btn" to="/admin/events?tab=qc-failures">{t('adminCsvUpload.actions.reviewQc')}</Link>
              <Link className="btn" to="/admin/events?tab=events">{t('adminCsvUpload.actions.reviewActivity')}</Link>
            </div>
            {!result.success && result.errors && result.errors.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <strong><Trans ns="admin" i18nKey="adminCsvUpload.text.rowErrors" /></strong>
                <ul style={{ margin: '8px 0 0 20px' }}>
                  {(result.row_errors?.map(entry => t('adminCsvUpload.messages.lineError', {
                    line: entry.line,
                    reason: t(`adminCsvUpload.rowReasons.${entry.code}`, { defaultValue: t('adminCsvUpload.rowReasons.import_failed') }),
                  })) ?? result.errors).map((entry) => (
                    <li key={entry}>{entry}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}
        <section className="card">
          <h2>{i18n.t('admin:workspace.chooseFile')}</h2>
        <p><strong>{i18n.t('admin:adminCsvUpload.text.unitRequirement')}</strong></p>
        <p>{i18n.t('admin:adminCsvUpload.text.noConversion')}</p>
        <p>{t('adminCsvUpload.text.updatePolicy')}</p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          aria-label={i18n.t('admin:adminCsvUpload.accessibility.chooseCsvFile')}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          disabled={uploading}
          style={{ display: 'none' }}
        />

        <div className="form-actions" style={{ justifyContent: 'flex-start', alignItems: 'center' }}>
          <button
            type="button"
            className="btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            <Trans ns="admin" i18nKey="adminCsvUpload.actions.chooseCsvFile" /></button>
          <span className="csv-file-name muted">{file ? file.name : i18n.t('admin:adminCsvUpload.text.noFileSelected')}</span>
        </div>

        <div className="form-actions" style={{ justifyContent: 'flex-start' }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onUpload}
            disabled={uploading}
          >
            {uploading ? i18n.t('admin:adminCsvUpload.actions.uploading') : i18n.t('admin:adminCsvUpload.actions.uploadCsv')}
          </button>
        </div>

        {uploading && <div>
          <p role="status">{t('adminCsvUpload.messages.processing')}</p>
          <p className="muted">{t('adminCsvUpload.messages.elapsed', { seconds: elapsedSeconds })}</p>
        </div>}
        {error && <div className="error-banner" role="alert">{error.kind === 'unconfirmed' ? <>
          <p>{t('adminCsvUpload.messages.uploadUnconfirmed')}</p>
          <div className="form-actions">
            <Link className="btn" to="/admin/events?tab=events">{t('adminCsvUpload.actions.reviewActivity')}</Link>
          </div>
        </> : error.kind === 'header' ? <>
          <p>{t('adminCsvUpload.messages.headerRequiredColumnNames', { columns: error.requiredHeaderNames.join(', ') })}</p>
          <p>{t('adminCsvUpload.messages.headerUseSupportedFormat')} <code>{CSV_REQUIRED_HEADER}</code>.</p>
          <p>{t('adminCsvUpload.messages.headerRejectedBeforeImport')}</p>
        </> : i18n.t(error.key)}</div>}
        </section>
        <CsvSensorReference />
        <section className="card col-span-full">
          <h2>{i18n.t('admin:workspace.format')}</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          <Trans ns="admin" i18nKey="adminCsvUpload.text.requiredCsvHeader" /><code><Trans ns="admin" i18nKey="adminCsvUpload.text.internalsensoridDatetimeValue" /></code>
        </p>
        <p className="muted">
          <Trans ns="admin" i18nKey="adminCsvUpload.text.csvIdentifier" />
        </p>
        <p className="muted">
          <Trans ns="admin" i18nKey="adminCsvUpload.text.whereToFindCsvIdentifier" />
        </p>
        <p className="muted">
          <Trans ns="admin" i18nKey="adminCsvUpload.text.maximumFileSize" />
        </p>
        <p className="muted">
          <Trans ns="admin" i18nKey="adminCsvUpload.text.datetimeMustIso8601IfNo" /></p>
        <p className="muted">{t('adminCsvUpload.text.timestampSemantics')}</p>
        <p className="muted">{t('adminCsvUpload.text.aqiMetadata')}</p>
        <p className="muted">{t('adminCsvUpload.text.futureTolerance')}</p>
        <p className="muted">
          <Trans ns="admin" i18nKey="adminCsvUpload.text.fileMayIncludeMultipleDifferentSensor" /></p>
        <p className="muted">
          <Trans ns="admin" i18nKey="adminCsvUpload.text.exampleLabel" />
        </p>
        <pre className="code-block csv-example" aria-label={i18n.t('admin:adminCsvUpload.text.exampleLabel')}><code>{'internalsensorid,datetime,value\n12345,2026-01-15T00:00:00Z,12.5\n12346,2026-01-15T00:00:00Z,9.8'}</code></pre>

        </section>
      </div>
    </AdminPageLayout>
  );
}
