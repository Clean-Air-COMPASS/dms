import i18n from './i18n';
import { getAggregationDisplayLabel } from './aqi';

export type MeasurementAggregationOptionMetadata = {
  result_aggregation_code: string;
  display_name: string;
  duration_minutes?: number | null;
  is_rolling: boolean;
  capability_kind: 'native' | 'direct_rollup' | 'chained_rollup';
  rollup_path: string[];
  supports_latest: boolean;
  supports_history: boolean;
  formatting_status: 'configured' | 'not_configured';
  display_precision?: number | null;
};

export type MeasurementAggregationCapability = {
  parameter_code: string;
  native_aggregation_code: string | null;
  native_status: 'known' | 'unknown';
  supported_aggregations: MeasurementAggregationOptionMetadata[];
};

export type MeasurementAggregationOption = {
  code: string;
  display: string;
  displayPrecision?: number | null;
};

function normalizedCode(value: string | null | undefined): string {
  return (value || '').trim().toLowerCase();
}

/**
 * Present backend-resolved capabilities for one stream.  This helper does not
 * infer graph reachability or scientific compatibility.
 */
export function getMeasurementAggregationOptions({
  nativeAggregationCode,
  parameterCode,
  capabilities,
  usage = 'history',
}: {
  nativeAggregationCode: string | null | undefined;
  parameterCode: string;
  capabilities: MeasurementAggregationCapability[];
  usage?: 'latest' | 'history';
}): MeasurementAggregationOption[] {
  const normalizedNative = normalizedCode(nativeAggregationCode) || null;
  const capability = capabilities.find((candidate) => (
    normalizedCode(candidate.parameter_code) === normalizedCode(parameterCode)
    && (normalizedCode(candidate.native_aggregation_code) || null) === normalizedNative
  ));
  if (!capability) return [];

  return capability.supported_aggregations
    .filter((option) => usage === 'latest' ? option.supports_latest : option.supports_history)
    .map((option) => ({
      code: normalizedCode(option.result_aggregation_code),
      display: option.capability_kind === 'native'
        ? i18n.t('aq:aggregation.native', { aggregation: getAggregationDisplayLabel(option.result_aggregation_code) })
        : getAggregationDisplayLabel(option.result_aggregation_code),
      displayPrecision: option.display_precision,
    }));
}
