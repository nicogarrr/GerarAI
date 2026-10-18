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

/**
 * Aprobacion manual de la ultima tesis (POST /thesis/{ticker}/approve).
 * La aprobacion automatica por Telegram queda documentada como futura:
 * este boton es hoy la unica via que cambia el estado.
 */
export default function ThesisApproveButton({
    ticker,
    disabled = false,
}: {
    ticker: string;
    /** Sin versiones de tesis no hay nada que aprobar/rechazar (B17). */
    disabled?: boolean;
}) {
    const router = useRouter();
    const [pending, setPending] = useState<'approved' | 'rejected' | null>(null);

    const decide = async (decision: 'approved' | 'rejected') => {
        setPending(decision);
        try {
            const result = await approveThesis(ticker, decision);
            toast.success(
                result.decision === 'approved'
                    ? `Tesis v${result.version} aprobada`
                    : `Tesis v${result.version} rechazada`,
            );
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
                variant={disabled ? 'outline' : 'default'}
                onClick={() => decide('approved')}
                disabled={disabled || pending !== null}
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
            {disabled ? (
                <span className="text-xs text-gray-500">Sin versiones de tesis que aprobar o rechazar.</span>
            ) : null}
        </div>
    );
}
