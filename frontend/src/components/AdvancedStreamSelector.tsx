import React, { useEffect, useRef, useState } from 'react';
import AsyncSensorSearch from './AsyncSensorSearch';
import type { SearchResult } from './AsyncSensorSearch';
import { fetchJson } from '../api';

export default function AdvancedStreamSelector({
  open,
  anchorRef,
  initialParameter,
  initialHours,
  onClose,
  onSetPrimary,
  onAddOverlay,
}: {
  open: boolean;
  anchorRef: React.RefObject<HTMLElement>;
  initialParameter: string;
  initialHours: number;
  onClose: () => void;
  onSetPrimary: (sensorId: number, parameter: string, opts: { aggregate: string; start?: string; end?: string }) => void;
  onAddOverlay: (sensorId: number, parameter: string, opts: { aggregate: string; start?: string; end?: string }) => void;
}) {
  const [parameters, setParameters] = useState<Array<{ code: string; display_name: string; unit_symbol?: string | null }>>([]);
  const [parameter, setParameter] = useState(initialParameter || '');
  const [hours, setHours] = useState(initialHours || 24);
  const [aggregate, setAggregate] = useState<string>('hour');
  const [start, setStart] = useState<string>('');
  const [end, setEnd] = useState<string>('');
  const [action, setAction] = useState<'primary' | 'overlay'>('overlay');
  const popRef = useRef<HTMLDivElement>(null);

  useEffect(() => setParameter(initialParameter || ''), [initialParameter]);
  useEffect(() => setHours(initialHours || 24), [initialHours]);

  
  useEffect(() => {
    const now = new Date();
    const startDt = new Date(now.getTime() - (hours || 24) * 60 * 60 * 1000);
    const fmt = (d: Date) => {
      const pad = (n: number) => String(n).padStart(2, '0');
      const yyyy = d.getFullYear();
      const mm = pad(d.getMonth() + 1);
      const dd = pad(d.getDate());
      const hh = pad(d.getHours());
      const mi = pad(d.getMinutes());
      return `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
    };
    setStart(fmt(startDt));
    setEnd(fmt(now));
  }, [hours]);

  useEffect(() => {
    if (!open) return;
    let cancel = false;
    (async () => {
      try {
        const data = await fetchJson<any[]>('/parameters');
        if (!cancel) setParameters(data || []);
      } catch {/* ignore */}
    })();
    return () => { cancel = true; };
  }, [open]);

  
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!open) return;
      const target = e.target as Node;
      if (popRef.current && !popRef.current.contains(target)) {
        if (anchorRef.current && anchorRef.current.contains(target as Node)) return;
        onClose();
      }
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open, onClose, anchorRef]);

  if (!open) return null;

  
  return (
    <div
      ref={popRef}
      className="absolute z-20 mt-2 w-[28rem] max-h-[28rem] overflow-auto bg-white border border-slate-200 rounded-lg shadow-sm p-3"
      role="dialog"
      aria-label="Advanced Stream Selector"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-semibold text-slate-800">Add Data Stream</div>
        <button
          type="button"
          className="text-slate-500 hover:text-slate-700"
          onClick={onClose}
          aria-label="Close selector"
        >✕</button>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-3">
        <label className="text-sm">
          <div className="text-slate-500 mb-1">Parameter</div>
          <select
            className="w-full transition-all duration-200 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
            value={parameter}
            onChange={(e) => setParameter(e.target.value)}
            title="Parameter"
            aria-label="Parameter"
          >
            {parameters.map((p) => (
              <option key={p.code} value={p.code}>{p.display_name}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <div className="text-slate-500 mb-1">Aggregate</div>
          <select
            className="w-full transition-all duration-200 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
            value={aggregate}
            onChange={(e) => setAggregate(e.target.value)}
            title="Aggregate"
            aria-label="Aggregate"
          >
            <option value="hour">Hourly</option>
            <option value="day">Daily</option>
          </select>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-3 mb-3">
        <label className="text-sm">
          <div className="text-slate-500 mb-1">Start (optional)</div>
          <input
            type="datetime-local"
            className="w-full transition-all duration-200 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            placeholder="All time"
            aria-label="Start date/time"
          />
        </label>
        <label className="text-sm">
          <div className="text-slate-500 mb-1">End (optional)</div>
          <input
            type="datetime-local"
            className="w-full transition-all duration-200 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            placeholder="Now"
            aria-label="End date/time"
          />
        </label>
      </div>

      <div className="mb-3">
        <div className="text-slate-500 text-sm mb-1">Action</div>
        <div className="flex items-center gap-4 text-sm">
          <label className="inline-flex items-center gap-2">
            <input type="radio" name="stream_action" checked={action==='overlay'} onChange={() => setAction('overlay')} />
            Add Overlay
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="radio" name="stream_action" checked={action==='primary'} onChange={() => setAction('primary')} />
            Replace Primary
          </label>
        </div>
      </div>

      <div className="space-y-2">
        <div className="text-slate-500 text-sm">Search sensors</div>
        <AsyncSensorSearch
          parameter={parameter}
          hours={(function () {
            
            if (start) {
              const endDate = end ? new Date(end) : new Date();
              const startDate = new Date(start);
              const diffMs = endDate.getTime() - startDate.getTime();
              const h = Math.max(1, Math.ceil(diffMs / (1000 * 60 * 60)));
              return h;
            }
            return hours;
          })()}
          onSelect={(s: SearchResult) => {
            
            const toUtcIso = (val?: string) => {
              if (!val) return undefined;
              return new Date(val).toISOString();
            };
            const opts = {
              aggregate,
              start: start ? toUtcIso(start) : undefined,
              end: end ? toUtcIso(end) : undefined,
            };
            if (action === 'primary') {
              onSetPrimary(s.sensor_id, (s.parameter || parameter), opts);
            } else {
              onAddOverlay(s.sensor_id, (s.parameter || parameter), opts);
            }
            onClose();
          }}
        />
      </div>
    </div>
  );
}
