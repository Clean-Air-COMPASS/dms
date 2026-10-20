import { authFetchJson } from './auth';
import type { EventRecord, JobRunRecord } from './api';

export type HistoryPage<T> = {
  items: T[];
  total: number;
  options: Record<string, string[]>;
};

export type HistoryFilters = {
  limit: number;
  offset: number;
  started_after?: string;
  started_before?: string;
  status?: string;
  task?: string;
  event_type?: string;
  source?: string;
  severity?: string;
};

function historyQuery(filters: HistoryFilters): string {
  const params = new URLSearchParams({ paginated: 'true' });
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') params.set(key, String(value));
  }
  return params.toString();
}

export function listJobHistory(filters: HistoryFilters) {
  return authFetchJson<HistoryPage<JobRunRecord>>(`/admin/jobs/runs?${historyQuery(filters)}`);
}

export function listEventHistory(filters: HistoryFilters) {
  return authFetchJson<HistoryPage<EventRecord>>(`/admin/events?${historyQuery(filters)}`);
}

export const HISTORY_PAGE_SIZE = 25;
export type HistoryWindow = { from: string; to: string; offset: number; snapshot: string };
export function initialHistoryWindow(): HistoryWindow {
  return { from: '', to: '', offset: 0, snapshot: new Date().toISOString() };
}
export function historyDates(window: HistoryWindow) {
  return {
    started_after: window.from ? `${window.from}T00:00:00Z` : undefined,
    // The end date includes the full UTC calendar day.
    started_before: window.to
      ? new Date(Date.parse(`${window.to}T00:00:00Z`) + 86400000).toISOString()
      : window.snapshot,
  };
}
