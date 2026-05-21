import React, { useEffect, useState } from 'react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';
import TimeSelector from './TimeSelector';

export type DateTimeRangePickerProps = {
  open: boolean;
  startIso: string | '';
  endIso: string | '';
  onApply: (startIso: string, endIso: string) => void;
  onClose: () => void;
  onClear: () => void;
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

const DateTimeRangePicker: React.FC<DateTimeRangePickerProps> = ({ open, startIso, endIso, onApply, onClose, onClear }) => {
  const [startDate, setStartDate] = useState<Date | null>(() => isoToDate(startIso));
  const [endDate, setEndDate] = useState<Date | null>(() => isoToDate(endIso));

  useEffect(() => { setStartDate(isoToDate(startIso)); }, [startIso]);
  useEffect(() => { setEndDate(isoToDate(endIso)); }, [endIso]);

  if (!open) return null;

  return (
    <div className="popover" role="dialog" aria-label="Custom date range" onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
      <div className="px-2 py-2">
        <DatePicker
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
            label="Start time:"
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
            label="End time:"
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
        <button className="btn" onClick={() => { onClear(); }} aria-label="Clear range">Clear</button>
        <div className="flex-1" />
        <button className="btn" onClick={onClose} aria-label="Cancel">Cancel</button>
        <button
          className="btn"
          onClick={() => {
            const sIso = dateToIso(startDate);
            
            const eIso = endDate ? dateToIso(endDate) : new Date().toISOString();
            onApply(sIso, eIso);
          }}
          aria-label="Apply range"
        >Apply</button>
      </div>
    </div>
  );
};

export default DateTimeRangePicker;
