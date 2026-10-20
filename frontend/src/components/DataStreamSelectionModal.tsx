import { isValidAnalyticsDateRange } from '../analyticsDateRange';
import ZonedDateTimeInput from './ZonedDateTimeInput';
import { resolveDisplayTimezone } from '../utils/timezone';
import { Trans } from 'react-i18next';
import i18n from '../i18n';
import DataStreamDialog from './DataStreamDialog';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchJson, listPublicDataSources, type PublicDataSource } from '../api';
import {
  MAX_ANALYTICS_SCALE_GROUPS,
  MAX_ANALYTICS_SERIES,
  analyticsScaleGroupKey,
  analyticsSeriesKey,
  type AirQualityIndexSeriesSelection,
} from '../analyticsSeries';
import type {
  AirQualityIndexProductMetadata,
  AirQualityIndexStandardMetadata,
} from '../airQualityIndex';
import {
  getAirQualityIndexProductLabel,
  getAirQualityIndexStandardLabel,
  getAirQualityIndexTimeResolutionLabel,
} from '../airQualityIndexPresentation';
import {
  getMeasurementAggregationOptions,
  type MeasurementAggregationCapability,
} from '../measurementAggregations';
import { getAggregationDisplayLabel } from '../aqi';
import { getParameterDisplayName } from '../parameterPresentation';

export type DataStreamResult = {
  sensor_id: number;
  external_sensor_id?: string | number | null;
  parameter: string;
  parameter_name?: string;
  unit?: string;
  device_name?: string;
  device_id?: number | null;
  network?: string | null;
  latest_value?: number | null;
  latest_observed_at?: string | null;
  
  sensor_aggregation_period?: string | null;
};

type ParameterOption = {
  code: string;
  display_name: string;
  unit_symbol?: string | null;
};

type ExistingDataStreamKey = {
  sensor_id: number;
  parameter: string;
  aggregate: string;
};

type DataStreamSelectionModalProps = {
  open: boolean;
  onClose: () => void;
  onSelectPrimary: (
    sensor_id: number,
    parameter: string,
    options: { aggregate: string }
  ) => void;
  onSelectOverlay: (
    sensor_id: number,
    parameter: string,
    options: { aggregate: string }
  ) => void;
  initialParameter?: string;
  initialAggregate?: string;
  startIso: string;
  endIso: string;
  rangeValid: boolean;
  onStartChange: (iso: string) => void;
  onEndChange: (iso: string) => void;
  onStartValidityChange: (valid: boolean) => void;
  onEndValidityChange: (valid: boolean) => void;
  displayTimezone?: string | null;
  
  existingSelections?: ExistingDataStreamKey[];
  existingAqiSelections?: AirQualityIndexSeriesSelection[];
  aqiStandards?: AirQualityIndexStandardMetadata[];
  aqiDevices?: AirQualityIndexDeviceOption[];
  aqiCatalogLoading?: boolean;
  aqiCatalogError?: string | null;
  onRetryAqiCatalog?: () => void;
  currentSeriesCount?: number;
  existingScaleGroupKeys?: string[];
  onSelectAqi?: (
    series: AirQualityIndexSeriesSelection,
    options: { role: 'primary' | 'overlay' },
  ) => void;
};


export type AirQualityIndexDeviceOption = {
  device_id: number;
  name: string;
  friendly_name: string | null;
  timezone: string | null;
  network: string | null;
  sensor_count: number;
};

const DEFAULT_DATA_SOURCE_OPTIONS: PublicDataSource[] = [
  { name: 'Other', filter_value: 'other' },
];


function availableAirQualityIndexProducts(
  standard: AirQualityIndexStandardMetadata | undefined,
): AirQualityIndexProductMetadata[] {
  return standard?.products.filter((product) => (
    product.availability_status === 'available' && product.history_status === 'available'
  )) || [];
}


function DataTypeSelector({
  value,
  onChange,
}: {
  value: 'measurement' | 'aqi';
  onChange: (value: 'measurement' | 'aqi') => void;
}) {
  return (
    <fieldset>
      <legend className="block text-sm font-medium text-slate-700 mb-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.dataType" /></legend>
      <div className="data-type-selector" aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.selectDataType')}>
        <button
          type="button"
          onClick={() => onChange('measurement')}
          aria-pressed={value === 'measurement'}
        >
          <Trans ns="analytics" i18nKey="dataStreamSelectionModal.actions.measurement" /></button>
        <button
          type="button"
          onClick={() => onChange('aqi')}
          aria-pressed={value === 'aqi'}
        >
          <Trans ns="analytics" i18nKey="dataStreamSelectionModal.actions.aqi" /></button>
      </div>
    </fieldset>
  );
}

export default function DataStreamSelectionModal({
  open,
  onClose,
  onSelectPrimary,
  onSelectOverlay,
  initialParameter = '',
  
  startIso,
  endIso,
  rangeValid,
  onStartChange,
  onEndChange,
  onStartValidityChange,
  onEndValidityChange,
  displayTimezone = resolveDisplayTimezone('local'),
  existingSelections = [],
  existingAqiSelections = [],
  aqiStandards = [],
  aqiDevices = [],
  aqiCatalogLoading = false,
  aqiCatalogError = null,
  onRetryAqiCatalog,
  currentSeriesCount = 0,
  existingScaleGroupKeys = [],
  onSelectAqi,
}: DataStreamSelectionModalProps) {
  const [selectedDataType, setSelectedDataType] = useState<'measurement' | 'aqi'>('measurement');
  const [parameters, setParameters] = useState<ParameterOption[]>([]);
  const [measurementCapabilities, setMeasurementCapabilities] = useState<MeasurementAggregationCapability[]>([]);
  const [selectedParameter, setSelectedParameter] = useState<string>(initialParameter);
  const [selectedDataSource, setSelectedDataSource] = useState<string>('');
  const [dataSourceOptions, setDataSourceOptions] = useState<PublicDataSource[]>(DEFAULT_DATA_SOURCE_OPTIONS);
  
  const [selectedTimeResolution, setSelectedTimeResolution] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  
  const [selectionAction, setSelectionAction] = useState<'primary' | 'overlay'>(() =>
    existingSelections.length + existingAqiSelections.length > 0 ? 'overlay' : 'primary'
  );
  const [streamAggregationSelections, setStreamAggregationSelections] = useState<Record<number, string>>({});

  const [dataStreams, setDataStreams] = useState<DataStreamResult[]>([]);
  const [dataStreamsLoading, setDataStreamsLoading] = useState<boolean>(false);
  const [dataStreamsError, setDataStreamsError] = useState<string | null>(null);
  const [parametersLoading, setParametersLoading] = useState<boolean>(true);
  const [parametersError, setParametersError] = useState(false);
  const [filtersRetry, setFiltersRetry] = useState(0);
  
  
  const discoveryRequest = useRef(0);
  const [hasLoadedSensors, setHasLoadedSensors] = useState<boolean>(false);
  const [selectedAqiStandardCode, setSelectedAqiStandardCode] = useState('');
  const [selectedAqiProductCode, setSelectedAqiProductCode] = useState('');

  useEffect(() => {
    setSelectedParameter(initialParameter || '');
  }, [initialParameter]);
  

  
  useEffect(() => {
    if (!open) return;
    setSelectionAction(existingSelections.length + existingAqiSelections.length > 0 ? 'overlay' : 'primary');
  }, [open, existingSelections.length, existingAqiSelections.length]);

  useEffect(() => {
    if (!open || aqiStandards.length === 0) return;
    const selectedStandard = aqiStandards.find(
      (standard) => standard.standard_code === selectedAqiStandardCode,
    ) || aqiStandards.find((standard) => standard.is_default) || aqiStandards[0];
    if (selectedStandard.standard_code !== selectedAqiStandardCode) {
      setSelectedAqiStandardCode(selectedStandard.standard_code);
    }
    const products = availableAirQualityIndexProducts(selectedStandard);
    if (!products.some((product) => product.product_code === selectedAqiProductCode)) {
      const defaultProduct = products.find(
        (product) => product.product_code === selectedStandard.default_product_code,
      ) || products[0];
      setSelectedAqiProductCode(defaultProduct?.product_code || '');
    }
  }, [open, aqiStandards, selectedAqiStandardCode, selectedAqiProductCode]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setParametersLoading(true);
    setParametersError(false);
    (async () => {
      try {
        const capabilityParams = new URLSearchParams();
        if (selectedParameter) capabilityParams.set('parameter', selectedParameter);
        if (selectedDataSource) capabilityParams.set('source', selectedDataSource);
        const capabilityQuery = capabilityParams.toString();
        const [parameterList, capabilities] = await Promise.all([
          fetchJson<ParameterOption[]>('/parameters'),
          fetchJson<MeasurementAggregationCapability[]>(
            `/measurement-aggregation-capabilities${capabilityQuery ? `?${capabilityQuery}` : ''}`,
          ),
        ]);
        if (cancelled) return;
        setParameters(parameterList || []);
        setMeasurementCapabilities(capabilities || []);
        // Require an explicit parameter before loading observations.
      } catch {
        if (!cancelled) {
          setParametersError(true);
          setParameters([]);
          setMeasurementCapabilities([]);
        }
      } finally {
        if (!cancelled) setParametersLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, selectedDataSource, selectedParameter, filtersRetry]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      try {
        const sources = await listPublicDataSources({ skipCache: true });
        if (cancelled) return;
        setDataSourceOptions((sources && sources.length > 0) ? sources : DEFAULT_DATA_SOURCE_OPTIONS);
      } catch {
        if (!cancelled) {
          setDataSourceOptions(DEFAULT_DATA_SOURCE_OPTIONS);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  
  const fetchDataStreams = useCallback(async () => {
    if (!rangeValid || !selectedParameter) return;
    const request = ++discoveryRequest.current;
    setDataStreamsLoading(true);
    setDataStreamsError(null);
    setHasLoadedSensors(true);
    try {
      const queryParams = new URLSearchParams();
      queryParams.set('since', startIso);
      queryParams.set('until', endIso);
      
      if (selectedDataSource) {
        queryParams.set('external_api_name', selectedDataSource);
      }
      
      const endpoint = `/measurements/${encodeURIComponent(selectedParameter)}/latest`;
      const queryString = queryParams.toString();
      const url = queryString ? `${endpoint}?${queryString}` : endpoint;
      const response = await fetchJson<any[]>(url, { skipCache: true });
      const mappedStreams: DataStreamResult[] = (response || []).map((row: any) => ({
        sensor_id: row.sensor_id,
        external_sensor_id: row.external_sensor_id,
        parameter: row.parameter,
        parameter_name: row.parameter_name,
        unit: row.unit,
        device_name: row.device?.name || row.device?.friendly_name || '',
        device_id: row.device?.device_id || null,
        network: row.device?.network || null,
        latest_value: row.value,
        latest_observed_at: row.observed_at,
        sensor_aggregation_period: row.sensor_aggregation_period || null,
      }));
      if (request !== discoveryRequest.current) return;
      setDataStreams(mappedStreams);
      
      setStreamAggregationSelections({});
    } catch {
      if (request !== discoveryRequest.current) return;
      setDataStreamsError(i18n.t('common:errors.loadDataStreams'));
      setDataStreams([]);
    } finally {
      if (request === discoveryRequest.current) setDataStreamsLoading(false);
    }
  }, [selectedParameter, selectedDataSource, startIso, endIso, rangeValid]);

  
  useEffect(() => {
    // Discovery belongs to this mode and query; late responses must not restore stale rows.
    discoveryRequest.current += 1;
    setHasLoadedSensors(false);
    setDataStreams([]);
    setDataStreamsError(null);
    setDataStreamsLoading(false);
    setStreamAggregationSelections({});
    return () => { discoveryRequest.current += 1; };
  }, [open, selectedDataType, selectedParameter, selectedDataSource, startIso, endIso, rangeValid]);

  
  const availableTimeResolutions = useMemo(() => {
    
    
    
    
    const optionsByCode = new Map<string, { code: string; duration_minutes?: number | null }>();
    measurementCapabilities.forEach((capability) => capability.supported_aggregations
      .filter((option) => option.supports_history)
      .forEach((option) => optionsByCode.set(option.result_aggregation_code, {
        code: option.result_aggregation_code,
        duration_minutes: option.duration_minutes,
      })));
    return [...optionsByCode.values()]
      .sort((a, b) => {
        
        const durationA = a.duration_minutes ?? Number.MAX_SAFE_INTEGER;
        const durationB = b.duration_minutes ?? Number.MAX_SAFE_INTEGER;
        return durationA - durationB;
      })
      .map(period => ({
        code: period.code.toLowerCase(),
      }));
  }, [measurementCapabilities]);

  useEffect(() => {
    if (!selectedTimeResolution) return;
    const resolutionIsAvailable = availableTimeResolutions.some(
      (resolution) => resolution.code === selectedTimeResolution,
    );
    if (!resolutionIsAvailable) {
      setSelectedTimeResolution('');
    }
  }, [availableTimeResolutions, selectedTimeResolution]);

  const filteredDataStreams = useMemo(() => {
    let filtered = dataStreams;

    
    if (selectedTimeResolution) {
      filtered = filtered.filter((stream) => {
        const supportedCodes = getMeasurementAggregationOptions({
          nativeAggregationCode: stream.sensor_aggregation_period,
          parameterCode: stream.parameter || selectedParameter,
          capabilities: measurementCapabilities,
          usage: 'history',
        }).map((option) => option.code.toLowerCase());
        return supportedCodes.includes(selectedTimeResolution.toLowerCase());
      });
    }

    if (selectedDataSource) {
      filtered = filtered.filter((stream) => {
        const streamNetwork = (stream.network || '').toLowerCase();
        return streamNetwork.includes(selectedDataSource.toLowerCase());
      });
    }

    if (searchQuery.trim()) {
      const queryLower = searchQuery.toLowerCase();
      filtered = filtered.filter((stream) => {
        const deviceNameMatch = (stream.device_name || '').toLowerCase().includes(queryLower);
        const externalIdMatch = String(stream.external_sensor_id || '').toLowerCase().includes(queryLower);
        const sensorIdMatch = String(stream.sensor_id).includes(queryLower);
        return deviceNameMatch || externalIdMatch || sensorIdMatch;
      });
    }

    return filtered.slice(0, 50);
  }, [
    dataStreams,
    measurementCapabilities,
    searchQuery,
    selectedDataSource,
    selectedParameter,
    selectedTimeResolution,
  ]);

  
  const getValidAggregationsForStream = useCallback((stream: DataStreamResult): { code: string; display: string }[] => {
    return getMeasurementAggregationOptions({
      nativeAggregationCode: stream.sensor_aggregation_period,
      parameterCode: stream.parameter || selectedParameter,
      capabilities: measurementCapabilities,
      usage: 'history',
    });
  }, [measurementCapabilities, selectedParameter]);

  
  const isStreamAlreadySelected = useCallback((stream: DataStreamResult, aggregateCode: string): boolean => {
    return existingSelections.some(
      s => s.sensor_id === stream.sensor_id &&
           s.parameter.toLowerCase() === (stream.parameter || selectedParameter).toLowerCase() &&
           s.aggregate.toLowerCase() === aggregateCode.toLowerCase()
    );
  }, [existingSelections, selectedParameter]);

  const handleSelectStream = useCallback(
    (stream: DataStreamResult) => {
      
      const selectedAggregate = streamAggregationSelections[stream.sensor_id] || 
                               stream.sensor_aggregation_period || 
                               'raw';
      
      
      if (isStreamAlreadySelected(stream, selectedAggregate)) {
        
        return;
      }
      const candidateScaleGroup = analyticsScaleGroupKey({
        kind: 'measurement',
        normalized_unit: stream.unit || i18n.t('analytics:analytics.states.unknownUnit'),
      });
      const wouldAddScaleGroup = !existingScaleGroupKeys.includes(candidateScaleGroup);
      if (currentSeriesCount >= MAX_ANALYTICS_SERIES
        || (wouldAddScaleGroup && new Set(existingScaleGroupKeys).size >= MAX_ANALYTICS_SCALE_GROUPS)) {
        return;
      }
      
      const selectionOptions = {
        aggregate: selectedAggregate,
      };
      if (selectionAction === 'primary') {
        onSelectPrimary(stream.sensor_id, stream.parameter || selectedParameter, selectionOptions);
      } else {
        onSelectOverlay(stream.sensor_id, stream.parameter || selectedParameter, selectionOptions);
      }
      onClose();
    },
    [
      selectionAction,
      streamAggregationSelections,
      isStreamAlreadySelected,
      selectedParameter,
      onSelectPrimary,
      onSelectOverlay,
      onClose,
      currentSeriesCount,
      existingScaleGroupKeys,
    ]
  );

  
  

  if (!open) return null;

  if (selectedDataType === 'aqi') {
    const selectedStandard = aqiStandards.find(
      (standard) => standard.standard_code === selectedAqiStandardCode,
    ) || aqiStandards.find((standard) => standard.is_default) || aqiStandards[0];
    const products = availableAirQualityIndexProducts(selectedStandard);
    const selectedProduct = products.find(
      (product) => product.product_code === selectedAqiProductCode,
    ) || products[0];
    const selectedSourceOption = dataSourceOptions.find(
      (sourceOption) => sourceOption.filter_value === selectedDataSource,
    );
    const selectedSourceName = selectedSourceOption?.name || selectedDataSource;
    const normalizedSearch = searchQuery.trim().toLowerCase();
    const matchingDevices = aqiDevices.filter((device) => (
      (!selectedDataSource || device.network?.toLowerCase() === selectedSourceName.toLowerCase())
      && (!normalizedSearch || `${device.friendly_name || ''} ${device.name} ${device.network || ''} ${device.device_id}`.toLowerCase().includes(normalizedSearch))
    ));
    const candidateScaleGroup = selectedStandard
      ? analyticsScaleGroupKey({
          kind: 'aqi',
          result_kind: selectedStandard.result_kind,
          standard_code: selectedStandard.standard_code,
        })
      : null;
    const exceedsScaleLimit = candidateScaleGroup != null
      && !existingScaleGroupKeys.includes(candidateScaleGroup)
      && new Set(existingScaleGroupKeys).size >= MAX_ANALYTICS_SCALE_GROUPS;

    return (
      <DataStreamDialog onClose={onClose}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 flex-shrink-0">
          <h2 className="text-xl font-semibold text-slate-800"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.headings.selectDataStream" /></h2>
          <button type="button" className="text-slate-400 hover:text-slate-600 text-2xl leading-none" onClick={onClose} aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.closeModal')}>×</button>
        </div>
        <div className="data-stream-dialog-content">
          <div className="px-6 py-4 space-y-4 border-b border-slate-200">
            <DataTypeSelector value={selectedDataType} onChange={setSelectedDataType} />
            <p className="text-sm text-slate-600"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.aqiDiscovery" /></p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block text-sm font-medium text-slate-700"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.standard" /><select className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200" value={selectedStandard?.standard_code || ''} onChange={(event) => setSelectedAqiStandardCode(event.target.value)} disabled={aqiCatalogLoading || !!aqiCatalogError} aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.selectAqiStandard')}>
                  {aqiStandards.map((standard) => <option key={standard.standard_code} value={standard.standard_code}>{getAirQualityIndexStandardLabel(standard.standard_code)}</option>)}
                </select>
              </label>
              <label className="block text-sm font-medium text-slate-700"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.aqiProduct" /><select className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200" value={selectedProduct?.product_code || ''} onChange={(event) => setSelectedAqiProductCode(event.target.value)} disabled={aqiCatalogLoading || !!aqiCatalogError} aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.selectAqiProduct')}>
                  {products.map((product) => <option key={product.product_code} value={product.product_code}>{getAirQualityIndexProductLabel(product.product_code)}</option>)}
                </select>
              </label>
              <label className="block text-sm font-medium text-slate-700"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.calculationTimeResolution" /><input className="mt-1 w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-600" readOnly value={selectedProduct ? getAirQualityIndexTimeResolutionLabel(selectedProduct) : ''} />
              </label>
              <label className="block text-sm font-medium text-slate-700"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.dataSource" /><select className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200" value={selectedDataSource} onChange={(event) => setSelectedDataSource(event.target.value)} aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.selectAqiDataSource')}>
                  <option value=""><Trans ns="analytics" i18nKey="dataStreamSelectionModal.options.allSources" /></option>
                  {dataSourceOptions.map((option) => <option key={option.filter_value} value={option.filter_value}>{option.name}</option>)}
                </select>
              </label>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <p className="sm:col-span-2 text-sm text-slate-600">{displayTimezone ? i18n.t('analytics:timezones.displayedIn', { timezone: displayTimezone }) : i18n.t('analytics:timezones.unavailable')}</p>
              {!isValidAnalyticsDateRange(startIso, endIso) && <p role="alert" className="sm:col-span-2 text-sm text-red-700">{i18n.t('analytics:analytics.messages.invalidDateRange')}</p>}
              <ZonedDateTimeInput label={i18n.t('analytics:dataStreamSelectionModal.accessibility.startDateTime')} iso={startIso} timezone={displayTimezone} onChange={onStartChange} onValidityChange={onStartValidityChange} />
              <ZonedDateTimeInput label={i18n.t('analytics:dataStreamSelectionModal.accessibility.endDateTime')} iso={endIso} timezone={displayTimezone} onChange={onEndChange} onValidityChange={onEndValidityChange} />
            </div>
            <label className="block text-sm font-medium text-slate-700"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.searchDevices" /><input className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200" placeholder={i18n.t('analytics:dataStreamSelectionModal.placeholders.searchDeviceSourceId')} value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.searchAqiDevices')} />
            </label>
            <fieldset>
              <legend className="block text-sm font-medium text-slate-700 mb-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.selectionMode" /></legend>
              <div className="flex flex-wrap items-center gap-4">
                <label className="inline-flex items-center gap-2 text-sm"><input type="radio" name="aqi_selection_action" checked={selectionAction === 'primary'} onChange={() => setSelectionAction('primary')} /><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.setPrimary" /></label>
                <label className="inline-flex items-center gap-2 text-sm"><input type="radio" name="aqi_selection_action" checked={selectionAction === 'overlay'} onChange={() => setSelectionAction('overlay')} /><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.addOverlay" /></label>
              </div>
            </fieldset>
            {exceedsScaleLimit && <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.productWouldRequireFourthIncompatibleY" />{' '}{MAX_ANALYTICS_SCALE_GROUPS} {' '}<Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.readableScaleGroups" /></p>}
          </div>
          <div className="px-6 py-4">
            {aqiCatalogLoading && <div role="status" className="text-center text-blue-600 py-8"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.loadingAqiStandardsDevices" /></div>}
            {aqiCatalogError && !aqiCatalogLoading && <div className="text-center text-red-600 py-8"><p>{aqiCatalogError}</p>{onRetryAqiCatalog && <button type="button" className="btn mt-3" onClick={onRetryAqiCatalog}><Trans ns="analytics" i18nKey="dataStreamSelectionModal.actions.retryAqiCatalog" /></button>}</div>}
            {!aqiCatalogLoading && !aqiCatalogError && !selectedProduct && <p className="text-center text-slate-500 py-8"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.noAqiProducts" /></p>}
            {!aqiCatalogLoading && !aqiCatalogError && selectedProduct && matchingDevices.length === 0 && <div className="text-center text-slate-500 py-8"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.noAqiCapableDevicesMatchThese" /></div>}
            {!aqiCatalogLoading && !aqiCatalogError && selectedStandard && selectedProduct && matchingDevices.length > 0 && <div className="space-y-2">
              {matchingDevices.map((device) => {
                const candidate: AirQualityIndexSeriesSelection = {
                  kind: 'aqi',
                  device_id: device.device_id,
                  standard_code: selectedStandard.standard_code,
                  product_code: selectedProduct.product_code,
                };
                const duplicate = existingAqiSelections.some((series) => analyticsSeriesKey(series) === analyticsSeriesKey(candidate));
                const atSeriesLimit = currentSeriesCount >= MAX_ANALYTICS_SERIES;
                const disabled = duplicate || atSeriesLimit || exceedsScaleLimit || !onSelectAqi;
                return (
                  <button type="button" key={device.device_id} className="w-full text-left rounded-lg border border-slate-200 bg-slate-50/50 p-3 transition hover:border-blue-300 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-55" disabled={disabled || !rangeValid} onClick={() => {
                    onSelectAqi?.(candidate, { role: selectionAction });
                    onClose();
                  }}>
                    <span className="font-medium text-slate-800">{device.friendly_name || device.name}</span>
                    <span className="block text-sm text-slate-600 mt-1">{getAirQualityIndexProductLabel(selectedProduct.product_code)}</span>
                    <span className="block text-xs text-slate-500 mt-1">{device.network || i18n.t('analytics:analytics.states.unknownSourceLower')} {' '}<Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.device" />{' '}{device.device_id} · {device.timezone || i18n.t('analytics:analytics.states.timezoneUnavailable')}</span>
                    {duplicate && <span className="block text-xs text-orange-600 mt-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.alreadyChart" /></span>}
                    {!duplicate && atSeriesLimit && <span className="block text-xs text-orange-600 mt-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.sixSeriesMaximumReached" /></span>}
                  </button>
                );
              })}
            </div>}
          </div>
        </div>
        <div className="px-6 py-4 border-t border-slate-200 flex justify-end flex-shrink-0"><button type="button" className="px-4 py-2 rounded-md bg-slate-100 text-slate-700 hover:bg-slate-200 transition text-sm font-medium" onClick={onClose}><Trans ns="common" i18nKey="actions.cancel" /></button></div>
      </DataStreamDialog>
    );
  }

  return (
    <DataStreamDialog onClose={onClose}>
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
        <h2 className="text-xl font-semibold text-slate-800"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.headings.selectDataStream2" /></h2>
        <button
          type="button"
          className="text-slate-400 hover:text-slate-600 text-2xl leading-none"
          onClick={onClose}
          aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.closeModal2')}
        >
          ×
        </button>
      </div>

      <div className="data-stream-dialog-content">
        <div className="px-6 py-4 space-y-4 border-b border-slate-200">
          <DataTypeSelector value={selectedDataType} onChange={setSelectedDataType} />
          {parametersError && <div role="alert" className="text-sm text-red-700">
            <p><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.filtersUnavailable" /></p>
            <button type="button" className="btn mt-2" onClick={() => setFiltersRetry(value => value + 1)}><Trans ns="common" i18nKey="actions.retry" /></button>
          </div>}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.parameter" /></label>
              <select
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
                value={selectedParameter}
                onChange={(event) => setSelectedParameter(event.target.value)}
                disabled={parametersLoading}
                aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.selectParameter')}
              >
                {parametersLoading ? (
                  <option value=""><Trans ns="common" i18nKey="states.loading" /></option>
                ) : (
                  <>
                    <option value=""><Trans ns="analytics" i18nKey="dataStreamSelectionModal.options.selectParameter" /></option>
                    {parameters.map((parameter) => (
                      <option key={parameter.code} value={parameter.code}>
                        {getParameterDisplayName(parameter.code, parameter.display_name)}
                      </option>
                    ))}
                  </>
                )}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.nativeStreamResolution" /></label>
              <select
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
                value={selectedTimeResolution}
                onChange={(event) => setSelectedTimeResolution(event.target.value)}
                aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.filterSensorTimeResolution')}
              >
                <option value=""><Trans ns="analytics" i18nKey="dataStreamSelectionModal.options.allResolutions" /></option>
                {availableTimeResolutions.map((resolution) => (
                  <option key={resolution.code} value={resolution.code}>
                    {getAggregationDisplayLabel(resolution.code)}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.dataSource2" /></label>
              <select
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
                value={selectedDataSource}
                onChange={(event) => setSelectedDataSource(event.target.value)}
                aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.selectDataSource')}
              >
                <option value=""><Trans ns="analytics" i18nKey="dataStreamSelectionModal.options.allSources2" /></option>
                {dataSourceOptions.map((option) => (
                  <option key={option.filter_value} value={option.filter_value}>
                    {option.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <p className="sm:col-span-2 text-sm text-slate-600">{displayTimezone ? i18n.t('analytics:timezones.displayedIn', { timezone: displayTimezone }) : i18n.t('analytics:timezones.unavailable')}</p>
              {!isValidAnalyticsDateRange(startIso, endIso) && <p role="alert" className="sm:col-span-2 text-sm text-red-700">{i18n.t('analytics:analytics.messages.invalidDateRange')}</p>}
              <ZonedDateTimeInput label={i18n.t('analytics:dataStreamSelectionModal.accessibility.startDateTime')} iso={startIso} timezone={displayTimezone} onChange={onStartChange} onValidityChange={onStartValidityChange} />
              <ZonedDateTimeInput label={i18n.t('analytics:dataStreamSelectionModal.accessibility.endDateTime')} iso={endIso} timezone={displayTimezone} onChange={onEndChange} onValidityChange={onEndValidityChange} />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.searchDevicesSensors" /></label>
            <input
              type="text"
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
              placeholder={i18n.t('analytics:dataStreamSelectionModal.placeholders.searchDeviceNameSensorIdExternal')}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.searchDataStreams')}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.selectionMode" /></label>
            <div className="flex flex-wrap items-center gap-4">
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="selection_action"
                  checked={selectionAction === 'primary'}
                  onChange={() => setSelectionAction('primary')}
                />
                <Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.setPrimary2" /></label>
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="selection_action"
                  checked={selectionAction === 'overlay'}
                  onChange={() => setSelectionAction('overlay')}
                />
                <Trans ns="analytics" i18nKey="dataStreamSelectionModal.fields.addOverlay2" /></label>
            </div>
          </div>

          
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <p className="text-sm text-slate-600 flex-1"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.measurementDiscovery" /></p>
            <button
              type="button"
              className="btn self-end"
              onClick={fetchDataStreams}
              disabled={dataStreamsLoading || parametersLoading || parametersError || !rangeValid || !selectedParameter}
            >
              {dataStreamsLoading ? i18n.t('common:states.loading') : i18n.t(dataStreamsError ? 'common:actions.retry' : 'analytics:dataStreamSelectionModal.actions.loadSensors')}
            </button>
          </div>
        </div>

        <div className="px-6 py-4">
          {dataStreamsLoading && (
            <div role="status" className="text-center text-blue-600 py-8"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.loadingDataStreams" /></div>
          )}

          {dataStreamsError && !dataStreamsLoading && (
            <div role="alert" className="text-center text-red-600 py-8">{dataStreamsError}</div>
          )}

          
          {!dataStreamsLoading && !dataStreamsError && !hasLoadedSensors && (
            <div className="text-center text-slate-500 py-8">
              <svg className="w-12 h-12 mx-auto mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <p className="mb-2 font-medium"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.configureFiltersAboveThenClickLoad" /></p>
            </div>
          )}

          
          {!dataStreamsLoading && !dataStreamsError && hasLoadedSensors && filteredDataStreams.length === 0 && (
            <div className="text-center text-slate-500 py-8">
              <Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.noDataStreamsFoundMatchingFilters" /></div>
          )}

          {!dataStreamsLoading && !dataStreamsError && filteredDataStreams.length > 0 && (
            <div className="space-y-2">
              {filteredDataStreams.map((stream) => {
                const validAggregations = getValidAggregationsForStream(stream);
                const selectedAggregationCode = streamAggregationSelections[stream.sensor_id] || 
                                   stream.sensor_aggregation_period || 
                                   validAggregations[0]?.code || 
                                   'raw';
                const isDuplicate = isStreamAlreadySelected(stream, selectedAggregationCode);
                const candidateScaleGroup = analyticsScaleGroupKey({
                  kind: 'measurement',
                  normalized_unit: stream.unit || i18n.t('analytics:analytics.states.unknownUnit'),
                });
                const atSeriesLimit = currentSeriesCount >= MAX_ANALYTICS_SERIES;
                const exceedsScaleLimit = !existingScaleGroupKeys.includes(candidateScaleGroup)
                  && new Set(existingScaleGroupKeys).size >= MAX_ANALYTICS_SCALE_GROUPS;
                const selectionBlocked = isDuplicate || atSeriesLimit || exceedsScaleLimit;
                const selectedAggDisplay = validAggregations.find(a => a.code === selectedAggregationCode)?.display || selectedAggregationCode;
                
                
                const sourceName = stream.network || i18n.t('analytics:analytics.states.unknownSource');
                
                return (
                  <div
                    key={stream.sensor_id}
                    className={`w-full flex flex-wrap items-start gap-3 p-3 rounded-lg border transition ${
                      selectionBlocked
                        ? 'border-orange-300 bg-orange-50 cursor-not-allowed' 
                        : 'border-slate-200 bg-slate-50/50 hover:bg-blue-50 hover:border-blue-300 cursor-pointer'
                    }`}
                  >
                  <button
                    type="button"
                    className="flex flex-1 min-w-0 items-start gap-3 text-left rounded focus-visible:outline-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed"
                    onClick={() => handleSelectStream(stream)}
                    disabled={selectionBlocked || !rangeValid}
                    title={isDuplicate
                      ? i18n.t('analytics:dataStreamSelectionModal.actions.datastreamTimeResolutionAlreadyChartSelect')
                      : atSeriesLimit
                        ? i18n.t('analytics:dataStreamSelectionModal.actions.analyticsSupportsUpSixSeries')
                        : exceedsScaleLimit
                          ? i18n.t('analytics:dataStreamSelectionModal.actions.measurementUnitWouldRequireFourthIncompatible')
                      : i18n.t('analytics:dataStreamSelectionModal.tooltips.addAs', {
                          role: selectionAction === 'primary'
                            ? i18n.t('analytics:dataStreamSelectionModal.states.primary')
                            : i18n.t('analytics:dataStreamSelectionModal.states.overlay'),
                        })
                    }
                  >
                    
                      
                      <div
                        className="flex-shrink-0 w-3 h-3 rounded-full mt-1 ring-2 ring-white shadow-sm bg-slate-300"
                        title={i18n.t('analytics:dataStreamSelectionModal.tooltips.chartLineColorWillAssignedWhen')}
                        aria-hidden="true"
                      />
                      
                      <div className="flex-1 min-w-0">
                        
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-slate-800 truncate">
                            {stream.device_name || i18n.t('analytics:analytics.dynamic.sensor', { id: stream.sensor_id })}
                          </span>
                        </div>
                        
                        
                        <div className="flex items-center gap-2 flex-wrap mt-1 text-sm text-slate-600">
                          <span className="font-medium text-slate-700">
                            {getParameterDisplayName(stream.parameter, stream.parameter_name)}
                          </span>
                          <span className="text-slate-400">•</span>
                          <span>{stream.unit || '—'}</span>
                          <span className="text-slate-400">•</span>
                          <span className="text-slate-500">{selectedAggDisplay}</span>
                        </div>
                        
                        
                        <div className="flex items-center gap-2 flex-wrap mt-1 text-sm text-slate-500">
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-200 text-slate-600 text-xs">
                            {sourceName}
                          </span>
                          <span className="text-slate-400">
                            <Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.id" />{stream.external_sensor_id || stream.sensor_id}
                          </span>
                        </div>
                        
                        
                        {isDuplicate && (
                          <div className="mt-2 text-xs text-orange-600">
                            <Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.alreadyChartSelectDifferentTimeResolution" /></div>
                        )}
                        {!isDuplicate && atSeriesLimit && <div className="mt-2 text-xs text-orange-600"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.sixSeriesMaximumReached2" /></div>}
                        {!isDuplicate && !atSeriesLimit && exceedsScaleLimit && <div className="mt-2 text-xs text-orange-600"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.unitWouldRequireFourthIncompatibleY" /></div>}
                      </div>
                      
                      
                  </button>
                      <div className="w-full sm:w-auto sm:min-w-[160px] sm:ml-6">
                        <span className="mb-1 block text-xs font-medium text-slate-600"><Trans ns="analytics" i18nKey="dataStreamSelectionModal.text.plotTimeResolution" /></span>
                        <select
                          className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
                          value={selectedAggregationCode}
                          onChange={(event) => {
                            event.stopPropagation();
                            setStreamAggregationSelections(previousSelections => ({
                              ...previousSelections,
                              [stream.sensor_id]: event.target.value
                            }));
                          }}
                          onClick={(event) => event.stopPropagation()}
                          aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.selectAggregationDatastream')}
                        >
                          {validAggregations.map((aggregationOption) => (
                            <option key={aggregationOption.code} value={aggregationOption.code}>
                              {aggregationOption.display}
                            </option>
                          ))}
                        </select>
                      </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

      </div>
      <div className="px-6 py-4 border-t border-slate-200 flex justify-end">
        <button
          type="button"
          className="px-4 py-2 rounded-md bg-slate-100 text-slate-700 hover:bg-slate-200 transition text-sm font-medium"
          onClick={onClose}
        >
          <Trans ns="common" i18nKey="actions.cancel" /></button>
      </div>
    </DataStreamDialog>
  );
}
