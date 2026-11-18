'use client';

import { useRef, useState } from 'react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { deleteSotpResult } from '@/lib/actions/sotp.actions';
import { useT } from '@/lib/i18n/client';

/**
 * Borrado del desglose SOTP con el mismo contrato que el resto de borrados:
 * el botón visible solo abre el diálogo y la mutación no corre hasta que se
 * confirma. El formulario mantiene su aviso de error en línea.
 */
export function DeleteSotpResultButton({ ticker }: { ticker: string }) {
    const t = useT();
    const [confirmOpen, setConfirmOpen] = useState(false);
    const submitRef = useRef<HTMLButtonElement>(null);

    return (
        <>
            <Button type="button" variant="outline" className="w-fit" onClick={() => setConfirmOpen(true)}>
                {t('research.sotp.delete')}
            </Button>
            <MutationForm action={deleteSotpResult.bind(null, ticker)} className="mt-3" successMessage={t('research.sotp.deleted')}>
                <Button ref={submitRef} type="submit" className="sr-only" tabIndex={-1} aria-hidden="true">
                    {t('research.sotp.delete')}
                </Button>
            </MutationForm>
            <ConfirmDialog
                open={confirmOpen}
                onOpenChange={setConfirmOpen}
                title={t('research.sotp.deleteConfirmTitle')}
                description={t('research.sotp.deleteConfirmDescription')}
                onConfirm={() => submitRef.current?.click()}
            />
        </>
    );
}
