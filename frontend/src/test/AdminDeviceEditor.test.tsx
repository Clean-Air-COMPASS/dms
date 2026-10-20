import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AdminDeviceEditor from '../AdminDeviceEditor';
import * as api from '../api';
import { ApiError } from '../apiError';

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
    createDeviceAdmin: vi.fn(),
    createDeviceSensorAdmin: vi.fn(),
    deleteDeviceSensorAdmin: vi.fn(),
    fetchJson: vi.fn().mockImplementation(async (path: string) => {
      if (path === '/parameters') {
        return [
          { code: 'pm25', display_name: 'PM2.5' },
          { code: 'co', display_name: 'Carbon Monoxide' },
        ];
      }
      if (path === '/aggregation_periods') {
        return [
          { code: '24h', display_name: 'Daily' },
          { code: '1h', display_name: 'Hourly' },
        ];
      }
      return [];
    }),
    getDeviceAdmin: vi.fn().mockResolvedValue({
      device_id: 123,
      name: 'Test Device',
      friendly_name: null,
      external_id: null,
      external_api_id: 1,
      external_api_name: 'alpha source',
      timezone: null,
      allow_updates: 'inherit',
      is_external: false,
    }),
    listDeviceSensors: vi.fn().mockResolvedValue([
      {
        sensor_id: 77,
        parameter_code: 'pm25',
        parameter_name: 'PM2.5',
        aggregation_code: '1h',
        external_sensor_id: 'sensor-ext-77',
        value: 12.5,
        unit_symbol: 'ug/m3',
        observed_at: '2026-03-31T12:00:00Z',
      },
    ]),
    listExternalAPIs: vi.fn().mockResolvedValue([
      { external_api_id: 2, name: 'Zulu Source', enabled: false },
      { external_api_id: 1, name: 'alpha source', enabled: true },
    ]),
    updateDeviceAdmin: vi.fn(),
    updateDeviceSensorAdmin: vi.fn(),
  };
});

describe('device field validation', () => {
  const renderManual = () => render(<MemoryRouter><AdminDeviceEditor /></MemoryRouter>);

  beforeEach(() => { vi.clearAllMocks(); });

  it('requires a truthful Other source name only for the Other selection and focuses its error', async () => {
    renderManual();
    const source = await screen.findByLabelText('Data Source');
    expect(screen.queryByLabelText(/Other Data Source Name/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Manual station' } });
    fireEvent.change(source, { target: { value: '__other__' } });
    const otherName = screen.getByLabelText(/Other Data Source Name/);
    expect(otherName).toBeRequired();
    expect(otherName).toHaveAccessibleDescription(/Required when Other is selected/);
    fireEvent.change(otherName, { target: { value: '   ' } });
    fireEvent.submit(otherName.closest('form')!);
    expect(api.createDeviceAdmin).not.toHaveBeenCalled();
    expect(otherName).toHaveAttribute('aria-invalid', 'true');
    expect(otherName).toHaveAccessibleDescription(/Enter a data source name when Other is selected/);
    await waitFor(() => expect(otherName).toHaveFocus());
    fireEvent.change(source, { target: { value: '1' } });
    expect(screen.queryByLabelText(/Other Data Source Name/)).not.toBeInTheDocument();
    fireEvent.submit(source.closest('form')!);
    await waitFor(() => expect(api.createDeviceAdmin).toHaveBeenCalledWith(expect.objectContaining({ external_api_id: 1 })));
    expect(vi.mocked(api.createDeviceAdmin).mock.calls[0][0]).not.toHaveProperty('network');
  });

  it('validates coordinates on blur and submit with accessible field errors and focus', async () => {
    renderManual();
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Manual station' } });
    const latitude = screen.getByLabelText('Latitude');
    const longitude = screen.getByLabelText('Longitude');
    fireEvent.change(latitude, { target: { value: '2000' } });
    fireEvent.change(longitude, { target: { value: '3000' } });
    fireEvent.blur(longitude);
    expect(latitude).toHaveAccessibleDescription(/Latitude must be between -90 and 90/);
    expect(longitude).toHaveAccessibleDescription(/Longitude must be between -180 and 180/);
    expect(screen.getAllByRole('alert')).toHaveLength(2);
    fireEvent.submit(latitude.closest('form')!);
    expect(api.createDeviceAdmin).not.toHaveBeenCalled();
    await waitFor(() => expect(latitude).toHaveFocus());
    expect(latitude).toHaveValue('2000');
    fireEvent.change(latitude, { target: { value: '-35.1234' } });
    fireEvent.change(longitude, { target: { value: '-120.1234' } });
    fireEvent.submit(latitude.closest('form')!);
    await waitFor(() => expect(api.createDeviceAdmin).toHaveBeenCalledWith(expect.objectContaining({ latitude: -35.1234, longitude: -120.1234 })));
  });

  it('clears an existing location explicitly using null coordinates', async () => {
    vi.mocked(api.getDeviceAdmin).mockResolvedValueOnce({ device_id: 123, name: 'Local station', is_external: false, latitude: 38.44, longitude: -122.71 } as api.DeviceRecord);
    render(<MemoryRouter initialEntries={['/admin/devices/123/edit']}><Routes><Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} /></Routes></MemoryRouter>);
    const latitude = await screen.findByLabelText('Latitude');
    fireEvent.change(latitude, { target: { value: '  ' } });
    fireEvent.change(screen.getByLabelText('Longitude'), { target: { value: '' } });
    fireEvent.submit(latitude.closest('form')!);
    await waitFor(() => expect(api.updateDeviceAdmin).toHaveBeenCalledWith(123, expect.objectContaining({ latitude: null, longitude: null })));
  });

  it('preserves backend coordinate validation and associates its error with the field', async () => {
    vi.mocked(api.createDeviceAdmin).mockRejectedValueOnce(new ApiError({ status: 400, errorCode: 'longitude_out_of_range' }));
    renderManual();
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Local station' } });
    const longitude = screen.getByLabelText('Longitude');
    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '0' } });
    fireEvent.change(longitude, { target: { value: '180' } });
    fireEvent.submit(longitude.closest('form')!);
    await waitFor(() => expect(longitude).toHaveAccessibleDescription(/Longitude must be between -180 and 180/));
    await waitFor(() => expect(longitude).toHaveFocus());
    expect(longitude).toHaveValue('180');
  });

  it('serializes a manual device with blank coordinates and an omitted automatic source', async () => {
    renderManual();
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Manual station' } });
    fireEvent.submit(screen.getByLabelText(/^Name/).closest('form')!);

    await waitFor(() => expect(api.createDeviceAdmin).toHaveBeenCalledTimes(1));
    expect(JSON.parse(JSON.stringify(vi.mocked(api.createDeviceAdmin).mock.calls[0][0]))).toEqual({
      friendly_name: '',
      allow_updates: 'inherit',
      name: 'Manual station',
      latitude: null,
      longitude: null,
    });
  });

  it.each([
    ['latitude_out_of_range', 'Latitude', 'Latitude', /Latitude must be between -90 and 90/],
    ['incomplete_coordinate_pair', 'Latitude', 'Longitude', /Enter both latitude and longitude/],
    ['non_finite_coordinate', 'Latitude', 'Longitude', /Enter a valid number/],
  ])('maps backend %s to coordinate feedback', async (errorCode, field, focusedField, message) => {
    vi.mocked(api.createDeviceAdmin).mockRejectedValueOnce(new ApiError({ status: 400, errorCode }));
    renderManual();
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Manual station' } });
    fireEvent.submit(screen.getByLabelText(/^Name/).closest('form')!);

    const input = screen.getByLabelText(field);
    await waitFor(() => expect(input).toHaveAccessibleDescription(message));
    await waitFor(() => expect(screen.getByLabelText(focusedField)).toHaveFocus());
  });
});

describe('AdminDeviceEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a sorted data source dropdown for manual device creation', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/devices/manual']}>
        <Routes>
          <Route path="/admin/devices/manual" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    const select = await screen.findByLabelText(/Data Source/);
    await waitFor(() => {
      expect(screen.getByText("Optional. If left on automatic assignment, the server uses Local when available, otherwise the first Data Source. Select a source to control the assignment.")).toBeInTheDocument();
    });

    const options = screen.getAllByRole('option').map((option) => option.textContent);
    expect(select).toHaveValue('');
    expect(screen.getByText('Data Source')).toBeInTheDocument();
    expect(screen.getAllByText('*').length).toBeGreaterThan(0);
    expect(screen.getByText('Automatic assignment')).toBeInTheDocument();
    expect(options).toContain('alpha source');
    expect(options).not.toContain('Zulu Source');
    expect(options).toContain('Other');
    expect(select).not.toBeDisabled();
  });

  it('shows a custom data source input and saves the typed name when Other is selected', async () => {
    const createDeviceAdminMock = vi.mocked(api.createDeviceAdmin);
    createDeviceAdminMock.mockResolvedValue({
      device_id: 456,
      name: 'Custom Source Device',
      friendly_name: null,
      external_id: null,
      external_api_id: 33,
      external_api_name: 'Neighborhood Lab',
      timezone: null,
      allow_updates: 'inherit',
      is_external: false,
    } as api.DeviceRecord);

    render(
      <MemoryRouter initialEntries={['/admin/devices/manual']}>
        <Routes>
          <Route path="/admin/devices/manual" element={<AdminDeviceEditor />} />
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    fireEvent.change(await screen.findByRole('textbox', { name: /^Name/ }), { target: { value: 'Custom Source Device' } });
    fireEvent.change(screen.getByLabelText(/Data Source/), { target: { value: '__other__' } });
    fireEvent.change(screen.getByLabelText(/Other Data Source Name/), { target: { value: 'Neighborhood Lab' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add device' }));

    await waitFor(() => {
      expect(createDeviceAdminMock).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'Custom Source Device',
          network: 'Neighborhood Lab',
        })
      );
    });
    expect(createDeviceAdminMock.mock.calls[0][0]).not.toHaveProperty('external_api_id');
    expect(JSON.parse(JSON.stringify(createDeviceAdminMock.mock.calls[0][0]))).toEqual({
      friendly_name: '',
      allow_updates: 'inherit',
      name: 'Custom Source Device',
      latitude: null,
      longitude: null,
      network: 'Neighborhood Lab',
    });
  });

  it('keeps an inactive assigned data source visible when editing an existing device', async () => {
    vi.mocked(api.getDeviceAdmin).mockResolvedValueOnce({
      device_id: 123,
      name: 'Test Device',
      friendly_name: null,
      external_id: null,
      external_api_id: 2,
      external_api_name: 'Zulu Source',
      timezone: null,
      allow_updates: 'inherit',
      is_external: false,
    } as api.DeviceRecord);

    render(
      <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
        <Routes>
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    const select = await screen.findByLabelText(/Data Source/);
    const options = screen.getAllByRole('option').map((option) => option.textContent);

    expect(select).toHaveValue('2');
    expect(options).toContain('Zulu Source');
    expect(options).toContain('alpha source');
  });

  it('shows a parameter dropdown for adding sensors', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
        <Routes>
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    const parameterSelect = await screen.findByLabelText(/Parameter/);
    const options = screen.getAllByRole('option').map((option) => option.textContent);

    expect(parameterSelect).toHaveValue('');
    expect(screen.getByText('Select parameter')).toBeInTheDocument();
    expect(options).toContain('Carbon Monoxide');
    expect(options).toContain('PM2.5');
    expect(options.indexOf('Carbon Monoxide')).toBeLessThan(options.indexOf('PM2.5'));
    expect(parameterSelect).not.toBeDisabled();
    const editButton = await screen.findByRole('button', { name: 'Edit' });
    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
    expect(editButton).toBeInTheDocument();
    expect(editButton).toHaveClass('sensor-item-action-btn');
    expect(deleteButtons.length).toBeGreaterThan(0);
    expect(deleteButtons[deleteButtons.length - 1]).toHaveClass('sensor-item-action-btn');
  });

  it('shows a time resolution dropdown for adding sensors sorted alphabetically', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
        <Routes>
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    const resolutionSelect = await screen.findByLabelText(/^Time Resolution/);
    const options = within(resolutionSelect).getAllByRole('option').map((option) => option.textContent);

    expect(screen.getByText('Time Resolution')).toBeInTheDocument();
    expect(options).toContain('Daily');
    expect(options).toContain('Hourly');
    expect(options.indexOf('Daily')).toBeLessThan(options.indexOf('Hourly'));
  });

  it('shows the operational sensor summary without technical metadata details', async () => {
    vi.mocked(api.listDeviceSensors).mockResolvedValueOnce([
      {
        sensor_id: 77,
        parameter_code: 'pm25',
        parameter_name: 'PM2.5',
        aggregation_code: '2m',
        external_sensor_id: 'sensor-ext-77',
        value: 2.4,
        unit_symbol: 'µg/m³',
        observed_at: '2026-07-31T03:59:00Z',
        is_valid: true,
        expected_frequency_seconds: 120,
        measurement_duration_seconds: 120,
        source_aggregation_duration_seconds: 120,
        measurement_timestamp_semantics: 'provider_received_at',
        measurement_metadata_status: 'provider_documented',
        measurement_metadata_managed_by: 'purpleair_importer',
      },
    ]);

    const { container } = render(
      <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
        <Routes>
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('Updates every 2 minutes · Each value is a 2-minute average')).toBeInTheDocument();
    const sensorItem = container.querySelector<HTMLElement>('.sensor-item');
    expect(sensorItem).not.toBeNull();
    const sensorCard = within(sensorItem as HTMLElement);
    expect(sensorCard.getByText('PM2.5')).toBeInTheDocument();
    expect(sensorCard.getByText('Valid')).toBeInTheDocument();
    expect(sensorCard.getByText('2.4')).toBeInTheDocument();
    expect(container.querySelector('.sensor-value')).toHaveTextContent('2.4 µg/m³');
    expect(sensorCard.getByText('Latest reading')).toBeInTheDocument();
    const readingTime = container.querySelector('time');
    expect(readingTime).not.toBeNull();
    expect(readingTime).toHaveAttribute('datetime', '2026-07-31T03:59:00Z');
    expect(readingTime?.textContent).toBeTruthy();
    expect(sensorCard.getByText('Internal Sensor ID: 77')).toBeInTheDocument();
    expect(sensorCard.getByText('External Sensor ID: sensor-ext-77')).toBeInTheDocument();
    expect(screen.queryByText(/120 seconds/i)).not.toBeInTheDocument();

    expect(screen.queryByText('Technical details')).not.toBeInTheDocument();
    expect(screen.queryByText('Timestamp source')).not.toBeInTheDocument();
    expect(screen.queryByText('Time received by PurpleAir')).not.toBeInTheDocument();
    expect(screen.queryByText('Metadata basis')).not.toBeInTheDocument();
    expect(screen.queryByText('Based on provider documentation')).not.toBeInTheDocument();
    expect(screen.queryByText('Metadata managed by')).not.toBeInTheDocument();
    expect(screen.queryByText('PurpleAir importer')).not.toBeInTheDocument();
    expect(screen.queryByText('Source aggregation period')).not.toBeInTheDocument();
    expect(screen.queryByText('provider_received_at')).not.toBeInTheDocument();
    expect(screen.queryByText('provider_documented')).not.toBeInTheDocument();
    expect(screen.queryByText('purpleair_importer')).not.toBeInTheDocument();
  });

  it('links directly from a sensor card to its quality control page', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
        <Routes>
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    const manageQc = await screen.findByRole('link', { name: 'Manage QC' });
    expect(manageQc).toHaveAttribute('href', '/admin/qc/sensors/77');
  });

  it('renders frequency-only metadata without an empty technical section', async () => {
    vi.mocked(api.listDeviceSensors).mockResolvedValueOnce([
      {
        sensor_id: 78,
        parameter_code: 'pm25',
        parameter_name: 'PM2.5',
        expected_frequency_seconds: 120,
        measurement_duration_seconds: null,
        source_aggregation_duration_seconds: null,
        measurement_timestamp_semantics: 'unknown_semantics',
        measurement_metadata_status: null,
        measurement_metadata_managed_by: null,
      },
    ]);

    render(
      <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
        <Routes>
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('Updates every 2 minutes')).toBeInTheDocument();
    expect(screen.queryByText(/Each value is/)).not.toBeInTheDocument();
    expect(screen.queryByText('Technical details')).not.toBeInTheDocument();
    expect(screen.queryByText('unknown_semantics')).not.toBeInTheDocument();
  });

  it('renders duration-only metadata without an empty cadence label', async () => {
    vi.mocked(api.listDeviceSensors).mockResolvedValueOnce([
      {
        sensor_id: 79,
        parameter_code: 'pm25',
        parameter_name: 'PM2.5',
        expected_frequency_seconds: null,
        measurement_duration_seconds: 120,
      },
    ]);

    render(
      <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
        <Routes>
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('Each value is a 2-minute average')).toBeInTheDocument();
    expect(screen.queryByText(/Updates every/)).not.toBeInTheDocument();
    expect(screen.queryByText('Technical details')).not.toBeInTheDocument();
  });

  it('refreshes the sensor list after editing a sensor', async () => {
    const listDeviceSensorsMock = vi.mocked(api.listDeviceSensors);
    const updateDeviceSensorAdminMock = vi.mocked(api.updateDeviceSensorAdmin);

    listDeviceSensorsMock
      .mockResolvedValueOnce([
        {
          sensor_id: 77,
          parameter_code: 'pm25',
          parameter_name: 'PM2.5',
          aggregation_code: '1h',
          external_sensor_id: 'sensor-ext-77',
          value: 12.5,
          unit_symbol: 'ug/m3',
          observed_at: '2026-03-31T12:00:00Z',
        },
      ])
      .mockResolvedValueOnce([
        {
          sensor_id: 77,
          parameter_code: 'co',
          parameter_name: 'Carbon Monoxide',
          aggregation_code: '24h',
          external_sensor_id: 'sensor-ext-99',
          value: 12.5,
          unit_symbol: 'ug/m3',
          observed_at: '2026-03-31T12:00:00Z',
        },
      ]);
    updateDeviceSensorAdminMock.mockResolvedValue({
      sensor_id: 77,
      parameter_code: 'co',
      external_sensor_id: 'sensor-ext-99',
    } as api.DeviceSensorCreateResult);

    const { container } = render(
      <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
        <Routes>
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const sensorItem = container.querySelector('.sensor-item');
    expect(sensorItem).not.toBeNull();
    expect(within(sensorItem as HTMLElement).getByLabelText(/^Time Resolution/)).toHaveValue('1h');
    fireEvent.change(within(sensorItem as HTMLElement).getByLabelText(/^Parameter /), { target: { value: 'co' } });
    fireEvent.change(within(sensorItem as HTMLElement).getByLabelText(/^Time Resolution/), { target: { value: '24h' } });
    fireEvent.change(within(sensorItem as HTMLElement).getByLabelText('External Sensor ID'), { target: { value: 'sensor-ext-99' } });
    fireEvent.click(within(sensorItem as HTMLElement).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(updateDeviceSensorAdminMock).toHaveBeenCalledWith(123, 77, {
        parameter_code: 'co',
        aggregation_code: '24h',
        external_sensor_id: 'sensor-ext-99',
      });
    });
    await waitFor(() => {
      const refreshedSensorItem = container.querySelector('.sensor-item');
      expect(refreshedSensorItem).not.toBeNull();
      expect(within(refreshedSensorItem as HTMLElement).getByText('Carbon Monoxide')).toBeInTheDocument();
      expect(within(refreshedSensorItem as HTMLElement).getByText('External Sensor ID: sensor-ext-99')).toBeInTheDocument();
    });
    expect(listDeviceSensorsMock).toHaveBeenCalledTimes(2);
  });

  it('refreshes the sensor list after deleting a sensor', async () => {
    const listDeviceSensorsMock = vi.mocked(api.listDeviceSensors);
    const deleteDeviceSensorAdminMock = vi.mocked(api.deleteDeviceSensorAdmin);

    listDeviceSensorsMock
      .mockResolvedValueOnce([
        {
          sensor_id: 77,
          parameter_code: 'pm25',
          parameter_name: 'PM2.5',
          external_sensor_id: 'sensor-ext-77',
          value: 12.5,
          unit_symbol: 'ug/m3',
          observed_at: '2026-03-31T12:00:00Z',
        },
      ])
      .mockResolvedValueOnce([]);
    deleteDeviceSensorAdminMock.mockResolvedValue(undefined);

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    const { container } = render(
      <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
        <Routes>
          <Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} />
        </Routes>
      </MemoryRouter>
    );

    const sensorDeleteButton = await waitFor(() => {
      const button = container.querySelector('.sensor-item-action-btn.btn-danger');
      expect(button).not.toBeNull();
      return button as HTMLElement;
    });
    fireEvent.click(sensorDeleteButton);

    await waitFor(() => {
      expect(deleteDeviceSensorAdminMock).toHaveBeenCalledWith(123, 77);
    });
    expect(await screen.findByText('No sensors found for this device.')).toBeInTheDocument();
    expect(listDeviceSensorsMock).toHaveBeenCalledTimes(2);

    confirmSpy.mockRestore();
  });
});

it('shows accurate requirements, optional timezone choices, and an explicit inherited-policy gap', async () => {
  render(<MemoryRouter><AdminDeviceEditor /></MemoryRouter>);
  const name = screen.getByRole('textbox', { name: /^Name/ });
  expect(name).toBeRequired();
  expect(name).toHaveAccessibleName('Name *');
  const source = await screen.findByLabelText('Data Source');
  expect(source).not.toBeRequired();
  expect(source).toHaveAccessibleDescription(/Optional/);
  const timezone = screen.getByRole('combobox', { name: 'Timezone' });
  expect(timezone).not.toBeRequired();
  expect(timezone).toHaveValue('');
  fireEvent.change(timezone, { target: { value: 'Asia/Manila' } });
  expect(timezone).toHaveValue('Asia/Manila');
  const policy = screen.getByLabelText('Measurement Updates Policy');
  expect(policy).toHaveAccessibleDescription(/effective inherited policy is unavailable/);
  fireEvent.change(policy, { target: { value: 'deny' } });
  expect(screen.queryByText(/effective inherited policy is unavailable/)).not.toBeInTheDocument();
});

it('allows automatic source assignment, prevents duplicate saves, and preserves input after failure', async () => {
  vi.clearAllMocks();
  let reject!: (error: Error) => void;
  vi.mocked(api.createDeviceAdmin).mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
  render(<MemoryRouter><AdminDeviceEditor /></MemoryRouter>);
  const name = screen.getByRole('textbox', { name: /^Name/ });
  fireEvent.change(name, { target: { value: 'Manual station' } });
  fireEvent.change(screen.getByLabelText('Timezone'), { target: { value: 'Asia/Manila' } });
  const form = name.closest('form')!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  expect(name).toBeDisabled();
  expect(api.createDeviceAdmin).toHaveBeenCalledWith(expect.objectContaining({ name: 'Manual station', timezone: 'Asia/Manila', external_api_id: undefined }));
  expect(api.createDeviceAdmin).toHaveBeenCalledTimes(1);
  reject(new Error('fixture failure'));
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(name).toHaveValue('Manual station');
  expect(screen.getByLabelText('Timezone')).toHaveValue('Asia/Manila');
});

describe('device ownership and task order', () => {
  const renderEditor = () => render(
    <MemoryRouter initialEntries={['/admin/devices/123/edit']}>
      <Routes><Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} /></Routes>
    </MemoryRouter>
  );

  it.each(['OpenAQ', 'PurpleAir', 'AirGradient', 'Demo Data'])('keeps %s reference data outside the local save scope', async provider => {
    const record = { device_id: 123, name: `${provider} station`, friendly_name: 'Library', external_id: 'provider-123', external_api_name: provider, latitude: 0, longitude: 121, timezone: 'Asia/Manila', allow_updates: 'inherit', is_external: true } as api.DeviceRecord;
    vi.mocked(api.getDeviceAdmin).mockResolvedValueOnce(record);
    vi.mocked(api.updateDeviceAdmin).mockResolvedValueOnce({ ...record, friendly_name: 'Community library' });
    const { container } = renderEditor();
    const local = await screen.findByRole('form', { name: 'Local Settings' });
    const providerSection = screen.getByRole('region', { name: 'Provider-managed details' });
    expect(local.compareDocumentPosition(providerSection) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(local).getByRole('button', { name: 'Save changes' })).toBeInTheDocument();
    expect(within(providerSection).queryByRole('textbox')).not.toBeInTheDocument();
    expect(within(providerSection).queryByRole('combobox')).not.toBeInTheDocument();
    expect(within(providerSection).getByText(`Managed by ${provider} · Read-only`)).toBeInTheDocument();
    expect(within(providerSection).getByText('0')).toBeInTheDocument();
    expect(within(providerSection).getByText('Asia/Manila')).toBeInTheDocument();
    const sensors = container.querySelector('#device-sensors')!;
    const metadata = container.querySelector('.meta-card')!;
    expect(sensors.compareDocumentPosition(providerSection) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(sensors.compareDocumentPosition(metadata) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Manage QC' })).toHaveAttribute('href', '/admin/qc/sensors/77');
    expect(screen.queryByRole('button', { name: 'Add Sensor' })).not.toBeInTheDocument();
    expect(screen.getByText(/Manual sensor creation is not available here/)).toBeInTheDocument();
    const friendly = within(local).getByLabelText('Friendly Name');
    fireEvent.change(friendly, { target: { value: 'Community library' } });
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Library');
    fireEvent.click(within(local).getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(api.updateDeviceAdmin).toHaveBeenLastCalledWith(123, { friendly_name: 'Community library', allow_updates: 'inherit' }));
    expect(await within(local).findByText('Device saved successfully.')).toBeInTheDocument();
    await waitFor(() => expect(container.querySelector('.device-save-feedback')).toHaveFocus());
  });

  it('keeps manual location and sensor controls editable and metadata after the workflow', async () => {
    const { container } = renderEditor();
    const local = await screen.findByRole('form', { name: 'Local Settings' });
    expect(within(local).getByLabelText('Latitude')).toBeEnabled();
    expect(within(local).getByLabelText('Longitude')).toBeEnabled();
    expect(within(local).getByLabelText('Timezone')).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Add Sensor' })).toBeEnabled();
    expect(screen.queryByRole('region', { name: 'Provider-managed details' })).not.toBeInTheDocument();
    expect(container.querySelector('.meta-card')!.closest('form')).toBeNull();
    expect(local.compareDocumentPosition(container.querySelector('#device-sensors')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows the custom manual source in the saved location header', async () => {
    vi.mocked(api.getDeviceAdmin).mockResolvedValueOnce({ device_id: 123, name: 'Independent station', external_id: null, external_api_id: 1, external_api_name: 'alpha source', network: 'Local laboratory', manual_data_source_name: 'Local laboratory', is_external: false, timezone: 'UTC', status: 'active', last_seen_at: null });
    render(<MemoryRouter initialEntries={['/admin/devices/123/edit']}><Routes><Route path="/admin/devices/:deviceId/edit" element={<AdminDeviceEditor />} /></Routes></MemoryRouter>);
    expect(await screen.findByText('Local laboratory')).toBeVisible();
    expect(screen.getByLabelText(/Other Data Source Name/)).toHaveValue('Local laboratory');
  });

});
