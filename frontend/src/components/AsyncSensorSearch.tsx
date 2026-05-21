import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchJson } from '../api';

export type SearchResult = {
  sensor_id: number;
  external_sensor_id?: string | number | null;
  parameter: string;
  parameter_name?: string;
  unit?: string;
  device_name?: string;
};

function debounce<T extends (...args: any[]) => void>(fn: T, delay: number) {
  let t: any;
  return (...args: Parameters<T>) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), delay);
  };
}

export default function AsyncSensorSearch({
  parameter,
  hours,
  onSelect,
  placeholder = 'Search sensors…',
}: {
  parameter: string;
  hours: number;
  onSelect: (s: SearchResult) => void;
  placeholder?: string;
}) {
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const doSearch = useMemo(() => debounce(async (query: string) => {
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams();
      
      const since = new Date(Date.now() - hours * 3600 * 1000).toISOString();
      params.set('since', since);
      
      const data = await fetchJson<any[]>(`/measurements/${encodeURIComponent(parameter)}/latest?${params.toString()}`);
      if (!mounted.current) return;
      
      const ql = (query || '').toLowerCase();
      const filtered = (Array.isArray(data) ? data : []).filter((r: any) => {
        if (!ql) return true;
        const name = (r?.device?.name || '').toLowerCase();
        const ext = String(r?.external_sensor_id || '').toLowerCase();
        const sid = String(r?.sensor_id || '').toLowerCase();
        return name.includes(ql) || ext.includes(ql) || sid.includes(ql);
      }).slice(0, 20).map((r: any) => ({
        sensor_id: r.sensor_id,
        external_sensor_id: r.external_sensor_id,
        parameter: r.parameter,
        unit: r.unit,
        device_name: r?.device?.name,
      } as SearchResult));
      setResults(filtered);
    } catch (e: any) {
      if (!mounted.current) return;
      setError(e?.message || 'Search error');
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, 250), [parameter, hours]);

  useEffect(() => {
    
    doSearch(q);
  }, [q, parameter, hours, doSearch]);

  return (
    <div className="w-full">
      <input
        type="text"
        className="w-full transition-all duration-200 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
        placeholder={placeholder}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Search sensors"
      />
      <div className="mt-2 max-h-56 overflow-auto rounded-md border border-slate-200 bg-white">
        {loading && <div className="px-3 py-2 text-blue-700 text-sm">Searching…</div>}
        {error && !loading && <div className="px-3 py-2 text-red-700 text-sm">{error}</div>}
        {!loading && !error && results.length === 0 && (
          <div className="px-3 py-2 text-slate-500 text-sm">No matches</div>
        )}
        {!loading && !error && results.map((r) => (
          <button
            key={`${r.sensor_id}`}
            type="button"
            title={`Select sensor ${r.sensor_id}`}
            className="w-full text-left px-3 py-2 hover:bg-blue-50 text-sm"
            onClick={() => onSelect(r)}
          >
            <div className="font-medium text-slate-800">Sensor {r.sensor_id} • {r.parameter.toUpperCase()} {r.unit ? `(${r.unit})` : ''}</div>
            <div className="text-slate-500">{r.device_name || ''}{r.external_sensor_id ? ` • ${r.external_sensor_id}` : ''}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
