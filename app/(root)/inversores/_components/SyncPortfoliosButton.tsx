'use client';

import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { syncInvestorPortfoliosNow } from '@/lib/actions/investors.actions';
import { useT } from '@/lib/i18n/client';

const AUTO_SYNC_MIN_INTERVAL_MS = 6 * 60 * 60 * 1000;

// Interactivo (estado + server action en onClick): no puede ser servidor.
export function SyncPortfoliosButton({
    label,
    queuedText,
}: {
    label?: string;
    queuedText?: string;
}) {
    const t = useT();
    const [state, setState] = useState<'idle' | 'syncing' | 'queued' | 'error'>('idle');

    const handleSync = async () => {
        setState('syncing');
        let success = false;
        try {
            const result = await syncInvestorPortfoliosNow();
            success = Boolean(result.success);
            if (success) {
                try {
                    window.localStorage.setItem('sync-13f-last-auto', String(Date.now()));
                } catch {
                    // Ignorar error al acceder a localStorage (ej. modo incógnito)
                }
            }
        } catch {
            success = false;
        } finally {
            // Un rechazo de la server action no puede dejar el botón en
            // «Encolando…» para siempre: el estado final se fija aquí.
            setState(success ? 'queued' : 'error');
        }
        return success;
    };

    // Estado vacío: primer uso sin datos encola la sincronización una vez; si ya
    // se intentó hace menos de 6 h (cualquier pantalla) no se repite.
    useEffect(() => {
        const key = 'sync-13f-last-auto';
        try {
            const last = Number(window.localStorage.getItem(key));
            if (Number.isFinite(last) && Date.now() - last < AUTO_SYNC_MIN_INTERVAL_MS) return;
        } catch {
            return;
        }
        // Auto-sync al montar: el setState de handleSync no es síncrono
        // dentro del efecto.
        queueMicrotask(() => void handleSync());
    }, []);

    const loading = state === 'syncing';
    return (
        <div className="flex flex-col items-center gap-3">
            <Button
                onClick={handleSync}
                disabled={loading || state === 'queued'}
                aria-busy={loading}
                className="gap-2"
            >
                <RefreshCw aria-hidden="true" className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                {loading ? t('investors.sync.syncing') : (label ?? t('investors.sync.label'))}
            </Button>
            {state === 'queued' ? (
                <p className="text-sm text-teal-300">{queuedText ?? t('investors.sync.queued')}</p>
            ) : null}
            {state === 'error' ? (
                <p className="text-sm text-red-400">{t('investors.sync.error')}</p>
            ) : null}
        </div>
    );
}
