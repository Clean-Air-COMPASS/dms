import type {
  AirQualityIndexProductMetadata,
  AirQualityIndexStandardMetadata,
} from './airQualityIndex';
import type { MeasurementAggregationCapability } from './measurementAggregations';
import i18n from './i18n';
import { getAirQualityIndexStandardLabel } from './airQualityIndexPresentation';
import { getAggregationDisplayLabel } from './aqi';


export type MapLayer = 'devices' | 'measurements' | 'aqi';

export interface SelectedDataProduct {
  layer: MapLayer;
  parameter_code: string;
  aggregation_period: string;
  air_quality_index_product_code: string;
}

export interface RequestedMapSelection extends SelectedDataProduct {
  standard_code: string;
}

export interface MeasurementParameterMetadata {
  code: string;
  display_name: string;
}

export interface AggregationPeriodMetadata {
  code: string;
  display_name: string;
}

export interface ParameterAggregationMetadata {
  parameter_code: string;
  aggregation_code: string;
}

export interface AggregationRollupMetadata {
  parameter_code: string;
  to_period_code: string;
}

export interface MapSelectionMetadata {
  parameters: MeasurementParameterMetadata[];
  measurement_aggregation_capabilities: MeasurementAggregationCapability[];
  air_quality_index_standards: AirQualityIndexStandardMetadata[];
}

export interface NormalizedMapSelection {
  selection: SelectedDataProduct;
  unavailable_reason: string | null;
}


const DEFAULT_MEASUREMENT_PARAMETER_CODE = 'pm25';


function normalizeCode(value: string | null | undefined): string {
  return (value || '').trim().toLowerCase();
}


export function createRequestedMapSelection(search: string): RequestedMapSelection {
  const searchParameters = new URLSearchParams(search);
  const requestedDisplayMode = normalizeCode(searchParameters.get('display_mode'));
  const standardCode = normalizeCode(searchParameters.get('standard_code'));
  const productCode = normalizeCode(searchParameters.get('product_code'));
  const requestedMode = normalizeCode(searchParameters.get('mode'));
  const requestedAggregation = normalizeCode(searchParameters.get('time_resolution'));
  const isAirQualityIndex = (
    requestedDisplayMode === 'us_epa'
    || requestedDisplayMode === 'eea_european'
    || requestedDisplayMode === 'philippines_denr'
    || standardCode === 'us_epa'
    || standardCode === 'eea_european'
    || standardCode === 'philippines_denr'
    || Boolean(productCode)
  );

  return {
    layer: isAirQualityIndex
      ? 'aqi'
      : requestedMode === 'pollutants' ? 'measurements' : 'devices',
    parameter_code: normalizeCode(searchParameters.get('parameter')),
    aggregation_period: requestedAggregation,
    air_quality_index_product_code: productCode,
    standard_code: standardCode || (
      requestedDisplayMode === 'us_epa'
      || requestedDisplayMode === 'eea_european'
      || requestedDisplayMode === 'philippines_denr'
        ? requestedDisplayMode
        : ''
    ),
  };
}


export function listAvailableAirQualityIndexProducts(
  standards: AirQualityIndexStandardMetadata[],
): AirQualityIndexProductMetadata[] {
  return standards.flatMap((standard) => (
    standard.products.filter((product) => product.availability_status === 'available')
  ));
}


export function findAirQualityIndexProduct(
  standards: AirQualityIndexStandardMetadata[],
  productCode: string,
): AirQualityIndexProductMetadata | null {
  const normalizedProductCode = normalizeCode(productCode);
  if (!normalizedProductCode) return null;
  return listAvailableAirQualityIndexProducts(standards).find(
    (product) => normalizeCode(product.product_code) === normalizedProductCode,
  ) ?? null;
}


export function findStandardForProduct(
  standards: AirQualityIndexStandardMetadata[],
  productCode: string,
): AirQualityIndexStandardMetadata | null {
  const normalizedProductCode = normalizeCode(productCode);
  return standards.find((standard) => standard.products.some(
    (product) => normalizeCode(product.product_code) === normalizedProductCode,
  )) ?? null;
}


export function listValidAggregationPeriods(
  metadata: MapSelectionMetadata,
  layer: 'devices' | 'measurements',
  parameterCode: string,
): AggregationPeriodMetadata[] {
  const normalizedParameterCode = normalizeCode(parameterCode);
  const optionsByCode = new Map<string, AggregationPeriodMetadata>();
  metadata.measurement_aggregation_capabilities.forEach((capability) => {
    if (
      normalizedParameterCode
      && normalizeCode(capability.parameter_code) !== normalizedParameterCode
    ) return;
    capability.supported_aggregations
      .filter((option) => option.supports_latest)
      .forEach((option) => {
        const code = normalizeCode(option.result_aggregation_code);
        if (!optionsByCode.has(code)) {
          optionsByCode.set(code, { code, display_name: getAggregationDisplayLabel(code) });
        }
      });
  });

  // Devices with no selected parameter can qualify through any configured
  // measurement stream. Measurements always require parameter compatibility.
  if (layer === 'measurements' && !normalizedParameterCode) return [];
  return [...optionsByCode.values()];
}


function normalizeMeasurementSelection(
  requested: RequestedMapSelection,
  metadata: MapSelectionMetadata,
): NormalizedMapSelection {
  if (metadata.parameters.length === 0) {
    return {
      selection: {
        layer: 'measurements',
        parameter_code: '',
        aggregation_period: '',
        air_quality_index_product_code: '',
      },
      unavailable_reason: i18n.t('map:selection.messages.noMeasurementParameters'),
    };
  }

  const requestedParameterCode = normalizeCode(requested.parameter_code);
  const requestedParameterIsValid = metadata.parameters.some(
    (parameter) => normalizeCode(parameter.code) === requestedParameterCode,
  );
  const defaultParameterExists = metadata.parameters.some(
    (parameter) => normalizeCode(parameter.code) === DEFAULT_MEASUREMENT_PARAMETER_CODE,
  );
  const parameterCode = requestedParameterIsValid
    ? requestedParameterCode
    : defaultParameterExists ? DEFAULT_MEASUREMENT_PARAMETER_CODE : '';

  if (!parameterCode) {
    return {
      selection: {
        layer: 'measurements',
        parameter_code: '',
        aggregation_period: '',
        air_quality_index_product_code: '',
      },
      unavailable_reason: i18n.t('map:selection.messages.defaultPm25Unavailable'),
    };
  }

  const validAggregationPeriods = listValidAggregationPeriods(
    metadata,
    'measurements',
    parameterCode,
  );
  const requestedAggregationPeriod = normalizeCode(requested.aggregation_period);
  const aggregationPeriod = validAggregationPeriods.some(
    (period) => normalizeCode(period.code) === requestedAggregationPeriod,
  ) ? requestedAggregationPeriod : '';

  return {
    selection: {
      layer: 'measurements',
      parameter_code: parameterCode,
      aggregation_period: aggregationPeriod,
      air_quality_index_product_code: '',
    },
    unavailable_reason: null,
  };
}


function normalizeDeviceSelection(
  requested: RequestedMapSelection,
  metadata: MapSelectionMetadata,
): NormalizedMapSelection {
  const requestedParameterCode = normalizeCode(requested.parameter_code);
  const parameterCode = metadata.parameters.some(
    (parameter) => normalizeCode(parameter.code) === requestedParameterCode,
  ) ? requestedParameterCode : '';
  return {
    selection: {
      layer: 'devices',
      parameter_code: parameterCode,
      aggregation_period: '',
      air_quality_index_product_code: '',
    },
    unavailable_reason: null,
  };
}


function findRequestedAirQualityIndexProduct(
  requested: RequestedMapSelection,
  standard: AirQualityIndexStandardMetadata,
): AirQualityIndexProductMetadata | null {
  const availableProducts = standard.products.filter(
    (product) => product.availability_status === 'available',
  );
  const requestedProductCode = normalizeCode(requested.air_quality_index_product_code);
  if (requestedProductCode) {
    return availableProducts.find(
      (product) => normalizeCode(product.product_code) === requestedProductCode,
    ) ?? null;
  }

  return availableProducts.find(
    (product) => normalizeCode(product.product_code) === normalizeCode(standard.default_product_code),
  ) ?? null;
}


function normalizeAirQualityIndexSelection(
  requested: RequestedMapSelection,
  metadata: MapSelectionMetadata,
): NormalizedMapSelection {
  if (metadata.air_quality_index_standards.length === 0) {
    return {
      selection: {
        layer: 'aqi',
        parameter_code: '',
        aggregation_period: '',
        air_quality_index_product_code: '',
      },
      unavailable_reason: i18n.t('map:selection.messages.aqiMetadataUnavailable'),
    };
  }

  const productByCode = findAirQualityIndexProduct(
    metadata.air_quality_index_standards,
    requested.air_quality_index_product_code,
  );
  const requestedProductCode = normalizeCode(
    requested.air_quality_index_product_code,
  );
  if (requestedProductCode && !productByCode) {
    return {
      selection: {
        layer: 'aqi',
        parameter_code: '',
        aggregation_period: '',
        air_quality_index_product_code: '',
      },
      unavailable_reason: i18n.t('map:selection.messages.productUnavailable', {
        code: requestedProductCode,
      }),
    };
  }
  const legacyAggregationCode = normalizeCode(requested.aggregation_period);
  if (
    !requestedProductCode
    && (legacyAggregationCode === 'aqi' || legacyAggregationCode.startsWith('aqi-'))
  ) {
    return {
      selection: {
        layer: 'aqi',
        parameter_code: '',
        aggregation_period: '',
        air_quality_index_product_code: '',
      },
      unavailable_reason: i18n.t('map:selection.messages.legacySelectionUnavailable', {
        code: legacyAggregationCode,
      }),
    };
  }
  let standard = productByCode
    ? findStandardForProduct(metadata.air_quality_index_standards, productByCode.product_code)
    : null;

  const requestedStandardCode = normalizeCode(requested.standard_code);
  if (!standard && requestedStandardCode) {
    standard = metadata.air_quality_index_standards.find(
      (candidate) => normalizeCode(candidate.standard_code) === requestedStandardCode,
    ) ?? null;
    if (!standard) {
      return {
        selection: {
          layer: 'aqi',
          parameter_code: '',
          aggregation_period: '',
          air_quality_index_product_code: '',
        },
        unavailable_reason: i18n.t('map:selection.messages.standardUnavailable', {
          code: requestedStandardCode,
        }),
      };
    }
  }

  if (!standard) {
    standard = metadata.air_quality_index_standards.find((candidate) => candidate.is_default) ?? null;
  }
  if (!standard) {
    return {
      selection: {
        layer: 'aqi',
        parameter_code: '',
        aggregation_period: '',
        air_quality_index_product_code: '',
      },
      unavailable_reason: i18n.t('map:selection.messages.noDefaultStandard'),
    };
  }

  const product = productByCode ?? findRequestedAirQualityIndexProduct(requested, standard);
  if (!product) {
    return {
      selection: {
        layer: 'aqi',
        parameter_code: '',
        aggregation_period: '',
        air_quality_index_product_code: '',
      },
      unavailable_reason: i18n.t('map:selection.messages.noMapProducts', {
        standard: getAirQualityIndexStandardLabel(standard.standard_code),
      }),
    };
  }

  return {
    selection: {
      layer: 'aqi',
      parameter_code: normalizeCode(product.parameter_code),
      aggregation_period: normalizeCode(product.aggregation_period),
      air_quality_index_product_code: product.product_code,
    },
    unavailable_reason: null,
  };
}


export function normalizeSelectedDataProduct(
  requested: RequestedMapSelection,
  metadata: MapSelectionMetadata,
): NormalizedMapSelection {
  if (requested.layer === 'devices') return normalizeDeviceSelection(requested, metadata);
  if (requested.layer === 'measurements') return normalizeMeasurementSelection(requested, metadata);
  return normalizeAirQualityIndexSelection(requested, metadata);
}
