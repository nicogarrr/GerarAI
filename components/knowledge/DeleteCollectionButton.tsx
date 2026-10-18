'use client';

import { useState } from 'react';
import { Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { deleteKnowledgeCollection } from '@/lib/actions/research-tools.actions';

// Interactivo (confirmación + estado + server action en onClick): no puede ser servidor.
export function DeleteCollectionButton({ collectionId, name, className }: { collectionId: number; name: string; className?: string }) {
    const [state, setState] = useState<'idle' | 'deleting' | 'error'>('idle');

    const handleDelete = async () => {
        if (!window.confirm(`¿Eliminar la colección vacía «${name}»? Esta acción no se puede deshacer.`)) return;
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
                onClick={handleDelete}
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
        </span>
    );
}
