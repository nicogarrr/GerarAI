'use client';

import { useState, useTransition } from 'react';
import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { syncOwnershipManagers } from '@/lib/actions/ownership.actions';

export default function SyncButton() {
    const [pending, startTransition] = useTransition();
    const [feedback, setFeedback] = useState<string | null>(null);
    return (
        <div className="space-y-2">
            <Button
                size="sm"
                variant="ghost"
                className="text-gray-400"
                disabled={pending}
                onClick={() => startTransition(async () => {
                    setFeedback(null);
                    try {
                        const result = await syncOwnershipManagers();
                        const failed = result.results.filter((r) => r.status !== 'ok');
                        if (failed.length === 0) {
                            setFeedback('Sincronización completada.');
                        } else {
                            const reason = failed[0]?.reason?.split('\n')[0] ?? 'error desconocido';
                            setFeedback(`No se pudo sincronizar ${failed[0]?.manager ?? 'el gestor'}: ${reason}`);
                        }
                    } catch {
                        setFeedback('No se pudo completar la sincronización. Inténtalo de nuevo.');
                    }
                })}
            >
                <RefreshCw className={`h-4 w-4 ${pending ? 'animate-spin' : ''}`} />
                {pending ? 'Sincronizando…' : 'Sincronizar 13F'}
            </Button>
            {feedback ? <p className="text-xs text-amber-300">{feedback}</p> : null}
        </div>
    );
}
