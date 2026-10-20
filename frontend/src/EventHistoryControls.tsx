import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { formatOperationalTimestamp } from './utils/timezone';
import './eventHistory.css';

import { HISTORY_PAGE_SIZE, initialHistoryWindow, type HistoryWindow } from './eventsHistory';

export default function EventHistoryControls({ window, onChange, total, loading, error, firstTime, lastTime }: {
  window: HistoryWindow;
  onChange: (value: HistoryWindow) => void;
  total: number;
  loading: boolean;
  error: boolean;
  firstTime?: string | null;
  lastTime?: string | null;
}) {
  const { t } = useTranslation('events');
  const [from, setFrom] = useState(window.from);
  const [to, setTo] = useState(window.to);
  const invalid = Boolean(from && to && from > to);
  return <section className="event-history-controls" aria-label={t('history.title')}>
    <p>{t('history.scope')}</p>
    <form className="filter-bar" onSubmit={event => {
      event.preventDefault();
      if (!invalid) onChange({ from, to, offset: 0, snapshot: new Date().toISOString() });
    }}>
      <label className="filter-group">{t('history.from')}<input type="date" max={new Date().toISOString().slice(0, 10)} value={from} onChange={event => setFrom(event.target.value)} /></label>
      <label className="filter-group">{t('history.to')}<input type="date" value={to} aria-invalid={invalid} aria-describedby={invalid ? 'history-date-error' : undefined} onChange={event => setTo(event.target.value)} /></label>
      <button className="btn" disabled={invalid} type="submit">{t('history.apply')}</button>
      <button className="btn" type="button" onClick={() => { setFrom(''); setTo(''); onChange(initialHistoryWindow()); }}>{t('history.clear')}</button>
    </form>
    {invalid && <p id="history-date-error" role="alert">{t('history.invalid')}</p>}
    <p className="muted">{t('history.period', { from: window.from || t('history.beginning'), to: window.to || formatOperationalTimestamp(window.snapshot) })}</p>
    <div className="event-history-pagination">
      <span role="status">{!loading && !error && t('history.range', { first: total ? window.offset + 1 : 0, last: Math.min(window.offset + HISTORY_PAGE_SIZE, total), total })}</span>
      <button className="btn" disabled={loading || window.offset === 0} onClick={() => onChange({ ...window, offset: Math.max(0, window.offset - HISTORY_PAGE_SIZE) })}>{t('history.previous')}</button>
      <button className="btn" disabled={loading || error || window.offset + HISTORY_PAGE_SIZE >= total} onClick={() => onChange({ ...window, offset: window.offset + HISTORY_PAGE_SIZE })}>{t('history.next')}</button>
    </div>
    {!loading && !error && firstTime && lastTime && <p className="muted">{t('history.pagePeriod', { from: formatOperationalTimestamp(lastTime), to: formatOperationalTimestamp(firstTime) })}</p>}
  </section>;
}
