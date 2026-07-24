import { useState, useEffect, useCallback, useRef } from 'react';
import { Loader2, Play, Download, Trash2, RefreshCw, AlertCircle, X, Copy, Check } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { useI18n } from '../contexts/I18nContext';

const STATUS_META = {
  processing:  { key: 'in progress', cls: 'badge-brass', spin: true },
  interrupted: { key: 'interrupted', cls: 'badge-warn' },
  completed:   { key: 'done',        cls: 'badge-ok' },
  failed:      { key: 'error',       cls: 'badge-danger' },
};

export default function MyGenerationsTab({ falKey, elevenLabsKey, falImageHeaders = {} }) {
  const { t } = useI18n();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewing, setViewing] = useState(null); // record for the viewer modal
  const timer = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/api/saasshorts/my-generations');
      const data = await res.json().catch(() => ({}));
      setItems(data.generations || []);
    } catch { /* keep prior list */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Poll every 5s while anything is active.
  useEffect(() => {
    const active = items.some((r) => r.status === 'processing');
    clearInterval(timer.current);
    if (active) timer.current = setInterval(load, 5000);
    return () => clearInterval(timer.current);
  }, [items, load]);

  const remove = async (jobId) => {
    if (!window.confirm(t('Delete this generation?'))) return;
    await apiFetch(`/api/saasshorts/my-generations/${jobId}`, { method: 'DELETE' });
    setItems((prev) => prev.filter((r) => r.job_id !== jobId));
  };

  const retry = async (rec) => {
    // rec.script is the full original script (segments, actor_description, …).
    await apiFetch('/api/saasshorts/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Fal-Key': falKey, 'X-ElevenLabs-Key': elevenLabsKey, ...falImageHeaders },
      body: JSON.stringify({ script: rec.script || rec, video_mode: rec.video_mode, retry_job_id: rec.job_id }),
    });
    load();
  };

  return (
    <div className="h-full overflow-y-auto custom-scrollbar p-4 sm:p-6 md:p-10 animate-fade">
      <div className="max-w-5xl mx-auto">
        <p className="eyebrow mb-1.5">03 · {t('My Generations')}</p>
        <h1 className="font-display text-2xl md:text-3xl text-ink mb-6">{t('My Generations')}</h1>

        {loading ? (
          <div className="flex items-center gap-2 text-muted text-sm"><Loader2 size={16} className="animate-spin" /> …</div>
        ) : items.length === 0 ? (
          <div className="card p-8 text-center">
            <p className="text-ink font-medium mb-1">{t('No generations yet')}</p>
            <p className="text-xs text-muted">{t('Generate your first video in AI Shorts.')}</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((rec) => {
              const s = STATUS_META[rec.status] || STATUS_META.completed;
              return (
                <div key={rec.job_id} className="card p-4 flex flex-col gap-3">
                  <div className="aspect-[9/16] rounded-input overflow-hidden bg-paper3 relative">
                    {rec.actor_url
                      ? <img src={rec.actor_url} alt="" className="w-full h-full object-cover" />
                      : <div className="w-full h-full flex items-center justify-center text-muted"><Play size={24} /></div>}
                    <span className={`absolute top-2 left-2 ${s.cls} flex items-center gap-1`}>
                      {s.spin && <Loader2 size={10} className="animate-spin" />}{t(s.key)}
                    </span>
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm text-ink truncate">{rec.title || '—'}</p>
                    <p className="readout mt-0.5">
                      {rec.created_at ? new Date(rec.created_at).toLocaleString() : ''}
                      {rec.cost_estimate?.total ? ` · $${rec.cost_estimate.total}` : ''}
                    </p>
                    {rec.status === 'failed' && rec.error && (
                      <p className="text-xs text-danger mt-1 flex items-start gap-1"><AlertCircle size={12} className="shrink-0 mt-0.5" />{rec.error}</p>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2 mt-auto">
                    {rec.status === 'completed' && rec.video_url && (
                      <>
                        <button onClick={() => setViewing(rec)} className="btn-quiet py-1.5 px-3 text-xs"><Play size={12} /> {t('Open')}</button>
                        <a href={rec.video_url} download className="btn-quiet py-1.5 px-3 text-xs"><Download size={12} /> {t('Download')}</a>
                      </>
                    )}
                    {(rec.status === 'failed' || rec.status === 'interrupted') && (
                      <button onClick={() => retry(rec)} className="btn-quiet py-1.5 px-3 text-xs"><RefreshCw size={12} /> {t('Retry')}</button>
                    )}
                    <button onClick={() => remove(rec.job_id)} className="btn-danger py-1.5 px-3 text-xs"><Trash2 size={12} /> {t('Delete')}</button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {viewing && <ViewerModal rec={viewing} onClose={() => setViewing(null)} t={t} />}
    </div>
  );
}

function ViewerModal({ rec, onClose, t }) {
  const [copied, setCopied] = useState('');
  const copy = (field, text) => { navigator.clipboard.writeText(text || ''); setCopied(field); setTimeout(() => setCopied(''), 1500); };
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div className="card max-w-md w-full max-h-[90vh] overflow-y-auto custom-scrollbar p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display text-lg text-ink truncate">{rec.title}</h2>
          <button onClick={onClose} className="text-muted hover:text-ink"><X size={18} /></button>
        </div>
        <video src={rec.video_url} controls className="w-full rounded-input bg-black mb-4" />
        {rec.caption && (
          <div className="mb-3">
            <div className="flex items-center justify-between"><span className="eyebrow">{t('Caption')}</span>
              <button onClick={() => copy('cap', rec.caption)} className="btn-quiet py-1 px-2 text-xs">{copied === 'cap' ? <Check size={11} /> : <Copy size={11} />}</button></div>
            <p className="text-xs text-ink2 mt-1 leading-relaxed">{rec.caption}</p>
          </div>
        )}
        {rec.hashtags?.length > 0 && (
          <div className="mb-3">
            <div className="flex items-center justify-between"><span className="eyebrow">{t('Hashtags')}</span>
              <button onClick={() => copy('tags', rec.hashtags.join(' '))} className="btn-quiet py-1 px-2 text-xs">{copied === 'tags' ? <Check size={11} /> : <Copy size={11} />}</button></div>
            <p className="text-xs text-brass mt-1">{rec.hashtags.join(' ')}</p>
          </div>
        )}
        <div className="flex items-center justify-between text-xs text-muted">
          <span>{t('Cost')}: ${rec.cost_estimate?.total ?? '—'}</span>
          <a href={rec.video_url} download className="btn-quiet py-1.5 px-3"><Download size={12} /> {t('Download')}</a>
        </div>
      </div>
    </div>
  );
}
