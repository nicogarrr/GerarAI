'use client';

import { useCallback, useEffect, useState } from 'react';
import { Headphones, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';

type AudioState = 'loading' | 'ready' | 'pending' | 'missing' | 'error';

/**
 * Escuchar la tesis: `<audio controls>` con el mp3 ya generado. Si no existe,
 * un botón lo pide; mientras se genera se consulta el estado cada 5 s.
 * Nunca se pinta un reproductor sin audio detrás.
 */
export default function ThesisAudioPlayer({ ticker, version }: { ticker: string; version: number }) {
    const base = `/api/thesis/${encodeURIComponent(ticker)}/audio`;
    const [state, setState] = useState<AudioState>('loading');
    const [requesting, setRequesting] = useState(false);

    const refresh = useCallback(async (): Promise<AudioState> => {
        try {
            const res = await fetch(`${base}/status`, { cache: 'no-store' });
            const body = (await res.json()) as { state?: AudioState };
            return body.state && ['ready', 'pending', 'missing', 'error'].includes(body.state) ? body.state : 'error';
        } catch {
            return 'error';
        }
    }, [base]);

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
    }, [refresh, version]);

    async function generate() {
        setRequesting(true);
        try {
            const res = await fetch(base, { method: 'POST' });
            setState(res.ok ? 'pending' : 'error');
        } catch {
            setState('error');
        } finally {
            setRequesting(false);
        }
    }

    return (
        <div aria-label="Escuchar la tesis" className="flex flex-wrap items-center gap-3" role="group">
            <span className="inline-flex items-center gap-2 text-sm font-medium text-gray-200">
                <Headphones className="h-4 w-4" />Escuchar la tesis
            </span>
            {state === 'ready' ? (
                <audio className="h-10 max-w-full" controls key={version} onError={() => setState('error')} preload="none" src={`${base}?v=${version}`} />
            ) : state === 'pending' ? (
                <span className="inline-flex items-center gap-2 text-sm text-gray-400" role="status">
                    <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />Generando audio…
                </span>
            ) : state === 'missing' ? (
                <Button disabled={requesting} onClick={generate} type="button" variant="outline">Generar audio</Button>
            ) : state === 'error' ? (
                <>
                    <span className="text-sm text-red-300">No se pudo generar el audio.</span>
                    <Button disabled={requesting} onClick={generate} type="button" variant="outline">Reintentar</Button>
                </>
            ) : null}
        </div>
    );
}
