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
import { useT } from '@/lib/i18n/client';

/** Estados desde los que el backend rechaza publicar (409): no hay nada
 *  aprobable. Mismo criterio que NON_APPROVABLE_STATUSES del backend. */
const NON_APPROVABLE = {
    insufficient_data: 'research.thesisApprove.reason.insufficientData',
    draft_failed_audit: 'research.thesisApprove.reason.failedAudit',
} as const;

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
    const t = useT();
    const [pending, setPending] = useState<'approved' | 'rejected' | null>(null);
    const [confirming, setConfirming] = useState(false);

    const alreadyPublished = latestStatus === 'published';
    const notApprovableKey = latestStatus && Object.hasOwn(NON_APPROVABLE, latestStatus) ? NON_APPROVABLE[latestStatus as keyof typeof NON_APPROVABLE] : undefined;
    const notApprovableReason = notApprovableKey ? t(notApprovableKey) : undefined;
    const approveBlocked = disabled || alreadyPublished || notApprovableReason !== undefined;
    // Con la version ya publicada el estado lo dice el propio boton
    // («Publicada vX»): una leyenda al lado repetiria lo mismo.
    const blockNote = disabled
        ? t('research.thesisApprove.noVersions')
        : alreadyPublished
          ? null
          : notApprovableReason !== undefined
            ? t('research.thesisApprove.cannotPublish', { version: latestVersion ?? '?', reason: notApprovableReason })
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
                    toast.success(t('research.thesisApprove.approvedIndexed', { version: result.version }));
                } else if (sync === 'unchanged') {
                    toast.success(t('research.thesisApprove.approvedUnchanged', { version: result.version }));
                } else if (sync === 'failed') {
                    toast.warning(t('research.thesisApprove.approvedIndexFailed', { version: result.version }));
                } else {
                    toast.success(t('research.thesisApprove.approved', { version: result.version }));
                }
            } else {
                toast.success(
                    result.knowledge_sync?.status === 'removed'
                        ? t('research.thesisApprove.rejectedRemoved', { version: result.version })
                        : t('research.thesisApprove.rejected', { version: result.version }),
                );
                if (olderPublishedVersion !== null) {
                    toast.info(t('research.thesisApprove.olderStillPublished', { version: olderPublishedVersion }));
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
            title={t('research.thesisApprove.manualTitle')}
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
                    ? t('research.thesisApprove.approving')
                    : alreadyPublished
                      ? t('research.thesisApprove.published', { version: latestVersion ?? '?' })
                      : t('research.thesisApprove.approve')}
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
                {pending === 'rejected' ? t('research.thesisApprove.rejecting') : t('research.thesisApprove.reject')}
            </Button>
            {blockNote ? (
                <span className="text-xs text-gray-500">{blockNote}</span>
            ) : null}
            {confirming ? (
                <div role="alert" className="w-full rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200">
                    <p className="font-medium">{t('research.thesisApprove.notFinal')}</p>
                    <ul className="mt-1 list-disc pl-5">
                        {riskNotes.map((note) => (
                            <li key={note}>{note}</li>
                        ))}
                    </ul>
                    <p className="mt-2 text-xs text-amber-300/80">
                        {t('research.thesisApprove.publishEffect')}
                    </p>
                    <div className="mt-2 flex gap-2">
                        <Button type="button" size="sm" onClick={() => decide('approved', true)} disabled={pending !== null}>
                            {t('research.thesisApprove.publishAnyway')}
                        </Button>
                        <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(false)}>
                            {t('research.thesisApprove.cancel')}
                        </Button>
                    </div>
                </div>
            ) : null}
        </div>
    );
}
