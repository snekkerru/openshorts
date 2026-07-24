import React, { useState } from 'react';
import { apiFetch } from '../lib/api';

export default function BrollSlotEditor({ segment, onChange, onClose, t = (x) => x }) {
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState('');
  const source = segment.broll_source || 'ai';
  const mute = segment.broll_mute_audio !== false; // default true

  const upload = async (file) => {
    if (!file) return;
    setUploading(true); setErr('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await apiFetch('/api/saasshorts/broll-upload', { method: 'POST', body: fd });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Upload failed'); }
      const data = await res.json();
      onChange({ broll_source: data.kind, broll_asset_url: data.url });
    } catch (e) { setErr(e.message); }
    setUploading(false);
  };

  return (
    <div className="rounded-xl border border-rule bg-paper p-4 mt-2 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-ink">{t('B-roll slot')} · {segment.type}</h4>
        <button type="button" onClick={onClose} className="text-xs text-muted hover:text-ink">✕</button>
      </div>

      <div className="flex gap-2 text-xs">
        {[['ai', t('AI')], ['image', t('My photo')], ['video', t('My video')]].map(([val, label]) => (
          <label key={val} className={`px-3 py-1.5 rounded-input border cursor-pointer ${source === val ? 'border-accent text-ink' : 'border-rule text-muted'}`}>
            <input type="radio" className="hidden" name="broll_source" checked={source === val}
              onChange={() => onChange({ broll_source: val })} />
            {label}
          </label>
        ))}
      </div>

      {source === 'ai' && (
        <textarea
          className="w-full text-xs bg-black/30 border border-rule rounded-input p-2 text-ink2"
          rows={3}
          value={segment.broll_prompt || ''}
          onChange={(e) => onChange({ broll_prompt: e.target.value })}
          placeholder={t('Describe the b-roll visual...')}
        />
      )}

      {(source === 'image' || source === 'video') && (
        <div className="space-y-2">
          <input type="file" accept={source === 'image' ? 'image/*' : 'video/*'}
            disabled={uploading}
            onChange={(e) => upload(e.target.files?.[0])}
            className="block text-xs text-muted" />
          {uploading && <p className="text-xs text-muted">{t('Uploading...')}</p>}
          {segment.broll_asset_url && !uploading && (
            <p className="text-xs text-emerald-400 truncate">✓ {segment.broll_asset_url.split('/').pop()}</p>
          )}
          {err && <p className="text-xs text-red-400">{err}</p>}
        </div>
      )}

      {source === 'video' && (
        <label className="flex items-center gap-2 text-xs text-ink2">
          <input type="checkbox" checked={mute}
            onChange={(e) => onChange({ broll_mute_audio: e.target.checked })} />
          {t('Mute video audio (keep voiceover only)')}
        </label>
      )}

      <div className="flex gap-2 items-center text-xs text-muted">
        <label>{t('Start')}
          <input type="number" step="0.5" value={segment.start}
            onChange={(e) => onChange({ start: parseFloat(e.target.value) })}
            className="w-16 ml-1 bg-black/30 border border-rule rounded-input px-1 text-ink2" />
        </label>
        <label>{t('End')}
          <input type="number" step="0.5" value={segment.end}
            onChange={(e) => onChange({ end: parseFloat(e.target.value) })}
            className="w-16 ml-1 bg-black/30 border border-rule rounded-input px-1 text-ink2" />
        </label>
      </div>
    </div>
  );
}
