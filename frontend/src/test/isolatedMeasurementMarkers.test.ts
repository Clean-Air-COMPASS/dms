import { describe, expect, it } from 'vitest';
import { isolatedMeasurementMarkerIndices } from '../isolatedMeasurementMarkers';

function points(minutes: number[]) {
  return minutes.map(x => ({ x: x * 60_000, y: 12 as number | null,
    measurementPoint: { timestamp: new Date(x * 60_000).toISOString(), value: 12, is_valid: true } }));
}

describe('ordinary observations without visible adjacent segments', () => {
  it.each([
    [[], []], [[0], [0]], [[0, 2], []], [[0, 60], [0, 1]],
    [[0, 2, 4], []], [[0, 60, 120], [0, 1, 2]],
    [[0, 2, 4, 60, 62, 120], [5]], [[0, 3, 6], []],
  ])('selects isolated indices for minute offsets %j', (minutes, expected) => {
    const data = points(minutes);
    expect([...isolatedMeasurementMarkerIndices(data, ({ p0DataIndex, p1DataIndex }) =>
      data[p1DataIndex].x - data[p0DataIndex].x > 180_000)]).toEqual(expected);
  });

  it('respects excluded segments even when observations have nearby timestamps', () => {
    const data = points([0, 2, 4, 6, 8]);
    data[1].measurementPoint.is_valid = false;
    data[1].y = null;
    data[3].measurementPoint.is_valid = false;
    const excluded = ({ p0DataIndex, p1DataIndex }: { p0DataIndex: number; p1DataIndex: number }) =>
      data.slice(p0DataIndex, p1DataIndex + 1).some(p => !p.measurementPoint.is_valid);
    expect([...isolatedMeasurementMarkerIndices(data, excluded)]).toEqual([0, 2, 4]);
  });

  it('does not add ordinary markers to flagged or invalid observations', () => {
    const data = points([0, 60, 120]).map(p => ({ ...p, measurementPoint: { ...p.measurementPoint,
      qc_results: [{ check_code: 'max_value', evaluation_status: 'failed' as const, passed: false,
        failure_action: 'flag_for_review' as const, reason_code: null }] } }));
    data[1].measurementPoint.is_valid = false;
    expect([...isolatedMeasurementMarkerIndices(data, () => true)]).toEqual([]);
  });

  it('bounds 3000 isolated observations to 300 markers without mutating data', () => {
    const data = points(Array.from({ length: 3000 }, (_, i) => i * 60));
    const original = structuredClone(data);
    expect(isolatedMeasurementMarkerIndices(data, () => true).size).toBe(300);
    expect(data).toEqual(original);
  });
});
