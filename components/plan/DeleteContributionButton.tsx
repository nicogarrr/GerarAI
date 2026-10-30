'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { deletePlanContribution } from '@/lib/actions/plan.actions';

/** Borra una aportación registrada por error, con confirmación. */
export default function DeleteContributionButton({ contributionId, label }: { contributionId: number; label: string }) {
    const router = useRouter();
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [state, setState] = useState<'idle' | 'deleting' | 'error'>('idle');

    const handleDelete = async () => {
        setState('deleting');
        const result = await deletePlanContribution(contributionId);
        if (!result.ok) {
            setState('error');
            return;
        }
        setState('idle');
        router.refresh();
    };

    return (
        <span className="inline-flex flex-col items-end gap-1">
            <Button
                type="button"
                variant="outline"
                size="sm"
                className="min-h-[44px]"
                aria-label={`Eliminar aportación: ${label}`}
                disabled={state === 'deleting'}
                onClick={() => setConfirmOpen(true)}
            >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                {state === 'deleting' ? 'Eliminando…' : 'Eliminar'}
            </Button>
            {state === 'error' ? <span role="alert" className="text-xs text-red-400">No se pudo eliminar. Inténtalo de nuevo.</span> : null}
            <ConfirmDialog
                open={confirmOpen}
                onOpenChange={setConfirmOpen}
                title={`¿Eliminar la aportación ${label}?`}
                description="Se borra solo este registro del plan. No toca tu cartera ni tus movimientos."
                onConfirm={handleDelete}
            />
        </span>
    );
}
