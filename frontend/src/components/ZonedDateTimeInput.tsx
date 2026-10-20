import { useEffect, useId, useState } from 'react';
import i18n from '../i18n';
import { inputToTimestamp, timestampToInput } from '../utils/timezone';

export default function ZonedDateTimeInput({ label, iso, timezone, onChange, onValidityChange }: {
  label: string;
  iso: string;
  timezone: string | null;
  onChange: (iso: string) => void;
  onValidityChange?: (valid: boolean) => void;
}) {
  const id = useId();
  const [value, setValue] = useState('');
  const [error, setError] = useState(false);
  useEffect(() => {
    setValue(timezone ? timestampToInput(iso, timezone) : '');
    setError(false);
    onValidityChange?.(true);
  }, [iso, timezone, onValidityChange]);
  return <div className="min-w-0 w-full sm:w-auto">
    <label className="flex flex-wrap items-center gap-2 text-sm font-medium" htmlFor={id}>
      {label}
      <input id={id} type="datetime-local" step="1" disabled={!timezone}
        className="min-w-0 w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
        value={value} aria-invalid={error} aria-describedby={error ? `${id}-error` : undefined}
        onChange={event => {
          setValue(event.target.value);
          try {
            const next = inputToTimestamp(event.target.value, timezone!, iso);
            setError(false);
            onValidityChange?.(true);
            onChange(next);
          } catch {
            setError(true);
            onValidityChange?.(false);
          }
        }} />
    </label>
    {error && <p id={`${id}-error`} role="alert" className="text-sm text-red-700 max-w-xs mt-1">
      {i18n.t('analytics:timezones.invalidInput')}
    </p>}
  </div>;
}
