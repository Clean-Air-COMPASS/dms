import { useRef, useState } from 'react';
import AdminPageLayout from './components/AdminPageLayout';
import { uploadMeasurementsCsv, type CsvUploadResult } from './api';

export default function AdminCsvUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<CsvUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const onUpload = async () => {
    if (!file) {
      setError('Please choose a CSV file first.');
      return;
    }
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const data = await uploadMeasurementsCsv(file);
      setResult(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <AdminPageLayout
      title="CSV Upload"
      description="Upload measurements from a CSV file."
      breadcrumbs={[{ label: 'Admin', to: '/admin' }, { label: 'CSV Upload' }]}
      contentClassName="csv-upload-page"
    >
      <div className="card">
        <p className="muted" style={{ marginTop: 0 }}>
          Required CSV header: <code>internalsensorid,datetime,value</code>
        </p>
        <p className="muted">
          Datetime must be ISO 8601. If no timezone is provided in the CSV, the sensor&apos;s device timezone from the database is applied.
        </p>
        <p className="muted">
          A file may include multiple different sensor IDs. Each sensor ID must already exist in the database.
        </p>

        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
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
            Choose CSV File
          </button>
          <span className="muted">{file ? file.name : 'No file selected'}</span>
        </div>

        <div className="form-actions" style={{ justifyContent: 'flex-start' }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onUpload}
            disabled={uploading}
          >
            {uploading ? 'Uploading…' : 'Upload CSV'}
          </button>
        </div>

        {error && <div className="error-banner">{error}</div>}

        {result && (
          <div className={result.success ? 'info-banner' : 'error-banner'}>
            <div>{result.message}</div>
            <div style={{ marginTop: 8 }}>
              Total: {result.total_records} | Inserted: {result.inserted_records} | Failed: {result.failed_records}
            </div>
            {!result.success && result.errors && result.errors.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <strong>Row errors:</strong>
                <ul style={{ margin: '8px 0 0 20px' }}>
                  {result.errors.map((entry) => (
                    <li key={entry}>{entry}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </AdminPageLayout>
  );
}
