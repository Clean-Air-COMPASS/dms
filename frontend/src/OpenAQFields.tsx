
import { useEffect } from 'react';
import type { ExternalAPI } from './api';
import { authFetchJson } from './auth';

export default function OpenAQFields({
  apiEditing,
  setApiEditing,
  selectedExternalAPI,
  apiParamsText,
  setApiParamsText,
}: {
  apiEditing: { base_url?: string; description?: string; api_key?: string };
  setApiEditing: (v: any) => void;
  selectedExternalAPI: ExternalAPI | null;
  apiParamsText: string;
  setApiParamsText: (s: string) => void;
}) {
  
  void apiEditing; void setApiEditing; 

  const parseParams = (): any => {
    
    
    
    
    const tryParse = (txt: any) => {
      if (txt == null) return null;
      if (typeof txt === 'object') return txt;
      if (typeof txt === 'string') {
        const trimmed = txt.trim();
        if (!trimmed || trimmed === '{}' || trimmed === 'null') return null;
        try { return JSON.parse(trimmed); } catch { return null; }
      }
      return null;
    };

    const fromApiParams = tryParse(apiParamsText);
    if (fromApiParams) return fromApiParams;
    const fromSelected = tryParse(selectedExternalAPI?.params);
    if (fromSelected) return fromSelected;
    return {};
  };

  const params = parseParams();
  const minuteVal = typeof params.rate_limit_per_minute !== 'undefined' ? String(params.rate_limit_per_minute) : '';
  const hourVal = typeof params.rate_limit_per_hour !== 'undefined' ? String(params.rate_limit_per_hour) : '';

  const updateParam = (key: string, value: string) => {
    let obj: any = {};
    try {
      obj = parseParams() || {};
    } catch { obj = {}; }
    if (value === '' || value == null) {
      delete obj[key];
    } else {
      const n = Number(value);
      if (!Number.isFinite(n)) return; 
      obj[key] = Number.isInteger(n) ? n : n;
    }
    try {
      setApiParamsText(JSON.stringify(obj, null, 2));
    } catch {
      
      setApiParamsText('{}');
    }
  };

  
  
  
  useEffect(() => {
    let cancelled = false;
    const id = selectedExternalAPI?.external_api_id;
    if (!id || id <= 0) return;
    (async () => {
      try {
        const detail = await authFetchJson(`/admin/external_apis/${id}`) as any;
        if (cancelled) return;
        const p = detail?.params;
        if (p == null) {
          setApiParamsText('{}');
        } else if (typeof p === 'string') {
          
          setApiParamsText(p.trim() || '{}');
        } else {
          setApiParamsText(JSON.stringify(p, null, 2));
        }
      } catch {
        // ignore fetch errors — keep existing params
      }
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedExternalAPI?.external_api_id]);

  return (
    <div className="provider-fields openaq-fields">
      <div className="form-field">
        <div>Rate Limit — Per Minute</div>
        <input
          className="text-input"
          type="number"
          min={0}
          value={minuteVal}
          onChange={e => updateParam('rate_limit_per_minute', e.target.value)}
          placeholder="e.g. 60"
        />
      </div>

      <div className="form-field">
        <div>Rate Limit — Per Hour</div>
        <input
          className="text-input"
          type="number"
          min={0}
          value={hourVal}
          onChange={e => updateParam('rate_limit_per_hour', e.target.value)}
          placeholder="e.g. 1000"
        />
      </div>
    </div>
  );
}
