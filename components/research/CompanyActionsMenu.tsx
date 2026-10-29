'use client';

import Link from 'next/link';
import { MoreHorizontal } from 'lucide-react';

import { GuideBrainButton } from '@/components/research/GuideBrainButton';
import { DecisionJournalEntryLink } from '@/components/research/DecisionJournalEntryLink';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

const ITEM = 'flex min-h-[44px] items-center text-sm text-teal-300 hover:text-teal-200';

/** Enlaces secundarios de la ficha en un único menú de cabecera (antes seis enlaces sueltos). */
export default function CompanyActionsMenu({ ticker, changeCount }: { ticker: string; changeCount: number }) {
    const t = encodeURIComponent(ticker);
    return (
        <Popover>
            <PopoverTrigger asChild>
                <button
                    aria-label="Más acciones"
                    className="flex size-11 items-center justify-center rounded-lg text-gray-300 hover:text-teal-300"
                    type="button"
                >
                    <MoreHorizontal aria-hidden="true" className="h-5 w-5" />
                </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="max-h-[min(75dvh,34rem)] w-60 overflow-y-auto border-gray-700 bg-gray-900 p-2">
                <nav aria-label="Enlaces de la empresa" className="flex flex-col">
                    <GuideBrainButton ticker={ticker} />
                    <Link className={ITEM} href={`/research/${t}?view=seguimiento`}>
                        Qué ha cambiado{changeCount ? ` (${changeCount})` : ''}
                    </Link>
                    <DecisionJournalEntryLink className={ITEM} ticker={ticker} />
                    <p className="mt-1 border-t border-gray-700/60 px-0 pb-0.5 pt-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Análisis profundo</p>
                    <Link className={ITEM} href={`/research/${t}?view=finanzas#terminal`}>Terminal financiero</Link>
                    <Link className={ITEM} href={`/research/${t}?view=valoracion#supuestos`}>Supuestos de drivers</Link>
                    <Link className={ITEM} href={`/research/${t}?view=seguimiento#lecciones`}>Lecciones de decisiones</Link>
                    <Link className={ITEM} href={`/research/${t}?view=seguimiento#directiva`}>Credibilidad de la directiva</Link>
                    <Link className={ITEM} href={`/research/${t}?view=finanzas#dilucion`}>Dilución y recompras</Link>
                    <p className="mt-1 border-t border-gray-700/60 px-0 pb-0.5 pt-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Señales externas</p>
                    <Link className={ITEM} href={`/research/${t}/shorts`}>Cortos públicos</Link>
                    <Link className={ITEM} href={`/research/news?ticker=${t}`}>Noticias</Link>
                    <Link className={ITEM} href={`/insider?ticker=${t}`}>Insiders</Link>
                    <Link className={ITEM} href={`/corporate-actions?ticker=${t}`}>Dividendos y splits</Link>
                </nav>
            </PopoverContent>
        </Popover>
    );
}
