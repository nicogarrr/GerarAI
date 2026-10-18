'use client';

import { BookOpen } from 'lucide-react';

/**
 * «Guía de investigación» de la ficha: la guía vive en el Cerebro. Abre el
 * panel con el ticker de la ficha ya puesto en el selector (modo guía).
 */
export function GuideBrainButton({ ticker }: { ticker: string }) {
    return (
        <button
            type="button"
            onClick={() => window.dispatchEvent(new CustomEvent('gerarai:open-brain', { detail: { ticker } }))}
            className="inline-flex min-h-[44px] items-center gap-1 text-teal-300 transition hover:text-teal-200 sm:min-h-0"
        >
            <BookOpen className="h-4 w-4" />Guía de investigación
        </button>
    );
}
