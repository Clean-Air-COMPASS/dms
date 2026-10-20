import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchJson } from '../api';
import {
  buildAirQualityIndexAnalyticsPath,
  buildAirQualityIndexHistoryPath,
  buildLatestAirQualityIndexPath,
  buildUsEpaCompletedDayHistoryPath,
  findAirQualityIndexStandard,
  getAirQualityIndexHistory,
  getLatestAirQualityIndex,
  getUsEpaCompletedDayHistory,
  listAirQualityIndexStandards,
} from '../airQualityIndex';
import {
  EUROPEAN_AQI_UNAVAILABLE_COLOR,
  getAirQualityIndexAuditFlagLabel,
  getAirQualityIndexCoverageStatusLabel,
  getAirQualityIndexTimeResolutionLabel,
  getAirQualityIndexProductLabel,
  getEuropeanAqiCategoryColor,
  getEuropeanAqiMarkerPresentation,
  getExclusionReasonLabel,
  getPollutantDisplayLabel,
} from '../airQualityIndexPresentation';
import i18n from '../i18n';

vi.mock('../api', () => ({ fetchJson: vi.fn() }));

const mockedFetchJson = vi.mocked(fetchJson);
const categories = [
  { code: 'good', label: 'Good', internal_severity_rank: 1, color: '#50F0E6' },
  { code: 'poor', label: 'Poor', internal_severity_rank: 4, color: '#FF5050' },
];
const product = {
  product_code: 'eea_european.overall.hourly', display_name: 'Overall hourly European AQI',
  parameter_code: null, calculation_code: 'worst_available_category', aggregation_period: '1h',
  aggregation_display_name: '1-hour average', result_scope: 'overall' as const,
  is_parameter_default: false, availability_status: 'available', availability_reason: null,
};
const standard = {
  standard_code: 'eea_european', display_name: 'European Air Quality Index',
  methodology_version: 'eea_2024_bands', result_kind: 'categorical' as const,
  averaging_minutes: 60, required_averaging_period: '1h', supported_parameter_codes: ['pm25'],
  normalized_unit: 'µg/m³', categories, products: [product],
  default_product_code: product.product_code, is_default: false,
};

describe('European Air Quality Index client', () => {
  beforeEach(() => mockedFetchJson.mockReset());

  it('forwards map and source filters using the Phase 2 field names', async () => {
    mockedFetchJson.mockResolvedValue({ results: [] });

    await getLatestAirQualityIndex({
      standard_code: 'eea_european',
      product_code: 'eea_european.overall.hourly',
      bbox: '-5,40,10,55',
      external_api_name: 'OpenAQ',
      device_id: 42,
      until: '2026-07-14T10:00:00Z',
      limit: 500,
    });

    expect(mockedFetchJson).toHaveBeenCalledWith(
      '/air-quality-index/eea_european/latest?product_code=eea_european.overall.hourly&bbox=-5%2C40%2C10%2C55&external_api_name=OpenAQ&device_id=42&until=2026-07-14T10%3A00%3A00Z&limit=500',
      { skipCache: true },
    );
  });

  it('loads standards without the shared GET cache and finds a standard by canonical code', async () => {
    const standards = [{ standard_code: 'eea_european' }];
    mockedFetchJson.mockResolvedValue(standards);
    const loadedStandards = await listAirQualityIndexStandards();
    expect(mockedFetchJson).toHaveBeenCalledWith('/air-quality-index/standards', { skipCache: true });
    expect(findAirQualityIndexStandard(loadedStandards as never, 'EEA_EUROPEAN')).toBe(standards[0]);
  });

  it('omits absent optional filters', () => {
    expect(buildLatestAirQualityIndexPath({ standard_code: 'eea_european' }))
      .toBe('/air-quality-index/eea_european/latest');
  });

  it('builds an exact completed-day device history request in summary mode', async () => {
    mockedFetchJson.mockResolvedValue({ detail: 'summary', device_series: [] });
    const controller = new AbortController();
    const query = {
      product_code: 'us_epa.pm10.completed_day',
      start_local_date: '2026-07-01',
      end_local_date: '2026-07-30',
      device_id: 42,
      external_api_name: 'openaq',
    };

    expect(buildUsEpaCompletedDayHistoryPath(query)).toBe(
      '/air-quality-index/us_epa/history?product_code=us_epa.pm10.completed_day&start_local_date=2026-07-01&end_local_date=2026-07-30&device_id=42&external_api_name=openaq&detail=summary',
    );
    await getUsEpaCompletedDayHistory(query, controller.signal);
    expect(mockedFetchJson).toHaveBeenCalledWith(
      expect.stringContaining('detail=summary'),
      { skipCache: true, signal: controller.signal },
    );
    expect(mockedFetchJson.mock.calls[0][0]).not.toContain('detail=full');
    expect(mockedFetchJson.mock.calls[0][0]).not.toContain('bbox=');
  });

  it('omits an absent source from completed-day history requests', () => {
    const path = buildUsEpaCompletedDayHistoryPath({
      product_code: 'us_epa.pm25.completed_day',
      start_local_date: '2026-07-30',
      end_local_date: '2026-07-30',
      device_id: 8,
    });
    expect(path).not.toContain('external_api_name');
    expect(path).toContain('detail=summary');
  });

  it('builds one bounded current-condition history request for the selected product', async () => {
    mockedFetchJson.mockResolvedValue({ results: [] });
    const controller = new AbortController();
    const query = {
      standard_code: 'us_epa',
      product_code: 'us_epa.no2.latest',
      start: '2026-07-13T11:00:00.000Z',
      end: '2026-07-14T11:00:00.000Z',
      device_id: 42,
      external_api_name: 'openaq',
    };
    expect(buildAirQualityIndexHistoryPath(query)).toBe(
      '/air-quality-index/us_epa/current-history?start=2026-07-13T11%3A00%3A00.000Z&end=2026-07-14T11%3A00%3A00.000Z&product_code=us_epa.no2.latest&device_id=42&external_api_name=openaq&limit=1000',
    );
    await getAirQualityIndexHistory(query, controller.signal);
    expect(mockedFetchJson).toHaveBeenCalledWith(
      buildAirQualityIndexHistoryPath(query),
      { skipCache: true, signal: controller.signal },
    );
  });

  it('preserves AQI product context in the Full Analytics action', () => {
    expect(buildAirQualityIndexAnalyticsPath({
      standard_code: 'us_epa',
      product_code: 'us_epa.pm25.completed_day',
      device_id: 42,
      parameter_code: 'pm25',
      sensor_id: 7,
      external_api_name: 'OpenAQ',
      completed_day: true,
    })).toBe(
      '/analytics?series=aqi%7Cus_epa%7Cus_epa.pm25.completed_day%7C42&source=OpenAQ&recency=7d&timezone=utc',
    );
  });
});

describe('European Air Quality Index presentation', () => {
  it.each(['en', 'es'])('labels NowCast and every Philippine product in %s', async (language) => {
    await i18n.changeLanguage(language);
    try {
      expect(getAirQualityIndexTimeResolutionLabel({ product_code: 'us_epa.pm25.nowcast', aggregation_period: '12h_nowcast' }))
        .toBe(language === 'en' ? '12-hour NowCast' : 'NowCast de 12 horas');
      for (const suffix of ['pm25.completed_day', 'pm10.completed_day', 'so2.completed_day', 'o3.latest', 'co.latest', 'no2.latest']) {
        const label = getAirQualityIndexProductLabel(`philippines_denr.${suffix}`);
        expect(label).toContain('DENR');
        expect(label).not.toMatch(/philippines_denr|\{\{/);
      }
      expect(getAirQualityIndexTimeResolutionLabel({ product_code: 'philippines_denr.so2.completed_day', aggregation_period: '24h' }))
        .toBe(language === 'en' ? 'Completed local day' : 'Día local completo');
      expect(getAirQualityIndexTimeResolutionLabel({ product_code: 'philippines_denr.o3.latest', aggregation_period: 'latest_completed_window' }))
        .not.toMatch(/latest_completed_window|Aggregation|Agregación/);
    } finally {
      await i18n.changeLanguage('en');
    }
  });
  it('localizes stable product aggregation codes instead of backend display prose', async () => {
    await i18n.changeLanguage('es');
    try {
      expect(getAirQualityIndexTimeResolutionLabel(product)).toBe('Promedio de 1 hora');
      expect(getAirQualityIndexTimeResolutionLabel({
        ...product,
        product_code: 'philippines_denr.pm25.completed_day',
        aggregation_period: 'completed_local_day',
        aggregation_display_name: 'Completed Day',
      })).toBe('Día local completo');
    } finally {
      await i18n.changeLanguage('en');
    }
  });

  it('uses backend-provided category colors and the neutral no-data color', () => {
    expect(getEuropeanAqiCategoryColor('good', categories)).toBe('#50F0E6');
    expect(getEuropeanAqiCategoryColor('poor', categories)).toBe('#FF5050');
    expect(getEuropeanAqiCategoryColor(null, categories)).toBe(EUROPEAN_AQI_UNAVAILABLE_COLOR);
    expect(getEuropeanAqiCategoryColor('unknown', categories)).toBe(EUROPEAN_AQI_UNAVAILABLE_COLOR);
  });

  it('presents partial eligible results without using numeric_value', () => {
    const presentation = getEuropeanAqiMarkerPresentation({
      device_id: 7,
      device_name: 'Central Station',
      device_friendly_name: null,
      eligibility_status: 'eligible',
      category_code: 'poor',
      category_label: 'Poor',
      numeric_value: null,
      coverage: { coverage_status: 'partial' },
      pollutant_results: [],
      exclusion_reasons: [],
    } as never, standard, product);
    expect(presentation.markerText).toBe('Poor · Partial');
    expect(presentation.accessibleLabel).toContain('partial pollutant coverage');
    expect(presentation.markerText).not.toContain('AQI');
  });

  it('uses a neutral unavailable presentation and readable centralized labels', () => {
    const presentation = getEuropeanAqiMarkerPresentation({
      device_id: 8,
      device_name: 'Unavailable Station',
      eligibility_status: 'ineligible',
      category_code: null,
      category_label: null,
      coverage: { coverage_status: 'none' },
      pollutant_results: [],
      exclusion_reasons: ['no_eligible_pollutants'],
    } as never, standard, product);
    expect(presentation.categoryLabel).toBe('Unavailable');
    expect(presentation.color).toBe(EUROPEAN_AQI_UNAVAILABLE_COLOR);
    expect(getPollutantDisplayLabel('pm25')).toBe('PM2.5');
    expect(getExclusionReasonLabel('unsupported_unit')).toBe('Unsupported unit');
    expect(getExclusionReasonLabel('unexpected_internal_reason')).toBe('Unavailable');
    expect(getExclusionReasonLabel('completed_day_methodology_not_implemented'))
      .toBe('This completed-day method is not implemented');
    expect(getAirQualityIndexAuditFlagLabel('invalid_observations_rejected'))
      .toBe('Invalid observations were excluded from the completed-day result.');
    expect(getAirQualityIndexAuditFlagLabel('unknown_audit_flag'))
      .toBe('An additional data-quality note is available.');
    expect(getAirQualityIndexCoverageStatusLabel('partial')).toBe('Partial');
    expect(getAirQualityIndexCoverageStatusLabel('unknown')).toBe('Not available');
  });
});


it('requests every latest Map result without a recency or viewport bound', () => {
  const path = buildLatestAirQualityIndexPath({ standard_code: 'us_epa', product_code: 'us_epa.pm25.nowcast', all_results: true });
  expect(path).toBe('/air-quality-index/us_epa/latest?product_code=us_epa.pm25.nowcast&all_results=true');
});
