import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SensorChart, { type MeasurementHistoryResponse } from '../SensorChart';
import type { AirQualityIndexAnalyticsSeries, AirQualityIndexStandardMetadata } from '../airQualityIndex';
import i18n from '../i18n';

const captured = vi.hoisted(() => ({ props: null as null | { data: { datasets: any[] }; options: any } }));

vi.mock('react-chartjs-2', () => ({
  Line: (props: { data: { datasets: any[] }; options: any }) => {
    captured.props = props;
    return <div data-testid="chart-canvas" />;
  },
}));

const measurement: MeasurementHistoryResponse = {
  sensor_id: 10, parameter: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³', device_name: 'Measurement Station',
  device_timezone: 'UTC', external_sensor_id: 'S-10', external_api: { name: 'OpenAQ' },
  _displayAggregate: '1h', _seriesKey: 'measurement|10|pm25|1h',
  data: [{ timestamp: '2026-08-01T01:00:00Z', value: 12.5, is_valid: true }],
};

const standards: AirQualityIndexStandardMetadata[] = [{
  standard_code: 'eea_european', display_name: 'European Air Quality Index', methodology_version: '2024', result_kind: 'categorical',
  averaging_minutes: 60, required_averaging_period: '1h', supported_parameter_codes: ['pm25'], normalized_unit: 'µg/m³',
  categories: [{ code: 'good', label: 'Good', internal_severity_rank: 1, color: '#50f0e6' }, { code: 'poor', label: 'Poor', internal_severity_rank: 4, color: '#ff5050' }],
  default_product_code: 'eea_european.overall.hourly', is_default: false, products: [],
}];

function point(overrides: Record<string, unknown> = {}) {
  return {
    observed_at: '2026-08-01T01:00:00Z', interval_started_at: '2026-08-01T00:00:00Z', interval_ended_at: '2026-08-01T01:00:00Z',
    represented_local_date: null, numeric_value: 74, category_code: 'moderate', category_label: 'Moderate', normalized_concentration: 22.1234,
    preprocessed_concentration: 22.1,
    normalized_unit: 'µg/m³', calculation_status: 'calculated' as const, eligibility_status: 'eligible' as const, coverage_status: 'complete' as const,
    exclusion_reason: null, selected_calculation_code: 'pm_nowcast', selected_aggregation_period: '12h_nowcast', dominant_pollutants: ['pm25'],
    available_pollutants: ['pm25'], missing_pollutants: [], ineligible_pollutants: [], ...overrides,
  };
}

const aqiSeries: AirQualityIndexAnalyticsSeries[] = [{
  standard_code: 'us_epa', standard_display_name: 'U.S. EPA AQI', methodology_version: '2024', product_code: 'us_epa.pm25.nowcast',
  product_display_name: 'PM2.5 NowCast AQI', parameter_code: 'pm25', calculation_code: 'pm_nowcast', aggregation_period: '12h_nowcast',
  result_kind: 'numeric', result_scope: 'pollutant', history_interval: 'utc_hour', device_id: 1, device_name: 'U.S. Station',
  device_friendly_name: null, device_timezone: 'UTC', source_name: 'OpenAQ', points: [point()],
}, {
  standard_code: 'eea_european', standard_display_name: 'European Air Quality Index', methodology_version: '2024',
  product_code: 'eea_european.overall.hourly', product_display_name: 'Overall hourly European AQI', parameter_code: null,
  calculation_code: 'worst_available_category', aggregation_period: '1h', result_kind: 'categorical', result_scope: 'overall',
  history_interval: 'utc_hour', device_id: 2, device_name: 'European Station', device_friendly_name: null, device_timezone: 'UTC',
  source_name: 'OpenAQ', points: [point({ numeric_value: null, category_code: 'poor', category_label: 'Poor', coverage_status: 'partial' })],
}];

describe('SensorChart mixed semantic adapters', () => {
  it('reveals isolated native observations independently in multiple datasets without changing gap rules', () => {
    const sparse = { ...measurement, _displayAggregate: '2m', data: [0, 60, 120].map(minutes => ({
      timestamp: new Date(Date.UTC(2026, 7, 1, 0, minutes)).toISOString(), value: 12, is_valid: true,
    })) };
    render(<SensorChart data={sparse} overlays={[{ ...sparse, sensor_id: 11, unit: '°C' }]} />);
    for (const dataset of captured.props!.data.datasets) {
      expect(dataset.pointRadius).toEqual([2.5, 2.5, 2.5]);
      expect(dataset.spanGaps).toBe(180_000);
      expect(dataset.pointHoverRadius).toBe(5);
      expect(dataset.segment.borderColor({ p0DataIndex: 0, p1DataIndex: 1 })).toBe('transparent');
    }
  });
  it('preserves unknown-cadence inference and ignores nonfinite measurement values', () => {
    render(<SensorChart data={{ ...measurement, _displayAggregate: 'unknown', data: [
      { timestamp: '2026-08-01T01:00:00Z', value: 12, is_valid: true },
      { timestamp: '2026-08-01T01:30:00Z', value: NaN, is_valid: true },
      { timestamp: '2026-08-01T02:00:00Z', value: 13, is_valid: true },
      { timestamp: '2026-08-01T03:00:00Z', value: 14, is_valid: true },
    ] }} />);
    const dataset = captured.props!.data.datasets[0];
    expect(dataset.data).toHaveLength(3);
    expect(dataset.spanGaps).toBe(5_400_000);
    expect(dataset.pointRadius).toEqual([0, 0, 0]);
  });
  it('bounds ordinary sparse markers without changing the 300-per-status QC bounds', () => {
    const flagged = { check_code: 'max_value', evaluation_status: 'failed' as const, passed: false,
      failure_action: 'flag_for_review' as const, reason_code: null };
    render(<SensorChart invalidMeasurementsIncluded data={{ ...measurement, _displayAggregate: '2m',
      data: Array.from({ length: 3000 }, (_, index) => ({
        timestamp: new Date(Date.UTC(2026, 0, 1, index)).toISOString(), value: index,
        is_valid: index % 3 !== 2, ...(index % 3 === 1 ? { qc_results: [flagged] } : {}),
      })) }} />);
    const dataset = captured.props!.data.datasets[0];
    expect(dataset.data).toHaveLength(3000);
    expect(dataset.pointRadius.filter((r: number) => r === 2.5)).toHaveLength(300);
    expect(dataset.pointRadius.filter((r: number) => r === 4)).toHaveLength(600);
  });
  it('coordinates invalid visibility, shapes, tooltip, and breaks around hidden invalid observations', () => {
    const flagged = { check_code: 'max_value', evaluation_status: 'failed' as const, passed: false, failure_action: 'flag_for_review' as const, reason_code: null };
    const data = { ...measurement, data: [
      { timestamp: '2026-08-01T01:00:00Z', value: 12, is_valid: true },
      { timestamp: '2026-08-01T02:00:00Z', value: 38, is_valid: true, qc_results: [flagged] },
      { timestamp: '2026-08-01T03:00:00Z', value: 80, is_valid: false, qc_results: [{ ...flagged, failure_action: 'mark_invalid' as const }] },
      { timestamp: '2026-08-01T04:00:00Z', value: 14, is_valid: true },
    ] };
    const { rerender } = render(<SensorChart data={data} invalidMeasurementsIncluded={false} />);
    expect(screen.queryByRole('checkbox', { name: 'Show invalid points' })).not.toBeInTheDocument();
    rerender(<SensorChart data={data} invalidMeasurementsIncluded />);
    const dataset = captured.props!.data.datasets[0];
    expect(dataset.pointStyle).toEqual(['circle', 'triangle', 'crossRot', 'circle']);
    expect(dataset.pointRadius).toEqual([0, 4, 4, 2.5]);
    expect(captured.props!.options.plugins.tooltip.callbacks.afterLabel({ dataset, raw: dataset.data[1] })).toEqual(['Flagged for review · Valid', 'Maximum plausible value']);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Show invalid points' }));
    const hidden = captured.props!.data.datasets[0];
    expect(hidden.data[2].y).toBeNull();
    expect(hidden.segment.borderColor({ p0DataIndex: 1, p1DataIndex: 3 })).toBe('transparent');
    expect(hidden.spanGaps).toBe(5400000);
  });
  it('bounds dense exceptional markers without dropping observations', () => {
    render(<SensorChart data={{ ...measurement, data: Array.from({ length: 3000 }, (_, index) => ({
      timestamp: new Date(Date.UTC(2026, 0, 1, 0, index * 2)).toISOString(), value: index, is_valid: false,
    })) }} invalidMeasurementsIncluded />);
    const dataset = captured.props!.data.datasets[0];
    expect(dataset.data).toHaveLength(3000);
    expect(dataset.pointRadius.filter((radius: number) => radius > 0)).toHaveLength(300);
    expect(screen.getByText(/Some QC markers overlap/)).toBeVisible();
  });
  it('uses numeric timestamps with parsing disabled so automatic bounds include historical observations', () => {
    render(<SensorChart data={{ ...measurement, data: [
      { timestamp: '2026-08-01T01:00:00Z', value: 12.5, is_valid: true },
      { timestamp: '2026-08-01T02:00:00Z', value: 13.5, is_valid: true },
    ] }} />);
    expect(captured.props!.options.parsing).toBeUndefined();
    const dataset = captured.props!.data.datasets[0];
    expect(dataset.parsing).toBe(false);
    expect(dataset.data.every((point: { x: number }) => Number.isFinite(point.x))).toBe(true);
  });
  it('keeps dense, coincident series to one compact tooltip with automatic edge alignment', () => {
    render(<SensorChart aqiSeries={aqiSeries} aqiStandards={standards} />);
    const tooltip = captured.props!.options.plugins.tooltip;
    expect(tooltip.xAlign).toBeUndefined();
    expect(tooltip.filter({}, 0)).toBe(true);
    expect(tooltip.filter({}, 1)).toBe(false);
    const dataset = captured.props!.data.datasets[0];
    const details = tooltip.callbacks.afterLabel({ dataset, raw: dataset.data[0] });
    expect(details).toHaveLength(3);
    expect(details.join(' ')).toContain('Coverage');
    expect(details.join(' ')).not.toContain('Interval');
  });
  it.each(['en', 'es'])('fully interpolates AQI legend labels in %s', async (language) => {
    await i18n.changeLanguage(language);
    try {
      render(<SensorChart sensorId={10} parameter="pm25" unit="µg/m³" data={measurement} overlays={[]} aqiSeries={aqiSeries} aqiStandards={standards} />);
      const labels = captured.props!.data.datasets.map((dataset) => dataset.label);
      expect(labels.join(' ')).toContain('NowCast');
      expect(labels.join(' ')).not.toMatch(/\{\{|philippines_denr|Aggregation 12h_nowcast/);
    } finally {
      await i18n.changeLanguage('en');
    }
  });
  it('breaks measurement lines when a gap exceeds the expected interval', () => {
    render(<SensorChart data={{ ...measurement, data: [
      { timestamp: '2026-08-01T01:00:00Z', value: 10, is_valid: true },
      { timestamp: '2026-08-01T03:00:00Z', value: 12, is_valid: true },
      { timestamp: '2026-08-01T04:00:00Z', value: 13, is_valid: true },
    ] }} />);
    expect(captured.props?.data.datasets[0].spanGaps).toBe(5_400_000);
    const segment = captured.props!.data.datasets[0].segment;
    expect(segment.borderColor({ p0DataIndex: 0, p1DataIndex: 1 })).toBe('transparent');
    expect(segment.borderColor({ p0DataIndex: 1, p1DataIndex: 2 })).toBeUndefined();
  });

  it('identifies same-site, same-parameter streams by their external stream IDs', () => {
    const secondStream: MeasurementHistoryResponse = {
      ...measurement,
      sensor_id: 11,
      external_sensor_id: 'S-11',
      _seriesKey: 'measurement|11|pm25|1h',
    };
    render(<SensorChart sensorId={10} parameter="pm25" unit="µg/m³" data={measurement} overlays={[secondStream]}
      aqiSeries={[]} aqiStandards={standards}
      orderedSeriesKeys={['measurement|10|pm25|1h', 'measurement|11|pm25|1h']} />);
    expect(captured.props?.data.datasets.map((dataset) => dataset.label)).toEqual([
      expect.stringContaining('Stream S-10'),
      expect.stringContaining('Stream S-11'),
    ]);
  });

  it('keeps measurement tooltip compact rather than repeating table interval details', () => {
    const intervalMeasurement: MeasurementHistoryResponse = {
      ...measurement,
      measurement_timestamp_semantics: 'interval_end',
      data: [{
        ...measurement.data[0],
        interval_started_at: '2026-08-01T00:00:00Z',
        interval_ended_at: '2026-08-01T01:00:00Z',
      }],
    };
    render(<SensorChart sensorId={10} parameter="pm25" unit="µg/m³" data={intervalMeasurement} overlays={[]}
      aqiSeries={[]} aqiStandards={standards} timezoneMode="utc" />);
    const dataset = captured.props?.data.datasets[0];
    const details = captured.props?.options.plugins.tooltip.callbacks.afterLabel({ dataset, raw: dataset.data[0] });
    expect(details).toEqual([]);
    expect(captured.props?.options.plugins.tooltip.callbacks.label({ dataset, raw: dataset.data[0] }).join(' ')).toContain('PM2.5');
  });

  it('uses one physical-unit axis for native, hourly, and daily resolutions', () => {
    const native = { ...measurement, _displayAggregate: '2m', _seriesKey: 'measurement|10|pm25|2m' };
    const daily = { ...measurement, _displayAggregate: '24h', _seriesKey: 'measurement|10|pm25|24h' };
    render(<SensorChart sensorId={10} parameter="pm25" unit="µg/m³" data={native} overlays={[measurement, daily]}
      aqiSeries={[]} aqiStandards={standards}
      orderedSeriesKeys={['measurement|10|pm25|2m', 'measurement|10|pm25|1h', 'measurement|10|pm25|24h']} />);
    expect(captured.props?.data.datasets.map((dataset) => dataset.yAxisID)).toEqual([
      'measurementScale1', 'measurementScale1', 'measurementScale1',
    ]);
  });

  it('uses native timestamps and three explicit compatible axes without converting European categories to numeric AQI', () => {
    render(<SensorChart sensorId={10} parameter="pm25" unit="µg/m³" data={measurement} overlays={[]} aqiSeries={aqiSeries}
      aqiStandards={standards} orderedSeriesKeys={['measurement|10|pm25|1h', 'aqi|us_epa|us_epa.pm25.nowcast|1', 'aqi|eea_european|eea_european.overall.hourly|2']}
      timezoneMode="utc" />);
    expect(screen.getByTestId('chart-canvas')).toBeInTheDocument();
    expect(captured.props?.data.datasets.map((dataset) => dataset.yAxisID)).toEqual([
      'measurementScale1', 'numericAqi', 'categorical_eea_european',
    ]);
    expect(captured.props?.options.scales.numericAqi.title.text).toBe('U.S. EPA AQI');
    expect(captured.props?.options.scales.categorical_eea_european.ticks.callback(4)).toBe('Poor');
    expect(new Date(captured.props?.data.datasets[0].data[0].x).toISOString()).toBe('2026-08-01T01:00:00.000Z');
    const categoryDataset = captured.props?.data.datasets[2];
    expect(categoryDataset.stepped).toBe(true);
    expect(categoryDataset.data[0].aqiPoint.numeric_value).toBeNull();
    expect(captured.props?.options.plugins.tooltip.callbacks.label({ dataset: categoryDataset, raw: categoryDataset.data[0] })).toContain('Poor');
    expect(captured.props?.options.plugins.tooltip.callbacks.label({ dataset: categoryDataset, raw: categoryDataset.data[0] })).not.toContain('AQI 4');
    expect(captured.props?.options.plugins.tooltip.callbacks.afterLabel({ dataset: categoryDataset, raw: categoryDataset.data[0] }))
      .toContain('Processed concentration: 22.1 µg/m³');
  });

  it.each(['utc', 'stream', 'local'] as const)('preserves completed-day AQI boundaries and represented dates in %s mode', (timezoneMode) => {
    const completedDaySeries: AirQualityIndexAnalyticsSeries = {
      ...aqiSeries[0], product_code: 'us_epa.pm25.completed_day', product_display_name: 'PM2.5 Completed-Day AQI',
      aggregation_period: 'device_local_day', history_interval: 'represented_device_local_date',
      points: [point({
        observed_at: '2026-08-02T07:00:00Z', interval_started_at: '2026-08-01T07:00:00Z',
        interval_ended_at: '2026-08-02T07:00:00Z', represented_local_date: '2026-08-01', numeric_value: 81,
      })],
    };
    render(<SensorChart sensorId={10} parameter="pm25" unit="µg/m³" data={measurement} overlays={[]}
      aqiSeries={[aqiSeries[0], completedDaySeries]} aqiStandards={standards} timezoneMode={timezoneMode} streamTimezone="America/New_York"
      orderedSeriesKeys={['measurement|10|pm25|1h', 'aqi|us_epa|us_epa.pm25.nowcast|1', 'aqi|us_epa|us_epa.pm25.completed_day|1']} />);
    const dailyDataset = captured.props?.data.datasets[2];
    expect(dailyDataset.yAxisID).toBe('numericAqi');
    expect(dailyDataset.label).toContain('Daily');
    expect(new Date(dailyDataset.data[0].x).toISOString()).toBe('2026-08-02T07:00:00.000Z');
    expect(captured.props?.options.plugins.tooltip.callbacks.title([{ raw: dailyDataset.data[0] }])).toBe('Represented local date: 2026-08-01');
  });

  it('uses the selected numeric standard metadata for the AQI axis title', () => {
    const philippineStandard: AirQualityIndexStandardMetadata = {
      standard_code: 'philippines_denr',
      display_name: 'Philippines Air Quality Index',
      methodology_version: 'denr_emb_aqi_2021',
      result_kind: 'numeric',
      averaging_minutes: null,
      required_averaging_period: null,
      supported_parameter_codes: ['pm25'],
      normalized_unit: 'AQI',
      categories: [],
      default_product_code: 'philippines_denr.pm25.completed_day',
      is_default: false,
      products: [],
    };
    const philippineSeries: AirQualityIndexAnalyticsSeries = {
      ...aqiSeries[0],
      standard_code: 'philippines_denr',
      standard_display_name: 'Philippines Air Quality Index',
      methodology_version: 'denr_emb_aqi_2021',
      product_code: 'philippines_denr.pm25.completed_day',
      product_display_name: 'Philippines PM2.5 Completed-Day AQI',
      aggregation_period: '24h',
      history_interval: 'represented_device_local_date',
    };
    render(
      <SensorChart
        aqiSeries={[philippineSeries]}
        aqiStandards={[philippineStandard]}
        orderedSeriesKeys={[
          'aqi|philippines_denr|philippines_denr.pm25.completed_day|1',
        ]}
      />,
    );
    expect(captured.props?.options.scales.numericAqi.title.text).toBe(
      'Philippines Air Quality Index',
    );
  });
});


it.each([
  ['utc', 'UTC', '01:00', '01:00:00 AM UTC'],
  ['stream', 'America/New_York', '21:00', '09:00:00 PM EDT'],
] as const)('uses %s clock times for ticks and tooltip titles', (mode, timezone, tick, title) => {
  render(<SensorChart data={measurement} timezoneMode={mode} streamTimezone={timezone} />);
  const instant = Date.parse('2026-08-01T01:00:00Z');
  expect(captured.props!.options.scales.x.ticks.callback(instant)).toContain(tick);
  expect(captured.props!.options.plugins.tooltip.callbacks.title([
    { raw: captured.props!.data.datasets[0].data[0], parsed: { x: instant } },
  ])).toContain(title);
});


describe('measurement tooltip precision without chart data changes', () => {
  it.each([
    ['pm25', '1m', 'µg/m³', 17.1, 1, '17.1'],
    ['pm25', '1h', 'µg/m³', 17, 1, '17.0'],
    ['pm25', '24h', 'µg/m³', 17, 1, '17.0'],
    ['pm25', 'rolling_24h', 'µg/m³', 17.141666666666666, null, '17.1416666667'],
    ['o3', '1h', 'ppm', 0.005, 3, '0.005'],
    ['no2', '1h', 'ppm', 1, 1, '1.0'],
    ['so2', '1h', 'ppm', 2, 1, '2.0'],
    ['co', '1h', 'ppm', 3, 1, '3.0'],
    ['no', '1h', 'ppb', 4, 1, '4.0'],
    ['nox', '1m', 'ppm', 0.0049, null, '0.0049'],
    ['pm10', '1h', 'µg/m³', 17, 0, '17'],
    ['tvoc', '1m', 'ppb', 0.0049, null, '0.0049'],
    ['tvoc_index', '1m', 'index', 12.3456, null, '12.3456'],
    ['nox_index', '1m', 'index', 99.995, null, '99.995'],
    ['pressure', '1m', 'hPa', 1013.251, null, '1013.251'],
    ['temperature', '1m', '°C', -0.0049, null, '-0.0049'],
  ])('%s %s %s', (parameter, aggregation, unit, value, precision, expected) => {
    const input = { ...measurement, parameter, unit, _displayAggregate: aggregation,
      display_precision: precision, data: [{ ...measurement.data[0], value }] };
    render(<SensorChart data={input} />);
    const dataset = captured.props!.data.datasets[0];
    const tooltip = captured.props!.options.plugins.tooltip.callbacks.label({ dataset, raw: dataset.data[0] }).join(' ');
    expect(tooltip).toContain(`${expected} ${unit}`);
    expect(dataset.data[0].y).toBe(value);
    expect(input.data[0].value).toBe(value);
    expect(captured.props!.options.scales.measurementScale1.ticks.callback).toBeUndefined();
  });
});
