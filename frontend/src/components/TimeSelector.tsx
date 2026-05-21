import * as React from 'react';

export type TimeSelectorProps = {
  label?: string;
  value: Date | null;
  onChange: (next: Date) => void;
};

function getHours12(d: Date): number {
  const h = d.getHours();
  const h12 = h % 12;
  return h12 === 0 ? 12 : h12;
}

function setHours12(base: Date, hour12: number, am: boolean): Date {
  const d = new Date(base.getTime());
  const h12 = Math.max(1, Math.min(12, hour12));
  let h24 = h12 % 12; 
  if (!am) h24 += 12;
  d.setHours(h24);
  return d;
}

function setMinutes(base: Date, minutes: number): Date {
  const d = new Date(base.getTime());
  d.setMinutes(Math.max(0, Math.min(59, minutes)));
  d.setSeconds(0);
  d.setMilliseconds(0);
  return d;
}

const HOURS = Array.from({ length: 12 }, (_, i) => i + 1);
const MINUTES = Array.from({ length: 12 }, (_, i) => (i * 5) % 60); 

const selectCls = 'select-input w-16';

const TimeSelector: React.FC<TimeSelectorProps> = ({ label, value, onChange }) => {
  const base = value ?? new Date();
  const h12 = getHours12(base);
  const mins = base.getMinutes();
  const isAM = base.getHours() < 12;

  const updateHour = (ev: React.ChangeEvent<HTMLSelectElement>) => {
    const newHour = Number(ev.target.value) || 12;
    onChange(setHours12(base, newHour, isAM));
  };
  const updateMinute = (ev: React.ChangeEvent<HTMLSelectElement>) => {
    const newMinute = Number(ev.target.value) || 0;
    onChange(setMinutes(base, newMinute));
  };
  const updateAmPm = (ev: React.ChangeEvent<HTMLSelectElement>) => {
    const mode = ev.target.value === 'AM';
    onChange(setHours12(base, h12, mode));
  };

  return (
    <div className="flex items-center gap-2 flex-wrap" aria-label={label || 'Time selector'}>
      {label && <span className="text-xs font-medium text-slate-600 min-w-[72px]">{label}</span>}
      <select aria-label="Hour" className={selectCls} value={h12} onChange={updateHour}>
        {HOURS.map(h => <option key={h} value={h}>{h}</option>)}
      </select>
      <select aria-label="Minutes" className={selectCls} value={Math.round(mins / 5) * 5 % 60} onChange={updateMinute}>
        {MINUTES.map(m => <option key={m} value={m}>{m.toString().padStart(2,'0')}</option>)}
      </select>
      <select aria-label="AM or PM" className={selectCls} value={isAM ? 'AM' : 'PM'} onChange={updateAmPm}>
        <option value="AM">AM</option>
        <option value="PM">PM</option>
      </select>
    </div>
  );
};

export default TimeSelector;
