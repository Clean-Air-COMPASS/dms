import { act, fireEvent, render, screen, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import LocationSearch from '../LocationSearch';
const result = { place_id: 'london', name: 'London', lat: 51.5, lon: -0.12, result_type: 'city', formatted: 'London' };
const response = (results = [result]) => ({ ok: true, status: 200, json: async () => ({ results }) });
const search = async (text: string) => {
  fireEvent.change(screen.getByRole('combobox'), { target: { value: text } });
  await act(async () => { await vi.advanceTimersByTimeAsync(250); });
};
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal('fetch', vi.fn()); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
it('completes search and selects a result by keyboard', async () => {
  vi.mocked(fetch).mockResolvedValue(response() as Response);
  const select = vi.fn(); render(<LocationSearch onLocationSelect={select} />);
  await search('London');
  expect(screen.getByRole('option')).toHaveTextContent('London');
  expect(screen.getByRole('status')).not.toHaveTextContent('Searching');
  fireEvent.keyDown(screen.getByRole('combobox'), {key:'Enter'});
  expect(select).toHaveBeenCalledWith(51.5, -0.12, 12, 'London');
});
it('announces empty results', async () => {
  vi.mocked(fetch).mockResolvedValue(response([]) as Response);
  render(<LocationSearch onLocationSelect={vi.fn()} />); await search('Nothing');
  expect(screen.getByRole('status')).toHaveTextContent('No matches');
});
it.each([429, 503, 502])('exits loading on HTTP %s and can retry', async status => {
  vi.mocked(fetch).mockResolvedValueOnce({ok:false,status} as Response).mockResolvedValue(response() as Response);
  render(<LocationSearch onLocationSelect={vi.fn()} />); await search('Failure');
  expect(screen.getByRole('status')).not.toHaveTextContent('Searching');
  expect(screen.getByRole('status').textContent).not.toBe('');
  await search('London'); expect(screen.getByRole('option')).toBeInTheDocument();
});
it('recovers from a network failure', async () => {
  vi.spyOn(console,'error').mockImplementation(() => {});
  vi.mocked(fetch).mockRejectedValue(new TypeError('Offline'));
  render(<LocationSearch onLocationSelect={vi.fn()} />); await search('Failure');
  expect(screen.getByRole('status')).toHaveTextContent('Location search failed');
  expect(screen.getByRole('combobox')).toHaveAttribute('aria-describedby',screen.getByRole('status').id);
});
it('bounds a hanging request and ignores its late response', async () => {
  let finish!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation(() => new Promise(resolve => {finish=resolve;}));
  render(<LocationSearch onLocationSelect={vi.fn()} />); await search('Slow');
  await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
  expect(screen.getByRole('status')).toHaveTextContent('took too long');
  await act(async () => finish(response() as Response));
  expect(screen.queryByRole('option')).not.toBeInTheDocument();
});
it.each(['clear','new query','escape','unmount'])('invalidates pending work on %s, even if fetch ignores abort', async action => {
  let finish!: (value: Response) => void;
  vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => {finish=resolve;})).mockResolvedValue(response([]) as Response);
  const select=vi.fn(); const view=render(<LocationSearch onLocationSelect={select} />); await search('London');
  const signal=vi.mocked(fetch).mock.calls[0][1]?.signal;
  if(action==='clear') fireEvent.click(screen.getByRole('button',{name:'Clear search'}));
  if(action==='escape') fireEvent.keyDown(screen.getByRole('combobox'),{key:'Escape'});
  if(action==='new query') await search('New place');
  if(action==='unmount') view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(response() as Response));
  expect(screen.queryByRole('option')).not.toBeInTheDocument(); expect(select).not.toHaveBeenCalled();
});
