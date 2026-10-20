import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CompletedDayAqiHistory from '../components/CompletedDayAqiHistory';
import {
  getUsEpaCompletedDayHistory,
  type UsEpaCompletedDayHistoryResult,
  type UsEpaCompletedDayHistorySummary,
} from '../airQualityIndex';


vi.mock('../airQualityIndex', async (importActual) => {
  const actual = await importActual<typeof import('../airQualityIndex')>();
  return { ...actual, getUsEpaCompletedDayHistory: vi.fn() };
});

vi.mock('../components/CompletedDayAqiHistoryChart', () => ({
  default: ({ results, onSelectRepresentedLocalDate }: {
    results: UsEpaCompletedDayHistoryResult[];
    onSelectRepresentedLocalDate: (date: string) => void;
  }) => (
    <div aria-label="History chart test double">
      {results.map((result) => (
        <button
          key={result.represented_local_date}
          type="button"
          onClick={() => onSelectRepresentedLocalDate(result.represented_local_date)}
        >
          Chart {result.represented_local_date}
        </button>
      ))}
    </div>
  ),
}));

const mockedGetHistory = vi.mocked(getUsEpaCompletedDayHistory);
const categories = [
  { code: 'moderate', label: 'Moderate', internal_severity_rank: 2, color: '#FFFF00' },
];

function result(
  representedLocalDate: string,
  overrides: Partial<UsEpaCompletedDayHistoryResult> = {},
): UsEpaCompletedDayHistoryResult {
  return {
    represented_local_date: representedLocalDate,
    local_day_started_at: null,
    local_day_ended_at: null,
    utc_window_started_at: null,
    utc_window_ended_at: null,
    expected_hour_count: 24,
    valid_hour_count: 24,
    required_valid_hour_count: 18,
    required_completeness_fraction: 0.75,
    achieved_completeness_fraction: 1,
    daily_concentration: 26.3,
    preprocessed_concentration: 26.3,
    normalized_unit: 'µg/m³',
    calculation_status: 'calculated',
    coverage_status: 'complete',
    numeric_value: 84,
    category_code: 'moderate',
    category_label: 'Moderate',
    aqi_scale_status: 'within_0_to_500',
    selected_sensor_id: 3,
    blocking_reasons: [],
    audit_flags: [],
    ...overrides,
  };
}

function response(
  results: UsEpaCompletedDayHistoryResult[],
  overrides: Partial<UsEpaCompletedDayHistorySummary> = {},
): UsEpaCompletedDayHistorySummary {
  const calculatedResultCount = results.filter((item) => item.calculation_status === 'calculated').length;
  return {
    standard_code: 'us_epa',
    methodology_version: 'us_epa_aqi_2024',
    result_kind: 'numeric',
    product_code: 'us_epa.pm25.completed_day',
    product_display_name: 'U.S. EPA PM2.5 Completed-Day AQI',
    product_kind: 'completed_day',
    parameter_code: 'pm25',
    methodology_code: 'us_epa_aqi_40_cfr_58_appendix_g',
    methodology_revision: '2024-05',
    methodology_effective_date: '2024-05-06',
    start_local_date: results[0]?.represented_local_date ?? '2026-07-01',
    end_local_date: results[results.length - 1]?.represented_local_date ?? '2026-07-30',
    requested_day_count: results.length,
    returned_device_count: results.length ? 1 : 0,
    returned_result_count: results.length,
    calculated_result_count: calculatedResultCount,
    unavailable_result_count: results.length - calculatedResultCount,
    maximum_supported_day_count: 366,
    detail: 'summary',
    device_series: results.length ? [{
      device_id: 42,
      device_name: 'station-42',
      device_friendly_name: 'Station 42',
      latitude: 38.5,
      longitude: -122.7,
      device_timezone: 'America/Los_Angeles',
      source_name: 'OpenAQ',
      results,
    }] : [],
    ...overrides,
  };
}

function renderHistory(overrides: Partial<React.ComponentProps<typeof CompletedDayAqiHistory>> = {}) {
  return render(
    <CompletedDayAqiHistory
      applicable
      deviceId={42}
      productCode="us_epa.pm25.completed_day"
      productDisplayName="U.S. EPA PM2.5 Completed-Day AQI"
      latestRepresentedLocalDate="2026-07-30"
      externalApiName="openaq"
      categories={categories}
      {...overrides}
    />,
  );
}

describe('CompletedDayAqiHistory', () => {
  beforeEach(() => {
    mockedGetHistory.mockReset();
  });

  it('loads a 30-day summary request and keeps unavailable dates selectable in chart and table', async () => {
    mockedGetHistory.mockResolvedValue(response([
      result('2026-07-29'),
      result('2026-07-30', {
        calculation_status: 'unavailable',
        coverage_status: 'partial',
        numeric_value: null,
        category_code: null,
        category_label: null,
        valid_hour_count: 17,
        blocking_reasons: ['daily_completeness_not_met'],
        audit_flags: ['invalid_observations_rejected'],
      }),
    ]));
    renderHistory();

    expect(screen.getByRole('status')).toHaveTextContent('Loading completed-day history');
    await waitFor(() => expect(mockedGetHistory).toHaveBeenCalledWith({
      product_code: 'us_epa.pm25.completed_day',
      start_local_date: '2026-07-01',
      end_local_date: '2026-07-30',
      device_id: 42,
      external_api_name: 'openaq',
    }, expect.any(AbortSignal)));

    expect(await screen.findByRole('heading', { name: 'July 30, 2026' })).toBeInTheDocument();
    expect(screen.getByText('AQI unavailable')).toBeInTheDocument();
    expect(screen.getAllByText(/Not enough eligible hourly concentrations/).length).toBeGreaterThan(0);
    expect(screen.getByText('Invalid observations were excluded from the completed-day result.')).toBeInTheDocument();

    const table = screen.getByRole('table');
    expect(within(table).getByText('July 29, 2026')).toBeInTheDocument();
    expect(within(table).getByText('July 30, 2026')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Chart 2026-07-29' }));
    expect(screen.getByRole('heading', { name: 'July 29, 2026' })).toBeInTheDocument();
    expect(within(table).getByRole('button', { name: 'Select July 29, 2026' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('does not request while custom dates are edited or invalid, then applies exact valid dates', async () => {
    mockedGetHistory.mockResolvedValue(response([result('2026-07-30')]));
    renderHistory();
    await screen.findByRole('table');
    expect(mockedGetHistory).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Custom' }));
    const startInput = screen.getByLabelText('Start date');
    const endInput = screen.getByLabelText('End date');
    fireEvent.change(startInput, { target: { value: '2026-07-20' } });
    fireEvent.change(endInput, { target: { value: '2026-07-10' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Start date must be on or before end date');
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
    expect(mockedGetHistory).toHaveBeenCalledTimes(1);

    fireEvent.change(endInput, { target: { value: '2026-07-25' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(mockedGetHistory).toHaveBeenCalledTimes(2));
    expect(mockedGetHistory.mock.calls[1][0]).toEqual(expect.objectContaining({
      start_local_date: '2026-07-20',
      end_local_date: '2026-07-25',
    }));
  });

  it('distinguishes request errors, retry, empty series, and all-unavailable results', async () => {
    mockedGetHistory
      .mockRejectedValueOnce(new Error('raw backend failure'))
      .mockResolvedValueOnce(response([]));
    const view = renderHistory();
    expect(await screen.findByRole('alert')).toHaveTextContent('Historical AQI could not be loaded');
    expect(screen.queryByText('raw backend failure')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText(/No completed-day history was returned/)).toBeInTheDocument();

    mockedGetHistory.mockResolvedValue(response([
      result('2026-07-30', {
        calculation_status: 'unavailable',
        numeric_value: null,
        category_code: null,
        category_label: null,
        coverage_status: 'none',
        valid_hour_count: 0,
        blocking_reasons: ['no_valid_hourly_concentrations'],
      }),
    ]));
    view.rerender(
      <CompletedDayAqiHistory
        applicable
        deviceId={42}
        productCode="us_epa.pm10.completed_day"
        productDisplayName="U.S. EPA PM10 Completed-Day AQI"
        latestRepresentedLocalDate="2026-07-30"
        externalApiName="openaq"
        categories={categories}
      />,
    );
    expect(await screen.findByText(/No completed-day AQI values are available/)).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('aborts and ignores an older product response while preserving a custom range', async () => {
    let resolvePm25!: (value: UsEpaCompletedDayHistorySummary) => void;
    let resolvePm10!: (value: UsEpaCompletedDayHistorySummary) => void;
    mockedGetHistory.mockImplementation((query) => new Promise((resolve) => {
      if (query?.product_code.includes('pm10')) resolvePm10 = resolve;
      else resolvePm25 = resolve;
    }));
    const view = renderHistory();
    await waitFor(() => expect(mockedGetHistory).toHaveBeenCalledTimes(1));
    const firstSignal = mockedGetHistory.mock.calls[0][1]!;

    view.rerender(
      <CompletedDayAqiHistory
        applicable
        deviceId={42}
        productCode="us_epa.pm10.completed_day"
        productDisplayName="U.S. EPA PM10 Completed-Day AQI"
        latestRepresentedLocalDate="2026-07-31"
        externalApiName="openaq"
        categories={categories}
      />,
    );
    await waitFor(() => expect(mockedGetHistory).toHaveBeenCalledTimes(2));
    expect(firstSignal.aborted).toBe(true);

    await act(async () => {
      resolvePm25(response([result('2026-07-30')]));
      resolvePm10(response([result('2026-07-31')], {
        product_code: 'us_epa.pm10.completed_day',
        product_display_name: 'U.S. EPA PM10 Completed-Day AQI',
        parameter_code: 'pm10',
      }));
      await Promise.resolve();
    });
    expect(screen.queryByRole('heading', { name: 'July 30, 2026' })).not.toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'July 31, 2026' })).toBeInTheDocument();
  });

  it('is absent and performs no request when history is not applicable', () => {
    renderHistory({ applicable: false, productCode: 'us_epa.pm25.nowcast' });
    expect(screen.queryByText('Completed-day history')).not.toBeInTheDocument();
    expect(mockedGetHistory).not.toHaveBeenCalled();
  });
});
