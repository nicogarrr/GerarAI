'use client';

import { useState } from 'react';
import { Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useT } from '@/lib/i18n/client';
import { deleteKnowledgeDocument } from '@/lib/actions/research-tools.actions';

// Interactivo (confirmación + estado + server action en onClick): no puede ser servidor.
export function DeleteDocumentButton({ documentId, title, className }: { documentId: number; title: string; className?: string }) {
    const t = useT();
    const [state, setState] = useState<'idle' | 'deleting' | 'error'>('idle');
    const [confirmOpen, setConfirmOpen] = useState(false);

    const handleDelete = async () => {
        setState('deleting');
        const result = await deleteKnowledgeDocument(documentId);
        setState(result.success ? 'idle' : 'error');
    };

    return (
        <span className="inline-flex flex-col items-end gap-1">
            <Button
                aria-label={t('knowledge.delete.documentAria', { title })}
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
                title={t('knowledge.delete.confirmTitle', { title })}
                description={t('knowledge.delete.confirmDescription')}
                onConfirm={handleDelete}
            />
        </span>
    );
}
