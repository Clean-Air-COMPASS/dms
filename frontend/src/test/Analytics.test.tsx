import i18n from '../i18n';
import userEvent from '@testing-library/user-event';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import Analytics from '../Analytics';
import { fetchJson, listPublicDataSources } from '../api';
import {
  getAirQualityIndexAnalyticsHistory,
  listAirQualityIndexStandards,
  type AirQualityIndexAnalyticsHistory,
  type AirQualityIndexStandardMetadata,
} from '../airQualityIndex';

vi.mock('../api', async (importActual) => {
  const actual = await importActual<typeof import('../api')>();
  return { ...actual, fetchJson: vi.fn(), listPublicDataSources: vi.fn() };
});

vi.mock('../airQualityIndex', async (importActual) => {
  const actual = await importActual<typeof import('../airQualityIndex')>();
  return {
    ...actual,
    listAirQualityIndexStandards: vi.fn(),
    getAirQualityIndexAnalyticsHistory: vi.fn(),
  };
});

vi.mock('../SensorChart', () => ({
  default: (props: { data: unknown; overlays: unknown[]; aqiSeries: unknown[]; orderedSeriesKeys: string[] }) => (
    <div data-testid="mixed-chart">
      {`measurement:${(props.data ? 1 : 0) + props.overlays.length};aqi:${props.aqiSeries.length};order:${props.orderedSeriesKeys.join(',')}`}
    </div>
  ),
}));

vi.mock('../components/UserMenu', () => ({ default: () => null }));

const standards: AirQualityIndexStandardMetadata[] = [
  {
    standard_code: 'us_epa', display_name: 'U.S. EPA AQI', methodology_version: '2024', result_kind: 'numeric',
    averaging_minutes: 60, required_averaging_period: null, supported_parameter_codes: ['pm25'], normalized_unit: 'AQI', is_default: true,
    categories: [{ code: 'moderate', label: 'Moderate', internal_severity_rank: 2, color: '#ffff00' }],
    default_product_code: 'us_epa.pm25.nowcast', products: [{
      product_code: 'us_epa.pm25.nowcast', display_name: 'PM2.5 NowCast AQI', parameter_code: 'pm25', calculation_code: 'pm_nowcast',
      aggregation_period: '12h_nowcast', aggregation_display_name: 'NowCast', result_scope: 'pollutant', is_parameter_default: true,
      availability_status: 'available', availability_reason: null, history_status: 'available', history_interval: 'utc_hour', maximum_history_interval_count: 2160,
    }],
  },
  {
    standard_code: 'eea_european', display_name: 'European Air Quality Index', methodology_version: '2024', result_kind: 'categorical',
    averaging_minutes: 60, required_averaging_period: '1h', supported_parameter_codes: ['pm25'], normalized_unit: 'µg/m³', is_default: false,
    categories: [{ code: 'good', label: 'Good', internal_severity_rank: 1, color: '#50f0e6' }, { code: 'poor', label: 'Poor', internal_severity_rank: 4, color: '#ff5050' }],
    default_product_code: 'eea_european.overall.hourly', products: [{
      product_code: 'eea_european.overall.hourly', display_name: 'Overall hourly European AQI', parameter_code: null,
      calculation_code: 'worst_available_category', aggregation_period: '1h', aggregation_display_name: 'Hourly', result_scope: 'overall',
      is_parameter_default: false, availability_status: 'available', availability_reason: null, history_status: 'available',
      history_interval: 'utc_hour', maximum_history_interval_count: 2160,
    }],
  },
];

function aqiPoint(overrides: Record<string, unknown> = {}) {
  return {
    observed_at: '2026-08-01T01:00:00Z', interval_started_at: '2026-08-01T00:00:00Z', interval_ended_at: '2026-08-01T01:00:00Z',
    represented_local_date: null, numeric_value: 74, category_code: 'moderate', category_label: 'Moderate', normalized_concentration: 22.1234,
    preprocessed_concentration: 22.1,
    normalized_unit: 'µg/m³', calculation_status: 'calculated' as const, eligibility_status: 'eligible' as const, coverage_status: 'complete' as const,
    exclusion_reason: null, selected_calculation_code: 'pm_nowcast', selected_aggregation_period: '12h_nowcast', dominant_pollutants: ['pm25'],
    available_pollutants: ['pm25'], missing_pollutants: [], ineligible_pollutants: [], ...overrides,
  };
}

const aqiHistory: AirQualityIndexAnalyticsHistory = {
  range_started_at: '2026-08-01T00:00:00Z', range_ended_at: '2026-08-02T00:00:00Z', requested_series_count: 2, returned_series_count: 2,
  maximum_series_count: 6, maximum_hourly_interval_count: 2160, maximum_completed_day_interval_count: 366,
  series: [
    {
      standard_code: 'us_epa', standard_display_name: 'U.S. EPA AQI', methodology_version: '2024', product_code: 'us_epa.pm25.nowcast',
      product_display_name: 'PM2.5 NowCast AQI', parameter_code: 'pm25', calculation_code: 'pm_nowcast', aggregation_period: '12h_nowcast',
      result_kind: 'numeric', result_scope: 'pollutant', history_interval: 'utc_hour', device_id: 1, device_name: 'U.S. Station',
      device_friendly_name: null, device_timezone: 'UTC', source_name: 'OpenAQ', points: [aqiPoint()],
    },
    {
      standard_code: 'eea_european', standard_display_name: 'European Air Quality Index', methodology_version: '2024',
      product_code: 'eea_european.overall.hourly', product_display_name: 'Overall hourly European AQI', parameter_code: null,
      calculation_code: 'worst_available_category', aggregation_period: '1h', result_kind: 'categorical', result_scope: 'overall', history_interval: 'utc_hour',
      device_id: 2, device_name: 'European Station', device_friendly_name: null, device_timezone: 'Europe/Paris', source_name: 'OpenAQ',
      points: [aqiPoint({ numeric_value: null, category_code: 'poor', category_label: 'Poor', coverage_status: 'partial', missing_pollutants: ['no2'] })],
    },
  ],
};

const measurementHistory = {
  sensor_id: 10, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³', device_name: 'Measurement Station',
  device_timezone: 'UTC', external_sensor_id: 'S-10', external_api: { name: 'OpenAQ' },
  data: [{ timestamp: '2026-08-01T01:00:00Z', value: 12.5, is_valid: true, failed_checks: [] }],
};

function LocationProbe() {
  return <output data-testid="location">{useLocation().search}</output>;
}

function renderAnalytics(search: string) {
  return render(<MemoryRouter initialEntries={[`/analytics${search}`]}><Routes><Route path="/analytics" element={<><Analytics /><LocationProbe /></>} /></Routes></MemoryRouter>);
}

describe('unified Analytics workspace', () => {
  it('reports range limits separately from genuine API failure', async () => {
    const { ApiError } = await import('../apiError');
    vi.mocked(getAirQualityIndexAnalyticsHistory).mockRejectedValue(new ApiError({
      status: 400, errorCode: 'aqi_history_range_exceeded', errorContext: { maximum_days: 366 },
    }));
    renderAnalytics('?series=aqi%7Cus_epa%7Cus_epa.pm25.nowcast%7C1&start=2025-01-01T00%3A00%3A00Z&end=2026-08-01T00%3A00%3A00Z');
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose an AQI history range of at most 366 days.');
  });

  it('shows retry for genuine AQI API failure without fabricating an empty series', async () => {
    vi.mocked(getAirQualityIndexAnalyticsHistory).mockRejectedValue(new Error('Network unavailable'));
    renderAnalytics('?series=aqi%7Cus_epa%7Cus_epa.pm25.nowcast%7C1&start=2026-01-01T00%3A00%3A00Z&end=2026-10-06T00%3A00%3A00Z');
    expect(await screen.findByRole('alert')).toHaveTextContent('AQI history could not be loaded. Please retry');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeVisible();
  });
  beforeAll(() => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.open = true; } });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.open = false; } });
  });
  afterEach(async () => { vi.restoreAllMocks(); vi.unstubAllGlobals(); await act(async () => { await i18n.changeLanguage('en'); }); });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAirQualityIndexStandards).mockResolvedValue(standards);
    vi.mocked(getAirQualityIndexAnalyticsHistory).mockResolvedValue(aqiHistory);
    vi.mocked(listPublicDataSources).mockResolvedValue([{ name: 'OpenAQ', filter_value: 'OpenAQ' }]);
    vi.mocked(fetchJson).mockImplementation(async (path) => {
      if (String(path) === '/devices') return [
        { device_id: 1, name: 'U.S. Station', friendly_name: null, timezone: 'UTC', network: 'OpenAQ', sensor_count: 1 },
        { device_id: 2, name: 'European Station', friendly_name: null, timezone: 'Europe/Paris', network: 'OpenAQ', sensor_count: 1 },
      ];
      if (String(path).startsWith('/sensors/10/history')) return measurementHistory;
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it('keeps precise numbers in sorting while formatting summary, table and QC details', async () => {
    vi.mocked(fetchJson).mockResolvedValue({ ...measurementHistory, display_precision: 1,
      data: [
        { timestamp: '2026-08-01T01:00:00Z', value: 17, is_valid: true },
        { timestamp: '2026-08-01T02:00:00Z', value: 2.04, is_valid: true },
        { timestamp: '2026-08-01T03:00:00Z', value: 2.01, is_valid: true },
        { timestamp: '2026-08-01T04:00:00Z', value: null, is_valid: true },
      ] });
    renderAnalytics('?series=measurement%7C10%7Cpm25%7C1h');
    const table = await screen.findByRole('table');
    await waitFor(() => expect(within(table).getAllByRole('row')).toHaveLength(5));
    expect(within(table).getByText('17.0')).toBeVisible();
    expect(within(table).getAllByText('2.0')).toHaveLength(2);
    expect(screen.getByText('Latest').parentElement).toHaveTextContent('—');
    expect(screen.getByText('Average').parentElement).toHaveTextContent('7.0');
    fireEvent.click(within(table).getByRole('columnheader', { name: /Value/ }));
    const rows = within(table).getAllByRole('row').slice(1);
    // Null sorts first. Equal display strings still sort by 2.01 before 2.04.
    expect(rows[1]).toHaveTextContent('03:00:00');
    expect(rows[2]).toHaveTextContent('02:00:00');
    const detail = within(rows[3]).getByText('View QC details').closest('details')!;
    fireEvent.click(within(rows[3]).getByText('View QC details'));
    expect(detail).toHaveTextContent('17.0 µg/m³');
  });

  it('preserves both range boundaries when edits arrive before navigation commits', async () => {
    vi.mocked(fetchJson).mockImplementation(async path => path.startsWith('/sensors/') ? measurementHistory : []);
    renderAnalytics('?series=measurement%7C10%7Cpm25%7C1h&start=2026-08-01T00:00:00Z&end=2026-08-02T00:00:00Z&timezone=utc');
    await screen.findByTestId('mixed-chart');
    const start = screen.getByLabelText('Start:');
    const end = screen.getByLabelText('End:');
    act(() => {
      fireEvent.change(start, { target: { value: '2026-08-01T06:00' } });
      fireEvent.change(end, { target: { value: '2026-08-02T06:00' } });
    });
    await waitFor(() => {
      const query = new URLSearchParams(screen.getByTestId('location').textContent!);
      expect(query.get('start')).toBe('2026-08-01T06:00:00.000Z');
      expect(query.get('end')).toBe('2026-08-02T06:00:00.000Z');
    });
    expect(start).toHaveValue('2026-08-01T06:00');
    expect(end).toHaveValue('2026-08-02T06:00');
    fireEvent.click(screen.getByRole('button', { name: 'Select Data Stream' }));
    const modal = within(await screen.findByRole('dialog', { name: 'Select Data Stream' }));
    expect(modal.getByLabelText('Start date and time')).toHaveValue('2026-08-01T06:00');
    expect(modal.getByLabelText('End date and time')).toHaveValue('2026-08-02T06:00');
  });

  it('owns an editable range across direct entry, modal selection, adding and removing streams', async () => {
    vi.mocked(fetchJson).mockImplementation(async path => {
      if (path === '/parameters') return [{ code: 'pm25', display_name: 'PM2.5' }];
      if (path.startsWith('/measurements/pm25/latest')) return [10, 11].map(id => ({
        sensor_id: id, parameter: 'pm25', unit: 'µg/m³', device: { name: `Synthetic station ${id}` },
      }));
      if (path.startsWith('/sensors/')) {
        const id = Number(path.split('/')[2]);
        return { ...measurementHistory, sensor_id: id, device_name: `Synthetic station ${id}` };
      }
      return [];
    });
    renderAnalytics('');
    const dialog = await screen.findByRole('dialog', { name: 'Select Data Stream' });
    let modal = within(dialog);
    expect(modal.getByLabelText('Start date and time')).toBeEnabled();
    expect(modal.getByLabelText('End date and time')).toBeEnabled();
    expect(modal.getByLabelText('Start date and time')).not.toHaveValue('');
    fireEvent.change(modal.getByLabelText('Start date and time'), { target: { value: '2026-08-01T00:00' } });
    fireEvent.change(modal.getByLabelText('End date and time'), { target: { value: '2026-08-02T00:00' } });
    await modal.findByRole('option', { name: 'PM2.5' });
    fireEvent.change(modal.getByLabelText('Select parameter'), { target: { value: 'pm25' } });
    await waitFor(() => expect(modal.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    fireEvent.click(modal.getByRole('button', { name: 'Load Sensors' }));
    fireEvent.click(await modal.findByRole('button', { name: /Synthetic station 10/ }));
    await screen.findByTestId('mixed-chart');
    const start = screen.getByLabelText('Start:');
    const end = screen.getByLabelText('End:');
    expect(start).toBeEnabled(); expect(end).toBeEnabled();
    fireEvent.change(start, { target: { value: '2026-08-01T06:00' } });
    fireEvent.change(end, { target: { value: '2026-08-02T06:00' } });
    const range = { start: '2026-08-01T06:00:00.000Z', end: '2026-08-02T06:00:00.000Z' };
    fireEvent.click(screen.getByRole('button', { name: 'Select Data Stream' }));
    modal = within(await screen.findByRole('dialog', { name: 'Select Data Stream' }));
    await waitFor(() => expect(modal.getByRole('button', { name: 'Load Sensors' })).toBeEnabled());
    fireEvent.click(modal.getByRole('button', { name: 'Load Sensors' }));
    fireEvent.click(await modal.findByRole('button', { name: /Synthetic station 11/ }));
    await waitFor(() => expect(screen.getByTestId('mixed-chart')).toHaveTextContent('measurement:2'));
    expect(new URLSearchParams(screen.getByTestId('location').textContent!).get('start')).toBe(range.start);
    expect(new URLSearchParams(screen.getByTestId('location').textContent!).get('end')).toBe(range.end);
    vi.mocked(fetchJson).mockClear();
    fireEvent.change(start, { target: { value: '2026-08-01T07:00' } });
    await waitFor(() => expect(vi.mocked(fetchJson).mock.calls.filter(([path]) => path.startsWith('/sensors/'))).toHaveLength(2));
    for (const [path] of vi.mocked(fetchJson).mock.calls.filter(([path]) => path.startsWith('/sensors/'))) {
      const query = new URL(path, 'http://localhost').searchParams;
      expect(query.get('start')).toBe('2026-08-01T07:00:00.000Z'); expect(query.get('end')).toBe(range.end);
    }
    fireEvent.click(await screen.findByRole('button', { name: 'Remove Synthetic station 11 data stream' }));
    await waitFor(() => expect(screen.getByTestId('mixed-chart')).toHaveTextContent('measurement:1'));
    expect(start).toHaveValue('2026-08-01T07:00'); expect(end).toHaveValue('2026-08-02T06:00');
  });

  it.each(['2026-08-02T00:00:00Z', '2026-08-03T00:00:00Z', 'invalid', '2026-08-01T00:00:00', ''])('rejects an invalid deep-link range (%s) without history requests', async start => {
    const query = new URLSearchParams({ series: 'measurement|10|pm25|raw', start, end: '2026-08-02T00:00:00Z' });
    renderAnalytics(`?${query}`);
    expect(await screen.findByRole('alert')).toHaveTextContent('Start must be before End');
    expect(vi.mocked(fetchJson).mock.calls.filter(([path]) => path.startsWith('/sensors/'))).toHaveLength(0);
  });

  it('blocks invalid edits for both measurement and AQI requests and recovers without resetting the range', async () => {
    renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&series=aqi%7Cus_epa%7Cus_epa.pm25.nowcast%7C1&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    await waitFor(() => expect(getAirQualityIndexAnalyticsHistory).toHaveBeenCalled());
    vi.mocked(fetchJson).mockClear(); vi.mocked(getAirQualityIndexAnalyticsHistory).mockClear();
    fireEvent.change(screen.getByLabelText('Start:'), { target: { value: '2026-08-02T00:00' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Start must be before End');
    expect(fetchJson).not.toHaveBeenCalled(); expect(getAirQualityIndexAnalyticsHistory).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('End:'), { target: { value: '' } });
    expect(fetchJson).not.toHaveBeenCalled(); expect(getAirQualityIndexAnalyticsHistory).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('End:'), { target: { value: '2026-08-03T00:00' } });
    await waitFor(() => expect(getAirQualityIndexAnalyticsHistory).toHaveBeenCalledWith('2026-08-02T00:00:00.000Z', '2026-08-03T00:00:00.000Z', expect.any(Array), expect.any(AbortSignal)));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps Map-style entry in the device timezone and uses UTC for missing timezone metadata', async () => {
    vi.mocked(fetchJson).mockResolvedValue({ ...measurementHistory, device_timezone: 'America/New_York' });
    const { unmount } = renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&recency=24h&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    await waitFor(() => expect(screen.getByLabelText('Start:')).toHaveValue('2026-07-31T20:00'));
    unmount();
    vi.mocked(fetchJson).mockResolvedValue({ ...measurementHistory, device_timezone: null });
    renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    await screen.findByTestId('mixed-chart');
    expect(screen.getByLabelText('Start:')).toBeEnabled();
    expect(screen.getByLabelText('Start:')).toHaveValue('2026-08-01T00:00');
    expect(screen.getByText(/Start and End use UTC/)).toBeInTheDocument();
  });

  it('blocks requests for invalid clock text and discards only that draft when the modal closes', async () => {
    renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&timezone=local&start=2026-03-08T06:30:00Z&end=2026-03-08T08:30:00Z');
    await screen.findByTestId('mixed-chart');
    // Use the backend device timezone, independent of the test runner's local zone.
    vi.mocked(fetchJson).mockImplementation(async path => path.startsWith('/sensors/')
      ? { ...measurementHistory, device_timezone: 'America/New_York' } : []);
    fireEvent.change(screen.getByLabelText('Timezone:'), { target: { value: 'stream' } });
    await waitFor(() => expect(screen.getByLabelText('Start:')).toHaveValue('2026-03-08T01:30'));
    fireEvent.click(screen.getByRole('button', { name: 'Select Data Stream' }));
    const modal = within(await screen.findByRole('dialog'));
    await modal.findByRole('button', { name: 'Load Sensors' });
    vi.mocked(fetchJson).mockClear();
    fireEvent.change(modal.getByLabelText('Start date and time'), { target: { value: '2026-03-08T02:30' } });
    expect(modal.getByRole('alert')).toHaveTextContent('daylight-saving');
    expect(modal.getByRole('button', { name: 'Load Sensors' })).toBeDisabled();
    expect(vi.mocked(fetchJson).mock.calls.filter(([path]) => path.startsWith('/sensors/'))).toHaveLength(0);
    fireEvent.click(modal.getByRole('button', { name: 'Cancel' }));
    await screen.findByTestId('mixed-chart');
    expect(screen.getByLabelText('Start:')).toHaveValue('2026-03-08T01:30');
    fireEvent.change(screen.getByLabelText('Start:'), { target: { value: '2026-03-08T02:30' } });
    expect(screen.getByRole('button', { name: 'Select Data Stream' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('daylight-saving');
  });

  for (const language of ['en', 'es']) {
    it.each(['ppm', 'ppb', 'µg/m³', '°C'])(`uses primary-series metadata for every measurement summary in ${language}: %s`, async unit => {
      await act(async () => { await i18n.changeLanguage(language); });
      vi.mocked(fetchJson).mockImplementation(async path => path.startsWith('/sensors/11/')
        ? { ...measurementHistory, sensor_id: 11, unit: '%', data: [{ timestamp: '2026-08-01T01:00:00Z', value: 999 }] }
        : { ...measurementHistory, unit, data: [{ timestamp: '2026-08-01T01:00:00Z', value: 10 }, { timestamp: '2026-08-01T02:00:00Z', value: 20 }] });
      renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&series=measurement%7C11%7Chumidity%7Craw&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
      const latest = await screen.findByText(i18n.t('analytics:analytics.summary.latest'));
      expect(latest.parentElement).toHaveTextContent(`20${unit}`);
      expect(screen.getByText(i18n.t('analytics:analytics.summary.average')).parentElement).toHaveTextContent(`15${unit}`);
      const minMax = screen.getByText(i18n.t('analytics:analytics.summary.minimumMaximum')).parentElement!;
      expect(minMax).toHaveTextContent(`10 / 20${unit}`);
      expect(within(minMax).getAllByText(unit)).toHaveLength(1);
    });
    it(`keeps AQI summaries free of concentration units in ${language}`, async () => {
      await act(async () => { await i18n.changeLanguage(language); });
      renderAnalytics('?series=aqi%7Cus_epa%7Cus_epa.pm25.nowcast%7C1&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
      const latest = await screen.findByText(i18n.t('analytics:analytics.summary.latest'));
      expect(latest.parentElement).toHaveTextContent('74AQI');
      for (const key of ['latest', 'average', 'minimumMaximum'] as const) expect(screen.getByText(i18n.t(`analytics:analytics.summary.${key}`)).parentElement).not.toHaveTextContent('µg/m³');
    });
  }

  it.each(['en', 'es'])('keeps category and concentration units separate in table and CSV in %s', async (language) => {
    await act(async () => { await i18n.changeLanguage(language); });
    vi.mocked(getAirQualityIndexAnalyticsHistory).mockResolvedValue({ ...aqiHistory, series: [aqiHistory.series[1]] });
    renderAnalytics('?series=aqi%7Ceea_european%7Ceea_european.overall.hourly%7C2&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    const category = language === 'en' ? 'Poor' : 'Deficiente';
    const cell = await screen.findByRole('cell', { name: category });
    const cells = within(cell.closest('tr')!).getAllByRole('cell');
    expect(cells[2]).toHaveTextContent(language === 'en' ? 'Category' : 'Categoría');
    expect(cells[2]).not.toHaveTextContent('µg/m³');
    expect(cells[4]).toHaveTextContent(language === 'en' ? 'Processed concentration: 22.1 µg/m³' : 'Concentración procesada: 22,1 µg/m³');
    const createUrl = vi.fn<(blob: Blob) => string>(() => 'blob:category-csv');
    vi.stubGlobal('URL', { createObjectURL: createUrl, revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await userEvent.click(screen.getByRole('button', { name: language === 'en' ? 'Download CSV' : 'Descargar CSV' }));
    const blob = createUrl.mock.calls[0][0] as Blob;
    const csv = await new Promise<string>((resolve) => {
      const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob);
    });
    // CSV Unit continues to qualify the concentration columns; no numeric AQI is invented.
    expect(csv).toContain(`,,,${category},22.1234,22.1,µg/m³,,eligible,partial,`);
    await act(async () => { await i18n.changeLanguage(language === 'en' ? 'es' : 'en'); });
    const translatedCell = screen.getByRole('cell', { name: language === 'en' ? 'Deficiente' : 'Poor' });
    expect(within(translatedCell.closest('tr')!).getAllByRole('cell')[2]).toHaveTextContent(language === 'en' ? 'Categoría' : 'Category');
  });

  it.each(['numeric', 'categorical'] as const)('shows an unavailable %s result without borrowing a concentration unit', async (resultKind) => {
    const series = resultKind === 'numeric' ? aqiHistory.series[0] : aqiHistory.series[1];
    vi.mocked(getAirQualityIndexAnalyticsHistory).mockResolvedValue({ ...aqiHistory, series: [{ ...series, points: [aqiPoint({
      numeric_value: null, category_code: null, category_label: null, normalized_concentration: null,
      preprocessed_concentration: null, normalized_unit: 'µg/m³', calculation_status: 'unavailable', coverage_status: 'none',
    })] }] });
    renderAnalytics(`?series=aqi%7C${series.standard_code}%7C${series.product_code}%7C${series.device_id}&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z`);
    await screen.findByRole('table');
    const cells = within(screen.getByRole('table')).getAllByRole('row')[1].querySelectorAll('td');
    expect(cells[1]).toHaveTextContent('—');
    expect(cells[2]).toHaveTextContent('—');
  });

  it.each(['us_epa', 'philippines_denr'])('keeps numeric %s table results in AQI', async (standardCode) => {
    const productCode = standardCode === 'us_epa' ? 'us_epa.pm25.nowcast' : 'philippines_denr.pm25.completed_day';
    const series = { ...aqiHistory.series[0], standard_code: standardCode, product_code: productCode };
    vi.mocked(listAirQualityIndexStandards).mockResolvedValue([...standards, {
      ...standards[0], standard_code: 'philippines_denr', default_product_code: productCode,
      products: [{ ...standards[0].products[0], product_code: productCode }],
    }]);
    vi.mocked(getAirQualityIndexAnalyticsHistory).mockResolvedValue({ ...aqiHistory, series: [series] });
    renderAnalytics(`?series=aqi%7C${standardCode}%7C${productCode}%7C1&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z`);
    const cell = await screen.findByRole('cell', { name: '74' });
    expect(within(cell.closest('tr')!).getAllByRole('cell')[2]).toHaveTextContent('AQI');
  });

  it('labels a category without a concentration and retains units for concentration-only diagnostics', async () => {
    vi.mocked(getAirQualityIndexAnalyticsHistory).mockResolvedValue({ ...aqiHistory, series: [{ ...aqiHistory.series[1], points: [
      aqiPoint({ numeric_value: null, category_code: 'poor', preprocessed_concentration: null, normalized_concentration: null }),
      aqiPoint({ observed_at: '2026-08-01T02:00:00Z', numeric_value: null, category_code: null, category_label: null, eligibility_status: 'ineligible' }),
    ] }] });
    renderAnalytics('?series=aqi%7Ceea_european%7Ceea_european.overall.hourly%7C2&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    const category = await screen.findByRole('cell', { name: 'Poor' });
    expect(within(category.closest('tr')!).getAllByRole('cell')[2]).toHaveTextContent('Category');
    const diagnostic = screen.getByRole('cell', { name: '22.1' });
    expect(within(diagnostic.closest('tr')!).getAllByRole('cell')[2]).toHaveTextContent('µg/m³');
  });

  it('sorts with Enter and Space and exposes the active direction', async () => {
    const user = userEvent.setup();
    renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    const value = await screen.findByRole('button', { name: /^Value/ });
    value.focus();
    await user.keyboard('{Enter}');
    expect(value.closest('th')).toHaveAttribute('aria-sort', 'ascending');
    await user.keyboard(' ');
    expect(value.closest('th')).toHaveAttribute('aria-sort', 'descending');
    expect(value).toHaveFocus();
  });

  it('explains unavailable AQI beside the chart using the backend reason', async () => {
    vi.mocked(getAirQualityIndexAnalyticsHistory).mockResolvedValue({ ...aqiHistory, series: [{ ...aqiHistory.series[0], points: [aqiPoint({ numeric_value: null, category_code: null, category_label: null, preprocessed_concentration: null, normalized_concentration: null, calculation_status: 'unavailable', coverage_status: 'none', exclusion_reason: 'unsupported_unit' })] }] });
    renderAnalytics('?series=aqi%7Cus_epa%7Cus_epa.pm25.nowcast%7C1&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    const message = await screen.findByText('AQI history is unavailable for this series in the selected time range.');
    expect(message.parentElement).toHaveTextContent(/unsupported unit/i);
    expect(message.closest('section')).toContainElement(screen.getByTestId('mixed-chart'));
  });

  it('keeps a measurement-only view in the approved workspace', async () => {
    renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    expect(await screen.findByText('Measurement Station')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Measurements' })).toBeInTheDocument();
    expect(screen.getByTestId('mixed-chart')).toHaveTextContent('measurement:1;aqi:0');
    expect(getAirQualityIndexAnalyticsHistory).not.toHaveBeenCalled();
    expect(vi.mocked(fetchJson).mock.calls.filter(([path]) => String(path).startsWith('/sensors/')).length).toBe(1);
  });

  it('renders a canonical AirGradient temperature stream with unit and provenance', async () => {
    vi.mocked(fetchJson).mockImplementation(async (path) => {
      if (String(path).startsWith('/sensors/10/history')) return {
        ...measurementHistory,
        parameter: 'temperature',
        parameter_name: 'Temperature',
        unit: '°C',
        device_name: 'São Paulo',
        external_sensor_id: '175911:atmp',
        external_api: { name: 'AirGradient' },
        data: [{ timestamp: '2026-09-03T06:05:40Z', value: 17.6, is_valid: true }],
      };
      return [];
    });

    renderAnalytics('?series=measurement%7C10%7Ctemperature%7C1m&start=2026-09-03T00%3A00%3A00Z&end=2026-09-04T00%3A00%3A00Z');

    expect(await screen.findByText('São Paulo')).toBeInTheDocument();
    expect(screen.getAllByText('Temperature').length).toBeGreaterThan(0);
    expect(screen.getAllByText('AirGradient').length).toBeGreaterThan(0);
    expect(document.body).toHaveTextContent('175911:atmp');
    expect(screen.getAllByText('17.6').length).toBeGreaterThan(0);
    expect(screen.getAllByText('°C').length).toBeGreaterThan(0);
  });

  it('loads measurement and mixed numeric/categorical AQI series into one chart and table', async () => {
    renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&series=aqi%7Cus_epa%7Cus_epa.pm25.nowcast%7C1&series=aqi%7Ceea_european%7Ceea_european.overall.hourly%7C2&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    await waitFor(() => expect(getAirQualityIndexAnalyticsHistory).toHaveBeenCalledTimes(1));
    expect(vi.mocked(getAirQualityIndexAnalyticsHistory).mock.calls[0][2]).toHaveLength(2);
    expect(await screen.findByText(/measurement:1;aqi:2/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Analysis Results' })).toBeInTheDocument();
    expect(screen.getAllByText('PM2.5 NowCast AQI').length).toBeGreaterThan(0);
    expect(screen.getAllByText('12-hour NowCast').length).toBeGreaterThan(0);
    expect(document.body).not.toHaveTextContent('Aggregation 12h_nowcast');
    expect(screen.getAllByText('Poor').length).toBeGreaterThan(0);
    expect(screen.getAllByText('12.5').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Processed concentration: 22.1 µg\/m³/)).toHaveLength(2);
    expect(screen.queryByText(/Processed concentration: 22.1 AQI/)).not.toBeInTheDocument();
    expect(screen.queryByText(/22.1234 µg\/m³/)).not.toBeInTheDocument();
  });

  it('supports one-site source-versus-result analysis with two native measurement resolutions and NowCast AQI', async () => {
    vi.mocked(getAirQualityIndexAnalyticsHistory).mockResolvedValue({ ...aqiHistory, requested_series_count: 1, returned_series_count: 1, series: [aqiHistory.series[0]] });
    renderAnalytics('?series=measurement%7C10%7Cpm25%7C2m&series=measurement%7C10%7Cpm25%7C1h&series=aqi%7Cus_epa%7Cus_epa.pm25.nowcast%7C1&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    await waitFor(() => expect(screen.getByTestId('mixed-chart')).toHaveTextContent('measurement:2;aqi:1'));
    expect(vi.mocked(fetchJson).mock.calls.filter(([path]) => String(path).startsWith('/sensors/10/history')).length).toBe(2);
    const historyRequests = vi.mocked(fetchJson).mock.calls
      .map(([path]) => String(path))
      .filter((path) => path.startsWith('/sensors/10/history'));
    expect(historyRequests.some((path) => path.includes('aggregation=2m'))).toBe(true);
    expect(historyRequests.some((path) => path.includes('aggregation=1h'))).toBe(true);
    expect(getAirQualityIndexAnalyticsHistory).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/order:measurement\|10\|pm25\|2m,measurement\|10\|pm25\|1h,aqi\|us_epa/)).toBeInTheDocument();
  });

  it('keeps resolutions and devices distinct in ordered URL state', async () => {
    vi.mocked(fetchJson).mockImplementation(async (path) => {
      if (String(path).startsWith('/sensors/10/history')) return measurementHistory;
      if (String(path).startsWith('/sensors/11/history')) return { ...measurementHistory, sensor_id: 11, device_name: 'Daily Station' };
      return [];
    });
    renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&series=measurement%7C10%7Cpm25%7C1h&series=measurement%7C11%7Cpm25%7C24h&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    expect(await screen.findByTestId('mixed-chart')).toHaveTextContent('measurement:3;aqi:0');
    expect(screen.getByTestId('location')).toHaveTextContent('series=measurement%7C10%7Cpm25%7Craw');
    expect(vi.mocked(fetchJson).mock.calls.filter(([path]) => String(path).startsWith('/sensors/')).length).toBe(3);
    expect(vi.mocked(fetchJson).mock.calls.some(([path]) => String(path).includes('aggregation=24h'))).toBe(true);
  });

  it('shows stream IDs when same-site pollutant streams would otherwise be indistinguishable', async () => {
    vi.mocked(fetchJson).mockImplementation(async (path) => {
      if (String(path).startsWith('/sensors/10/history')) return measurementHistory;
      if (String(path).startsWith('/sensors/11/history')) return {
        ...measurementHistory,
        sensor_id: 11,
        external_sensor_id: 'S-11',
      };
      return [];
    });
    renderAnalytics('?series=measurement%7C10%7Cpm25%7C1h&series=measurement%7C11%7Cpm25%7C1h&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');

    expect(await screen.findByTestId('mixed-chart')).toHaveTextContent('measurement:2;aqi:0');
    expect(screen.getByRole('columnheader', { name: 'Stream' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'S-10' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'S-11' })).toBeInTheDocument();
  });

  it('preserves measurement intervals and timestamp roles in the table details', async () => {
    vi.mocked(fetchJson).mockImplementation(async (path) => {
      if (String(path).startsWith('/sensors/10/history')) return {
        ...measurementHistory,
        measurement_timestamp_semantics: 'interval_end',
        data: [{
          ...measurementHistory.data[0],
          interval_started_at: '2026-08-01T00:00:00Z',
          interval_ended_at: '2026-08-01T01:00:00Z',
        }],
      };
      return [];
    });
    renderAnalytics('?series=measurement%7C10%7Cpm25%7C1h&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z&timezone=utc');

    expect(await screen.findByText(/Timestamp role: interval end/)).toBeInTheDocument();
    expect(screen.getByText(/Interval:/)).toBeInTheDocument();
  });

  it('preserves successful AQI data when a measurement request fails and removes one comparison deterministically', async () => {
    vi.mocked(fetchJson).mockImplementation(async (path) => {
      if (String(path) === '/devices') return [
        { device_id: 1, name: 'U.S. Station', friendly_name: null, timezone: 'UTC', network: 'OpenAQ', sensor_count: 1 },
        { device_id: 2, name: 'European Station', friendly_name: null, timezone: 'UTC', network: 'OpenAQ', sensor_count: 1 },
      ];
      if (String(path).startsWith('/sensors/10/history')) throw new Error('measurement unavailable');
      return [];
    });
    renderAnalytics('?series=aqi%7Cus_epa%7Cus_epa.pm25.nowcast%7C1&series=aqi%7Ceea_european%7Ceea_european.overall.hourly%7C2&series=measurement%7C10%7Cpm25%7Craw&start=2026-08-01T00%3A00%3A00Z&end=2026-08-02T00%3A00%3A00Z');
    expect(await screen.findByText(/1 measurement series could not be loaded/)).toBeInTheDocument();
    expect(await screen.findByTestId('mixed-chart')).toHaveTextContent('measurement:0;aqi:2');
    fireEvent.click(screen.getByRole('button', { name: /Remove European Station data stream/i }));
    await waitFor(() => expect(screen.getByTestId('location')).not.toHaveTextContent('eea_european'));
    expect(screen.getByTestId('location')).toHaveTextContent('us_epa.pm25.nowcast');
  });

  it('distinguishes review flags from validity without claiming time coverage', async () => {
    vi.mocked(fetchJson).mockResolvedValue({ ...measurementHistory, data: [
      { timestamp: '2026-08-01T01:00:00Z', value: 12.5, is_valid: true, qc_results: [{ check_code: 'baseline_drift', evaluation_status: 'failed', failure_action: 'flag_for_review', passed: false, reason_code: null }], failed_checks: [{ check_code: 'baseline_drift' }] },
      { timestamp: '2026-08-01T02:00:00Z', value: 20000, is_valid: false, failed_checks: [{ check_code: 'max_value' }] },
    ] });
    renderAnalytics('?series=measurement%7C10%7Cpm25%7Craw&start=2026-01-01T00%3A00%3A00Z&end=2026-10-07T00%3A00%3A00Z');
    expect(await screen.findByText('Returned readings')).toBeVisible();
    expect(screen.queryByText('Completeness')).not.toBeInTheDocument();
    expect(await screen.findByText('Flagged for review · Valid')).toBeVisible();
    fireEvent.click(screen.getByText('View QC details'));
    expect(screen.getByText(/Baseline drift/)).toBeInTheDocument();
    expect(screen.queryByText('baseline_drift')).not.toBeInTheDocument();
  });

  it('explains excluded history without inventing a zero-percent validity result', async () => {
    vi.mocked(fetchJson).mockResolvedValue({ ...measurementHistory, history_status: 'no_eligible_observations', data: [] });
    renderAnalytics('?series=measurement%7C10%7Cpm25%7C1h&start=2026-08-01T00:00:00Z&end=2026-08-02T00:00:00Z');
    expect(await screen.findByText(/none are eligible for the selected history/)).toBeVisible();
    expect(screen.queryByText('0% valid')).not.toBeInTheDocument();
  });

});
