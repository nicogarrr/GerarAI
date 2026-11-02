'use client';

import { useState } from 'react';
import { Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useT } from '@/lib/i18n/client';

/**
 * Borrado de la biblioteca con confirmación, compartido por
 * DeleteDocumentButton y DeleteCollectionButton (eran dos copias exactas
 * salvo la server action y las claves i18n). La mutación SOLO corre al
 * confirmar; ningún click borra en silencio.
 */
export function DeleteKnowledgeButton({
    ariaLabel,
    confirmTitle,
    confirmDescription,
    onDelete,
    className,
}: {
    ariaLabel: string;
    confirmTitle: string;
    confirmDescription: string;
    onDelete: () => Promise<{ success: boolean }>;
    className?: string;
}) {
    const t = useT();
    const [state, setState] = useState<'idle' | 'deleting' | 'error'>('idle');
    const [confirmOpen, setConfirmOpen] = useState(false);

    const handleDelete = async () => {
        setState('deleting');
        const result = await onDelete();
        setState(result.success ? 'idle' : 'error');
    };

    return (
        <span className="inline-flex flex-col items-end gap-1">
            <Button
                aria-label={ariaLabel}
                className={className}
                disabled={state === 'deleting'}
                onClick={() => setConfirmOpen(true)}
                size="sm"
                type="button"
                variant="outline"
            >
                <Trash2 aria-hidden="true" className="h-4 w-4" />
                {state === 'deleting' ? t('knowledge.delete.deleting') : t('common.actions.delete')}
            </Button>
            {state === 'error' ? (
                <span className="text-xs text-red-400" role="alert">{t('knowledge.delete.error')}</span>
            ) : null}
            <ConfirmDialog
                open={confirmOpen}
                onOpenChange={setConfirmOpen}
                title={confirmTitle}
                description={confirmDescription}
                onConfirm={handleDelete}
            />
        </span>
    );
}
