'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { OPEN_BRAIN_PENDING_KEY, type OpenBrainDetail } from '@/lib/brain/open-brain';

/**
 * Redirect del antiguo /research/assistant: la página ya no existe como tal,
 * la guía es el Cerebro. Deja el detalle en sessionStorage ANTES de navegar
 * (el Cerebro montado en el layout lo recoge sin carrera de efectos) y
 * lleva a la ficha del ticker o a /research.
 */
export function AssistantRedirect({ ticker, reviewId }: { ticker?: string; reviewId?: number }) {
    const router = useRouter();
    useEffect(() => {
        const detail: OpenBrainDetail = { ...(ticker ? { ticker } : {}), ...(reviewId ? { review_id: reviewId } : {}) };
        try {
            window.sessionStorage.setItem(OPEN_BRAIN_PENDING_KEY, JSON.stringify(detail));
        } catch {
            // Sin almacenamiento disponible: se navega igual y el Cerebro no se abre solo.
        }
        router.replace(ticker ? `/research/${encodeURIComponent(ticker)}` : '/research');
    }, [router, ticker, reviewId]);
    const href = ticker ? `/research/${encodeURIComponent(ticker)}` : '/research';
    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-1 py-4 sm:px-4 sm:py-6">
            <p className="text-sm text-gray-400">
                La guía de investigación ahora vive en el Cerebro.{' '}
                <Link className="text-teal-300 underline underline-offset-2 hover:text-teal-200" href={href}>Continuar</Link>
            </p>
        </main>
    );
}
