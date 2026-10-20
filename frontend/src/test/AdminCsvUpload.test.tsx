import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AdminCsvUpload from '../AdminCsvUpload';
import { ApiError } from '../apiError';
import * as api from '../api';
import type { DeviceRecord } from '../api';
import i18n from '../i18n';

vi.mock('../auth', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    user: null,
    logout: vi.fn(),
    isLoading: false,
  }),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    uploadMeasurementsCsv: vi.fn(),
    listDevicesAdmin: vi.fn().mockResolvedValue([]),
    listDeviceSensors: vi.fn().mockResolvedValue([]),
  };
});

function makeDevice(device_id: number, name: string): DeviceRecord {
  return {
    device_id,
    name,
    friendly_name: null,
    external_id: `external-${device_id}`,
    external_api_name: 'OpenAQ',
    network: 'OpenAQ',
    timezone: 'UTC',
    status: 'active',
    last_seen_at: null,
  };
}

describe('AdminCsvUpload', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage('en');
  });

  it('explains the required internal sensor identifier and multi-sensor format', () => {
    render(
      <MemoryRouter>
        <AdminCsvUpload />
      </MemoryRouter>,
    );

    expect(screen.getByText(/must contain the internal Sensor ID/)).toBeInTheDocument();
    expect(screen.getByText(/Do not use the Device ID, External Device ID, or External Sensor ID/)).toBeInTheDocument();
    expect(screen.getByText(/multiple pollutant sensors/)).toBeInTheDocument();
    expect(screen.getByText(/12345,2026-01-15T00:00:00Z,12.5/)).toBeInTheDocument();
    expect(screen.getByText(/up to 5 MB/)).toBeInTheDocument();
    expect(screen.getByText(/must already be in the destination sensor/)).toBeInTheDocument();
    expect(screen.getByText(/does not infer a different unit/)).toBeInTheDocument();
  });

  it('identifies the sensor, configured unit and timezone on the page', async () => {
    vi.mocked(api.listDevicesAdmin).mockResolvedValueOnce([{ ...makeDevice(1, 'Fixture station'), timezone: 'Asia/Manila' }]);
    vi.mocked(api.listDeviceSensors).mockResolvedValueOnce([{ sensor_id: 77, parameter_name: 'PM2.5', unit: 'µg/m³', aggregation_code: '1h', external_sensor_id: 'fixture-pm25-77' }]);
    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Fixture station' }));
    expect(await screen.findByText('Device ID: 1')).toBeInTheDocument();
    expect(screen.getByText('External Device ID: external-1')).toBeInTheDocument();
    expect(screen.getByText('Data source: OpenAQ')).toBeInTheDocument();
    expect(screen.getByText('Parameter: PM2.5')).toBeInTheDocument();
    expect(await screen.findByText('Sensor ID: 77 · Unit: µg/m³')).toBeInTheDocument();
    expect(screen.getByText('External Sensor ID: fixture-pm25-77')).toBeInTheDocument();
    expect(screen.getByText('Aggregation: 1h')).toBeInTheDocument();
    expect(screen.getByText('Device timezone: Asia/Manila')).toBeInTheDocument();
  });

  it('starts the lookup at zero-based page 0 and shows devices from the first API page', async () => {
    const firstPage = Array.from({ length: 20 }, (_, index) => makeDevice(index + 1, `First page device ${index + 1}`));
    vi.mocked(api.listDevicesAdmin).mockResolvedValueOnce(firstPage);

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);

    expect(await screen.findByRole('button', { name: 'First page device 1' })).toBeInTheDocument();
    expect(api.listDevicesAdmin).toHaveBeenCalledWith({ search: '', page: 0, page_size: 20 });
    expect(screen.getByText('Page 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).not.toBeDisabled();
  });

  it('requests next and previous pages using the same zero-based contract', async () => {
    const firstPage = Array.from({ length: 20 }, (_, index) => makeDevice(index + 1, `Page one device ${index + 1}`));
    const secondPage = [makeDevice(21, 'Page two device')];
    vi.mocked(api.listDevicesAdmin).mockImplementation(({ page = 0 } = {}) => Promise.resolve(page === 0 ? firstPage : secondPage));
    const user = userEvent.setup();

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    await screen.findByRole('button', { name: 'Page one device 1' });

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByRole('button', { name: 'Page two device' })).toBeInTheDocument();
    expect(api.listDevicesAdmin).toHaveBeenLastCalledWith({ search: '', page: 1, page_size: 20 });
    expect(screen.getByText('Page 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Previous' }));
    expect(await screen.findByRole('button', { name: 'Page one device 1' })).toBeInTheDocument();
    expect(api.listDevicesAdmin).toHaveBeenLastCalledWith({ search: '', page: 0, page_size: 20 });
    expect(screen.getByText('Page 1')).toBeInTheDocument();
  });

  it('does not turn an exact page boundary into a false empty state', async () => {
    const firstPage = Array.from({ length: 20 }, (_, index) => makeDevice(index + 1, `Exact page device ${index + 1}`));
    vi.mocked(api.listDevicesAdmin).mockImplementation(({ page = 0 } = {}) => Promise.resolve(page === 0 ? firstPage : []));
    const user = userEvent.setup();

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    await screen.findByRole('button', { name: 'Exact page device 1' });

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Exact page device 1' })).toBeInTheDocument();
      expect(screen.queryByText('No devices or sensors match this search.')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    });
  });

  it('resets the lookup to page 0 when the search text changes', async () => {
    const firstPage = Array.from({ length: 20 }, (_, index) => makeDevice(index + 1, `Page one device ${index + 1}`));
    const secondPage = [makeDevice(21, 'Page two device')];
    const filteredDevice = makeDevice(50, 'Filtered device');
    vi.mocked(api.listDevicesAdmin).mockImplementation(({ search = '', page = 0 } = {}) => {
      if (search) return Promise.resolve([filteredDevice]);
      return Promise.resolve(page === 0 ? firstPage : secondPage);
    });
    const user = userEvent.setup();

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    await screen.findByRole('button', { name: 'Page one device 1' });
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('button', { name: 'Page two device' });

    await user.type(screen.getByRole('searchbox', { name: 'Device name or identifier' }), 'Filtered');
    expect(await screen.findByRole('button', { name: 'Filtered device' })).toBeInTheDocument();
    expect(api.listDevicesAdmin).toHaveBeenLastCalledWith({ search: 'Filtered', page: 0, page_size: 20 });
    expect(screen.getByText('Page 1')).toBeInTheDocument();
  });

  it('shows a localized empty state only when the lookup succeeds with no matches', async () => {
    vi.mocked(api.listDevicesAdmin).mockResolvedValueOnce([]);

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);

    expect(await screen.findByText('No devices or sensors match this search.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each(['en', 'es'])('separates updated/skipped outcomes and localizes file-line reasons (%s)', async language => {
    await i18n.changeLanguage(language);
    vi.mocked(api.uploadMeasurementsCsv).mockResolvedValueOnce({
      success: false, message: 'Backend diagnostic', total_records: 4,
      inserted_records: 1, updated_records: 1, skipped_records: 1, failed_records: 1,
      errors: ['Line 5: English diagnostic'], row_errors: [{ line: 5, code: 'timestamp_future', message: 'English diagnostic' }],
      qc: { evaluated: 2, passed: 1, flagged: 1, indeterminate: 0 },
    });
    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    const input = screen.getByLabelText(language === 'en' ? 'CSV file' : 'Archivo CSV');
    await userEvent.upload(input, new File(['fixture'], 'synthetic.csv', { type: 'text/csv' }));
    await userEvent.click(screen.getByRole('button', { name: language === 'en' ? 'Upload CSV' : 'Subir CSV' }));
    expect(await screen.findByText(language === 'en' ? /Line 5: Timestamp is later/ : /Línea 5: La marca de tiempo/)).toBeInTheDocument();
    expect(screen.getByText(language === 'en' ? /Updated: 1.*Skipped: 1/ : /Actualizadas: 1.*Omitidas: 1/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: language === 'en' ? 'Review QC failures' : 'Revisar fallos de QC' })).toHaveAttribute('href', '/admin/events?tab=qc-failures');
    expect(screen.queryByText('English diagnostic')).not.toBeInTheDocument();
  });

  it('shows an error instead of the empty state when the lookup request fails', async () => {
    vi.mocked(api.listDevicesAdmin).mockRejectedValueOnce(new Error('network failure'));

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);

    expect(await screen.findByRole('alert')).toHaveTextContent('Sensor reference could not be loaded. Try again.');
    expect(screen.queryByText('No devices or sensors match this search.')).not.toBeInTheDocument();
  });

  it('keeps the device and sensor reference details localized in Spanish', async () => {
    await i18n.changeLanguage('es');
    vi.mocked(api.listDevicesAdmin).mockResolvedValueOnce([makeDevice(1, 'Estación de prueba')]);
    vi.mocked(api.listDeviceSensors).mockResolvedValueOnce([{ sensor_id: 77, parameter_name: 'PM2.5', unit: 'µg/m³', aggregation_code: '1h', external_sensor_id: 'sensor-externo-77' }]);

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Estación de prueba' }));

    expect(await screen.findByText('ID del dispositivo: 1')).toBeInTheDocument();
    expect(screen.getByText('ID externo del sensor: sensor-externo-77')).toBeInTheDocument();
    expect(screen.getByText('Parámetro: PM2.5')).toBeInTheDocument();
  });

  it('renders Spanish partial summaries from counts and keeps row diagnostics separate', async () => {
    await i18n.changeLanguage('es');
    vi.mocked(api.uploadMeasurementsCsv).mockResolvedValueOnce({ success: false, message: 'English backend summary', total_records: 2, inserted_records: 1, failed_records: 1, errors: ['Row 3: Unknown sensor'] });
    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    await userEvent.upload(screen.getByLabelText('Archivo CSV'), new File(['test'], 'fixture.csv', { type: 'text/csv' }));
    await userEvent.click(screen.getByRole('button', { name: 'Subir CSV' }));
    expect(await screen.findByText(/Se procesaron algunas filas/)).toBeInTheDocument();
    expect(screen.queryByText('English backend summary')).not.toBeInTheDocument();
    expect(screen.getByText('Row 3: Unknown sensor')).toBeInTheDocument();
  });

  it('shows a localized controlled message for proxy or application 413 responses', async () => {
    const user = userEvent.setup();
    vi.mocked(api.uploadMeasurementsCsv).mockRejectedValue(
      new ApiError({ status: 413, errorCode: 'csv_file_too_large' }),
    );

    render(
      <MemoryRouter>
        <AdminCsvUpload />
      </MemoryRouter>,
    );

    await user.upload(
      screen.getByLabelText('CSV file') as HTMLInputElement,
      new File(['internalsensorid,datetime,value\n1,2026-01-15T00:00:00Z,12.5\n'], 'large.csv', { type: 'text/csv' }),
    );
    await user.click(screen.getByRole('button', { name: 'Upload CSV' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('File is too large. CSV files can be up to 5 MB.');
    expect(alert).not.toHaveTextContent('Request Entity Too Large');
    expect(alert).not.toHaveTextContent('csv_file_too_large');
  });

  it('explains a rejected CSV header, shows the supported columns, and allows a corrected retry', async () => {
    const user = userEvent.setup();
    vi.mocked(api.uploadMeasurementsCsv)
      .mockRejectedValueOnce(new ApiError({
        status: 400,
        diagnosticMessage: 'missing required CSV columns: internalsensorid, datetime',
      }))
      .mockResolvedValueOnce({
        success: true,
        message: 'Imported 7 records',
        total_records: 7,
        inserted_records: 7,
        failed_records: 0,
        errors: [],
      });

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);

    await user.upload(
      screen.getByLabelText('CSV file') as HTMLInputElement,
      new File(['sensor_id,value,observed_at\n72,1.2,2026-10-16T20:00:00Z'], 'wrong-header.csv', { type: 'text/csv' }),
    );
    await user.click(screen.getByRole('button', { name: 'Upload CSV' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The CSV header must use these required column names: internalsensorid, datetime.');
    expect(alert).toHaveTextContent('internalsensorid,datetime,value');
    expect(alert).toHaveTextContent('The file was rejected before any measurements were imported.');
    expect(alert).not.toHaveTextContent('some rows may already have been saved');
    expect(alert).not.toHaveTextContent('missing required CSV columns:');
    expect(screen.getByText('wrong-header.csv')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Upload CSV' })).toBeEnabled();

    await user.upload(
      screen.getByLabelText('CSV file') as HTMLInputElement,
      new File(['internalsensorid,datetime,value\n72,2026-10-16T20:00:00Z,1.2'], 'corrected.csv', { type: 'text/csv' }),
    );
    await user.click(screen.getByRole('button', { name: 'Upload CSV' }));

    expect(await screen.findByText('CSV processing completed.')).toBeInTheDocument();
    expect(api.uploadMeasurementsCsv).toHaveBeenCalledTimes(2);
  });

  it('keeps unrelated HTTP 400 responses in the uncertain-outcome state', async () => {
    vi.mocked(api.uploadMeasurementsCsv).mockRejectedValueOnce(
      new ApiError({ status: 400, diagnosticMessage: 'Uploaded file is empty' }),
    );

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    await userEvent.upload(
      screen.getByLabelText('CSV file') as HTMLInputElement,
      new File([''], 'empty.csv', { type: 'text/csv' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Upload CSV' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('some rows may already have been saved');
    expect(alert).not.toHaveTextContent('Uploaded file is empty');
  });

  it('keeps the upload error localized in Spanish', async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage('es');
    vi.mocked(api.uploadMeasurementsCsv).mockRejectedValue(new ApiError({ status: 413 }));

    render(
      <MemoryRouter>
        <AdminCsvUpload />
      </MemoryRouter>,
    );

    await user.upload(
      screen.getByLabelText('Archivo CSV') as HTMLInputElement,
      new File(['internalsensorid,datetime,value\n1,2026-01-15T00:00:00Z,12.5\n'], 'grande.csv', { type: 'text/csv' }),
    );
    await user.click(screen.getByRole('button', { name: 'Subir CSV' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('El archivo es demasiado grande.');
    expect(screen.getAllByText(/ID interno del sensor/).length).toBeGreaterThan(0);
  });

  it('localizes a known header validation error in Spanish', async () => {
    const user = userEvent.setup();
    await i18n.changeLanguage('es');
    vi.mocked(api.uploadMeasurementsCsv).mockRejectedValueOnce(
      new ApiError({ status: 400, diagnosticMessage: 'missing required CSV columns: internalsensorid, datetime' }),
    );

    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    await user.upload(
      screen.getByLabelText('Archivo CSV') as HTMLInputElement,
      new File(['sensor_id,value,observed_at\n72,1.2,2026-10-16T20:00:00Z'], 'encabezado-incorrecto.csv', { type: 'text/csv' }),
    );
    await user.click(screen.getByRole('button', { name: 'Subir CSV' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('El encabezado CSV debe usar estos nombres de columna obligatorios: internalsensorid, datetime.');
    expect(alert).toHaveTextContent('Use el encabezado admitido: internalsensorid,datetime,value.');
    expect(alert).toHaveTextContent('El archivo se rechazó antes de importar mediciones.');
    expect(alert).not.toHaveTextContent('es posible que algunas filas ya se hayan guardado');
  });

  it('explains pending checks and uncertain upload outcome, then supports retry', async () => {
    let rejectUpload!: (reason: Error) => void;
    vi.mocked(api.uploadMeasurementsCsv).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectUpload = reject; }));
    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    const file = new File(['internalsensorid,datetime,value\n1,2026-01-15T00:00:00Z,12.5'], 'retry.csv', { type: 'text/csv' });
    await userEvent.upload(screen.getByLabelText('CSV file'), file);
    await userEvent.click(screen.getByRole('button', { name: 'Upload CSV' }));
    expect(await screen.findByText(/Baseline Drift checks can take a minute/)).toBeVisible();
    expect(screen.getByText('Elapsed: 0 seconds')).toBeVisible();
    rejectUpload(new Error('Network failed'));
    expect(await screen.findByRole('alert')).toHaveTextContent('some rows may already have been saved');
    expect(screen.getByRole('link', { name: 'View upload activity' })).toHaveAttribute('href', '/admin/events?tab=events');
    expect(screen.getByText('retry.csv')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Upload CSV' })).toBeEnabled();
    expect(screen.getByText(/CSV uploads do not establish AQI eligibility/)).toBeVisible();
  });


  it('keeps sensor lookup loading until the selected device response arrives', async () => {
    vi.mocked(api.listDevicesAdmin).mockResolvedValueOnce([makeDevice(1, 'Pending station')]);
    let resolveSensors!: (value: api.DeviceSensorSummary[]) => void;
    vi.mocked(api.listDeviceSensors).mockImplementationOnce(() => new Promise(resolve => { resolveSensors = resolve; }));
    render(<MemoryRouter><AdminCsvUpload /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Pending station' }));
    expect(screen.queryByText('No sensors are configured for this device.')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Loading');
    await waitFor(() => expect(api.listDeviceSensors).toHaveBeenCalledWith(1));
    resolveSensors([{ sensor_id: 77, parameter_name: 'PM2.5', unit: 'µg/m³' }]);
    expect(await screen.findByText('Sensor ID: 77 · Unit: µg/m³')).toBeVisible();
  });
});
