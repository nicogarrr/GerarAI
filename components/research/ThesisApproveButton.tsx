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
 * producia un 409; el boton ahora lo impide y lo explica. Tras publicar,
 * el boton cambia de estado visual: deshabilitado y «Publicada vX», para
 * que la vista no siga ofreciendo una accion que ya no existe. El aviso
 * confirma tambien el indexado en la Biblioteca tal como lo devuelve el
 * backend (knowledge_sync), sin suponerlo.
 */
export default function ThesisApproveButton({
    ticker,
    disabled = false,
    latestStatus = null,
    latestVersion = null,
    riskNotes = [],
    olderPublishedVersion = null,
}: {
    ticker: string;
    /** Sin versiones de tesis no hay nada que aprobar/rechazar (B17). */
    disabled?: boolean;
    /** Estado de la ultima version; gobierna si "Aprobar" tiene sentido. */
    latestStatus?: string | null;
    /** Numero de la ultima version, para nombrarla en la explicacion. */
    latestVersion?: number | null;
    /** Motivos por los que publicar esta versión merece una confirmación explícita. */
    riskNotes?: string[];
    /** Versión publicada anterior (si existe): rechazar la última no la retira. */
    olderPublishedVersion?: number | null;
}) {
    const router = useRouter();
    const [pending, setPending] = useState<'approved' | 'rejected' | null>(null);
    const [confirming, setConfirming] = useState(false);

    const alreadyPublished = latestStatus === 'published';
    const notApprovableReason = latestStatus ? NON_APPROVABLE[latestStatus] : undefined;
    const approveBlocked = disabled || alreadyPublished || notApprovableReason !== undefined;
    // Con la version ya publicada el estado lo dice el propio boton
    // («Publicada vX»): una leyenda al lado repetiria lo mismo.
    const blockNote = disabled
        ? 'Sin versiones de tesis que aprobar o rechazar.'
        : alreadyPublished
          ? null
          : notApprovableReason !== undefined
            ? `La v${latestVersion ?? '?'} no se puede publicar: ${notApprovableReason}.`
            : null;

    const decide = async (decision: 'approved' | 'rejected', confirmed = false) => {
        // Publicar una tesis con valoración parcial, datos pendientes o red team
        // bajo exige una confirmación explícita con los motivos a la vista.
        if (decision === 'approved' && riskNotes.length > 0 && !confirmed) {
            setConfirming(true);
            return;
        }
        setConfirming(false);
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
                if (olderPublishedVersion !== null) {
                    toast.info(`La v${olderPublishedVersion} sigue publicada: rechazar solo afecta a la última versión.`);
                }
            }
            // F391: sin refresh el memo y el historial siguen mostrando el estado anterior.
            // El ancla de scroll se conserva: el lector no pierde su sitio.
            preserveScrollPosition(() => router.refresh());
        } catch (exc) {
            if (isNextRedirectError(exc)) throw exc;
            showErrorToast(exc, { onRetry: () => decide(decision, confirmed) });
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
                {pending === 'approved'
                    ? 'Aprobando…'
                    : alreadyPublished
                      ? `Publicada v${latestVersion ?? '?'}`
                      : 'Aprobar tesis'}
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
            {confirming ? (
                <div role="alert" className="w-full rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200">
                    <p className="font-medium">Esta tesis aún no es una valoración final:</p>
                    <ul className="mt-1 list-disc pl-5">
                        {riskNotes.map((note) => (
                            <li key={note}>{note}</li>
                        ))}
                    </ul>
                    <p className="mt-2 text-xs text-amber-300/80">
                        Al publicarla pasa a la Biblioteca y el Cerebro la usará como referencia.
                    </p>
                    <div className="mt-2 flex gap-2">
                        <Button type="button" size="sm" onClick={() => decide('approved', true)} disabled={pending !== null}>
                            Publicar igualmente
                        </Button>
                        <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(false)}>
                            Cancelar
                        </Button>
                    </div>
                </div>
            ) : null}
        </div>
    );
}
