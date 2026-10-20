import type {
  AirQualityIndexCategoryMetadata,
  AirQualityIndexProductMetadata,
  AirQualityIndexStandardMetadata,
  DeviceAirQualityIndexResult,
} from './airQualityIndex';
import { formatTimestamp } from './utils/timezone';
import i18n, { formatDisplayDateTime, formatDisplayList, formatDisplayNumber } from './i18n';
import { getAggregationDisplayLabel } from './aqi';


export const EEA_EUROPEAN_STANDARD_CODE = 'eea_european';
export function getPhilippineAqiCategoryOnlyMessage(): string {
  return i18n.t('aq:messages.numericValueAbovePublishedRange');
}

export function getEeaEuropeanStandardLabel(): string {
  return i18n.t('aq:standards.eeaEuropean');
}

export const EUROPEAN_AQI_UNAVAILABLE_COLOR = '#6B7280';

export function formatEuropeanAqiConcentration(value: number | null): string {
  if (value == null) return '';
  return formatDisplayNumber(value, i18n.resolvedLanguage === 'es' ? 'es' : 'en', {
    maximumFractionDigits: 2,
    useGrouping: false,
  });
}

const POLLUTANT_DISPLAY_LABELS: Readonly<Record<string, string>> = {
  pm25: 'PM2.5',
  pm10: 'PM10',
  o3: 'O₃',
  no2: 'NO₂',
  so2: 'SO₂',
  co: 'CO',
};

const EXCLUSION_REASON_KEYS = {
  unsupported_pollutant: 'aq:exclusionReasons.unsupportedPollutant',
  unsupported_unit: 'aq:exclusionReasons.unsupportedUnit',
  unsupported_aggregation_period: 'aq:exclusionReasons.unsupportedAveragingPeriod',
  unsupported_product: 'aq:exclusionReasons.unsupportedProduct',
  invalid_concentration: 'aq:exclusionReasons.invalidConcentration',
  incomplete_hour: 'aq:exclusionReasons.incompleteHour',
  missing_measurements: 'aq:exclusionReasons.missingMeasurements',
  hourly_concentration_not_available: 'aq:exclusionReasons.hourlyConcentrationUnavailable',
  hourly_aggregation_provenance_missing: 'aq:exclusionReasons.hourlyAveragingInformationUnavailable',
  unsupported_input_aggregation_period: 'aq:exclusionReasons.unsupportedInputAveragingPeriod',
  unsupported_input_frequency: 'aq:exclusionReasons.unsupportedInputFrequency',
  conversion_not_supported: 'aq:exclusionReasons.conversionNotSupported',
  expected_frequency_missing: 'aq:exclusionReasons.expectedFrequencyUnavailable',
  unsupported_pollutant_duration_frequency_combination: 'aq:exclusionReasons.unsupportedDurationFrequency',
  timestamp_semantics_unknown: 'aq:exclusionReasons.timestampSemanticsUnknown',
  hourly_completeness_not_met: 'aq:exclusionReasons.hourlyCompletenessNotMet',
  duplicate_observation_interval: 'aq:exclusionReasons.duplicateObservationInterval',
  off_frequency_observations: 'aq:exclusionReasons.offFrequencyObservations',
  no_valid_observations: 'aq:exclusionReasons.noValidObservations',
  insufficient_recent_hours: 'aq:exclusionReasons.insufficientRecentHours',
  no_eligible_sensor_stream: 'aq:exclusionReasons.noEligibleSensorStream',
  device_timezone_missing: 'aq:exclusionReasons.deviceTimezoneMissing',
  device_timezone_invalid: 'aq:exclusionReasons.deviceTimezoneInvalid',
  completed_local_day_not_available: 'aq:exclusionReasons.completedLocalDayUnavailable',
  daily_completeness_not_met: 'aq:exclusionReasons.dailyCompletenessNotMet',
  no_valid_hourly_concentrations: 'aq:exclusionReasons.noValidHourlyConcentrations',
  unsupported_daily_pollutant: 'aq:exclusionReasons.unsupportedDailyPollutant',
  unsupported_daily_methodology: 'aq:exclusionReasons.unsupportedDailyMethodology',
  completed_day_methodology_not_implemented: 'aq:exclusionReasons.completedDayMethodologyNotImplemented',
  no_eligible_pollutants: 'aq:exclusionReasons.noEligiblePollutants',
  ozone_1_hour_not_applicable: 'aq:exclusionReasons.ozoneOneHourNotApplicable',
  ozone_8_hour_not_applicable: 'aq:exclusionReasons.ozoneEightHourNotApplicable',
  rolling_8_hour_completeness_not_met: 'aq:exclusionReasons.rollingEightHourCompletenessNotMet',
  no_applicable_ozone_candidate: 'aq:exclusionReasons.noApplicableOzoneCandidate',
  published_breakpoint_gap: 'aq:exclusionReasons.publishedBreakpointGap',
  subindex_not_defined_for_concentration: 'aq:exclusionReasons.subindexNotDefined',
  rolling_24_hour_completeness_not_met: 'aq:exclusionReasons.rollingTwentyFourHourCompletenessNotMet',
  so2_1_hour_not_applicable: 'aq:exclusionReasons.sulfurDioxideOneHourNotApplicable',
  so2_24_hour_not_applicable: 'aq:exclusionReasons.sulfurDioxideTwentyFourHourNotApplicable',
  no_applicable_so2_candidate: 'aq:exclusionReasons.noApplicableSulfurDioxideCandidate',
} as const;

const AUDIT_FLAG_KEYS = {
  duplicate_observation_interval: 'aq:auditFlags.duplicateObservationInterval',
  off_frequency_observations: 'aq:auditFlags.offFrequencyObservations',
  invalid_observations_rejected: 'aq:auditFlags.invalidObservationsRejected',
} as const;

const COVERAGE_STATUS_KEYS = {
  complete: 'aq:coverage.complete',
  partial: 'aq:coverage.partial',
  none: 'aq:coverage.none',
} as const;

const CATEGORY_KEYS = {
  good: 'aq:categories.good',
  fair: 'aq:categories.fair',
  moderate: 'aq:categories.moderate',
  poor: 'aq:categories.poor',
  very_poor: 'aq:categories.veryPoor',
  extremely_poor: 'aq:categories.extremelyPoor',
  unhealthy_for_sensitive_groups: 'aq:categories.unhealthyForSensitiveGroups',
  unhealthy: 'aq:categories.unhealthy',
  very_unhealthy: 'aq:categories.veryUnhealthy',
  hazardous: 'aq:categories.hazardous',
  acutely_unhealthy: 'aq:categories.acutelyUnhealthy',
  emergency: 'aq:categories.emergency',
} as const;

const STANDARD_KEYS = {
  us_epa: 'aq:standards.usEpa',
  eea_european: 'aq:standards.eeaEuropean',
  philippines_denr: 'aq:standards.philippinesDenr',
} as const;

const PRODUCT_KEYS = {
  'eea_european.overall.hourly': 'aq:products.eeaOverallHourly',
  'eea_european.pm25.hourly': 'aq:products.eeaPm25Hourly',
  'eea_european.pm10.hourly': 'aq:products.eeaPm10Hourly',
  'eea_european.o3.hourly': 'aq:products.eeaOzoneHourly',
  'eea_european.no2.hourly': 'aq:products.eeaNitrogenDioxideHourly',
  'eea_european.so2.hourly': 'aq:products.eeaSulfurDioxideHourly',
  'us_epa.pm25.nowcast': 'aq:products.usEpaPm25Nowcast',
  'us_epa.pm10.nowcast': 'aq:products.usEpaPm10Nowcast',
  'us_epa.o3.latest': 'aq:products.usEpaOzoneLatest',
  'us_epa.co.latest': 'aq:products.usEpaCarbonMonoxideLatest',
  'us_epa.no2.latest': 'aq:products.usEpaNitrogenDioxideLatest',
  'us_epa.so2.latest': 'aq:products.usEpaSulfurDioxideLatest',
  'us_epa.pm25.completed_day': 'aq:products.usEpaPm25CompletedDay',
  'us_epa.pm10.completed_day': 'aq:products.usEpaPm10CompletedDay',
  'philippines_denr.pm25.completed_day': 'aq:products.philippinesPm25CompletedDay',
  'philippines_denr.pm10.completed_day': 'aq:products.philippinesPm10CompletedDay',
  'philippines_denr.so2.completed_day': 'aq:products.philippinesSo2CompletedDay',
  'philippines_denr.o3.latest': 'aq:products.philippinesOzoneLatest',
  'philippines_denr.co.latest': 'aq:products.philippinesCarbonMonoxideLatest',
  'philippines_denr.no2.latest': 'aq:products.philippinesNitrogenDioxideLatest',
} as const;

export function getAirQualityIndexStandardLabel(standardCode: string): string {
  const key = STANDARD_KEYS[standardCode as keyof typeof STANDARD_KEYS];
  return key ? i18n.t(key) : i18n.t('aq:unknown.standard', { code: standardCode });
}

export function getAirQualityIndexProductLabel(productCode: string): string {
  const key = PRODUCT_KEYS[productCode as keyof typeof PRODUCT_KEYS];
  return key ? i18n.t(key) : i18n.t('aq:unknown.product', { code: productCode });
}

export function getAirQualityIndexCategoryLabel(categoryCode: string): string {
  const key = CATEGORY_KEYS[categoryCode as keyof typeof CATEGORY_KEYS];
  return key ? i18n.t(key) : i18n.t('aq:unknown.category', { code: categoryCode });
}

export interface EuropeanAqiMarkerPresentation {
  categoryLabel: string;
  color: string;
  isAvailable: boolean;
  isPartial: boolean;
  markerText: string;
  accessibleLabel: string;
}

export interface EuropeanAqiDisplayedResult {
  parameterCode: string | null;
  categoryCode: string | null;
  categoryLabel: string | null;
  eligibilityStatus: string;
  exclusionReason: string | null;
}


export function getPollutantDisplayLabel(parameterCode: string): string {
  const normalizedParameterCode = parameterCode.trim().toLowerCase();
  return POLLUTANT_DISPLAY_LABELS[normalizedParameterCode] ?? parameterCode.toUpperCase();
}


export function formatPollutantList(parameterCodes: string[]): string {
  if (parameterCodes.length === 0) return i18n.t('aq:common.none');
  return formatDisplayList(
    parameterCodes.map(getPollutantDisplayLabel),
    i18n.resolvedLanguage === 'es' ? 'es' : 'en',
    { type: 'unit' },
  );
}


export function getExclusionReasonLabel(exclusionReason: string | null): string {
  if (!exclusionReason) return i18n.t('aq:common.unavailable');
  const key = EXCLUSION_REASON_KEYS[exclusionReason as keyof typeof EXCLUSION_REASON_KEYS];
  return key ? i18n.t(key) : i18n.t('aq:common.unavailable');
}


export function getAirQualityIndexAuditFlagLabel(auditFlag: string): string {
  const key = AUDIT_FLAG_KEYS[auditFlag as keyof typeof AUDIT_FLAG_KEYS];
  return key ? i18n.t(key) : i18n.t('aq:auditFlags.additionalNote');
}


export function getAirQualityIndexCoverageStatusLabel(coverageStatus: string | null): string {
  if (!coverageStatus) return i18n.t('aq:common.notAvailable');
  const key = COVERAGE_STATUS_KEYS[coverageStatus as keyof typeof COVERAGE_STATUS_KEYS];
  return key ? i18n.t(key) : i18n.t('aq:common.notAvailable');
}


export function formatUtcInterval(startedAt: string, endedAt: string): string {
  const options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  } as const;
  const languageCode = i18n.resolvedLanguage === 'es' ? 'es' : 'en';
  return i18n.t('aq:interval.utcRange', {
    start: formatDisplayDateTime(startedAt, languageCode, options),
    end: formatDisplayDateTime(endedAt, languageCode, options),
  });
}


export function getAirQualityIndexTimeResolutionLabel(
  product: Pick<AirQualityIndexProductMetadata, 'product_code' | 'aggregation_period'> & Partial<AirQualityIndexProductMetadata>,
): string {
  const compactLabelKeys = {
    'us_epa.pm25.nowcast': 'aq:aggregation.nowCastTwelveHour',
    'us_epa.pm10.nowcast': 'aq:aggregation.nowCastTwelveHour',
    'us_epa.o3.latest': 'aq:aggregation.selectedOzoneResult',
    'us_epa.co.latest': 'aq:aggregation.eightHourAverage',
    'us_epa.no2.latest': 'aq:aggregation.oneHourAverage',
    'us_epa.so2.latest': 'aq:aggregation.twentyFourHourEvaluation',
    'us_epa.pm25.completed_day': 'aq:aggregation.completedLocalDay',
    'us_epa.pm10.completed_day': 'aq:aggregation.completedLocalDay',
    'philippines_denr.pm25.completed_day': 'aq:aggregation.completedLocalDay',
    'philippines_denr.pm10.completed_day': 'aq:aggregation.completedLocalDay',
    'philippines_denr.so2.completed_day': 'aq:aggregation.completedLocalDay',
    'philippines_denr.o3.latest': 'aq:aggregation.selectedOzoneResult',
  } as const;
  const key = compactLabelKeys[product.product_code as keyof typeof compactLabelKeys];
  if (key) return i18n.t(key);
  if (product.product_kind === 'completed_day' || product.aggregation_period === 'completed_local_day') {
    return i18n.t('aq:aggregation.completedLocalDay');
  }
  if (product.product_kind === 'nowcast' || product.aggregation_period === '12h_nowcast') {
    return i18n.t('aq:aggregation.nowCastTwelveHour');
  }
  return getAggregationDisplayLabel(product.aggregation_period);
}


export function getEuropeanAqiCategoryColor(
  categoryCode: string | null,
  categories: AirQualityIndexCategoryMetadata[],
): string {
  if (!categoryCode) return EUROPEAN_AQI_UNAVAILABLE_COLOR;
  return categories.find((category) => category.code === categoryCode)?.color
    ?? EUROPEAN_AQI_UNAVAILABLE_COLOR;
}


export function getEuropeanAqiDisplayedResult(
  airQualityIndexResult: DeviceAirQualityIndexResult,
  product: AirQualityIndexProductMetadata,
): EuropeanAqiDisplayedResult {
  if (product.result_scope === 'pollutant' && product.parameter_code) {
    const pollutantResult = airQualityIndexResult.pollutant_results.find(
      (candidate) => candidate.parameter_code === product.parameter_code,
    );
    return {
      parameterCode: product.parameter_code,
      categoryCode: pollutantResult?.category_code ?? null,
      categoryLabel: pollutantResult?.category_label ?? null,
      eligibilityStatus: pollutantResult?.eligibility_status ?? 'ineligible',
      exclusionReason: pollutantResult?.exclusion_reason ?? 'no_eligible_pollutants',
    };
  }

  return {
    parameterCode: null,
    categoryCode: airQualityIndexResult.category_code,
    categoryLabel: airQualityIndexResult.category_label,
    eligibilityStatus: airQualityIndexResult.eligibility_status,
    exclusionReason: airQualityIndexResult.exclusion_reasons[0] ?? null,
  };
}


export function getEuropeanAqiMarkerPresentation(
  airQualityIndexResult: DeviceAirQualityIndexResult,
  standardMetadata: AirQualityIndexStandardMetadata,
  product: AirQualityIndexProductMetadata,
): EuropeanAqiMarkerPresentation {
  const displayedResult = getEuropeanAqiDisplayedResult(airQualityIndexResult, product);
  const isAvailable = displayedResult.eligibilityStatus === 'eligible'
    && displayedResult.categoryCode !== null
    && displayedResult.categoryLabel !== null;
  const isPartial = airQualityIndexResult.coverage.coverage_status === 'partial';
  const categoryLabel = isAvailable
    ? getAirQualityIndexCategoryLabel(displayedResult.categoryCode!)
    : i18n.t('aq:common.unavailable');
  const markerText = isPartial && isAvailable
    ? i18n.t('aq:marker.partial', { category: categoryLabel })
    : categoryLabel;
  const deviceName = airQualityIndexResult.device_friendly_name
    || airQualityIndexResult.device_name
    || i18n.t('aq:marker.device', { id: airQualityIndexResult.device_id });
  const productLabel = getAirQualityIndexProductLabel(product.product_code);
  return {
    categoryLabel,
    color: isAvailable
      ? getEuropeanAqiCategoryColor(displayedResult.categoryCode, standardMetadata.categories)
      : EUROPEAN_AQI_UNAVAILABLE_COLOR,
    isAvailable,
    isPartial,
    markerText,
    accessibleLabel: i18n.t('aq:marker.accessibleLabel', {
      device: deviceName,
      product: productLabel,
      category: categoryLabel,
      coverage: isPartial ? i18n.t('aq:coverage.partialPollutant') : '',
    }),
  };
}


export function formatCompletedEuropeanAqiHour(observedAt: string): string {
  return formatTimestamp(observedAt, 'utc');
}


export function categoriesWithEuropeanColors(
  categories: AirQualityIndexCategoryMetadata[],
): AirQualityIndexCategoryMetadata[] {
  return [...categories]
    .sort((firstCategory, secondCategory) => (
      firstCategory.internal_severity_rank - secondCategory.internal_severity_rank
    ));
}
