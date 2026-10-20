import { hasTimestampOffset } from './utils/timezone';

/** Analytics history requests require two explicit, ordered instants. */
export function isValidAnalyticsDateRange(start: string, end: string): boolean {
  return hasTimestampOffset(start) && hasTimestampOffset(end)
    && Number.isFinite(Date.parse(start)) && Number.isFinite(Date.parse(end))
    && Date.parse(start) < Date.parse(end);
}
