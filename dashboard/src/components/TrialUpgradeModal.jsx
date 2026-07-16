import React, { useState, useEffect } from 'react';
import { X, Loader2, Rocket, CheckCircle2 } from 'lucide-react';
import { apiJson } from '../lib/api';

// Shown when a TRIALING user hits the trial minute cap. Lets them end the trial
// and activate the paid plan right away (charges the card now, unlocks the full
// monthly minutes). The subscription webhook flips status→active server-side.
export default function TrialUpgradeModal({ plan, onActivated, onClose }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const [planMinutes, setPlanMinutes] = useState(null);

  // Look up the full monthly minutes for the current plan (to show what unlocks).
  useEffect(() => {
    apiJson('/api/billing/plans')
      .then((d) => {
        const match = (d.plans || []).find((p) => p.plan === plan && p.interval === 'month');
        if (match) setPlanMinutes(match.minutes);
      })
      .catch(() => {});
  }, [plan]);

  const activate = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await apiJson('/api/billing/end-trial', { method: 'POST' });
      // Poll /api/me until the webhook flips the subscription to active.
      let ok = res?.status === 'active';
      for (let i = 0; i < 10 && !ok; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const me = await onActivated();
        ok = me?.status === 'active';
      }
      if (ok) {
        setDone(true);
        setTimeout(onClose, 1800);
      } else {
        // Charge is processing (or card needs attention) — let them proceed anyway.
        await onActivated();
        setError('Almost there — your plan is activating. If it doesn\'t unlock in a minute, check your billing details.');
      }
    } catch (e) {
      setError('Could not activate your plan. Please try again or manage billing from your account.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-surface border border-white/10 rounded-2xl p-8 w-full max-w-md relative">
        <button onClick={onClose} className="absolute right-4 top-4 text-zinc-400 hover:text-white"><X size={20} /></button>

        {done ? (
          <div className="text-center py-4">
            <div className="inline-flex p-3 bg-green-500/20 rounded-full text-green-400 mb-4"><CheckCircle2 size={24} /></div>
            <h2 className="text-xl font-bold mb-1">You're all set 🎉</h2>
            <p className="text-zinc-400 text-sm">Your plan is active{planMinutes ? ` with ${planMinutes} minutes` : ''}. Go ahead and generate your clips.</p>
          </div>
        ) : (
          <>
            <div className="inline-flex p-3 bg-primary/20 rounded-full text-primary mb-4"><Rocket size={24} /></div>
            <h2 className="text-xl font-bold mb-1">You've used your free trial minutes</h2>
            <p className="text-zinc-400 text-sm mb-6">
              Activate your{plan ? <> <span className="capitalize font-semibold text-white">{plan}</span></> : ''} plan now to unlock{' '}
              {planMinutes ? <><b className="text-white">{planMinutes} minutes</b> every month</> : 'your full monthly minutes'} and keep creating.
              Your card is charged today and your 3-day trial ends now.
            </p>

            {error && <p className="text-amber-400 text-xs mb-4">{error}</p>}

            <button
              onClick={activate}
              disabled={busy}
              className="w-full btn-primary py-3 flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {busy ? <><Loader2 size={18} className="animate-spin" /> Activating…</> : <>Activate my plan now</>}
            </button>
            <button
              onClick={onClose}
              disabled={busy}
              className="w-full mt-2 text-zinc-400 hover:text-white text-sm py-2 disabled:opacity-60"
            >
              Maybe later
            </button>
          </>
        )}
      </div>
    </div>
  );
}
