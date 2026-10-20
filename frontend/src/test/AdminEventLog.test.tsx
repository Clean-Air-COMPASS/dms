import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AdminEventLog from '../AdminEventLog';
import i18n from '../i18n';

const apiMocks = vi.hoisted(() => ({
  listAllJobRuns: vi.fn(),
  listEvents: vi.fn(),
  listQCFailures: vi.fn(),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return { ...actual, ...apiMocks };
});

const historyMocks = vi.hoisted(() => ({ listJobHistory: vi.fn(), listEventHistory: vi.fn() }));
vi.mock('../eventsHistory', async () => ({ ...await vi.importActual<typeof import('../eventsHistory')>('../eventsHistory'), ...historyMocks }));

function qcFailure(overrides: Record<string, unknown> = {}) {
  return {
    measurement_qc_result_id: 41,
    qc_result_created_at: '2026-08-22T14:31:00Z',
    measurement_id: 9301,
    measurement_observed_at: '2026-08-22T14:30:00Z',
    measurement_value: 18.4,
    measurement_is_valid: true,
    device_id: 12,
    device_name: 'Larchmont, NY',
    sensor_id: 812,
    external_sensor_id: '58376:pm02',
    data_source_id: 2,
    data_source_name: 'PurpleAir',
    provider_code: 'purpleair',
    parameter_code: 'pm25',
    parameter_name: 'PM2.5',
    unit_code: 'ug_m3',
    unit_symbol: 'µg/m³',
    check_code: 'max_value',
    check_name: 'Maximum Value QC Check',
    evaluation_status: 'failed',
    failure_action: 'flag_for_review',
    reason_code: 'above_maximum',
    message: 'Value 18.4 exceeds maximum 10',
    details: { value: 18.4 },
    params_snapshot: { max: 10 },
    rule_source: 'sensor_override',
    policy_snapshot: { default_profile_version: '2026.1' },
    policy_provenance: { 'settings.max': { layer: 'sensor_override' } },
    ...overrides,
  };
}

function qcFailureResponse(items = [qcFailure()], total = items.length) {
  return { items, total, limit: 25, offset: 0 };
}

beforeEach(() => {
  historyMocks.listJobHistory.mockImplementation(async filters => ({ items: await apiMocks.listAllJobRuns(filters), total: 126, options: { status: ['success', 'failed', 'interrupted'], task: ['openaq_import', 'airgradient_import', 'purpleair_import'] } }));
  historyMocks.listEventHistory.mockImplementation(async filters => ({ items: await apiMocks.listEvents(filters), total: 0, options: { event_type: ['auth.login.failed', 'email.test.sent'], source: ['auth', 'email'], severity: ['info', 'error'] } }));
  apiMocks.listAllJobRuns.mockResolvedValue([
    {
      job_run_id: 1,
      job_schedule_id: 1,
      task: 'openaq_import',
      status: 'success',
      started_at: '2026-08-16T14:00:00Z',
      finished_at: '2026-08-16T14:01:00Z',
      summary: {
        devices_processed: 3,
        measurements_received: 286,
        measurements_inserted: 284,
        measurements_skipped: 2,
        qc: { evaluated: 284, passed: 282, flagged: 2, indeterminate: 0 },
      },
    },
    {
      job_run_id: 2,
      job_schedule_id: 2,
      task: 'airgradient_import',
      status: 'success',
      started_at: '2026-08-16T13:00:00Z',
      finished_at: '2026-08-16T13:00:01Z',
      summary: {
        devices_processed: 0,
        measurements_inserted: 0,
        reference_locations_failed: [{ region: 'sao_paulo', location_id: '175911' }],
      },
    },
  ]);
  apiMocks.listEvents.mockResolvedValue([]);
  apiMocks.listQCFailures.mockResolvedValue(qcFailureResponse());
});

afterEach(async () => {
  await i18n.changeLanguage('en');
  vi.clearAllMocks();
});

describe('AdminEventLog', () => {
  it.each(['en', 'es'])('shows a localized CSV outcome, counts and actor (%s)', async language => {
    await i18n.changeLanguage(language);
    apiMocks.listEvents.mockResolvedValueOnce([{
      event_id: 51, event_type: 'csv.upload', source: 'CSV upload', severity: 'warning',
      message: 'Backend diagnostic summary', actor_display_name: 'Synthetic CSV administrator',
      actor_email: 'synthetic@example.test', created_at: '2026-10-06T12:00:00Z',
      params: { outcome: 'partial', inserted_records: 1, updated_records: 2, skipped_records: 3, failed_records: 1, completed_at: '2026-10-06T12:00:01Z' },
    }]);
    render(<MemoryRouter initialEntries={['/admin/events?tab=events']}><AdminEventLog /></MemoryRouter>);
    expect(await screen.findByText(language === 'en' ? 'CSV upload completed with rejected lines' : 'Carga de CSV completada con líneas rechazadas')).toBeInTheDocument();
    expect(screen.getByText(language === 'en' ? /Inserted: 1 · Updated: 2 · Skipped: 3 · Failed: 1/ : /Insertadas: 1 · Actualizadas: 2 · Omitidas: 3 · Fallidas: 1/)).toBeInTheDocument();
    expect(screen.getByText('Synthetic CSV administrator')).toBeInTheDocument();
    expect(screen.queryByText('Backend diagnostic summary')).not.toBeInTheDocument();
  });

  it('names the refresh interval selector through its visible label', async () => {
    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);
    const interval = screen.getByRole('combobox', { name: 'Refresh interval' });
    expect(screen.getByLabelText('Refresh interval')).toBe(interval);
    await userEvent.selectOptions(interval, '60');
    expect(interval).toHaveValue('60');
  });

  it('registers the default 45-second refresh while viewing current history', async () => {
    const intervalSpy = vi.spyOn(globalThis, 'setInterval');
    try {
      render(<MemoryRouter><AdminEventLog /></MemoryRouter>);
      await screen.findByText('Showing 1–25 of 126 matching records');
      const refresh = intervalSpy.mock.calls.find(([, delay]) => delay === 45_000)?.[0];
      expect(typeof refresh).toBe('function');
      const requestCount = historyMocks.listJobHistory.mock.calls.length;
      await act(async () => { if (typeof refresh === 'function') refresh(); });
      await waitFor(() => expect(historyMocks.listJobHistory.mock.calls.length).toBeGreaterThan(requestCount));
    } finally {
      intervalSpy.mockRestore();
    }
  });

  it('keeps job history loading and diagnostic error states visible', async () => {
    let rejectRequest!: (error: Error) => void;
    historyMocks.listJobHistory.mockImplementationOnce(() => new Promise((_, reject) => { rejectRequest = reject; }));
    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);

    expect(screen.getByText('Loading job runs…')).toBeVisible();
    await act(async () => rejectRequest(new Error('Detailed backend failure')));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('History could not be loaded. Use Refresh to try again.');
    await userEvent.click(within(alert).getByText('Error details'));
    expect(within(alert).getByText('Detailed backend failure')).toBeVisible();
  });

  it('explains when no job runs match the current filters', async () => {
    historyMocks.listJobHistory.mockResolvedValueOnce({ items: [], total: 0, options: {} });
    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);
    expect(await screen.findByText('No job runs match this period and these filters. Try other dates or clear a filter.')).toBeVisible();
  });
  it('uses audit name snapshots with email secondary and historic email fallback', async () => {
    apiMocks.listEvents.mockResolvedValue([
      { event_id: 1, event_type: 'profile_updated', source: 'auth', severity: 'info', message: 'Profile updated', created_at: '2026-09-07T10:00:00Z', actor_display_name: 'Jennifer DeWinter', actor_email: 'jennifer@example.com' },
      { event_id: 2, event_type: 'profile_updated', source: 'auth', severity: 'info', message: 'Profile updated', created_at: '2026-09-07T10:00:00Z', actor_display_name: null, actor_email: 'historic@example.com' },
    ]);
    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);
    await userEvent.click(screen.getByRole('tab', { name: 'System events' }));
    expect(await screen.findByText('Jennifer DeWinter')).toBeVisible();
    expect(screen.getByText('jennifer@example.com')).toBeVisible();
    expect(screen.getByText('historic@example.com')).toBeVisible();
  });

  it('renders an interrupted run with its recovery explanation', async () => {
    apiMocks.listAllJobRuns.mockResolvedValue([
      {
        job_run_id: 746,
        job_schedule_id: 1,
        task: 'openaq_import',
        status: 'interrupted',
        started_at: '2026-08-26T05:00:13Z',
        finished_at: '2026-08-27T00:15:00Z',
        summary: null,
        error_message: 'CompassAQ marked this scheduled importer run interrupted because no scheduler still owned its schedule lock.',
      },
    ]);

    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);

    expect(await screen.findByText('Interrupted', { selector: 'span' })).toHaveClass('status-interrupted');
    expect(screen.getByText('CompassAQ marked this scheduled importer run interrupted because no scheduler still owned its schedule lock.')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Interrupted' })).toBeInTheDocument();
  });

  it('renders common importer summaries as concise human language', async () => {
    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);

    const summary = await screen.findByText(
      '3 devices · 286 received · 284 inserted · 2 skipped · QC: 282 passed, 2 flagged',
    );
    expect(summary.closest('td')).toHaveAttribute(
      'title',
      '3 devices · 286 received · 284 inserted · 2 skipped · QC: 282 passed, 2 flagged',
    );
    expect(screen.getByText(/0 devices configured · no measurements requested · AirGradient reference location 175911 \(São Paulo\) could not be loaded/)).toBeInTheDocument();
  });

  it('switches between job runs, system events, and QC failures', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);

    expect((await screen.findAllByText('openaq_import')).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('tab', { name: 'System events' }));
    expect(await screen.findByText('No events match this period and these filters. Try other dates or clear a filter.')).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'QC failures' }));
    expect(await screen.findByText('Larchmont, NY')).toBeInTheDocument();
    expect(apiMocks.listQCFailures).toHaveBeenCalled();
  });

  it('renders QC failure context, effect, message, and provenance', async () => {
    const user = userEvent.setup();
    apiMocks.listQCFailures.mockResolvedValue(qcFailureResponse([
      qcFailure(),
      qcFailure({
        measurement_qc_result_id: 42,
        measurement_id: 9302,
        measurement_is_valid: false,
        failure_action: 'mark_invalid',
        message: 'Value 42 exceeds maximum 10',
      }),
      qcFailure({
        measurement_qc_result_id: 43,
        measurement_id: 9303,
        evaluation_status: 'indeterminate',
        reason_code: 'conversion_not_supported',
        message: 'Cannot safely convert ppm to ug_m3',
        policy_snapshot: { default_profile_version: '2026.1', status: 'unavailable' },
      }),
    ]));
    render(<MemoryRouter initialEntries={['/admin/events?tab=qc-failures']}><AdminEventLog /></MemoryRouter>);

    const flaggedMessage = (await screen.findAllByText('Value 18.4 exceeds maximum 10'))[0];
    const table = screen.getByRole('table');
    const qcTable = within(table);
    expect(qcTable.getAllByText('Larchmont, NY')).toHaveLength(3);
    expect(qcTable.getAllByText('58376:pm02')).toHaveLength(3);
    expect(qcTable.getAllByText('PurpleAir')).toHaveLength(3);
    expect(qcTable.getAllByText('PM2.5')).toHaveLength(3);
    expect(qcTable.getAllByText('Maximum plausible value')).toHaveLength(3);
    expect(qcTable.getByText('Failed — Flag for review')).toBeInTheDocument();
    expect(qcTable.getByText('Failed — Marked invalid')).toBeInTheDocument();
    expect(qcTable.getByText('Unable to evaluate')).toBeInTheDocument();
    expect(qcTable.getByText(
      'This measurement is reported in µg/m³, but this QC rule is defined in ppm. CompassAQ cannot safely convert between these units without temperature and pressure information, so no pass/fail decision was made.',
    )).toBeInTheDocument();
    const flaggedRow = flaggedMessage.closest('tr');
    expect(flaggedRow).not.toBeNull();
    const flaggedFailure = within(flaggedRow as HTMLTableRowElement);
    expect(flaggedFailure.getByText(/18\.4 µg\/m³/)).toBeInTheDocument();

    await user.click(flaggedFailure.getByText('View QC provenance'));
    expect(flaggedFailure.getByText('Sensor override')).toBeInTheDocument();
    expect(flaggedFailure.getByText('above_maximum')).toBeInTheDocument();
    expect(flaggedFailure.getByText('2026.1')).toBeInTheDocument();
    expect(flaggedFailure.getByText('9301')).toBeInTheDocument();

    const indeterminateMessage = screen.getByText(
      'This measurement is reported in µg/m³, but this QC rule is defined in ppm. CompassAQ cannot safely convert between these units without temperature and pressure information, so no pass/fail decision was made.',
    );
    const indeterminateRow = indeterminateMessage.closest('tr');
    expect(indeterminateRow).not.toBeNull();
    const indeterminateFailure = within(indeterminateRow as HTMLTableRowElement);
    await user.click(indeterminateFailure.getByText('View QC provenance'));
    expect(indeterminateFailure.getByText('conversion_not_supported')).toBeInTheDocument();
    expect(indeterminateFailure.getByText('Cannot safely convert ppm to ug_m3')).toBeInTheDocument();
    expect(indeterminateFailure.getByText('unavailable')).toBeInTheDocument();
  });

  it('renders Baseline Drift values and direction in English and Spanish', async () => {
    const user = userEvent.setup();
    apiMocks.listQCFailures.mockResolvedValue(qcFailureResponse([
      qcFailure({
        check_code: 'baseline_drift',
        check_name: 'Baseline Drift QC Check',
        details: { value: 18.4, drift_per_day: 2.32 },
        params_snapshot: { max_drift_per_day: 0, direction: 'both' },
      }),
    ]));
    const { unmount } = render(
      <MemoryRouter initialEntries={['/admin/events?tab=qc-failures']}><AdminEventLog /></MemoryRouter>,
    );

    await user.click(await screen.findByText('View QC provenance'));
    expect(screen.getByText('Baseline shift indicator')).toBeInTheDocument();
    expect(screen.getByText('Configured maximum indicator')).toBeInTheDocument();
    expect(screen.getByText('2.32 µg/m³/day')).toBeInTheDocument();
    expect(screen.getByText('0 µg/m³/day')).toBeInTheDocument();
    expect(screen.getByText('Both directions')).toBeInTheDocument();

    unmount();
    await i18n.changeLanguage('es');
    render(<MemoryRouter initialEntries={['/admin/events?tab=qc-failures']}><AdminEventLog /></MemoryRouter>);
    await user.click(await screen.findByText('Ver procedencia de CC'));
    expect(screen.getByText('Indicador de cambio de línea base')).toBeInTheDocument();
    expect(screen.getByText('Indicador máximo configurado')).toBeInTheDocument();
    expect(screen.getByText('2,32 µg/m³/día')).toBeInTheDocument();
    expect(screen.getByText('0 µg/m³/día')).toBeInTheDocument();
    expect(screen.getByText('Ambas direcciones')).toBeInTheDocument();
  });

  it('states explicitly when no QC failures were found', async () => {
    apiMocks.listQCFailures.mockResolvedValue(qcFailureResponse([]));
    render(<MemoryRouter initialEntries={['/admin/events?tab=qc-failures']}><AdminEventLog /></MemoryRouter>);

    expect(await screen.findByText(
      'No QC issues were found. QC may still be running and passing measurements.',
    )).toBeInTheDocument();
  });

  it('applies QC filters and server-side pagination', async () => {
    const user = userEvent.setup();
    apiMocks.listQCFailures.mockResolvedValue(qcFailureResponse([qcFailure()], 26));
    render(<MemoryRouter initialEntries={['/admin/events?tab=qc-failures']}><AdminEventLog /></MemoryRouter>);
    await screen.findByText('Larchmont, NY');

    await user.type(screen.getByLabelText('Search:'), 'Larchmont');
    await user.type(screen.getByLabelText('Parameter:'), 'pm25');
    await user.selectOptions(screen.getByLabelText('Effect:'), 'mark_invalid');
    await user.type(screen.getByLabelText('Data source:'), 'purpleair');
    await waitFor(() => expect(apiMocks.listQCFailures).toHaveBeenLastCalledWith({
      limit: 25,
      offset: 0,
      search: 'Larchmont',
      parameter: 'pm25',
      status: undefined,
      outcome: 'mark_invalid',
      data_source: 'purpleair',
    }));

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(apiMocks.listQCFailures).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 25 }),
    ));
  });

  it('filters QC issues by failed or unable-to-evaluate status', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={['/admin/events?tab=qc-failures']}><AdminEventLog /></MemoryRouter>);
    await screen.findByText('Larchmont, NY');

    await user.selectOptions(screen.getByLabelText('Status:'), 'indeterminate');
    await waitFor(() => expect(apiMocks.listQCFailures).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'indeterminate', offset: 0 }),
    ));
  });

  it('renders the QC failures view in Spanish with mobile card labels', async () => {
    await i18n.changeLanguage('es');
    apiMocks.listQCFailures.mockResolvedValue(qcFailureResponse([
      qcFailure({
        evaluation_status: 'indeterminate',
        reason_code: 'conversion_not_supported',
        message: 'No se puede convertir de forma segura',
      }),
    ]));
    window.innerWidth = 390;
    window.dispatchEvent(new Event('resize'));
    render(<MemoryRouter initialEntries={['/admin/events?tab=qc-failures']}><AdminEventLog /></MemoryRouter>);

    expect(await screen.findByRole('tab', { name: 'Fallas de CC' })).toHaveAttribute('aria-selected', 'true');
    const table = screen.getByRole('table');
    expect(table).toHaveClass('qc-failure-table');
    expect(within(table).getByText('No se puede evaluar')).toBeInTheDocument();
    expect(within(table).getByText(/Esta medición se informa en µg\/m³/)).toBeInTheDocument();
    const deviceCell = within(table).getByText('Larchmont, NY').closest('td');
    expect(deviceCell).toHaveAttribute('data-label', 'Dispositivo');
  });
});


describe('operational history navigation', () => {
  it('pages beyond 100 records and resets the page when filtering', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);
    await screen.findByText('Showing 1–25 of 126 matching records');
    for (let page = 1; page <= 4; page++) {
      await user.click(screen.getByRole('button', { name: 'Next' }));
      await waitFor(() => expect(historyMocks.listJobHistory).toHaveBeenLastCalledWith(expect.objectContaining({ offset: page * 25 })));
    }
    expect(screen.getByText('Showing 101–125 of 126 matching records')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Task:'), 'purpleair_import');
    await waitFor(() => expect(historyMocks.listJobHistory).toHaveBeenLastCalledWith(expect.objectContaining({ task: 'purpleair_import', offset: 0 })));
    expect(screen.getByRole('option', { name: 'OpenAQ import' })).toBeInTheDocument();
  });

  it('applies inclusive UTC days and rejects reversed dates without fetching', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);
    await screen.findByText('Showing 1–25 of 126 matching records');
    fireEvent.change(screen.getByLabelText('From date (UTC)'), { target: { value: '2020-01-02' } });
    fireEvent.change(screen.getByLabelText('Through date (UTC)'), { target: { value: '2020-01-01' } });
    expect(screen.getByRole('button', { name: 'Apply dates' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('The end date');
    fireEvent.change(screen.getByLabelText('Through date (UTC)'), { target: { value: '2020-01-02' } });
    await user.click(screen.getByRole('button', { name: 'Apply dates' }));
    await waitFor(() => expect(historyMocks.listJobHistory).toHaveBeenLastCalledWith(expect.objectContaining({ started_after: '2020-01-02T00:00:00Z', started_before: '2020-01-03T00:00:00.000Z', offset: 0 })));
  });

  it('provides one tab stop and arrow, Home, and End navigation with linked panels', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><AdminEventLog /></MemoryRouter>);
    const jobs = screen.getByRole('tab', { name: 'Job Runs' });
    jobs.focus();
    await user.keyboard('{ArrowRight}');
    const events = screen.getByRole('tab', { name: 'System events' });
    expect(events).toHaveFocus();
    expect(events).toHaveAttribute('tabindex', '0');
    expect(jobs).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', events.id);
    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'QC failures' })).toHaveFocus();
    await user.keyboard('{Home}{ArrowLeft}');
    expect(screen.getByRole('tab', { name: 'QC failures' })).toHaveFocus();
  });

  it('ignores an older request that finishes after a filter change', async () => {
    let resolveOld!: (value: unknown) => void;
    historyMocks.listJobHistory.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={['/admin/events?task=openaq_import']}><AdminEventLog /></MemoryRouter>);
    await user.selectOptions(screen.getByLabelText('Task:'), '');
    await screen.findByText('Showing 1–25 of 126 matching records');
    await act(async () => resolveOld({ items: [], total: 999, options: {} }));
    expect(screen.queryByText(/999 matching/)).not.toBeInTheDocument();
    expect(screen.getByText('Showing 1–25 of 126 matching records')).toBeInTheDocument();
  });

  it.each(['success', 'failure'])('ignores a stale QC %s after changing the effect filter', async staleResult => {
    let resolveOld!: (value: ReturnType<typeof qcFailureResponse>) => void;
    let rejectOld!: (reason: Error) => void;
    apiMocks.listQCFailures.mockImplementationOnce(() => new Promise((resolve, reject) => { resolveOld = resolve; rejectOld = reject; }));
    apiMocks.listQCFailures.mockResolvedValue(qcFailureResponse([qcFailure({ device_name: 'Filtered invalid station', failure_action: 'mark_invalid', measurement_is_valid: false })]));
    render(<MemoryRouter initialEntries={['/admin/events?tab=qc-failures']}><AdminEventLog /></MemoryRouter>);
    await userEvent.selectOptions(screen.getByLabelText('Effect:'), 'mark_invalid');
    await screen.findByText('Filtered invalid station');
    await act(async () => {
      if (staleResult === 'success') resolveOld(qcFailureResponse([qcFailure({ device_name: 'Stale flagged station' })]));
      else rejectOld(new Error('Old request failed'));
    });
    expect(screen.getByText('Filtered invalid station')).toBeVisible();
    expect(screen.queryByText('Stale flagged station')).not.toBeInTheDocument();
    expect(screen.queryByText('Old request failed')).not.toBeInTheDocument();
  });

});
