'use client';

import { useState } from 'react';
import { Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { deleteKnowledgeCollection } from '@/lib/actions/research-tools.actions';

// Interactivo (confirmación + estado + server action en onClick): no puede ser servidor.
export function DeleteCollectionButton({ collectionId, name, className }: { collectionId: number; name: string; className?: string }) {
    const [state, setState] = useState<'idle' | 'deleting' | 'error'>('idle');
    const [confirmOpen, setConfirmOpen] = useState(false);

    const handleDelete = async () => {
        setState('deleting');
        const result = await deleteKnowledgeCollection(collectionId);
        setState(result.success ? 'idle' : 'error');
    };

    return (
        <span className="inline-flex flex-col items-end gap-1">
            <Button
                aria-label={`Eliminar colección: ${name}`}
                className={className}
                disabled={state === 'deleting'}
                onClick={() => setConfirmOpen(true)}
                size="sm"
                type="button"
                variant="outline"
            >
                <Trash2 aria-hidden="true" className="h-4 w-4" />
                {state === 'deleting' ? 'Eliminando...' : 'Eliminar'}
            </Button>
            {state === 'error' ? (
                <span className="text-xs text-red-400" role="alert">No se pudo eliminar. Inténtalo de nuevo.</span>
            ) : null}
            <ConfirmDialog
                open={confirmOpen}
                onOpenChange={setConfirmOpen}
                title={`¿Eliminar la colección vacía «${name}»?`}
                description="Esta acción no se puede deshacer."
                onConfirm={handleDelete}
            />
        </span>
    );
}
