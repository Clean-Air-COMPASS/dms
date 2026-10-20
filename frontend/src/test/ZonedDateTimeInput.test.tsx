import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ZonedDateTimeInput from '../components/ZonedDateTimeInput';
import DateTimeRangePicker from '../components/DateTimeRangePicker';

describe('timezone-aware range controls', () => {
  it('changes the display timezone without changing the instant', () => {
    const onChange = vi.fn();
    const props = { label: 'Start', iso: '2026-03-08T07:30:00Z', onChange };
    const { rerender } = render(<ZonedDateTimeInput {...props} timezone="UTC" />);
    expect(screen.getByLabelText('Start')).toHaveValue('2026-03-08T07:30');
    rerender(<ZonedDateTimeInput {...props} timezone="America/New_York" />);
    expect(screen.getByLabelText('Start')).toHaveValue('2026-03-08T03:30');
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Start'), { target: { value: '2026-03-08T04:30' } });
    expect(onChange).toHaveBeenCalledWith('2026-03-08T08:30:00.000Z');
  });
  it('shows an accessible error and blocks applying a DST gap in the picker', () => {
    const onApply = vi.fn();
    render(<DateTimeRangePicker open startIso="2026-03-08T06:30:00Z" endIso="2026-03-08T08:30:00Z"
      displayTimezone="America/New_York" onApply={onApply} onClose={vi.fn()} onClear={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Start:'), { target: { value: '2026-03-08T02:30' } });
    expect(screen.getByRole('alert')).toHaveTextContent('daylight-saving');
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
    expect(onApply).not.toHaveBeenCalled();
  });
  it.each(['2026-03-08T08:30', '2026-03-08T09:30', ''])('rejects an unordered or incomplete picker range (%s)', value => {
    const onApply = vi.fn();
    render(<DateTimeRangePicker open startIso="2026-03-08T06:30:00Z" endIso="2026-03-08T08:30:00Z"
      displayTimezone="UTC" onApply={onApply} onClose={vi.fn()} onClear={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Start:'), { target: { value } });
    expect(screen.getByRole('alert')).toHaveTextContent('Start must be before End');
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Start:'), { target: { value: '2026-03-08T07:30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledWith('2026-03-08T07:30:00.000Z', '2026-03-08T08:30:00Z');
  });
});
