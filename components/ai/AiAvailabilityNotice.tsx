'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getAiAvailability, type AiAvailability, type AiFeature } from '@/lib/actions/ai-availability.actions';
import { useT } from '@/lib/i18n/client';

export function useAiAvailability(feature: AiFeature) {
    const [status, setStatus] = useState<AiAvailability | null>(null);
    const [failed, setFailed] = useState(false);
    const [checking, setChecking] = useState(true);
    const request = useRef(0);
    const refresh = useCallback(async () => {
        const seq = ++request.current;
        setChecking(true);
        try {
            const next = await getAiAvailability(feature);
            if (seq === request.current) { setStatus(next); setFailed(false); }
            return seq === request.current && next.can_start;
        } catch {
            if (seq === request.current) { setStatus(null); setFailed(true); }
            return false;
        } finally {
            if (seq === request.current) setChecking(false);
        }
    }, [feature]);
    useEffect(() => {
        void refresh();
        return () => { request.current += 1; };
    }, [refresh]);
    return { status, failed, checking, canStart: !checking && status?.can_start === true, refresh };
}

export function AiAvailabilityNotice({ availability }: { availability: ReturnType<typeof useAiAvailability> }) {
    const t = useT();
    const { status, checking, failed, refresh } = availability;
    const labels = {
        checking: 'brain.aiAvailability.checking', unknown: 'brain.aiAvailability.unknown',
        off: 'brain.aiAvailability.off', paused: 'brain.aiAvailability.paused',
        degraded: 'brain.aiAvailability.degraded', unverified: 'brain.aiAvailability.unverified',
    } as const;
    const key = checking ? 'checking' : failed ? 'unknown' : status?.state ?? 'unknown';
    return <div className="w-full rounded-md border border-amber-800/50 bg-amber-950/20 px-3 py-2 text-xs leading-5 text-amber-100">
        <p role="status" aria-live="polite">{t(labels[key])}</p>
        {status?.state === 'paused' && status.retry_after_seconds ? <p>{t('brain.aiAvailability.wait', { seconds: status.retry_after_seconds })}</p> : null}
        <p className="mt-1 text-amber-100/70">{t('brain.aiAvailability.localOnly')}</p>
        <button type="button" disabled={checking} className="mt-1 underline underline-offset-2 disabled:opacity-50" onClick={() => { void refresh(); }}>{t('brain.aiAvailability.refresh')}</button>
    </div>;
}
