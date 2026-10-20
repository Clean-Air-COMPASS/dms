import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import i18n from '../i18n';
import { ApiError } from '../apiError';
import AdminQcSensorPolicy from '../qc/AdminQcSensorPolicy';
import AdminQcSensorSearch from '../qc/AdminQcSensorSearch';
import type {
  QcCheckMetadata,
  QcPolicyLayer,
  QcPolicyResponse,
  QcPreviewResponse,
  QcResolvedCheck,
  QcSensorSearchItem,
} from '../qc/types';

const qcApiMocks = vi.hoisted(() => ({
  getSensorPolicy: vi.fn(),
  listQcChecks: vi.fn(),
  listQcParameters: vi.fn(),
  previewQcPolicy: vi.fn(),
  replaceSensorPolicy: vi.fn(),
  resetSensorCheck: vi.fn(),
  resetSensorPolicy: vi.fn(),
  searchQcSensors: vi.fn(),
}));

vi.mock('../qc/api', async () => {
  const actual = await vi.importActual<typeof import('../qc/api')>('../qc/api');
  return { ...actual, ...qcApiMocks };
});

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    listExternalAPIs: vi.fn().mockResolvedValue([
      { external_api_id: 3, name: 'AirGradient', enabled: true },
      { external_api_id: 4, name: 'OpenAQ', enabled: true },
    ]),
  };
});

const unit = {
  unit_id: 1,
  unit_code: 'ug_m3',
  symbol: 'µg/m³',
  name: 'micrograms per cubic metre',
};

const sourceLayer: QcPolicyLayer = {
  layer: 'source_override',
  label: 'technical source label',
  qc_rule_id: 20,
  rule_version: 1,
  default_profile_version: null,
  policy_unit_code: 'ug_m3',
};

const sensorLayer: QcPolicyLayer = {
  layer: 'sensor_override',
  label: 'technical sensor label',
  qc_rule_id: 30,
  rule_version: 1,
  default_profile_version: null,
  policy_unit_code: 'ug_m3',
};

const metadata: QcCheckMetadata[] = [
  {
    check_code: 'min_value',
    display_name: 'Minimum value',
    description: 'technical minimum',
    available: true,
    plugin_version: '1',
    qc_api: 1,
    origin: 'built_in',
    required_access: 'api-only',
    unit_settings: ['min'],
    overview: { visible: true, label: 'Minimum', order: 10, summary_setting: 'min' },
    settings: [{ setting_code: 'min', value_type: 'number', label: 'Minimum', help_text: 'technical', required: true, choices: null }],
    failure_actions: ['flag_for_review', 'mark_invalid'],
  },
  {
    check_code: 'max_value',
    display_name: 'Maximum value',
    description: 'technical maximum',
    available: true,
    plugin_version: '1',
    qc_api: 1,
    origin: 'built_in',
    required_access: 'api-only',
    unit_settings: ['max'],
    overview: { visible: true, label: 'Maximum', order: 20, summary_setting: 'max' },
    settings: [{ setting_code: 'max', value_type: 'number', label: 'Maximum', help_text: 'technical', required: true, choices: null }],
    failure_actions: ['flag_for_review', 'mark_invalid'],
  },
  {
    check_code: 'spike_detection',
    display_name: 'Spike detection',
    description: 'technical unavailable check',
    available: false,
    plugin_version: null,
    qc_api: null,
    origin: null,
    required_access: null,
    unit_settings: [],
    overview: { visible: true, label: 'Spike Detection', order: 40, summary_setting: null },
    settings: [],
    failure_actions: ['flag_for_review', 'mark_invalid'],
  },
  {
    check_code: 'reference_threshold',
    display_name: 'Reference Threshold QC Check',
    description: 'application-unknown test check',
    available: true,
    plugin_version: '1',
    qc_api: 1,
    origin: 'entry_point',
    required_access: 'api-only',
    unit_settings: [],
    overview: { visible: true, label: 'Reference Threshold', order: 40, summary_setting: 'limit' },
    settings: [{ setting_code: 'limit', value_type: 'number', label: 'Threshold', help_text: 'test only', required: true, choices: null }],
    failure_actions: ['flag_for_review', 'mark_invalid'],
  },
];

function resolvedCheck(options: {
  checkCode: string;
  settingCode: string;
  value: number;
  inheritedValue?: number;
  currentLayer?: QcPolicyLayer;
  inheritedLayer?: QcPolicyLayer;
  status?: 'ready' | 'disabled' | 'unavailable';
  reasonCode?: string | null;
}): QcResolvedCheck {
  const inheritedValue = options.inheritedValue ?? options.value;
  const inheritedLayer = options.inheritedLayer ?? sourceLayer;
  const currentLayer = options.currentLayer ?? inheritedLayer;
  const inherited = {
    check_code: options.checkCode,
    status: 'ready' as const,
    enabled: true,
    failure_action: 'flag_for_review' as const,
    configured_settings: { [options.settingCode]: inheritedValue },
    evaluation_settings: { [options.settingCode]: inheritedValue },
    configured_unit_code: 'ug_m3',
    evaluation_unit_code: 'ug_m3',
    applicable_unit_code: 'ug_m3',
    unit_conversion: { status: 'exact' },
    reason_code: null,
    message: '',
    applicability: 'applicable' as const,
    default_profile_version: '2026.1',
    applied_layers: [inheritedLayer],
    most_specific_source: inheritedLayer,
    property_provenance: {
      enabled: inheritedLayer,
      failure_action: inheritedLayer,
      unit: inheritedLayer,
      [`settings.${options.settingCode}`]: inheritedLayer,
    },
  };
  return {
    ...inherited,
    status: options.status ?? 'ready',
    reason_code: options.reasonCode ?? null,
    configured_settings: { [options.settingCode]: options.value },
    evaluation_settings: { [options.settingCode]: options.value },
    applied_layers: [inheritedLayer, ...(currentLayer === inheritedLayer ? [] : [currentLayer])],
    most_specific_source: currentLayer,
    property_provenance: {
      ...inherited.property_provenance,
      [`settings.${options.settingCode}`]: currentLayer,
    },
    inherited_policy: inherited,
  };
}

function sensorPolicy(overrides = true): QcPolicyResponse {
  return {
    scope: { scope_type: 'sensor', parameter_id: 7, external_api_id: 3, sensor_id: 812 },
    parameter: { parameter_id: 7, parameter_code: 'pm25', display_name: 'PM2.5', default_unit: unit, supported_units: [unit] },
    data_source: { external_api_id: 3, provider_code: 'airgradient', name: 'AirGradient' },
    sensor: {
      sensor_id: 812,
      external_sensor_id: 'AG-12345',
      device_id: 44,
      device_name: 'Bakersfield Downtown',
      display_label: 'technical display label',
      parameter: { parameter_id: 7, parameter_code: 'pm25', display_name: 'PM2.5', default_unit: unit, supported_units: [unit] },
      unit,
      data_source: { external_api_id: 3, provider_code: 'airgradient', name: 'AirGradient' },
      aggregation_code: '1h',
    },
    default_profile_version: '2026.1',
    overrides: overrides ? [{
      qc_rule_id: 30,
      check_code: 'max_value',
      enabled_override: null,
      failure_action_override: null,
      settings: { max: 700 },
      policy_unit: unit,
      version: 1,
      overridden_properties: ['settings.max', 'unit'],
      updated_at: null,
    }] : [],
    checks: [
      resolvedCheck({ checkCode: 'min_value', settingCode: 'min', value: -5 }),
      resolvedCheck({
        checkCode: 'max_value',
        settingCode: 'max',
        value: overrides ? 700 : 800,
        inheritedValue: 800,
        currentLayer: overrides ? sensorLayer : sourceLayer,
      }),
    ],
    advanced_aggregation_override_count: 0,
  };
}

function sensorSearchItem(options: Partial<QcSensorSearchItem> = {}): QcSensorSearchItem {
  return {
    ...sensorPolicy().sensor!,
    override_check_count: 0,
    has_overrides: false,
    advanced_override_count: 0,
    has_sensor_specific_qc: false,
    ...options,
  };
}

function previewWithoutMeasurements(policy: QcPolicyResponse): QcPreviewResponse {
  return {
    preview_since: '2026-08-17T00:00:00Z',
    preview_until: '2026-08-18T00:00:00Z',
    hours: 24,
    sample_limit: 2000,
    samples_available: 0,
    samples_evaluated: 0,
    truncated: false,
    checks: [],
    candidate_policy: policy,
  };
}

describe('Phase 2B sensor quality control', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage('en');
    qcApiMocks.listQcChecks.mockResolvedValue(metadata);
    qcApiMocks.listQcParameters.mockResolvedValue({
      default_profile_version: '2026.1',
      items: [{
        ...sensorPolicy().parameter,
        supported: true,
        sensor_count: 2,
        parameter_override_count: 0,
        source_override_count: 0,
        sensor_override_count: 0,
        source_exception_count: 0,
        sensor_exception_count: 0,
        baseline_drift_source_override_count: 0,
        baseline_drift_sensor_override_count: 0,
        baseline_drift_enabled_source_count: 0,
        baseline_drift_enabled_sensor_count: 0,
        checks: [],
      }],
      total: 1,
    });
  });

  it('searches by human sensor identity and distinguishes inherited, custom, and advanced QC', async () => {
    qcApiMocks.searchQcSensors.mockResolvedValue({
      items: [
        sensorSearchItem(),
        sensorSearchItem({ sensor_id: 813, external_sensor_id: 'AG-999', device_name: 'Bakersfield North', has_overrides: true, has_sensor_specific_qc: true, override_check_count: 1 }),
        sensorSearchItem({ sensor_id: 814, external_sensor_id: null, device_name: 'Bakersfield Mobile', has_sensor_specific_qc: true, advanced_override_count: 1 }),
      ],
      total: 3,
      limit: 25,
      offset: 0,
    });

    render(<MemoryRouter initialEntries={['/admin/qc/sensors']}><AdminQcSensorSearch /></MemoryRouter>);

    expect(await screen.findByText('Bakersfield Downtown')).toBeInTheDocument();
    expect(screen.getByText('Sensor AG-12345')).toBeInTheDocument();
    expect(screen.getByText('Uses normal inherited QC')).toBeInTheDocument();
    expect(screen.getAllByText('Custom sensor QC')).toHaveLength(2);
    expect(screen.getByText('Advanced sensor QC applies')).toBeInTheDocument();
    expect(screen.getByText('Internal sensor 814')).toBeInTheDocument();

    await userEvent.click(screen.getByText('Filters'));
    await userEvent.selectOptions(screen.getByLabelText('QC status'), 'custom');
    await waitFor(() => expect(qcApiMocks.searchQcSensors).toHaveBeenLastCalledWith(expect.objectContaining({
      hasSensorSpecificQc: true,
      offset: 0,
    })));

    await userEvent.selectOptions(screen.getByLabelText('Parameter'), '7');
    await userEvent.selectOptions(screen.getByLabelText('Data source'), '3');
    await waitFor(() => expect(qcApiMocks.searchQcSensors).toHaveBeenLastCalledWith(expect.objectContaining({
      parameterId: 7,
      externalApiId: 3,
      hasSensorSpecificQc: true,
    })));

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search sensors' }), 'AG-12345');
    await waitFor(() => expect(qcApiMocks.searchQcSensors).toHaveBeenLastCalledWith(expect.objectContaining({ query: 'AG-12345' })));
  });

  it('shows search loading, error, retry, and no-match states', async () => {
    let rejectSearch: ((reason?: unknown) => void) | undefined;
    qcApiMocks.searchQcSensors.mockImplementationOnce(() => new Promise((_resolve, reject) => {
      rejectSearch = reject;
    }));

    render(<MemoryRouter initialEntries={['/admin/qc/sensors?q=missing']}><AdminQcSensorSearch /></MemoryRouter>);

    expect(screen.getByText('Loading sensors…')).toBeInTheDocument();
    rejectSearch?.(new Error('search unavailable'));
    expect(await screen.findByText('Sensors could not be loaded.')).toBeInTheDocument();

    qcApiMocks.searchQcSensors.mockResolvedValueOnce({ items: [], total: 0, limit: 25, offset: 0 });
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'No sensors match' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
  });

  it('distinguishes an empty sensor inventory from a filtered no-match result', async () => {
    qcApiMocks.searchQcSensors.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });

    render(<MemoryRouter initialEntries={['/admin/qc/sensors']}><AdminQcSensorSearch /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: 'No sensors available' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument();
  });

  it('keeps sensor-search pagination in the URL-backed query', async () => {
    qcApiMocks.searchQcSensors.mockResolvedValue({
      items: [sensorSearchItem()],
      total: 26,
      limit: 25,
      offset: 0,
    });

    render(<MemoryRouter initialEntries={['/admin/qc/sensors']}><AdminQcSensorSearch /></MemoryRouter>);

    await screen.findByText('Bakersfield Downtown');
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(qcApiMocks.searchQcSensors).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 })));
  });

  it('shows the effective value and property-level source without exposing technical provenance', async () => {
    qcApiMocks.getSensorPolicy.mockResolvedValue(sensorPolicy());
    render(
      <MemoryRouter initialEntries={['/admin/qc/sensors/812']}>
        <Routes><Route path="/admin/qc/sensors/:sensorId" element={<AdminQcSensorPolicy />} /></Routes>
      </MemoryRouter>,
    );

    const contextHeading = await screen.findByRole('heading', { name: 'Bakersfield Downtown', level: 2 });
    await waitFor(() => expect(contextHeading).toHaveFocus());
    expect(screen.getByText('1 custom setting for this sensor')).toBeInTheDocument();
    expect(screen.getAllByText('AirGradient PM2.5 setting').length).toBeGreaterThan(0);
    expect(screen.getByText('Custom for this sensor')).toBeInTheDocument();
    expect(screen.getByText('700 µg/m³')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Reference Threshold QC Check' })).toBeInTheDocument();
    expect(screen.queryByText('technical sensor label')).not.toBeInTheDocument();
    expect(screen.queryByText('sensor_override')).not.toBeInTheDocument();
  });

  it('saves only the edited sensor property and keeps unrelated checks inherited', async () => {
    const current = sensorPolicy();
    const updated = sensorPolicy();
    updated.overrides[0].settings = { max: 650 };
    updated.checks[1].configured_settings = { max: 650 };
    updated.checks[1].evaluation_settings = { max: 650 };
    qcApiMocks.getSensorPolicy.mockResolvedValue(current);
    qcApiMocks.replaceSensorPolicy.mockResolvedValue(updated);

    render(
      <MemoryRouter initialEntries={['/admin/qc/sensors/812']}>
        <Routes><Route path="/admin/qc/sensors/:sensorId" element={<AdminQcSensorPolicy />} /></Routes>
      </MemoryRouter>,
    );
    const maximumCard = (await screen.findByRole('heading', { name: 'Maximum plausible value' })).closest('article')!;
    await userEvent.click(within(maximumCard).getByRole('button', { name: 'Edit settings' }));
    const sensorUnitSelector = within(maximumCard).getByRole('combobox', { name: 'Unit' });
    expect(within(sensorUnitSelector).getAllByRole('option')).toHaveLength(1);
    expect(sensorUnitSelector).toHaveValue('ug_m3');
    const maximumInput = within(maximumCard).getByLabelText('Maximum plausible value');
    await userEvent.clear(maximumInput);
    await userEvent.type(maximumInput, '650');
    await userEvent.click(within(maximumCard).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(qcApiMocks.replaceSensorPolicy).toHaveBeenCalledWith(812, [{
      check_code: 'max_value',
      enabled_override: null,
      failure_action_override: null,
      settings: { max: 650 },
      policy_unit_code: 'ug_m3',
    }]));
    expect(await screen.findByText('Sensor quality control saved.')).toBeInTheDocument();
  });

  it('keeps sensor edits open after a backend validation failure', async () => {
    qcApiMocks.getSensorPolicy.mockResolvedValue(sensorPolicy());
    qcApiMocks.replaceSensorPolicy.mockRejectedValue(new ApiError({
      status: 422,
      errorCode: 'invalid_policy_setting',
    }));

    render(
      <MemoryRouter initialEntries={['/admin/qc/sensors/812']}>
        <Routes><Route path="/admin/qc/sensors/:sensorId" element={<AdminQcSensorPolicy />} /></Routes>
      </MemoryRouter>,
    );
    const maximumCard = (await screen.findByRole('heading', { name: 'Maximum plausible value' })).closest('article')!;
    await userEvent.click(within(maximumCard).getByRole('button', { name: 'Edit settings' }));
    const maximumInput = within(maximumCard).getByLabelText('Maximum plausible value');
    await userEvent.clear(maximumInput);
    await userEvent.type(maximumInput, '650');
    await userEvent.click(within(maximumCard).getByRole('button', { name: 'Save changes' }));

    expect(await within(maximumCard).findByText('One or more configured values are invalid.')).toBeInTheDocument();
    expect(within(maximumCard).getByLabelText('Maximum plausible value')).toHaveValue(650);
    expect(within(maximumCard).getByRole('button', { name: 'Save changes' })).toBeInTheDocument();
  });

  it('resets one property through the sparse editor and still allows saving without preview data', async () => {
    const current = sensorPolicy();
    const inherited = sensorPolicy(false);
    qcApiMocks.getSensorPolicy.mockResolvedValue(current);
    qcApiMocks.previewQcPolicy.mockResolvedValue(previewWithoutMeasurements(inherited));
    qcApiMocks.replaceSensorPolicy.mockResolvedValue(inherited);

    render(
      <MemoryRouter initialEntries={['/admin/qc/sensors/812']}>
        <Routes><Route path="/admin/qc/sensors/:sensorId" element={<AdminQcSensorPolicy />} /></Routes>
      </MemoryRouter>,
    );
    const maximumCard = (await screen.findByRole('heading', { name: 'Maximum plausible value' })).closest('article')!;
    await userEvent.click(within(maximumCard).getByRole('button', { name: 'Edit settings' }));
    await userEvent.click(within(maximumCard).getByRole('button', { name: 'Use AirGradient PM2.5 setting' }));
    await userEvent.click(within(maximumCard).getByRole('button', { name: 'Preview impact' }));
    expect(await within(maximumCard).findByText('No recent measurements are available to preview this change.')).toBeInTheDocument();
    expect(within(maximumCard).getByRole('button', { name: 'Save changes' })).toBeEnabled();
    await userEvent.click(within(maximumCard).getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(qcApiMocks.replaceSensorPolicy).toHaveBeenCalledWith(812, []));
  });

  it('confirms a check reset without implying parent or advanced settings are removed', async () => {
    const current = sensorPolicy();
    const inherited = sensorPolicy(false);
    qcApiMocks.getSensorPolicy.mockResolvedValue(current);
    qcApiMocks.resetSensorCheck.mockResolvedValue(inherited);
    qcApiMocks.resetSensorPolicy.mockResolvedValue(inherited);

    render(
      <MemoryRouter initialEntries={['/admin/qc/sensors/812']}>
        <Routes><Route path="/admin/qc/sensors/:sensorId" element={<AdminQcSensorPolicy />} /></Routes>
      </MemoryRouter>,
    );
    const maximumCard = (await screen.findByRole('heading', { name: 'Maximum plausible value' })).closest('article')!;
    await userEvent.click(within(maximumCard).getByRole('button', { name: 'Reset custom settings for Maximum plausible value' }));
    const checkDialog = screen.getByRole('dialog');
    expect(within(checkDialog).getByText(/Parameter, data-source, advanced time-resolution, and historical data are not changed/)).toBeInTheDocument();
    await userEvent.click(within(checkDialog).getByRole('button', { name: 'Reset check' }));
    await waitFor(() => expect(qcApiMocks.resetSensorCheck).toHaveBeenCalledWith(812, 'max_value', 'ug_m3'));
  });

  it('confirms a full sensor reset and immediately shows inherited settings', async () => {
    const current = sensorPolicy();
    const inherited = sensorPolicy(false);
    qcApiMocks.getSensorPolicy.mockResolvedValue(current);
    qcApiMocks.resetSensorPolicy.mockResolvedValue(inherited);

    render(
      <MemoryRouter initialEntries={['/admin/qc/sensors/812']}>
        <Routes><Route path="/admin/qc/sensors/:sensorId" element={<AdminQcSensorPolicy />} /></Routes>
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Reset all custom QC' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/Parameter, data-source, advanced time-resolution, and historical data are not changed/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Reset all custom QC' }));
    await waitFor(() => expect(qcApiMocks.resetSensorPolicy).toHaveBeenCalledWith(812));
    expect(await screen.findByText('Uses normal inherited QC')).toBeInTheDocument();
  });

  it('keeps unavailable, no-recommendation, and unit-incompatibility states distinct', async () => {
    const policy = sensorPolicy(false);
    const unitIssue = resolvedCheck({ checkCode: 'max_value', settingCode: 'max', value: 800, status: 'unavailable', reasonCode: 'conversion_not_supported' });
    const unavailablePlugin = {
      ...resolvedCheck({ checkCode: 'spike_detection', settingCode: 'threshold', value: 2 }),
      status: 'unavailable' as const,
      reason_code: 'plugin_unavailable',
    };
    policy.checks = [unitIssue, unavailablePlugin];
    qcApiMocks.getSensorPolicy.mockResolvedValue(policy);

    render(
      <MemoryRouter initialEntries={['/admin/qc/sensors/812']}>
        <Routes><Route path="/admin/qc/sensors/:sensorId" element={<AdminQcSensorPolicy />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("This check cannot use the sensor's unit")).toBeInTheDocument();
    expect(screen.getByText('Spike detection unavailable')).toBeInTheDocument();
    // Both the known check and the application-unknown reference plugin keep
    // their own no-recommendation state in each sensor policy card.
    expect(screen.getAllByText('No CompassAQ recommendation')).toHaveLength(4);
    expect(screen.queryByText('plugin_unavailable')).not.toBeInTheDocument();
  });

  it('separates manual location identity from its inherited source policy', async () => {
    const policy = sensorPolicy(false);
    policy.sensor!.manual_data_source_name = 'Local laboratory';
    qcApiMocks.getSensorPolicy.mockResolvedValue(policy);
    render(<MemoryRouter initialEntries={['/admin/qc/sensors/812']}><Routes><Route path="/admin/qc/sensors/:sensorId" element={<AdminQcSensorPolicy />} /></Routes></MemoryRouter>);
    expect(await screen.findByText(/This is a manual monitoring location/)).toHaveTextContent('does not make it provider-managed');
    expect(screen.getByText(/This is a manual monitoring location/)).toHaveTextContent(policy.data_source!.name);
    expect(screen.getByText(/Local laboratory/)).toBeVisible();
  });

});
