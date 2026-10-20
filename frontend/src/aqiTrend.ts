export const AQI_CURRENT_CONDITION_HISTORY_HOURS = 24;
export const AQI_COMPLETED_DAY_HISTORY_DAYS = 7;


export function createCurrentConditionHistoryRange(latestObservedAt: string): {
  start: string;
  end: string;
} | null {
  const latestTimestamp = new Date(latestObservedAt);
  if (Number.isNaN(latestTimestamp.getTime())) return null;
  const start = new Date(
    latestTimestamp.getTime()
      - (AQI_CURRENT_CONDITION_HISTORY_HOURS - 1) * 60 * 60 * 1000,
  );
  const end = new Date(latestTimestamp.getTime() + 60 * 60 * 1000);
  return { start: start.toISOString(), end: end.toISOString() };
}
