import type { MeasurementHistoryDataPoint } from './measurementHistory';
import { isFlagged } from './measurementQc';

type MeasurementPoint = {
  x: number;
  y: number | null;
  measurementPoint: MeasurementHistoryDataPoint;
};

/** Select ordinary observations with no visible adjoining line, in sorted order.
 * Reuse the chart's segment exclusion rule so QC and temporal gaps agree.
 * One marker per time bin bounds overplotting without removing hover targets.
 */
export function isolatedMeasurementMarkerIndices(
  points: readonly MeasurementPoint[],
  excludedSegment: (context: { p0DataIndex: number; p1DataIndex: number }) => boolean,
): Set<number> {
  const selected = new Set<number>();
  const occupiedBins = new Set<number>();
  const extent = Math.max(1, (points.at(-1)?.x ?? 0) - (points[0]?.x ?? 0));
  const connects = (left: number, right: number) => left >= 0 && right < points.length
    && points[left].y != null && points[right].y != null
    && Number.isFinite(points[left].x) && Number.isFinite(points[right].x)
    && !excludedSegment({ p0DataIndex: left, p1DataIndex: right });

  points.forEach((point, index) => {
    // Exceptional markers retain their existing shapes, priority and own bounds.
    if (point.y == null || !Number.isFinite(point.x) || point.measurementPoint.is_valid === false
      || isFlagged(point.measurementPoint)) return;
    if (connects(index - 1, index) || connects(index, index + 1)) return;
    // Match the existing QC density bound, independently for ordinary points.
    const bin = Math.min(299, Math.floor((point.x - points[0].x) / extent * 300));
    if (!occupiedBins.has(bin)) { occupiedBins.add(bin); selected.add(index); }
  });
  return selected;
}
