'use client';

import { useT } from '@/lib/i18n/client';
import { deleteKnowledgeDocument } from '@/lib/actions/research-tools.actions';

import { DeleteKnowledgeButton } from './DeleteKnowledgeButton';

// Interactivo (confirmación + estado + server action): no puede ser servidor.
// La lógica vive en DeleteKnowledgeButton; aquí solo la identidad del documento.
export function DeleteDocumentButton({ documentId, title, className }: { documentId: number; title: string; className?: string }) {
    const t = useT();
    return (
        <DeleteKnowledgeButton
            ariaLabel={t('knowledge.delete.documentAria', { title })}
            className={className}
            confirmDescription={t('knowledge.delete.confirmDescription')}
            confirmTitle={t('knowledge.delete.confirmTitle', { title })}
            onDelete={() => deleteKnowledgeDocument(documentId)}
        />
    );
}
