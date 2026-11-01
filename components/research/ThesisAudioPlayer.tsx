'use client';

import { useCallback, useEffect, useState } from 'react';
import { Headphones, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useT } from '@/lib/i18n/client';

type AudioState = 'loading' | 'ready' | 'pending' | 'missing' | 'unpublished' | 'error';

/**
 * Escuchar la tesis: `<audio controls>` con el mp3 ya generado. Si no existe,
 * un botón lo pide; mientras se genera se consulta el estado cada 5 s.
 * Nunca se pinta un reproductor sin audio detrás.
 */
export default function ThesisAudioPlayer({ ticker, version }: { ticker: string; version: number | null }) {
    const t = useT();
    const base = `/api/thesis/${encodeURIComponent(ticker)}/audio`;
    const query = version === null ? '' : `?version=${version}`;
    const [state, setState] = useState<AudioState>('loading');
    const [requesting, setRequesting] = useState(false);
    const [pollCycle, setPollCycle] = useState(0);

    const refresh = useCallback(async (): Promise<AudioState> => {
        try {
            const res = await fetch(`${base}/status${query}`, { cache: 'no-store' });
            const body = (await res.json()) as { state?: AudioState; hasKey?: boolean };
            if (body.state === 'missing' && body.hasKey === false) return 'unpublished';
            return body.state && ['ready', 'pending', 'missing', 'error'].includes(body.state) ? body.state : 'error';
        } catch {
            return 'error';
        }
    }, [base, query]);

    useEffect(() => {
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const tick = async () => {
            const next = await refresh();
            if (cancelled) return;
            setState(next);
            if (next === 'pending') timer = setTimeout(tick, 5000);
        };
        void tick();
        return () => {
            cancelled = true;
            if (timer) clearTimeout(timer);
        };
    }, [refresh, version, pollCycle]);

    async function generate() {
        setRequesting(true);
        try {
            const res = await fetch(`${base}${query}`, { method: 'POST' });
            setState(res.ok ? 'pending' : 'error');
            // El sondeo inicial acaba en missing/error. Reiniciarlo tras el POST
            // permite llegar a ready sin tener que recargar la página.
            if (res.ok) setPollCycle(cycle => cycle + 1);
        } catch {
            setState('error');
        } finally {
            setRequesting(false);
        }
    }

    return (
        <div aria-label={t('research.thesisAudio.group')} className="flex flex-wrap items-center gap-3" role="group">
            <span className="inline-flex items-center gap-2 text-sm font-medium text-gray-200">
                <Headphones className="h-4 w-4" />{t('research.thesisAudio.group')}
            </span>
            {state === 'ready' ? (
                <audio className="h-10 max-w-full" controls key={version ?? 'latest'} onError={() => setState('error')} preload="none" src={`${base}${query}`} />
            ) : state === 'pending' ? (
                <span className="inline-flex items-center gap-2 text-sm text-gray-400" role="status">
                    <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />{t('research.thesisAudio.generating')}
                </span>
            ) : state === 'missing' ? (
                <Button disabled={requesting} onClick={generate} type="button" variant="outline">{t('research.thesisAudio.generate')}</Button>
            ) : state === 'unpublished' ? (
                <span className="text-sm text-gray-400">{t('research.thesisAudio.unpublished')}</span>
            ) : state === 'error' ? (
                <>
                    <span className="text-sm text-red-300">{t('research.thesisAudio.failed')}</span>
                    <Button disabled={requesting} onClick={generate} type="button" variant="outline">{t('research.thesisAudio.retry')}</Button>
                </>
            ) : null}
        </div>
    );
}
