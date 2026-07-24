import React from 'react';

const KIND = {
  th:    { cls: 'bg-zinc-600 border-zinc-500 text-zinc-100', label: '🗣' },
  ai:    { cls: 'bg-violet-600 border-violet-400 text-white', label: 'AI' },
  image: { cls: 'bg-sky-600 border-sky-400 text-white', label: '📷' },
  video: { cls: 'bg-amber-500 border-amber-300 text-black', label: '🎬' },
};

function slotKind(seg) {
  if (seg.visual !== 'broll') return 'th';
  const s = seg.broll_source || 'ai';
  return ['ai', 'image', 'video'].includes(s) ? s : 'ai';
}

export default function BrollTimeline({ script, onSlotClick, activeSeg = null, t = (x) => x }) {
  const segments = script?.segments || [];
  const total = script?.duration_seconds
    || segments.reduce((m, s) => Math.max(m, s.end || 0), 0) || 1;

  return (
    <div className="rounded-xl border border-rule bg-black/40 p-3">
      <div className="flex text-[10px] text-muted mb-1 pl-14">
        {[0, 0.25, 0.5, 0.75, 1].map((f, i) => (
          <span key={i} className="flex-1">{Math.round(total * f)}s</span>
        ))}
      </div>
      <div className="flex items-stretch mb-1.5">
        <div className="w-14 shrink-0 text-[10px] text-muted uppercase flex items-center justify-end pr-2">
          {t('Video')}
        </div>
        <div className="flex-1 flex gap-[3px] h-9">
          {segments.map((seg, i) => {
            const kind = slotKind(seg);
            const meta = KIND[kind];
            const grow = Math.max(0.5, (seg.end - seg.start));
            const clickable = seg.visual === 'broll';
            const active = activeSeg === i;
            return (
              <button
                key={i}
                type="button"
                disabled={!clickable}
                onClick={() => clickable && onSlotClick(i)}
                style={{ flexGrow: grow, flexBasis: 0 }}
                className={`rounded-md border text-[10px] font-semibold flex flex-col items-center justify-center overflow-hidden px-1 ${meta.cls} ${clickable ? 'cursor-pointer hover:brightness-110' : 'cursor-default'} ${active ? 'ring-2 ring-white' : ''}`}
                title={seg.type || kind}
              >
                <span>{meta.label}</span>
                <span className="text-[8px] font-normal opacity-80 truncate max-w-full">{seg.type}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex items-stretch">
        <div className="w-14 shrink-0 text-[10px] text-muted uppercase flex items-center justify-end pr-2">
          {t('Voice')}
        </div>
        <div className="flex-1 h-6 rounded-md border border-slate-600 bg-slate-800 text-[9px] text-sky-300 flex items-center justify-center">
          🔊 {t('Voiceover — continuous')}
        </div>
      </div>
      <div className="flex gap-3 flex-wrap text-[10px] text-muted mt-2 pl-14">
        <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-zinc-600 mr-1 align-[-1px]" />{t('Head')}</span>
        <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-violet-600 mr-1 align-[-1px]" />{t('AI b-roll')}</span>
        <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-sky-600 mr-1 align-[-1px]" />{t('My photo')}</span>
        <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-amber-500 mr-1 align-[-1px]" />{t('My video')}</span>
      </div>
    </div>
  );
}
