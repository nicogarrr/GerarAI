'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { CheckCheck, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { approveThesis } from '@/lib/actions/thesis-jobs.actions';
import { showErrorToast } from '@/lib/toast';
import { preserveScrollPosition } from '@/lib/utils/scroll-anchor';
import { isNextRedirectError } from '@/lib/types/errors';
import { toast } from 'sonner';

/** Estados desde los que el backend rechaza publicar (409): no hay nada
 *  aprobable. Mismo criterio que NON_APPROVABLE_STATUSES del backend. */
const NON_APPROVABLE: Record<string, string> = {
    insufficient_data: 'datos insuficientes',
    draft_failed_audit: 'no superó la auditoría de fuentes',
};

/**
 * Aprobacion manual de la ultima tesis (POST /thesis/{ticker}/approve).
 * La aprobacion automatica por Telegram queda documentada como futura:
 * este boton es hoy la unica via que cambia el estado.
 *
 * Flujo honesto: publicar una version ya publicada o no aprobable solo
 * producia un 409; el boton ahora lo impide y lo explica. El aviso
 * confirma tambien el indexado en la Biblioteca tal como lo devuelve el
 * backend (knowledge_sync), sin suponerlo.
 */
export default function ThesisApproveButton({
    ticker,
    disabled = false,
    latestStatus = null,
    latestVersion = null,
}: {
    ticker: string;
    /** Sin versiones de tesis no hay nada que aprobar/rechazar (B17). */
    disabled?: boolean;
    /** Estado de la ultima version; gobierna si "Aprobar" tiene sentido. */
    latestStatus?: string | null;
    /** Numero de la ultima version, para nombrarla en la explicacion. */
    latestVersion?: number | null;
}) {
    const router = useRouter();
    const [pending, setPending] = useState<'approved' | 'rejected' | null>(null);

    const alreadyPublished = latestStatus === 'published';
    const notApprovableReason = latestStatus ? NON_APPROVABLE[latestStatus] : undefined;
    const approveBlocked = disabled || alreadyPublished || notApprovableReason !== undefined;
    const blockNote = disabled
        ? 'Sin versiones de tesis que aprobar o rechazar.'
        : alreadyPublished
          ? `La v${latestVersion ?? '?'} ya está publicada.`
          : notApprovableReason !== undefined
            ? `La v${latestVersion ?? '?'} no se puede publicar: ${notApprovableReason}.`
            : null;

    const decide = async (decision: 'approved' | 'rejected') => {
        setPending(decision);
        try {
            const result = await approveThesis(ticker, decision);
            if (result.decision === 'approved') {
                const sync = result.knowledge_sync?.status;
                if (sync === 'indexed') {
                    toast.success(`Tesis v${result.version} aprobada y añadida a la Biblioteca`);
                } else if (sync === 'unchanged') {
                    toast.success(`Tesis v${result.version} aprobada; ya estaba en la Biblioteca`);
                } else if (sync === 'failed') {
                    toast.warning(`Tesis v${result.version} aprobada, pero no se pudo indexar en la Biblioteca`);
                } else {
                    toast.success(`Tesis v${result.version} aprobada`);
                }
            } else {
                toast.success(
                    result.knowledge_sync?.status === 'removed'
                        ? `Tesis v${result.version} rechazada y retirada de la Biblioteca`
                        : `Tesis v${result.version} rechazada`,
                );
            }
            // F391: sin refresh el memo y el historial siguen mostrando el estado anterior.
            // El ancla de scroll se conserva: el lector no pierde su sitio.
            preserveScrollPosition(() => router.refresh());
        } catch (exc) {
            if (isNextRedirectError(exc)) throw exc;
            showErrorToast(exc, { onRetry: () => decide(decision) });
        } finally {
            setPending(null);
        }
    };

    return (
        <div
            className="flex flex-wrap items-center gap-2"
            title="Aprobación manual. La aprobación automática por Telegram es una mejora futura."
        >
            <Button
                type="button"
                size="sm"
                // F288: sin versiones (disabled) el primario casi blanco al 50%
                // de opacidad seguia siendo lo mas luminoso de la vista y se
                // leia como accion principal activa. Deshabilitado se rinde
                // como outline (claramente secundario) + leyenda visible.
                variant={approveBlocked ? 'outline' : 'default'}
                onClick={() => decide('approved')}
                disabled={approveBlocked || pending !== null}
                aria-busy={pending !== null}
            >
                <CheckCheck aria-hidden="true" className="mr-2 h-4 w-4" />
                {pending === 'approved' ? 'Aprobando…' : 'Aprobar tesis'}
            </Button>
            <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => decide('rejected')}
                disabled={disabled || pending !== null}
                aria-busy={pending !== null}
            >
                <XCircle aria-hidden="true" className="mr-2 h-4 w-4" />
                {pending === 'rejected' ? 'Rechazando…' : 'Rechazar'}
            </Button>
            {blockNote ? (
                <span className="text-xs text-gray-500">{blockNote}</span>
            ) : null}
        </div>
    );
}
