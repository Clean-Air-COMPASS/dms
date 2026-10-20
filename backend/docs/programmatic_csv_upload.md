# Programmatic CSV Upload

- Endpoint: `POST /ingest/upload-csv`
- Authentication header: `X-API-Key`
- Required environment variable: `COMPASSAQ_CSV_UPLOAD_API_KEY`
- Optional size limit variable: `COMPASSAQ_CSV_UPLOAD_MAX_BYTES`
- Default file size limit: `5000000` bytes (5 MB)
- Request format: `multipart/form-data`
- File constraints:
  - must be UTF-8 text-based CSV
  - must include a header row
  - required headers: `internalsensorid`, `datetime`, `value`
  - binary uploads and oversized uploads are rejected

Example:

```bash
curl -X POST "http://localhost:8000/ingest/upload-csv" \
  -H "X-API-Key: YOUR_UPLOAD_API_KEY" \
  -F "file=@./measurements.csv;type=text/csv"
```

CSV example:

```csv
internalsensorid,datetime,value
1675,2026-01-15T00:00:00Z,12.5
1676,2026-01-15T00:05:00,9.8
```

Notes:

- `internalsensorid` requires CompassAQ's internal numeric `Sensor ID`. It does not accept a device ID, external device ID, or external sensor ID.
- The internal Sensor ID is shown for each sensor in Administration → Devices → the device detail page.
- A file may contain rows for multiple sensors or pollutants; use one row per sensor measurement and the matching internal Sensor ID in each row.
- `datetime` must be ISO 8601.
- If `datetime` has no timezone, the sensor's device timezone from the database is used.
- The 5 MB application file limit is separate from multipart request overhead at the reverse proxy. Larger files should be split into multiple uploads.
- The endpoint does not permanently store raw uploaded files.
- Future timestamps beyond a five-minute clock-skew tolerance are rejected per line; historical backfill is allowed.
- Duplicate records follow the destination sensor/device Measurement Update Policy. Keep counts as skipped; Replace updates the value and reruns ingest QC; Inherit follows the device policy, defaulting to Keep.
- The response separates `inserted_records`, `updated_records`, `skipped_records`, and `failed_records`, and includes `row_errors`, `qc`, and the upload `event_id`.
- Physical file lines are reported as `Line 3` for the second data record in a simple CSV with a header.
- Authenticated attempts are summarized in Events → System Events, with source CSV upload. API-key uploads have no user actor.
- Timestamp meaning and AQI eligibility follow existing sensor metadata; import does not invent them. See [CSV measurement uploads](../../docs/csv-upload-workflow.md).
