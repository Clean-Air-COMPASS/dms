import { useEffect, useMemo, useState } from 'react';
import { saveRuleDraft, previewRule, activateRule } from '../api';
import type { PluginInfo, QCRule, PreviewResult } from '../api';

export default function QCRuleEditDrawer({
  rule,
  plugins,
  onClose,
  onChanged,
}: {
  rule: QCRule;
  plugins: PluginInfo[];
  onClose: () => void;
  onChanged: () => Promise<void> | void;
}) {
  const plugin = useMemo(() => plugins.find(p => p.name === rule.check_code), [plugins, rule.check_code]);
  const schema = plugin?.param_schema || {};
  const [form, setForm] = useState<Record<string, any>>(() => ({ ...(rule.draft_params || rule.params || {}) }));
  const [saving, setSaving] = useState(false);
  const [activating, setActivating] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string,string | null>>({});

  useEffect(() => {
    setForm({ ...(rule.draft_params || rule.params || {}) });
    setPreview(null);
    setError(null);
  // Include param objects to satisfy exhaustive-deps; rule identity change already triggers.
  }, [rule.qc_rule_id, rule.draft_params, rule.params]);

  const onFieldChange = (key: string, val: string) => {
    const coerced = coerceValue(schema[key], val);
    setForm(prev => ({ ...prev, [key]: coerced }));
    
    const t = schema[key]?.type || 'number';
    setFieldErrors(prev => {
      const next = { ...prev };
      if ((t === 'number' || t === 'integer') && val.trim() !== '' && coerced === undefined) {
        next[key] = 'Must be a number';
      } else {
        next[key] = null;
      }
      return next;
    });
  };

  const coerceValue = (spec: any, val: string): any => {
    const t = spec?.type || 'number';
    if (t === 'number') {
      const n = Number(val);
      return Number.isFinite(n) ? n : undefined;
    }
    if (t === 'integer') {
      const n = parseInt(val, 10);
      return Number.isFinite(n) ? n : undefined;
    }
    if (t === 'boolean') return val === 'true';
    return val;
  };

  const saveDraft = async () => {
    
    for (const [k, spec] of Object.entries(schema)) {
      if (spec?.required && (form[k] === undefined || form[k] === null || String(form[k]).trim() === '')) {
        setError(`Field ${spec.label || k} is required`);
        return;
      }
    }
    for (const v of Object.values(fieldErrors)) {
      if (v) { setError('Fix validation errors before saving'); return; }
    }

    setSaving(true); setError(null);
    try {
      await saveRuleDraft(rule.qc_rule_id, form);
      await onChanged();
    } catch (e:any) {
      setError(e?.message || 'Failed to save draft');
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async () => {
    for (const v of Object.values(fieldErrors)) {
      if (v) { setError('Fix validation errors before preview'); return; }
    }
    setPreviewing(true); setError(null);
    try {
      
      await saveRuleDraft(rule.qc_rule_id, form);
      const res = await previewRule(rule.qc_rule_id, 24);
      setPreview(res);
    } catch (e:any) {
      setError(e?.message || 'Preview failed');
      setPreview(null);
    } finally {
      setPreviewing(false);
    }
  };

  const onActivate = async () => {
    for (const v of Object.values(fieldErrors)) {
      if (v) { setError('Fix validation errors before activating'); return; }
    }
    setActivating(true); setError(null);
    try {
      
      await saveRuleDraft(rule.qc_rule_id, form);
      await activateRule(rule.qc_rule_id);
      await onChanged();
      onClose();
    } catch (e:any) {
      setError(e?.message || 'Activation failed');
    } finally {
      setActivating(false);
    }
  };

  const scope = [
    rule.sensor_id != null ? `sensor:${rule.sensor_id}` : null,
    rule.parameter_id != null ? `parameter:${rule.parameter_id}` : (rule.sensor_id==null ? 'global' : null),
    rule.aggregate_code || null,
  ].filter(Boolean).join(' · ');

  return (
    <div className="drawer">
      <div className="drawer-header">
        <div>
          <h3>Edit QC Rule #{rule.qc_rule_id}</h3>
          <div className="subtle">{plugin?.display_name || rule.check_code} • {scope}</div>
          {rule.version != null && <div className="subtle">Version {rule.version} • State {rule.state || 'active'}</div>}
        </div>
        <button className="btn" onClick={onClose}>Close</button>
      </div>

      {plugin?.long_description && (
        <div className="hint">{plugin.long_description}</div>
      )}

      <div className="form-grid">
        {Object.entries(schema).map(([key, spec]: any) => (
          <div className="form-label" key={key}>
            <div>{spec?.label || key}</div>
            <input
              className="text-input"
              placeholder={spec?.help || ''}
              value={form[key] ?? ''}
              onChange={e=>onFieldChange(key, e.target.value)}
            />
            {fieldErrors[key] && <div className="error-text">{fieldErrors[key]}</div>}
          </div>
        ))}
        {Object.keys(schema).length === 0 && (
          <div className="hint">This plugin has no editable parameters.</div>
        )}
      </div>

      {error && <div className="error-text">{error}</div>}

      <div className="row-flex gap-8">
        <button className="btn" onClick={saveDraft} disabled={saving}>Save Draft</button>
        <button className="btn" onClick={runPreview} disabled={previewing}>Preview (24h)</button>
        <button className="btn primary" onClick={onActivate} disabled={activating}>Activate</button>
      </div>

      {preview && (
        <div className="panel">
          <h4>Preview Results</h4>
          <div className="row-flex gap-16">
            <div>Samples: <b>{preview.samples}</b></div>
            <div>Would pass: <b>{preview.would_pass}</b></div>
            <div>Would fail: <b>{preview.would_fail}</b></div>
            <div>Threshold: <b>{preview.threshold}</b></div>
          </div>
        </div>
      )}
    </div>
  );
}
