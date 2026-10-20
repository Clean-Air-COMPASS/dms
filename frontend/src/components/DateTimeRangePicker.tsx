import { isValidAnalyticsDateRange } from '../analyticsDateRange';
import { Trans, useTranslation } from 'react-i18next';
import i18n from '../i18n';
import React, { useEffect, useRef, useState } from 'react';
import DatePicker from 'react-datepicker';
import { enUS, es } from 'date-fns/locale';
import 'react-datepicker/dist/react-datepicker.css';
import TimeSelector from './TimeSelector';
import ZonedDateTimeInput from './ZonedDateTimeInput';

export type DateTimeRangePickerProps = {
  open: boolean;
  startIso: string | '';
  endIso: string | '';
  onApply: (startIso: string, endIso: string) => void;
  onClose: () => void;
  onClear: () => void;
  displayTimezone?: string | null;
};

function isoToDate(iso: string | ''): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d;
}

function dateToIso(d: Date | null): string {
  if (!d) return '';
  return d.toISOString();
}

const DateTimeRangePicker: React.FC<DateTimeRangePickerProps> = (props) => {
  if (props.displayTimezone !== undefined) return <ZonedRangePicker {...props} />;
  return <BrowserRangePicker {...props} />;
};

function ZonedRangePicker({ open, startIso, endIso, displayTimezone, onApply, onClose, onClear }: DateTimeRangePickerProps) {
  const dialog = useRef<HTMLDivElement>(null);
  const [start, setStart] = useState(startIso);
  const [end, setEnd] = useState(endIso);
  const [startValid, setStartValid] = useState(true);
  const [endValid, setEndValid] = useState(true);
  useEffect(() => { setStart(startIso); setEnd(endIso); }, [startIso, endIso, open]);
  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLInputElement>('input:not(:disabled)')?.focus();
    return () => { previousFocus?.focus(); };
  }, [open]);
  const rangeValid = startValid && endValid && isValidAnalyticsDateRange(start, end);
  if (!open) return null;
  return <div ref={dialog} className="popover p-3 space-y-3" style={{ width: 'min(320px, calc(100vw - 64px))' }} role="dialog"
    aria-label={i18n.t('analytics:dateTimeRangePicker.accessibility.customDateRange')}
    onKeyDown={event => { if (event.key === 'Escape') onClose(); }}>
    <p className="text-sm">{displayTimezone ? i18n.t('analytics:timezones.displayedIn', { timezone: displayTimezone }) : i18n.t('analytics:timezones.unavailable')}</p>
    <ZonedDateTimeInput label={i18n.t('analytics:analytics.fields.start')} iso={start} timezone={displayTimezone ?? null} onChange={setStart} onValidityChange={setStartValid} />
    <ZonedDateTimeInput label={i18n.t('analytics:analytics.fields.end')} iso={end} timezone={displayTimezone ?? null} onChange={setEnd} onValidityChange={setEndValid} />
    {!isValidAnalyticsDateRange(start, end) && <p role="alert" className="text-sm text-red-700">{i18n.t('analytics:analytics.messages.invalidDateRange')}</p>}
    <div className="flex flex-wrap gap-2">
      <button className="btn" onClick={onClear}>{i18n.t('analytics:dateTimeRangePicker.actions.clear')}</button>
      <button className="btn" onClick={onClose}>{i18n.t('common:actions.cancel')}</button>
      <button className="btn" disabled={!displayTimezone || !rangeValid} onClick={() => onApply(start, end)}>{i18n.t('analytics:dateTimeRangePicker.actions.apply')}</button>
    </div>
  </div>;
}

const BrowserRangePicker: React.FC<DateTimeRangePickerProps> = ({ open, startIso, endIso, onApply, onClose, onClear }) => {
  const { t, i18n: language } = useTranslation('analytics');
  const [startDate, setStartDate] = useState<Date | null>(() => isoToDate(startIso));
  const [endDate, setEndDate] = useState<Date | null>(() => isoToDate(endIso));

  useEffect(() => { setStartDate(isoToDate(startIso)); }, [startIso]);
  useEffect(() => { setEndDate(isoToDate(endIso)); }, [endIso]);

  if (!open) return null;

  return (
    <div className="popover" role="dialog" aria-label={i18n.t('analytics:dateTimeRangePicker.accessibility.customDateRange')} onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
      <div className="px-2 py-2">
        <DatePicker
          locale={language.resolvedLanguage === 'es' ? es : enUS}
          previousMonthAriaLabel={t('dateTimeRangePicker.calendar.previousMonth')}
          nextMonthAriaLabel={t('dateTimeRangePicker.calendar.nextMonth')}
          previousMonthButtonLabel={t('dateTimeRangePicker.calendar.previousMonth')}
          nextMonthButtonLabel={t('dateTimeRangePicker.calendar.nextMonth')}
          chooseDayAriaLabelPrefix={t('dateTimeRangePicker.calendar.chooseDay')}
          disabledDayAriaLabelPrefix={t('dateTimeRangePicker.calendar.disabledDay')}
          weekAriaLabelPrefix={t('dateTimeRangePicker.calendar.week')}
          monthAriaLabelPrefix={t('dateTimeRangePicker.calendar.month')}
          selected={startDate}
          onChange={(dates: [Date | null, Date | null]) => {
            const [s, e] = dates;
            setStartDate(s);
            setEndDate(e);
          }}
          startDate={startDate}
          endDate={endDate}
          selectsRange
          dateFormat="P"
          inline
        />
        <div className="mt-2 flex flex-col gap-1">
          <TimeSelector
            label={i18n.t('analytics:dateTimeRangePicker.accessibility.startTime')}
            value={startDate}
            onChange={(next) => {
              if (startDate) {
                const d = new Date(startDate.getTime());
                d.setHours(next.getHours(), next.getMinutes(), 0, 0);
                setStartDate(d);
              } else {
                setStartDate(next);
              }
            }}
          />
          <TimeSelector
            label={i18n.t('analytics:dateTimeRangePicker.accessibility.endTime')}
            value={endDate}
            onChange={(next) => {
              if (endDate) {
                const d = new Date(endDate.getTime());
                d.setHours(next.getHours(), next.getMinutes(), 0, 0);
                setEndDate(d);
              } else {
                setEndDate(next);
              }
            }}
          />
        </div>
      </div>

      <div className="px-2 pb-2 flex items-center gap-2">
        <button className="btn" onClick={() => { onClear(); }} aria-label={i18n.t('analytics:dateTimeRangePicker.accessibility.clearRange')}><Trans ns="analytics" i18nKey="dateTimeRangePicker.actions.clear" /></button>
        <div className="flex-1" />
        <button className="btn" onClick={onClose} aria-label={i18n.t('common:actions.cancel')}><Trans ns="common" i18nKey="actions.cancel" /></button>
        <button
          className="btn"
          onClick={() => {
            const sIso = dateToIso(startDate);
            
            const eIso = endDate ? dateToIso(endDate) : new Date().toISOString();
            onApply(sIso, eIso);
          }}
          aria-label={i18n.t('analytics:dateTimeRangePicker.accessibility.applyRange')}
        ><Trans ns="analytics" i18nKey="dateTimeRangePicker.actions.apply" /></button>
      </div>
    </div>
  );
};

export default DateTimeRangePicker;
