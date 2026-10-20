export type QcFailureAction = 'flag_for_review' | 'mark_invalid';
export type QcPolicyStatus = 'ready' | 'disabled' | 'not_configured' | 'unavailable';
export type QcPolicyApplicability = 'applicable' | 'not_applicable';
export type QcScopeType = 'parameter' | 'source_parameter' | 'sensor';
export type QcPolicyLayerName =
  | 'compassaq_default'
  | 'parameter_override'
  | 'parameter_aggregate_override'
  | 'source_override'
  | 'source_aggregate_override'
  | 'sensor_override'
  | 'sensor_aggregate_override';

export type QcUnit = {
  unit_id: number;
  unit_code: string;
  symbol: string;
  name: string;
};

export type QcPolicyLayer = {
  layer: QcPolicyLayerName;
  label: string;
  qc_rule_id: number | null;
  rule_version: number | null;
  default_profile_version: string | null;
  policy_unit_code: string | null;
};

export type QcResolvedPolicy = {
  check_code: string;
  status: QcPolicyStatus;
  enabled: boolean;
  failure_action: QcFailureAction | null;
  configured_settings: Record<string, unknown>;
  evaluation_settings: Record<string, unknown>;
  configured_unit_code: string | null;
  evaluation_unit_code: string | null;
  applicable_unit_code: string | null;
  unit_conversion: Record<string, unknown> | null;
  reason_code: string | null;
  message: string;
  applicability: QcPolicyApplicability;
  default_profile_version: string;
  applied_layers: QcPolicyLayer[];
  most_specific_source: QcPolicyLayer | null;
  property_provenance: Record<string, QcPolicyLayer>;
};

export type QcResolvedCheck = QcResolvedPolicy & {
  inherited_policy?: QcResolvedPolicy;
};

export type QcCheckSetting = {
  setting_code: string;
  value_type: 'number' | 'integer' | 'boolean' | 'string';
  label: string;
  help_text: string;
  required: boolean;
  choices: string[] | null;
  minimum?: number;
  maximum?: number;
};

export type QcCheckMetadata = {
  check_code: string;
  display_name: string;
  description: string;
  available: boolean;
  plugin_version: string | null;
  qc_api: number | null;
  origin: 'built_in' | 'entry_point' | 'runtime' | null;
  required_access: 'api-only' | 'db-read' | 'db-write' | null;
  unit_settings: string[];
  overview: {
    visible: boolean;
    label: string;
    order: number;
    summary_setting: string | null;
  };
  settings: QcCheckSetting[];
  failure_actions: QcFailureAction[];
};

export type QcOverride = {
  qc_rule_id: number;
  check_code: string;
  enabled_override: boolean | null;
  failure_action_override: QcFailureAction | null;
  settings: Record<string, unknown>;
  policy_unit: QcUnit | null;
  version: number;
  overridden_properties: string[];
  updated_at: string | null;
};

export type QcOverrideInput = {
  check_code: string;
  enabled_override: boolean | null;
  failure_action_override: QcFailureAction | null;
  settings: Record<string, unknown>;
  policy_unit_code: string | null;
};

export type QcParameter = {
  parameter_id: number;
  parameter_code: string;
  display_name: string;
  default_unit: QcUnit | null;
  supported_units: QcUnit[];
};

export type QcDataSource = {
  external_api_id: number;
  provider_code: string | null;
  name: string;
};

export type QcSensorContext = {
  sensor_id: number;
  external_sensor_id: string | null;
  device_id: number;
  device_name: string;
  manual_data_source_name?: string | null;
  display_label: string;
  parameter: QcParameter;
  unit: QcUnit | null;
  data_source: QcDataSource;
  aggregation_code: string | null;
};

export type QcSensorSearchItem = QcSensorContext & {
  override_check_count: number;
  has_overrides: boolean;
  advanced_override_count: number;
  has_sensor_specific_qc: boolean;
};

export type QcPolicyResponse = {
  scope: {
    scope_type: QcScopeType;
    parameter_id: number;
    external_api_id: number | null;
    sensor_id: number | null;
  };
  parameter: QcParameter;
  data_source: QcDataSource | null;
  sensor: QcSensorContext | null;
  default_profile_version: string;
  overrides: QcOverride[];
  checks: QcResolvedCheck[];
  advanced_aggregation_override_count: number;
};

export type QcParameterSummary = QcParameter & {
  supported: boolean;
  sensor_count: number;
  parameter_override_count: number;
  source_override_count: number;
  sensor_override_count: number;
  source_exception_count: number;
  sensor_exception_count: number;
  baseline_drift_source_override_count: number;
  baseline_drift_sensor_override_count: number;
  baseline_drift_enabled_source_count: number;
  baseline_drift_enabled_sensor_count: number;
  checks: QcResolvedCheck[];
};

export type QcParameterListResponse = {
  default_profile_version: string;
  items: QcParameterSummary[];
  total: number;
};

export type QcPreviewCheck = {
  check_code: string;
  samples_evaluated: number;
  passed: number;
  failed: number;
  indeterminate: number;
  disabled_or_not_applicable: number;
  would_flag: number;
  would_invalidate: number;
  reason_counts: Record<string, number>;
};

export type QcPreviewResponse = {
  preview_since: string;
  preview_until: string;
  hours: number;
  sample_limit: number;
  samples_available: number;
  samples_evaluated: number;
  truncated: boolean;
  checks: QcPreviewCheck[];
  candidate_policy: QcPolicyResponse;
};

export type QcSensorSearchResponse = {
  items: QcSensorSearchItem[];
  total: number;
  limit: number;
  offset: number;
};

export type QcPluginInfo = {
  name: string;
  display_name: string;
  description: string;
  long_description?: string;
  version: string;
  origin: 'built_in' | 'entry_point' | 'runtime';
  required_access: 'api-only' | 'db-read' | 'db-write';
  rules_count: number;
};

export type QcDiscoveryIssue = {
  reason_code: string;
  message: string;
  entrypoint?: string | null;
};

export type QcUnavailableCheck = {
  check_code: string;
  display_name: string;
  reason_code: 'plugin_unavailable';
  configured_rule_count: number;
};

export type QcPluginsResponse = {
  plugins: QcPluginInfo[];
  unavailable_checks: QcUnavailableCheck[];
  rules_summary: Record<string, number>;
  discovery: {
    rejected: QcDiscoveryIssue[];
    failed: QcDiscoveryIssue[];
  };
  management_mode: 'deployment_owned';
};

export type QcPreviewInput = {
  scope_type: QcScopeType;
  parameter_id?: number;
  external_api_id?: number;
  sensor_id?: number;
  hours: number;
  check_codes: string[];
  overrides: QcOverrideInput[];
};
