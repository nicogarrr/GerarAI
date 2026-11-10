'use client';

import { BookOpen } from 'lucide-react';
import { openBrain } from '@/lib/brain/open-brain';
import { markEarlyOpenHydrated } from '@/lib/early-open';

/**
 * «Guía de investigación» de la ficha: la guía vive en el Cerebro. Abre el
 * panel con el ticker de la ficha ya puesto en el selector (modo guía).
 */
export function GuideBrainButton({ ticker }: { ticker: string }) {
    return (
        <button
            type="button"
            ref={markEarlyOpenHydrated}
            data-early-open="brain"
            data-early-open-detail={JSON.stringify({ ticker })}
            onClick={() => openBrain({ ticker })}
            className="inline-flex min-h-[44px] items-center gap-1 text-teal-300 transition hover:text-teal-200 sm:min-h-0"
        >
            <BookOpen className="h-4 w-4" />Guía de investigación
        </button>
    );
}
