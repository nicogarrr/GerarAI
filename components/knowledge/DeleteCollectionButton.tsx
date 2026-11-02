'use client';

import { useT } from '@/lib/i18n/client';
import { deleteKnowledgeCollection } from '@/lib/actions/research-tools.actions';

import { DeleteKnowledgeButton } from './DeleteKnowledgeButton';

// Interactivo (confirmación + estado + server action): no puede ser servidor.
// La lógica vive en DeleteKnowledgeButton; aquí solo la identidad de la colección.
export function DeleteCollectionButton({ collectionId, name, className }: { collectionId: number; name: string; className?: string }) {
    const t = useT();
    return (
        <DeleteKnowledgeButton
            ariaLabel={t('knowledge.delete.collectionAria', { name })}
            className={className}
            confirmDescription={t('knowledge.delete.confirmCollectionDescription')}
            confirmTitle={t('knowledge.delete.confirmCollectionTitle', { name })}
            onDelete={() => deleteKnowledgeCollection(collectionId)}
        />
    );
}
