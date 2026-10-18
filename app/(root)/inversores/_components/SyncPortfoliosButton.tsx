'use client';

import { useState } from 'react';
import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { syncInvestorPortfoliosNow } from '@/lib/actions/investors.actions';

// Interactivo (estado + server action en onClick): no puede ser servidor.
export function SyncPortfoliosButton({
    label = 'Sincronizar carteras ahora',
    queuedText = 'Sincronización en curso; recarga la página en unos minutos para ver las carteras.',
}: {
    label?: string;
    queuedText?: string;
}) {
    const [state, setState] = useState<'idle' | 'syncing' | 'queued' | 'error'>('idle');

    const handleSync = async () => {
        setState('syncing');
        const result = await syncInvestorPortfoliosNow();
        setState(result.success ? 'queued' : 'error');
    };

    const loading = state === 'syncing';
    return (
        <div className="flex flex-col items-center gap-3">
            <Button
                onClick={handleSync}
                disabled={loading || state === 'queued'}
                aria-busy={loading}
                className="gap-2 bg-teal-600 text-white hover:bg-teal-700"
            >
                <RefreshCw aria-hidden="true" className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                {loading ? 'Encolando sincronización...' : label}
            </Button>
            {state === 'queued' ? (
                <p className="text-sm text-teal-300">{queuedText}</p>
            ) : null}
            {state === 'error' ? (
                <p className="text-sm text-red-400">No se pudo encolar la sincronización. Inténtalo de nuevo.</p>
            ) : null}
        </div>
    );
}
