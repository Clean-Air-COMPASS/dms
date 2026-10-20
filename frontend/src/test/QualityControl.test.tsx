import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import i18n from '../i18n';
import AdminQcExtensions from '../qc/AdminQcExtensions';
import AdminQcOverview from '../qc/AdminQcOverview';
import AdminQcParameterDetail from '../qc/AdminQcParameterDetail';
import { rangeConfigurationState } from '../qc/presentation';
import AdminQcSourcePolicy from '../qc/AdminQcSourcePolicy';
import QcCheckCard from '../qc/QcCheckCard';
import QcCheckEditor from '../qc/QcCheckEditor';
import type {
  QcCheckMetadata,
  QcOverride,
  QcParameterSummary,
  QcPolicyResponse,
  QcResolvedCheck,
} from '../qc/types';

const apiMocks = vi.hoisted(() => ({
  countQcSensors: vi.fn(),
  getParameterPolicy: vi.fn(),
  getQcPlugins: vi.fn(),
  getSourceParameterPolicy: vi.fn(),
  listQcChecks: vi.fn(),
  listQcParameters: vi.fn(),
  previewQcPolicy: vi.fn(),
  replaceSourceParameterPolicy: vi.fn(),
  resetSourceParameterCheck: vi.fn(),
  resetSourceParameterPolicy: vi.fn(),
}));

vi.mock('../qc/api', async () => {
  const actual = await vi.importActual<typeof import('../qc/api')>('../qc/api');
  return { ...actual, ...apiMocks };
});

const unit = {
  unit_id: 1,
  unit_code: 'ug_m3',
  symbol: 'µg/m³',
  name: 'micrograms per cubic metre',
};

const metadata: QcCheckMetadata[] = [
  {
    check_code: 'min_value',
    display_name: 'Minimum value',
    description: 'Technical minimum description',
    available: true,
    plugin_version: '1.0.0',
    qc_api: 1,
    origin: 'built_in',
    required_access: 'api-only',
    unit_settings: ['min'],
    overview: { visible: true, label: 'Minimum', order: 10, summary_setting: 'min' },
    settings: [{
      setting_code: 'min',
      value_type: 'number',
      label: 'Minimum',
      help_text: 'Technical setting help',
      required: true,
      choices: null,
    }],
    failure_actions: ['flag_for_review', 'mark_invalid'],
  },
  {
    check_code: 'max_value',
    display_name: 'Maximum value',
    description: 'Technical maximum description',
    available: true,
    plugin_version: '1.0.0',
    qc_api: 1,
    origin: 'entry_point',
    required_access: 'api-only',
    unit_settings: ['max'],
    overview: { visible: true, label: 'Maximum', order: 20, summary_setting: 'max' },
    settings: [{
      setting_code: 'max',
      value_type: 'number',
      label: 'Maximum',
      help_text: 'Technical setting help',
      required: true,
      choices: null,
    }],
    failure_actions: ['flag_for_review', 'mark_invalid'],
  },
  {
    check_code: 'baseline_drift',
    display_name: 'Baseline drift',
    description: 'Technical drift description',
    available: true,
    plugin_version: '1.0.0',
    qc_api: 1,
    origin: 'built_in',
    required_access: 'db-read',
    unit_settings: ['max_drift_per_day'],
    overview: { visible: true, label: 'Baseline Drift', order: 30, summary_setting: null },
    settings: [
      {
        setting_code: 'lookback_hours',
        value_type: 'integer',
        label: 'Lookback hours',
        help_text: 'Technical setting help',
        required: true,
        choices: null,
        minimum: 1,
      },
      {
        setting_code: 'min_samples',
        value_type: 'integer',
        label: 'Minimum measurements',
        help_text: 'Technical setting help',
        required: true,
        choices: null,
        minimum: 2,
      },
      {
        setting_code: 'baseline_quantile',
        value_type: 'number',
        label: 'Baseline quantile',
        help_text: 'Technical setting help',
        required: true,
        choices: null,
      },
      {
        setting_code: 'max_drift_per_day',
        value_type: 'number',
        label: 'Maximum baseline shift indicator (per day)',
        help_text: 'Technical setting help',
        required: true,
        choices: null,
      },
      {
        setting_code: 'direction',
        value_type: 'string',
        label: 'Direction',
        help_text: 'Technical setting help',
        required: true,
        choices: ['up', 'down', 'both'],
      },
    ],
    failure_actions: ['flag_for_review', 'mark_invalid'],
  },
  {
    check_code: 'reference_threshold',
    display_name: 'Reference Threshold QC Check',
    description: 'Application-unknown test check',
    available: true,
    plugin_version: '1.0.0',
    qc_api: 1,
    origin: 'entry_point',
    required_access: 'api-only',
    unit_settings: [],
    overview: { visible: true, label: 'Reference Threshold', order: 40, summary_setting: 'limit' },
    settings: [{
      setting_code: 'limit',
      value_type: 'number',
      label: 'Threshold',
      help_text: 'Application-unknown test setting',
      required: true,
      choices: null,
    }],
    failure_actions: ['flag_for_review', 'mark_invalid'],
  },
];

function resolvedCheck(
  checkCode: string,
  enabled: boolean,
  settings: Record<string, unknown>,
  inheritedSettings = settings,
): QcResolvedCheck {
  const inherited = {
    check_code: checkCode,
    status: enabled ? 'ready' as const : 'disabled' as const,
    enabled,
    failure_action: enabled ? 'flag_for_review' as const : null,
    configured_settings: inheritedSettings,
    evaluation_settings: inheritedSettings,
    configured_unit_code: 'ug_m3',
    evaluation_unit_code: 'ug_m3',
    applicable_unit_code: 'ug_m3',
    unit_conversion: null,
    reason_code: enabled ? null : 'disabled',
    message: '',
    applicability: 'applicable' as const,
    default_profile_version: '2026.1',
    applied_layers: [],
    most_specific_source: {
      layer: 'compassaq_default' as const,
      label: 'CompassAQ default',
      qc_rule_id: null,
      rule_version: null,
      default_profile_version: '2026.1',
      policy_unit_code: 'ug_m3',
    },
    property_provenance: {},
  };
  return { ...inherited, inherited_policy: inherited };
}

function parameterPolicy(overrides: QcOverride[] = []): QcPolicyResponse {
  const baselineDriftPreset = resolvedCheck('baseline_drift', false, {
    lookback_hours: 168,
    min_samples: 72,
    baseline_quantile: 0.1,
    max_drift_per_day: 5,
    direction: 'both',
  });
  baselineDriftPreset.failure_action = 'flag_for_review';
  baselineDriftPreset.evaluation_settings = {};
  if (baselineDriftPreset.inherited_policy) {
    baselineDriftPreset.inherited_policy.failure_action = 'flag_for_review';
    baselineDriftPreset.inherited_policy.evaluation_settings = {};
  }
  return {
    scope: { scope_type: 'parameter', parameter_id: 7, external_api_id: null, sensor_id: null },
    parameter: { parameter_id: 7, parameter_code: 'pm25', display_name: 'PM2.5', default_unit: unit, supported_units: [unit] },
    data_source: null,
    sensor: null,
    default_profile_version: '2026.1',
    overrides,
    checks: [
      resolvedCheck('min_value', true, { min: -10 }),
      resolvedCheck('max_value', true, { max: 1000 }),
      baselineDriftPreset,
    ],
    advanced_aggregation_override_count: 0,
  };
}

function parameterSummary(overrides = 0): QcParameterSummary {
  return {
    parameter_id: 7,
    parameter_code: 'pm25',
    display_name: 'PM2.5',
    default_unit: unit,
    supported_units: [unit],
    supported: true,
    sensor_count: 16,
    parameter_override_count: overrides,
    source_override_count: 2,
    sensor_override_count: 3,
    source_exception_count: 1,
    sensor_exception_count: 2,
    baseline_drift_source_override_count: 0,
    baseline_drift_sensor_override_count: 0,
    baseline_drift_enabled_source_count: 0,
    baseline_drift_enabled_sensor_count: 0,
    checks: parameterPolicy().checks,
  };
}

function landingParameter(options: {
  parameterId: number;
  parameterCode: string;
  displayName: string;
  supported?: boolean;
  parameterOverrideCount?: number;
  sourceExceptionCount?: number;
  sensorExceptionCount?: number;
  baselineDriftSourceOverrideCount?: number;
  baselineDriftSensorOverrideCount?: number;
  baselineDriftEnabledSourceCount?: number;
  baselineDriftEnabledSensorCount?: number;
  checks?: QcResolvedCheck[];
}): QcParameterSummary {
  return {
    ...parameterSummary(),
    parameter_id: options.parameterId,
    parameter_code: options.parameterCode,
    display_name: options.displayName,
    supported: options.supported ?? true,
    parameter_override_count: options.parameterOverrideCount ?? 0,
    source_override_count: options.sourceExceptionCount ?? 0,
    sensor_override_count: options.sensorExceptionCount ?? 0,
    source_exception_count: options.sourceExceptionCount ?? 0,
    sensor_exception_count: options.sensorExceptionCount ?? 0,
    baseline_drift_source_override_count: options.baselineDriftSourceOverrideCount ?? 0,
    baseline_drift_sensor_override_count: options.baselineDriftSensorOverrideCount ?? 0,
    baseline_drift_enabled_source_count: options.baselineDriftEnabledSourceCount ?? 0,
    baseline_drift_enabled_sensor_count: options.baselineDriftEnabledSensorCount ?? 0,
    checks: options.checks ?? parameterPolicy().checks,
  };
}

describe('Phase 2A quality control experience', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
  });

  it.each(['en', 'es'])('prioritizes parameter controls and exception paths before unit references in %s', async language => {
    await i18n.changeLanguage(language);
    const policy = parameterPolicy();
    policy.parameter.supported_units.push({ unit_id: 2, unit_code: 'mg_m3', symbol: 'mg/m³', name: 'Milligrams per cubic metre' });
    apiMocks.getParameterPolicy.mockResolvedValue(policy);
    apiMocks.listQcChecks.mockResolvedValue(metadata.slice(0, 3));
    apiMocks.listQcParameters.mockResolvedValue({ items: [{ ...parameterSummary(), source_exception_count: 0 }], total: 1 });
    const { container } = render(<MemoryRouter initialEntries={['/admin/qc/parameters/7']}><Routes>
      <Route path="/admin/qc/parameters/:parameterId" element={<AdminQcParameterDetail />} />
    </Routes></MemoryRouter>);
    const unitSelect = await screen.findByRole('combobox', { name: i18n.t('qualityControl:detail.effectiveUnit') });
    expect(unitSelect).toHaveValue('ug_m3');
    const firstAction = screen.getAllByRole('button', { name: i18n.t('qualityControl:actions.customize') })[0];
    const reference = container.querySelector('.qc-unit-defaults')!;
    expect(unitSelect.compareDocumentPosition(firstAction) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(firstAction.compareDocumentPosition(reference) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(reference).not.toHaveAttribute('open');
    expect(container.querySelector('.qc-exception-shortcuts')).toHaveTextContent(i18n.t('qualityControl:detail.dataSourceExceptions'));
    expect(container.querySelector('.qc-exception-shortcuts a:last-child')).toHaveAttribute('href', '/admin/qc/sensors?parameter_id=7');
    for (const key of ['minimum', 'maximum', 'baselineDrift'] as const) {
      expect(screen.getByRole('heading', { level: 3, name: i18n.t(`qualityControl:checks.${key}.name`) })).toBeInTheDocument();
    }
    const drift = screen.getByRole('heading', { name: i18n.t('qualityControl:checks.baselineDrift.name') }).closest('article')!;
    expect(within(drift).getAllByText(i18n.t('qualityControl:states.disabled')).length).toBeGreaterThan(0);
    expect(within(drift).getByText(i18n.t('qualityControl:checks.baselineDrift.suggestedDescription'))).toBeInTheDocument();
    await userEvent.click(reference.querySelector('summary')!);
    expect(reference).toHaveAttribute('open');
    expect(reference).toHaveTextContent('mg/m³');
    await userEvent.selectOptions(unitSelect, 'mg_m3');
    expect(unitSelect).toHaveValue('mg_m3');
    expect(screen.getAllByText(i18n.t('qualityControl:states.needsConfiguration')).length).toBeGreaterThan(0);
  });

  it.each(['en', 'es'])('distinguishes range presets, default-only policies and custom values in %s', async language => {
    await i18n.changeLanguage(language);
    const noRange = landingParameter({ parameterId: 21, parameterCode: 'tvoc', displayName: 'TVOC', checks: [resolvedCheck('baseline_drift', false, {})] });
    const custom = landingParameter({ parameterId: 22, parameterCode: 'custom', displayName: 'Custom fixture', parameterOverrideCount: 1 });
    apiMocks.listQcChecks.mockResolvedValue(metadata);
    apiMocks.listQcParameters.mockResolvedValue({ items: [parameterSummary(), noRange, custom], total: 3 });
    render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);
    const row = async (name: string) => within(await screen.findByRole('link', { name: i18n.t('qualityControl:overview.openParameter', { parameter: name }) }));
    expect((await row('PM2.5')).getByText(i18n.t('qualityControl:states.recommendedPreset'))).toBeInTheDocument();
    const absent = await row('TVOC');
    expect(absent.getByText(i18n.t('qualityControl:states.noRecommendedRange'))).toBeInTheDocument();
    expect(absent.getAllByText(i18n.t('qualityControl:states.notConfigured'))).toHaveLength(3);
    expect(absent.queryByText(i18n.t('qualityControl:states.recommendedPreset'))).not.toBeInTheDocument();
    expect((await row('Custom fixture')).getByText(i18n.t('qualityControl:states.custom'))).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole('combobox'), 'no_recommendation');
    expect(await screen.findByText('TVOC')).toBeInTheDocument();
    expect(screen.queryByText('PM2.5')).not.toBeInTheDocument();
  });

  it('requires applicable, ready default values before identifying a recommended preset', () => {
    const summary = parameterSummary();
    expect(rangeConfigurationState(summary)).toBe('recommendedPreset');
    summary.checks[0].most_specific_source = null;
    expect(rangeConfigurationState(summary)).toBe('defaultConfiguration');
    summary.checks = parameterPolicy().checks;
    summary.checks[0].configured_settings = {};
    expect(rangeConfigurationState(summary)).toBe('defaultConfiguration');
    summary.checks = parameterPolicy().checks;
    summary.checks[0].applicability = 'not_applicable';
    expect(rangeConfigurationState(summary)).toBe('defaultConfiguration');
    summary.checks = parameterPolicy().checks.map(check => ({ ...check, status: 'not_configured', enabled: false }));
    expect(rangeConfigurationState(summary)).toBe('noRecommendedRange');
    summary.checks = parameterPolicy().checks;
    summary.default_unit = { ...unit, unit_code: 'mg_m3' };
    expect(rangeConfigurationState(summary)).toBe('defaultConfiguration');
  });

  it('presents a parameter-centered overview with active checks and distinct exceptions', async () => {
    apiMocks.listQcChecks.mockResolvedValue(metadata);
    apiMocks.listQcParameters.mockResolvedValue({
      default_profile_version: '2026.1',
      items: [parameterSummary()],
      total: 1,
    });

    render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);

    const list = await screen.findByRole('region', { name: 'Quality control settings by parameter' });
    expect(within(list).getByText('PM2.5')).toBeInTheDocument();
    expect(within(list).getByText('-10')).toBeInTheDocument();
    expect(within(list).getByText('1 source · 2 sensors')).toBeInTheDocument();
    expect(within(list).getByText('Off')).toBeInTheDocument();
    expect(screen.queryByText(/parameters need attention/)).not.toBeInTheDocument();
  });

  it('adds an application-unknown plugin overview column and summary without UI wiring', async () => {
    apiMocks.listQcChecks.mockResolvedValue(metadata);
    apiMocks.listQcParameters.mockResolvedValue({
      default_profile_version: '2026.2',
      items: [landingParameter({
        parameterId: 41,
        parameterCode: 'pm25-reference',
        displayName: 'Reference plugin parameter',
        checks: [
          resolvedCheck('min_value', true, { min: -10 }),
          resolvedCheck('max_value', true, { max: 10_000 }),
          resolvedCheck('baseline_drift', false, {}),
          resolvedCheck('reference_threshold', true, { limit: 42 }),
        ],
      })],
      total: 1,
    });

    render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);

    const list = await screen.findByRole('region', { name: 'Quality control settings by parameter' });
    expect(within(list).getByText('Reference Threshold')).toBeInTheDocument();
    const row = screen.getByRole('link', {
      name: 'Open Reference plugin parameter quality control settings',
    });
    expect(within(row).getByText('42')).toBeInTheDocument();
    expect(row.querySelector('[data-label="Maximum"]')).toHaveTextContent('10,000 µg/m³');
  });

  it('uses generic localized states for plugins without overview summary settings', async () => {
    await i18n.changeLanguage('es');
    const toggleMetadata: QcCheckMetadata = {
      ...metadata[3],
      check_code: 'completeness_toggle',
      display_name: 'Completeness Toggle QC Check',
      settings: [],
      overview: {
        visible: true,
        label: 'Completeness Toggle',
        order: 40,
        summary_setting: null,
      },
    };
    apiMocks.listQcChecks.mockResolvedValue([...metadata.slice(0, 3), toggleMetadata]);
    apiMocks.listQcParameters.mockResolvedValue({
      default_profile_version: '2026.2',
      items: [
        landingParameter({
          parameterId: 42,
          parameterCode: 'toggle-on',
          displayName: 'Toggle on',
          checks: [...parameterPolicy().checks, resolvedCheck('completeness_toggle', true, {})],
        }),
        landingParameter({
          parameterId: 43,
          parameterCode: 'toggle-off',
          displayName: 'Toggle off',
          checks: [...parameterPolicy().checks, resolvedCheck('completeness_toggle', false, {})],
        }),
        landingParameter({
          parameterId: 44,
          parameterCode: 'toggle-missing',
          displayName: 'Toggle missing',
        }),
      ],
      total: 3,
    });

    render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);

    const onRow = await screen.findByRole('link', {
      name: 'Abrir la configuración de control de calidad de Toggle on',
    });
    const offRow = screen.getByRole('link', {
      name: 'Abrir la configuración de control de calidad de Toggle off',
    });
    const missingRow = screen.getByRole('link', {
      name: 'Abrir la configuración de control de calidad de Toggle missing',
    });
    expect(onRow.querySelector('[data-label="Completeness Toggle"]')).toHaveTextContent('Activada');
    expect(offRow.querySelector('[data-label="Completeness Toggle"]')).toHaveTextContent('Desactivada');
    expect(missingRow.querySelector('[data-label="Completeness Toggle"]')).toHaveTextContent('Sin configurar');
  });

  it('separates the Baseline Drift default from enabled source and sensor overrides', async () => {
    const oneSensorEnabled = landingParameter({
      parameterId: 31,
      parameterCode: 'pm25-one-sensor',
      displayName: 'One sensor enabled',
      sensorExceptionCount: 4,
      baselineDriftSensorOverrideCount: 2,
      baselineDriftEnabledSensorCount: 1,
    });
    const pluralSensorsEnabled = landingParameter({
      parameterId: 32,
      parameterCode: 'pm25-many-sensors',
      displayName: 'Many sensors enabled',
      baselineDriftSensorOverrideCount: 3,
      baselineDriftEnabledSensorCount: 3,
    });
    const sourceEnabled = landingParameter({
      parameterId: 33,
      parameterCode: 'pm25-source',
      displayName: 'One source enabled',
      baselineDriftSourceOverrideCount: 1,
      baselineDriftEnabledSourceCount: 1,
    });
    const sourceAndSensorsEnabled = landingParameter({
      parameterId: 34,
      parameterCode: 'pm25-combined',
      displayName: 'Source and sensors enabled',
      baselineDriftSourceOverrideCount: 1,
      baselineDriftSensorOverrideCount: 2,
      baselineDriftEnabledSourceCount: 1,
      baselineDriftEnabledSensorCount: 2,
    });
    const onWithOverrides = landingParameter({
      parameterId: 36,
      parameterCode: 'pm25-on',
      displayName: 'Default and overrides enabled',
      baselineDriftSourceOverrideCount: 1,
      baselineDriftSensorOverrideCount: 1,
      checks: [
        resolvedCheck('min_value', true, { min: -10 }),
        resolvedCheck('max_value', true, { max: 10_000 }),
        resolvedCheck('baseline_drift', true, {
          lookback_hours: 168,
          min_samples: 72,
          baseline_quantile: 0.1,
          max_drift_per_day: 5,
          direction: 'both',
        }),
      ],
    });
    apiMocks.listQcChecks.mockResolvedValue(metadata);
    apiMocks.listQcParameters.mockResolvedValue({
      default_profile_version: '2026.2',
      items: [
        oneSensorEnabled,
        pluralSensorsEnabled,
        sourceEnabled,
        sourceAndSensorsEnabled,
        onWithOverrides,
      ],
      total: 5,
    });

    render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);

    const oneSensorRow = await screen.findByRole('link', {
      name: 'Open One sensor enabled quality control settings',
    });
    expect(within(oneSensorRow).getByText('Off by default')).toBeInTheDocument();
    expect(within(oneSensorRow).getByText('1 sensor On')).toBeInTheDocument();
    expect(within(oneSensorRow).getByText('0 sources · 4 sensors')).toBeInTheDocument();

    const pluralSensorRow = screen.getByRole('link', {
      name: 'Open Many sensors enabled quality control settings',
    });
    expect(within(pluralSensorRow).getByText('3 sensors On')).toBeInTheDocument();

    const sourceRow = screen.getByRole('link', {
      name: 'Open One source enabled quality control settings',
    });
    expect(within(sourceRow).getByText('1 source On')).toBeInTheDocument();

    const combinedRow = screen.getByRole('link', {
      name: 'Open Source and sensors enabled quality control settings',
    });
    expect(within(combinedRow).getByText('1 source On')).toBeInTheDocument();
    expect(within(combinedRow).getByText('2 sensors On')).toBeInTheDocument();

    const onWithOverridesRow = screen.getByRole('link', {
      name: 'Open Default and overrides enabled quality control settings',
    });
    expect(within(onWithOverridesRow).getByText('On · 2 overrides')).toBeInTheDocument();
  });

  it('localizes the Baseline Drift override summary in Spanish', async () => {
    await i18n.changeLanguage('es');
    apiMocks.listQcChecks.mockResolvedValue(metadata);
    apiMocks.listQcParameters.mockResolvedValue({
      default_profile_version: '2026.2',
      items: [landingParameter({
        parameterId: 35,
        parameterCode: 'pm25-spanish',
        displayName: 'PM2.5',
        baselineDriftSourceOverrideCount: 1,
        baselineDriftSensorOverrideCount: 2,
        baselineDriftEnabledSourceCount: 1,
        baselineDriftEnabledSensorCount: 2,
      })],
      total: 1,
    });

    render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);

    const row = await screen.findByRole('link', {
      name: 'Abrir la configuración de control de calidad de PM2.5',
    });
    expect(within(row).getByText('Desactivada de forma predeterminada')).toBeInTheDocument();
    expect(within(row).getByText('1 fuente activada')).toBeInTheDocument();
    expect(within(row).getByText('2 sensores activados')).toBeInTheDocument();
  });

  it('shows an expected but unavailable check in extension diagnostics', async () => {
    apiMocks.getQcPlugins.mockResolvedValue({
      plugins: [],
      unavailable_checks: [{
        check_code: 'max_value',
        display_name: 'max_value',
        reason_code: 'plugin_unavailable',
        configured_rule_count: 2,
      }],
      rules_summary: { max_value: 2 },
      discovery: { rejected: [], failed: [] },
      management_mode: 'deployment_owned',
    });

    render(<MemoryRouter><AdminQcExtensions /></MemoryRouter>);

    expect(await screen.findByText('Maximum plausible value is unavailable')).toBeInTheDocument();
    expect(screen.getByText(/2 configured customizations are affected/)).toBeInTheDocument();
    expect(screen.getByText('plugin_unavailable')).toBeInTheDocument();
    expect(screen.queryByText('No extension discovery issues were reported.')).not.toBeInTheDocument();
  });

  it('does not count a normal missing unit default as needing attention', async () => {
    const missingConfiguration = landingParameter({
      parameterId: 11,
      parameterCode: 'no2',
      displayName: 'Supported missing configuration',
      checks: [resolvedCheck('min_value', true, { min: -1 }), resolvedCheck('baseline_drift', false, {})],
    });
    const unavailableMaximum = {
      ...resolvedCheck('max_value', true, { max: 500 }),
      status: 'unavailable' as const,
      reason_code: 'plugin_unavailable',
    };
    const unavailableCheck = landingParameter({
      parameterId: 12,
      parameterCode: 'co',
      displayName: 'Unavailable maximum check',
      checks: [resolvedCheck('min_value', true, { min: 0 }), unavailableMaximum, resolvedCheck('baseline_drift', false, {})],
    });
    const normalRecommended = landingParameter({
      parameterId: 13,
      parameterCode: 'pm10',
      displayName: 'Normal recommended parameter',
    });
    const noRecommendation = landingParameter({
      parameterId: 14,
      parameterCode: 'voc',
      displayName: 'Unsupported parameter',
      supported: false,
      checks: [],
    });
    const customizedWithoutRecommendation = landingParameter({
      parameterId: 15,
      parameterCode: 'custom_voc',
      displayName: 'Customized unsupported parameter',
      supported: false,
      parameterOverrideCount: 1,
      checks: [resolvedCheck('max_value', true, { max: 100 })],
    });
    apiMocks.listQcChecks.mockResolvedValue(metadata);
    apiMocks.listQcParameters.mockResolvedValue({
      default_profile_version: '2026.1',
      items: [missingConfiguration, unavailableCheck, normalRecommended, noRecommendation, customizedWithoutRecommendation],
      total: 5,
    });

    render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);

    const unsupportedRow = await screen.findByRole('link', { name: 'Open Unsupported parameter quality control settings' });
    expect(within(unsupportedRow).getByText('No CompassAQ recommendation')).toBeInTheDocument();
    expect(within(unsupportedRow).queryByText('Needs configuration')).not.toBeInTheDocument();
    const missingRow = screen.getByRole('link', { name: 'Open Supported missing configuration quality control settings' });
    expect(within(missingRow).queryByText('Needs configuration')).not.toBeInTheDocument();
    const normalRow = screen.getByRole('link', { name: 'Open Normal recommended parameter quality control settings' });
    expect(within(normalRow).queryByText('Needs configuration')).not.toBeInTheDocument();
    expect(within(normalRow).queryByText('No CompassAQ recommendation')).not.toBeInTheDocument();
    const customizedUnsupportedRow = screen.getByRole('link', { name: 'Open Customized unsupported parameter quality control settings' });
    expect(within(customizedUnsupportedRow).getByText('Custom')).toBeInTheDocument();
    expect(within(customizedUnsupportedRow).queryByText('Needs configuration')).not.toBeInTheDocument();
    expect(within(customizedUnsupportedRow).queryByText('Recommended')).not.toBeInTheDocument();

    await userEvent.type(screen.getByRole('searchbox', { name: 'Parameter' }), 'Supported missing');
    expect(screen.queryByText('Unavailable maximum check')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /1 parameter needs attention/ }));

    expect(screen.getByRole('combobox', { name: 'Show' })).toHaveValue('attention');
    expect(screen.getByRole('searchbox', { name: 'Parameter' })).toHaveValue('');
    const filteredList = screen.getByRole('region', { name: 'Quality control settings by parameter' });
    expect(within(filteredList).getAllByRole('link')).toHaveLength(1);
    expect(within(filteredList).queryByText('Supported missing configuration')).not.toBeInTheDocument();
    expect(within(filteredList).getByText('Unavailable maximum check')).toBeInTheDocument();
    expect(within(filteredList).queryByText('Normal recommended parameter')).not.toBeInTheDocument();
    expect(within(filteredList).queryByText('Unsupported parameter')).not.toBeInTheDocument();
    expect(within(filteredList).queryByText('Customized unsupported parameter')).not.toBeInTheDocument();
  });

  it('preserves Customized, Has exceptions, Unavailable, and No recommendation filters', async () => {
    const customized = landingParameter({
      parameterId: 21,
      parameterCode: 'pm10',
      displayName: 'Customized parameter',
      parameterOverrideCount: 1,
    });
    const withExceptions = landingParameter({
      parameterId: 22,
      parameterCode: 'so2',
      displayName: 'Parameter with exceptions',
      sourceExceptionCount: 1,
    });
    const unavailableMaximum = {
      ...resolvedCheck('max_value', true, { max: 500 }),
      status: 'unavailable' as const,
      reason_code: 'plugin_unavailable',
    };
    const unavailable = landingParameter({
      parameterId: 23,
      parameterCode: 'co',
      displayName: 'Parameter with unavailable check',
      checks: [resolvedCheck('min_value', true, { min: 0 }), unavailableMaximum, resolvedCheck('baseline_drift', false, {})],
    });
    const noRecommendation = landingParameter({
      parameterId: 24,
      parameterCode: 'voc',
      displayName: 'Parameter without recommendation',
      supported: false,
      checks: [],
    });
    apiMocks.listQcChecks.mockResolvedValue(metadata);
    apiMocks.listQcParameters.mockResolvedValue({
      default_profile_version: '2026.1',
      items: [customized, withExceptions, unavailable, noRecommendation],
      total: 4,
    });
    render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);
    const statusFilter = await screen.findByRole('combobox', { name: 'Show' });

    await userEvent.selectOptions(statusFilter, 'custom');
    expect(screen.getByText('Customized parameter')).toBeInTheDocument();
    expect(screen.queryByText('Parameter with exceptions')).not.toBeInTheDocument();

    await userEvent.selectOptions(statusFilter, 'exceptions');
    expect(screen.getByText('Parameter with exceptions')).toBeInTheDocument();
    expect(screen.queryByText('Customized parameter')).not.toBeInTheDocument();

    await userEvent.selectOptions(statusFilter, 'unavailable');
    expect(screen.getByText('Parameter with unavailable check')).toBeInTheDocument();
    expect(screen.queryByText('Parameter with exceptions')).not.toBeInTheDocument();

    await userEvent.selectOptions(statusFilter, 'no_recommendation');
    expect(screen.getByText('Parameter without recommendation')).toBeInTheDocument();
    expect(screen.queryByText('Parameter with unavailable check')).not.toBeInTheDocument();
  });

  it('keeps landing loading, error, and empty states explicit', async () => {
    apiMocks.listQcChecks.mockRejectedValue(new Error('offline'));
    apiMocks.listQcParameters.mockRejectedValue(new Error('offline'));
    const firstRender = render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);
    expect(screen.getByText('Loading quality control settings…')).toBeInTheDocument();
    expect(await screen.findByText('Quality control settings could not be loaded.')).toBeInTheDocument();
    firstRender.unmount();

    apiMocks.listQcChecks.mockResolvedValue(metadata);
    apiMocks.listQcParameters.mockResolvedValue({ default_profile_version: '2026.1', items: [], total: 0 });
    render(<MemoryRouter><AdminQcOverview /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'No parameters available' })).toBeInTheDocument();
  });

  it('shows the disabled Baseline Drift screening preset without changing Min/Max recommendations', () => {
    const policy = parameterPolicy();
    const check = policy.checks.find((candidate) => candidate.check_code === 'baseline_drift')!;
    render(
      <MemoryRouter>
        <QcCheckCard
          policy={policy}
          check={check}
          metadata={metadata[2]}
          affectedSensorCount={16}
          editing={false}
          onStartEditing={vi.fn()}
          onStopEditing={vi.fn()}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onResetCheck={vi.fn()}
        />
        <QcCheckCard
          policy={policy}
          check={policy.checks[0]}
          metadata={metadata[0]}
          affectedSensorCount={16}
          editing={false}
          onStartEditing={vi.fn()}
          onStopEditing={vi.fn()}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onResetCheck={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('Off')).toBeInTheDocument();
    expect(screen.getByText('CompassAQ screening preset')).toBeInTheDocument();
    expect(screen.getByText('Recommended')).toBeInTheDocument();
    expect(screen.getByText('Suggested screening settings')).toBeInTheDocument();
    expect(screen.getByText('168')).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
    expect(screen.getByText('0.1')).toBeInTheDocument();
    expect(screen.getByText('5 µg/m³')).toBeInTheDocument();
    expect(screen.getByText('Both directions')).toBeInTheDocument();
    expect(screen.getByText('Suggested failure action: Flag for review.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review and enable' })).toBeInTheDocument();
    expect(screen.queryByText('Recommended QC value not configured')).not.toBeInTheDocument();
  });

  it('presents an application-unknown unitless plugin without a policy as needing configuration', () => {
    const policy = parameterPolicy();
    const check: QcResolvedCheck = {
      ...resolvedCheck('reference_threshold', false, {}),
      status: 'not_configured',
      reason_code: 'no_matching_rule',
      applicability: 'not_applicable',
      most_specific_source: null,
    };
    render(
      <MemoryRouter>
        <QcCheckCard
          policy={{ ...policy, checks: [...policy.checks, check] }}
          check={check}
          metadata={metadata[3]}
          affectedSensorCount={16}
          editing={false}
          onStartEditing={vi.fn()}
          onStopEditing={vi.fn()}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onResetCheck={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Reference Threshold QC Check' })).toBeInTheDocument();
    expect(screen.getByText('Needs configuration')).toBeInTheDocument();
    expect(screen.getByText('CompassAQ does not currently provide a universal recommended value for PM2.5.')).toBeInTheDocument();
    expect(screen.queryByText('Recommended')).not.toBeInTheDocument();
  });

  it.each(['en', 'es'])('keeps a disabled ozone preset in its configured ppm unit when viewing ppb in %s', async language => {
    await i18n.changeLanguage(language);
    const policy = parameterPolicy();
    const check = { ...policy.checks[2], configured_unit_code: 'ppm', evaluation_unit_code: 'ppb', applicable_unit_code: 'ppb',
      configured_settings: { ...policy.checks[2].configured_settings, max_drift_per_day: 0.003 }, evaluation_settings: {} };
    render(<MemoryRouter><QcCheckCard policy={policy} check={check} metadata={metadata[2]} affectedSensorCount={1}
      editing={false} onStartEditing={vi.fn()} onStopEditing={vi.fn()} onSave={vi.fn()} onPreview={vi.fn()} onResetCheck={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText(`${language === 'es' ? '0,003' : '0.003'} ppm`)).toBeInTheDocument();
    expect(screen.queryByText(/0[.,]003 ppb/)).not.toBeInTheDocument();
    expect(screen.getAllByText(i18n.t('qualityControl:states.disabled')).length).toBeGreaterThan(0);
  });

  it('lets an administrator deliberately enable the suggested Baseline Drift preset', async () => {
    const policy = parameterPolicy();
    const check = policy.checks.find((candidate) => candidate.check_code === 'baseline_drift')!;
    const onSave = vi.fn().mockResolvedValue(undefined);
    const editorView = render(
      <MemoryRouter>
        <QcCheckEditor
          policy={policy}
          check={check}
          metadata={metadata[2]}
          affectedSensorCount={16}
          onSave={onSave}
          onPreview={vi.fn()}
          onCancel={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole('checkbox', { name: /Enable this check/ })).not.toBeChecked();
    await userEvent.click(screen.getByRole('checkbox', { name: /Enable this check/ }));
    expect(screen.getByLabelText('Lookback hours')).toHaveValue(168);
    expect(screen.getByLabelText('Minimum measurements')).toHaveValue(72);
    expect(screen.getByLabelText('Baseline quantile')).toHaveValue(0.1);
    expect(screen.getByLabelText('Maximum baseline shift indicator (per day)')).toHaveValue(5);
    expect(screen.getByLabelText('Direction')).toHaveValue('both');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(onSave).toHaveBeenCalledWith({
      check_code: 'baseline_drift',
      enabled_override: true,
      failure_action_override: null,
      settings: {},
      policy_unit_code: 'ug_m3',
    });

    editorView.unmount();
    const enabledCheck: QcResolvedCheck = {
      ...check,
      status: 'ready',
      enabled: true,
      evaluation_settings: check.configured_settings,
      reason_code: null,
    };
    render(
      <MemoryRouter>
        <QcCheckCard
          policy={{ ...policy, checks: [enabledCheck] }}
          check={enabledCheck}
          metadata={metadata[2]}
          affectedSensorCount={16}
          editing={false}
          onStartEditing={vi.fn()}
          onStopEditing={vi.fn()}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onResetCheck={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('On')).toBeInTheDocument();
  });

  it('uses clear English and Spanish Baseline Drift screening terminology', async () => {
    const policy = parameterPolicy();
    const check = policy.checks.find((candidate) => candidate.check_code === 'baseline_drift')!;
    const view = render(
      <MemoryRouter>
        <QcCheckCard
          policy={policy}
          check={check}
          metadata={metadata[2]}
          affectedSensorCount={16}
          editing={false}
          onStartEditing={vi.fn()}
          onStopEditing={vi.fn()}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onResetCheck={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('Suggested screening settings')).toBeInTheDocument();

    await i18n.changeLanguage('es');
    view.rerender(
      <MemoryRouter>
        <QcCheckCard
          policy={policy}
          check={check}
          metadata={metadata[2]}
          affectedSensorCount={16}
          editing={false}
          onStartEditing={vi.fn()}
          onStopEditing={vi.fn()}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onResetCheck={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText('Configuración de detección sugerida')).toBeInTheDocument();
    expect(screen.getByText('Preajuste de detección de CompassAQ')).toBeInTheDocument();
  });

  it('creates only the properties needed to configure a previously unconfigured check', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const inherited = {
      ...resolvedCheck('min_value', false, {}).inherited_policy!,
      status: 'not_configured' as const,
      reason_code: 'no_matching_rule',
      configured_unit_code: null,
      evaluation_unit_code: 'ug_m3',
      applicable_unit_code: 'ug_m3',
      most_specific_source: null,
    };
    const check: QcResolvedCheck = { ...inherited, inherited_policy: inherited };

    render(
      <MemoryRouter>
        <QcCheckEditor
          policy={{ ...parameterPolicy(), checks: [check] }}
          check={check}
          metadata={metadata[0]}
          affectedSensorCount={16}
          onSave={onSave}
          onPreview={vi.fn()}
          onCancel={vi.fn()}
        />
      </MemoryRouter>,
    );

    const unitSelector = screen.getByRole('combobox', { name: 'Unit' });
    expect(within(unitSelector).getAllByRole('option')).toHaveLength(1);
    await userEvent.type(screen.getByLabelText('Minimum plausible value'), '-5');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(onSave).toHaveBeenCalledWith({
      check_code: 'min_value',
      enabled_override: true,
      failure_action_override: 'flag_for_review',
      settings: { min: -5 },
      policy_unit_code: 'ug_m3',
    });
  });

  it('offers every supported parameter unit in the always-visible range selector', () => {
    const milligramUnit = {
      unit_id: 2,
      unit_code: 'mg_m3',
      symbol: 'mg/m³',
      name: 'milligrams per cubic metre',
    };
    const policy = parameterPolicy();
    policy.parameter.supported_units = [unit, milligramUnit];

    render(
      <MemoryRouter>
        <QcCheckEditor
          policy={policy}
          check={policy.checks[0]}
          metadata={metadata[0]}
          affectedSensorCount={16}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onCancel={vi.fn()}
        />
      </MemoryRouter>,
    );

    const unitSelector = screen.getByRole('combobox', { name: 'Unit' });
    expect(within(unitSelector).getAllByRole('option')).toHaveLength(2);
    expect(unitSelector).toHaveValue('ug_m3');
  });

  it('displays and edits a safely converted range in the selected unit', () => {
    const ppmUnit = { unit_id: 3, unit_code: 'ppm', symbol: 'ppm', name: 'parts per million' };
    const ppbUnit = { unit_id: 4, unit_code: 'ppb', symbol: 'ppb', name: 'parts per billion' };
    const base = resolvedCheck('max_value', true, { max: 0.5 });
    const inherited = {
      ...base.inherited_policy!,
      configured_settings: { max: 0.5 },
      evaluation_settings: { max: 500 },
      configured_unit_code: 'ppm',
      evaluation_unit_code: 'ppb',
      applicable_unit_code: 'ppb',
    };
    const convertedCheck: QcResolvedCheck = {
      ...base,
      ...inherited,
      inherited_policy: inherited,
    };
    const policy = parameterPolicy();
    policy.parameter.default_unit = ppmUnit;
    policy.parameter.supported_units = [ppmUnit, ppbUnit];
    policy.checks = [convertedCheck];

    render(
      <MemoryRouter>
        <QcCheckCard
          policy={policy}
          check={convertedCheck}
          metadata={metadata[1]}
          affectedSensorCount={2}
          editing
          onStartEditing={vi.fn()}
          onStopEditing={vi.fn()}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onResetCheck={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('500 ppb')).toBeInTheDocument();
    expect(screen.getByLabelText('Maximum plausible value')).toHaveValue(500);
    expect(screen.getByRole('combobox', { name: 'Unit' })).toHaveValue('ppb');
  });

  it('keeps edits visible after a save failure and associates required-value errors', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('offline'));
    const check = parameterPolicy().checks[0];
    const firstRender = render(
      <MemoryRouter>
        <QcCheckEditor
          policy={parameterPolicy()}
          check={check}
          metadata={metadata[0]}
          affectedSensorCount={16}
          onSave={onSave}
          onPreview={vi.fn()}
          onCancel={vi.fn()}
        />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByText(/Turning off Minimum plausible value stops this check for up to 16 sensors/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox'));
    const input = screen.getByLabelText('Minimum plausible value');
    await userEvent.clear(input);
    await userEvent.type(input, '-8');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('The settings could not be saved. Your edits are still here.')).toBeInTheDocument();
    expect(input).toHaveValue(-8);
    firstRender.unmount();

    const validationSave = vi.fn();
    render(
      <MemoryRouter>
        <QcCheckEditor
          policy={parameterPolicy()}
          check={check}
          metadata={metadata[0]}
          affectedSensorCount={16}
          onSave={validationSave}
          onPreview={vi.fn()}
          onCancel={vi.fn()}
        />
      </MemoryRouter>,
    );
    await userEvent.clear(screen.getByLabelText('Minimum plausible value'));
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(screen.getByText('This value is required when the check is enabled.')).toBeInTheDocument();
    expect(validationSave).not.toHaveBeenCalled();
  });

  it('shows unavailable and scientifically unconfigured checks as different states', () => {
    const unconfigured = {
      ...resolvedCheck('min_value', false, {}),
      status: 'not_configured' as const,
      reason_code: 'no_matching_rule',
    };
    const unavailable = {
      ...resolvedCheck('legacy_check', true, {}),
      status: 'unavailable' as const,
      reason_code: 'plugin_unavailable',
    };
    const unavailableMetadata: QcCheckMetadata = {
      ...metadata[0],
      check_code: 'legacy_check',
      display_name: 'Spike detection',
      description: 'Checks sudden changes.',
      available: false,
      settings: [],
      unit_settings: [],
    };
    render(
      <MemoryRouter>
        <QcCheckCard
          policy={parameterPolicy()}
          check={unconfigured}
          metadata={metadata[0]}
          affectedSensorCount={16}
          editing={false}
          onStartEditing={vi.fn()}
          onStopEditing={vi.fn()}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onResetCheck={vi.fn()}
        />
        <QcCheckCard
          policy={parameterPolicy()}
          check={unavailable}
          metadata={unavailableMetadata}
          affectedSensorCount={16}
          editing={false}
          onStartEditing={vi.fn()}
          onStopEditing={vi.fn()}
          onSave={vi.fn()}
          onPreview={vi.fn()}
          onResetCheck={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('No default range for µg/m³')).toBeInTheDocument();
    expect(screen.getByText('Spike detection unavailable')).toBeInTheDocument();
    expect(screen.queryByText('legacy_check')).not.toBeInTheDocument();
  });

  it('removes the final threshold and its unit override together', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const existing: QcOverride = {
      qc_rule_id: 42,
      check_code: 'max_value',
      enabled_override: null,
      failure_action_override: null,
      settings: { max: 800 },
      policy_unit: unit,
      version: 1,
      overridden_properties: ['settings.max', 'unit'],
      updated_at: '2026-08-17T00:00:00Z',
    };
    const inherited = resolvedCheck('max_value', true, { max: 1000 }).inherited_policy!;
    const check: QcResolvedCheck = {
      ...resolvedCheck('max_value', true, { max: 800 }, { max: 1000 }),
      inherited_policy: inherited,
      property_provenance: {
        'settings.max': {
          layer: 'parameter_override',
          label: 'Parameter override',
          qc_rule_id: 42,
          rule_version: 1,
          default_profile_version: null,
          policy_unit_code: 'ug_m3',
        },
      },
    };

    render(
      <MemoryRouter>
        <QcCheckEditor
          policy={{ ...parameterPolicy([existing]), checks: [check] }}
          check={check}
          metadata={metadata[1]}
          affectedSensorCount={16}
          onSave={onSave}
          onPreview={vi.fn()}
          onCancel={vi.fn()}
        />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Use recommended value' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(onSave).toHaveBeenCalledWith(null);
  });

  it('shows preview flag, invalid, indeterminate, truncation, and history context', async () => {
    const preview = vi.fn().mockResolvedValue({
      preview_since: '2026-08-16T00:00:00Z',
      preview_until: '2026-08-17T00:00:00Z',
      hours: 24,
      sample_limit: 2000,
      samples_available: 2200,
      samples_evaluated: 2000,
      truncated: true,
      checks: [{
        check_code: 'min_value',
        samples_evaluated: 2000,
        passed: 1980,
        failed: 17,
        indeterminate: 3,
        disabled_or_not_applicable: 0,
        would_flag: 12,
        would_invalidate: 5,
        reason_counts: { missing_value: 3 },
      }],
      candidate_policy: parameterPolicy(),
    });
    const check = parameterPolicy().checks[0];

    render(
      <MemoryRouter>
        <QcCheckEditor
          policy={parameterPolicy()}
          check={check}
          metadata={metadata[0]}
          affectedSensorCount={16}
          onSave={vi.fn()}
          onPreview={preview}
          onCancel={vi.fn()}
        />
      </MemoryRouter>,
    );

    await userEvent.clear(screen.getByLabelText('Minimum plausible value'));
    await userEvent.type(screen.getByLabelText('Minimum plausible value'), '-8');
    await userEvent.click(screen.getByRole('button', { name: 'Preview impact' }));

    expect(await screen.findByText('Based on 2,000 measurements from the last 24 hours')).toBeInTheDocument();
    expect(await screen.findByText('Would record a QC warning')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('Latest 2,000 matching measurements')).toBeInTheDocument();
    expect(screen.getByText('Preview only. Historical measurements are not changed.')).toBeInTheDocument();
  });

  it('removes the final data-source exception and returns to the parameter page', async () => {
    const sourceOverride: QcOverride = {
      qc_rule_id: 44,
      check_code: 'max_value',
      enabled_override: null,
      failure_action_override: null,
      settings: { max: 800 },
      policy_unit: unit,
      version: 1,
      overridden_properties: ['settings.max'],
      updated_at: '2026-08-17T00:00:00Z',
    };
    const sourcePolicy: QcPolicyResponse = {
      ...parameterPolicy([sourceOverride]),
      scope: { scope_type: 'source_parameter', parameter_id: 7, external_api_id: 3, sensor_id: null },
      data_source: { external_api_id: 3, provider_code: 'airgradient', name: 'AirGradient' },
    };
    apiMocks.getSourceParameterPolicy.mockResolvedValue(sourcePolicy);
    apiMocks.listQcChecks.mockResolvedValue(metadata);
    apiMocks.countQcSensors.mockResolvedValue({ items: [], total: 6, limit: 1, offset: 0 });
    apiMocks.resetSourceParameterPolicy.mockResolvedValue({ ...sourcePolicy, overrides: [] });

    render(
      <MemoryRouter initialEntries={['/admin/qc/parameters/7/sources/3']}>
        <Routes>
          <Route path="/admin/qc/parameters/:parameterId/sources/:externalApiId" element={<AdminQcSourcePolicy />} />
          <Route path="/admin/qc/parameters/:parameterId" element={<div>Parameter destination</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await userEvent.click(await screen.findByRole('button', { name: 'Remove exception' }));
    expect(screen.getByRole('heading', { name: 'Reference Threshold QC Check' })).toBeInTheDocument();
    expect(screen.getAllByText('Uses PM2.5 settings').length).toBeGreaterThan(0);
    const dialog = screen.getByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove exception' }));

    expect(apiMocks.resetSourceParameterPolicy).toHaveBeenCalledWith(3, 7);
    expect(await screen.findByText('Parameter destination')).toBeInTheDocument();
  });
});
